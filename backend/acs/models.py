"""Domain-neutral discussion API v2. Model outputs and public messages share a schema."""
from datetime import datetime
from .capabilities import MetricReference, TurnProgress, ToolCall
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal['analyst', 'operations', 'finance', 'critic']

class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Error(Model):
    code: str
    message: str

class Attachment(Model):
    name: str = Field(min_length=1, max_length=200)
    text: str | None = Field(default=None, max_length=40000)
    url: str | None = Field(default=None, max_length=2000)

    @model_validator(mode='after')
    def content(self):
        if not self.text and not self.url:
            raise ValueError('Provide extracted text or a reference URL')
        if self.url and not self.url.startswith(('https://', 'http://')):
            raise ValueError('Attachment URLs must use HTTP(S)')
        return self

class Task(Model):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=20000)
    context: str | None = Field(default=None, max_length=40000)
    attachments: list[Attachment] = Field(default_factory=list, max_length=10)

    @model_validator(mode='after')
    def bounded(self):
        if len(self.model_dump_json()) > 100000:
            raise ValueError('Task including attachments exceeds 100,000 characters')
        return self

class Evidence(Model):
    id: str
    name: str
    text: str | None
    url: str | None
    origin: Literal['user_provided', 'reference_only', 'human_answer', 'observation', 'derived_metric', 'forecast', 'human_preference', 'simulated_business']
    sha256: str
    artifact_id: str | None = None
    source_fingerprint: str | None = None
    limitations: list[str] = Field(default_factory=list)

class Action(Model):
    title: str
    description: str
    rationale: str
    evidence_ids: list[str]

class Draft(Model):
    summary: str
    recommended_actions: list[Action] = Field(min_length=1, max_length=12)
    risks: list[str]
    unresolved_questions: list[str]

class Claim(Model):
    metric_references: list[MetricReference] = Field(default_factory=list)
    statement: str
    basis: Literal['supported', 'assumption', 'estimate']
    evidence_ids: list[str]

class ObjectionDraft(Model):
    target_message_id: str | None
    concern: str
    explanation: str
    blocking: bool
    evidence_ids: list[str]

class Resolution(Model):
    objection_id: str
    explanation: str
    evidence_ids: list[str]

class Option(Model):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=300)
    explanation: str

class QuestionDraft(Model):
    text: str = Field(min_length=1)
    explanation: str
    options: list[Option] = Field(min_length=2, max_length=5)

    @model_validator(mode='after')
    def distinct(self):
        if len({o.id for o in self.options}) != len(self.options):
            raise ValueError('Question option IDs must be unique')
        return self

class AgentTurn(Model):
    applicability: Literal['applicable', 'not_applicable']
    kind: Literal['proposal', 'review', 'objection', 'revision', 'not_applicable']
    text: str
    explanation: str
    evidence_ids: list[str]
    claims: list[Claim]
    objections: list[ObjectionDraft]
    resolutions: list[Resolution]
    draft: Draft | None
    question: QuestionDraft | None
    needs_revision: bool

class Message(Model):
    id: str
    proposal_version: int
    cycle: int
    round: int
    actor: Literal['analyst', 'operations', 'finance', 'critic', 'operator', 'system']
    reply_to: str | None
    created_at: datetime
    content: AgentTurn
    model: str | None = None
    provider_response_id: str | None = None

class Objection(ObjectionDraft):
    id: str
    message_id: str
    status: Literal['open', 'resolved'] = 'open'
    resolution: Resolution | None = None
    resolved_by_message_id: str | None = None

class Question(QuestionDraft):
    id: str
    proposal_version: int
    reason: Literal['agent_request', 'round_limit']
    allow_free_text: bool = True

class Proposal(Draft):
    version: int
    created_at: datetime
    status: Literal['draft', 'final', 'conditional']
    evidence_ids: list[str]
    source_message_ids: list[str]

class ApprovalRecord(Model):
    proposal_version: int
    actor: str
    at: datetime

class Run(Model):
    provider_attempts: int | None = None
    model_usage: dict[str, int] = Field(default_factory=dict)
    capability_profile: str | None = None
    profile_version: str | None = None
    turn_progress: TurnProgress | None = None
    tool_activity: list[ToolCall] = Field(default_factory=list, max_length=32)
    schema_version: Literal['2.0'] = '2.0'
    id: str
    task: Task
    mode: Literal['model', 'mock']
    model: str | None
    notice: str
    state: Literal['running', 'awaiting_input', 'proposal_ready', 'approved', 'failed']
    proposal_version: int = 0
    cycle: int = 1
    round: int = 1
    max_rounds: int
    next_role: Role = 'analyst'
    messages: list[Message] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    objections: list[Objection] = Field(default_factory=list)
    proposal: Proposal | None = None
    proposals: list[Proposal] = Field(default_factory=list)
    question: Question | None = None
    approval: ApprovalRecord | None = None
    error: Error | None = None
    created_at: datetime
    updated_at: datetime

class CreateRun(Model):
    capability_profile: str | None = None

    @model_validator(mode='after')
    def registered_profile(self):
        from .profiles import get_profile
        get_profile(self.capability_profile)
        return self

    task: Task
    mode: Literal['model', 'mock'] = Field(default_factory=lambda: 'model')
    max_rounds: int | None = Field(default=None, ge=1, le=6)
    idempotency_key: str = Field(min_length=1, max_length=120)

class Command(Model):
    proposal_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=120)

class Answer(Command):
    question_id: str
    actor: str = Field(min_length=1, max_length=200)
    option_id: str | None = None
    text: str | None = Field(default=None, max_length=10000)
    finalize_with_unresolved: bool = False

    @model_validator(mode='after')
    def answered(self):
        if not self.option_id and not (self.text and self.text.strip()):
            raise ValueError('Choose an option or provide an answer')
        return self

class Approval(Command):
    actor: str = Field(min_length=1, max_length=200)

class StreamEvent(Model):
    sequence: int
    run_id: str
    type: Literal['snapshot'] = 'snapshot'
    data: Run

class Health(Model):
    status: Literal['ok'] = 'ok'
    api_version: Literal['2.0'] = '2.0'
    model_configured: bool
    model: str | None
    default_max_rounds: int
