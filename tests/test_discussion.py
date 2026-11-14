import json
import time
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.acs.api import app
from backend.acs import discussion as engine
from backend.acs.models import CreateRun, Task, AgentTurn, ObjectionDraft, Claim
from backend.acs.db import transaction, get, put
from backend.acs.providers import MockProvider, OpenAIProvider, ModelFailure, Result
from backend.acs.errors import Conflict

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('ACS_DB', str(tmp_path/'test.sqlite'))
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('ACS_MODEL', raising=False)
    return TestClient(app)

UNRELATED = {'title':'Scrivere una guida per nuovi volontari',
             'description':'Proporre una guida breve per accogliere volontari in biblioteca, usando solo risorse esistenti.',
             'attachments':[{'name':'Note del coordinatore','text':'I volontari sono disponibili sabato mattina.'}]}

def create(client, task=None, **kwargs):
    body = {'task':task or UNRELATED,'mode':'mock','idempotency_key':str(uuid4()),**kwargs}
    result = client.post('/api/v2/runs',json=body)
    assert result.status_code == 202,result.text
    return result.json()

def read(ident):
    with transaction() as db:
        return engine.load(db,ident)

def drain(ident, provider=None):
    for _ in range(30):
        if read(ident).state != 'running':
            return read(ident)
        engine.step(ident,provider)
    raise AssertionError('Discussion exceeded test bound')

def answer(client, run, **kwargs):
    body={'proposal_version':run.proposal_version,'idempotency_key':'answer-'+str(uuid4()),
          'question_id':run.question.id,'option_id':run.question.options[0].id,'actor':'Nico',**kwargs}
    return client.post(f'/api/v2/runs/{run.id}/answers',json=body)

@pytest.mark.parametrize('charging',[False,True])
def test_full_flow_for_arbitrary_task_and_charging(client,charging):
    task=client.get('/examples/charging/task').json() if charging else UNRELATED
    r=create(client,task)
    r=drain(r['id'])
    assert r.state=='awaiting_input'
    assert task['title'] in r.question.text
    assert {m.actor for m in r.messages}=={'analyst','operations','finance','critic'}
    if not charging:
        assert next(m for m in r.messages if m.actor=='finance').content.applicability=='not_applicable'
        assert 'supplier' not in r.model_dump_json()
    assert answer(client,r,text='Cominciamo da un primo passo piccolo e verificabile.').status_code==200
    final=drain(r.id)
    assert final.state=='proposal_ready' and final.proposal.status=='final'
    assert final.proposal.recommended_actions and final.proposal.risks
    assert len(final.proposals)>=3 and len({p.version for p in final.proposals})==len(final.proposals)
    assert all(o.status=='resolved' for o in final.objections)
    response=client.post(f'/api/v2/runs/{r.id}/approve',json={'proposal_version':final.proposal_version,'idempotency_key':'ap','actor':'Nico'})
    assert response.status_code==200 and response.json()['state']=='approved'
    assert client.post(f'/api/v2/runs/{r.id}/execute',json={}).status_code==404

def test_model_mode_requires_credentials_not_silent_mock(client):
    r=client.post('/api/v2/runs',json={'task':UNRELATED,'idempotency_key':'missing'})
    assert r.status_code==503 and r.json()['code']=='model_not_configured'

def test_idempotency_and_stale_question_approval(client):
    r=create(client,idempotency_key='stable')
    assert create(client,idempotency_key='stable')['id']==r['id']
    different=client.post('/api/v2/runs',json={'task':{'title':'Different','description':'task'},'mode':'mock','idempotency_key':'stable'})
    assert different.status_code==409
    q=drain(r['id'])
    answered=answer(client,q,idempotency_key='one')
    assert answered.status_code==200
    # The identical request returns its original response, even after the worker advances.
    final=drain(q.id)
    assert answer(client,q,idempotency_key='one').json()==answered.json()
    assert answer(client,q,idempotency_key='new').status_code==409
    stale=client.post(f'/api/v2/runs/{q.id}/approve',json={'proposal_version':q.proposal_version,'idempotency_key':'old','actor':'Nico'})
    assert stale.status_code==409 and stale.json()['code']=='stale_version'
    assert read(q.id).proposal_version==final.proposal_version

