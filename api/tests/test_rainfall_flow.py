"""Principal flow: rainfall → evidence → HSE → proposal → approval → simulated ack → completion → reassessment."""
from __future__ import annotations

import uuid

from .conftest import drain, login


def test_health_and_modes(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    h = r.json()
    assert h["modes"]["data_mode"] == "synthetic"
    assert h["modes"]["model_provider"] == "demo"
    assert h["modes"]["action_connectors"] == "simulated"
    assert any(p["kind"] == "guard" and p["provider"] == "deterministic_gate" for p in h["providers"])


def test_unauthenticated_blocked(client):
    client.cookies.clear()
    assert client.get("/api/incidents").status_code == 401
    assert client.post("/api/approvals", json={"proposal_id": "x", "decision": "approved"}).status_code == 401


def test_rainfall_end_to_end(client):
    login(client, "u_drain")
    r = client.post("/api/scenarios/SC-A-rainfall/run", json={})
    assert r.status_code == 200, r.text
    inc_id = r.json()["incident_id"]
    # duplicate suppression
    r2 = client.post("/api/scenarios/SC-A-rainfall/run", json={})
    assert r2.json()["duplicate_suppressed"] is True and r2.json()["incident_id"] == inc_id

    inc = client.get(f"/api/incidents/{inc_id}").json()
    assert inc["status"] == "awaiting_approval", inc["next_decision"]
    assert inc["label"] == "forecast_risk"
    assert inc["severity_band"] in {"high", "severe"}
    assert inc["calibrated_probability"] is None
    personas = {r["persona"] for r in inc["agent_runs"]}
    assert {"observer", "hydrologist", "hse_officer", "incident_coordinator", "response_planner", "communications_officer", "assurance_officer"} <= personas
    assert "utility_engineer" not in personas  # irrelevant specialist skipped
    assert inc["independent_sources"] >= 2
    assert inc["pending_interrupt"]["kind"] == "approval"
    prop = inc["proposals"][-1]
    kinds = [a["kind"] for a in prop["actions"]]
    assert "inspection" in kinds and "pump_deployment" in kinds and "hse_review" in kinds
    assert prop["public_text_en"] and prop["public_text_ar"] and prop["translation_status"] == "draft-unreviewed"
    assert "SS-7" not in prop["public_text_en"]  # sensitive asset never named publicly
    tools_used = {t["tool"] for t in inc["tool_results"]}
    assert {"run_water_balance", "assess_asset_exposure", "check_pump_capacity", "plan_route", "retrieve_procedure"} <= tools_used
    wb = next(t for t in inc["tool_results"] if t["tool"] == "run_water_balance")
    assert wb["result"]["label"] == "scenario model — uncalibrated"
    assert wb["result"]["mass_balance_max_error_m3"] < 1e-3

    # Field inspector cannot approve
    login(client, "u_field")
    r = client.post("/api/approvals", json={"proposal_id": prop["id"], "decision": "approved"}, headers={"Idempotency-Key": "k-field-1"})
    assert r.status_code == 403

    # Drainage controller approves its actions; idempotent replay returns same approval
    login(client, "u_drain")
    key = f"k-{uuid.uuid4().hex[:6]}"
    r = client.post("/api/approvals", json={"proposal_id": prop["id"], "decision": "approved", "note": "approved for inspection+pump"}, headers={"Idempotency-Key": key})
    assert r.status_code == 200, r.text
    ap = r.json()
    assert ap["work_orders"]
    r_dup = client.post("/api/approvals", json={"proposal_id": prop["id"], "decision": "approved"}, headers={"Idempotency-Key": key})
    assert r_dup.json()["idempotent_replay"] is True and r_dup.json()["approval_id"] == ap["approval_id"]
    drain()
    inc = client.get(f"/api/incidents/{inc_id}").json()
    wos = inc["work_orders"]
    dispatched = [w for w in wos if w["status"] == "dispatched"]
    assert dispatched and all(w["receipt"]["simulated"] is True for w in dispatched)
    assert inc["status"] == "responding"
    pump_wo = next(w for w in wos if w["kind"] == "pump_deployment")
    # Acknowledgement alone must not change physical state
    r = client.post(f"/api/work-orders/{pump_wo['id']}/transition", json={"status": "acknowledged", "note": "crew en route (simulated)"})
    assert r.status_code == 200
    state = client.get("/api/twin/SC-A-rainfall/state").json()
    basin = next(c for c in state["catchments"] if c["id"] == "C_underpass")
    assert "deployed_extra_pump_m3_s" not in basin["assumptions"]
    # Completion applies the effect and triggers reassessment
    r = client.post(f"/api/work-orders/{pump_wo['id']}/transition", json={"status": "completed", "note": "pump running (simulated)"})
    assert r.status_code == 200 and r.json()["physical_effect_applied"] is True
    state = client.get("/api/twin/SC-A-rainfall/state").json()
    basin = next(c for c in state["catchments"] if c["id"] == "C_underpass")
    assert basin["assumptions"]["deployed_extra_pump_m3_s"] > 0
    drain()
    inc2 = client.get(f"/api/incidents/{inc_id}").json()
    assert inc2["version"] > inc["version"]
    runs_after = [r for r in inc2["agent_runs"] if r["persona"] == "hydrologist"]
    assert len(runs_after) >= 2  # reassessed with new capacity
    peak_before = runs_after[0]["output"]["peak_depth_by_catchment_m"]["C_underpass"]
    peak_after = runs_after[-1]["output"]["peak_depth_by_catchment_m"]["C_underpass"]
    assert peak_after < peak_before


def test_twin_controls_change_outcome(client):
    login(client, "u_drain")
    base = {"scenario_id": "SC-A-rainfall", "controls": {"rain_multiplier": 1.0, "drain_blockage": 0.0, "pump_availability": 1.0}}
    worse = {"scenario_id": "SC-A-rainfall", "controls": {"rain_multiplier": 1.5, "drain_blockage": 0.6, "pump_availability": 0.0},
             "baseline_controls": {"rain_multiplier": 1.0, "drain_blockage": 0.0, "pump_availability": 1.0}}
    r0 = client.post("/api/twin/simulate", json=base).json()
    r1 = client.post("/api/twin/simulate", json=worse).json()
    d0 = r0["intervention"]["catchments"]["C_underpass"]["peak_depth_m"]
    d1 = r1["intervention"]["catchments"]["C_underpass"]["peak_depth_m"]
    assert d1 > d0
    assert r1["comparison"]["control_changes"]
    assert r1["intervention"]["label"] == "scenario model — uncalibrated"
    better = {"scenario_id": "SC-A-rainfall", "controls": {"rain_multiplier": 1.0, "drain_blockage": 0.0, "pump_availability": 1.0, "extra_pump_m3_s": 0.5}}
    r2 = client.post("/api/twin/simulate", json=better).json()
    assert r2["intervention"]["catchments"]["C_underpass"]["peak_depth_m"] < d0
    # field inspector cannot operate twin controls
    login(client, "u_field")
    assert client.post("/api/twin/simulate", json=base).status_code == 403
