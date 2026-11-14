"""Keep bounded discussions moving with explicitly unverified, reviewable output."""
from .models import AgentTurn, Draft, Action, ObjectionDraft
from .providers import Result

GUESS = 'Ipotesi non verificata da confermare'


def recover(run, role, reason, result=None):
    """Never accept invalid citations as proof or silently publish malformed output."""
    turn = result.turn.model_copy(deep=True) if result and result.turn else AgentTurn(
        applicability='applicable', kind='review', text='', explanation='',
        evidence_ids=[], claims=[], objections=[], resolutions=[], draft=None,
        question=None, needs_revision=True)
    available = {e.id for e in run.evidence}
    clean = lambda refs: [e for e in refs if e in available]
    turn.applicability = 'applicable'
    turn.kind = 'revision' if role == 'analyst' else 'review'
    turn.evidence_ids = clean(turn.evidence_ids)
    for claim in turn.claims:
        claim.basis = 'assumption'
        claim.metric_references = []
        claim.evidence_ids = clean(claim.evidence_ids)
        claim.statement = GUESS + ': ' + claim.statement
    turn.resolutions = []
    turn.objections = [ObjectionDraft(target_message_id=None, concern=GUESS,
        explanation=f'Il turno {role} non è stato validato: {reason}. '
        'Il critico deve riesaminare le affermazioni; quelle non verificate richiedono conferma umana come ipotesi, non come fatti. '
        + ' '.join(c.statement for c in turn.claims),
        blocking=True, evidence_ids=[])]
    turn.question = None  # Let all roles, including the critic, examine the result first.
    turn.needs_revision = True
    warning = f'{GUESS}. Validazione non completata ({reason}). '
    turn.text = warning + (turn.text or 'Nessun risultato verificato disponibile per questo turno.')
    turn.explanation = 'Avviso aggiunto dal sistema per proseguire la revisione. ' + warning + turn.explanation
    if role == 'analyst':
        if not turn.draft:
            turn.draft = Draft(summary=run.proposal.summary if run.proposal else run.task.title,
                recommended_actions=[Action(title='Verificare le ipotesi prima di procedere',
                    description='Confermare gli input mancanti e verificare la fattibilità del piano.',
                    rationale='Il turno non ha prodotto una valutazione verificata.', evidence_ids=[])],
                risks=[], unresolved_questions=[])
        turn.draft.summary = warning + turn.draft.summary
        turn.draft.risks.append(warning)
        turn.draft.unresolved_questions.extend([c.statement for c in turn.claims] or [warning])
        for action in turn.draft.recommended_actions:
            action.evidence_ids = clean(action.evidence_ids)
            action.rationale = GUESS + ': ' + action.rationale
    else:
        turn.draft = None
    return Result(turn=turn, response_id=result.response_id if result else None)
