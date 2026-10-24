"""OpenAI-compatible chat-completions planner for NIM / vLLM / allow-listed hosted
endpoints.  Used for both ``local_nim`` and ``approved_hosted``; the only difference
is the base URL (allow-listed in settings) and the label shown in the UI.

* Served model ids are discovered via ``GET /v1/models`` and the configured id must
  be present — it is never assumed to equal the catalog id.
* The persona's typed output is obtained through a mandatory ``submit_output`` tool
  call validated against the persona's JSON schema.
* Any failure is reported visibly (``PlanResult.error``); there is no silent fallback
  to the demo planner and never a cloud fallback.
"""
from __future__ import annotations

import json
from typing import Callable

import httpx
from pydantic import BaseModel, ValidationError

from ..config import Settings
from .base import PlanResult, ProviderStatus


class OpenAICompatiblePlanner:
    def __init__(self, settings: Settings, label: str):
        self.s = settings
        self.name = label
        self._served: list[str] | None = None
        self._exercised = False
        self._last_error: str | None = None

    # -- discovery ---------------------------------------------------------
    def served_models(self, force: bool = False) -> list[str]:
        if self._served is not None and not force:
            return self._served
        try:
            with httpx.Client(timeout=10) as c:
                r = c.get(f"{self.s.llm_base_url.rstrip('/')}/models", headers=self._headers())
                r.raise_for_status()
                self._served = [m.get("id") for m in r.json().get("data", [])]
        except Exception as e:  # noqa: BLE001
            self._served = []
            self._last_error = f"/v1/models unavailable: {e}"
        return self._served

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.s.llm_api_key:
            h["Authorization"] = f"Bearer {self.s.llm_api_key}"
        return h

    def status(self) -> ProviderStatus:
        configured = bool(self.s.llm_base_url and self.s.llm_model)
        healthy = False
        detail = "LLM_BASE_URL / LLM_MODEL not set"
        if configured:
            served = self.served_models()
            if self.s.llm_model in served:
                healthy, detail = True, f"model served at {self.s.llm_base_url}"
            elif served:
                detail = f"configured model not in served list ({len(served)} served: {', '.join(served[:5])})"
            else:
                detail = self._last_error or "endpoint did not list models"
        return ProviderStatus(kind="text", provider=self.name, configured=configured, healthy=healthy, model_id=self.s.llm_model or "(unset)", detail=detail,
                              exercised=self._exercised, extra={"base_url": self.s.llm_base_url, "contract": "openai-chat-completions+tools", "cloud_fallback": False})

    # -- planning ----------------------------------------------------------
    def plan(self, persona: str, system_prompt: str, user_content: str, tool_schemas: list[dict], output_model: type[BaseModel],
             execute_tool: Callable[[str, dict], dict], max_iterations: int = 6) -> PlanResult:
        st = self.status()
        if not st.healthy:
            return PlanResult(output={}, tool_calls=[], model_id=self.s.llm_model, provider=self.name, exercised=False, basis="model", error=f"provider unavailable: {st.detail}")
        output_schema = output_model.model_json_schema()
        submit = {"type": "function", "function": {"name": "submit_output", "description": "Submit the final structured output for this persona. Call exactly once.", "parameters": output_schema}}
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]
        tools = tool_schemas + [submit]
        calls: list[dict] = []
        tokens = 0
        final: dict | None = None
        try:
            with httpx.Client(timeout=self.s.llm_timeout_s) as client:
                for _ in range(max_iterations):
                    body = {"model": self.s.llm_model, "messages": messages, "tools": tools, "tool_choice": "auto", "temperature": 0.0, "max_tokens": self.s.llm_max_tokens}
                    r = client.post(f"{self.s.llm_base_url.rstrip('/')}/chat/completions", headers=self._headers(), json=body)
                    r.raise_for_status()
                    data = r.json()
                    tokens += int((data.get("usage") or {}).get("total_tokens") or 0)
                    msg = data["choices"][0]["message"]
                    messages.append({k: v for k, v in msg.items() if k in {"role", "content", "tool_calls"}})
                    tcs = msg.get("tool_calls") or []
                    if not tcs:
                        # Some models answer in text; try to parse a JSON object as the output.
                        content = msg.get("content") or ""
                        try:
                            cand = json.loads(content[content.index("{"): content.rindex("}") + 1])
                            if isinstance(cand, dict):
                                final = cand
                        except Exception:  # noqa: BLE001
                            pass
                        break
                    for tc in tcs:
                        name = tc["function"]["name"]
                        try:
                            args = json.loads(tc["function"].get("arguments") or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        if name == "submit_output":
                            final = args
                            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": "recorded"})
                            continue
                        result = execute_tool(name, args)  # allowlist + validation enforced by the registry
                        calls.append({"name": name, "args": args, "ok": "error" not in result})
                        messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result, default=str)[:6000]})
                    if final is not None:
                        break
        except Exception as e:  # noqa: BLE001
            return PlanResult(output={}, tool_calls=calls, model_id=self.s.llm_model, provider=self.name, exercised=False, tokens=tokens, basis="model", error=f"inference failed: {e}")
        if final is None:
            return PlanResult(output={}, tool_calls=calls, model_id=self.s.llm_model, provider=self.name, exercised=True, tokens=tokens, basis="model", error="model did not submit a structured output")
        try:
            final = output_model.model_validate(final).model_dump(mode="json")
        except ValidationError as e:
            return PlanResult(output=final, tool_calls=calls, model_id=self.s.llm_model, provider=self.name, exercised=True, tokens=tokens, basis="model",
                              error="structured output failed validation: " + "; ".join(str(x.get("msg")) for x in e.errors()[:3]))
        self._exercised = True
        return PlanResult(output=final, tool_calls=calls, model_id=self.s.llm_model, provider=self.name, exercised=True, tokens=tokens, basis="model")
