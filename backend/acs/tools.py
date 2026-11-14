"""Immutable, run-scoped analytical records. Domain handlers have no publication authority."""
import hashlib
import json
from datetime import datetime, timezone
from .capabilities import ToolCall, ToolOutcome
from .db import get, put
from .errors import require

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def immutable(db, kind, ident, value):
    old = get(db, kind, ident)
    if old is not None and old != value:
        raise ValueError('Immutable artifact collision')
    if old is None:
        db.execute('INSERT INTO documents VALUES (?,?,?)', (kind, ident, canonical(value)))

def artifact(db, run_id, artifact_id):
    result = get(db, 'tool_artifact', artifact_id)
    require(result is not None and result['run_id'] == run_id, 'not_found', 'Artifact not attached to this run', 404)
    return result

def history(db, run_id, offset=0, limit=20):
    return [ToolCall.model_validate_json(r[0]) for r in db.execute(
        "SELECT payload FROM documents WHERE kind='tool_call' AND json_extract(payload,'$.run_id')=? ORDER BY json_extract(payload,'$.created_at'),id LIMIT ? OFFSET ?",
        (run_id, limit, offset))]

def reserve(db, run, request, parameters, source_fingerprint, method_version):
    p = run.turn_progress
    require(p is not None and p.cycle == run.cycle and p.role == run.next_role and p.proposal_version == run.proposal_version,
            'stale_turn', 'Tool request belongs to an obsolete turn')
    cache_key = digest(dict(tool=request.name, parameters=parameters, source=source_fingerprint, version=method_version))
    ident = digest([run.id, p.token, request.call_id])
    prior = get(db, 'tool_call', ident)
    if prior:
        call = ToolCall.model_validate(prior)
        require(call.cache_key == cache_key, 'call_conflict', 'Call ID reused with different inputs')
        return call
    cached = db.execute("SELECT payload FROM documents WHERE kind='tool_call' AND json_extract(payload,'$.run_id')=? AND json_extract(payload,'$.cache_key')=? AND json_extract(payload,'$.status')='succeeded' AND json_extract(payload,'$.artifact_id') IS NOT NULL ORDER BY id LIMIT 1", (run.id, cache_key)).fetchone()
    call = ToolCall(id=ident, run_id=run.id, cycle=run.cycle, role=p.role, turn_token=p.token,
                    request=request, normalized_parameters=parameters, cache_key=cache_key, source_fingerprint=source_fingerprint, method_version=method_version, created_at=datetime.now(timezone.utc))
    if cached:
        prior = ToolCall.model_validate_json(cached[0])
        call.artifact_id, call.status, call.summary, call.completed_at, call.cached = prior.artifact_id, prior.status, prior.summary, prior.completed_at, True
    put(db, 'tool_call', ident, call.model_dump(mode='json'))
    return call

def complete(db, call, outcome: ToolOutcome):
    existing = get(db, 'tool_call', call.id)
    if existing and existing['artifact_id']:
        return ToolCall.model_validate(existing)
    payload = outcome.model_dump(mode='json')
    # Short opaque citation handles reduce transcription errors; integrity uses full SHA256.
    ident = 'artifact-' + digest([call.run_id, call.cache_key, payload])[:16]
    immutable(db, 'tool_artifact', ident, dict(id=ident, run_id=call.run_id, tool_call_id=call.id, sha256=digest(payload), outcome=payload))
    call.artifact_id = ident
    call.completed_at = datetime.now(timezone.utc)
    call.status = 'failed' if outcome.status == 'error' else 'succeeded'
    call.summary = outcome.summary
    put(db, 'tool_call', call.id, call.model_dump(mode='json'))
    return call

def attach(db, run, call):
    p = run.turn_progress
    if not (p and run.state == 'running' and p.token == call.turn_token and run.cycle == call.cycle and run.next_role == call.role and run.proposal_version == p.proposal_version):
        return False
    from .models import Evidence
    result = artifact(db, run.id, call.artifact_id)
    outcome = result['outcome']
    if not any(e.id == call.artifact_id for e in run.evidence):
        require(len(run.evidence) < 256, 'evidence_limit', 'Evidence budget exhausted')
        run.evidence.append(Evidence(id=call.artifact_id, name=call.request.name, text=outcome['summary'], url=None,
            origin=outcome['origin'], sha256=result['sha256'], artifact_id=call.artifact_id,
            source_fingerprint=outcome['source_fingerprint'], limitations=outcome['limitations']))
    run.tool_activity = ([c for c in run.tool_activity if c.id != call.id]+[call])[-32:]
    return True
