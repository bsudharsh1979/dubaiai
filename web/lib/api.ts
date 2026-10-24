// Thin typed fetch wrapper. Credentials are included so the server-side signed
// identity cookie travels with every request; the client never sends a role.
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown; idempotencyKey?: string } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string> | undefined) };
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  if (init.idempotencyKey) headers["Idempotency-Key"] = init.idempotencyKey;
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers, body, credentials: "include" });
  const text = await res.text();
  let data: unknown = text;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const detail = (data && typeof data === "object" && "detail" in (data as Record<string, unknown>)) ? (data as { detail: unknown }).detail : data;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export function newIdempotencyKey(prefix: string): string {
  const rnd = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : Math.random().toString(36).slice(2);
  return `${prefix}-${rnd}`;
}

/** Subscribe to the server event stream. Returns an unsubscribe function. */
export function subscribeEvents(onEvent: (topic: string, data: Record<string, unknown>) => void): () => void {
  if (typeof window === "undefined") return () => {};
  const es = new EventSource(`${API_BASE}/api/events`, { withCredentials: true });
  const handler = (topic: string) => (e: MessageEvent) => {
    try {
      onEvent(topic, JSON.parse(e.data));
    } catch {
      onEvent(topic, { raw: e.data });
    }
  };
  for (const topic of ["incident", "agent_run", "tool_call", "proposal", "approval", "execution_blocked", "dispatch", "work_order", "escalation", "field_report", "security", "import", "twin", "system"]) {
    es.addEventListener(topic, handler(topic) as EventListener);
  }
  return () => es.close();
}

export function dubai(ts: string | null | undefined, locale: "en" | "ar" = "en"): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return new Intl.DateTimeFormat(locale === "ar" ? "ar-AE" : "en-GB", {
    timeZone: "Asia/Dubai",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d) + " GST";
}
