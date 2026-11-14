"""Version-checked message seam. Model workers also check their durable lease token."""
from .discussion import load, save, apply_turn
from .errors import require
from .providers import Result


def publish_message(db, run_id, expected_version, role, turn):
    db.execute('BEGIN IMMEDIATE')
    run = load(db, run_id)
    require(run.proposal_version == expected_version, 'stale_version', 'Message targets an old proposal')
    require(run.state == 'running' and run.next_role == role, 'unexpected_role', 'Role is no longer scheduled')
    require(not (run.turn_progress and run.turn_progress.pending_job_id), 'tool_pending', 'The requesting role is waiting for an analytical job')
    lease = db.execute('SELECT 1 FROM discussion_leases WHERE run_id=?', (run_id,)).fetchone()
    require(lease is None, 'turn_in_progress', 'A model worker already owns this turn')
    apply_turn(run, role, Result(turn))
    run.turn_progress = None
    return save(db, run)
