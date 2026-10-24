"""Leak and unreliable-evidence branches; raster import validation; units/mass balance; no future leakage;
unresolved routes; retrieval authorization; evaluation harness."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from rainready.clock import parse_iso
from rainready.db import session_scope
from rainready.evaluation import harness
from rainready.knowledge.retrieval import retrieve
from rainready.models import Forecast, Incident, Observation
from rainready.tools import hydrology, routing, sar
from rainready.tools.registry import ToolContext, call_tool

from .conftest import drain, login


def _cancel_all(client):
    login(client, "u_cmd")
    for i in client.get("/api/incidents").json():
        client.post(f"/api/incidents/{i['id']}/cancel")


# --- leak branch -------------------------------------------------------------
def test_leak_flow_suspected_then_confirmation_required(client):
    _cancel_all(client)
    login(client, "u_util")
    inc_id = client.post("/api/scenarios/SC-B-leak/run", json={}).json()["incident_id"]
    inc = client.get(f"/api/incidents/{inc_id}").json()
    assert inc["kind"] == "leak" and inc["label"] == "suspected_incident"
    personas = {r["persona"] for r in inc["agent_runs"]}
    assert "utility_engineer" in personas and "hydrologist" not in personas and "communications_officer" not in personas
    assert inc["status"] == "awaiting_approval"
    prop = inc["proposals"][-1]
    kinds = [a["kind"] for a in prop["actions"]]
    assert kinds == ["utility_investigation"]
    util = next(r for r in inc["agent_runs"] if r["persona"] == "utility_engineer")["output"]
    assert util["request_utility_confirmation"] is True and util["suspected_segments"] == ["SEG12"]
    # utility engineer approves investigation; field confirmation (accepted report) is required before 'confirmed'
    r = client.post("/api/approvals", json={"proposal_id": prop["id"], "decision": "approved"}, headers={"Idempotency-Key": "leak-1-" + inc_id})
    assert r.status_code == 200
    drain()
    inc = client.get(f"/api/incidents/{inc_id}").json()
    assert inc["label"] == "suspected_incident"  # approval does not confirm anything
    _cancel_all(client)


def test_leak_alternative_branch_planned_flushing_changes_outcome(client):
    _cancel_all(client)
    login(client, "u_util")
    inc_id = client.post("/api/scenarios/SC-B2-leak-flushing/run", json={}).json()["incident_id"]
    inc = client.get(f"/api/incidents/{inc_id}").json()
    util = next(r for r in inc["agent_runs"] if r["persona"] == "utility_engineer")["output"]
    assert util["label"] == "anomaly" and util["request_utility_confirmation"] is False
    assert any("planned_operation" in c for c in util["competing_explanations"])
    assert inc["label"] == "anomaly"
    assert not any(a["kind"] == "utility_investigation" for p in inc["proposals"] for a in p["actions"])
    _cancel_all(client)


# --- unreliable evidence branch ----------------------------------------------
def test_unreliable_evidence_requests_more_then_escalates(client):
    _cancel_all(client)
    login(client, "u_drain")
    inc_id = client.post("/api/scenarios/SC-C-unreliable/run", json={}).json()["incident_id"]
    inc = client.get(f"/api/incidents/{inc_id}").json()
    assert inc["status"] == "awaiting_evidence", inc["next_decision"]
    assert inc["severity_band"] in {"high", "severe"}  # high forecast band is not discarded
    stale = [e for e in inc["evidence"] if e["freshness"] == "stale"]
    poor = [e for e in inc["evidence"] if e["quality"] == "poor"]
    assert stale and poor
    assert not inc["proposals"]
    # second loop still insufficient → urgent human review (never silently dropped)
    client.post(f"/api/incidents/{inc_id}/reassess")
    drain()
    client.post(f"/api/incidents/{inc_id}/reassess")
    drain()
    inc = client.get(f"/api/incidents/{inc_id}").json()
    assert inc["status"] == "urgent_human_review", inc["next_decision"]
    _cancel_all(client)


def test_unreliable_evidence_resolves_with_reviewed_report(client):
    _cancel_all(client)
    login(client, "u_drain")
    inc_id = client.post("/api/scenarios/SC-C-unreliable/run", json={}).json()["incident_id"]
    assert client.get(f"/api/incidents/{inc_id}").json()["status"] == "awaiting_evidence"
    login(client, "u_field")
    r = client.post("/api/field-reports", data={"description": "Standing water across the U-7 approach, roughly 15 cm at the kerb, inlets partially blocked by debris.", "lat": 25.19, "lon": 55.31,
                                               "capture_time": "2026-10-24T01:50:00+00:00", "incident_id": inc_id})
    assert r.status_code == 200
    fr_id = r.json()["id"]
    login(client, "u_hse")
    assert client.post(f"/api/field-reports/{fr_id}/review", json={"review_status": "accepted", "reliability": "corroborated"}).status_code == 200
    drain()
    inc = client.get(f"/api/incidents/{inc_id}").json()
    assert inc["status"] == "awaiting_approval", inc["next_decision"]
    assert any(e["kind"] == "field_report" and e["quality"] == "good" for e in inc["evidence"])
    _cancel_all(client)


# --- closure requires new observation + human --------------------------------
def test_closure_requires_new_observation_and_commander(client):
    _cancel_all(client)
    login(client, "u_drain")
    inc_id = client.post("/api/scenarios/SC-A-rainfall/run", json={}).json()["incident_id"]
    prop = client.get(f"/api/incidents/{inc_id}").json()["proposals"][-1]
    login(client, "u_cmd")
    client.post("/api/approvals", json={"proposal_id": prop["id"], "decision": "approved"}, headers={"Idempotency-Key": "close-" + inc_id})
    drain()
    r = client.post(f"/api/incidents/{inc_id}/close", json={"confirmation_note": "all clear", "new_observation_ref": "nonexistent"})
    assert r.status_code == 409
    login(client, "u_field")
    fr = client.post("/api/field-reports", data={"description": "Underpass dry, inlets clear, pump stopped.", "lat": 25.19, "lon": 55.31, "capture_time": "2026-10-24T05:00:00+00:00", "incident_id": inc_id}).json()
    login(client, "u_drain")
    assert client.post(f"/api/incidents/{inc_id}/close", json={"confirmation_note": "clear now", "new_observation_ref": fr["id"]}).status_code == 403
    login(client, "u_cmd")
    r = client.post(f"/api/incidents/{inc_id}/close", json={"confirmation_note": "clear now", "new_observation_ref": fr["id"]})
    assert r.status_code == 409 and "reviewed" in r.text
    login(client, "u_hse")
    client.post(f"/api/field-reports/{fr['id']}/review", json={"review_status": "accepted", "reliability": "corroborated"})
    drain()
    login(client, "u_cmd")
    r = client.post(f"/api/incidents/{inc_id}/close", json={"confirmation_note": "Confirmed clear after field verification", "new_observation_ref": fr["id"]})
    assert r.status_code == 200 and r.json()["status"] == "closed"


# --- process refinements: CAP-aligned alert, SITREP, after-action review -------
def test_structured_alert_sitrep_and_after_action_review(client):
    _cancel_all(client)
    login(client, "u_drain")
    inc_id = client.post("/api/scenarios/SC-A-rainfall/run", json={}).json()["incident_id"]
    inc = client.get(f"/api/incidents/{inc_id}").json()
    prop = inc["proposals"][-1]
    adv = next(a for a in prop["actions"] if a["kind"] == "advisory")
    alert = adv["alert"]
    # CAP-aligned fields are present, mapped from bands (no probability), and inside the hashed payload
    assert alert["severity"] in {"Extreme", "Severe", "Moderate", "Minor", "Unknown"}
    assert alert["certainty"] in {"Observed", "Likely", "Possible", "Unknown"} and "not a probability" in alert["certainty_basis"]
    assert alert["message_level"] in {"Advice", "Watch and Act", "Emergency Warning"}
    assert alert["instruction_en"] and alert["instruction_ar"] and "not an official" in alert["sender"]
    assert inc["severity_band"] in {"high", "severe"} and alert["message_level"] in {"Watch and Act", "Emergency Warning"}
    # SITREP is built from persisted state only
    sr = client.get(f"/api/incidents/{inc_id}/sitrep").json()
    assert sr["basis"].startswith("persisted state") and sr["situation"]["label"] == inc["label"]
    assert sr["decisions"]["latest_proposal"]["payload_hash"] == prop["payload_hash"]
    assert sr["evidence"]["independent_sources"] == inc["independent_sources"]
    assert any("approval" in o for o in sr["open_items"])
    assert sr["after_action_review"] is None
    # closure with an after-action review stores it on the incident
    login(client, "u_cmd")
    client.post("/api/approvals", json={"proposal_id": prop["id"], "decision": "approved"}, headers={"Idempotency-Key": "aar-" + inc_id})
    drain()
    login(client, "u_field")
    fr = client.post("/api/field-reports", data={"description": "Underpass dry, inlets clear.", "lat": 25.19, "lon": 55.31, "capture_time": "2026-10-24T06:00:00+00:00", "incident_id": inc_id}).json()
    login(client, "u_hse")
    client.post(f"/api/field-reports/{fr['id']}/review", json={"review_status": "accepted", "reliability": "corroborated"})
    drain()
    login(client, "u_cmd")
    r = client.post(f"/api/incidents/{inc_id}/close", json={"confirmation_note": "Closed after verification", "new_observation_ref": fr["id"],
                                                          "after_action": {"what_was_expected": "waterlogging at U-7", "what_happened": "pump deployed, water receded", "went_well": "fast ack",
                                                                           "improve": "earlier inlet inspection", "follow_ups": ["inspect DI-7A grate"]}})
    assert r.status_code == 200, r.text
    aar = r.json()["summary"]["after_action_review"]
    assert aar["follow_ups"] == ["inspect DI-7A grate"] and aar["recorded_by"] == "u_cmd"
    sr = client.get(f"/api/incidents/{inc_id}/sitrep").json()
    assert sr["after_action_review"]["improve"] == "earlier inlet inspection" and sr["open_items"] == []


def test_audit_chain_survives_concurrent_appends(client):
    """Request threads and the worker thread append audit events concurrently; the chain
    must stay linear (no two events linking to the same predecessor)."""
    import threading
    from rainready import audit

    barrier = threading.Barrier(4)
    errors: list[BaseException] = []

    def writer(tag: str):
        try:
            barrier.wait(timeout=10)
            for i in range(15):
                with session_scope() as db:
                    audit.record(db, actor=f"t-{tag}", action="test.concurrent", subject_type="test", subject_id=f"{tag}-{i}", payload={"i": i})
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(str(n),)) for n in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=60)
    assert not errors, errors
    with session_scope() as db:
        result = audit.verify_chain(db)
    assert result["ok"], result


# --- hazard tools --------------------------------------------------------------
def test_mass_balance_and_units():
    specs = [hydrology.CatchmentSpec("up", "up", 1_000_000, 0.6, 10_000, 0.3, downstream_id="low", travel_minutes=20, mechanism="flash_flood"),
             hydrology.CatchmentSpec("low", "low", 200_000, 0.9, 3_000, 0.5, pump_capacity_m3_s=0.4, protects_asset_ids=["A"])]
    rain = {"up": [60.0] * 12 + [0.0] * 24, "low": [40.0] * 12 + [0.0] * 24}
    res = hydrology.simulate(specs, rain, hydrology.Controls(), asset_thresholds_m={"A": 0.3})
    t = res["totals_m3"]
    stored = sum(c["final_storage_m3"] for c in res["catchments"].values())
    assert abs(t["rain_in"] - (t["drained"] + t["pumped"] + t["spilled_out"] + stored)) < 1e-3
    # 60 mm/h for 1 h over 1 km² at C=0.6 → 36,000 m³ ; 40 mm/h over 0.2 km² at 0.9 → 7,200 m³
    assert abs(t["rain_in"] - (36_000 + 7_200)) < 1.0
    assert all(s["storage_m3"] >= 0 for ser in res["series"].values() for s in ser)
    assert res["catchments"]["up"]["mechanism"] == "flash_flood" and res["catchments"]["low"]["peak_depth_m"] > 0
    # upstream travel delay: downstream inflow arrives later with delay than without
    res_nd = hydrology.simulate(specs, rain, hydrology.Controls(upstream_delay_enabled=False), asset_thresholds_m={"A": 0.3})
    first_in = next(s["t_min"] for s in res["series"]["low"] if s["upstream_in_m3"] > 0)
    first_in_nd = next(s["t_min"] for s in res_nd["series"]["low"] if s["upstream_in_m3"] > 0)
    assert first_in > first_in_nd
    with pytest.raises(ValueError):
        hydrology.simulate([hydrology.CatchmentSpec("a", "a", 1, 1, 1, 1, downstream_id="b"), hydrology.CatchmentSpec("b", "b", 1, 1, 1, 1, downstream_id="a")], {}, hydrology.Controls())


def test_no_future_information_leakage():
    """Observations/forecasts available after the decision time must be invisible to tools."""
    with session_scope() as db:
        sc_time = parse_iso("2026-10-24T02:00:00+00:00")
        fut = Observation(id="ob_future_test", feed_id="water_levels", sensor_id="WL-U7", scenario_id="SC-A-rainfall", variable="m", value=9.9, source_id="t", observed_at=sc_time + timedelta(minutes=10),
                          available_at=sc_time + timedelta(minutes=11), received_at=sc_time + timedelta(minutes=11), units="m", quality_flags=[], license_class="synthetic-demo", simulation_status="synthetic")
        late = Observation(id="ob_late_avail_test", feed_id="water_levels", sensor_id="WL-U7", scenario_id="SC-A-rainfall", variable="m", value=8.8, source_id="t", observed_at=sc_time - timedelta(minutes=2),
                           available_at=sc_time + timedelta(minutes=30), received_at=sc_time + timedelta(minutes=30), units="m", quality_flags=[], license_class="synthetic-demo", simulation_status="synthetic")
        db.add_all([fut, late])
        db.flush()
        ctx = ToolContext(db=db, decision_time=sc_time, persona="observer", scenario_id="SC-A-rainfall", max_calls=5)
        w = call_tool(ctx, "read_sensor_window", {"sensor_id": "WL-U7", "minutes": 60})
        assert all(v["value"] not in (9.9, 8.8) for v in w["values"]) and w["max"] < 1
        fc_late = Forecast(id="fc_late_test", feed_id="nowcast_synthetic", scenario_id="SC-A-rainfall", variable="rain_rate_mm_h", issued_at=sc_time + timedelta(minutes=5), valid_at=sc_time + timedelta(minutes=10), value=999.0,
                           attributes={"catchment_id": "C_underpass"}, source_id="t", observed_at=sc_time + timedelta(minutes=5), available_at=sc_time + timedelta(minutes=6), received_at=sc_time + timedelta(minutes=6),
                           units="mm/h", quality_flags=[], license_class="synthetic-demo", simulation_status="synthetic")
        db.add(fc_late)
        db.flush()
        ctx2 = ToolContext(db=db, decision_time=sc_time, persona="hydrologist", scenario_id="SC-A-rainfall", max_calls=5)
        res = call_tool(ctx2, "run_water_balance", {"catchment_ids": ["C_underpass"], "horizon_min": 60})
        assert max(s["rain_mm_h"] for s in res["series"]["C_underpass"]) < 500
        assert harness.no_leakage([{"id": "x", "available_at": sc_time + timedelta(seconds=1)}], sc_time)["ok"] is False
        db.rollback()


def test_routing_excludes_flooded_and_reports_unresolved():
    links = [{"id": "a", "from_node": "A", "to_node": "B", "length_m": 100, "status": "open"}, {"id": "b", "from_node": "B", "to_node": "C", "length_m": 100, "status": "flooded"},
             {"id": "c", "from_node": "A", "to_node": "C", "length_m": 500, "status": "unknown"}]
    r = routing.shortest_path(links, "A", "C")
    assert r["status"] == "no verified route" and {e["link_id"] for e in r["excluded_links"]} == {"b", "c"}
    r2 = routing.shortest_path(links, "A", "C", allow_unknown=True)
    assert r2["status"].startswith("candidate route") and "insufficient" in r2["coverage"]


def test_raster_import_validation_and_mask(client, tmp_path):
    login(client, "u_drain")
    ok = client.post("/api/imports/sentinel1/fixture").json()
    assert ok["status"] == "processed" and ok["result"]["label"] == "candidate inundation at acquisition time"
    assert 0 < ok["result"]["summary"]["fractions"]["1"] < 0.5 and ok["result"]["summary"]["fractions"]["3"] > 0  # unknown class retained
    bad = client.post("/api/imports/sentinel1/fixture?misaligned=true").json()
    assert bad["status"] == "rejected" and any("not aligned" in p or "overlap" in p for p in bad["validation"]["problems"])
    # wrong CRS pair
    p1 = sar.write_synthetic_pair(tmp_path / "a", size=32, crs="EPSG:32640")
    p2 = sar.write_synthetic_pair(tmp_path / "b", size=32, crs="EPSG:32639")
    meta = {"orbit": "o", "polarisation": "VV", "preprocessing": "p", "acquisition_at": "t", "available_at": "t", "source_id": "s", "provenance_uri": "u", "license_class": "l"}
    v = sar.validate_pair(p1["before"], p2["after"], meta, meta)
    assert not v["ok"] and any("CRS mismatch" in p for p in v["problems"])
    # orbit mismatch
    v2 = sar.validate_pair(p1["before"], p1["after"], meta, {**meta, "orbit": "other"})
    assert not v2["ok"] and any("orbit differs" in p for p in v2["problems"])
    # synthetic segmentation metrics run on the fixture truth mask (pipeline validation only)
    res = sar.change_mask(p1["before"], p1["after"], str(tmp_path / "m.tif"), p1["permanent_water"], p1["shadow"])
    m = harness.segmentation_metrics(res["mask_path"], p1["truth_flood"])
    assert m["recall"] > 0.8 and "SYNTHETIC" in m["note"]
    login(client, "u_field")
    assert client.post("/api/imports/sentinel1/fixture").status_code == 403


def test_retrieval_authorization_and_citations():
    with session_scope() as db:
        hits = retrieve(db, "leak competing explanations planned operations", roles=["utility_engineer"], k=3)
        assert hits and hits[0]["doc_id"] == "SOP-LEAK-INVESTIGATE" and "§" in hits[0]["citation"] and hits[0]["method"] == "lexical"
        denied = retrieve(db, "leak competing explanations planned operations", roles=["field_inspector"], collection="utility", k=3)
        assert denied == []


def test_evaluation_summary_is_honest(client):
    login(client, "u_cmd")
    a = client.get("/api/assurance").json()
    ev = a["evaluation"]
    assert ev["forecast_skill"]["status"] == "not evaluated" and ev["leak_detection"]["status"] == "not evaluated"
    assert ev["agent_operation"]["dispatch_without_approval"] == 0
    assert a["audit_chain"]["ok"]
