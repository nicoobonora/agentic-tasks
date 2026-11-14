"""Small durable discussion loop. No domain-specific decisions or action execution."""
import hashlib
import json
import time
from datetime import datetime, timezone
from uuid import uuid4
from pydantic import ValidationError
from .db import transaction, get, put
from .errors import require, Conflict
from .models import (Run, CreateRun, Evidence, AgentTurn, Message, Proposal, Question,
                     QuestionDraft, Option, Objection, ApprovalRecord, Error)
from .providers import ROLES, settings, provider_for, ModelFailure

KIND = 'discussion_v2'

def now():
    return datetime.now(timezone.utc)

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def load(db, run_id):
    value = get(db, KIND, run_id)
    require(value is not None, 'not_found', 'Discussion not found', 404)
    return Run.model_validate(value)

def save(db, run):
    run.updated_at = now()
    value = run.model_dump(mode='json')
    put(db, KIND, run.id, value)
    db.execute('INSERT INTO events(run_id,payload) VALUES (?,?)', (run.id, json.dumps(value)))
    return run

def replay(db, key, body):
    prior = get(db, 'discussion_commands', key)
    if prior:
        require(prior['hash'] == fingerprint(body.model_dump(mode='json')), 'idempotency_conflict', 'Key reused with a different request')
        return Run.model_validate(prior['result'])

def record(db, key, body, run):
    put(db, 'discussion_commands', key, {'hash': fingerprint(body.model_dump(mode='json')), 'result': run.model_dump(mode='json')})

def evidence(ident, name, text, url=None, origin='user_provided'):
    return Evidence(id=ident, name=name, text=text, url=url, origin=origin,
                    sha256=fingerprint({'text': text, 'url': url}))

def create(body: CreateRun):
    with transaction() as db:
        db.execute('BEGIN IMMEDIATE')
        key = 'create:' + body.idempotency_key
        previous = replay(db, key, body)
        if previous:
            return previous
        config = settings()
        require(body.mode == 'mock' or bool(config['key'] and config['model']), 'model_not_configured',
                'Set OPENAI_API_KEY and ACS_MODEL, or explicitly request mode=mock.', 503)
        sources = [evidence('task', body.task.title, body.task.description)]
        if body.task.context:
            sources.append(evidence('context', 'Task context', body.task.context))
        sources.extend(evidence(f'attachment-{i+1}', a.name, a.text, a.url,
                       'user_provided' if a.text else 'reference_only') for i, a in enumerate(body.task.attachments))
        run = Run(id=str(uuid4()), task=body.task, mode=body.mode, model=config['model'] if body.mode == 'model' else None,
                  notice='MOCK: deterministic development fixture; no model calls.' if body.mode == 'mock' else 'Model-backed discussion. Actions are proposals only and are never executed.',
                  state='running', max_rounds=body.max_rounds or config['max_rounds'], evidence=sources,
                  created_at=now(), updated_at=now())
        save(db, run)
        record(db, key, body, run)
        return run

def public_message(run, text, actor='system', evidence_ids=None):
    turn = AgentTurn(applicability='applicable', kind='review', text=text, explanation=text,
                     evidence_ids=evidence_ids or [], claims=[], objections=[], resolutions=[], draft=None, question=None, needs_revision=False)
    msg = Message(id=str(uuid4()), proposal_version=run.proposal_version, cycle=run.cycle, round=run.round,
                  actor=actor, reply_to=run.messages[-1].id if run.messages else None, created_at=now(), content=turn)
    run.messages.append(msg)


def validate_turn(run, role, turn):
    available = {e.id for e in run.evidence}
    readable = {e.id for e in run.evidence if e.text and e.origin != 'reference_only'}
    refs = list(turn.evidence_ids)
    for claim in turn.claims:
        refs += claim.evidence_ids
        if claim.basis == 'supported' and (not claim.evidence_ids or not set(claim.evidence_ids) <= readable):
            raise ValueError('Supported claims require readable evidence; a bare URL is not evidence of its contents')
    for objection in turn.objections:
        refs += objection.evidence_ids
        if objection.target_message_id and not any(m.id == objection.target_message_id for m in run.messages):
            raise ValueError('Objection references an unknown message')
    for resolution in turn.resolutions:
        refs += resolution.evidence_ids
        if role != 'critic':
            raise ValueError('Only the critic can resolve objections')
        if not resolution.explanation.strip() or not any(o.id == resolution.objection_id and o.status == 'open' for o in run.objections):
            raise ValueError('Resolution must explain an existing open objection')
    if turn.draft:
        if role != 'analyst':
            raise ValueError('Only the analyst may revise the draft; other agents must request a revision')
        refs += [e for a in turn.draft.recommended_actions for e in a.evidence_ids]
    if role == 'analyst' and turn.applicability == 'applicable' and turn.draft is None:
        raise ValueError('An applicable analyst must propose or revise a draft')
    if turn.applicability == 'not_applicable' and (turn.kind != 'not_applicable' or turn.draft or turn.objections or turn.resolutions):
        raise ValueError('not_applicable must be explicit and cannot change the proposal or objections')
    if not set(refs) <= available:
        raise ValueError('Unknown evidence IDs: '+', '.join(sorted(set(refs)-available)))


