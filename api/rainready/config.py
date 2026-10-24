"""Application settings.

Three independent provenance switches are exposed everywhere in the UI:

* ``DATA_MODE``        — where inputs come from (synthetic | historical_replay | connected)
* ``MODEL_PROVIDER``   — where inference comes from (demo | local_nim | approved_hosted)
* ``ACTION_CONNECTORS`` — simulated | connected (connected is refused in this MVP)

Connected data mode stays disabled until authorized adapters are configured;
a provider is never switched silently.  Secrets are server-only.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = API_DIR / "data"
FIXTURE_DIR = API_DIR / "rainready" / "seed" / "fixtures"
SOP_DIR = API_DIR / "rainready" / "knowledge" / "sops"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=API_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["local", "hosted", "production"] = "local"
    app_name: str = "RainReady UAE — Sovereign Water & HSE Command"
    host: str = "127.0.0.1"
    port: int = 8100
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3100", "http://127.0.0.1:3100"])
    static_dir: str = ""  # when set, the API serves the exported Next.js site from this folder

    # Provenance switches ----------------------------------------------------
    data_mode: Literal["synthetic", "historical_replay", "connected"] = "synthetic"
    model_provider: Literal["demo", "local_nim", "approved_hosted"] = "demo"
    action_connectors: Literal["simulated", "connected"] = "simulated"
    sovereign_mode: bool = True  # local retrieval/inference/guards/logs only; no cloud fallback ever

    # Persistence -------------------------------------------------------------
    database_url: str = f"sqlite:///{(DATA_DIR / 'rainready.db').as_posix()}"
    auto_migrate: bool = True
    auto_seed: bool = True
    attachments_dir: str = (DATA_DIR / "attachments").as_posix()
    rasters_dir: str = (DATA_DIR / "rasters").as_posix()

    # Identity ----------------------------------------------------------------
    demo_auth: bool = True  # passwordless identity switcher (demo only; server still owns the session)
    session_secret: str = "change-me-rainready-0123456789abcdef"
    session_cookie_name: str = "rainready_session"
    session_max_age_s: int = 60 * 60 * 12
    cookie_secure: bool = False

    # Operations --------------------------------------------------------------
    timezone: str = "Asia/Dubai"
    demo_clock_default: str = "2026-10-24T06:00:00+04:00"
    approval_ttl_minutes: int = 30
    ack_escalation_minutes: int = 15
    max_evidence_loops: int = 2
    retry_budget: int = 3
    emergency_stop: bool = False

    # Text planning provider (shared by all personas) -----------------------
    llm_base_url: str = ""          # e.g. http://nim-llm:8000/v1 (local_nim) or an allow-listed hosted URL
    llm_model: str = ""             # served model id — discovered via /v1/models, never assumed
    llm_api_key: str = ""
    llm_timeout_s: float = 90.0
    llm_max_tool_iterations: int = 6
    llm_max_tokens: int = 1500
    provider_allowlist: list[str] = Field(default_factory=lambda: ["http://localhost", "http://127.0.0.1", "http://nim-", "https://integrate.api.nvidia.com"])

    # Embeddings / rerank -----------------------------------------------------
    embed_base_url: str = ""
    embed_model: str = ""
    embed_api_key: str = ""
    rerank_base_url: str = ""
    rerank_model: str = ""

    # Guards ------------------------------------------------------------------
    guard_content_safety_url: str = ""   # nemotron content-safety (chat-completions contract)
    guard_content_safety_model: str = ""
    guard_jailbreak_url: str = ""         # NemoGuard JailbreakDetect classification API
    guard_api_key: str = ""
    guard_required_for_publication: bool = False  # when True and the guard adapter is down, publication is blocked

    # Optional visual evidence ------------------------------------------------
    vision_base_url: str = ""
    vision_model: str = ""
    vision_api_key: str = ""

    # Worker ------------------------------------------------------------------
    worker_enabled: bool = True
    worker_poll_s: float = 1.0

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def demo_identity_switcher_enabled(self) -> bool:
        return self.demo_auth and self.app_env != "production"

    @model_validator(mode="after")
    def _guards(self) -> "Settings":
        if self.app_env == "production":
            if self.demo_auth:
                raise RuntimeError("Refusing to start: DEMO_AUTH=true is not allowed when APP_ENV=production")
            if self.session_secret.startswith("change-me"):
                raise RuntimeError("Refusing to start: SESSION_SECRET must be set in production")
        if self.action_connectors == "connected":
            raise RuntimeError("ACTION_CONNECTORS=connected is not available in this MVP: no real valve/power/evacuation control exists")
        if self.data_mode == "connected":
            raise RuntimeError("DATA_MODE=connected requires authorized feed adapters and validation that are not configured")
        if self.model_provider != "demo" and self.llm_base_url and not any(self.llm_base_url.startswith(p) for p in self.provider_allowlist):
            raise RuntimeError(f"LLM_BASE_URL {self.llm_base_url!r} is not in PROVIDER_ALLOWLIST")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
