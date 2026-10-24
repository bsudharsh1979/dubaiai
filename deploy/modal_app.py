"""Modal deployment for RainReady UAE (prototype).

One CPU container serves the FastAPI API, the embedded worker and the exported
Next.js site.  State lives in SQLite (domain DB + LangGraph checkpoints) on a Modal
Volume; because Volumes are last-write-wins the app is pinned to one container and the
SQLite files are copied back on a timer and at shutdown.

Guardrails that hold in the hosted deployment (all enforced server-side):
  * APP_ENV=hosted, DEMO_AUTH=true  → demo identity switcher stays available, but the
    role always comes from the signed server cookie; a client-supplied role never authorizes.
  * ACTION_CONNECTORS=simulated (the only value the code accepts) → no real valve/power/
    evacuation endpoint exists; dispatch produces simulated receipts only.
  * DATA_MODE=synthetic; MODEL_PROVIDER=demo by default (visible "rehearsal" label).
    The optional competition-gate function below uses the allow-listed NVIDIA endpoint
    through the ``approved_hosted`` provider in a *separate* process and never changes the
    public deployment's provider.
  * SOVEREIGN_MODE=true on the public app: no cloud fallback, provider allowlist enforced.
  * SESSION_SECRET and any API key come from Modal Secrets (server-only), never from the client.
  * COOKIE_SECURE=true; security headers set by the app.

Deploy:
    cd rainready/web && npm run build
    modal deploy rainready/deploy/modal_app.py
Secrets:
    modal secret create rainready SESSION_SECRET=<random 32+ chars>
    (optional, for the gate check) existing secret `nvidia-api-key` with NVIDIA_API_KEY
Gate check (real model inference, results printed, nothing persisted to the public app):
    modal run rainready/deploy/modal_app.py::model_gate_check
"""
from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "api"
WEB_OUT = ROOT / "web" / "out"

APP_NAME = "rainready-uae"
VOLUME_NAME = "rainready-uae-data"
VOLUME_MOUNT = "/data"
LOCAL_DATA = "/tmp/rainready"
SYNC_INTERVAL_S = 30

if modal.is_local() and not WEB_OUT.exists():
    raise SystemExit("rainready/web/out missing — run `npm run build` in rainready/web before deploying")

base_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libexpat1")  # rasterio wheels are self-contained; expat is needed by GDAL's XML parsing
    .pip_install_from_requirements(str(API / "requirements.lock.txt"))
)


def _with_sources(img: modal.Image) -> modal.Image:
    """Local files are added last so Modal mounts them at startup instead of rebuilding the image."""
    return (
        img.add_local_dir(str(API / "rainready"), remote_path="/app/api/rainready")
        .add_local_dir(str(API / "alembic"), remote_path="/app/api/alembic")
        .add_local_file(str(API / "alembic.ini"), remote_path="/app/api/alembic.ini")
        .add_local_dir(str(WEB_OUT), remote_path="/app/web/out")
    )


image = _with_sources(
    base_image.env({
        "APP_ENV": "hosted",
        "DEMO_AUTH": "true",
        "COOKIE_SECURE": "true",
        "AUTO_MIGRATE": "true",
        "AUTO_SEED": "true",
        "WORKER_ENABLED": "true",
        "DATA_MODE": "synthetic",
        "MODEL_PROVIDER": "demo",
        "ACTION_CONNECTORS": "simulated",
        "SOVEREIGN_MODE": "true",
        "DATABASE_URL": f"sqlite:///{LOCAL_DATA}/rainready.db",
        "ATTACHMENTS_DIR": f"{LOCAL_DATA}/attachments",
        "RASTERS_DIR": f"{LOCAL_DATA}/rasters",
        "STATIC_DIR": "/app/web/out",
        "PYTHONUNBUFFERED": "1",
    })
)

app = modal.App(APP_NAME)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
secrets = [modal.Secret.from_name("rainready", required_keys=["SESSION_SECRET"])]


def _copy_db_files(src: str, dst: str) -> None:
    Path(dst).mkdir(parents=True, exist_ok=True)
    for p in Path(src).glob("*.db*"):
        shutil.copy2(p, Path(dst) / p.name)


def _checkpoint_and_sync() -> None:
    import sqlite3

    for db in Path(LOCAL_DATA).glob("*.db"):
        con = sqlite3.connect(db)
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            con.close()
    _copy_db_files(LOCAL_DATA, VOLUME_MOUNT)
    volume.commit()


@app.cls(image=image, volumes={VOLUME_MOUNT: volume}, secrets=secrets, max_containers=1, scaledown_window=15 * 60, timeout=60 * 60)
@modal.concurrent(max_inputs=50)
class Server:
    @modal.enter()
    def start(self):
        volume.reload()
        Path(LOCAL_DATA).mkdir(parents=True, exist_ok=True)
        _copy_db_files(VOLUME_MOUNT, LOCAL_DATA)
        self._stop = threading.Event()

        def loop():
            while not self._stop.wait(SYNC_INTERVAL_S):
                try:
                    _checkpoint_and_sync()
                except Exception as exc:  # noqa: BLE001 — never kill the server over a sync hiccup
                    print(f"[sync] {exc!r}")

        threading.Thread(target=loop, daemon=True).start()

    @modal.exit()
    def stop(self):
        self._stop.set()
        try:
            _checkpoint_and_sync()
        except Exception as exc:  # noqa: BLE001
            print(f"[sync@exit] {exc!r}")

    @modal.asgi_app()
    def web(self):
        import sys

        sys.path.insert(0, "/app/api")
        os.chdir("/app/api")
        from rainready.main import create_app

        return create_app()


