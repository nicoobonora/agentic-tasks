"""Domain-neutral, additive contracts for bounded analytical capabilities."""
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime

class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')

class MetricReference(Contract):
    evidence_id: str
    path: str = Field(min_length=1, max_length=300)
    value: float
    unit: str = Field(min_length=1, max_length=80)
    site_id: str
    start: AwareDatetime
    end: AwareDatetime

class ToolRequest(Contract):
    call_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any]

class ToolOutcome(Contract):
    status: Literal['available', 'unavailable', 'needs_clarification', 'error']
    summary: str = Field(max_length=4000)
    data: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    origin: Literal['observation', 'derived_metric', 'forecast', 'simulated_business', 'human_preference'] = 'observation'
    source_fingerprint: str
    method: str
    method_version: str = '1'
    queried_at: datetime

class ToolCall(Contract):
    id: str
    run_id: str
    cycle: int
    role: str
    turn_token: str
    request: ToolRequest
    normalized_parameters: dict[str, Any]
    cache_key: str
    source_fingerprint: str = ""
    method_version: str = "1"
    created_at: datetime
    completed_at: datetime | None = None
    status: Literal['queued', 'running', 'succeeded', 'failed'] = 'queued'
    artifact_id: str | None = None
    summary: str = ''
    cached: bool = False

class AnalyticalJob(Contract):
    id: str
    tool_call_id: str
    run_id: str
    cycle: int
    role: str
    turn_token: str
    status: Literal['queued', 'running', 'succeeded', 'failed'] = 'queued'
    created_at: datetime
    deadline: datetime
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    artifact_id: str | None = None
    error: str | None = None

class TurnProgress(Contract):
    token: str
    cycle: int
    round: int
    role: str
    proposal_version: int
    provider_requests: int = 0
    tool_requests: int = 0
    pending_job_id: str | None = None
    correction: str | None = None
    started_at: datetime
    protocol: list[dict[str, Any]] = Field(default_factory=list)

class ToolArtifact(Contract):
    id: str
    run_id: str
    tool_call_id: str
    sha256: str
    outcome: ToolOutcome
