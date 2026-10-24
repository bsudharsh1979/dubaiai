"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useI18n, type StringKey } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { Chip } from "./ui";

const NAV: { href: string; key: StringKey; testid: string }[] = [
  { href: "/", key: "nav_command", testid: "nav-command" },
  { href: "/twin", key: "nav_twin", testid: "nav-twin" },
  { href: "/agents", key: "nav_agents", testid: "nav-agents" },
  { href: "/incidents", key: "nav_incidents", testid: "nav-incidents" },
  { href: "/field", key: "nav_field", testid: "nav-field" },
  { href: "/assurance", key: "nav_assurance", testid: "nav-assurance" },
  { href: "/how-it-works", key: "nav_how", testid: "nav-how" },
];

// Pages that render without identity: the explanatory page, and the landing page whose executive overview is
// static (the command view inside it renders SignInPanel itself until an identity exists).
const PUBLIC_PATHS = new Set(["/", "/how-it-works", "/how-it-works/"]);

export function Shell({ children }: { children: ReactNode }) {
  const { t, locale, setLocale } = useI18n();
  const { identity, identities, config, login, logout, loading } = useSession();
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const modes = config?.modes;

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-ink-800 bg-ink-900 text-white">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2">
          <Link href="/" className="flex items-center gap-2">
            <Logo />
            <div className="leading-tight">
              <div className="text-base font-semibold tracking-tight">{t("app_name")}</div>
              <div className="text-[11px] text-ink-100/80">{t("app_sub")}</div>
            </div>
          </Link>
          <nav className="order-3 flex w-full gap-1 overflow-x-auto md:order-none md:w-auto md:flex-1 md:justify-center" aria-label="Primary">
            {NAV.map((n) => {
              const active = n.href === "/" ? path === "/" : path?.startsWith(n.href);
              return (
                <Link key={n.href} href={n.href} data-testid={n.testid} className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm ${active ? "bg-lagoon-600 text-white" : "text-ink-100 hover:bg-ink-800"}`}>
                  {t(n.key)}
                </Link>
              );
            })}
          </nav>
          <div className="ms-auto flex items-center gap-2">
            <button type="button" data-testid="lang-toggle" onClick={() => setLocale(locale === "ar" ? "en" : "ar")} className="rounded-md border border-ink-700 px-2 py-1 text-xs hover:bg-ink-800">
              {t("arabic")}
            </button>
            <div className="relative">
              <button type="button" data-testid="identity-button" onClick={() => setOpen((o) => !o)} className="flex items-center gap-2 rounded-md border border-ink-700 px-2 py-1 text-xs hover:bg-ink-800">
                <span className="hidden sm:inline text-ink-100/70">{identity ? t("identity") : t("not_signed_in")}</span>
                <span className="font-medium">{identity ? `${identity.name} · ${identity.role_label}` : "—"}</span>
              </button>
              {open && (
                <div className="absolute end-0 mt-1 w-80 rounded-lg border border-ink-100 bg-white p-2 text-ink-900 shadow-xl">
                  <div className="label mb-1">{t("switch_identity")}</div>
                  {modes?.demo_identity_switcher ? (
                    <ul className="max-h-80 overflow-auto">
                      {identities.map((u) => (
                        <li key={u.id}>
                          <button
                            type="button"
                            data-testid={`identity-${u.id}`}
                            onClick={async () => {
                              await login(u.id);
                              setOpen(false);
                            }}
                            className={`flex w-full flex-col items-start rounded-md px-2 py-1.5 text-start text-sm hover:bg-ink-100/60 ${identity?.id === u.id ? "bg-lagoon-100" : ""}`}
                          >
                            <span className="font-medium">{u.name}</span>
                            <span className="text-xs text-ink-700/80">
                              {u.role_label} — {u.organisation}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="p-2 text-xs">Identity is assigned by the server (SSO/IdP in production). Demo switcher disabled.</p>
                  )}
                  {identity && (
                    <button type="button" onClick={() => void logout()} className="btn-secondary mt-2 w-full text-xs">
                      Sign out
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
        <ModeBar />
      </header>
      {modes?.emergency_stop && (
        <div data-testid="emergency-banner" className="bg-band-severe px-4 py-1.5 text-center text-sm font-semibold text-white">
          {t("emergency_stop")}
        </div>
      )}
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-4">
        {!loading && !identity && !PUBLIC_PATHS.has(path ?? "") ? <SignInPanel /> : children}
      </main>
      <footer className="border-t border-ink-100 bg-white px-4 py-3 text-[11px] text-ink-700/80">
        <div className="mx-auto flex max-w-[1600px] flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <span>{t("disclaimer")}</span>
          <ArchitectureStrip />
        </div>
      </footer>
    </div>
  );
}

function ModeBar() {
  const { t } = useI18n();
  const { config } = useSession();
  const m = config?.modes;
  if (!m) return null;
  return (
    <div data-testid="mode-bar" className="border-t border-ink-800 bg-ink-950/70 px-4 py-1 text-[11px] text-ink-100">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-2">
        <Chip tone={m.data_mode === "synthetic" ? "sand" : m.data_mode === "connected" ? "severe" : "lagoon"}>
          {t("mode_data")}: {m.data_mode}
        </Chip>
        <Chip tone={m.model_provider === "demo" ? "sand" : "lagoon"}>
          {t("mode_model")}: {m.model_provider}
          {m.model_provider === "demo" ? " (rehearsal — no inference)" : ""}
        </Chip>
        <Chip tone={m.action_connectors === "simulated" ? "sand" : "severe"}>
          {t("mode_connectors")}: {m.action_connectors}
        </Chip>
        <Chip tone={m.sovereign_mode ? "lagoon" : "severe"}>
          {t("mode_sovereign")}: {m.sovereign_mode ? "on" : "off"}
        </Chip>
        <Chip tone="neutral">env: {m.app_env}</Chip>
      </div>
    </div>
  );
}

function ArchitectureStrip() {
  const { t } = useI18n();
  const { config } = useSession();
  if (!config) return null;
  return (
    <div className="flex flex-wrap items-center gap-1" data-testid="architecture-strip">
      <span className="label me-1">{t("architecture")}:</span>
      {config.architecture.map((a, i) => (
        <span key={a} className="flex items-center gap-1">
          <span className="rounded bg-ink-100/70 px-1.5 py-0.5">{a}</span>
          {i < config.architecture.length - 1 && <span aria-hidden>→</span>}
        </span>
      ))}
    </div>
  );
}

export function SignInPanel({ compact = false }: { compact?: boolean }) {
  const { t } = useI18n();
  const { identities, login, config } = useSession();
  return (
    <div className={`mx-auto max-w-xl card p-6 ${compact ? "mt-2" : "mt-10"}`} data-testid="sign-in">
      <h1 className="text-lg font-semibold">{t("app_name")}</h1>
      <p className="mt-1 text-sm text-ink-700">{t("sign_in_hint")}</p>
      {config?.modes.demo_identity_switcher ? (
        <ul className="mt-4 grid gap-2 sm:grid-cols-2">
          {identities.map((u) => (
            <li key={u.id}>
              <button type="button" data-testid={`signin-${u.id}`} onClick={() => void login(u.id)} className="w-full rounded-lg border border-ink-100 p-3 text-start hover:border-lagoon-500 hover:bg-lagoon-100/40">
                <div className="font-medium">{u.name}</div>
                <div className="text-xs text-ink-700/80">{u.role_label}</div>
                <div className="text-[11px] text-ink-700/60">{u.organisation}</div>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-sm">Demo identity switcher is disabled in this environment. Sign in through the organisation identity provider.</p>
      )}
    </div>
  );
}

function Logo() {
  return (
    <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden className="shrink-0">
      <defs>
        <linearGradient id="rr-g" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="#139aa8" />
          <stop offset="1" stopColor="#0c7c8a" />
        </linearGradient>
      </defs>
      <path d="M17 3c5 7 10 12 10 18a10 10 0 1 1-20 0C7 15 12 10 17 3z" fill="url(#rr-g)" />
      <path d="M10 22h14M12 26h10" stroke="#f7eed8" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
