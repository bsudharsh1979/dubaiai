"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import type { Scenario, TwinResponse, TwinResult } from "@/lib/types";
import { SectorMap } from "@/components/SectorMap";
import { BandChip, Chip, ErrorBox, KV, Section, Spinner } from "@/components/ui";

type Controls = { rain_multiplier: number; drain_blockage: number; pump_availability: number; extra_pump_m3_s: number; sensor_outage: string[]; report_reliability: "normal" | "low"; leak_rate_lps: number };
const DEFAULT: Controls = { rain_multiplier: 1, drain_blockage: 0, pump_availability: 1, extra_pump_m3_s: 0, sensor_outage: [], report_reliability: "normal", leak_rate_lps: 0 };

export default function TwinPage() {
  const { t } = useI18n();
  const { identity, can } = useSession();
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState<string>("SC-A-rainfall");
  const [controls, setControls] = useState<Controls>(DEFAULT);
  const [res, setRes] = useState<TwinResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sensors, setSensors] = useState<{ id: string; kind: string }[]>([]);
  const [persistMsg, setPersistMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!identity) return;
    api<Scenario[]>("/api/scenarios").then((s) => setScenarios(s.filter((x) => x.kind === "rainfall" || x.kind === "hse"))).catch(setError);
  }, [identity]);

  useEffect(() => {
    if (!identity || !scenarioId) return;
    api<{ controls: Partial<Controls>; sensors: { id: string; kind: string }[] }>(`/api/twin/${scenarioId}/state`)
      .then((s) => {
        setControls({ ...DEFAULT, ...s.controls });
        setSensors(s.sensors);
      })
      .catch(setError);
  }, [identity, scenarioId]);

  const simulate = useCallback(
    async (persist = false) => {
      if (!identity || !can("twin:control")) return;
      setBusy(true);
      setError(null);
      try {
        const r = await api<TwinResponse>("/api/twin/simulate", { method: "POST", json: { scenario_id: scenarioId, controls, persist_to_scenario: persist } });
        setRes(r);
        if (persist) setPersistMsg(`Controls saved to scenario; reassessment queued for ${JSON.stringify((r.persisted as { reassess_queued_for?: string[] })?.reassess_queued_for ?? [])}`);
      } catch (e) {
        setError(e);
      } finally {
        setBusy(false);
      }
    },
    [identity, can, scenarioId, controls],
  );

  useEffect(() => {
    const h = setTimeout(() => void simulate(false), 250);
    return () => clearTimeout(h);
  }, [simulate]);

  const bands = useMemo(() => Object.fromEntries(Object.entries(res?.intervention.catchments ?? {}).map(([k, v]) => [k, v.worst_band])), [res]);

  return (
    <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
      <div className="space-y-4">
        <Section title={t("twin_title")} testid="twin-controls">
          <label className="label">Scenario</label>
          <select className="mb-3 w-full rounded-lg border border-ink-100 p-2 text-sm" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} data-testid="twin-scenario">
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <Slider label={t("rain_multiplier")} value={controls.rain_multiplier} min={0} max={3} step={0.1} onChange={(v) => setControls((c) => ({ ...c, rain_multiplier: v }))} testid="slider-rain" fmt={(v) => `× ${v.toFixed(1)}`} />
          <Slider label={t("drain_blockage")} value={controls.drain_blockage} min={0} max={1} step={0.05} onChange={(v) => setControls((c) => ({ ...c, drain_blockage: v }))} testid="slider-blockage" fmt={(v) => `${Math.round(v * 100)} %`} />
          <Slider label={t("pump_availability")} value={controls.pump_availability} min={0} max={1} step={0.05} onChange={(v) => setControls((c) => ({ ...c, pump_availability: v }))} testid="slider-pump" fmt={(v) => `${Math.round(v * 100)} %`} />
          <Slider label={t("extra_pump")} value={controls.extra_pump_m3_s} min={0} max={1} step={0.05} onChange={(v) => setControls((c) => ({ ...c, extra_pump_m3_s: v }))} testid="slider-extra-pump" fmt={(v) => `${v.toFixed(2)} m³/s`} />
          <p className="mb-2 text-[11px] text-ink-700/70">{t("ack_note")}</p>
          <div className="mb-2">
            <div className="label">{t("sensor_outage")}</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {sensors.map((s) => {
                const on = controls.sensor_outage.includes(s.id);
                return (
                  <button key={s.id} type="button" onClick={() => setControls((c) => ({ ...c, sensor_outage: on ? c.sensor_outage.filter((x) => x !== s.id) : [...c.sensor_outage, s.id] }))} className={`chip ${on ? "border-band-severe/50 bg-band-severe/10 text-band-severe" : "border-ink-100"}`} data-testid={`outage-${s.id}`}>
                    {s.id}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="mb-3">
            <div className="label">{t("report_reliability")}</div>
            <select className="mt-1 w-full rounded-lg border border-ink-100 p-1.5 text-sm" value={controls.report_reliability} onChange={(e) => setControls((c) => ({ ...c, report_reliability: e.target.value as "normal" | "low" }))}>
              <option value="normal">normal</option>
              <option value="low">low (disputed / single source)</option>
            </select>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-secondary text-xs" onClick={() => setControls(DEFAULT)}>
              Reset
            </button>
            <button type="button" className="btn-primary text-xs" disabled={busy || !can("twin:control")} onClick={() => void simulate(true)} data-testid="persist-controls">
              {busy ? <Spinner /> : "Apply to scenario & reassess open incidents"}
            </button>
          </div>
          {persistMsg && <p className="mt-2 text-[11px] text-lagoon-600">{persistMsg}</p>}
          {!can("twin:control") && <p className="mt-2 text-xs text-band-severe">Your role cannot change twin controls (server-enforced).</p>}
          <ErrorBox error={error} />
        </Section>
        {res && (
          <Section title={t("compare_note")} testid="twin-compare">
            {Object.entries(res.comparison.per_catchment).map(([cid, c]) => (
              <div key={cid} className="mb-2 rounded-lg border border-ink-100 p-2 text-sm">
                <div className="font-medium">{res.intervention.catchments[cid]?.name ?? cid}</div>
                <KV k={t("baseline")} v={<span className="flex items-center gap-2"><span className="ltr-only">{c.baseline_peak_depth_m.toFixed(2)} m</span><BandChip band={c.baseline_band} /></span>} />
                <KV k={t("intervention")} v={<span className="flex items-center gap-2"><span className="ltr-only">{c.intervention_peak_depth_m.toFixed(2)} m</span><BandChip band={c.intervention_band} /></span>} />
                <KV k="Δ" v={<span className={`ltr-only ${c.delta_depth_m > 0 ? "text-band-severe" : c.delta_depth_m < 0 ? "text-band-low" : ""}`}>{c.delta_depth_m > 0 ? "+" : ""}{c.delta_depth_m.toFixed(2)} m</span>} />
              </div>
            ))}
            <div className="text-[11px] text-ink-700/70">
              {Object.keys(res.comparison.control_changes).length ? `Changed controls: ${Object.entries(res.comparison.control_changes).map(([k, [a, b]]) => `${k} ${String(a)}→${String(b)}`).join(", ")}` : "No control differences from the saved scenario baseline."}
            </div>
          </Section>
        )}
      </div>
      <div className="space-y-4">
        <SectorMap overlay={{ bands, sensorOutage: controls.sensor_outage }} height={360} />
        {res ? <TwinCharts result={res.intervention} baseline={res.baseline} /> : <Section title={t("twin_title")}>{busy ? <Spinner /> : "—"}</Section>}
      </div>
    </div>
  );
}

function Slider({ label, value, min, max, step, onChange, testid, fmt }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; testid: string; fmt: (v: number) => string }) {
  return (
    <label className="mb-2 block text-sm">
      <div className="flex justify-between">
        <span>{label}</span>
        <span className="ltr-only font-mono text-xs">{fmt(value)}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(parseFloat(e.target.value))} className="w-full" data-testid={testid} />
    </label>
  );
}