# ---------------------------------------------------------------------------
# Competition gate: run the real bounded workflow with model inference.  This runs in
# its own container with a throw-away SQLite DB, MODEL_PROVIDER=approved_hosted and the
# allow-listed NVIDIA endpoint.  SOVEREIGN_MODE is reported false for this run because a
# hosted endpoint is used; nothing here changes the public deployment.
gate_image = _with_sources(
    base_image.env({
        "APP_ENV": "hosted",
        "DEMO_AUTH": "true",
        "AUTO_MIGRATE": "true",
        "AUTO_SEED": "true",
        "DATA_MODE": "synthetic",
        "ACTION_CONNECTORS": "simulated",
        "DATABASE_URL": "sqlite:////tmp/gate/rainready.db",
        "ATTACHMENTS_DIR": "/tmp/gate/attachments",
        "RASTERS_DIR": "/tmp/gate/rasters",
        "WORKER_ENABLED": "false",
        "MODEL_PROVIDER": "approved_hosted",
        "SOVEREIGN_MODE": "false",
        "LLM_BASE_URL": "https://integrate.api.nvidia.com/v1",
        "LLM_TIMEOUT_S": "120",
        "PYTHONUNBUFFERED": "1",
    })
)


@app.function(image=gate_image, secrets=[modal.Secret.from_name("nvidia-api-key")], timeout=60 * 30)
def model_gate_check(model: str = "", scenario: str = "SC-A-rainfall", list_only: bool = False) -> dict:
    """Discover served models, pick the configured Nemotron id if present, run one incident end-to-end
    and report, truthfully, whether model inference was exercised and whether outputs validated."""
    import json
    import sys
    import time

    sys.path.insert(0, "/app/api")
    os.chdir("/app/api")
    key = os.environ.get("NVIDIA_API_KEY") or os.environ.get("LLM_API_KEY") or ""
    if not key:
        return {"ok": False, "error": "secret nvidia-api-key does not expose NVIDIA_API_KEY/LLM_API_KEY; no inference attempted"}
    os.environ["LLM_API_KEY"] = key
    import httpx

    with httpx.Client(timeout=30) as c:
        r = c.get("https://integrate.api.nvidia.com/v1/models", headers={"Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            return {"ok": False, "error": f"/v1/models returned {r.status_code}: {r.text[:300]}"}
        served = sorted(m.get("id") for m in r.json().get("data", []))
    candidates = [m for m in served if "nemotron" in m.lower()]
    if list_only:
        out = {"ok": True, "served_count": len(served), "nemotron_candidates": candidates}; print(json.dumps(out, indent=1)); return out
    preferred = [model] if model else ["nvidia/nemotron-3-nano-30b-a3b", "nvidia/nemotron-3-nano-30b-a3b-bf16", "nvidia/llama-3.3-nemotron-super-49b-v1.5", "nvidia/llama-3.1-nemotron-nano-8b-v1"]
    chosen = next((m for m in preferred if m in served), None)
    if not chosen:
        out = {"ok": False, "error": "none of the preferred Nemotron ids are served", "nemotron_candidates": candidates[:40]}; print(json.dumps(out, indent=1)); return out
    os.environ["LLM_MODEL"] = chosen

    from rainready.config import get_settings
    get_settings.cache_clear()
    from rainready import bootstrap, worker
    from rainready.agents import runner
    from rainready.db import reset_engine, session_scope
    from rainready.models import AgentRun, Incident, Proposal, Scenario, ToolResult
    from rainready.providers.registry import get_providers
    from sqlalchemy import select

    Path("/tmp/gate").mkdir(parents=True, exist_ok=True)
    reset_engine()
    bootstrap.startup()
    get_providers.cache_clear()
    status = get_providers().text.status().__dict__
    with session_scope() as db:
        sc = db.get(Scenario, scenario)
        if not sc:
            return {"ok": False, "error": f"unknown scenario {scenario}"}
        kind = sc.kind if sc.kind in {"rainfall", "leak", "hse"} else "rainfall"
    t0 = time.time()
    inc_id = runner.start_incident(scenario, kind, "gate-check")
    elapsed = time.time() - t0
    with session_scope() as db:
        inc = db.get(Incident, inc_id)
        runs = db.execute(select(AgentRun).where(AgentRun.incident_id == inc_id)).scalars().all()
        tools = db.execute(select(ToolResult).where(ToolResult.incident_id == inc_id)).scalars().all()
        props = db.execute(select(Proposal).where(Proposal.incident_id == inc_id)).scalars().all()
        exercised = [r for r in runs if r.model_exercised and r.status == "completed"]
        failed = [r for r in runs if r.status == "failed"]
        report = {
            # ok == the gate itself: at least one persona executed by the real model with a validated output, and none failed.
            "ok": bool(exercised) and not failed,
            "gate": "passed" if (exercised and not failed) else ("not passed — no persona exercised by the model" if not exercised else "not passed — persona failures"),
            "model": chosen,
            "provider_status": status,
            "incident": {"id": inc.id, "status": inc.status, "label": inc.label, "severity_band": inc.severity_band, "consequence": inc.consequence, "next_decision": inc.next_decision},
            "elapsed_s": round(elapsed, 1),
            "agent_runs": [{"persona": r.persona, "status": r.status, "provider": r.provider, "model_id": r.model_id, "exercised": r.model_exercised, "tool_calls": r.tool_call_count, "tokens": r.token_count,
                            "error": (r.output or {}).get("error") if isinstance(r.output, dict) else None,
                            "ms": int((r.finished_at - r.started_at).total_seconds() * 1000) if r.finished_at and r.started_at else None} for r in runs],
            "tool_results": len(tools),
            "proposals": [{"version": p.version, "actions": [a.get("kind") for a in p.actions]} for p in props],
        }
    print(json.dumps(report, indent=1, default=str))
    return report
