"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Locale = "en" | "ar";

const STRINGS = {
  app_name: ["RainReady UAE", "رين ريدي الإمارات"],
  app_sub: ["Sovereign Water & HSE Command — prototype", "قيادة المياه والسلامة السيادية — نموذج أولي"],
  nav_command: ["Command", "القيادة"],
  nav_twin: ["Digital twin", "التوأم الرقمي"],
  nav_agents: ["Agents & evidence", "الوكلاء والأدلة"],
  nav_incidents: ["Incident & approvals", "الحادثة والموافقات"],
  nav_field: ["Field report", "تقرير ميداني"],
  nav_assurance: ["Assurance", "الضمان"],
  nav_how: ["How it works", "كيف يعمل"],
  how_title: ["How RainReady works — executive summary", "كيف يعمل رين ريدي — ملخص تنفيذي"],
  how_lede: [
    "RainReady turns rainfall, satellite, sensor, utility and field evidence into bounded, human-approved response actions. Physics lives in versioned tools, authority in deterministic policy, and the AI personas are confined to coordination.",
    "يحوّل رين ريدي أدلة الأمطار والأقمار الصناعية والمستشعرات والمرافق والميدان إلى إجراءات استجابة محدودة تتطلب موافقة بشرية. الفيزياء في أدوات ذات إصدارات، والصلاحية في سياسات حتمية، والوكلاء الذكيون مقيّدون بالتنسيق فقط.",
  ],
  how_flow: ["The six stages", "المراحل الست"],
  how_features: ["Key features", "الميزات الرئيسية"],
  how_practices: ["Practices adapted from international emergency-management processes", "ممارسات مقتبسة من عمليات إدارة الطوارئ الدولية"],
  how_status: ["Live status of this deployment", "الحالة الحية لهذا النشر"],
  how_status_note: ["Read from the server; nothing on this page is animated or assumed.", "مقروءة من الخادم؛ لا شيء في هذه الصفحة متحرك أو مفترض."],
  how_not_claimed: ["Not claimed", "غير مُدَّعى"],
  how_demo_cta: ["Open the four-minute demo path", "افتح مسار العرض التوضيحي"],
  overview_collapse: ["Hide overview", "إخفاء النظرة العامة"],
  overview_expand: ["Show overview", "إظهار النظرة العامة"],
  flow_title: ["Flow of events — how the agentic system works", "تسلسل الأحداث — كيف يعمل النظام الوكيلي"],
  flow_lanes: ["Lanes", "المسارات"],
  flow_guardrail: ["Guardrail", "الضابط"],
  flow_live_here: ["Selected incident is here", "الحادثة المحددة هنا"],
  flow_marker_note: ["Live marker is derived from the persisted status of the selected incident", "العلامة الحية مشتقة من الحالة المحفوظة للحادثة المحددة"],
  flow_marker_none: ["Select or run an incident below to see where it is in this flow (derived from its persisted status).", "اختر أو شغّل حادثة أدناه لترى موضعها في هذا التسلسل (مشتق من حالتها المحفوظة)."],
  flow_open_view: ["Open view", "افتح الشاشة"],
  sign_in_to_operate: ["Sign in with a demo identity to run scenarios and operate the command view.", "سجّل الدخول بهوية تجريبية لتشغيل السيناريوهات واستخدام شاشة القيادة."],
  risk_matrix: ["Risk matrix (likelihood band × consequence band)", "مصفوفة المخاطر (نطاق الاحتمال × نطاق العواقب)"],
  risk_matrix_note: ["Ordinal bands from versioned tools; the highlighted cell is the current position. No probabilities.", "نطاقات ترتيبية من أدوات ذات إصدارات؛ الخلية المميزة هي الموقع الحالي. لا احتمالات."],
  structured_alert: ["Structured alert (CAP-aligned draft)", "تنبيه منظّم (مسودة متوافقة مع CAP)"],
  sitrep: ["Situation report", "تقرير الموقف"],
  sitrep_generate: ["Generate SITREP", "إنشاء تقرير الموقف"],
  sitrep_copy: ["Copy as text", "نسخ كنص"],
  sitrep_copied: ["Copied", "تم النسخ"],
  aar: ["After-action review (optional, stored at closure)", "مراجعة ما بعد الحدث (اختياري، يُحفظ عند الإغلاق)"],
  aar_expected: ["What was expected", "ما كان متوقعاً"],
  aar_happened: ["What happened", "ما حدث"],
  aar_well: ["What went well", "ما سار جيداً"],
  aar_improve: ["What to improve", "ما يجب تحسينه"],
  aar_followups: ["Follow-ups (one per line)", "متابعات (واحدة في كل سطر)"],
  op_period: ["Operational period", "الفترة التشغيلية"],
  elapsed: ["elapsed", "منقضٍ"],
  mode_data: ["Data", "البيانات"],
  mode_model: ["Model", "النموذج"],
  mode_connectors: ["Connectors", "الموصلات"],
  mode_sovereign: ["Sovereign mode", "الوضع السيادي"],
  emergency_stop: ["EMERGENCY STOP ACTIVE — privileged actions blocked; monitoring continues", "إيقاف الطوارئ مفعّل — الإجراءات المميزة محظورة؛ المراقبة مستمرة"],
  identity: ["Signed in as", "تم تسجيل الدخول باسم"],
  switch_identity: ["Demo identity", "هوية تجريبية"],
  not_signed_in: ["Not signed in", "لم يتم تسجيل الدخول"],
  architecture: ["Architecture", "البنية"],
  disclaimer: ["Prototype. Synthetic data, simulated connectors. Not an official government system and does not imply endorsement or an existing integration.", "نموذج أولي. بيانات اصطناعية وموصلات محاكاة. ليس نظاماً حكومياً رسمياً ولا يعني أي اعتماد أو تكامل قائم."],
  scenarios: ["Scenarios", "السيناريوهات"],
  run_scenario: ["Run scenario", "تشغيل السيناريو"],
  running: ["Running…", "جارٍ التشغيل…"],
  incidents: ["Incidents", "الحوادث"],
  no_incidents: ["No incidents yet. Run a scenario to start the workflow.", "لا توجد حوادث بعد. شغّل سيناريو لبدء سير العمل."],
  label: ["Label", "التصنيف"],
  status: ["Status", "الحالة"],
  severity: ["Hazard band", "نطاق الخطر"],
  consequence: ["Consequence", "العواقب"],
  evidence_quality: ["Evidence", "الأدلة"],
  probability: ["Probability", "الاحتمال"],
  next_decision: ["Next decision", "القرار التالي"],
  decision_time: ["Decision time", "وقت القرار"],
  map_attribution: ["Synthetic local basemap — no external tiles", "خريطة أساس محلية اصطناعية — بدون بلاطات خارجية"],
  uae_overview: ["UAE overview (schematic)", "نظرة عامة على الإمارات (تخطيطية)"],
  demo_area: ["Demo Sector 7 (synthetic)", "القطاع التجريبي 7 (اصطناعي)"],
  layers: ["Layers", "الطبقات"],
  twin_title: ["Live scenario twin — water balance (scenario model — uncalibrated)", "التوأم الحي للسيناريو — الموازنة المائية (نموذج سيناريو — غير معاير)"],
  rain_multiplier: ["Rain intensity ×", "شدة المطر ×"],
  drain_blockage: ["Drain blockage", "انسداد الصرف"],
  pump_availability: ["Pump availability", "جاهزية المضخات"],
  extra_pump: ["Deployed mobile pump (m³/s)", "مضخة متنقلة منشورة (م³/ث)"],
  simulate: ["Recompute via backend tool", "إعادة الحساب عبر أداة الخادم"],
  baseline: ["Baseline", "الأساس"],
  intervention: ["Intervention", "التدخل"],
  peak_depth: ["Peak synthetic depth", "أقصى عمق اصطناعي"],
  mechanism: ["Mechanism", "الآلية"],
  horizon_note: ["+30/+60/+180 min are simulation horizons, not claimed warning lead times.", "+30/+60/+180 دقيقة هي آفاق محاكاة وليست أوقات إنذار مدّعاة."],
  ack_note: ["Acknowledgement alone never changes the physical state — only a recorded completion does.", "الإقرار وحده لا يغيّر الحالة الفيزيائية — فقط الإنجاز المسجّل يفعل ذلك."],
  personas: ["Personas", "الشخصيات"],
  tool_calls: ["Tool calls", "استدعاءات الأدوات"],
  evidence: ["Evidence", "الأدلة"],
  agent_runs: ["Agent runs", "تشغيلات الوكلاء"],
  skipped: ["skipped (not relevant)", "تم التخطي (غير ذي صلة)"],
  proposals: ["Proposals", "المقترحات"],
  approve: ["Approve", "موافقة"],
  reject: ["Reject", "رفض"],
  revise: ["Revise (invalidates prior approvals)", "تعديل (يُلغي الموافقات السابقة)"],
  work_orders: ["Work orders (simulated connectors)", "أوامر العمل (موصلات محاكاة)"],
  acknowledge: ["Acknowledge", "إقرار"],
  start: ["Start", "بدء"],
  complete: ["Complete", "إنجاز"],
  reassess: ["Reassess", "إعادة تقييم"],
  close_incident: ["Confirm closure", "تأكيد الإغلاق"],
  cancel_incident: ["Cancel incident", "إلغاء الحادثة"],
  assistant: ["Incident assistant (bounded, cited)", "مساعد الحادثة (محدود ومُستشهَد)"],
  ask: ["Ask", "اسأل"],
  field_title: ["Field report", "تقرير ميداني"],
  description: ["Description", "الوصف"],
  photo: ["Photo (JPEG/PNG ≤ 8 MB, metadata stripped)", "صورة (JPEG/PNG ≤ 8 ميغابايت، تُحذف البيانات الوصفية)"],
  location: ["Location", "الموقع"],
  capture_time: ["Capture time", "وقت الالتقاط"],
  submit: ["Submit report", "إرسال التقرير"],
  my_reports: ["Recent reports", "التقارير الأخيرة"],
  review: ["Review", "مراجعة"],
  accept: ["Accept", "قبول"],
  isolated: ["Instruction-like text isolated (not executed)", "تم عزل نص يشبه التعليمات (لم يُنفذ)"],
  providers: ["Providers", "المزودون"],
  audit: ["Audit chain (hash-linked, append-only)", "سلسلة التدقيق (مرتبطة بالتجزئة، إلحاق فقط)"],
  verify_chain: ["Verify chain", "تحقق من السلسلة"],
  policy_decisions: ["Policy decisions", "قرارات السياسة"],
  model_versions: ["Tool & model versions", "إصدارات الأدوات والنماذج"],
  guard_status: ["Guard status", "حالة الحارس"],
  worker: ["Worker", "العامل"],
  exercised: ["exercised", "تم اختباره"],
  not_exercised: ["not exercised", "لم يُختبر"],
  sign_in_hint: ["Choose a demo identity to begin (demo mode only; server assigns the role).", "اختر هوية تجريبية للبدء (الوضع التجريبي فقط؛ الخادم يحدد الدور)."],
  error: ["Error", "خطأ"],
  refresh: ["Refresh", "تحديث"],
  version: ["version", "الإصدار"],
  actions: ["actions", "إجراءات"],
  authority: ["authority", "الصلاحية"],
  expires: ["expires", "ينتهي"],
  payload_hash: ["payload hash", "تجزئة الحمولة"],
  public_text: ["Public advisory text (pending approval)", "نص الإرشاد العام (بانتظار الموافقة)"],
  no_data: ["No usable observation ≠ no hazard", "لا توجد ملاحظة صالحة ≠ لا يوجد خطر"],
  arabic: ["العربية", "English"],
  compare_note: ["Baseline vs intervention — only completed deployments change the modelled state.", "الأساس مقابل التدخل — فقط عمليات النشر المكتملة تغيّر الحالة النموذجية."],
  reset_demo: ["Reset demo data", "إعادة ضبط البيانات التجريبية"],
  select_incident: ["Select an incident", "اختر حادثة"],
  sensor_outage: ["Sensor outage", "انقطاع المستشعر"],
  report_reliability: ["Report reliability", "موثوقية التقارير"],
} satisfies Record<string, [string, string]>;

