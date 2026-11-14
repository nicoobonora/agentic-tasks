"""Generic discussion API; the optional charging data app has its own OpenAPI."""
import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import os
from . import discussion as engine
from . import models as m
from .db import transaction, documents
from .errors import Conflict
from .providers import settings

async def worker():
    while True:
        try:
            with transaction() as db:
                ids = [r['id'] for r in documents(db, engine.KIND) if r['state'] == 'running']
            for run_id in ids:
                await asyncio.to_thread(engine.step, run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            import logging
            logging.exception('Discussion worker iteration failed; pending runs remain persisted')
        await asyncio.sleep(.2)

@asynccontextmanager
async def lifespan(app):
    job = asyncio.create_task(worker())
    yield
    job.cancel()
    try:
        await job
    except asyncio.CancelledError:
        pass

app = FastAPI(title='Task Discussion API', version='2.0.0', lifespan=lifespan,
              description='Submit any task, discuss, clarify, and deliver a versioned proposal. No execution.')
app.add_middleware(CORSMiddleware, allow_origins=os.getenv('ACS_CORS_ORIGINS', 'http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173').split(','),
                   allow_methods=['GET','POST'], allow_headers=['Content-Type','Last-Event-ID'])

@app.exception_handler(Conflict)
async def conflict_handler(request, exc):
    return JSONResponse(status_code=exc.status, content={'code': exc.code, 'message': exc.message})

@app.exception_handler(RequestValidationError)
async def validation_handler(request, exc):
    return JSONResponse(status_code=422, content={'code': 'validation_error', 'message': str(exc)})

ERRORS = {404: {'model': m.Error}, 409: {'model': m.Error}, 422: {'model': m.Error}, 503: {'model': m.Error}}

@app.get('/api/v2/health', response_model=m.Health)
def health():
    conf = settings()
    return {'model_configured': bool(conf['key'] and conf['model']), 'model': conf['model'], 'default_max_rounds': conf['max_rounds']}

@app.post('/api/v2/runs', response_model=m.Run, status_code=202, responses=ERRORS)
def create_run(body: m.CreateRun):
    return engine.create(body)

@app.get('/api/v2/runs/{run_id}', response_model=m.Run, responses=ERRORS)
def read_run(run_id: str):
    with transaction() as db:
        return engine.load(db, run_id)

@app.get('/api/v2/runs/{run_id}/evidence', response_model=list[m.Evidence], responses=ERRORS)
def evidence(run_id: str):
    return read_run(run_id).evidence

@app.post('/api/v2/runs/{run_id}/answers', response_model=m.Run, responses=ERRORS)
def answer(run_id: str, body: m.Answer):
    return engine.command(run_id, 'answer', body)

@app.post('/api/v2/runs/{run_id}/approve', response_model=m.Run, responses=ERRORS)
def approve(run_id: str, body: m.Approval):
    return engine.command(run_id, 'approve', body)

@app.post('/api/v2/runs/{run_id}/retry', response_model=m.Run, responses=ERRORS)
def retry(run_id: str, body: m.Command):
    return engine.command(run_id, 'retry', body)

@app.get('/api/v2/runs/{run_id}/events', responses=ERRORS, response_class=StreamingResponse)
async def events(run_id: str, request: Request, after: int = Query(0, ge=0), once: bool = False):
    read_run(run_id)
    try:
        cursor = max(after, int(request.headers.get('Last-Event-ID', '0')))
    except ValueError:
        raise Conflict('invalid_cursor', 'Last-Event-ID must be an integer')
    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            with transaction() as db:
                rows = db.execute('SELECT * FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT 100', (run_id,cursor)).fetchall()
            for row in rows:
                cursor = row['sequence']
                event = m.StreamEvent(sequence=cursor, run_id=run_id, data=json.loads(row['payload']))
                yield f'id: {cursor}\nevent: snapshot\ndata: {event.model_dump_json()}\n\n'
            if once:
                break
            yield ': heartbeat\n\n'
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

# A separate sub-application keeps charging-specific schemas out of the generic contract.
from .examples.charging.api import app as charging_app
app.mount('/examples/charging', charging_app)
