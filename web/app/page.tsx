"use client";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { api, dubai } from "@/lib/api";
import { pick, useI18n } from "@/lib/i18n";
import { useLive, useSession } from "@/lib/session";
import type { Incident, Scenario } from "@/lib/types";
import { SectorMap } from "@/components/SectorMap";
import { ExecutiveOverview } from "@/components/EventFlow";
import { SignInPanel } from "@/components/Shell";
import { BandChip, Chip, Empty, ErrorBox, KV, LabelChip, Section, Spinner, StatusChip } from "@/components/ui";

export default function CommandPage() {
  const { t, locale } = useI18n();
  const { identity, can, events, loading } = useSession();
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!identity) return;
    try {
      const [sc, inc] = await Promise.all([api<Scenario[]>("/api/scenarios"), api<Incident[]>("/api/incidents")]);
      setScenarios(sc);
      setIncidents(inc);
      setSelected((s) => s ?? inc[0]?.id ?? null);
    } catch (e) {
      setError(e);
    }
  }, [identity]);
  useLive(load, ["incident", "approval", "work_order", "dispatch", "system", "twin"], [identity?.id]);

  const run = async (id: string) => {
    setBusy(id);
    setError(null);
    try {
      const r = await api<{ incident_id: string; duplicate_suppressed: boolean }>(`/api/scenarios/${id}/run`, { method: "POST", json: {} });
      setSelected(r.incident_id);
      await load();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };

  const sel = incidents.find((i) => i.id === selected) ?? null;
  const overlay = useMemo(() => {
    const hyd = (sel?.summary?.hydrology ?? {}) as { catchment_bands?: Record<string, string>; peak_depth_by_catchment_m?: Record<string, number> };
    const bands: Record<string, string> = hyd.catchment_bands ?? {};
    if (!Object.keys(bands).length && hyd.peak_depth_by_catchment_m) {
      for (const [cid, d] of Object.entries(hyd.peak_depth_by_catchment_m)) bands[cid] = d >= 0.3 ? "severe" : d >= 0.18 ? "high" : d >= 0.075 ? "moderate" : "low";
    }
    return { hazard: sel?.geometry ? ({ type: "Feature", geometry: sel.geometry, properties: { id: sel.id } } as GeoJSON.Feature) : null, bands };
  }, [sel]);

  const commandView = (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]" data-testid="command-view">
      <div className="space-y-4">
        <SectorMap overlay={overlay} height={440} />
        <Section title={t("incidents")} testid="incident-list" right={<Chip tone="neutral">{incidents.length}</Chip>}>
          {incidents.length === 0 ? (
            <Empty>{t("no_incidents")}</Empty>
          ) : (
            <ul className="divide-y divide-ink-100">
              {incidents.map((i) => (
                <li key={i.id}>
                  <button type="button" onClick={() => setSelected(i.id)} className={`flex w-full flex-wrap items-center gap-2 px-1 py-2 text-start text-sm hover:bg-ink-100/40 ${selected === i.id ? "bg-lagoon-100/50" : ""}`} data-testid={`incident-row-${i.id}`}>
                    <span className="flex-1 font-medium">{pick(locale, i, "title")}</span>
                    <LabelChip label={i.label} />
                    <BandChip band={i.severity_band} />
                    <StatusChip status={i.status} />
                    <span className="text-[11px] text-ink-700/70 ltr-only">{dubai(i.created_at, locale)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
      <div className="space-y-4">
        <Section title={t("scenarios")} testid="scenario-list">
          <ErrorBox error={error} />
          <ul className="space-y-2">
            {scenarios.map((s) => (
              <li key={s.id} className="rounded-lg border border-ink-100 p-3">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-sm font-medium">{s.name}</div>
                    <div className="mt-0.5 text-xs text-ink-700/80">{s.description}</div>
                    <div className="mt-1 flex flex-wrap gap-1 text-[11px]">
                      <Chip tone="sand">{s.data_mode}</Chip>
                      <Chip tone="neutral">{s.kind}</Chip>
                      <span className="text-ink-700/70 ltr-only">
                        {t("decision_time")}: {dubai(s.decision_time, locale)}
                      </span>
                    </div>
                  </div>
                  <button type="button" data-testid={`run-${s.id}`} disabled={!can("scenario:run") || busy !== null} onClick={() => void run(s.id)} className="btn-primary shrink-0 text-xs">
                    {busy === s.id ? <Spinner /> : s.open_incidents.length ? t("reassess") : t("run_scenario")}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </Section>
        {sel && (
          <Section title={pick(locale, sel, "title")} testid="incident-summary" right={<Link href={`/incidents?id=${sel.id}`} className="text-xs text-lagoon-600 underline">{t("nav_incidents")} →</Link>}>
            <div className="mb-2 flex flex-wrap gap-1">
              <LabelChip label={sel.label} />
              <StatusChip status={sel.status} />
            </div>
            <KV k={t("severity")} v={<BandChip band={sel.severity_band} />} />
            <KV k={t("consequence")} v={<BandChip band={sel.consequence} />} />
            <KV k={t("evidence_quality")} v={sel.evidence_quality ?? "—"} />
            <KV k={t("probability")} v={sel.calibrated_probability ?? <span className="text-xs text-ink-700/70">{sel.probability_note}</span>} />
            <KV k={t("version")} v={`v${sel.version}`} />
            <div className="mt-2 rounded-lg bg-sand-100 p-2 text-sm" data-testid="next-decision">
              <span className="label">{t("next_decision")}</span>
              <div>{sel.next_decision}</div>
            </div>
            {sel.summary?.hydrology && (
              <div className="mt-2 text-xs text-ink-700/80">
                {t("mechanism")}: {String((sel.summary.hydrology as Record<string, unknown>).mechanism ?? "—")} · {String((sel.summary.hydrology as Record<string, unknown>).observed_water_label ?? "")}
              </div>
            )}
          </Section>
        )}
        <Section title="Live events" testid="live-events">
          <ul className="max-h-64 space-y-1 overflow-auto text-[11px]">
            {events.slice(0, 40).map((e) => (
              <li key={e.seq} className="flex gap-2 border-b border-ink-100/60 py-0.5">
                <span className="w-24 shrink-0 font-mono text-ink-700/70">{e.topic}</span>
                <span className="truncate">{summarise(e.data)}</span>
              </li>
            ))}
            {events.length === 0 && <li className="text-ink-700/60">— waiting for events —</li>}
          </ul>
        </Section>
      </div>
    </div>
  );

  return (
    <div className="space-y-4">
      <ExecutiveOverview currentStatus={sel?.status ?? null} incidentTitle={sel ? pick(locale, sel, "title") : null} />
      {!loading && !identity ? (
        <div className="space-y-2" data-testid="command-signin">
          <p className="text-center text-sm text-ink-700">{t("sign_in_to_operate")}</p>
          <SignInPanel compact />
        </div>
      ) : (
        commandView
      )}
    </div>
  );
}

function summarise(d: Record<string, unknown>): string {
  return Object.entries(d)
    .filter(([k]) => !["incident_id"].includes(k))
    .slice(0, 4)
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v).slice(0, 40) : String(v)}`)
    .join(" ");
}