function TwinCharts({ result, baseline }: { result: TwinResult; baseline: TwinResult }) {
  const { t } = useI18n();
  return (
    <Section
      title={
        <span className="flex flex-wrap items-center gap-2">
          {result.tool_version}
          <Chip tone="sand">{result.label}</Chip>
          <BandChip band={result.overall_band} prefix="overall" />
        </span>
      }
      testid="twin-result"
    >
      <div className="grid gap-4 md:grid-cols-2">
        {Object.entries(result.series).map(([cid, series]) => (
          <div key={cid} className="rounded-lg border border-ink-100 p-2">
            <div className="mb-1 flex flex-wrap items-center justify-between gap-1 text-sm">
              <span className="font-medium">{result.catchments[cid].name}</span>
              <Chip tone={result.catchments[cid].mechanism === "flash_flood" ? "high" : "lagoon"}>{result.catchments[cid].mechanism}</Chip>
            </div>
            <DepthChart series={series} baseline={baseline.series[cid] ?? []} threshold={Math.min(...result.catchments[cid].protects.map((a) => result.asset_thresholds_m?.[a] ?? 0.3), 0.3)} />
            <div className="mt-1 grid grid-cols-3 gap-1 text-[11px]">
              {Object.entries(result.snapshots).map(([h, snap]) => (
                <div key={h} className="rounded bg-ink-100/50 p-1 text-center" data-testid={`snapshot-${cid}-${h}`}>
                  <div className="font-mono">{h} min</div>
                  <div className="ltr-only">{snap[cid]?.depth_m.toFixed(2)} m</div>
                  <BandChip band={snap[cid]?.band} />
                </div>
              ))}
            </div>
            <div className="mt-1 text-[11px] text-ink-700/70 ltr-only">
              {t("peak_depth")}: <b data-testid={`peak-${cid}`}>{result.catchments[cid].peak_depth_m.toFixed(2)} m</b> · final storage {result.catchments[cid].final_storage_m3.toFixed(0)} m³
              {result.forecast_total_mm?.[cid] != null ? ` · forecast total ${result.forecast_total_mm[cid]} mm` : ""}
            </div>
          </div>
        ))}
      </div>
      <div className="ltr-only mt-2 text-[11px] text-ink-700/70" data-testid="twin-totals">
        System totals (m³): rain in {result.totals_m3.rain_in?.toFixed(0)} = drained {result.totals_m3.drained?.toFixed(0)} + pumped {result.totals_m3.pumped?.toFixed(0)} + stored/in transit + spilled out {result.totals_m3.spilled_out?.toFixed(0)} · max mass-balance error {result.mass_balance_max_error_m3.toExponential(1)} m³
      </div>
      <ul className="mt-3 list-disc space-y-0.5 ps-5 text-[11px] text-ink-700/80">
        {result.assumptions.map((a) => (
          <li key={a}>{a}</li>
        ))}
        <li>{t("horizon_note")}</li>
      </ul>
    </Section>
  );
}

