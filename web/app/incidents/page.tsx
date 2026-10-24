"use client";
import { Fragment, useMemo, useState } from "react";
import { api, dubai, newIdempotencyKey } from "@/lib/api";
import { pick, useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import type { IncidentDetail, Proposal, Sitrep, StructuredAlert, WorkOrder } from "@/lib/types";
import { IncidentPicker, useIncidentDetail } from "@/components/IncidentPicker";
import { SectorMap } from "@/components/SectorMap";
import { BandChip, Chip, Empty, ErrorBox, KV, LabelChip, Section, Spinner, StatusChip } from "@/components/ui";

export default function IncidentsPage() {
  const { t, locale } = useI18n();
  const { identity, can, config } = useSession();
  const { list, id, setId, detail, error, reload, includeClosed, setIncludeClosed } = useIncidentDetail();
  const [busy, setBusy] = useState<string | null>(null);
  const [actErr, setActErr] = useState<unknown>(null);
  const [note, setNote] = useState("");
  const [closeRef, setCloseRef] = useState("");
  const [closeNote, setCloseNote] = useState("");
  const [aar, setAar] = useState({ what_was_expected: "", what_happened: "", went_well: "", improve: "", follow_ups: "" });
  const [sitrep, setSitrep] = useState<Sitrep | null>(null);
  const [copied, setCopied] = useState(false);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<{ answer: string; basis: string; cited_inputs: { type: string; id: string; summary: string }[]; guard?: Record<string, unknown> } | null>(null);
  const [editText, setEditText] = useState<string | null>(null);

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setActErr(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setActErr(e);
    } finally {
      setBusy(null);
    }
  };

  const latest = detail?.proposals.at(-1) ?? null;
  const overlay = useMemo(() => {
    const route = latest?.actions.find((a) => a.route?.geometry)?.route?.geometry;
    const closed = (detail?.summary?.hse as { closed_roads?: string[] } | undefined)?.closed_roads ?? [];
    return {
      hazard: detail?.geometry ? ({ type: "Feature", geometry: detail.geometry, properties: {} } as GeoJSON.Feature) : null,
      route: route ? ({ type: "Feature", geometry: route, properties: {} } as GeoJSON.Feature) : null,
      closedRoads: closed,
    };
  }, [detail, latest]);

  const myAuthority = identity?.approval_authority ?? [];

  return (
    <div className="space-y-4">
      <IncidentPicker list={list} id={id} setId={setId} includeClosed={includeClosed} setIncludeClosed={setIncludeClosed} />
      <ErrorBox error={error} />
      {!detail ? (
        <Empty>{t("no_incidents")}</Empty>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
          <div className="space-y-4">
            <Section
              title={
                <span className="flex flex-wrap items-center gap-2">
                  {pick(locale, detail, "title")} <span className="font-mono text-[11px] text-ink-700/60">{detail.id} · v{detail.version}</span>
                </span>
              }
              testid="incident-header"
              right={
                <div className="flex flex-wrap gap-1">
                  <LabelChip label={detail.label} />
                  <StatusChip status={detail.status} />
                  <BandChip band={detail.severity_band} prefix={t("severity")} />
                  <BandChip band={detail.consequence} prefix={t("consequence")} />
                </div>
              }
            >
              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <KV k={t("evidence_quality")} v={detail.evidence_quality ?? "—"} />
                  <KV k={t("probability")} v={detail.calibrated_probability ?? <span className="text-xs text-ink-700/70">{detail.probability_note}</span>} />
                  <KV k="Independent sources" v={detail.independent_sources} />
                  <KV k="Scenario" v={detail.scenario_id} />
                  <KV k="Created" v={<span className="ltr-only">{dubai(detail.created_at, locale)}</span>} />
                  {detail.pending_interrupt && <KV k="Graph" v={<Chip tone="sand">interrupted — awaiting human review</Chip>} />}
                </div>
                <div className="rounded-lg bg-sand-100 p-2 text-sm" data-testid="next-decision">
                  <span className="label">{t("next_decision")}</span>
                  <div>{detail.next_decision}</div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    <button type="button" className="btn-secondary text-xs" disabled={busy !== null || !can("scenario:run")} onClick={() => void act("reassess", () => api(`/api/incidents/${detail.id}/reassess`, { method: "POST" }))} data-testid="reassess">
                      {t("reassess")}
                    </button>
                    {can("incident:cancel") && (
                      <button type="button" className="btn-danger text-xs" disabled={busy !== null} onClick={() => void act("cancel", () => api(`/api/incidents/${detail.id}/cancel`, { method: "POST" }))}>
                        {t("cancel_incident")}
                      </button>
                    )}
                  </div>
                </div>
              </div>
              <RiskMatrix likelihood={detail.severity_band} consequence={detail.consequence} />
              <ErrorBox error={actErr} />
            </Section>

            <Section title={t("proposals")} testid="proposal-list">
              {detail.proposals.length === 0 && <Empty>No proposal — the coordinator has not reached the planning stage (see next decision).</Empty>}
              {detail.proposals.map((p) => (
                <ProposalCard key={p.id} p={p} detail={detail} latest={p.id === latest?.id} busy={busy} act={act} note={note} setNote={setNote} myAuthority={myAuthority} canApprove={myAuthority.length > 0} canRevise={myAuthority.length > 0} editText={editText} setEditText={setEditText} ttl={config?.approval_ttl_minutes ?? 30} />
              ))}
            </Section>

            <Section title={t("work_orders")} testid="work-orders">
              <p className="mb-2 text-[11px] text-ink-700/70">{t("ack_note")}</p>
              {detail.work_orders.length === 0 ? (
                <Empty>—</Empty>
              ) : (
                <ul className="space-y-2">
                  {detail.work_orders.map((w) => (
                    <WorkOrderRow key={w.id} w={w} busy={busy} act={act} canAck={can("workorder:ack")} canComplete={can("workorder:ack")} locale={locale} />
                  ))}
                </ul>
              )}
            </Section>

            <Section title={t("close_incident")} testid="closure">
              <p className="mb-2 text-xs text-ink-700/80">Closure requires a new observation or reviewed field report received after the last response action, plus incident-commander confirmation.</p>
              <div className="grid gap-2 md:grid-cols-[1fr_1fr_auto]">
                <select className="rounded-lg border border-ink-100 p-1.5 text-sm" value={closeRef} onChange={(e) => setCloseRef(e.target.value)} data-testid="close-ref">
                  <option value="">— new observation / reviewed field report —</option>
                  {detail.field_reports.map((f) => (
                    <option key={f.id} value={f.id}>
                      field report {f.id} · {f.review_status} · {f.description.slice(0, 40)}
                    </option>
                  ))}
                </select>
                <input className="rounded-lg border border-ink-100 p-1.5 text-sm" placeholder="confirmation note" value={closeNote} onChange={(e) => setCloseNote(e.target.value)} data-testid="close-note" />
                <button
                  type="button"
                  className="btn-primary text-xs"
                  disabled={busy !== null || !can("incident:close") || !closeRef || closeNote.length < 5}
                  onClick={() => {
                    const hasAar = Object.values(aar).some((v) => v.trim().length > 0);
                    const after_action = hasAar ? { ...aar, follow_ups: aar.follow_ups.split("\n").map((s) => s.trim()).filter(Boolean) } : undefined;
                    void act("close", () => api(`/api/incidents/${detail.id}/close`, { method: "POST", json: { confirmation_note: closeNote, new_observation_ref: closeRef, after_action } }));
                  }}
                  data-testid="close-submit"
                >
                  {t("close_incident")}
                </button>
              </div>
              <details className="mt-2 text-xs" data-testid="aar">
                <summary className="cursor-pointer text-ink-700/80">{t("aar")}</summary>
                <div className="mt-2 grid gap-2 md:grid-cols-2">
                  {(["what_was_expected", "what_happened", "went_well", "improve"] as const).map((k) => (
                    <label key={k} className="flex flex-col gap-0.5">
                      <span className="label">{t(({ what_was_expected: "aar_expected", what_happened: "aar_happened", went_well: "aar_well", improve: "aar_improve" } as const)[k])}</span>
                      <textarea className="rounded border border-ink-100 p-1" rows={2} value={aar[k]} onChange={(e) => setAar({ ...aar, [k]: e.target.value })} data-testid={`aar-${k}`} />
                    </label>
                  ))}
                  <label className="flex flex-col gap-0.5 md:col-span-2">
                    <span className="label">{t("aar_followups")}</span>
                    <textarea className="rounded border border-ink-100 p-1" rows={2} value={aar.follow_ups} onChange={(e) => setAar({ ...aar, follow_ups: e.target.value })} data-testid="aar-follow_ups" />
                  </label>
                </div>
              </details>
              {!can("incident:close") && <p className="mt-1 text-[11px] text-band-severe">Your role cannot confirm closure (incident commander only; server-enforced).</p>}
              {detail.summary?.after_action_review ? (
                <div className="mt-2 rounded bg-sand-100 p-2 text-xs" data-testid="aar-stored">
                  <span className="label">after-action review recorded</span>
                  <pre className="mt-1 whitespace-pre-wrap font-sans">{JSON.stringify(detail.summary.after_action_review, null, 1).replace(/[{}"]/g, "")}</pre>
                </div>
              ) : null}
            </Section>

            <Section
              title={t("sitrep")}
              testid="sitrep"
              right={
                <div className="flex gap-1">
                  <button type="button" className="btn-secondary text-xs" disabled={busy !== null} onClick={() => void act("sitrep", async () => setSitrep(await api<Sitrep>(`/api/incidents/${detail.id}/sitrep`)))} data-testid="sitrep-generate">
                    {busy === "sitrep" ? <Spinner /> : t("sitrep_generate")}
                  </button>
                  {sitrep && (
                    <button
                      type="button"
                      className="btn-secondary text-xs"
                      onClick={() => {
                        void navigator.clipboard?.writeText(sitrepText(sitrep, locale)).then(() => {
                          setCopied(true);
                          setTimeout(() => setCopied(false), 1500);
                        });
                      }}
                      data-testid="sitrep-copy"
                    >
                      {copied ? t("sitrep_copied") : t("sitrep_copy")}
                    </button>
                  )}
                </div>
              }
            >
              {!sitrep ? (
                <p className="text-xs text-ink-700/70">Incident-briefing layout assembled from persisted state only (situation · evidence · decisions · resources · open items · operational period · caveats).</p>
              ) : (
                <SitrepView s={sitrep} locale={locale} />
              )}
            </Section>
          </div>

          <div className="space-y-4">
            <SectorMap overlay={overlay} height={300} />
            <Section title="Approvals & policy" testid="approvals">
              {detail.approvals.length === 0 && <Empty>—</Empty>}
              <ul className="space-y-1 text-xs">
                {detail.approvals.map((a) => (
                  <li key={a.id} className="rounded border border-ink-100 p-2" data-testid={`approval-${a.id}`}>
                    <div className="flex flex-wrap gap-1">
                      <Chip tone={a.decision === "approved" ? "low" : "severe"}>{a.decision}</Chip>
                      <Chip tone={a.status === "active" ? "lagoon" : a.status === "consumed" ? "neutral" : "severe"}>{a.status}</Chip>
                      <span>
                        {a.approver_id} ({a.approver_role})
                      </span>
                    </div>
                    <div className="ltr-only mt-1 font-mono text-[10px] text-ink-700/70">
                      proposal v{a.proposal_version} · incident v{a.incident_version} · hash {a.payload_hash.slice(0, 12)}… · {t("expires")} {dubai(a.expires_at, locale)}
                    </div>
                  </li>
                ))}
              </ul>
              <div className="label mt-3 mb-1">{t("policy_decisions")}</div>
              <ul className="space-y-1 text-xs">
                {detail.policy_decisions.map((p) => (
                  <li key={p.id} className="flex flex-wrap gap-1">
                    <Chip tone={p.decision === "allow" ? "low" : p.decision === "deny" ? "severe" : "sand"}>{p.decision}</Chip>
                    <span className="text-ink-700/80">
                      {p.subject_type} · {p.reasons.length ? p.reasons.join("; ") : `${Array.isArray(p.checks) ? p.checks.length : p.checks} checks passed`}
                    </span>
                  </li>
                ))}
              </ul>
            </Section>
            <Section title={t("assistant")} testid="assistant">
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  void act("ask", async () => setAnswer(await api(`/api/incidents/${detail.id}/assistant`, { method: "POST", json: { question } })));
                }}
              >
                <input className="flex-1 rounded-lg border border-ink-100 p-1.5 text-sm" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="What is the current band and why?" data-testid="assistant-input" />
                <button type="submit" className="btn-primary text-xs" disabled={busy !== null || question.length < 3} data-testid="assistant-ask">
                  {busy === "ask" ? <Spinner /> : t("ask")}
                </button>
              </form>
              {answer && (
                <div className="mt-2 text-xs" data-testid="assistant-answer">
                  <p className="rounded-lg bg-lagoon-100/60 p-2">{answer.answer}</p>
                  <p className="mt-1 text-ink-700/70">basis: {answer.basis}</p>
                  <ul className="mt-1 list-disc ps-4 text-ink-700/80">
                    {answer.cited_inputs.slice(0, 6).map((c) => (
                      <li key={c.id}>
                        <span className="font-mono">{c.type}:{c.id}</span> — {c.summary}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </Section>
          </div>
        </div>
      )}
    </div>
  );
}

function ProposalCard({ p, detail, latest, busy, act, note, setNote, myAuthority, canApprove, canRevise, editText, setEditText, ttl }: { p: Proposal; detail: IncidentDetail; latest: boolean; busy: string | null; act: (k: string, fn: () => Promise<unknown>) => Promise<void>; note: string; setNote: (s: string) => void; myAuthority: string[]; canApprove: boolean; canRevise: boolean; editText: string | null; setEditText: (s: string | null) => void; ttl: number }) {
  const { t, locale } = useI18n();
  const active = latest && detail.status === "awaiting_approval" && p.status === "proposed";
  const approvable = p.actions.some((a) => myAuthority.includes(a.kind));
  const approvableIdx = p.actions.map((a, i) => (myAuthority.includes(a.kind) ? i : -1)).filter((i) => i >= 0);
  const approve = (decision: "approved" | "rejected") =>
    act(`approve-${p.id}`, () =>
      api("/api/approvals", {
        method: "POST",
        json: { proposal_id: p.id, decision, note, action_indexes: approvableIdx.length === p.actions.length ? null : approvableIdx },
        idempotencyKey: newIdempotencyKey(`ui-${p.id}-${decision}`),
      }),
    );
  return (
    <div className={`mb-3 rounded-lg border p-3 ${active ? "border-sand-500 bg-sand-100/30" : "border-ink-100"}`} data-testid={`proposal-${p.id}`}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <b>
          {t("proposals")} v{p.version}
        </b>
        <Chip tone={p.status === "proposed" ? "sand" : p.status === "approved" ? "low" : p.status === "superseded" || p.status === "invalidated" ? "neutral" : "severe"}>{p.status}</Chip>
        <span className="ltr-only font-mono text-[10px] text-ink-700/60" data-testid="payload-hash">
          {t("payload_hash")} {p.payload_hash.slice(0, 16)}…
        </span>
        <span className="text-[11px] text-ink-700/60">incident v{p.incident_version}</span>
      </div>
      <ol className="mt-2 space-y-1 text-xs">
        {p.actions.map((a, i) => (
          <li key={i} className="flex flex-wrap items-start gap-2 rounded bg-white p-2" data-testid={`action-${i}`}>
            <Chip tone={myAuthority.includes(a.kind) ? "lagoon" : "neutral"}>{a.kind}</Chip>
            <span className="flex-1">
              {a.summary}
              {a.route && (
                <span className="ms-1 text-[11px] text-ink-700/70">
                  — route: {a.route.label ?? a.route.status ?? ""} {a.route.nodes ? `(${a.route.nodes.join("→")})` : ""}
                </span>
              )}
            </span>
            <span className="text-[10px] text-ink-700/60">
              {a.department} · {t("authority")}: {a.requires_authority}
            </span>
            {a.alert && <AlertCard alert={a.alert} locale={locale} />}
          </li>
        ))}
      </ol>
      {(p.public_text_en || p.public_text_ar) && (
        <div className="mt-2 rounded border border-ink-100 bg-white p-2 text-xs" data-testid="public-text">
          <div className="label">{t("public_text")}</div>
          {editText !== null && active && canRevise ? (
            <div className="mt-1 flex flex-col gap-1">
              <textarea className="w-full rounded border border-ink-100 p-1" rows={3} value={editText} onChange={(e) => setEditText(e.target.value)} data-testid="revise-text" />
              <div className="flex gap-1">
                <button type="button" className="btn-primary text-xs" disabled={busy !== null} onClick={() => void act("revise", async () => { await api(`/api/proposals/${p.id}/revise`, { method: "POST", json: { public_text_en: editText } }); setEditText(null); })} data-testid="revise-submit">
                  Save revision
                </button>
                <button type="button" className="btn-secondary text-xs" onClick={() => setEditText(null)}>
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <>
              <p className="mt-1">{locale === "ar" && p.public_text_ar ? p.public_text_ar : p.public_text_en}</p>
              {p.translation_status && <p className="mt-0.5 text-[10px] text-ink-700/60">translation: {p.translation_status}</p>}
              {active && canRevise && (
                <button type="button" className="mt-1 text-[11px] text-lagoon-600 underline" onClick={() => setEditText(p.public_text_en ?? "")} data-testid="revise-start">
                  {t("revise")}
                </button>
              )}
            </>
          )}
        </div>
      )}
      {p.assumptions.length > 0 && (
        <details className="mt-2 text-[11px] text-ink-700/80">
          <summary className="cursor-pointer">assumptions & flags ({p.assumptions.length})</summary>
          <ul className="list-disc ps-4">
            {p.assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </details>
      )}
      {active && (
        <div className="mt-3 border-t border-ink-100 pt-2">
          <div className="flex flex-wrap items-center gap-2">
            <input className="min-w-[200px] flex-1 rounded-lg border border-ink-100 p-1.5 text-xs" placeholder="approval note (optional)" value={note} onChange={(e) => setNote(e.target.value)} data-testid="approval-note" />
            <button type="button" className="btn-primary text-xs" disabled={busy !== null || !canApprove || !approvable} onClick={() => void approve("approved")} data-testid="approve">
              {busy === `approve-${p.id}` ? <Spinner /> : t("approve")}
              {approvable && approvableIdx.length < p.actions.length ? ` (${approvableIdx.length}/${p.actions.length} in my authority)` : ""}
            </button>
            <button type="button" className="btn-danger text-xs" disabled={busy !== null || !canApprove || !approvable} onClick={() => void approve("rejected")} data-testid="reject">
              {t("reject")}
            </button>
          </div>
          <p className="mt-1 text-[11px] text-ink-700/70">
            Approval binds incident v{detail.version}, proposal v{p.version}, payload hash, intended tools/destinations and your server-side identity; valid {ttl} min; re-checked at execution.
            {!approvable && canApprove ? " None of these actions fall within your approval authority." : ""}
            {!canApprove ? " Your role cannot approve actions (server-enforced)." : ""}
          </p>
        </div>
      )}
    </div>
  );
}

function WorkOrderRow({ w, busy, act, canAck, canComplete, locale }: { w: WorkOrder; busy: string | null; act: (k: string, fn: () => Promise<unknown>) => Promise<void>; canAck: boolean; canComplete: boolean; locale: "en" | "ar" }) {
  const { t } = useI18n();
  const tr = (status: string) => act(`wo-${w.id}-${status}`, () => api(`/api/work-orders/${w.id}/transition`, { method: "POST", json: { status, note: "" }, idempotencyKey: newIdempotencyKey(`wo-${w.id}-${status}`) }));
  const tone = w.status === "completed" ? "low" : w.status === "dispatched" ? "lagoon" : w.status === "acknowledged" || w.status === "in_progress" ? "sand" : w.status === "failed" || w.status === "rejected" || w.status === "expired" ? "severe" : "neutral";
  return (
    <li className="rounded-lg border border-ink-100 p-2 text-xs" data-testid={`wo-${w.id}`}>
      <div className="flex flex-wrap items-center gap-1">
        <Chip tone="neutral">{w.kind}</Chip>
        <Chip tone={tone} testid={`wo-status-${w.id}`}>
          {w.status}
        </Chip>
        <Chip tone="sand">connector: {w.connector}</Chip>
        <span className="flex-1">{w.payload.summary}</span>
        <span className="text-[10px] text-ink-700/60">{w.department}</span>
      </div>
      <div className="ltr-only mt-1 text-[10px] text-ink-700/60">
        dispatched {dubai(w.dispatched_at, locale)} · ack {dubai(w.acknowledged_at, locale)} · completed {dubai(w.completed_at, locale)}
        {w.escalation_due_at && w.status === "dispatched" ? ` · escalation due ${dubai(w.escalation_due_at, locale)}` : ""}
        {w.receipt ? ` · receipt ${String((w.receipt as { receipt_id?: string }).receipt_id ?? "simulated")}` : ""}
      </div>
      {Object.keys(w.physical_effect ?? {}).length > 0 && (
        <div className="mt-1 text-[10px]">
          physical effect {JSON.stringify(w.physical_effect)} — <b className={w.physical_effect_applied ? "text-band-low" : "text-ink-700/70"}>{w.physical_effect_applied ? "applied (completion recorded)" : "not applied until completion"}</b>
        </div>
      )}
      <div className="mt-1 flex flex-wrap gap-1">
        {w.status === "dispatched" && (
          <button type="button" className="btn-secondary text-xs" disabled={busy !== null || !canAck} onClick={() => void tr("acknowledged")} data-testid={`ack-${w.id}`}>
            {t("acknowledge")}
          </button>
        )}
        {w.status === "acknowledged" && (
          <button type="button" className="btn-secondary text-xs" disabled={busy !== null || !canAck} onClick={() => void tr("in_progress")} data-testid={`start-${w.id}`}>
            {t("start")}
          </button>
        )}
        {(w.status === "acknowledged" || w.status === "in_progress") && (
          <button type="button" className="btn-primary text-xs" disabled={busy !== null || !canComplete} onClick={() => void tr("completed")} data-testid={`complete-${w.id}`}>
            {t("complete")}
          </button>
        )}
      </div>
    </li>
  );
}

const LIKELIHOOD = ["low", "moderate", "high", "severe"] as const;
const CONSEQUENCE = ["minor", "moderate", "major", "severe"] as const;
const CELL_TONE = (li: number, ci: number) => {
  const s = li + ci;
  return s >= 5 ? "bg-band-severe/70 text-white" : s >= 3 ? "bg-band-high/60" : s >= 2 ? "bg-band-moderate/50" : "bg-band-low/40";
};

function RiskMatrix({ likelihood, consequence }: { likelihood: string | null; consequence: string | null }) {
  const { t } = useI18n();
  const li = LIKELIHOOD.indexOf((likelihood ?? "") as (typeof LIKELIHOOD)[number]);
  const ci = CONSEQUENCE.indexOf((consequence ?? "") as (typeof CONSEQUENCE)[number]);
  return (
    <div className="mt-3" data-testid="risk-matrix">
      <div className="label">{t("risk_matrix")}</div>
      <div className="mt-1 grid grid-cols-[auto_repeat(4,minmax(0,1fr))] gap-0.5 text-[10px]">
        <div />
        {CONSEQUENCE.map((c) => (
          <div key={c} className="text-center text-ink-700/70">
            {c}
          </div>
        ))}
        {[...LIKELIHOOD].reverse().map((l, ri) => {
          const lIdx = LIKELIHOOD.length - 1 - ri;
          return (
            <Fragment key={l}>
              <div className="pe-1 text-end text-ink-700/70">{l}</div>
              {CONSEQUENCE.map((c, cIdx) => {
                const here = lIdx === li && cIdx === ci;
                return (
                  <div key={c} className={`h-6 rounded ${CELL_TONE(lIdx, cIdx)} ${here ? "ring-2 ring-ink-900" : ""}`} data-testid={here ? "risk-cell-current" : undefined} title={`${l} × ${c}`} aria-label={here ? `current: ${l} likelihood, ${c} consequence` : undefined}>
                    {here && <span className="flex h-full items-center justify-center font-semibold">●</span>}
                  </div>
                );
              })}
            </Fragment>
          );
        })}
      </div>
      <p className="mt-1 text-[10px] text-ink-700/60">
        {t("risk_matrix_note")}
        {li < 0 || ci < 0 ? " · band unknown — no cell highlighted" : ""}
      </p>
    </div>
  );
}

function AlertCard({ alert, locale }: { alert: StructuredAlert; locale: "en" | "ar" }) {
  const { t } = useI18n();
  const tone = alert.message_level === "Emergency Warning" ? "severe" : alert.message_level === "Watch and Act" ? "high" : "sand";
  return (
    <div className="mt-1 w-full rounded border border-ink-100 bg-sand-100/40 p-2" data-testid="structured-alert">
      <div className="flex flex-wrap items-center gap-1">
        <span className="label">{t("structured_alert")}</span>
        <Chip tone={tone as "severe" | "high" | "sand"}>{alert.message_level}</Chip>
        <Chip tone="neutral">urgency {alert.urgency}</Chip>
        <Chip tone="neutral">severity {alert.severity}</Chip>
        <Chip tone="neutral" title={alert.certainty_basis}>
          certainty {alert.certainty}
        </Chip>
        <Chip tone="neutral">response {alert.response_type}</Chip>
        <Chip tone="neutral">expires +{alert.expires_minutes} min</Chip>
      </div>
      <p className="mt-1">{locale === "ar" ? alert.instruction_ar : alert.instruction_en}</p>
      <p className="mt-0.5 text-[10px] text-ink-700/60">
        {alert.standard} · {alert.sender} · {alert.certainty_basis}
      </p>
    </div>
  );
}

function SitrepView({ s, locale }: { s: Sitrep; locale: "en" | "ar" }) {
  const { t } = useI18n();
  const sit = s.situation as Record<string, string | string[] | null>;
  return (
    <div className="space-y-2 text-xs" data-testid="sitrep-view">
      <div className="ltr-only text-[10px] text-ink-700/60">
        generated {dubai(s.generated_at, locale)} by {s.generated_by} · incident v{s.version} · {s.basis}
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        <div className="rounded border border-ink-100 p-2">
          <div className="label">1 · situation</div>
          <div>
            {String(sit.title)} — {String(sit.label)} · {t("severity")} {String(sit.severity_band)} · {t("consequence")} {String(sit.consequence_band)} · evidence {String(sit.evidence_quality)}
          </div>
          <div className="text-ink-700/80">
            mechanism {String(sit.mechanism ?? "—")} · observed water {String(sit.observed_water ?? "—")} · exposed assets {(sit.exposed_assets as string[] | null)?.join(", ") || "—"}
          </div>
          <div className="text-[10px] text-ink-700/60">{String(sit.probability_note)}</div>
        </div>
        <div className="rounded border border-ink-100 p-2">
          <div className="label">2 · evidence</div>
          <div>
            {s.evidence.items} items · {s.evidence.independent_sources} independent sources · stale {s.evidence.stale.length} · conflicts {s.evidence.conflicts.length} · poor {s.evidence.poor_quality.length}
          </div>
          <div className="text-ink-700/80">
            field reports {s.evidence.field_reports.total} (accepted {s.evidence.field_reports.accepted}, pending {s.evidence.field_reports.pending}, with isolated instructions {s.evidence.field_reports.with_isolated_instructions})
          </div>
          {s.evidence.persona_failures.length > 0 && <div className="text-band-severe">persona failures: {s.evidence.persona_failures.join(", ")}</div>}
        </div>
        <div className="rounded border border-ink-100 p-2">
          <div className="label">3 · decisions</div>
          <div>
            {s.decisions.proposals} proposal(s)
            {s.decisions.latest_proposal ? ` · latest v${s.decisions.latest_proposal.version} ${s.decisions.latest_proposal.status}: ${s.decisions.latest_proposal.actions.join(", ")}` : ""}
          </div>
          <div className="text-ink-700/80">{s.decisions.approvals.length === 0 ? "no approvals" : s.decisions.approvals.map((a) => `${a.decision} (${a.approver_role}, ${a.status})`).join("; ")}</div>
        </div>
        <div className="rounded border border-ink-100 p-2">
          <div className="label">4 · resources / work orders</div>
          {s.resources.length === 0 ? (
            <div>—</div>
          ) : (
            <ul>
              {s.resources.map((r) => (
                <li key={r.id}>
                  {r.kind} · {r.department} · <b>{r.status}</b>
                  {r.physical_effect_applied ? " · effect applied" : ""}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="rounded border border-ink-100 p-2">
          <div className="label">5 · open items</div>
          {s.open_items.length === 0 ? <div>none</div> : <ul className="list-disc ps-4">{s.open_items.map((o, i) => <li key={i}>{o}</li>)}</ul>}
        </div>
        <div className="rounded border border-ink-100 p-2">
          <div className="label">6 · {t("op_period")}</div>
          <div className="ltr-only">
            {dubai(s.operational_period.start, locale)} → {s.operational_period.closed_at ? dubai(s.operational_period.closed_at, locale) : "open"} · {t("elapsed")} {s.operational_period.elapsed_minutes} min · {s.operational_period.status}
          </div>
        </div>
      </div>
      <div className="rounded bg-sand-100 p-2 text-[10px] text-ink-700/80">
        <div className="label">7 · caveats</div>
        <ul className="list-disc ps-4">{s.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>
      </div>
      {s.after_action_review && (
        <div className="rounded border border-ink-100 p-2">
          <div className="label">8 · after-action review</div>
          <pre className="whitespace-pre-wrap font-sans">{JSON.stringify(s.after_action_review, null, 1).replace(/[{}"]/g, "")}</pre>
        </div>
      )}
    </div>
  );
}

function sitrepText(s: Sitrep, locale: "en" | "ar"): string {
  const sit = s.situation as Record<string, unknown>;
  const lines = [
    `SITREP — incident ${s.incident_id} v${s.version} — generated ${dubai(s.generated_at, locale)} by ${s.generated_by}`,
    `Basis: ${s.basis}`,
    "",
    `1. SITUATION: ${sit.title} — ${sit.label}; severity ${sit.severity_band}; consequence ${sit.consequence_band}; evidence ${sit.evidence_quality}; mechanism ${sit.mechanism ?? "-"}; exposed assets ${(sit.exposed_assets as string[] | undefined)?.join(", ") || "-"}. ${sit.probability_note}`,
    `2. EVIDENCE: ${s.evidence.items} items from ${s.evidence.independent_sources} independent sources; stale ${s.evidence.stale.length}; conflicts ${s.evidence.conflicts.length}; poor ${s.evidence.poor_quality.length}; field reports ${s.evidence.field_reports.total} (accepted ${s.evidence.field_reports.accepted}, pending ${s.evidence.field_reports.pending}).`,
    `3. DECISIONS: ${s.decisions.proposals} proposal(s)${s.decisions.latest_proposal ? `; latest v${s.decisions.latest_proposal.version} ${s.decisions.latest_proposal.status} [${s.decisions.latest_proposal.actions.join(", ")}] hash ${s.decisions.latest_proposal.payload_hash.slice(0, 12)}` : ""}; approvals: ${s.decisions.approvals.map((a) => `${a.decision}/${a.approver_role}/${a.status}`).join(", ") || "none"}.`,
    `4. RESOURCES: ${s.resources.map((r) => `${r.kind} (${r.department}) ${r.status}${r.physical_effect_applied ? " [effect applied]" : ""}`).join("; ") || "-"}`,
    `5. OPEN ITEMS: ${s.open_items.length ? s.open_items.map((o) => `\n   - ${o}`).join("") : "none"}`,
    `6. OPERATIONAL PERIOD: from ${dubai(s.operational_period.start, locale)}; elapsed ${s.operational_period.elapsed_minutes} min; status ${s.operational_period.status}${s.operational_period.closed_at ? `; closed ${dubai(s.operational_period.closed_at, locale)}` : ""}`,
    `7. CAVEATS: ${s.caveats.join(" ")}`,
  ];
  if (s.after_action_review) lines.push(`8. AFTER-ACTION REVIEW: ${JSON.stringify(s.after_action_review)}`);
  return lines.join("\n");
}
