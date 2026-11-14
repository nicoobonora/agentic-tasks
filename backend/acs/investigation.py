"""One bounded provider operation per short lease; durable same-role tool continuation."""
import json
import os
import time
from uuid import uuid4
from . import discussion as engine
from .db import transaction, get, put
from .capabilities import TurnProgress, ToolRequest, ToolCall, ToolOutcome
from .models import Error
from .providers import provider_for, ModelFailure
from .tools import reserve, complete, attach, artifact
from .jobs import enqueue

def limit(name,default,maximum):return max(1,min(maximum,int(os.getenv(name,str(default)))))

def output(db,run,call):
    result=artifact(db,run.id,call.artifact_id)
    data=result['outcome']
    value={'evidence_id':call.artifact_id,**data}
    from .profiles import get_profile
    value=get_profile(run.capability_profile).context(value)
    encoded=json.dumps(value)
    if len(encoded)>24000:
        value={'evidence_id':call.artifact_id,'status':data['status'],'summary':data['summary'],
               'limitations':data['limitations'],'detail_notice':'Result exceeds context bound; immutable detail available through scoped artifact endpoint.'}
    return {'type':'function_call_output','call_id':call.request.call_id,'output':json.dumps(value)}

def step(run_id,provider=None):
    from .profiles import get_profile
    lease_token=str(uuid4())
    with transaction() as db:
        db.execute('BEGIN IMMEDIATE')
        run=engine.load(db,run_id)
        if run.state!='running':return False
        lease=db.execute('SELECT * FROM discussion_leases WHERE run_id=?',(run_id,)).fetchone()
        if lease and lease['expires_at']>time.time():return False
        p=run.turn_progress
        if not p or (p.cycle,p.round,p.role,p.proposal_version)!=(run.cycle,run.round,run.next_role,run.proposal_version):
            p=TurnProgress(token=str(uuid4()),cycle=run.cycle,round=run.round,role=run.next_role,proposal_version=run.proposal_version,started_at=engine.now())
            run.turn_progress=p
        if p.pending_job_id:
            job=get(db,'analytical_job',p.pending_job_id)
            if job['status'] in ('queued','running'):return False
            call=ToolCall.model_validate(get(db,'tool_call',job['tool_call_id']))
            if attach(db,run,call):
                protocol=get(db,'turn_protocol',p.token) or []
                protocol.append(output(db,run,call));put(db,'turn_protocol',p.token,protocol)
            p.pending_job_id=None
            engine.save(db,run)
        if p.provider_requests>=limit('ACS_PROVIDER_REQUESTS',10,10) or (engine.now()-p.started_at).total_seconds()>1800:
            run.state='failed';run.error=Error(code='investigation_budget',message='Incomplete assessment: provider/time budget exhausted. Retry explicitly or supply a narrower goal.')
            engine.save(db,run);return True
        db.execute('INSERT OR REPLACE INTO discussion_leases VALUES (?,?,?)',(run_id,lease_token,time.time()+180))
        pending=get(db,'turn_requests',p.token) or []
        if not pending:
            p.provider_requests+=1
            run.provider_attempts=(run.provider_attempts or 0)+1
        engine.save(db,run)
    result=None;failure=None
    try:
        if not pending:
            result=(provider or provider_for(run)).generate(run,p.role,p.correction)
            with transaction() as db:
                db.execute('BEGIN IMMEDIATE')
                if not current(db,run,p,lease_token):return False
                measured=engine.load(db,run_id)
                for key,value in result.usage.items():measured.model_usage[key]=measured.model_usage.get(key,0)+value
                engine.save(db,measured)
            if result.requests:
                if len(result.requests)>8 or len({r.call_id for r in result.requests})!=len(result.requests):raise ValueError('Invalid tool call batch')
                pending=[r.model_dump(mode='json') for r in result.requests]
                with transaction() as db:
                    db.execute('BEGIN IMMEDIATE')
                    if not current(db,run,p,lease_token):return False
                    fresh=engine.load(db,run_id)
                    fresh.turn_progress.tool_requests+=len(result.requests)
                    if fresh.turn_progress.tool_requests>limit('ACS_TOOL_REQUESTS',8,8):
                        raise ModelFailure('tool_budget','Incomplete assessment: tool request budget exhausted')
                    engine.save(db,fresh)
                    protocol=get(db,'turn_protocol',p.token) or []
                    protocol.extend(result.protocol or [dict(type='function_call',call_id=r.call_id,name=r.name.replace('.','__'),arguments=json.dumps(r.arguments)) for r in result.requests])
                    put(db,'turn_protocol',p.token,protocol);put(db,'turn_requests',p.token,pending)
            else:
                engine.validate_turn(run,p.role,result.turn)
                p.correction=None
        while pending:
            request=ToolRequest.model_validate(pending[0])
            profile=get_profile(run.capability_profile)
            args=profile.normalize(request.name,request.arguments)
            with transaction() as db:
                db.execute('BEGIN IMMEDIATE')
                if not current(db,run,p,lease_token):return False
                run=engine.load(db,run_id);p=run.turn_progress
                call=reserve(db,run,request,args.model_dump(mode='json'),profile.snapshot(db),profile.id+'-tools-v'+profile.version)
                if request.name in profile.analytical_tools and not call.artifact_id:
                    count=db.execute("SELECT count(*) FROM documents WHERE kind='analytical_job' AND json_extract(payload,'$.run_id')=? AND json_extract(payload,'$.cycle')=?",(run.id,run.cycle)).fetchone()[0]
                    if count>=2 and not get(db,'analytical_job',call.id):raise ModelFailure('analytical_job_budget','At most two unique analytical jobs per cycle')
                    job=enqueue(db,call);p.pending_job_id=job.id
                    run.tool_activity=(run.tool_activity+[call])[-32:]
                    pending.pop(0);put(db,'turn_requests',p.token,pending)
                    engine.save(db,run)
                    db.execute('DELETE FROM discussion_leases WHERE run_id=?',(run_id,))
                    return True
                engine.save(db,run)
            if not call.artifact_id:
                with transaction() as db:
                    db.execute('BEGIN')
                    try:
                        outcome=profile.execute(db,run,request.name,args)
                    except Exception as exc:
                        outcome=ToolOutcome(status='error',summary='Tool execution failed: '+type(exc).__name__,source_fingerprint=call.source_fingerprint,method=request.name,queried_at=engine.now())
                    from .tools import digest
                    expected=digest(dict(tool=request.name,parameters=args.model_dump(mode='json'),source=outcome.source_fingerprint,version=profile.id+'-tools-v'+profile.version))
                    if outcome.method==request.name and expected!=call.cache_key:
                        raise ValueError('Source changed during tool execution; request a new calculation')
                with transaction() as db:
                    db.execute('BEGIN IMMEDIATE')
                    call=complete(db,call,outcome)
            with transaction() as db:
                db.execute('BEGIN IMMEDIATE')
                if not current(db,run,p,lease_token):return False
                run=engine.load(db,run_id);p=run.turn_progress
                attach(db,run,call)
                protocol=get(db,'turn_protocol',p.token) or [];protocol.append(output(db,run,call))
                put(db,'turn_protocol',p.token,protocol)
                pending.pop(0);put(db,'turn_requests',p.token,pending);engine.save(db,run)
            if not call.cached and call.status=='failed':
                failure=Error(code='tool_execution_error',message=call.summary);break
    except ModelFailure as exc: failure=Error(code=exc.code,message=str(exc))
    except ValueError as exc:
        if p.correction:failure=Error(code='invalid_model_output',message='Invalid structured output twice: '+str(exc)[:500])
        else:p.correction=str(exc)[:2000]
    except Exception as exc:failure=Error(code='investigation_error',message='Tool/provider execution failed: '+type(exc).__name__+'; retry explicitly.')
    with transaction() as db:
        db.execute('BEGIN IMMEDIATE')
        if not current(db,run,p,lease_token):return False
        run=engine.load(db,run_id)
        db.execute('DELETE FROM discussion_leases WHERE run_id=?',(run_id,))
        if failure:run.state='failed';run.error=failure
        elif result and result.turn and not p.correction:
            engine.apply_turn(run,p.role,result);run.turn_progress=None
        else:
            run.turn_progress.correction=p.correction
            if pending and p.correction:
                protocol=get(db,'turn_protocol',p.token) or []
                for request in pending:
                    protocol.append(dict(type='function_call_output',call_id=request['call_id'],output=json.dumps({'status':'error','reason':p.correction})))
                put(db,'turn_protocol',p.token,protocol)
                put(db,'turn_requests',p.token,[])
        engine.save(db,run)
    return True

def current(db,run,p,token):
    r=engine.load(db,run.id)
    lease=db.execute('SELECT * FROM discussion_leases WHERE run_id=?',(run.id,)).fetchone()
    return bool(lease and lease['token']==token and lease['expires_at']>time.time() and r.state=='running' and r.turn_progress and r.turn_progress.token==p.token and r.proposal_version==p.proposal_version and r.next_role==p.role)
