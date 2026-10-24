"use client";
import Link from "next/link";
import { Fragment, useEffect, useState } from "react";
import { tl, useI18n, STATUS_LABELS, type Locale } from "@/lib/i18n";
import { Chip } from "./ui";

/**
 * Executive summary + "ways of working" of the agentic system, drawn as a flow of events.
 * Everything here is static explanation except the live marker, which is derived from the
 * persisted status of the selected incident (no timers, no pretended progress).
 */

type Lane = "signals" | "tools" | "agents" | "policy" | "human" | "departments" | "review";

const LANE: Record<Lane, { en: string; ar: string; stripe: string; dot: string; chip: "sand" | "lagoon" | "neutral" | "ink" | "severe" | "low" | "high" }> = {
  signals: { en: "Signals", ar: "الإشارات", stripe: "border-s-ink-700", dot: "bg-ink-700", chip: "neutral" },
  tools: { en: "Hazard tools", ar: "أدوات المخاطر", stripe: "border-s-lagoon-600", dot: "bg-lagoon-600", chip: "lagoon" },
  agents: { en: "AI personas", ar: "شخصيات الذكاء الاصطناعي", stripe: "border-s-sand-500", dot: "bg-sand-500", chip: "sand" },
  policy: { en: "Policy engine", ar: "محرك السياسات", stripe: "border-s-ink-900", dot: "bg-ink-900", chip: "ink" },
  human: { en: "Human authority", ar: "الصلاحية البشرية", stripe: "border-s-band-severe", dot: "bg-band-severe", chip: "severe" },
  departments: { en: "Departments (simulated)", ar: "الإدارات (محاكاة)", stripe: "border-s-band-high", dot: "bg-band-high", chip: "high" },
  review: { en: "Review & closure", ar: "المراجعة والإغلاق", stripe: "border-s-band-low", dot: "bg-band-low", chip: "low" },
};

type Event = {
  n: number;
  lane: Lane;
  title: [string, string];
  what: [string, string];
  guard: [string, string];
  statuses: string[]; // persisted incident statuses that mean "the incident is here now"
  href?: string;
};

