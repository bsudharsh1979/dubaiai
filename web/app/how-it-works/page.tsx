"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useI18n, type Locale } from "@/lib/i18n";
import { Chip, ErrorBox, Section } from "@/components/ui";

type Health = {
  ok: boolean;
  modes: Record<string, unknown>;
  worker: { alive: boolean; queued_jobs?: number };
  providers: { kind: string; provider: string; configured: boolean; healthy: boolean; exercised: boolean; model_id: string }[];
  integrations: { feed_id: string; name: string; status: string }[];
  guard_gate: Record<string, unknown>;
  time: Record<string, string>;
};

const L = (locale: Locale, en: string, ar: string) => (locale === "ar" ? ar : en);

const STAGES: [string, string, string, string][] = [
  ["1", "Signals", "الإشارات", "Rain gauges, water levels, nowcasts, Sentinel-1 before/after scenes, utility flow and pressure, field reports. Every record carries provenance: observed_at, available_at, CRS, units, quality flags, licence."],
  ["2", "Brain 1 — hazard tools", "الدماغ 1 — أدوات المخاطر", "Versioned, deterministic tools are the only source of numbers: water-balance twin (mass-conserving; flash flood vs waterlogging), SAR change screen, residual leak screen, asset exposure, constrained router. Labelled 'scenario model — uncalibrated'."],
  ["3", "Brain 2 — eight personas", "الدماغ 2 — ثماني شخصيات", "Observer, Hydrologist, Utility Engineer, HSE Officer, Response Planner, Communications Officer, Assurance Officer, Incident Coordinator. Typed outputs, tool allowlists, budgets, at most two evidence loops then urgent human review."],
  ["4", "Authority", "الصلاحية", "A deterministic policy engine decides who may approve what. Approval is a workflow interrupt bound to incident version, payload hash, tools, destinations, approver and expiry. Any edit voids it; the gateway re-checks at execution."],
  ["5", "Departments", "الإدارات", "Simulated dispatch to drainage, transport, utility, HSE and advisory channels. No valve, power or evacuation endpoint exists. Acknowledgement changes nothing physical; only completion does."],
  ["6", "Reassessment & closure", "إعادة التقييم والإغلاق", "Completion applies the effect, bumps the incident version and re-runs the personas. Closure requires a new observation or reviewed report plus the incident-commander role; open work orders are stood down; an after-action review can be recorded."],
];

const AR_STAGE_TEXT: Record<string, string> = {
  "1": "مقاييس المطر، مناسيب المياه، التنبؤات القريبة، مشاهد سنتينل-1 قبل/بعد، تدفق وضغط شبكة المياه، التقارير الميدانية. كل سجل يحمل مصدره ووقت رصده وإتاحته ووحداته وجودته ورخصته.",
  "2": "أدوات حتمية ذات إصدارات هي المصدر الوحيد للأرقام: توأم موازنة المياه (حفظ الكتلة؛ فيضان خاطف مقابل تجمّع مياه)، فحص تغيّر الرادار، فحص بواقي التسرب، تعرّض الأصول، التوجيه المقيّد. موسومة «نموذج سيناريو — غير معاير».",
  "3": "المراقب، الهيدرولوجي، مهندس المرافق، مسؤول الصحة والسلامة، مخطط الاستجابة، مسؤول الاتصال، مسؤول الضمان، منسق الحادثة. مخرجات منظمة، قوائم أدوات مسموحة، ميزانيات، حلقتا أدلة كحد أقصى ثم مراجعة بشرية عاجلة.",
  "4": "محرك سياسات حتمي يحدد من يوافق على ماذا. الموافقة توقّف في سير العمل مرتبط بإصدار الحادثة وبصمة الحمولة والأدوات والوجهات والموافق ومدة الصلاحية. أي تعديل يلغيها؛ تُعاد المراجعة عند التنفيذ.",
  "5": "إرسال محاكى إلى الصرف والنقل والمرافق والسلامة وقنوات التنبيه. لا توجد نقطة تحكم فعلية في صمام أو طاقة أو إخلاء. الإقرار لا يغيّر الواقع؛ الإنجاز فقط يفعل.",
  "6": "الإنجاز يطبّق الأثر ويرفع إصدار الحادثة ويعيد تشغيل الشخصيات. الإغلاق يتطلب رصداً جديداً أو تقريراً مراجعاً مع دور قائد الحادثة؛ تُوقف أوامر العمل المفتوحة؛ ويمكن تسجيل مراجعة ما بعد الحدث.",
};

