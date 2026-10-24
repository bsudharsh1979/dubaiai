"use client";
import { useCallback, useState } from "react";
import { api, dubai } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useLive, useSession } from "@/lib/session";
import type { ProviderStatus } from "@/lib/types";
import { Chip, Empty, ErrorBox, KV, Section, Spinner } from "@/components/ui";

type Assurance = {
  modes: Record<string, unknown>;
  providers: ProviderStatus[];
  policy_decisions: { id: string; incident_id: string | null; subject_type: string; actor: string; decision: string; reasons: string[]; created_at: string }[];
  model_versions: { id: string; kind: string; name: string; version: string; card_uri: string; calibrated: boolean; notes: string }[];
  audit_chain: { ok: boolean; events: number; first_bad_seq?: number | null; detail?: string };
  evaluation: Record<string, unknown>;
  worker: { alive: boolean; last_tick: string | null };
};
type Health = { ok: boolean; database: Record<string, unknown>; worker: Record<string, unknown>; integrations: { feed_id: string; name: string; kind: string; status: string; access_classification: string }[]; guard_gate: Record<string, unknown>; time: Record<string, string> };
type AuditRow = { seq: number; ts: string; actor: string; action: string; subject_type: string; subject_id: string; payload: Record<string, unknown> };

export default function AssurancePage() {
  const { t, locale } = useI18n();
  const { identity, can, config, refresh } = useSession();
  const [a, setA] = useState<Assurance | null>(null);
  const [h, setH] = useState<Health | null>(null);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [verify, setVerify] = useState<Assurance["audit_chain"] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");

  const load = useCallback(async () => {
    if (!identity) return;
    try {
      const [as, he, au] = await Promise.all([api<Assurance>("/api/assurance"), api<Health>("/api/health"), api<AuditRow[]>("/api/audit/recent?limit=80")]);
      setA(as);
      setH(he);
      setAudit(au);
    } catch (e) {
      setError(e);
    }
  }, [identity]);
  useLive(load, ["incident", "approval", "work_order", "system", "security", "field_report", "dispatch", "execution_blocked", "proposal", "import"], [identity?.id]);

  const toggleStop = async (active: boolean) => {
    setBusy(true);
    try {
      await api("/api/assurance/emergency-stop", { method: "POST", json: { active, reason } });
      await refresh();
      await load();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const stop = config?.modes.emergency_stop ?? false;

  return (
    <div className="space-y-4">
      <ErrorBox error={error} />
      <div className="grid gap-4 lg:grid-cols-3">
        <Section title="Operating modes" testid="modes-panel">
          {config && (
            <>
              <KV k={t("mode_data")} v={<Chip tone="sand">{config.modes.data_mode}</Chip>} />
              <KV k={t("mode_model")} v={<Chip tone={config.modes.model_provider === "demo" ? "sand" : "lagoon"}>{config.modes.model_provider}</Chip>} />
              <KV k={t("mode_connectors")} v={<Chip tone="sand">{config.modes.action_connectors}</Chip>} />
              <KV k={t("mode_sovereign")} v={config.modes.sovereign_mode ? "on — no cloud fallback; provider allowlist enforced" : "off"} />
              <KV k="Environment" v={config.modes.app_env} />
              <KV k="Approval TTL" v={`${config.approval_ttl_minutes} min`} />
              <KV k="Ack escalation" v={`${config.ack_escalation_minutes} min`} />
              <KV k="Max evidence loops" v={config.max_evidence_loops} />
            </>
          )}
          {h && (
            <>
              <KV k="Database" v={`${h.database.dialect} · migrated ${String(h.database.migrated)}`} />
              <KV k={t("worker")} v={`${h.worker.enabled ? "enabled" : "disabled"} · ${h.worker.alive ? "alive" : "stopped"} · queued ${String(h.worker.queued_jobs)}`} />
              <KV k="Time" v={<span className="ltr-only text-xs">{h.time.dubai} (display Asia/Dubai; stored UTC)</span>} />
            </>
          )}
        </Section>
        <Section title={t("guard_status")} testid="guard-panel">
          {h && (
            <>
              <KV k="Deterministic gate" v={<Chip tone="low">{String(h.guard_gate.deterministic_gate)}</Chip>} />
              <KV k="Guard adapters required for publication" v={String(h.guard_gate.guard_adapters_required_for_publication)} />
              <KV k="Text provider healthy" v={<Chip tone={h.guard_gate.text_provider_healthy ? "low" : "severe"}>{String(h.guard_gate.text_provider_healthy)}</Chip>} />
              <KV k="Privileged actions blocked" v={<Chip tone={h.guard_gate.privileged_actions_blocked ? "severe" : "low"}>{String(h.guard_gate.privileged_actions_blocked)}</Chip>} />
            </>
          )}
          <div className="mt-3 rounded-lg border border-band-severe/30 bg-band-severe/5 p-2">
            <div className="label text-band-severe">Emergency stop</div>
            <p className="text-xs text-ink-700/80">Blocks approvals, dispatch and publication; intake, monitoring and reassessment continue. Incident commander only.</p>
            <input className="mt-1 w-full rounded-lg border border-ink-100 p-1.5 text-xs" placeholder="reason" value={reason} onChange={(e) => setReason(e.target.value)} data-testid="stop-reason" />
            <div className="mt-1 flex gap-1">
              <button type="button" className="btn-danger text-xs" disabled={busy || !can("emergency_stop") || stop} onClick={() => void toggleStop(true)} data-testid="stop-activate">
                {busy ? <Spinner /> : "Activate"}
              </button>
              <button type="button" className="btn-secondary text-xs" disabled={busy || !can("emergency_stop") || !stop} onClick={() => void toggleStop(false)} data-testid="stop-clear">
                Clear
              </button>
            </div>
          </div>
        </Section>
        <Section title={t("audit")} testid="audit-panel">
          {a && (
            <>
              <KV k="Events" v={a.audit_chain.events} />
              <KV k="Chain intact" v={<Chip tone={a.audit_chain.ok ? "low" : "severe"}>{a.audit_chain.ok ? "verified" : `broken at seq ${a.audit_chain.first_bad_seq}`}</Chip>} />
            </>
          )}
          <p className="mt-1 text-[11px] text-ink-700/70">Each event stores the hash of the previous event; re-verification detects edits or deletions inside the chain. This is tamper-evident within the database, not tamper-proof — an external anchor would be needed for stronger guarantees.</p>
          <div className="mt-2 flex gap-1">
            <button type="button" className="btn-secondary text-xs" onClick={() => api<Assurance["audit_chain"]>("/api/audit/verify").then(setVerify).catch(setError)} data-testid="verify-chain">
              {t("verify_chain")}
            </button>
            {can("audit:export") && (
              <a className="btn-secondary text-xs" href={`${process.env.NEXT_PUBLIC_API_BASE ?? ""}/api/audit/export`} target="_blank" rel="noreferrer">
                Export JSON
              </a>
            )}
          </div>
          {verify && <pre className="ltr-only mt-2 rounded bg-ink-950 p-2 text-[10px] text-ink-100">{JSON.stringify(verify)}</pre>}
        </Section>
      </div>

      <Section title={t("providers")} testid="providers-panel">
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          {(a?.providers ?? []).map((p) => (
            <div key={`${p.kind}-${p.provider}`} className="rounded-lg border border-ink-100 p-2 text-xs" data-testid={`provider-${p.kind}-${p.provider}`}>
              <div className="flex flex-wrap items-center gap-1">
                <Chip tone="neutral">{p.kind}</Chip>
                <b>{p.provider}</b>
                <Chip tone={p.configured ? (p.healthy ? "low" : "severe") : "sand"}>{p.configured ? (p.healthy ? "healthy" : "unhealthy") : "not configured"}</Chip>
                <Chip tone={p.exercised ? "low" : "neutral"}>{p.exercised ? t("exercised") : t("not_exercised")}</Chip>
              </div>
              <div className="ltr-only mt-1 font-mono text-[10px]">{p.model_id}</div>
              <div className="mt-1 text-ink-700/80">{p.detail}</div>
              {p.extra && Object.keys(p.extra).length > 0 && <div className="ltr-only mt-1 text-[10px] text-ink-700/60">{JSON.stringify(p.extra)}</div>}
            </div>
          ))}
        </div>
      </Section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Integrations & access requirements" testid="integrations-panel">
          <ul className="space-y-1 text-xs">
            {(h?.integrations ?? []).map((i) => (
              <li key={i.feed_id} className="flex flex-wrap items-center gap-1 rounded border border-ink-100 p-1.5">
                <Chip tone={i.status === "simulated" || i.status === "synthetic" ? "sand" : i.status === "requires_authorized_access" ? "high" : i.status === "connected" ? "low" : "neutral"}>{i.status}</Chip>
                <span className="font-medium">{i.name}</span>
                <span className="ms-auto text-[10px] text-ink-700/60">{i.access_classification}</span>
              </li>
            ))}
          </ul>
        </Section>
        <Section title={t("model_versions")} testid="models-panel">
          <ul className="space-y-1 text-xs">
            {(a?.model_versions ?? []).map((m) => (
              <li key={m.id} className="rounded border border-ink-100 p-1.5">
                <div className="flex flex-wrap items-center gap-1">
                  <Chip tone="neutral">{m.kind}</Chip>
                  <b>{m.name}</b>
                  <span className="font-mono text-[10px]">{m.version}</span>
                  <Chip tone={m.calibrated ? "low" : "sand"}>{m.calibrated ? "calibrated" : "uncalibrated"}</Chip>
                </div>
                <div className="text-ink-700/70">
                  {m.notes} · <span className="font-mono text-[10px]">{m.card_uri}</span>
                </div>
              </li>
            ))}
          </ul>
        </Section>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Evaluation status (honest)" testid="evaluation-panel">
          {a ? <pre className="ltr-only max-h-72 overflow-auto rounded bg-ink-950 p-2 text-[10px] text-ink-100">{JSON.stringify(a.evaluation, null, 1)}</pre> : <Spinner />}
        </Section>
        <Section title={t("policy_decisions")} testid="policy-panel">
          {a?.policy_decisions.length ? (
            <ul className="max-h-72 space-y-1 overflow-auto text-xs">
              {a.policy_decisions.map((p) => (
                <li key={p.id} className="flex flex-wrap items-center gap-1">
                  <Chip tone={p.decision === "allow" ? "low" : p.decision === "deny" ? "severe" : "sand"}>{p.decision}</Chip>
                  <span className="font-mono text-[10px]">{p.subject_type}</span>
                  <span>{p.reasons.join("; ") || "all checks passed"}</span>
                  <span className="ms-auto text-[10px] text-ink-700/60 ltr-only">{dubai(p.created_at, locale)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>—</Empty>
          )}
        </Section>
      </div>

      <Section title="Recent audit events (redacted payloads)" testid="audit-list">
        <ul className="max-h-96 space-y-0.5 overflow-auto text-[11px]">
          {audit.map((r) => (
            <li key={r.seq} className="flex flex-wrap gap-2 border-b border-ink-100/60 py-0.5">
              <span className="w-10 font-mono text-ink-700/60">#{r.seq}</span>
              <span className="ltr-only w-32 text-ink-700/60">{dubai(r.ts, locale)}</span>
              <span className="w-40 truncate font-medium">{r.action}</span>
              <span className="w-32 truncate">{r.actor}</span>
              <span className="flex-1 truncate font-mono text-ink-700/70">{JSON.stringify(r.payload).slice(0, 120)}</span>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}
