"""SQLAlchemy ORM.  Geometry is GeoJSON (+bbox) so the same schema runs on SQLite and
PostgreSQL; the Postgres migration adds an indexed PostGIS ``geom`` column."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, TypeDecorator, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every dialect (SQLite drops tzinfo otherwise)."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class GeoMixin:
    geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # GeoJSON geometry, EPSG:4326
    crs: Mapped[str] = mapped_column(String(32), default="EPSG:4326")
    bbox_minx: Mapped[float | None] = mapped_column(Float)
    bbox_miny: Mapped[float | None] = mapped_column(Float)
    bbox_maxx: Mapped[float | None] = mapped_column(Float)
    bbox_maxy: Mapped[float | None] = mapped_column(Float)


class ProvenanceMixin:
    """Mandatory provenance envelope for every record that feeds a decision."""
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())   # or acquisition_at
    available_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    units: Mapped[str | None] = mapped_column(String(32))
    resolution: Mapped[str | None] = mapped_column(String(64))
    quality_flags: Mapped[list] = mapped_column(JSON, default=list)
    provenance_uri: Mapped[str | None] = mapped_column(String(400))
    checksum: Mapped[str | None] = mapped_column(String(80))
    license_class: Mapped[str] = mapped_column(String(40), default="synthetic-demo")
    simulation_status: Mapped[str] = mapped_column(String(24), default="synthetic")  # synthetic|replayed|live


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(48))
    organisation: Mapped[str] = mapped_column(String(120))
    jurisdictions: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Feed(Base):
    __tablename__ = "feeds"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(40))
    cadence_s: Mapped[int | None] = mapped_column(Integer)
    typical_latency_s: Mapped[int | None] = mapped_column(Integer)
    freshness_current_s: Mapped[int] = mapped_column(Integer, default=3600)   # usable for the current decision
    freshness_context_s: Mapped[int] = mapped_column(Integer, default=86400 * 30)  # usable as historical context
    access_classification: Mapped[str] = mapped_column(String(60), default="synthetic-demo")
    status: Mapped[str] = mapped_column(String(40), default="synthetic")  # synthetic|requires_authorized_access|connected
    quality_rules: Mapped[dict] = mapped_column(JSON, default=dict)


class Asset(Base, GeoMixin):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(160))
    name_ar: Mapped[str | None] = mapped_column(String(160))
    criticality: Mapped[str] = mapped_column(String(16), default="medium")
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    jurisdiction: Mapped[str] = mapped_column(String(40), default="dubai-demo")
    simulation_status: Mapped[str] = mapped_column(String(24), default="synthetic")


class Catchment(Base, GeoMixin):
    __tablename__ = "catchments"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    area_m2: Mapped[float] = mapped_column(Float)
    runoff_coefficient: Mapped[float] = mapped_column(Float)
    storage_area_m2: Mapped[float] = mapped_column(Float)  # assumed ponding footprint for depth conversion
    drain_capacity_m3_s: Mapped[float] = mapped_column(Float)
    pump_asset_id: Mapped[str | None] = mapped_column(String(40))
    downstream_id: Mapped[str | None] = mapped_column(String(40))
    travel_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    protects_asset_ids: Mapped[list] = mapped_column(JSON, default=list)
    assumptions: Mapped[dict] = mapped_column(JSON, default=dict)


class Sensor(Base, GeoMixin):
    __tablename__ = "sensors"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    feed_id: Mapped[str] = mapped_column(ForeignKey("feeds.id"))
    kind: Mapped[str] = mapped_column(String(40))
    asset_id: Mapped[str | None] = mapped_column(String(40))
    catchment_id: Mapped[str | None] = mapped_column(String(40))
    units: Mapped[str] = mapped_column(String(32))
    health: Mapped[str] = mapped_column(String(24), default="ok")  # ok|degraded|faulty|offline
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)


class Observation(Base, GeoMixin, ProvenanceMixin):
    __tablename__ = "observations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    feed_id: Mapped[str] = mapped_column(ForeignKey("feeds.id"), index=True)
    sensor_id: Mapped[str | None] = mapped_column(String(40), index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(40), index=True)
    variable: Mapped[str] = mapped_column(String(40))
    value: Mapped[float | None] = mapped_column(Float)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)


class Forecast(Base, GeoMixin, ProvenanceMixin):
    __tablename__ = "forecasts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    feed_id: Mapped[str] = mapped_column(ForeignKey("feeds.id"), index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(40), index=True)
    variable: Mapped[str] = mapped_column(String(40))
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime())
    valid_at: Mapped[datetime] = mapped_column(UTCDateTime())
    value: Mapped[float | None] = mapped_column(Float)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)


class Scene(Base, GeoMixin, ProvenanceMixin):
    __tablename__ = "scenes"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    feed_id: Mapped[str] = mapped_column(ForeignKey("feeds.id"))
    platform: Mapped[str] = mapped_column(String(40))  # sentinel-1 | sentinel-2
    scene_role: Mapped[str] = mapped_column(String(24), default="observation")  # before|after|observation
    scenario_id: Mapped[str | None] = mapped_column(String(40), index=True)
    file_path: Mapped[str | None] = mapped_column(String(400))
    orbit: Mapped[str | None] = mapped_column(String(40))
    preprocessing: Mapped[str | None] = mapped_column(String(200))
    cloud_fraction: Mapped[float | None] = mapped_column(Float)
    derived: Mapped[dict] = mapped_column(JSON, default=dict)  # masks, statistics, candidate inundation summary


class RasterImport(Base):
    __tablename__ = "raster_imports"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24))  # validated|rejected|processed
    created_by: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    before_scene_id: Mapped[str | None] = mapped_column(String(40))
    after_scene_id: Mapped[str | None] = mapped_column(String(40))
    simulation_status: Mapped[str] = mapped_column(String(24), default="synthetic")


class UtilityEvent(Base, ProvenanceMixin):
    __tablename__ = "utility_events"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    scenario_id: Mapped[str | None] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # planned_operation|maintenance|demand_change|meter_health
    segment_id: Mapped[str | None] = mapped_column(String(40))
    starts_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    description: Mapped[str] = mapped_column(Text)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)


class FieldReport(Base, GeoMixin, ProvenanceMixin):
    __tablename__ = "field_reports"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    reporter_id: Mapped[str] = mapped_column(String(40))
    scenario_id: Mapped[str | None] = mapped_column(String(40), index=True)
    incident_id: Mapped[str | None] = mapped_column(String(40), index=True)
    capture_time: Mapped[datetime | None] = mapped_column(UTCDateTime())
    description: Mapped[str] = mapped_column(Text)
    observation_text: Mapped[str] = mapped_column(Text)        # observations preserved for reviewers
    isolated_instructions: Mapped[list] = mapped_column(JSON, default=list)  # quarantined imperative content
    photo_path: Mapped[str | None] = mapped_column(String(400))
    photo_mime: Mapped[str | None] = mapped_column(String(80))
    photo_sha256: Mapped[str | None] = mapped_column(String(80))
    reliability: Mapped[str] = mapped_column(String(16), default="unverified")  # unverified|corroborated|disputed|faulty
    review_status: Mapped[str] = mapped_column(String(24), default="pending")  # pending|accepted|rejected|needs_follow_up
    safety_flags: Mapped[list] = mapped_column(JSON, default=list)
    reviewed_by: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class Scenario(Base):
    __tablename__ = "scenarios"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(32))  # rainfall|leak|unreliable_evidence|malicious_instruction
    description: Mapped[str] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    decision_time: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(24), default="seeded")
    data_mode: Mapped[str] = mapped_column(String(24), default="synthetic")


class TwinRun(Base):
    __tablename__ = "twin_runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(40), index=True)
    incident_id: Mapped[str | None] = mapped_column(String(40))
    controls: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    tool_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class Incident(Base, GeoMixin):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)  # optimistic concurrency
    scenario_id: Mapped[str | None] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # rainfall|leak|hse
    title: Mapped[str] = mapped_column(String(200))
    title_ar: Mapped[str | None] = mapped_column(String(200))
    label: Mapped[str] = mapped_column(String(32))  # observed_water|susceptibility|forecast_risk|anomaly|suspected_incident|confirmed_incident
    status: Mapped[str] = mapped_column(String(32), default="open")  # open|awaiting_evidence|awaiting_approval|urgent_human_review|responding|monitoring|closure_pending|closed|cancelled
    severity_band: Mapped[str] = mapped_column(String(16), default="low")   # low|moderate|high|severe
    risk_band: Mapped[str] = mapped_column(String(16), default="low")
    consequence: Mapped[str] = mapped_column(String(16), default="minor")
    evidence_quality: Mapped[str] = mapped_column(String(16), default="insufficient")  # insufficient|weak|adequate|strong
    calibrated_probability: Mapped[float | None] = mapped_column(Float)  # None unless a calibrated model exists
    asset_ids: Mapped[list] = mapped_column(JSON, default=list)
    jurisdiction: Mapped[str] = mapped_column(String(40), default="dubai-demo")
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    next_decision: Mapped[str | None] = mapped_column(String(300))
    evidence_loops: Mapped[int] = mapped_column(Integer, default=0)
    graph_thread_id: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    closed_by: Mapped[str | None] = mapped_column(String(40))
    dedupe_key: Mapped[str | None] = mapped_column(String(120), index=True)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # sensor|forecast|scene|field_report|tool_result|document|utility
    ref_type: Mapped[str] = mapped_column(String(40))
    ref_id: Mapped[str] = mapped_column(String(80))
    independent_source_key: Mapped[str] = mapped_column(String(80))  # repeated reports from one source share a key
    summary: Mapped[str] = mapped_column(Text)
    quality: Mapped[str] = mapped_column(String(16), default="unknown")  # unknown|poor|fair|good
    observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    available_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    freshness: Mapped[str] = mapped_column(String(16), default="current")  # current|context|stale
    conflicts_with: Mapped[list] = mapped_column(JSON, default=list)
    added_by: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str | None] = mapped_column(String(40), index=True)
    thread_id: Mapped[str] = mapped_column(String(80), index=True)
    persona: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24))  # running|completed|skipped|abstained|challenged|failed|limited
    provider: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str] = mapped_column(String(120))
    model_exercised: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    limits: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)  # structured decision summary (not chain-of-thought)
    knowledge_used: Mapped[list] = mapped_column(JSON, default=list)


class ToolResult(Base):
    __tablename__ = "tool_results"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(40), index=True)
    incident_id: Mapped[str | None] = mapped_column(String(40), index=True)
    persona: Mapped[str | None] = mapped_column(String(40))
    tool: Mapped[str] = mapped_column(String(60))
    tool_version: Mapped[str] = mapped_column(String(24))
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    args_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # tool|text|embedding|guard|vision|eo_encoder
    name: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(60))
    card_uri: Mapped[str] = mapped_column(String(300))
    calibrated: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str | None] = mapped_column(String(40), index=True)
    subject_type: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[str] = mapped_column(String(80))
    actor: Mapped[str] = mapped_column(String(80))
    decision: Mapped[str] = mapped_column(String(16))  # allow|deny|review
    checks: Mapped[list] = mapped_column(JSON, default=list)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class Proposal(Base, GeoMixin):
    __tablename__ = "proposals"
    __table_args__ = (UniqueConstraint("incident_id", "version", name="uq_proposal_version"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    incident_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="proposed")  # draft|proposed|approved|rejected|superseded|expired|executed
    actions: Mapped[list] = mapped_column(JSON, default=list)
    public_text_en: Mapped[str] = mapped_column(Text, default="")
    public_text_ar: Mapped[str] = mapped_column(Text, default="")
    translation_status: Mapped[str] = mapped_column(String(24), default="draft-unreviewed")
    recipients: Mapped[list] = mapped_column(JSON, default=list)
    assumptions: Mapped[list] = mapped_column(JSON, default=list)
    payload_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    policy_decision_id: Mapped[str | None] = mapped_column(String(40))


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(40), index=True)
    proposal_id: Mapped[str] = mapped_column(String(40), index=True)
    proposal_version: Mapped[int] = mapped_column(Integer)
    incident_version: Mapped[int] = mapped_column(Integer)
    payload_hash: Mapped[str] = mapped_column(String(64))
    intended_tools: Mapped[list] = mapped_column(JSON, default=list)
    destinations: Mapped[list] = mapped_column(JSON, default=list)
    approver_id: Mapped[str] = mapped_column(String(40))
    approver_role: Mapped[str] = mapped_column(String(48))
    decision: Mapped[str] = mapped_column(String(16))  # approved|rejected
    note: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|consumed|expired|invalidated
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class WorkOrder(Base):
    __tablename__ = "work_orders"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(40), index=True)
    proposal_id: Mapped[str] = mapped_column(String(40), index=True)
    approval_id: Mapped[str | None] = mapped_column(String(40))
    action_index: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))  # inspection|pump_deployment|access_control|utility_investigation|advisory|hse_review
    department: Mapped[str] = mapped_column(String(80))
    connector: Mapped[str] = mapped_column(String(40), default="simulated")
    status: Mapped[str] = mapped_column(String(24), default="proposed")  # proposed|approved|dispatched|acknowledged|in_progress|completed|rejected|failed|expired|cancelled
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    dispatched_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    escalation_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    physical_effect: Mapped[dict] = mapped_column(JSON, default=dict)  # applied only on completion
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class DispatchReceipt(Base):
    __tablename__ = "dispatch_receipts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    work_order_id: Mapped[str] = mapped_column(String(40), index=True)
    connector: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24))
    receipt: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class AuditEvent(Base):
    """Append-only, hash-linked application audit log.  Each row's hash covers
    its content plus the previous hash; the export endpoint recomputes the chain."""
    __tablename__ = "audit_events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime())
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(80), index=True)
    subject_type: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[str] = mapped_column(String(20))
    section: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    collection: Mapped[str] = mapped_column(String(60), index=True)
    access_roles: Mapped[list] = mapped_column(JSON, default=list)
    body: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120))


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued|running|done|failed|cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    scope: Mapped[str] = mapped_column(String(60))
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class Crew(Base, GeoMixin):
    __tablename__ = "crews"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    department: Mapped[str] = mapped_column(String(80))
    capability: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="available")  # available|assigned|off_shift
    assigned_incident_id: Mapped[str | None] = mapped_column(String(40))


class RoadLink(Base, GeoMixin):
    __tablename__ = "road_links"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    from_node: Mapped[str] = mapped_column(String(40), index=True)
    to_node: Mapped[str] = mapped_column(String(40), index=True)
    length_m: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), default="open")  # open|flooded|closed|unknown
    emergency_route: Mapped[bool] = mapped_column(Boolean, default=False)
    asset_id: Mapped[str | None] = mapped_column(String(40))


Index("ix_obs_feed_time", Observation.feed_id, Observation.observed_at)
Index("ix_fc_feed_valid", Forecast.feed_id, Forecast.valid_at)