class Disagreeing(MockProvider):
    def generate(self,run,role,correction=None):
        result=super().generate(run,role,correction)
        result.turn.question=None
        result.turn.resolutions=[]
        if role=='critic':
            result.turn.needs_revision=True
            result.turn.objections=[ObjectionDraft(target_message_id=None,concern='The claimed benefit has no supporting measurement',
                explanation='A measurement is required before relying on that benefit.',blocking=True,evidence_ids=[])]
            result.turn=AgentTurn.model_validate(result.turn.model_dump())
        return result

def test_round_limit_surfaces_disagreement_and_conditional_final(client):
    r=create(client,max_rounds=2)
    r=drain(r['id'],Disagreeing())
    assert r.state=='awaiting_input' and r.question.reason=='round_limit'
    assert len(r.messages)==8 and r.round==2
    response=answer(client,r,option_id='retain_uncertainty')
    assert response.status_code==200
    result=response.json()
    assert result['proposal']['status']=='conditional' and result['proposal']['unresolved_questions']
    approval=client.post(f'/api/v2/runs/{r.id}/approve',json={'proposal_version':result['proposal_version'],'idempotency_key':'bad','actor':'Nico'})
    assert approval.status_code==409 and approval.json()['code']=='open_blocker'
    assert read(r.id).objections[0].status=='open'

def test_sse_and_restart_resume(client):
    r=create(client)
    engine.step(r['id'])
    # New client/process reads the same stored draft and scheduled role.
    fresh=TestClient(app)
    assert fresh.get(f"/api/v2/runs/{r['id']}").json()['next_role']=='operations'
    drain(r['id'])
    response=fresh.get(f"/api/v2/runs/{r['id']}/events?once=true")
    ids=[int(l[4:]) for l in response.text.splitlines() if l.startswith('id: ')]
    assert len(ids)==5
    replay=fresh.get(f"/api/v2/runs/{r['id']}/events?once=true",headers={'Last-Event-ID':str(ids[-2])})
    assert replay.text.count('event: snapshot')==1

def test_expired_worker_response_is_discarded(client):
    r=create(client)
    class Superseded(MockProvider):
        def generate(self,run,role,correction=None):
            with transaction() as db:
                db.execute("UPDATE discussion_leases SET token='another-worker' WHERE run_id=?",(run.id,))
            return super().generate(run,role,correction)
    assert engine.step(r['id'],Superseded()) is False
    assert read(r['id']).messages==[]
    with transaction() as db:
        db.execute('UPDATE discussion_leases SET expires_at=0 WHERE run_id=?',(r['id'],))
    assert engine.step(r['id']) is True
    assert len(read(r['id']).messages)==1

def test_claims_cannot_cite_unknown_or_unread_evidence(client):
    r=create(client,task={**UNRELATED,'attachments':[{'name':'Unread','url':'https://example.com'}]})
    class Invalid(MockProvider):
        calls=0
        def generate(self,run,role,correction=None):
            self.calls+=1
            result=super().generate(run,role,correction)
            result.turn.claims=[Claim(statement='A proven fact',basis='supported',evidence_ids=['attachment-1'])]
            result.turn=AgentTurn.model_validate(result.turn.model_dump())
            return result
    p=Invalid()
    engine.step(r['id'],p)
    assert p.calls==2 and read(r['id']).state=='failed' and read(r['id']).messages[0].actor=='system'
    failed=read(r['id'])
    response=client.post(f"/api/v2/runs/{r['id']}/retry",json={'proposal_version':failed.proposal_version,'idempotency_key':'retry'})
    assert response.status_code==200
    assert drain(r['id']).state=='awaiting_input'

def test_invalid_output_gets_one_correction(client):
    r=create(client)
    class Repair(MockProvider):
        calls=0
        def generate(self,run,role,correction=None):
            self.calls+=1
            result=super().generate(run,role,correction)
            if not correction:
                result.turn.evidence_ids=['invented']
            return result
    provider=Repair()
    engine.step(r['id'],provider)
    assert provider.calls==2 and read(r['id']).next_role=='operations'