def ask(run, draft, reason):
    run.question = Question(**draft.model_dump(), id=str(uuid4()), proposal_version=run.proposal_version, reason=reason)
    run.state = 'awaiting_input'
    run.approval = None


def limit_question(run):
    concerns = [o.concern for o in run.objections if o.status == 'open']
    concerns += [m.content.text for m in run.messages if m.cycle == run.cycle and m.round == run.round and m.content.needs_revision]
    if not run.proposal:
        concerns.append('No supported approach has been proposed yet.')
    details = '; '.join(dict.fromkeys(concerns)) or 'The agents have not converged on the current approach.'
    options = [Option(id='clarify', label='Provide guidance and resume', explanation='Use the text answer to clarify: '+details[:1200])]
    if run.proposal:
        options.append(Option(id='retain_uncertainty', label='Keep the unresolved points visible', explanation='Return a conditional proposal without asserting consensus or executing actions.'))
    else:
        options.append(Option(id='provide_context', label='Provide more context', explanation='Supply the missing information so an approach can be proposed.'))
    ask(run, QuestionDraft(text=f'How should we resolve the remaining questions for “{run.task.title}”?', explanation=details,
                           options=options), 'round_limit')


def finalize(run):
    require(run.proposal is not None, 'no_proposal', 'No draft exists yet; provide guidance and resume')
    open_points = [o for o in run.objections if o.status == 'open']
    unresolved = list(run.proposal.unresolved_questions)
    unresolved += [o.concern + ': ' + o.explanation for o in open_points]
    unresolved += [m.content.text for m in run.messages if m.cycle == run.cycle and m.round == run.round and m.content.needs_revision]
    unresolved = list(dict.fromkeys(unresolved))
    run.proposal_version += 1
    proposal = run.proposal.model_copy(update={'version': run.proposal_version, 'created_at': now(),
        'status': 'conditional' if unresolved else 'final', 'unresolved_questions': unresolved,
        'risks': list(dict.fromkeys(run.proposal.risks + [o.concern for o in open_points])),
        'source_message_ids': [m.id for m in run.messages]})
    run.proposal = proposal
    run.proposals.append(proposal.model_copy(deep=True))
    run.question = None
    run.state = 'proposal_ready'
    run.approval = None


def apply_turn(run, role, result):
    turn = result.turn
    validate_turn(run, role, turn)
    msg_id = str(uuid4())
    if turn.draft:
        run.proposal_version += 1
        proposal = Proposal(**turn.draft.model_dump(), version=run.proposal_version, created_at=now(), status='draft',
                            evidence_ids=sorted(set(turn.evidence_ids+[e for a in turn.draft.recommended_actions for e in a.evidence_ids])),
                            source_message_ids=[m.id for m in run.messages]+[msg_id])
        run.proposal = proposal
        run.proposals.append(proposal.model_copy(deep=True))
        run.approval = None
    msg = Message(id=msg_id, proposal_version=run.proposal_version, cycle=run.cycle, round=run.round, actor=role,
                  reply_to=run.messages[-1].id if run.messages else None, created_at=now(), content=turn,
                  model=run.model, provider_response_id=result.response_id)
    run.messages.append(msg)
    for obj in turn.objections:
        run.objections.append(Objection(**obj.model_dump(), id=str(uuid4()), message_id=msg.id))
    for resolution in turn.resolutions:
        obj = next(o for o in run.objections if o.id == resolution.objection_id)
        obj.status, obj.resolution, obj.resolved_by_message_id = 'resolved', resolution, msg.id
    if turn.question:
        ask(run, turn.question, 'agent_request')
        return
    if role != 'critic':
        run.next_role = ROLES[ROLES.index(role)+1]
        return
    unresolved = any(o.status == 'open' for o in run.objections)
    needs_revision = any(m.content.needs_revision for m in run.messages if m.cycle == run.cycle and m.round == run.round and m.actor != 'analyst')
    if unresolved or needs_revision or not run.proposal:
        if run.round >= run.max_rounds:
            limit_question(run)
        else:
            run.round += 1
            run.next_role = 'analyst'
    else:
        finalize(run)