function DepthChart({ series, baseline, threshold }: { series: { t_min: number; depth_m: number; rain_mm_h: number }[]; baseline: { t_min: number; depth_m: number }[]; threshold: number }) {
  const W = 420;
  const H = 150;
  const pad = 26;
  const maxT = series.at(-1)?.t_min ?? 180;
  const maxD = Math.max(threshold * 1.4, ...series.map((p) => p.depth_m), ...baseline.map((p) => p.depth_m), 0.1);
  const maxR = Math.max(10, ...series.map((p) => p.rain_mm_h));
  const x = (tm: number) => pad + ((W - 2 * pad) * tm) / maxT;
  const y = (d: number) => H - pad - ((H - 2 * pad) * d) / maxD;
  const yr = (r: number) => H - pad - ((H - 2 * pad) * r) / maxR;
  const path = (pts: { t_min: number; depth_m: number }[]) => pts.map((p, i) => `${i ? "L" : "M"}${x(p.t_min).toFixed(1)},${y(p.depth_m).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="ltr-only w-full" role="img" aria-label="synthetic depth over time">
      <rect x={pad} y={pad} width={W - 2 * pad} height={H - 2 * pad} fill="#f8fbfc" stroke="#dfeaee" />
      {series.map((p) => (
        <rect key={p.t_min} x={x(p.t_min) - 3} y={yr(p.rain_mm_h)} width={5} height={H - pad - yr(p.rain_mm_h)} fill="#139aa8" opacity={0.25} />
      ))}
      <line x1={pad} x2={W - pad} y1={y(threshold)} y2={y(threshold)} stroke="#b42318" strokeDasharray="4 3" />
      <text x={W - pad} y={y(threshold) - 3} fontSize="9" fill="#b42318" textAnchor="end">
        threshold {threshold} m
      </text>
      <path d={path(baseline)} fill="none" stroke="#8da3ab" strokeWidth="1.5" strokeDasharray="3 3" />
      <path d={path(series)} fill="none" stroke="#0b2a34" strokeWidth="2" />
      {[30, 60, 180].map((h) => (
        <g key={h}>
          <line x1={x(h)} x2={x(h)} y1={pad} y2={H - pad} stroke="#c89b3c" strokeWidth="0.8" />
          <text x={x(h)} y={H - pad + 10} fontSize="9" textAnchor="middle" fill="#7a5a14">
            +{h}
          </text>
        </g>
      ))}
      <text x={pad - 4} y={pad + 4} fontSize="9" textAnchor="end">
        {maxD.toFixed(1)} m
      </text>
      <text x={pad - 4} y={H - pad} fontSize="9" textAnchor="end">
        0
      </text>
      <text x={W - pad} y={pad - 6} fontSize="9" textAnchor="end" fill="#139aa8">
        rain ≤ {maxR.toFixed(0)} mm/h
      </text>
    </svg>
  );
}
