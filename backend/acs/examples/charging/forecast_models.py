"""Forecast artifacts are distinct from validated capacity recommendations."""
from datetime import datetime
from typing import Literal
from pydantic import Field
from .models import Model

class Hour(Model):
    time: datetime
    exposure_hours: float
    full_hours: float
    observed_starts: int
    mean_occupied: float | None
    mean_operational: float | None
    demand_p1: float | None
    demand_p05: float | None

class ForecastPoint(Model):
    time: datetime
    p: Literal[1.0, 0.5]
    p10: float = Field(ge=0)
    p50: float = Field(ge=0)
    p90: float = Field(ge=0)

class Score(Model):
    method: Literal['timestral', 'seasonal_naive']
    fold: int
    cutoff: datetime
    samples: int
    mae: float | None
    pinball: float | None
    coverage_80: float | None

class SiteForecast(Model):
    site_id: str
    site_name: str
    plug_ids: list[str]
    status: Literal['available', 'unavailable']
    reason: str | None
    selected_method: Literal['timestral', 'seasonal_naive'] | None
    valid_fraction: float
    evidence_ids: list[str]
    hours: list[Hour]
    points: list[ForecastPoint]
    backtest: list[Score]
    mean_occupancy_hours: float | None
    complete_episodes: int
    scenario_capacity: int | None
    limitations: list[str]

class ForecastBundle(Model):
    schema_version: Literal['1.0'] = '1.0'
    id: str
    generated_at: datetime
    origin: Literal['derived'] = 'derived'
    mode: Literal['model'] = 'model'
    model_name: str
    model_revision: str
    method_version: str
    input_sha256: str
    series_sha256: str
    input_start: datetime
    forecast_start: datetime
    horizon_hours: int
    parameters: dict
    covariates: list[str]
    sites: list[SiteForecast]
    analysis_id: str | None
    limitations: list[str]
