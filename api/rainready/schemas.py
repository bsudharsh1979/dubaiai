"""API request/response schemas (OpenAPI is generated from these)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class DemoLogin(BaseModel):
    user_id: str = Field(..., max_length=40)


class IdentityOut(BaseModel):
    id: str
    name: str
    role: str
    role_label: str
    organisation: str
    jurisdictions: list[str]
    permissions: list[str]
    approval_authority: list[str]


class ModeInfo(BaseModel):
    data_mode: str
    model_provider: str
    action_connectors: str
    sovereign_mode: bool
    demo_identity_switcher: bool
    emergency_stop: bool
    app_env: str


class HealthOut(BaseModel):
    ok: bool
    modes: ModeInfo
    database: dict
    worker: dict
    providers: list[dict]
    integrations: list[dict]
    guard_gate: dict
    time: dict


class TwinControls(BaseModel):
    rain_multiplier: float = Field(1.0, ge=0, le=5)
    drain_blockage: float = Field(0.0, ge=0, le=1)
    pump_availability: float = Field(1.0, ge=0, le=1)
    leak_rate_lps: float = Field(0.0, ge=0, le=500)
    sensor_outage: list[str] = Field(default_factory=list)
    report_reliability: Literal["normal", "low"] = "normal"
    extra_pump_m3_s: float = Field(0.0, ge=0, le=5)


class TwinSimulateIn(BaseModel):
    scenario_id: str
    controls: TwinControls
    baseline_controls: TwinControls | None = None
    horizon_min: int = Field(180, ge=30, le=360)
    persist_to_scenario: bool = False  # write controls into the scenario and trigger a reassessment of its open incidents


class ScenarioRunIn(BaseModel):
    kind: Literal["rainfall", "leak", "hse"] | None = None
    title: str | None = None


class ApprovalIn(BaseModel):
    proposal_id: str
    action_indexes: list[int] | None = None
    decision: Literal["approved", "rejected"]
    note: str = Field("", max_length=500)


class ProposalReviseIn(BaseModel):
    public_text_en: str | None = Field(None, max_length=1200)
    public_text_ar: str | None = Field(None, max_length=1200)
    recipients: list[str] | None = None
    drop_action_indexes: list[int] = Field(default_factory=list)


class WorkOrderTransitionIn(BaseModel):
    status: Literal["acknowledged", "in_progress", "completed", "rejected", "failed", "cancelled"]
    note: str = Field("", max_length=500)


class FieldReportReviewIn(BaseModel):
    review_status: Literal["accepted", "rejected", "needs_follow_up"]
    reliability: Literal["unverified", "corroborated", "disputed", "faulty"] | None = None
    attach_incident_id: str | None = None


class CloseIncidentIn(BaseModel):
    confirmation_note: str = Field(..., min_length=5, max_length=500)
    new_observation_ref: str = Field(..., description="id of an observation, field report or tool result newer than the last response")


class AssistantIn(BaseModel):
    question: str = Field(..., min_length=3, max_length=400)


class EmergencyStopIn(BaseModel):
    active: bool
    reason: str = Field("", max_length=300)


class RasterMeta(BaseModel):
    source_id: str
    acquisition_at: datetime
    available_at: datetime
    orbit: str
    polarisation: str
    preprocessing: str
    provenance_uri: str
    license_class: str
    simulation_status: Literal["synthetic", "replayed", "live"] = "synthetic"


class ImportMetadata(BaseModel):
    before: RasterMeta
    after: RasterMeta
    scenario_id: str | None = None


class GenericOk(BaseModel):
    ok: bool = True
    detail: Any = None