const EVENTS: Event[] = [
  {
    n: 1,
    lane: "signals",
    title: ["A signal arrives", "تصل إشارة"],
    what: ["Rain nowcast, gauge or level reading, Sentinel-1 scene, utility flow/pressure, or a field report. Each record carries observed_at, available_at, units, CRS, quality flags and licence.", "تنبؤ قريب للمطر، قراءة مقياس أو منسوب، مشهد سنتينل-1، تدفق/ضغط شبكة المياه، أو تقرير ميداني. كل سجل يحمل وقت الرصد والإتاحة والوحدات والنظام الإحداثي وأعلام الجودة والرخصة."],
    guard: ["Only data available at the decision time is used; no future leakage.", "تُستخدم فقط البيانات المتاحة وقت القرار؛ لا تسرّب من المستقبل."],
    statuses: [],
    href: "/assurance",
  },
  {
    n: 2,
    lane: "agents",
    title: ["Observer validates & correlates", "المراقب يتحقق ويربط"],
    what: ["The Observer persona checks freshness, conflicts and duplicates, and opens or re-assesses one incident per place and label.", "شخصية المراقب تفحص الحداثة والتعارض والتكرار، وتفتح أو تعيد تقييم حادثة واحدة لكل موقع وتصنيف."],
    guard: ["Instructions hidden in field reports are quarantined as data; observations and casualty mentions are kept.", "التعليمات المخفية في التقارير تُعزل كبيانات؛ وتُحفظ الملاحظات وإشارات الإصابات."],
    statuses: ["open", "assessing"],
    href: "/agents",
  },
  {
    n: 3,
    lane: "tools",
    title: ["Hazard tools compute the numbers", "أدوات المخاطر تحسب الأرقام"],
    what: ["Versioned deterministic tools run: water-balance twin, SAR change screen, leak residual screen, asset exposure, constrained routing. Output is ordinal bands with a 'scenario model — uncalibrated' label.", "تعمل أدوات حتمية ذات إصدارات: توأم موازنة المياه، فحص تغيّر الرادار، فحص بواقي التسرب، تعرّض الأصول، التوجيه المقيّد. المخرجات نطاقات ترتيبية موسومة «نموذج سيناريو — غير معاير»."],
    guard: ["No persona may invent a hazard value; six labels are never merged; no probabilities without calibration.", "لا تخترع أي شخصية قيمة خطر؛ التصنيفات الستة لا تُدمج؛ لا احتمالات دون معايرة."],
    statuses: [],
    href: "/twin",
  },
  {
    n: 4,
    lane: "agents",
    title: ["Specialist personas coordinate", "الشخصيات المتخصصة تنسّق"],
    what: ["Hydrologist, Utility Engineer, HSE Officer, Communications and Assurance read tool results and produce typed summaries; the Response Planner drafts bounded actions and a CAP-aligned advisory.", "الهيدرولوجي ومهندس المرافق ومسؤول السلامة والاتصال والضمان يقرؤون نتائج الأدوات وينتجون ملخصات منظمة؛ ومخطط الاستجابة يصوغ إجراءات محدودة وتنبيهاً متوافقاً مع CAP."],
    guard: ["Tool allowlists and budgets per persona; at most two evidence loops, then urgent human review.", "قوائم أدوات وميزانيات لكل شخصية؛ حلقتا أدلة كحد أقصى ثم مراجعة بشرية عاجلة."],
    statuses: ["awaiting_evidence", "urgent_human_review", "planning"],
    href: "/agents",
  },
  {
    n: 5,
    lane: "policy",
    title: ["Policy engine decides who may approve", "محرك السياسات يحدد من يوافق"],
    what: ["Deterministic rules map each action to the roles allowed to approve it, apply duplicate suppression and emergency stop, and record the decision.", "قواعد حتمية تربط كل إجراء بالأدوار المخوّلة بالموافقة، وتطبق قمع التكرار وإيقاف الطوارئ، وتسجل القرار."],
    guard: ["Roles come from the server-signed session only; the client can never grant authority.", "الأدوار من الجلسة الموقعة على الخادم فقط؛ لا يستطيع العميل منح صلاحية."],
    statuses: [],
    href: "/incidents",
  },
  {
    n: 6,
    lane: "human",
    title: ["A human approves (workflow pauses)", "إنسان يوافق (يتوقف سير العمل)"],
    what: ["The graph interrupts. The approver sees the risk matrix, the structured alert, the evidence and the exact payload hash, then approves or rejects.", "يتوقف المخطط. يرى الموافق مصفوفة المخاطر والتنبيه المنظم والأدلة وبصمة الحمولة بالضبط ثم يوافق أو يرفض."],
    guard: ["Approval is bound to incident version, hash, tools, destinations, approver and expiry; any edit voids it; it survives restarts.", "الموافقة مرتبطة بإصدار الحادثة والبصمة والأدوات والوجهات والموافق والصلاحية؛ أي تعديل يلغيها؛ وتصمد بعد إعادة التشغيل."],
    statuses: ["awaiting_approval"],
    href: "/incidents",
  },
  {
    n: 7,
    lane: "departments",
    title: ["Work orders dispatched (simulated)", "إرسال أوامر العمل (محاكاة)"],
    what: ["The gateway re-checks the approval, then sends work orders to drainage, transport, utility, HSE and advisory channels and stores the receipts.", "تعيد البوابة التحقق من الموافقة ثم ترسل أوامر العمل إلى الصرف والنقل والمرافق والسلامة وقنوات التنبيه وتحفظ الإيصالات."],
    guard: ["No valve, power or evacuation control endpoint exists; connectors are labelled simulated.", "لا توجد نقطة تحكم في صمام أو طاقة أو إخلاء؛ الموصلات موسومة محاكاة."],
    statuses: ["awaiting_execution"],
    href: "/incidents",
  },
  {
    n: 8,
    lane: "departments",
    title: ["Acknowledgement ≠ action", "الإقرار ≠ الإجراء"],
    what: ["Crews acknowledge, start and complete. Only completion applies a physical effect, bumps the incident version and triggers reassessment; unanswered dispatches escalate.", "تقرّ الفرق وتبدأ وتنجز. الإنجاز فقط يطبّق أثراً فعلياً ويرفع إصدار الحادثة ويطلق إعادة التقييم؛ وتُصعَّد الإرساليات دون رد."],
    guard: ["Every write carries an idempotency key; nothing is repeated on resume.", "كل كتابة تحمل مفتاح تكرار آمن؛ لا يتكرر شيء عند الاستئناف."],
    statuses: ["responding"],
    href: "/incidents",
  },
  {
    n: 9,
    lane: "review",
    title: ["Reassess, report, close", "إعادة التقييم والتقرير والإغلاق"],
    what: ["Personas re-run on the new version. A SITREP can be generated from stored state at any time. Closure needs a new observation or reviewed report plus the incident-commander role; open work is stood down and an after-action review recorded.", "تُعاد الشخصيات على الإصدار الجديد. يمكن توليد تقرير موقف من الحالة المحفوظة في أي وقت. الإغلاق يتطلب رصداً جديداً أو تقريراً مراجعاً مع دور قائد الحادثة؛ تُوقف الأعمال المفتوحة وتُسجل مراجعة ما بعد الحدث."],
    guard: ["Hash-linked audit chain (tamper-evident); honest 'not evaluated' wherever labelled data is missing.", "سلسلة تدقيق مرتبطة بالبصمات؛ «غير مُقيَّم» بصدق حيث تغيب البيانات الموسومة."],
    statuses: ["monitoring", "closure_pending", "closed", "cancelled"],
    href: "/incidents",
  },
];

