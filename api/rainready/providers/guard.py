"""Safety gate.

``DeterministicGate`` always runs: it separates *observations* from *instructions*
in untrusted text (field reports, retrieved documents, tool responses), flags
injury/death mentions for mandatory human review (never discards them), and
detects attempts to invoke privileged actions.  It cannot be bypassed and needs
no model.

Optional adapters wrap NVIDIA guard models when configured:
* content safety  — ``nvidia/nemotron-3.5-content-safety`` style chat-completions
  contract returning a safety verdict;
* jailbreak       — NemoGuard JailbreakDetect classification API (``/v1/classify``).

Guard scores never grant permission, validate physics or confirm incidents; they
only add review flags or block *public* output.  If a required adapter is down,
publication is blocked and monitoring continues.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from ..config import Settings
from .base import GuardResult, ProviderStatus

IMPERATIVE = re.compile(
    r"\b(ignore|override|bypass|skip|disregard)\b.{0,40}\b(approval|approvals|policy|policies|guard|guardrails|checks?|human review)\b|"
    r"\b(send|issue|publish|broadcast|trigger)\b.{0,30}\b(evacuation|alert|advisory|warning)\b|"
    r"\b(close|shut|open)\b.{0,20}\b(valve|road|gate|breaker|power|substation)\b|"
    r"\b(you must|you are now|system prompt|as an ai|new instructions?)\b|"
    r"تجاهل.{0,30}(الموافق|الموافقات)|أرسل.{0,30}(إخلاء|تحذير|إنذار)",
    re.I | re.S)
CASUALTY = re.compile(r"\b(injur\w*|casualt\w*|fatalit\w*|dead|death|died|drown\w*|trapped|unconscious)\b|إصاب|وفاة|غرق|محاصر", re.I)
PRIVILEGED_WORDS = re.compile(r"\b(evacuat\w*|switch(ing)? off|de-?energi[sz]e|dispatch now)\b", re.I)


@dataclass
class Separation:
    observations: str
    instructions: list[str]
    casualty_mention: bool
    privileged_action_attempt: bool
    flags: list[str]


def separate(text: str) -> Separation:
    """Split untrusted text into observation sentences and quarantined instructions."""
    sentences = re.split(r"(?<=[.!?؟])\s+|\n+", text.strip())
    obs, instr, flags = [], [], []
    for s in sentences:
        if not s.strip():
            continue
        if IMPERATIVE.search(s):
            instr.append(s.strip())
        else:
            obs.append(s.strip())
    casualty = bool(CASUALTY.search(text))
    priv = bool(IMPERATIVE.search(text) or PRIVILEGED_WORDS.search(" ".join(instr)))
    if instr:
        flags.append("instruction_isolated")
    if casualty:
        flags.append("casualty_mention_requires_human_review")
    if priv:
        flags.append("privileged_action_attempt")
    return Separation(observations=" ".join(obs), instructions=instr, casualty_mention=casualty, privileged_action_attempt=priv, flags=flags)


class DeterministicGate:
    name = "deterministic_gate"

    def check(self, text: str, context: str) -> GuardResult:
        sep = separate(text)
        return GuardResult(available=True, unsafe=sep.privileged_action_attempt, categories=sep.flags, jailbreak_score=None,
                           detail="pattern-based observation/instruction separation", provider=self.name)

    def status(self) -> ProviderStatus:
        return ProviderStatus(kind="guard", provider=self.name, configured=True, healthy=True, model_id="rules/1.0", detail="always-on deterministic gate", exercised=True)


class ContentSafetyAdapter:
    """Chat-completions style content-safety NIM (verify profile/terms before use)."""
    name = "nemotron_content_safety"

    def __init__(self, s: Settings):
        self.s = s
        self._exercised = False

    def check(self, text: str, context: str) -> GuardResult:
        if not (self.s.guard_content_safety_url and self.s.guard_content_safety_model):
            return GuardResult(available=False, unsafe=False, categories=[], jailbreak_score=None, detail="not configured", provider=self.name)
        try:
            with httpx.Client(timeout=20) as c:
                r = c.post(f"{self.s.guard_content_safety_url.rstrip('/')}/chat/completions", headers=self._h(),
                           json={"model": self.s.guard_content_safety_model, "messages": [{"role": "user", "content": text}], "max_tokens": 200})
                r.raise_for_status()
                content = r.json()["choices"][0]["message"].get("content", "")
            self._exercised = True
            unsafe = "unsafe" in content.lower()
            cats = [c.strip() for c in re.findall(r"\b(S\d+|[A-Z][a-z]+ [A-Z][a-z]+)\b", content)] if unsafe else []
            return GuardResult(available=True, unsafe=unsafe, categories=cats, jailbreak_score=None, detail=content[:200], provider=self.name)
        except Exception as e:  # noqa: BLE001
            return GuardResult(available=False, unsafe=False, categories=[], jailbreak_score=None, detail=f"adapter error: {e}", provider=self.name)

    def _h(self):
        h = {"Content-Type": "application/json"}
        if self.s.guard_api_key:
            h["Authorization"] = f"Bearer {self.s.guard_api_key}"
        return h

    def status(self) -> ProviderStatus:
        cfg = bool(self.s.guard_content_safety_url and self.s.guard_content_safety_model)
        healthy = False
        detail = "not configured (optional)"
        if cfg:
            try:
                with httpx.Client(timeout=5) as c:
                    r = c.get(f"{self.s.guard_content_safety_url.rstrip('/')}/models", headers=self._h())
                    healthy = r.status_code == 200
                    detail = "reachable" if healthy else f"HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                detail = f"unreachable: {e}"
        return ProviderStatus(kind="guard", provider=self.name, configured=cfg, healthy=healthy, model_id=self.s.guard_content_safety_model or "(unset)", detail=detail, exercised=self._exercised)


class JailbreakDetectAdapter:
    """NemoGuard JailbreakDetect: POST /v1/classify {"input": text} → {"jailbreak": bool, "score": float}."""
    name = "nemoguard_jailbreak_detect"

    def __init__(self, s: Settings):
        self.s = s
        self._exercised = False

    def check(self, text: str, context: str) -> GuardResult:
        if not self.s.guard_jailbreak_url:
            return GuardResult(available=False, unsafe=False, categories=[], jailbreak_score=None, detail="not configured", provider=self.name)
        try:
            with httpx.Client(timeout=15) as c:
                r = c.post(f"{self.s.guard_jailbreak_url.rstrip('/')}/v1/classify", json={"input": text},
                           headers={"Authorization": f"Bearer {self.s.guard_api_key}"} if self.s.guard_api_key else {})
                r.raise_for_status()
                data = r.json()
            self._exercised = True
            return GuardResult(available=True, unsafe=bool(data.get("jailbreak")), categories=["jailbreak"] if data.get("jailbreak") else [],
                               jailbreak_score=data.get("score"), detail="classified", provider=self.name)
        except Exception as e:  # noqa: BLE001
            return GuardResult(available=False, unsafe=False, categories=[], jailbreak_score=None, detail=f"adapter error: {e}", provider=self.name)

    def status(self) -> ProviderStatus:
        cfg = bool(self.s.guard_jailbreak_url)
        return ProviderStatus(kind="guard", provider=self.name, configured=cfg, healthy=cfg and self._exercised, model_id="nemoguard-jailbreak-detect" if cfg else "(unset)",
                              detail="configured; health known after first call" if cfg else "not configured (optional)", exercised=self._exercised)


class CompositeGuard:
    def __init__(self, s: Settings):
        self.s = s
        self.gate = DeterministicGate()
        self.adapters = [ContentSafetyAdapter(s), JailbreakDetectAdapter(s)]

    def check(self, text: str, context: str) -> dict:
        base = self.gate.check(text, context)
        results = [base] + [a.check(text, context) for a in self.adapters if a.status().configured]
        unavailable = [r.provider for r in results if not r.available]
        return {"unsafe": any(r.unsafe for r in results if r.available), "categories": sorted({c for r in results for c in r.categories}),
                "jailbreak_score": next((r.jailbreak_score for r in results if r.jailbreak_score is not None), None),
                "providers": [{"provider": r.provider, "available": r.available, "unsafe": r.unsafe, "detail": r.detail} for r in results],
                "unavailable_adapters": unavailable,
                "publication_blocked_by_outage": bool(unavailable) and self.s.guard_required_for_publication}

    def statuses(self) -> list[ProviderStatus]:
        return [self.gate.status()] + [a.status() for a in self.adapters]