@pytest.mark.parametrize('charging',[False,True])
def test_real_provider_protocol_full_flow_with_stubbed_http(client,monkeypatch,charging):
    """Exercise the real HTTP adapter. This is a protocol test, NOT a paid live-model test."""
    monkeypatch.setenv('OPENAI_API_KEY','test-key')
    monkeypatch.setenv('ACS_MODEL','test-structured-model')
    task=client.get('/examples/charging/task').json() if charging else UNRELATED
    r=create(client,task,mode='model')
    sent=[]
    current={}
    def handler(request):
        payload=json.loads(request.content)
        sent.append(payload)
        assert payload['text']['format']['strict'] is True and payload['store'] is False
        assert request.headers['Authorization']=='Bearer test-key'
        snapshot=current['run']
        out=MockProvider().generate(snapshot,snapshot.next_role).turn
        return httpx.Response(200,json={'id':'resp-protocol','status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':out.model_dump_json()}]}]})
    provider=OpenAIProvider(httpx.Client(transport=httpx.MockTransport(handler)))
    for cycle in range(2):
        for _ in range(8):
            current['run']=read(r['id'])
            if current['run'].state!='running': break
            engine.step(r['id'],provider)
        snapshot=read(r['id'])
        if cycle==0:
            assert snapshot.state=='awaiting_input'
            assert answer(client,snapshot,text='Preferire il primo passo limitato.').status_code==200
    result=read(r['id'])
    assert result.state=='proposal_ready' and result.mode=='model'
    assert len(sent)==8
    assert all(m.provider_response_id=='resp-protocol' for m in result.messages if m.actor!='operator')
    assert any('Human answer' in p['input'][0]['content'] for p in sent[4:])

@pytest.mark.parametrize('body,code',[
    ({'status':'incomplete','output':[]},'model_incomplete'),
    ({'status':'completed','output':[{'content':[{'type':'refusal'}]}]},'model_refusal')])
def test_provider_refusal_and_incomplete_are_visible(client,monkeypatch,body,code):
    monkeypatch.setenv('OPENAI_API_KEY','test-key');monkeypatch.setenv('ACS_MODEL','test-model')
    r=create(client,mode='model')
    provider=OpenAIProvider(httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=body))))
    engine.step(r['id'],provider)
    assert read(r['id']).state=='failed' and read(r['id']).error.code==code

def test_background_worker_runs_after_submit(client):
    with TestClient(app) as live:
        r=create(live)
        deadline=time.time()+5
        while time.time()<deadline:
            result=live.get(f"/api/v2/runs/{r['id']}").json()
            if result['state']=='awaiting_input': break
            time.sleep(.02)
        assert result['state']=='awaiting_input'

def test_main_contract_has_no_charging_or_execution_assumptions(client):
    schema=client.get('/openapi.json').json()
    serialized=json.dumps(schema)
    for forbidden in ['BZ_PIAVE','supplier','quantity_chargers','wait_a','switch_b','/execute','site_name']:
        assert forbidden not in serialized
    assert client.get('/examples/charging/openapi.json').status_code==200
    assert client.post('/api/v2/runs',json={'task':{'title':'x','description':'y','bad':1},'mode':'mock','idempotency_key':'bad'}).status_code==422

def test_stale_message_port_cannot_modify_new_proposal(client):
    from backend.acs.agent_port import publish_message
    r=create(client)
    initial=read(r['id'])
    turn=MockProvider().generate(initial,'analyst').turn
    engine.step(r['id'])
    with pytest.raises(Conflict) as caught:
        with transaction() as db:
            publish_message(db,r['id'],0,'analyst',turn)
    assert caught.value.code=='stale_version'
    assert len(read(r['id']).messages)==1

def test_empty_perspectives_do_not_invent_a_final_proposal(client):
    class NotApplicable(MockProvider):
        def generate(self,run,role,correction=None):
            return Result(AgentTurn(applicability='not_applicable',kind='not_applicable',text='No applicable perspective',
                explanation='The fixture deliberately declines all perspectives.',evidence_ids=[],claims=[],objections=[],
                resolutions=[],draft=None,question=None,needs_revision=False))
    r=create(client,max_rounds=1)
    result=drain(r['id'],NotApplicable())
    assert result.state=='awaiting_input' and result.proposal is None
    assert all(o.id!='retain_uncertainty' for o in result.question.options)
