import json
import httpx
from backend.acs.providers import OpenAIProvider
from backend.acs.models import CreateRun
from backend.acs import discussion
from backend.acs.capabilities import TurnProgress
from backend.acs.db import transaction,put

def test_native_call_id_and_result_correlation(tmp_path,monkeypatch):
    monkeypatch.setenv('ACS_DB',str(tmp_path/'native.sqlite'));monkeypatch.setenv('OPENAI_API_KEY','test');monkeypatch.setenv('ACS_MODEL','controlled')
    run=discussion.create(CreateRun(task=dict(title='a',description='b'),mode='model',capability_profile='charging',idempotency_key='native'))
    run.turn_progress=TurnProgress(token='turn',cycle=1,round=1,role='analyst',proposal_version=0,started_at=discussion.now())
    item=dict(type='function_call',call_id='provider-id',name='charging__discover_sites',arguments='{}')
    payloads=[]
    def respond(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200,json={'status':'completed','id':'response-id','output':[item]})
    provider=OpenAIProvider(httpx.Client(transport=httpx.MockTransport(respond)))
    result=provider.generate(run,'analyst')
    assert result.requests[0].call_id=='provider-id'
    assert result.requests[0].name=='charging.discover_sites'
    assert payloads[0]['parallel_tool_calls'] is False
    with transaction() as db:put(db,'turn_protocol','turn',[item,dict(type='function_call_output',call_id='provider-id',output='{"status":"unavailable"}')])
    provider.generate(run,'analyst')
    assert payloads[1]['input'][-1]['call_id']=='provider-id'
    assert payloads[1]['input'][-2]==item
