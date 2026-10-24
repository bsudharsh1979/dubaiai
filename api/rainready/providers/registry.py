"""Provider wiring + status for the Assurance view.  Nothing here ever downgrades
silently: a mis-configured provider reports ``healthy=False`` and planning runs
return a visible error instead of a fixture relabelled as model output."""
from __future__ import annotations

from functools import lru_cache

import httpx

from ..config import Settings, get_settings
from .base import PlanResult, ProviderStatus
from .guard import CompositeGuard
from .nim import OpenAICompatiblePlanner


class DemoPlanner:
    """Deterministic rehearsal planner.  The persona's demo policy produces the output;
    this class only exists so the status is reported honestly."""
    name = "demo"

    def plan(self, *a, **k) -> PlanResult:  # pragma: no cover - personas call their demo policy directly
        return PlanResult(output={}, tool_calls=[], model_id="deterministic-template", provider="demo", exercised=False, basis="deterministic")

    def status(self) -> ProviderStatus:
        return ProviderStatus(kind="text", provider="demo", configured=True, healthy=True, model_id="deterministic-template/1.0",
                              detail="Rehearsal mode: persona outputs are deterministic templates driven by tool results; no model inference.", exercised=False,
                              extra={"cloud_fallback": False})


class EmbeddingAdapter:
    """OpenAI-style /v1/embeddings (NIM embedding containers expose this contract; the served id is discovered, not assumed)."""

    def __init__(self, s: Settings):
        self.s = s
        self._exercised = False
        self._served: list[str] | None = None

    def served(self) -> list[str]:
        if self._served is None:
            try:
                with httpx.Client(timeout=8) as c:
                    r = c.get(f"{self.s.embed_base_url.rstrip('/')}/models", headers=self._h())
                    r.raise_for_status()
                    self._served = [m.get("id") for m in r.json().get("data", [])]
            except Exception:  # noqa: BLE001
                self._served = []
        return self._served

    def _h(self):
        return {"Authorization": f"Bearer {self.s.embed_api_key}"} if self.s.embed_api_key else {}

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not (self.s.embed_base_url and self.s.embed_model):
            return None
        try:
            with httpx.Client(timeout=30) as c:
                r = c.post(f"{self.s.embed_base_url.rstrip('/')}/embeddings", headers=self._h(), json={"model": self.s.embed_model, "input": texts, "input_type": "query"})
                r.raise_for_status()
                self._exercised = True
                return [d["embedding"] for d in r.json()["data"]]
        except Exception:  # noqa: BLE001
            return None

    def status(self) -> ProviderStatus:
        cfg = bool(self.s.embed_base_url and self.s.embed_model)
        healthy = cfg and self.s.embed_model in self.served()
        return ProviderStatus(kind="embedding", provider="nim_embeddings" if cfg else "lexical_fallback", configured=cfg, healthy=healthy or not cfg,
                              model_id=self.s.embed_model if cfg else "bm25-lexical/1.0",
                              detail=("served model confirmed" if healthy else "configured model not served") if cfg else "Lexical BM25 retrieval (labelled); embeddings not configured.",
                              exercised=self._exercised)


class VisionAdapter:
    def __init__(self, s: Settings):
        self.s = s

    def describe(self, image_path: str, prompt: str) -> dict | None:
        return None  # optional RGB field-photo review; not exercised in this build

    def status(self) -> ProviderStatus:
        cfg = bool(self.s.vision_base_url and self.s.vision_model)
        return ProviderStatus(kind="vision", provider="nim_vision" if cfg else "none", configured=cfg, healthy=False, model_id=self.s.vision_model or "(unset)",
                              detail="Optional RGB field-photo review (English only per model card). Not exercised; SAR/multispectral arrays are never passed as images.")


class EOEncoderStub:
    def encode(self, raster_paths):
        return None

    def status(self) -> ProviderStatus:
        return ProviderStatus(kind="eo_encoder", provider="none", configured=False, healthy=False, model_id="(baseline thresholds)",
                              detail="EOEncoderProvider interface reserved for AnySat/JEPA features + separately trained head. Baseline SAR threshold screen in use; predictive skill: not evaluated.")


class Providers:
    def __init__(self, s: Settings):
        self.s = s
        if s.model_provider == "demo":
            self.text = DemoPlanner()
        else:
            self.text = OpenAICompatiblePlanner(s, label=s.model_provider)
        self.embeddings = EmbeddingAdapter(s)
        self.guard = CompositeGuard(s)
        self.vision = VisionAdapter(s)
        self.eo = EOEncoderStub()

    def statuses(self) -> list[dict]:
        out = [self.text.status(), self.embeddings.status(), *self.guard.statuses(), self.vision.status(), self.eo.status()]
        return [s.__dict__ for s in out]

    def text_available(self) -> bool:
        return self.text.status().healthy


@lru_cache
def get_providers() -> Providers:
    return Providers(get_settings())
