"use client";
import type { ReactNode } from "react";
import { BAND_LABELS, LABEL_LABELS, STATUS_LABELS, tl, useI18n } from "@/lib/i18n";

type Tone = "low" | "moderate" | "high" | "severe" | "lagoon" | "sand" | "neutral" | "ink";

const TONES: Record<Tone, string> = {
  low: "border-band-low/40 bg-band-low/10 text-band-low",
  moderate: "border-band-moderate/50 bg-band-moderate/10 text-[#8a6a10]",
  high: "border-band-high/50 bg-band-high/10 text-band-high",
  severe: "border-band-severe/50 bg-band-severe/10 text-band-severe",
  lagoon: "border-lagoon-500/40 bg-lagoon-100 text-lagoon-600",
  sand: "border-sand-500/50 bg-sand-100 text-[#7a5a14]",
  neutral: "border-ink-100 bg-ink-100/50 text-ink-700",
  ink: "border-ink-700 bg-ink-800 text-white",
};

export function Chip({ tone = "neutral", children, title, testid }: { tone?: Tone; children: ReactNode; title?: string; testid?: string }) {
  return (
    <span className={`chip ${TONES[tone]}`} title={title} data-testid={testid}>
      {children}
    </span>
  );
}

export function BandChip({ band, prefix }: { band: string | null | undefined; prefix?: string }) {
  const { locale } = useI18n();
  const tone = (band && band in TONES ? band : "neutral") as Tone;
  return (
    <Chip tone={tone} testid="band-chip">
      {prefix ? `${prefix} ` : ""}
      {tl(locale, BAND_LABELS, band ?? "unknown")}
    </Chip>
  );
}

export function LabelChip({ label }: { label: string | null | undefined }) {
  const { locale } = useI18n();
  const tone: Tone = label === "confirmed_incident" ? "severe" : label === "suspected_incident" ? "high" : label === "forecast_risk" ? "moderate" : label === "anomaly" ? "sand" : "lagoon";
  return (
    <Chip tone={tone} testid="label-chip">
      {tl(locale, LABEL_LABELS, label)}
    </Chip>
  );
}

export function StatusChip({ status }: { status: string | null | undefined }) {
  const { locale } = useI18n();
  const tone: Tone = status === "awaiting_approval" ? "sand" : status === "urgent_human_review" ? "severe" : status === "awaiting_evidence" ? "high" : status === "responding" ? "lagoon" : status === "closed" ? "low" : "neutral";
  return (
    <Chip tone={tone} testid="status-chip">
      {tl(locale, STATUS_LABELS, status)}
    </Chip>
  );
}

export function Section({ title, children, right, testid, className = "" }: { title: ReactNode; children: ReactNode; right?: ReactNode; testid?: string; className?: string }) {
  return (
    <section className={`card p-4 ${className}`} data-testid={testid}>
      <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-ink-900">{title}</h2>
        {right}
      </header>
      {children}
    </section>
  );
}

export function KV({ k, v }: { k: ReactNode; v: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-ink-100/70 py-1 text-sm last:border-0">
      <span className="text-ink-700/80">{k}</span>
      <span className="text-end font-medium">{v}</span>
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const { t } = useI18n();
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" data-testid="error-box" className="rounded-lg border border-band-severe/40 bg-band-severe/5 px-3 py-2 text-sm text-band-severe">
      <span className="font-semibold">{t("error")}:</span> {msg}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-ink-100 p-4 text-center text-sm text-ink-700/70">{children}</p>;
}

export function Spinner() {
  return <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-lagoon-500 border-t-transparent align-middle" aria-label="loading" />;
}