const L = (locale: Locale, pair: [string, string]) => (locale === "ar" ? pair[1] : pair[0]);

const STORAGE_KEY = "rr.overview.collapsed";

export function ExecutiveOverview({ currentStatus, incidentTitle }: { currentStatus?: string | null; incidentTitle?: string | null }) {
  const { t, locale } = useI18n();
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(STORAGE_KEY) === "1");
    } catch {
      /* storage unavailable */
    }
  }, []);
  const toggle = () => {
    setCollapsed((c) => {
      try {
        window.localStorage.setItem(STORAGE_KEY, c ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !c;
    });
  };
  const currentIdx = currentStatus ? EVENTS.findIndex((e) => e.statuses.includes(currentStatus)) : -1;

  return (
    <section className="card p-4" data-testid="exec-overview" data-collapsed={collapsed ? "1" : "0"}>
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="max-w-4xl">
          <h1 className="text-base font-semibold">{t("how_title")}</h1>
          {!collapsed && <p className="mt-1 text-sm leading-relaxed text-ink-900">{t("how_lede")}</p>}
          <div className="mt-2 flex flex-wrap gap-1">
            <Chip tone="sand">{locale === "ar" ? "نموذج أولي" : "prototype"}</Chip>
            <Chip tone="sand">{locale === "ar" ? "بيانات اصطناعية" : "synthetic data"}</Chip>
            <Chip tone="sand">{locale === "ar" ? "موصلات محاكاة" : "simulated connectors"}</Chip>
            <Chip tone="lagoon">{locale === "ar" ? "استجابة بموافقة بشرية" : "human-approved response"}</Chip>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/how-it-works" className="text-xs text-lagoon-600 underline" data-testid="overview-more">
            {t("nav_how")} →
          </Link>
          <button type="button" onClick={toggle} className="rounded-md border border-ink-100 px-2 py-1 text-xs hover:bg-ink-100/60" data-testid="overview-toggle" aria-expanded={!collapsed}>
            {collapsed ? t("overview_expand") : t("overview_collapse")}
          </button>
        </div>
      </header>

      {!collapsed && (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-700" data-testid="flow-lanes">
            <span className="label">{t("flow_lanes")}:</span>
            {(Object.keys(LANE) as Lane[]).map((k) => (
              <span key={k} className="flex items-center gap-1">
                <span className={`inline-block h-2.5 w-2.5 rounded-full ${LANE[k].dot}`} aria-hidden />
                {locale === "ar" ? LANE[k].ar : LANE[k].en}
              </span>
            ))}
          </div>

          <ol className="mt-3 flex gap-0 overflow-x-auto pb-2" data-testid="event-flow" aria-label={t("flow_title")}>
            {EVENTS.map((e, i) => {
              const live = i === currentIdx;
              const lane = LANE[e.lane];
              return (
                <Fragment key={e.n}>
                  <li className={`relative w-[232px] shrink-0 rounded-lg border border-ink-100 border-s-4 bg-white p-3 ${lane.stripe} ${live ? "ring-2 ring-lagoon-500 shadow-md" : ""}`} data-testid={`flow-event-${e.n}`} data-live={live ? "1" : "0"}>
                    <div className="flex items-center justify-between gap-2">
                      <span className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold text-white ${lane.dot}`}>{e.n}</span>
                      <Chip tone={lane.chip}>{locale === "ar" ? lane.ar : lane.en}</Chip>
                    </div>
                    <h3 className="mt-2 text-sm font-semibold leading-snug">{L(locale, e.title)}</h3>
                    <p className="mt-1 text-[11px] leading-relaxed text-ink-700">{L(locale, e.what)}</p>
                    <p className="mt-2 rounded bg-sand-100/70 px-2 py-1 text-[11px] leading-relaxed text-[#7a5a14]">
                      <span className="font-semibold">{t("flow_guardrail")}: </span>
                      {L(locale, e.guard)}
                    </p>
                    {live && (
                      <div className="mt-2 text-[11px] font-medium text-lagoon-600" data-testid="flow-live-marker">
                        ● {t("flow_live_here")}
                        {currentStatus ? ` — ${tl(locale, STATUS_LABELS, currentStatus)}` : ""}
                      </div>
                    )}
                    {e.href && (
                      <Link href={e.href} className="mt-2 inline-block text-[11px] text-lagoon-600 underline">
                        {t("flow_open_view")} →
                      </Link>
                    )}
                  </li>
                  {i < EVENTS.length - 1 && (
                    <li aria-hidden className="flex w-7 shrink-0 items-center justify-center text-ink-700/50">
                      <span className="text-lg rtl:rotate-180">→</span>
                    </li>
                  )}
                </Fragment>
              );
            })}
          </ol>
          <p className="mt-1 text-[11px] text-ink-700/70" data-testid="flow-note">
            {currentIdx >= 0 && incidentTitle ? `${t("flow_marker_note")} — ${incidentTitle}.` : t("flow_marker_none")}
          </p>

          <div className="mt-3 grid gap-2 text-[11px] text-ink-700 md:grid-cols-3" data-testid="flow-ways">
            <div className="rounded-lg bg-ink-100/40 p-2">
              <div className="font-semibold text-ink-900">{locale === "ar" ? "ماذا يفعل الذكاء الاصطناعي" : "What the AI does"}</div>
              {locale === "ar" ? "يقرأ الأدلة، يشغّل الأدوات، يلخّص، يقترح إجراءات محدودة ويصوغ التنبيهات. لا يحسب الأرقام بنفسه ولا ينفّذ شيئاً." : "Reads evidence, runs tools, summarises, proposes bounded actions and drafts alerts. It never computes hazard numbers itself and never executes anything."}
            </div>
            <div className="rounded-lg bg-ink-100/40 p-2">
              <div className="font-semibold text-ink-900">{locale === "ar" ? "ماذا يفعل الإنسان" : "What people do"}</div>
              {locale === "ar" ? "يراجعون الأدلة ومصفوفة المخاطر، يوافقون أو يرفضون كل إجراء، يؤكدون الإنجاز، يغلقون الحادثة ويسجلون الدروس." : "Review the evidence and risk matrix, approve or reject every action, confirm completion, close the incident and record lessons."}
            </div>
            <div className="rounded-lg bg-ink-100/40 p-2">
              <div className="font-semibold text-ink-900">{locale === "ar" ? "ما لا يحدث أبداً" : "What never happens"}</div>
              {locale === "ar" ? "لا تحكم فعلي في صمام أو طاقة أو إخلاء؛ لا تبديل صامت للمزود؛ لا نسب دقة أو أرواح أُنقذت مُدّعاة؛ لا صلاحية من جهة العميل." : "No real valve, power or evacuation control; no silent provider switch; no claimed accuracy or lives saved; no authority granted by the client."}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