def command(run_id, action, body):
    with transaction() as db:
        db.execute('BEGIN IMMEDIATE')
        run = load(db, run_id)
        key = f'{run_id}:{action}:{body.idempotency_key}'
        previous = replay(db, key, body)
        if previous:
            return previous
        require(body.proposal_version == run.proposal_version, 'stale_version', 'Proposal version is no longer current')
        if action == 'answer':
            require(run.state == 'awaiting_input' and run.question and body.question_id == run.question.id, 'stale_question', 'Question is no longer active')
            option = next((o for o in run.question.options if o.id == body.option_id), None)
            require(body.option_id is None or option is not None, 'invalid_option', 'Unknown question option')
            finish = body.finalize_with_unresolved or (run.question.reason == 'round_limit' and body.option_id == 'retain_uncertainty')
            require(not finish or (run.question.reason == 'round_limit' and run.proposal is not None), 'invalid_finalization', 'Conditional finalization is allowed only after the round limit with a draft')
            answer = json.dumps({'question': run.question.text, 'option': option.model_dump() if option else None,
                                 'text': body.text, 'actor': body.actor}, ensure_ascii=False)
            source = evidence('answer-'+str(uuid4()), 'Human answer', answer, origin='human_answer')
            run.evidence.append(source)
            public_message(run, answer, 'operator', [source.id])
            if finish:
                finalize(run)
            else:
                run.proposal_version += 1  # Invalidate in-flight messages and previous approvals immediately.
                run.cycle += 1
                run.round, run.next_role, run.state = 1, 'analyst', 'running'
                run.question, run.approval, run.error = None, None, None
        elif action == 'approve':
            require(run.state == 'proposal_ready' and run.proposal is not None, 'not_ready', 'No final proposal is ready')
            require(not any(o.status == 'open' and o.blocking for o in run.objections), 'open_blocker', 'Unsupported claims or blocking objections must be resolved before approval')
            run.approval = ApprovalRecord(proposal_version=run.proposal_version, actor=body.actor, at=now())
            run.state = 'approved'
            public_message(run, f'{body.actor} approved proposal v{run.proposal_version}. No actions were executed.', 'operator')
        elif action == 'retry':
            require(run.state == 'failed', 'invalid_state', 'Only a failed discussion can be retried')
            run.state, run.error = 'running', None
            run.proposal_version += 1
        else:
            raise Conflict('unknown_command', 'Unknown command')
        db.execute('DELETE FROM discussion_leases WHERE run_id=?', (run_id,))
        save(db, run)
        record(db, key, body, run)
        return run


def step(run_id, provider=None):
    """Lease -> network without DB lock -> version/lease CAS -> commit. Restart-safe."""
    token = str(uuid4())
    with transaction() as db:
        db.execute('BEGIN IMMEDIATE')
        run = load(db, run_id)
        if run.state != 'running':
            return False
        lease = db.execute('SELECT * FROM discussion_leases WHERE run_id=?', (run_id,)).fetchone()
        if lease and lease['expires_at'] > time.time():
            return False
        db.execute('INSERT OR REPLACE INTO discussion_leases VALUES (?,?,?)', (run_id, token, time.time()+180))
        expected_version, role = run.proposal_version, run.next_role
    backend = provider or provider_for(run)
    result, failure, correction = None, None, None
    for attempt in range(2):
        try:
            result = backend.generate(run, role, correction)
            validate_turn(run, role, result.turn)
            break
        except (ValidationError, ValueError) as exc:
            correction = str(exc)[:2000]
            if attempt == 1:
                failure = ModelFailure('invalid_model_output', 'The model returned invalid structured output twice; no message was applied.')
        except ModelFailure as exc:
            failure = exc
            break
        except Exception:
            failure = ModelFailure('orchestration_error', 'Unexpected provider error; retry explicitly. No partial output was applied.')
            break
    with transaction() as db:
        db.execute('BEGIN IMMEDIATE')
        current = load(db, run_id)
        lease = db.execute('SELECT * FROM discussion_leases WHERE run_id=?', (run_id,)).fetchone()
        if not lease or lease['token'] != token or lease['expires_at'] <= time.time() or current.state != 'running' or current.proposal_version != expected_version or current.next_role != role:
            return False  # Response is stale; never overwrite current state.
        db.execute('DELETE FROM discussion_leases WHERE run_id=?', (run_id,))
        if failure:
            current.state = 'failed'
            current.error = Error(code=failure.code, message=str(failure))
            public_message(current, str(failure))
            current = Run.model_validate(current.model_dump())
        else:
            apply_turn(current, role, result)
        save(db, current)
    return True
