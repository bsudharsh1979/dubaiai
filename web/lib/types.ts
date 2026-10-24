export type Scenario = {
  id: string;
  name: string;
  kind: string;
  description: string;
  params: Record<string, unknown> & { title?: string; title_ar?: string; controls?: Record<string, unknown>; area_geometry?: GeoJSON.Geometry; depot_node?: string; target_node?: string };
  decision_time: string;
  decision_time_dubai: string;
  status: string;
  data_mode: string;
  open_incidents: string[];
};

export type Incident = {
  id: string;
  version: number;
  scenario_id: string;
  kind: string;
  title: string;
  title_ar: string | null;
  label: string;
  status: string;
  severity_band: string | null;
  risk_band: string | null;
  consequence: string | null;
  evidence_quality: string | null;
  calibrated_probability: number | null;
  probability_note: string | null;
  asset_ids: string[];
  jurisdiction: string;
  summary: Record<string, unknown> & { hydrology?: Record<string, unknown>; hse?: { consequence_band?: string; exposed?: number; routes?: unknown[] }; utility?: Record<string, unknown>; evidence_requests?: unknown[] };
  next_decision: string | null;
  geometry: GeoJSON.Geometry | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  closed_by: string | null;
};

export type Evidence = {
  id: string;
  kind: string;
  ref_type: string;
  ref_id: string;
  source_key: string;
  summary: string;
  quality: string;
  freshness: string;
  observed_at: string | null;
  available_at: string | null;
  conflicts_with: string[];
  added_by: string;
};

export type AgentRun = {
  id: string;
  persona: string;
  status: string;
  provider: string;
  model_id: string | null;
  model_exercised: boolean;
  started_at: string;
  finished_at: string | null;
  tool_call_count: number;
  token_count: number | null;
  limits: Record<string, unknown>;
  output: Record<string, unknown> | null;
  knowledge_used: unknown[];
  thread_id: string;
};

export type ToolResult = {
  id: string;
  run_id: string | null;
  persona: string;
  tool: string;
  version: string;
  args: Record<string, unknown>;
  ok: boolean;
  duration_ms: number;
  created_at: string;
  result: unknown;
};

export type Action = {
  kind: string;
  department: string;
  summary: string;
  target_asset_id: string | null;
  crew_id: string | null;
  route: { nodes?: string[]; status?: string; label?: string; geometry?: GeoJSON.Geometry } | null;
  requires_authority: string;
  physical_effect: Record<string, unknown>;
};

export type Proposal = {
  id: string;
  incident_id: string;
  version: number;
  incident_version: number;
  status: string;
  actions: Action[];
  public_text_en: string | null;
  public_text_ar: string | null;
  translation_status: string | null;
  recipients: string[];
  assumptions: string[];
  payload_hash: string;
  created_by: string;
  created_at: string;
  policy_decision_id: string | null;
  area: GeoJSON.Geometry | null;
};

export type Approval = {
  id: string;
  proposal_id: string;
  proposal_version: number;
  incident_version: number;
  payload_hash: string;
  intended_tools: string[];
  destinations: string[];
  approver_id: string;
  approver_role: string;
  decision: string;
  note: string;
  expires_at: string | null;
  status: string;
  consumed_at: string | null;
  created_at: string;
};

export type WorkOrder = {
  id: string;
  incident_id: string;
  proposal_id: string;
  approval_id: string | null;
  action_index: number;
  kind: string;
  department: string;
  connector: string;
  status: string;
  payload: Record<string, unknown> & { summary?: string; target_asset_id?: string; public_text_en?: string; public_text_ar?: string };
  retry_count: number;
  dispatched_at: string | null;
  acknowledged_at: string | null;
  completed_at: string | null;
  escalation_due_at: string | null;
  physical_effect: Record<string, unknown>;
  physical_effect_applied: boolean;
  receipt: Record<string, unknown> | null;
  created_at: string;
};

export type PolicyDecision = {
  id: string;
  subject_type: string;
  subject_id: string;
  actor: string;
  decision: string;
  reasons: string[];
  checks: unknown[] | number;
  created_at: string;
};

export type FieldReport = {
  id: string;
  reporter_id: string;
  scenario_id: string | null;
  incident_id: string | null;
  capture_time: string | null;
  created_at: string;
  description: string;
  observation_text: string;
  isolated_instructions: string[];
  has_photo: boolean;
  photo_mime: string | null;
  photo_sha256: string | null;
  reliability: string;
  review_status: string;
  safety_flags: string[];
  reviewed_by: string | null;
  geometry: GeoJSON.Geometry | null;
  quality_flags: string[];
};

export type IncidentDetail = Incident & {
  pending_interrupt: Record<string, unknown> | null;
  evidence: Evidence[];
  independent_sources: number;
  agent_runs: AgentRun[];
  tool_results: ToolResult[];
  proposals: Proposal[];
  approvals: Approval[];
  work_orders: WorkOrder[];
  policy_decisions: PolicyDecision[];
  field_reports: FieldReport[];
};

export type ProviderStatus = {
  kind: string;
  provider: string;
  configured: boolean;
  healthy: boolean;
  model_id: string;
  detail: string;
  exercised: boolean;
  extra: Record<string, unknown>;
};

export type TwinSeriesPoint = { t_min: number; rain_mm_h: number; inflow_m3: number; upstream_in_m3: number; drained_m3: number; pumped_m3: number; spilled_m3: number; storage_m3: number; depth_m: number; band: string };

export type TwinResult = {
  tool_version: string;
  label: string;
  dt_min: number;
  horizon_min: number;
  controls: Record<string, unknown>;
  assumptions: string[];
  catchments: Record<string, { name: string; mechanism: string; peak_depth_m: number; worst_band: string; final_storage_m3: number; protects: string[] }>;
  series: Record<string, TwinSeriesPoint[]>;
  snapshots: Record<string, Record<string, { depth_m: number; storage_m3: number; band: string }>>;
  totals_m3: Record<string, number>;
  mass_balance_max_error_m3: number;
  overall_band: string;
  forecast_total_mm?: Record<string, number>;
  asset_thresholds_m?: Record<string, number>;
  evidence_effects?: Record<string, unknown>;
};

export type TwinResponse = {
  twin_run_id: string;
  baseline: TwinResult;
  intervention: TwinResult;
  comparison: { per_catchment: Record<string, { baseline_peak_depth_m: number; intervention_peak_depth_m: number; delta_depth_m: number; baseline_band: string; intervention_band: string }>; control_changes: Record<string, [unknown, unknown]>; label: string };
  label: string;
  persisted?: unknown;
};
