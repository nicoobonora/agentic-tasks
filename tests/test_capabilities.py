import pytest
from pydantic import ValidationError
from backend.acs.models import CreateRun
from backend.acs.capabilities import MetricReference, ToolOutcome
from backend.acs import discussion

def test_profile_additive_and_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv('ACS_DB', str(tmp_path/'test.sqlite'))
    body = dict(task=dict(title='Goal', description='Investigate'), mode='mock', idempotency_key='old')
    assert discussion.create(CreateRun(**body)).capability_profile is None
    body.update(capability_profile='charging', idempotency_key='new')
    run = discussion.create(CreateRun(**body))
    assert run.profile_version == '1'
    assert run.capability_profile == 'charging'
    with pytest.raises(ValidationError):
        CreateRun(**{**body, 'capability_profile': 'arbitrary'})

def test_metric_dates_and_extra_arguments():
    with pytest.raises(ValidationError):
        MetricReference(evidence_id='x', path='n', value=2, unit='points', site_id='s', start='yesterday', end='tomorrow')
    with pytest.raises(ValidationError):
        ToolOutcome(status='available', summary='', source_fingerprint='a', method='x', queried_at='2026-01-01T00:00:00Z', sql='drop')

def test_immutable_scoped_replay_and_stale_attachment(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from backend.acs.capabilities import TurnProgress, ToolRequest
    from backend.acs.db import transaction
    from backend.acs import tools
    from backend.acs.errors import Conflict
    monkeypatch.setenv('ACS_DB', str(tmp_path/'test.sqlite'))
    run = discussion.create(CreateRun(task=dict(title='Goal', description='Investigate'), mode='mock', capability_profile='charging', idempotency_key='a'))
    run.turn_progress = TurnProgress(token='turn', cycle=1, round=1, role='analyst', proposal_version=0, started_at=datetime.now(timezone.utc))
    request = ToolRequest(call_id='call', name='discovery', arguments={})
    with transaction() as db:
        db.execute('BEGIN IMMEDIATE')
        call = tools.reserve(db, run, request, {}, 'source-a', 'v1')
        assert tools.reserve(db, run, request, {}, 'source-a', 'v1').id == call.id
        with pytest.raises(Conflict):
            tools.reserve(db, run, request, {}, 'source-b', 'v1')
        outcome = ToolOutcome(status='unavailable', summary='No data', source_fingerprint='source-a', method='discovery', queried_at=datetime.now(timezone.utc))
        call = tools.complete(db, call, outcome)
        assert tools.complete(db, call, outcome).artifact_id == call.artifact_id
        assert tools.attach(db, run, call)
        assert tools.attach(db, run, call)
        assert len(run.evidence) == 2
        with pytest.raises(Conflict):
            tools.artifact(db, 'another-run', call.artifact_id)
        run.cycle += 1
        assert not tools.attach(db, run, call)

def test_job_duplicate_recovery_and_failure(tmp_path,monkeypatch):
    from backend.acs import jobs,tools
    from backend.acs.capabilities import TurnProgress,ToolRequest
    from backend.acs.db import transaction, get, put
    from datetime import timedelta
    monkeypatch.setenv('ACS_DB',str(tmp_path/'jobs.sqlite'))
    run=discussion.create(CreateRun(task=dict(title='a',description='b'),mode='mock',idempotency_key='job'))
    run.turn_progress=TurnProgress(token='t',cycle=1,round=1,role='analyst',proposal_version=0,started_at=jobs.now())
    with transaction() as db:
        call=tools.reserve(db,run,ToolRequest(call_id='c',name='forecast',arguments={}),{},'source','v1')
        job=jobs.enqueue(db,call)
        assert jobs.enqueue(db,call).id==job.id
    owned=jobs.claim(job.id)
    assert jobs.claim(job.id) is None
    future=jobs.now()+timedelta(seconds=181)
    monkeypatch.setattr(jobs,'now',lambda:future)
    recovered=jobs.claim(job.id)
    assert recovered.lease_token!=owned.lease_token
    jobs.finish(owned,error='late')
    jobs.finish(recovered,error='missing weights')
    with transaction() as db:
        assert get(db,'analytical_job',job.id)['error']=='missing weights'
        assert get(db,'tool_call',call.id)['status']=='failed'

def test_tool_loop_preserves_role_and_shared_evidence(tmp_path,monkeypatch):
    from backend.acs.providers import Result,MockProvider
    from backend.acs.capabilities import ToolRequest
    from backend.acs.db import transaction
    monkeypatch.setenv('ACS_DB',str(tmp_path/'loop.sqlite'))
    run=discussion.create(CreateRun(task=dict(title='Charging',description='Inspect sites'),mode='mock',capability_profile='charging',idempotency_key='loop'))
    class Controlled:
        calls=0
        def generate(self,run,role,correction=None):
            self.calls+=1
            if self.calls==1:return Result(requests=[ToolRequest(call_id='c1',name='charging.discover_sites',arguments={})])
            assert role=='analyst'
            assert any(e.artifact_id for e in run.evidence)
            return MockProvider().generate(run,role)
    provider=Controlled()
    assert discussion.step(run.id,provider)
    with transaction() as db:
        r=discussion.load(db,run.id)
        assert r.next_role=='analyst' and len(r.messages)==0 and len(r.tool_activity)==1
    assert discussion.step(run.id,provider)
    with transaction() as db:
        r=discussion.load(db,run.id)
        assert r.next_role=='operations' and len(r.messages)==1

def test_profiled_invalid_output_corrected_once(tmp_path,monkeypatch):
    from backend.acs.providers import MockProvider
    from backend.acs.db import transaction
    monkeypatch.setenv('ACS_DB',str(tmp_path/'correction.sqlite'))
    run=discussion.create(CreateRun(task=dict(title='Charging',description='Inspect sites'),mode='mock',capability_profile='charging',idempotency_key='c'))
    class Controlled:
        def generate(self,run,role,correction=None):
            if not correction:raise ValueError('fix this')
            return MockProvider().generate(run,role)
    discussion.step(run.id,Controlled());discussion.step(run.id,Controlled())
    with transaction() as db: assert discussion.load(db,run.id).next_role=='operations'

def test_numerical_claims_are_bound_to_metric_units_site_period(tmp_path,monkeypatch):
    from backend.acs import tools
    from backend.acs.capabilities import ToolRequest,TurnProgress
    from backend.acs.providers import MockProvider
    from backend.acs.models import Claim
    from backend.acs.db import transaction
    monkeypatch.setenv('ACS_DB',str(tmp_path/'claims.sqlite'))
    run=discussion.create(CreateRun(task=dict(title='Charging',description='Inspect'),mode='mock',capability_profile='charging',idempotency_key='claims'))
    run.turn_progress=TurnProgress(token='t',cycle=1,round=1,role='analyst',proposal_version=0,started_at=discussion.now())
    period=dict(start='2026-10-01T00:00:00Z',end='2026-11-01T00:00:00Z')
    with transaction() as db:
        call=tools.reserve(db,run,ToolRequest(call_id='c',name='metric',arguments={}),{},'source','v1')
        call=tools.complete(db,call,ToolOutcome(status='available',summary='Observed starts',data={'sites':[dict(site_id='s',status='available',observed_starts=3,units={'observed_starts':'observed starts'},**period)]},source_fingerprint='s',method='metric',queried_at=discussion.now(),origin='derived_metric'))
        tools.attach(db,run,call)
    turn=MockProvider().generate(run,'analyst').turn
    ref=dict(evidence_id=call.artifact_id,path='sites.0.observed_starts',value=3,unit='observed starts',site_id='s',**period)
    turn.claims=[Claim(statement='3 observed starts',basis='supported',evidence_ids=[call.artifact_id],metric_references=[ref])]
    discussion.validate_turn(run,'analyst',turn)
    turn.claims[0].metric_references[0].path='/sites/0/observed_starts'
    discussion.validate_turn(run,'analyst',turn)
    for field,value in [('value',4),('unit','sessions'),('site_id','other'),('end','2026-11-02T00:00:00Z')]:
        turn.claims=[Claim(statement='3 starts',basis='supported',evidence_ids=[call.artifact_id],metric_references=[{**ref,field:value}])]
        with pytest.raises(ValueError):discussion.validate_turn(run,'analyst',turn)

def test_concurrent_logical_tool_reservation(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from backend.acs import tools
    from backend.acs.capabilities import TurnProgress,ToolRequest
    from backend.acs.db import transaction
    monkeypatch.setenv('ACS_DB',str(tmp_path/'concurrent.sqlite'))
    run=discussion.create(CreateRun(task=dict(title='a',description='b'),mode='mock',idempotency_key='parallel'))
    run.turn_progress=TurnProgress(token='t',cycle=1,round=1,role='analyst',proposal_version=0,started_at=discussion.now())
    request=ToolRequest(call_id='same',name='read',arguments={})
    def reserve():
        with transaction() as db:
            db.execute('BEGIN IMMEDIATE')
            return tools.reserve(db,run,request,{},'snapshot','v1').id
    with ThreadPoolExecutor(max_workers=4) as pool:assert len(set(pool.map(lambda _:reserve(),range(8))))==1
    with transaction() as db:assert len(tools.history(db,run.id))==1

def test_waiting_job_outlives_discussion_lease_without_provider_polling(tmp_path,monkeypatch):
    from backend.acs import jobs
    from backend.acs.capabilities import ToolRequest
    from backend.acs.providers import Result,MockProvider
    from backend.acs.db import transaction
    from datetime import timedelta
    monkeypatch.setenv('ACS_DB',str(tmp_path/'waiting.sqlite'))
    run=discussion.create(CreateRun(task=dict(title='Charging',description='Investigate'),mode='mock',capability_profile='charging',idempotency_key='wait'))
    class Controlled:
        calls=0
        def generate(self,run,role,correction=None):
            self.calls+=1
            if self.calls==1:return Result(requests=[ToolRequest(call_id='forecast',name='charging.request_forecast',arguments=dict(site_ids=['s'],cutoff='2026-11-14T00:00:00Z'))])
            assert role=='analyst'
            return MockProvider().generate(run,role)
    provider=Controlled();discussion.step(run.id,provider)
    with transaction() as db:job_id=discussion.load(db,run.id).turn_progress.pending_job_id
    job=jobs.claim(job_id);start=jobs.now()
    for seconds in range(40,241,40):
        moment=start+timedelta(seconds=seconds);monkeypatch.setattr(jobs,'now',lambda:moment)
        jobs.heartbeat(job)
        assert not discussion.step(run.id,provider)
    assert provider.calls==1
    jobs.finish(job,error='controlled missing weights')
    discussion.step(run.id,provider)
    with transaction() as db:
        resumed=discussion.load(db,run.id)
        assert resumed.next_role=='operations' and len(resumed.messages)==1
        assert resumed.tool_activity[0].status=='failed'

def test_invalid_tool_arguments_reach_provider_correction(tmp_path,monkeypatch):
    from backend.acs.providers import Result,MockProvider
    from backend.acs.capabilities import ToolRequest
    from backend.acs.db import transaction
    monkeypatch.setenv('ACS_DB',str(tmp_path/'tool-correction.sqlite'))
    run=discussion.create(CreateRun(task=dict(title='a',description='b'),mode='mock',capability_profile='charging',idempotency_key='tool-correction'))
    class Controlled:
        calls=0
        def generate(self,run,role,correction=None):
            self.calls+=1
            if self.calls==1:return Result(requests=[ToolRequest(call_id='bad',name='charging.discover_sites',arguments={'limit':1000})])
            assert correction is not None
            return MockProvider().generate(run,role)
    provider=Controlled();discussion.step(run.id,provider);discussion.step(run.id,provider)
    assert provider.calls==2
    with transaction() as db:assert discussion.load(db,run.id).next_role=='operations'
