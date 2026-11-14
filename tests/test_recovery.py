from backend.acs import discussion
from backend.acs.db import transaction
from backend.acs.models import CreateRun, Answer, Approval, AgentTurn, Claim
from backend.acs.providers import Result, ModelFailure


def load(ident):
    with transaction() as db:
        return discussion.load(db, ident)


class InvalidProvider:
    def generate(self, run, role, correction=None):
        return Result(turn=AgentTurn(applicability='applicable', kind='review',
            text='La capacità disponibile è 900 kW.', explanation='Dato non verificato.',
            evidence_ids=['invented'], claims=[Claim(statement='Capacità 900 kW',
                basis='supported', evidence_ids=['invented'])], objections=[],
            resolutions=[], draft=None, question=None, needs_revision=False))


def test_repeated_invalid_turns_reach_human_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv('ACS_DB',str(tmp_path/'recovery.sqlite'))
    run=discussion.create(CreateRun(task=dict(title='Piano',description='Aggiungere colonnine'),
        mode='mock', capability_profile='charging', max_rounds=1,idempotency_key='a'))
    for _ in range(8):
        discussion.step(run.id,InvalidProvider())
    run=load(run.id)
    assert run.state=='awaiting_input'
    assert [m.actor for m in run.messages]==['analyst','operations','finance','critic']
    assert all(c.basis=='assumption' and not c.metric_references and not c.evidence_ids
        for m in run.messages for c in m.content.claims)
    assert '900' in run.proposal.unresolved_questions[0]
    assert 'Unverified' in run.proposal.summary
    run=discussion.command(run.id,'answer',Answer(proposal_version=run.proposal_version,
        question_id=run.question.id, actor='Utente',option_id='retain_uncertainty',idempotency_key='confirm'))
    assert run.state=='proposal_ready' and run.proposal.status=='conditional'
    assert all(o.status=='open' and not o.blocking for o in run.objections)
    assert run.proposal.unresolved_questions
    run=discussion.command(run.id,'approve',Approval(proposal_version=run.proposal_version,
        actor='Utente',idempotency_key='approve'))
    assert run.state=='approved'


def test_provider_unavailable_still_produces_explicit_incomplete_plan(tmp_path, monkeypatch):
    monkeypatch.setenv('ACS_DB',str(tmp_path/'unavailable.sqlite'))
    class Unavailable:
        def generate(self,*args):
            raise ModelFailure('provider_error','Provider unavailable')
    run=discussion.create(CreateRun(task=dict(title='Piano',description='Valutare'),
        mode='mock',max_rounds=1,idempotency_key='a'))
    for _ in range(4):
        discussion.step(run.id,Unavailable())
    run=load(run.id)
    assert run.state=='awaiting_input'
    assert 'Provider unavailable' in run.proposal.summary
    assert not any(m.content.claims for m in run.messages)


def test_exhausted_profile_budget_advances_without_more_provider_calls(tmp_path, monkeypatch):
    from backend.acs.capabilities import TurnProgress
    monkeypatch.setenv('ACS_DB',str(tmp_path/'budget.sqlite'))
    run=discussion.create(CreateRun(task=dict(title='Piano',description='Valutare'),
        mode='mock',capability_profile='charging',max_rounds=1,idempotency_key='a'))
    run.turn_progress=TurnProgress(token='budget',cycle=run.cycle,round=run.round,
        role='analyst',proposal_version=run.proposal_version,provider_requests=10,
        started_at=discussion.now())
    with transaction() as db:
        discussion.save(db,run)
    class NoMoreCalls:
        def generate(self,*args):
            raise AssertionError('Budget exhausted: provider must not be called')
    discussion.step(run.id,NoMoreCalls())
    run=load(run.id)
    assert run.state=='running' and run.next_role=='operations'
    assert run.turn_progress is None
    assert 'limit reached' in run.proposal.summary
    assert run.objections[0].blocking
