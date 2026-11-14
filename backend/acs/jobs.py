"""Durable numerical job queue. Inference runs in bounded subprocesses, not API threads."""
import asyncio
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from .capabilities import AnalyticalJob, ToolCall, ToolOutcome
from .db import transaction, get, put
from .tools import complete

JOB_MODULE = "scripts.execute_analytical_job"

def now(): return datetime.now(timezone.utc)

def lease_seconds(): return max(5,min(300,int(os.getenv('ACS_JOB_LEASE_SECONDS','60'))))

def enqueue(db,call):
    prior=get(db,'analytical_job',call.id)
    if prior: return AnalyticalJob.model_validate(prior)
    job=AnalyticalJob(id=call.id,tool_call_id=call.id,run_id=call.run_id,cycle=call.cycle,role=call.role,
        turn_token=call.turn_token,created_at=now(),deadline=now()+timedelta(minutes=20))
    put(db,'analytical_job',job.id,job.model_dump(mode='json'))
    return job

def claim(ident):
    with transaction() as db:
        db.execute('BEGIN IMMEDIATE')
        job=AnalyticalJob.model_validate(get(db,'analytical_job',ident))
        if job.status in ('succeeded','failed') or (job.lease_expires_at and job.lease_expires_at>now()):return None
        job.status='running';job.lease_token=str(uuid4());job.lease_expires_at=now()+timedelta(seconds=lease_seconds())
        put(db,'analytical_job',ident,job.model_dump(mode='json'))
        call=ToolCall.model_validate(get(db,'tool_call',job.tool_call_id))
        call.status='running';put(db,'tool_call',call.id,call.model_dump(mode='json'))
        from .discussion import load,save
        run=load(db,job.run_id)
        if run.turn_progress and run.turn_progress.token==job.turn_token and run.state=='running':
            run.tool_activity=([c for c in run.tool_activity if c.id!=call.id]+[call])[-32:]
            save(db,run)
        return job

def finish(job,error=None,result=None):
    with transaction() as db:
        db.execute('BEGIN IMMEDIATE')
        current=AnalyticalJob.model_validate(get(db,'analytical_job',job.id))
        if current.status!='running' or current.lease_token!=job.lease_token or not current.lease_expires_at or current.lease_expires_at<=now(): return
        call=ToolCall.model_validate(get(db,'tool_call',job.tool_call_id))
        if error:
            outcome=ToolOutcome(status='error',summary=error,source_fingerprint=call.source_fingerprint,method=call.request.name,
                                queried_at=now(),origin='derived_metric')
        else:
            outcome,publications=result
            from .tools import immutable
            for kind,ident,payload in publications:immutable(db,kind,ident,payload)
        call=complete(db,call,outcome)
        current.status='failed' if error else 'succeeded';current.error=error;current.artifact_id=call.artifact_id
        current.lease_expires_at=None
        put(db,'analytical_job',current.id,current.model_dump(mode='json'))

def execute(ident,token,predictor=None):
    with transaction() as db:
        job=AnalyticalJob.model_validate(get(db,'analytical_job',ident))
        if job.lease_token!=token:return
        call=ToolCall.model_validate(get(db,'tool_call',job.tool_call_id))
    try:
        from .profiles import get_profile
        from .discussion import load
        with transaction() as db:profile=get_profile(load(db,job.run_id).capability_profile)
        result=profile.execute_job(call,predictor=predictor)
        finish(job,result=result)
    except ImportError: finish(job,error='numerical_dependency_missing: install numerical dependencies explicitly')
    except Exception as exc: finish(job,error=f'analytical_execution_error: {type(exc).__name__}: {str(exc)[:300]}')

def queued():
    with transaction() as db:
        return [r[0] for r in db.execute("SELECT id FROM documents WHERE kind='analytical_job' AND json_extract(payload,'$.status') IN ('queued','running') ORDER BY id")]

def heartbeat(job):
    with transaction() as db:
        db.execute('BEGIN IMMEDIATE')
        value=get(db,'analytical_job',job.id)
        if not value or value['status']!='running' or value['lease_token']!=job.lease_token:return
        value['lease_expires_at']=(now()+timedelta(seconds=lease_seconds())).isoformat()
        put(db,'analytical_job',job.id,value)

async def worker():
    concurrency=max(1,min(4,int(os.getenv('ACS_NUMERICAL_CONCURRENCY','1'))))
    active={}
    try:
        while True:
            for ident,(process,job) in list(active.items()):
                if process.poll() is not None:
                    # Child normally publishes itself. A crash is never a synthetic forecast.
                    await asyncio.to_thread(finish,job,'numerical_process_failed: worker exited without result')
                    del active[ident]
                elif now()>job.deadline:
                    process.terminate();await asyncio.to_thread(process.wait)
                    await asyncio.to_thread(finish,job,'numerical_timeout: deadline exceeded')
                    del active[ident]
                else: await asyncio.to_thread(heartbeat,job)
            for ident in await asyncio.to_thread(queued):
                if len(active)>=concurrency:break
                if ident in active:continue
                job=await asyncio.to_thread(claim,ident)
                if job:
                    if now()>job.deadline:
                        await asyncio.to_thread(finish,job,'numerical_timeout: deadline exceeded before execution');continue
                    process=subprocess.Popen([sys.executable,'-m',JOB_MODULE,ident,job.lease_token],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    active[ident]=(process,job)
            await asyncio.sleep(1)
    finally:
        for process,job in active.values():
            process.terminate()
            try: await asyncio.to_thread(process.wait,timeout=5)
            except subprocess.TimeoutExpired:process.kill();await asyncio.to_thread(process.wait)
            await asyncio.to_thread(finish,job,'numerical_interrupted: server shutdown; explicit retry required')
