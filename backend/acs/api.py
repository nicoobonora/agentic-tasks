"""Generic discussion API; the optional charging data app has its own OpenAPI."""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import os
from .config import load_environment

load_environment()

from . import discussion as engine
from . import models as m
from .db import transaction
from .errors import Conflict
from .providers import settings

def running_ids():
    with transaction() as db:
        return [row['id'] for row in db.execute(
            """SELECT d.id FROM documents d LEFT JOIN discussion_leases l ON l.run_id=d.id
               WHERE d.kind=? AND json_extract(d.payload, '$.state')='running'
               AND (l.run_id IS NULL OR l.expires_at<=?)
               ORDER BY json_extract(d.payload, '$.updated_at'), d.id""",
            (engine.KIND, time.time()))]


def event_batch(run_id, cursor):
    with transaction() as db:
        return db.execute('SELECT * FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT 100',
                          (run_id, cursor)).fetchall()


def worker_concurrency():
    return max(1, min(32, int(os.getenv('ACS_WORKER_CONCURRENCY', '4'))))


async def worker(concurrency=None):
    concurrency = concurrency or worker_concurrency()
    pending = {}

    async def turn(run_id):
        try:
            await asyncio.to_thread(engine.step, run_id)
        except Exception:
            logging.exception('Discussion turn failed for run %s', run_id)

    try:
        while True:
            pending = {ident: task for ident, task in pending.items() if not task.done()}
            try:
                ids = await asyncio.to_thread(running_ids)
                for run_id in ids:
                    if len(pending) >= concurrency:
                        break
                    if run_id not in pending:
                        pending[run_id] = asyncio.create_task(turn(run_id))
            except Exception:
                logging.exception('Discussion worker iteration failed; pending runs remain persisted')
            await asyncio.sleep(.2)
    finally:
        # Cancelling to_thread does not stop its thread. Drain owned turns before
        # shutdown so a graceful stop cannot leave untracked database writers.
        await asyncio.gather(*pending.values())

@asynccontextmanager
async def lifespan(app):
    # Reject malformed configuration at startup, not in a detached worker.
    concurrency = worker_concurrency()
    settings()
    job = asyncio.create_task(worker(concurrency))
    try:
        yield
    finally:
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
    await asyncio.to_thread(read_run, run_id)
    try:
        cursor = max(after, int(request.headers.get('Last-Event-ID', '0')))
    except ValueError:
        raise Conflict('invalid_cursor', 'Last-Event-ID must be an integer')
    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            rows = await asyncio.to_thread(event_batch, run_id, cursor)
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