const FEATURES: [string, string, string, string][] = [
  ["Six labels, never merged", "ستة تصنيفات لا تُدمج", "observed water · susceptibility · forecast risk · anomaly · suspected incident · confirmed incident — ordinal bands only, no uncalibrated probabilities.", "مياه مرصودة · قابلية · خطر متوقع · شذوذ · حادث مشتبه · حادث مؤكد — نطاقات ترتيبية فقط."],
  ["Versioned hazard tools", "أدوات مخاطر ذات إصدارات", "Numbers come only from tools with a mass-balance assertion; the planner never invents hazard values.", "الأرقام من الأدوات فقط مع تحقق حفظ الكتلة؛ المخطط لا يخترع قيماً."],
  ["Bounded personas", "شخصيات مقيّدة", "Typed I/O, tool allowlists, call and time budgets, structured summaries instead of chain-of-thought.", "مدخلات ومخرجات منظمة، قوائم أدوات مسموحة، ميزانيات، ملخصات منظمة."],
  ["Hash-bound human approval", "موافقة بشرية مرتبطة بالبصمة", "Edit ⇒ new version ⇒ old approval invalid; idempotent; survives restart; re-checked at execution.", "التعديل ينشئ إصداراً جديداً ويلغي الموافقة؛ متكرر آمن؛ يصمد بعد إعادة التشغيل."],
  ["Ack ≠ action", "الإقرار ≠ الإجراء", "Only completion changes state; closure needs new evidence and authority; open work orders stood down at closure.", "الإنجاز فقط يغيّر الحالة؛ الإغلاق يحتاج دليلاً جديداً وصلاحية."],
  ["Untrusted text is data", "النص غير الموثوق بيانات", "Instructions inside field reports are quarantined; observations kept; casualty mentions preserved and escalated.", "تُعزل التعليمات داخل التقارير؛ تُحفظ الملاحظات؛ تُصعَّد إشارات الإصابات."],
  ["Structured public alert", "تنبيه عام منظّم", "Advisory drafts carry CAP-aligned urgency / severity / certainty / response type and a three-tier message level, mapped from bands — for human approval.", "مسودات التنبيه تحمل حقول CAP ومستوى رسالة ثلاثي المستويات — للموافقة البشرية."],
  ["Situation report on demand", "تقرير موقف عند الطلب", "An ICS-style SITREP assembled from persisted state only: situation, evidence, decisions, resources, open items, operational period, caveats.", "تقرير موقف بنمط نظام قيادة الحوادث من الحالة المحفوظة فقط."],
  ["What-if digital twin", "توأم رقمي افتراضي", "Rain, blockage, pumps, sensor outage, report reliability; baseline vs intervention at +30/+60/+180 min simulation horizons.", "المطر، الانسداد، المضخات، تعطل المستشعرات؛ الأساس مقابل التدخل."],
  ["Sovereign by configuration", "سيادي بالتهيئة", "Provider allowlist, no cloud fallback, server-only secrets, offline basemap; demo → local NIM → approved hosted, never silently.", "قائمة مزودين مسموحة، لا رجوع سحابي، أسرار على الخادم فقط، خريطة محلية."],
  ["Assurance built in", "ضمان مدمج", "Hash-linked audit chain (tamper-evident), emergency stop, guard-outage rules, redacted logs, honest 'not evaluated'.", "سلسلة تدقيق مرتبطة بالبصمات، إيقاف طوارئ، قواعد تعطل الحارس، سجلات محجوبة."],
  ["Bilingual, offline", "ثنائي اللغة، دون اتصال", "English and Arabic (RTL) across all views; no external tiles, fonts or CDN.", "الإنجليزية والعربية في كل الشاشات؛ دون بلاطات أو خطوط خارجية."],
];

