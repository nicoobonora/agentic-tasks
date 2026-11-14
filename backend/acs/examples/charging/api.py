import gzip
import json
import os
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from ...db import ROOT, transaction, documents, get
from ...ingestion import ODHClient, now, utc, digest
from . import models as m
from . import catalog as catalog_data

app = FastAPI(title="ChargeCo ACS Foundation", version="1.0.0", description="Strumenti dati ODH e catalogo simulato dell’esempio opzionale; nessuna orchestrazione o esecuzione.")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("ACS_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173").split(","), allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Last-Event-ID"])

@app.exception_handler(catalog_data.Conflict)
async def conflict_handler(request, exc):
    return JSONResponse(status_code=404 if exc.code == "not_found" else 409, content={"code": exc.code, "message": exc.message, "details": None})

@app.exception_handler(RequestValidationError)
async def validation_handler(request, exc):
    return JSONResponse(status_code=422, content={"code": "validation_error", "message": "Richiesta non valida", "details": json.loads(json.dumps(exc.errors(), default=str))})

ERRORS = {404: {"model": m.Error}, 409: {"model": m.Error}, 422: {"model": m.Error}}

@app.get("/api/v1/health", response_model=m.Health)
def health():
    with transaction() as db:
        return {"sites": db.execute("SELECT count(*) FROM sites").fetchone()[0], "plugs": db.execute("SELECT count(*) FROM plugs").fetchone()[0],
                "observations": db.execute("SELECT count(*) FROM observations").fetchone()[0], "normalized": get(db, "pipeline", "normalization") is not None}

@app.get("/api/v1/sites", response_model=list[m.Site])
def sites(source: str = "Neogy-AMPECO"):
    with transaction() as db:
        return [json.loads(r[0]) for r in db.execute("SELECT payload FROM sites WHERE source=? ORDER BY name,id", (source,))]

@app.get("/api/v1/plugs", response_model=list[m.Plug])
def plugs(site_id: str):
    with transaction() as db:
        return [json.loads(r[0]) for r in db.execute("SELECT payload FROM plugs WHERE site_id=? ORDER BY id", (site_id,))]

@app.get("/api/v1/observations", response_model=m.ObservationPage, responses=ERRORS)
def observations(plug_id: str, start: datetime | None = None, end: datetime | None = None, limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0)):
    where, args = "plug_id=?", [plug_id]
    for value in (start, end):
        catalog_data.require(value is None or value.tzinfo is not None, "invalid_time", "Usare timestamp con timezone")
    catalog_data.require(start is None or end is None or start < end, "invalid_interval", "start deve precedere end")
    for field, op in ((start, ">="), (end, "<")):
        if field:
            where += f" AND observed_at {op} ?"
            args.append(field.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"))
    with transaction() as db:
        total = db.execute(f"SELECT count(*) FROM observations WHERE {where}", args).fetchone()[0]
        items = [dict(r) for r in db.execute(f"SELECT * FROM observations WHERE {where} ORDER BY observed_at,transaction_at,id LIMIT ? OFFSET ?", (*args, limit, offset))]
        return {"items": items, "limit": limit, "offset": offset, "total": total}

@app.get("/api/v1/episodes", response_model=list[m.Episode])
def episodes(plug_id: str, limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0)):
    with transaction() as db:
        return [dict(r) for r in db.execute("SELECT * FROM episodes WHERE plug_id=? ORDER BY start,id LIMIT ? OFFSET ?", (plug_id, limit, offset))]

@app.get("/api/v1/quality", response_model=list[m.Quality])
def quality():
    with transaction() as db:
        return documents(db, "quality")

@app.get("/api/v1/evidence", response_model=list[m.Evidence])
def evidence_index(limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0)):
    with transaction() as db:
        return [evidence_row(r) for r in db.execute("SELECT * FROM source_pages ORDER BY acquired_at,id LIMIT ? OFFSET ?", (limit, offset))]

def evidence_row(row):
    result = dict(row)
    result.pop("path")
    result["raw_url"] = f"/examples/charging/api/v1/evidence/{row['id']}/raw"
    return result

