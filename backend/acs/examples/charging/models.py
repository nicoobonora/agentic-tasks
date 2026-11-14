"""Canonical v1 contracts. OpenAPI/JSON Schema/TypeScript are generated from here."""
from datetime import datetime, date
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator

Origin = Literal["real", "derived", "simulated", "scenario_assumption"]

class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Error(Model):
    code: str
    message: str
    details: Any = None

class Coordinates(Model):
    srid: int = 4326
    x: float
    y: float

class Site(Model):
    id: str
    name: str
    source: str
    coordinates: Coordinates | None
    metadata: dict[str, Any]
    origin: Literal["real"] = "real"
    evidence_id: str

class Plug(Model):
    id: str
    site_id: str
    name: str
    source: str
    connectors: list[dict[str, Any]]
    origin: Literal["real"] = "real"
    evidence_id: str

class Observation(Model):
    id: str
    plug_id: str
    observed_at: datetime
    transaction_at: datetime
    status: str  # preserve unknown future OCPI values
    source_page_id: str

class ObservationPage(Model):
    items: list[Observation]
    limit: int
    offset: int
    total: int

class Evidence(Model):
    id: str
    url: str
    acquired_at: datetime | None
    sha256: str
    row_count: int
    kind: str
    origin: Origin = "real"
    raw_url: str

class LiveData(Model):
    mode: Literal["live", "snapshot"]
    fetched_at: datetime | None
    stale: bool
    warning: str | None = None
    items: list[Observation]

class Quality(Model):
    plug_id: str
    origin: Literal["derived"] = "derived"
    flags: list[str]
    observed_episode_starts: int
    covered_seconds: float
    unavailable_fraction: float | None
    longest_unavailable_seconds: float
    first_observation: datetime | None
    last_observation: datetime | None
    method: str
    dc_unavailability_validated: bool | None

class Cell(Model):
    p: Literal[1.0, 0.5]
    quantile: Literal["p50", "high"]
    status: Literal["available", "unavailable"]
    reason: str | None = None
    demand_per_hour: float | None = Field(default=None, ge=0)
    mean_occupancy_hours: float | None = Field(default=None, gt=0)
    access_current: float | None = Field(default=None, ge=0, le=1)
    access_plus_2: float | None = Field(default=None, ge=0, le=1)
    access_plus_4: float | None = Field(default=None, ge=0, le=1)
    access_restored: float | None = Field(default=None, ge=0, le=1)
    required_total_capacity: int | None = Field(default=None, ge=0)
    minimum_increment: Literal[0, 2, 4] | None = None

    @model_validator(mode="after")
    def consistency(self):
        metrics = [self.demand_per_hour, self.mean_occupancy_hours, self.access_current,
                   self.access_plus_2, self.access_plus_4, self.required_total_capacity]
        if self.status == "available" and any(v is None for v in metrics):
            raise ValueError("Available cells require demand, duration, access probabilities and required capacity")
        if self.status == "unavailable" and (not self.reason or any(v is not None for v in metrics) or self.minimum_increment is not None or self.access_restored is not None):
            raise ValueError("Unavailable cells require a reason and null metrics")
        return self

class ControlTable(Model):
    schema_version: Literal["1.0"] = "1.0"
    site_name: Literal["BZ_C_RISPARMIO_01", "BZ_PIAVE_01", "RENON_01"]
    group: Literal["AC_22"] = "AC_22"
    origin: Literal["derived"] = "derived"
    method: Literal["timestral", "seasonal_naive", "seasonal_naive_trend", "reserve"]
    period_start: date
    period_end: date
    measure_nature: str
    high_quantile_definition: Literal["daily_p90_curve", "historical_percentile_90", "pointwise_p90_peak"]
    operational_capacity: int = Field(ge=0)
    registry_capacity: int = Field(ge=0)
    restored_capacity: int | None = Field(default=None, ge=0)
    service_threshold: float = Field(gt=0, lt=1)
    cells: list[Cell] = Field(min_length=4, max_length=4)
    evidence_ids: list[str] = Field(min_length=1)
    limitations: list[str]

    @model_validator(mode="after")
    def complete_grid(self):
        if {(c.p,c.quantile) for c in self.cells} != {(1.,"p50"),(1.,"high"),(.5,"p50"),(.5,"high")}:
            raise ValueError("Expected exactly the p × quantile 2x2 grid")
        if self.period_end < self.period_start:
            raise ValueError("Invalid period")
        if self.operational_capacity > self.registry_capacity:
            raise ValueError("Operational capacity cannot exceed registry")
        if self.method == "reserve" and self.high_quantile_definition != "historical_percentile_90":
            raise ValueError("Reserve is not a forecast P90")
        return self

class AnalysisBundle(Model):
    schema_version: Literal["1.0"] = "1.0"
    id: str
    generated_at: datetime
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_start: datetime
    input_end: datetime
    method_version: str
    cleaning_parameters: dict[str, Any]
    reconstruction_parameters: dict[str, Any]
    model_name: str | None
    model_version: str | None
    covariates: list[str]
    backtest: dict[str, Any]
    tables: list[ControlTable] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def sites(self):
        if {t.site_name for t in self.tables} != {"BZ_C_RISPARMIO_01", "BZ_PIAVE_01", "RENON_01"}:
            raise ValueError("Expected the three frozen sites")
        if self.input_end <= self.input_start:
            raise ValueError("Invalid input interval")
        return self

class Catalog(Model):
    schema_version: Literal["1.0"] = "1.0"
    origin: Literal["scenario_assumption"] = "scenario_assumption"
    policy: dict[str, Any]
    site_assessments: list[dict[str, Any]]
    products: list[dict[str, Any]]
    offers: list[dict[str, Any]]
    work_schedule: list[dict[str, Any]]
    contract_terms: list[dict[str, Any]]
    economic_parameters: list[dict[str, Any]]

class Episode(Model):
    id: str
    plug_id: str
    start: datetime
    end: datetime
    duration_seconds: float
    left_censored: bool
    right_censored: bool
    short: bool
    prolonged: bool

class Health(Model):
    status: Literal["ok"] = "ok"
    api_version: Literal["1.0"] = "1.0"
    sites: int
    plugs: int
    observations: int
    normalized: bool
