"""Real ODH adapter: bounded windows, resumable immutable pages, UTC normalization."""
import gzip
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from .db import ROOT

CONFIG = json.loads((ROOT / "config/sources.json").read_text())

def utc(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp without timezone: {value}")
    return dt.astimezone(timezone.utc)

def stamp(value):
    return utc(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def windows(start, end, days=90):
    if not 0 < days <= 100 or start >= end:
        raise ValueError("Expected start < end and windows of 1..100 days")
    while start < end:
        stop = min(start + timedelta(days=days), end)
        yield start, stop
        start = stop

def source_filter(source, network=False):
    names = CONFIG["sites"] + CONFIG["context_sites"]
    terms = [f'pname.eq.{json.dumps(n)}' for n in names]
    if network:
        terms.append("scoordinate.bbi.(" + ",".join(map(str, CONFIG["network_bbox"])) + ")")
    return f'and(sorigin.eq.{json.dumps(source)},or({",".join(terms)}))'

class ODHClient:
    def __init__(self, db, raw_dir=None, client=None):
        self.db = db
        self.raw_dir = Path(raw_dir or ROOT / "data/raw")
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.client = client or httpx.Client(timeout=90, follow_redirects=True)

    @staticmethod
    def storage_path(path):
        return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)

    def page(self, path, params, kind, refresh=False):
        url = str(httpx.URL(CONFIG["base_url"] + path, params=params))
        key = digest(url)
        # Cache is per exact query. Live calls must request refresh=True.
        manifest = self.raw_dir / f"{key}.json"
        if manifest.exists() and not refresh:
            meta = json.loads(manifest.read_text())
            raw = gzip.decompress((self.raw_dir / meta["filename"]).read_bytes())
            if hashlib.sha256(raw).hexdigest() != meta["sha256"]:
                raise ValueError(f"Corrupt cache: {manifest}")
        else:
            for attempt in range(4):
                try:
                    response = self.client.get(url)
                    if response.status_code == 429 or response.status_code >= 500:
                        response.raise_for_status()
                    response.raise_for_status()
                    raw = response.content
                    body = json.loads(raw)
                    if not isinstance(body.get("data"), list):
                        raise ValueError("Unexpected ODH envelope")
                    break
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code == 429 or exc.response.status_code >= 500
                    if not retryable or attempt == 3:
                        raise
                    time.sleep(min(60, max(2 ** attempt, float(exc.response.headers.get("Retry-After", 0))) if isinstance(exc, httpx.HTTPStatusError) else 2 ** attempt))
            sha = hashlib.sha256(raw).hexdigest()
            meta = {"url": url, "sha256": sha, "acquired_at": now(), "filename": f"{sha}.json.gz", "kind": kind}
            (self.raw_dir / meta["filename"]).write_bytes(gzip.compress(raw, mtime=0))
            temp = manifest.with_suffix(".tmp")
            temp.write_text(json.dumps(meta, indent=2))
            temp.replace(manifest)
        body = json.loads(raw)
        page_id = digest(meta["url"] + meta["sha256"] + meta["acquired_at"])
        self.db.execute("INSERT OR IGNORE INTO source_pages VALUES (?,?,?,?,?,?,?)", (
            page_id, meta["url"], meta["acquired_at"], meta["sha256"],
            self.storage_path(self.raw_dir / meta["filename"]), len(body["data"]), kind))
        return body["data"], page_id

    def pages(self, path, params, kind, refresh=False):
        offset = 0
        while True:
            rows, page_id = self.page(path, {**params, "limit": CONFIG["page_size"], "offset": offset}, kind, refresh)
            yield rows, page_id
            self.db.commit()  # Completed pages survive failures and can be resumed.
            if len(rows) < CONFIG["page_size"]:
                break
            offset += len(rows)

    def metadata(self, source, network=False):
        for rows, page_id in self.pages("/flat/EChargingPlug", {"where": source_filter(source, network), "sort": "scode"}, "metadata"):
            for row in rows:
                site = {"id": row["pcode"], "name": row["pname"], "source": source,
                        "coordinates": row.get("pcoordinate"), "metadata": row.get("pmetadata", {}),
                        "origin": "real", "evidence_id": page_id}
                plug = {"id": row["scode"], "site_id": row["pcode"], "name": row["sname"], "source": source,
                        "connectors": row.get("smetadata", {}).get("connectors", []), "origin": "real", "evidence_id": page_id}
                self.db.execute("INSERT OR REPLACE INTO sites VALUES (?,?,?,?)", (site["id"], site["name"], source, json.dumps(site)))
                self.db.execute("INSERT OR REPLACE INTO plugs VALUES (?,?,?,?)", (plug["id"], site["id"], source, json.dumps(plug)))

    def observations(self, source, start=None, end=None, network=False, latest=False):
        path = "/flat/EChargingPlug/" + CONFIG["data_type"]
        ranges = [(None, None)] if latest else windows(start, end, CONFIG["window_days"])
        count = 0
        for a, b in ranges:
            suffix = "/latest" if latest else f'/{a.strftime("%Y-%m-%dT%H:%M:%S")}/{b.strftime("%Y-%m-%dT%H:%M:%S")}'
            params = {"where": source_filter(source, network), "select": "scode,mvalidtime,mvalue,mtransactiontime,mperiod", "sort": "mvalidtime,scode,mtransactiontime"}
            for rows, page_id in self.pages(path + suffix, params, "latest" if latest else "history", refresh=latest):
                for row in rows:
                    observed = stamp(row["mvalidtime"])
                    transaction = stamp(row.get("mtransactiontime", row["mvalidtime"]))
                    status = str(row["mvalue"])
                    ident = digest(json.dumps([row["scode"], observed, transaction, status]))
                    self.db.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)", (ident, row["scode"], observed, transaction, status, page_id))
                    self.db.execute("INSERT OR IGNORE INTO observation_pages VALUES (?,?)", (ident, page_id))
                    count += 1
                print(f"{source}: {count} rows, window {a or 'latest'}, offset page {page_id[:8]}", flush=True)
        return count