@app.get("/api/v1/evidence/{evidence_id}", response_model=m.Evidence, responses=ERRORS)
def evidence(evidence_id: str):
    with transaction() as db:
        row = db.execute("SELECT * FROM source_pages WHERE id=?", (evidence_id,)).fetchone()
        if row is not None:
            return evidence_row(row)
        item = catalog_data.catalog_document(evidence_id) or get(db, "analysis", evidence_id)
        catalog_data.require(item is not None, "not_found", "Prova inesistente")
        return {"id": evidence_id, "url": "/examples/charging/api/v1/catalog" if evidence_id.startswith("catalog:") else "/examples/charging/api/v1/analysis", "acquired_at": item.get("generated_at"),
                "sha256": digest(json.dumps(item, sort_keys=True)), "row_count": 1,
                "kind": "catalog" if evidence_id.startswith("catalog:") else "analysis", "origin": item.get("origin", "derived"),
                "raw_url": f"/examples/charging/api/v1/evidence/{evidence_id}/raw"}

@app.get("/api/v1/evidence/{evidence_id}/raw", responses=ERRORS, response_class=Response)
def evidence_raw(evidence_id: str):
    with transaction() as db:
        row = db.execute("SELECT * FROM source_pages WHERE id=?", (evidence_id,)).fetchone()
        if row is None:
            item = catalog_data.catalog_document(evidence_id) or get(db, "analysis", evidence_id)
            catalog_data.require(item is not None, "not_found", "Prova inesistente")
            return Response(json.dumps(item, sort_keys=True), media_type="application/json")
        path = ROOT / row["path"]
        catalog_data.require(path.exists(), "not_found", "Copia raw non disponibile su questa macchina")
        return Response(gzip.decompress(path.read_bytes()), media_type="application/json")

@app.get("/api/v1/live", response_model=m.LiveData)
def live(refresh: bool = False):
    mode, warning = "snapshot", None
    with transaction() as db:
        if refresh:
            client = ODHClient(db)
            try:
                client.metadata("Neogy-AMPECO", network=True)
                client.observations("Neogy-AMPECO", network=True, latest=True)
                mode = "live"
            except Exception as exc:
                warning = f"Fonte non disponibile ({type(exc).__name__}); copia locale."
            finally:
                client.client.close()
        rows = db.execute("""SELECT o.* FROM observations o JOIN plugs p ON p.id=o.plug_id
            WHERE p.source='Neogy-AMPECO' AND o.id=(SELECT x.id FROM observations x WHERE x.plug_id=o.plug_id
            ORDER BY observed_at DESC,transaction_at DESC,id DESC LIMIT 1) ORDER BY plug_id""").fetchall()
        acquired = db.execute("SELECT max(acquired_at) FROM source_pages WHERE kind IN ('latest','history')").fetchone()[0]
        stale = not rows or any(datetime.now(timezone.utc) - utc(r["observed_at"]) > timedelta(hours=2) for r in rows)
        return {"mode": mode, "fetched_at": acquired, "stale": stale, "warning": warning, "items": [dict(r) for r in rows]}

@app.get("/api/v1/catalog", response_model=m.Catalog)
def catalog():
    return catalog_data.CATALOG

@app.get("/api/v1/analysis", response_model=list[m.AnalysisBundle])
def analysis():
    with transaction() as db:
        return documents(db, "analysis")


from ...models import Task, Attachment

@app.get('/task', response_model=Task)
def example_task():
    """Read-only example data tool: capture a compact snapshot as explicit task context."""
    with transaction() as db:
        sites = [json.loads(r[0]) for r in db.execute("SELECT payload FROM sites WHERE source='Neogy-AMPECO' ORDER BY name")]
        chosen = [s for s in sites if s['name'] in ('BZ_C_RISPARMIO_01','BZ_PIAVE_01','RENON_01')]
        payload = {'sites': chosen, 'analysis': documents(db, 'analysis'),
                   'notes': 'Metadata only unless analysis bundles are present. No hourly capacity or demand forecast is inferred here.'}
    return Task(title='Valutare un ampliamento della rete di ricarica',
        description='Proporre come valutare la richiesta di 12 nuovi punti in tre siti. Contestare le capacità non verificate, confrontare fattibilità e costi e identificare le decisioni da chiedere alla direzione. Non emettere ordini.',
        context='Operatore ChargeCo simulato, dati pubblici ODH. Il piano di partenza riguarda BZ_C_RISPARMIO_01, BZ_PIAVE_01 e RENON_01. Il dimensionamento non è una conclusione già verificata.',
        attachments=[Attachment(name='ODH snapshot and imported analysis',text=json.dumps(payload,ensure_ascii=False)),
                     Attachment(name='Simulated internal catalog',text=json.dumps(catalog_data.CATALOG,ensure_ascii=False))])
