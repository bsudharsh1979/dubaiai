"use client";
import { useCallback, useEffect, useState } from "react";
import { API_BASE, api, ApiError, dubai } from "@/lib/api";
import { pick, useI18n } from "@/lib/i18n";
import { useLive, useSession } from "@/lib/session";
import type { FieldReport, Incident } from "@/lib/types";
import { Chip, Empty, ErrorBox, Section, Spinner } from "@/components/ui";

type Scene = { id: string; platform: string; role: string; scenario_id: string | null; acquisition_at: string; available_at: string; crs: string; resolution: string; orbit: string | null; cloud_fraction: number | null; quality_flags: string[]; derived: Record<string, unknown> };

export default function FieldPage() {
  const { t, locale } = useI18n();
  const { identity, can } = useSession();
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [reports, setReports] = useState<FieldReport[]>([]);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [form, setForm] = useState({ description: "", lat: "25.1900", lon: "55.3100", capture_time: new Date().toISOString().slice(0, 16), incident_id: "" });
  const [photo, setPhoto] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<(FieldReport & { note?: string | null; guard?: Record<string, unknown> }) | null>(null);
  const [importMsg, setImportMsg] = useState<unknown>(null);

  const load = useCallback(async () => {
    if (!identity) return;
    try {
      const [inc, rep, sc] = await Promise.all([api<Incident[]>("/api/incidents"), api<FieldReport[]>("/api/field-reports"), api<Scene[]>("/api/scenes")]);
      setIncidents(inc);
      setReports(rep);
      setScenes(sc);
    } catch (e) {
      setError(e);
    }
  }, [identity]);
  useLive(load, ["field_report", "incident", "import", "security"], [identity?.id]);

  useEffect(() => {
    if (!form.incident_id && incidents[0]) setForm((f) => ({ ...f, incident_id: incidents[0].id }));
  }, [incidents, form.incident_id]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const fd = new FormData();
      fd.set("description", form.description);
      fd.set("lat", form.lat);
      fd.set("lon", form.lon);
      fd.set("capture_time", new Date(form.capture_time).toISOString());
      if (form.incident_id) fd.set("incident_id", form.incident_id);
      if (photo) fd.set("photo", photo, photo.name);
      const res = await fetch(`${API_BASE}/api/field-reports`, { method: "POST", body: fd, credentials: "include" });
      const data = await res.json();
      if (!res.ok) throw new ApiError(res.status, data.detail ?? data);
      setResult(data);
      setForm((f) => ({ ...f, description: "" }));
      setPhoto(null);
      await load();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const review = async (id: string, review_status: string, reliability: string) => {
    setBusy(true);
    try {
      await api(`/api/field-reports/${id}/review`, { method: "POST", json: { review_status, reliability } });
      await load();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const useLocation = () => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition((p) => setForm((f) => ({ ...f, lat: p.coords.latitude.toFixed(5), lon: p.coords.longitude.toFixed(5) })));
  };

  const runFixtureImport = async () => {
    setBusy(true);
    setImportMsg(null);
    try {
      setImportMsg(await api("/api/imports/sentinel1/fixture", { method: "POST" }));
      await load();
    } catch (e) {
      setImportMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
      <div className="space-y-4">
        <Section title={t("field_title")} testid="field-form">
          <form onSubmit={submit} className="space-y-2 text-sm">
            <label className="block">
              <span className="label">Incident</span>
              <select className="mt-0.5 w-full rounded-lg border border-ink-100 p-2" value={form.incident_id} onChange={(e) => setForm({ ...form, incident_id: e.target.value })} data-testid="field-incident">
                <option value="">(none — attach later)</option>
                {incidents.map((i) => (
                  <option key={i.id} value={i.id}>
                    {pick(locale, i, "title")} · {i.status}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="label">{t("description")}</span>
              <textarea className="mt-0.5 w-full rounded-lg border border-ink-100 p-2" rows={4} required value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="What do you observe? Water extent, inlet condition, pump status, access…" data-testid="field-description" />
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className="block">
                <span className="label">lat</span>
                <input className="ltr-only mt-0.5 w-full rounded-lg border border-ink-100 p-2" value={form.lat} onChange={(e) => setForm({ ...form, lat: e.target.value })} inputMode="decimal" data-testid="field-lat" />
              </label>
              <label className="block">
                <span className="label">lon</span>
                <input className="ltr-only mt-0.5 w-full rounded-lg border border-ink-100 p-2" value={form.lon} onChange={(e) => setForm({ ...form, lon: e.target.value })} inputMode="decimal" data-testid="field-lon" />
              </label>
            </div>
            <button type="button" className="btn-secondary text-xs" onClick={useLocation}>
              Use device location
            </button>
            <label className="block">
              <span className="label">{t("capture_time")} (local)</span>
              <input type="datetime-local" className="ltr-only mt-0.5 w-full rounded-lg border border-ink-100 p-2" value={form.capture_time} onChange={(e) => setForm({ ...form, capture_time: e.target.value })} data-testid="field-time" />
            </label>
            <label className="block">
              <span className="label">{t("photo")}</span>
              <input type="file" accept="image/jpeg,image/png" className="mt-0.5 w-full text-xs" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} data-testid="field-photo" />
            </label>
            <button type="submit" className="btn-primary w-full" disabled={busy || !can("field_report:submit") || form.description.length < 3} data-testid="field-submit">
              {busy ? <Spinner /> : t("submit")}
            </button>
          </form>
          <ErrorBox error={error} />
          {result && (
            <div className="mt-3 rounded-lg border border-ink-100 bg-lagoon-100/40 p-2 text-xs" data-testid="field-result">
              <div className="flex flex-wrap gap-1">
                <Chip tone="low">submitted {result.id}</Chip>
                <Chip tone="sand">reliability: {result.reliability}</Chip>
                {result.safety_flags.map((f) => (
                  <Chip key={f} tone="high">
                    {f}
                  </Chip>
                ))}
              </div>
              {result.isolated_instructions.length > 0 && (
                <div className="mt-1 rounded border border-band-severe/40 bg-white p-2 text-band-severe" data-testid="isolated-instructions">
                  <b>{t("isolated")}:</b>
                  <ul className="list-disc ps-4">
                    {result.isolated_instructions.map((s, i) => (
                      <li key={i}>“{s}”</li>
                    ))}
                  </ul>
                  <p className="mt-1 text-ink-700/80">Observation retained for review: “{result.observation_text}”</p>
                </div>
              )}
              {result.note && <p className="mt-1">{result.note}</p>}
            </div>
          )}
        </Section>

        <Section title="Sentinel-1 before/after import (local GeoTIFF pair)" testid="import-panel">
          <p className="text-xs text-ink-700/80">
            Imports validate CRS, overlap, alignment, units (dB) and nodata, require the same relative orbit and preprocessing, and produce a baseline change mask labelled “candidate inundation at acquisition time” with permanent water and shadow masked and an explicit unknown class. Licensed Copernicus data: see <code>docs/DATA_ACCESS.md</code>.
          </p>
          <button type="button" className="btn-secondary mt-2 text-xs" disabled={busy || !can("import:raster")} onClick={() => void runFixtureImport()} data-testid="import-fixture">
            Run synthetic fixture import
          </button>
          {!can("import:raster") && <p className="mt-1 text-[11px] text-band-severe">Your role cannot import rasters.</p>}
          {importMsg !== null && <pre className="ltr-only mt-2 max-h-48 overflow-auto rounded bg-ink-950 p-2 text-[10px] text-ink-100">{typeof importMsg === "string" ? importMsg : JSON.stringify(importMsg, null, 1)}</pre>}
          <div className="mt-2 text-[11px]">
            <div className="label mb-1">Scenes</div>
            <ul className="space-y-1">
              {scenes.map((s) => (
                <li key={s.id} className="rounded border border-ink-100 p-1.5">
                  <span className="font-mono">{s.id}</span> · {s.platform} · {s.role} · <span className="ltr-only">{dubai(s.acquisition_at, locale)}</span> · {s.crs} · {s.resolution}
                  {s.cloud_fraction != null ? ` · cloud ${s.cloud_fraction}` : ""}
                  <div className="text-ink-700/70">{String(s.derived?.label ?? "metadata only")} {s.quality_flags.length ? `· flags: ${s.quality_flags.join(", ")}` : ""}</div>
                </li>
              ))}
            </ul>
          </div>
        </Section>
      </div>

      <Section title={t("my_reports")} testid="report-list">
        {reports.length === 0 ? (
          <Empty>—</Empty>
        ) : (
          <ul className="space-y-2 text-xs">
            {reports.map((r) => (
              <li key={r.id} className="rounded-lg border border-ink-100 p-2" data-testid={`report-${r.id}`}>
                <div className="flex flex-wrap items-center gap-1">
                  <span className="font-mono text-[10px]">{r.id}</span>
                  <Chip tone={r.review_status === "accepted" ? "low" : r.review_status === "rejected" ? "severe" : "sand"}>{r.review_status}</Chip>
                  <Chip tone={r.reliability === "corroborated" ? "low" : r.reliability === "disputed" || r.reliability === "faulty" ? "severe" : "neutral"}>{r.reliability}</Chip>
                  {r.safety_flags.map((f) => (
                    <Chip key={f} tone={f.startsWith("casualty") || f.startsWith("privileged") ? "severe" : "high"}>
                      {f}
                    </Chip>
                  ))}
                  <span className="ms-auto text-[10px] text-ink-700/60 ltr-only">
                    {r.reporter_id} · {dubai(r.created_at, locale)} · {r.incident_id ?? r.scenario_id ?? "unattached"}
                  </span>
                </div>
                <p className="mt-1">{r.observation_text}</p>
                {r.isolated_instructions.length > 0 && (
                  <p className="mt-1 text-band-severe">
                    {t("isolated")}: {r.isolated_instructions.map((s) => `“${s}”`).join(" ")}
                  </p>
                )}
                {r.has_photo && <p className="ltr-only mt-1 text-[10px] text-ink-700/60">photo {r.photo_mime} sha256 {r.photo_sha256?.slice(0, 16)}… (EXIF never read; stored under random name)</p>}
                {can("field_report:review") && r.review_status === "pending" && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    <button type="button" className="btn-primary text-xs" disabled={busy} onClick={() => void review(r.id, "accepted", "corroborated")} data-testid={`accept-${r.id}`}>
                      {t("accept")} (corroborated)
                    </button>
                    <button type="button" className="btn-secondary text-xs" disabled={busy} onClick={() => void review(r.id, "needs_follow_up", "unverified")}>
                      Needs follow-up
                    </button>
                    <button type="button" className="btn-danger text-xs" disabled={busy} onClick={() => void review(r.id, "rejected", "faulty")}>
                      Reject (faulty)
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