const PRACTICES: [string, string, string][] = [
  ["Common Alerting Protocol (OASIS CAP 1.2) — international alert interchange standard", "Advisory drafts carry CAP-aligned urgency, severity, certainty and response type. Certainty is mapped from evidence completeness, never from a probability.", "Proposal → advisory action → 'Structured alert'"],
  ["Three-tier public warning levels (as used by national warning systems such as Australia's Advice / Watch and Act / Emergency Warning)", "Message level follows the severity band so the public message and the call to action are consistent.", "Structured alert → message level"],
  ["Flood-risk matrix (likelihood × impact, as in the UK Flood Guidance Statement)", "The incident header shows a likelihood-band × consequence-band matrix with the current cell highlighted — ordinal, no percentages.", "Incident & approvals → Risk matrix"],
  ["Incident briefing / situation report (incident command systems, e.g. ICS-201 pattern)", "One-click SITREP from persisted state: situation, evidence, decisions, resources, open items, operational period, caveats. Copy as text for a shift handover.", "Incident & approvals → Situation report"],
  ["Joint Decision Model (UK JESIP): gather information → assess risk → consider policy → identify options → act and review", "Maps one-to-one onto the workflow graph: validate → assess/correlate → policy check → plan → human review → execute → monitor/reassess.", "Agents & evidence view"],
  ["After-action review (practised by many national emergency agencies)", "Structured AAR captured at closure: expected, happened, went well, improve, follow-ups — stored on the incident and included in the SITREP.", "Incident & approvals → Close incident"],
  ["Stand-down discipline", "Closing an incident stands down any work order still open and records it in the audit chain, so no live tasking survives a closed incident.", "Close incident"],
  ["Common operating picture with explicit data modes", "The mode bar (data / model / connectors / sovereign) is always visible so no screen can be mistaken for live operations.", "Every view"],
];

const PRACTICES_AR: [string, string][] = [
  ["بروتوكول التنبيه الموحد (CAP 1.2)", "مسودات التنبيه تحمل الاستعجال والشدة واليقين ونوع الاستجابة. اليقين مشتق من اكتمال الأدلة لا من احتمال."],
  ["مستويات التحذير العام الثلاثية", "مستوى الرسالة يتبع نطاق الشدة ليتسق النداء للعمل مع الرسالة."],
  ["مصفوفة مخاطر الفيضان (الاحتمال × الأثر)", "ترويسة الحادثة تعرض مصفوفة نطاق الاحتمال × نطاق العواقب مع تمييز الخلية الحالية."],
  ["إحاطة الحادثة / تقرير الموقف", "تقرير موقف بنقرة واحدة من الحالة المحفوظة؛ نسخ كنص لتسليم المناوبة."],
  ["نموذج القرار المشترك", "جمع المعلومات ← تقييم المخاطر ← مراعاة السياسات ← تحديد الخيارات ← التنفيذ والمراجعة — يطابق مخطط سير العمل."],
  ["مراجعة ما بعد الحدث", "مراجعة منظمة عند الإغلاق تُحفظ على الحادثة وتظهر في تقرير الموقف."],
  ["انضباط الإنهاء", "إغلاق الحادثة يوقف أوامر العمل المفتوحة ويسجل ذلك في سلسلة التدقيق."],
  ["صورة تشغيلية مشتركة بأوضاع بيانات صريحة", "شريط الأوضاع ظاهر دائماً حتى لا تُفهم أي شاشة على أنها تشغيل حي."],
];