export type StringKey = keyof typeof STRINGS;

const Ctx = createContext<{ locale: Locale; setLocale: (l: Locale) => void; t: (k: StringKey) => string; dir: "ltr" | "rtl" }>({
  locale: "en",
  setLocale: () => {},
  t: (k) => STRINGS[k][0],
  dir: "ltr",
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("en");
  useEffect(() => {
    const saved = typeof window !== "undefined" ? (window.localStorage.getItem("rr.locale") as Locale | null) : null;
    if (saved === "ar" || saved === "en") setLocaleState(saved);
  }, []);
  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    if (typeof window !== "undefined") window.localStorage.setItem("rr.locale", l);
  }, []);
  const dir = locale === "ar" ? "rtl" : "ltr";
  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = dir;
  }, [locale, dir]);
  const value = useMemo(() => ({ locale, setLocale, dir: dir as "ltr" | "rtl", t: (k: StringKey) => STRINGS[k][locale === "ar" ? 1 : 0] }), [locale, setLocale, dir]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n() {
  return useContext(Ctx);
}

/** Pick a localised field from API data (e.g. title / title_ar). */
export function pick(locale: Locale, obj: Record<string, unknown> | null | undefined, key: string): string {
  if (!obj) return "";
  const ar = obj[`${key}_ar`];
  if (locale === "ar" && typeof ar === "string" && ar) return ar;
  const v = obj[key];
  return typeof v === "string" ? v : "";
}

export const BAND_LABELS: Record<string, [string, string]> = {
  low: ["Low", "منخفض"],
  moderate: ["Moderate", "متوسط"],
  high: ["High", "مرتفع"],
  severe: ["Severe", "شديد"],
  unknown: ["Unknown", "غير معروف"],
};

export const LABEL_LABELS: Record<string, [string, string]> = {
  observed_water: ["Observed water", "مياه مرصودة"],
  susceptibility: ["Susceptibility", "قابلية التأثر"],
  forecast_risk: ["Forecast risk", "خطر متوقع"],
  anomaly: ["Anomaly", "شذوذ"],
  suspected_incident: ["Suspected incident", "حادثة مشتبه بها"],
  confirmed_incident: ["Confirmed incident", "حادثة مؤكدة"],
};

export const STATUS_LABELS: Record<string, [string, string]> = {
  open: ["Open", "مفتوحة"],
  assessing: ["Assessing", "قيد التقييم"],
  awaiting_evidence: ["Awaiting evidence", "بانتظار الأدلة"],
  urgent_human_review: ["Urgent human review", "مراجعة بشرية عاجلة"],
  planning: ["Planning", "التخطيط"],
  awaiting_approval: ["Awaiting approval", "بانتظار الموافقة"],
  responding: ["Responding", "جارٍ الاستجابة"],
  monitoring: ["Monitoring", "المراقبة"],
  closure_pending: ["Closure pending", "بانتظار الإغلاق"],
  closed: ["Closed", "مغلقة"],
  cancelled: ["Cancelled", "ملغاة"],
};

export function tl(locale: Locale, table: Record<string, [string, string]>, key: string | null | undefined): string {
  if (!key) return "—";
  const row = table[key];
  return row ? row[locale === "ar" ? 1 : 0] : key;
}
