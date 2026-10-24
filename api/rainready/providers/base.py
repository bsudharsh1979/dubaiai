"""Provider interfaces.  One shared text-inference service serves every persona;
personas differ in tools, knowledge and authority, not in model weights."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass
class ProviderStatus:
    kind: str                 # text|embedding|guard|vision|eo_encoder
    provider: str             # demo|local_nim|approved_hosted|none
    configured: bool
    healthy: bool
    model_id: str
    detail: str
    exercised: bool = False   # has a real inference request succeeded in this process?
    extra: dict = field(default_factory=dict)


@dataclass
class PlanResult:
    output: dict                       # validated structured output (persona schema)
    tool_calls: list[dict]             # [{name, args, ok}]
    model_id: str
    provider: str
    exercised: bool                    # True only when a live model produced the output
    tokens: int = 0
    basis: str = "deterministic"       # deterministic|model
    error: str | None = None


class TextPlanner(Protocol):
    name: str

    def plan(self, persona: str, system_prompt: str, user_content: str, tool_schemas: list[dict], output_model: type,
             execute_tool: Callable[[str, dict], dict], max_iterations: int = 6) -> PlanResult: ...

    def status(self) -> ProviderStatus: ...


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]] | None: ...

    def status(self) -> ProviderStatus: ...


@dataclass
class GuardResult:
    available: bool
    unsafe: bool
    categories: list[str]
    jailbreak_score: float | None
    detail: str
    provider: str


class GuardProvider(Protocol):
    def check(self, text: str, context: str) -> GuardResult: ...

    def status(self) -> ProviderStatus: ...


class VisualProvider(Protocol):
    def describe(self, image_path: str, prompt: str) -> dict | None: ...

    def status(self) -> ProviderStatus: ...


class EOEncoderProvider(Protocol):
    """Earth-observation feature extraction (e.g. AnySat/JEPA) plus a separately trained task head.
    Not implemented in this MVP: the baseline SAR threshold screen is the transparent starting point."""

    def encode(self, raster_paths: list[str]) -> Any: ...

    def status(self) -> ProviderStatus: ...