export default function HowItWorksPage() {
  const { t, locale } = useI18n();
  const [h, setH] = useState<Health | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    api<Health>("/api/health").then(setH).catch(setError);
  }, []);
  const modes = h?.modes ?? {};
  const text = h?.providers.find((p) => p.kind === "text");
  const simulated = h?.integrations.filter((i) => i.status === "synthetic" || i.status === "simulated").length ?? 0;
  const requires = h?.integrations.filter((i) => i.status === "requires_authorized_access").length ?? 0;

  return (
    <div className="space-y-4" data-testid="how-it-works">
      <Section title={t("how_title")} testid="how-hero">
        <p className="max-w-4xl text-sm leading-relaxed text-ink-900">{t("how_lede")}</p>
        <div className="mt-3 flex flex-wrap gap-1">
          <Chip tone="sand">{L(locale, "prototype", "نموذج أولي")}</Chip>
          <Chip tone="sand">{L(locale, "synthetic data", "بيانات اصطناعية")}</Chip>
          <Chip tone="sand">{L(locale, "simulated connectors", "موصلات محاكاة")}</Chip>
          <Chip tone="lagoon">{L(locale, "human-approved response", "استجابة بموافقة بشرية")}</Chip>
        </div>
        <img src="/infographics/agentic-flow.svg" alt={L(locale, "Agentic flow: signals, hazard tools, personas, authority, departments, reassessment", "تدفق الوكلاء")} className="mt-4 w-full rounded-lg border border-ink-100 bg-white" />
      </Section>

      <Section title={t("how_flow")} testid="how-stages">
        <ol className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {STAGES.map(([n, en, ar, body]) => (
            <li key={n} className="rounded-lg border border-ink-100 bg-white p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-lagoon-600 text-xs font-semibold text-white">{n}</span>
                <h3 className="text-sm font-semibold">{L(locale, en, ar)}</h3>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-ink-700">{locale === "ar" ? AR_STAGE_TEXT[n] : body}</p>
            </li>
          ))}
        </ol>
      </Section>

      <Section title={t("how_features")} testid="how-features">
        <ul className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {FEATURES.map(([en, ar, benEn, benAr]) => (
            <li key={en} className="rounded-lg bg-sand-100/60 p-3">
              <div className="text-sm font-semibold">{L(locale, en, ar)}</div>
              <p className="mt-1 text-xs text-ink-700">{L(locale, benEn, benAr)}</p>
            </li>
          ))}
        </ul>
        <img src="/infographics/key-features.svg" alt={L(locale, "Key features infographic", "ملخص الميزات")} className="mt-4 w-full rounded-lg border border-ink-100" />
      </Section>

      <Section title={t("how_practices")} testid="how-practices">
        <p className="mb-2 text-xs text-ink-700/80">
          {L(
            locale,
            "These are publicly documented practices adapted into the prototype's own process. Referencing them does not imply endorsement by, or an integration with, any of the organisations concerned.",
            "هذه ممارسات موثقة علنياً جرى تكييفها في عملية النموذج الأولي. الإشارة إليها لا تعني اعتماداً من أي جهة أو تكاملاً معها.",
          )}
        </p>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-start text-ink-700/70">
              <th className="py-1 text-start">{L(locale, "Practice", "الممارسة")}</th>
              <th className="py-1 text-start">{L(locale, "How RainReady adapts it", "كيف يكيّفها رين ريدي")}</th>
              <th className="py-1 text-start ltr-only">{L(locale, "Where", "أين")}</th>
            </tr>
          </thead>
          <tbody>
            {PRACTICES.map(([p, how, where], i) => (
              <tr key={p} className="border-t border-ink-100/70 align-top">
                <td className="py-1.5 pe-3 font-medium">{locale === "ar" ? PRACTICES_AR[i][0] : p}</td>
                <td className="py-1.5 pe-3">{locale === "ar" ? PRACTICES_AR[i][1] : how}</td>
                <td className="py-1.5 text-ink-700/70">{where}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <img src="/infographics/guardrails.svg" alt={L(locale, "Guardrail layers", "طبقات الحماية")} className="mt-4 w-full rounded-lg border border-ink-100 bg-white" />
      </Section>

      <div className="grid gap-4 md:grid-cols-2">
        <Section title={t("how_status")} testid="how-status">
          <p className="mb-2 text-[11px] text-ink-700/70">{t("how_status_note")}</p>
          <ErrorBox error={error} />
          {h && (
            <ul className="space-y-1 text-xs">
              <li className="flex flex-wrap gap-1">
                <Chip tone="neutral">{t("mode_data")}: {String(modes.data_mode)}</Chip>
                <Chip tone="neutral">{t("mode_model")}: {String(modes.model_provider)}</Chip>
                <Chip tone="neutral">{t("mode_connectors")}: {String(modes.action_connectors)}</Chip>
                <Chip tone={modes.sovereign_mode ? "low" : "sand"}>{t("mode_sovereign")}: {String(modes.sovereign_mode)}</Chip>
                <Chip tone={modes.emergency_stop ? "severe" : "low"}>emergency stop: {String(modes.emergency_stop)}</Chip>
              </li>
              <li>
                {L(locale, "Text provider", "مزود النص")}: <b>{text?.provider}</b> · {text?.model_id} · {L(locale, "exercised", "تم تشغيله")}: <b>{String(text?.exercised)}</b>
              </li>
              <li>
                {L(locale, "Worker alive", "العامل نشط")}: <b>{String(h.worker.alive)}</b> · {L(locale, "queued jobs", "مهام في الانتظار")}: {h.worker.queued_jobs ?? 0}
              </li>
              <li>
                {L(locale, "Integrations", "التكاملات")}: {simulated} {L(locale, "synthetic/simulated", "اصطناعية/محاكاة")} · {requires} {L(locale, "require authorized access", "تتطلب وصولاً مصرحاً")}
              </li>
              <li>
                {L(locale, "Guard gate", "بوابة الحماية")}: {String(h.guard_gate.deterministic_gate)} · {L(locale, "server time (Dubai)", "وقت الخادم (دبي)")}: <span className="ltr-only">{h.time.dubai}</span>
              </li>
            </ul>
          )}
        </Section>
        <Section title={t("how_not_claimed")} testid="how-not-claimed">
          <ul className="list-disc space-y-1 ps-4 text-xs text-ink-700">
            <li>{L(locale, "No lives saved, losses avoided or accuracy percentages — every predictive metric is 'not evaluated' without labelled data.", "لا ادعاء بأرواح أُنقذت أو خسائر تُجنبت أو نسب دقة — كل مقياس تنبؤي «غير مُقيَّم» دون بيانات موسومة.")}</li>
            <li>{L(locale, "No agency endorsement or existing integration; no real valve, power or evacuation control.", "لا اعتماد من أي جهة ولا تكامل قائم؛ لا تحكم فعلي في صمام أو طاقة أو إخلاء.")}</li>
            <li>{L(locale, "Real model inference is implemented but has not been exercised here (hosted credential rejected); the status above is read from the server.", "الاستدلال الحقيقي للنموذج منفذ لكنه لم يُشغَّل هنا؛ الحالة أعلاه مقروءة من الخادم.")}</li>
            <li>{L(locale, "The audit chain is tamper-evident within the database, not tamper-proof.", "سلسلة التدقيق كاشفة للعبث داخل قاعدة البيانات وليست مانعة له.")}</li>
          </ul>
          <Link href="/" className="btn-primary mt-3 inline-block text-xs" data-testid="how-demo-cta">
            {t("how_demo_cta")}
          </Link>
        </Section>
      </div>
    </div>
  );
}
