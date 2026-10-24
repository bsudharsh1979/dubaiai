"use client";
import { useEffect, useState } from "react";
import { api, dubai } from "@/lib/api";
import { pick, useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import type { AgentRun, ToolResult } from "@/lib/types";
import { IncidentPicker, useIncidentDetail } from "@/components/IncidentPicker";
import { Chip, Empty, ErrorBox, Section } from "@/components/ui";

type Persona = { key: string; title: string; title_ar: string; tools: string[]; registry_allowlist: string[]; knowledge: string[]; cannot: string[]; limits: Record<string, number>; output_schema: Record<string, unknown> };

const ORDER = ["observer", "hydrologist", "utility_engineer", "hse_officer", "response_planner", "communications_officer", "assurance_officer", "incident_coordinator"];

export default function AgentsPage() {
  const { t, locale } = useI18n();
  const { identity, config } = useSession();
  const { list, id, setId, detail, error, includeClosed, setIncludeClosed } = useIncidentDetail();
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [openRun, setOpenRun] = useState<string | null>(null);

  useEffect(() => {
    if (identity) api<Persona[]>("/api/agents/personas").then(setPersonas).catch(() => {});
  }, [identity]);

  const runsByPersona = new Map<string, AgentRun[]>();
  for (const r of detail?.agent_runs ?? []) runsByPersona.set(r.persona, [...(runsByPersona.get(r.persona) ?? []), r]);
  const latestThread = detail?.agent_runs.at(-1)?.thread_id;

  return (
    <div className="space-y-4">
      <IncidentPicker list={list} id={id} setId={setId} includeClosed={includeClosed} setIncludeClosed={setIncludeClosed} />
      <ErrorBox error={error} />
      <div className="card p-3 text-xs" data-testid="arch-flow">
        <div className="label mb-1">{t("architecture")}</div>
        <div className="flex flex-wrap items-center gap-1">
          {(config?.architecture ?? []).map((a, i, arr) => (
            <span key={a} className="flex items-center gap-1">
              <span className={`rounded px-2 py-1 ${i === 1 || i === 2 ? "bg-lagoon-100 text-lagoon-600" : "bg-ink-100/60"}`}>{a}</span>
              {i < arr.length - 1 && <span aria-hidden>→</span>}
            </span>
          ))}
        </div>
        <p className="mt-1 text-ink-700/70">
          {t("mode_model")}: <b>{config?.modes.model_provider}</b>
          {config?.modes.model_provider === "demo" ? " — rehearsal: persona outputs are deterministic templates driven by tool results; no model inference is performed." : " — real model requests with validated structured outputs; failures are shown, never masked."}
        </p>
      </div>

      <Section title={t("personas")} testid="persona-grid">
        {!detail && <Empty>{t("no_incidents")}</Empty>}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {ORDER.map((key) => {
            const p = personas.find((x) => x.key === key);
            const runs = (runsByPersona.get(key) ?? []).filter((r) => !latestThread || r.thread_id === latestThread);
            const last = runs.at(-1);
            const status = last?.status ?? (detail ? "skipped" : "idle");
            const tone = status === "completed" ? "low" : status === "error" || status === "failed" ? "severe" : status === "running" ? "lagoon" : "neutral";
            return (
              <div key={key} className="rounded-lg border border-ink-100 p-3" data-testid={`persona-${key}`}>
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-sm font-semibold">{p ? (locale === "ar" ? p.title_ar : p.title) : key}</div>
                    <div className="text-[11px] text-ink-700/70">{key}</div>
                  </div>
                  <Chip tone={tone} testid={`persona-status-${key}`}>
                    {status === "skipped" ? t("skipped") : status}
                  </Chip>
                </div>
                {last && (
                  <div className="mt-2 text-[11px] text-ink-700/80">
                    <div>
                      provider <b>{last.provider}</b> · {last.model_id ?? "—"} · {last.model_exercised ? t("exercised") : t("not_exercised")}
                    </div>
                    <div>
                      {t("tool_calls")}: {last.tool_call_count} / {String(last.limits?.max_tool_calls ?? "—")} · {last.finished_at && last.started_at ? `${Math.max(0, new Date(last.finished_at).getTime() - new Date(last.started_at).getTime())} ms` : ""}
                    </div>
                    <button type="button" className="mt-1 text-lagoon-600 underline" onClick={() => setOpenRun(openRun === last.id ? null : last.id)}>
                      {openRun === last.id ? "hide summary" : "structured summary"}
                    </button>
                    {openRun === last.id && <pre className="ltr-only mt-1 max-h-56 overflow-auto rounded bg-ink-950 p-2 text-[10px] text-ink-100">{JSON.stringify(last.output, null, 1)}</pre>}
                  </div>
                )}
                {p && (
                  <details className="mt-2 text-[11px]">
                    <summary className="cursor-pointer text-ink-700/80">card: tools, knowledge, limits, prohibitions</summary>
                    <div className="mt-1 space-y-1">
                      <div>
                        <span className="label">tools</span> {p.tools.join(", ")}
                      </div>
                      <div>
                        <span className="label">knowledge</span> {p.knowledge.join(", ")}
                      </div>
                      <div>
                        <span className="label">limits</span> {Object.entries(p.limits).map(([k, v]) => `${k}=${v}`).join(" ")}
                      </div>
                      <div className="text-band-severe">
                        <span className="label">cannot</span> {p.cannot.join("; ")}
                      </div>
                    </div>
                  </details>
                )}
              </div>
            );
          })}
        </div>
      </Section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title={t("evidence")} testid="evidence-list" right={detail && <Chip tone="neutral">{detail.independent_sources} independent sources</Chip>}>
          {detail?.evidence.length ? (
            <ul className="max-h-[480px] space-y-1 overflow-auto text-xs">
              {detail.evidence.map((e) => (
                <li key={e.id} className="rounded border border-ink-100 p-2" data-testid={`evidence-${e.id}`}>
                  <div className="flex flex-wrap items-center gap-1">
                    <Chip tone="neutral">{e.kind}</Chip>
                    <Chip tone={e.freshness === "current" ? "low" : e.freshness === "stale" ? "severe" : e.freshness === "unknown" ? "high" : "sand"}>{e.freshness}</Chip>
                    <Chip tone={e.quality === "good" ? "low" : e.quality === "poor" ? "severe" : "sand"}>{e.quality}</Chip>
                    <span className="font-mono text-[10px] text-ink-700/60">{e.source_key}</span>
                  </div>
                  <div className="mt-1">{e.summary}</div>
                  <div className="ltr-only mt-0.5 text-[10px] text-ink-700/60">
                    observed {dubai(e.observed_at, locale)} · available {dubai(e.available_at, locale)}
                    {e.conflicts_with.length ? ` · conflicts: ${e.conflicts_with.join(", ")}` : ""}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>{t("no_data")}</Empty>
          )}
        </Section>
        <Section title={t("tool_calls")} testid="tool-list">
          {detail?.tool_results.length ? (
            <ul className="max-h-[480px] space-y-1 overflow-auto text-xs">
              {detail.tool_results.map((tr) => (
                <ToolRow key={tr.id} tr={tr} />
              ))}
            </ul>
          ) : (
            <Empty>—</Empty>
          )}
        </Section>
      </div>
      {detail && (
        <Section title="Agent decision summary (structured, not chain-of-thought)" testid="coordinator-summary">
          <div className="text-sm">
            <b>{pick(locale, detail, "title")}</b> — {detail.next_decision}
          </div>
          {detail.agent_runs.filter((r) => r.persona === "incident_coordinator").map((r) => (
            <pre key={r.id} className="ltr-only mt-2 max-h-48 overflow-auto rounded bg-ink-950 p-2 text-[10px] text-ink-100">
              {JSON.stringify(r.output, null, 1)}
            </pre>
          ))}
        </Section>
      )}
    </div>
  );
}

function ToolRow({ tr }: { tr: ToolResult }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded border border-ink-100 p-2" data-testid={`tool-${tr.id}`}>
      <div className="flex flex-wrap items-center gap-1">
        <Chip tone={tr.ok ? "low" : "severe"}>{tr.ok ? "ok" : "error"}</Chip>
        <span className="font-mono">{tr.tool}</span>
        <span className="text-[10px] text-ink-700/60">{tr.version}</span>
        <span className="ms-auto text-[10px] text-ink-700/60">
          {tr.persona} · {tr.duration_ms} ms
        </span>
      </div>
      <button type="button" className="mt-1 text-[11px] text-lagoon-600 underline" onClick={() => setOpen(!open)}>
        {open ? "hide" : "args & result"}
      </button>
      {open && <pre className="ltr-only mt-1 max-h-48 overflow-auto rounded bg-ink-950 p-2 text-[10px] text-ink-100">{JSON.stringify({ args: tr.args, result: tr.result }, null, 1)}</pre>}
    </li>
  );
}
