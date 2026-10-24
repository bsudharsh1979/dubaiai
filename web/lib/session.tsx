"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError, subscribeEvents } from "./api";

export type Identity = {
  id: string;
  name: string;
  role: string;
  role_label: string;
  organisation: string;
  jurisdictions: string[];
  permissions: string[];
  approval_authority: string[];
};

export type Modes = {
  data_mode: string;
  model_provider: string;
  action_connectors: string;
  sovereign_mode: boolean;
  demo_identity_switcher: boolean;
  emergency_stop: boolean;
  app_env: string;
};

export type AppConfig = {
  app_name: string;
  modes: Modes;
  approval_ttl_minutes: number;
  ack_escalation_minutes: number;
  max_evidence_loops: number;
  labels: string[];
  architecture: string[];
};

export type LiveEvent = { seq: number; topic: string; data: Record<string, unknown>; at: number };

type SessionValue = {
  identity: Identity | null;
  identities: { id: string; name: string; role: string; role_label: string; organisation: string }[];
  config: AppConfig | null;
  loading: boolean;
  events: LiveEvent[];
  eventSeq: number;
  login: (userId: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  can: (perm: string) => boolean;
};

const Ctx = createContext<SessionValue>({
  identity: null,
  identities: [],
  config: null,
  loading: true,
  events: [],
  eventSeq: 0,
  login: async () => {},
  logout: async () => {},
  refresh: async () => {},
  can: () => false,
});

export function SessionProvider({ children }: { children: ReactNode }) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [identities, setIdentities] = useState<SessionValue["identities"]>([]);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [eventSeq, setEventSeq] = useState(0);
  const seqRef = useRef(0);

  const refresh = useCallback(async () => {
    try {
      const [cfg, ids] = await Promise.all([api<AppConfig>("/api/config"), api<{ identities: SessionValue["identities"] }>("/api/auth/identities")]);
      setConfig(cfg);
      setIdentities(ids.identities);
    } catch {
      /* API unreachable; UI shows offline state */
    }
    try {
      setIdentity(await api<Identity>("/api/auth/me"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setIdentity(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const unsub = subscribeEvents((topic, data) => {
      seqRef.current += 1;
      const ev = { seq: seqRef.current, topic, data, at: Date.now() };
      setEvents((prev) => [ev, ...prev].slice(0, 150));
      setEventSeq(seqRef.current);
      if (topic === "system") void refresh();
    });
    return unsub;
  }, [refresh]);

  const login = useCallback(
    async (userId: string) => {
      await api("/api/auth/demo-login", { method: "POST", json: { user_id: userId } });
      await refresh();
    },
    [refresh],
  );
  const logout = useCallback(async () => {
    await api("/api/auth/logout", { method: "POST" });
    setIdentity(null);
  }, []);

  const value = useMemo<SessionValue>(
    () => ({ identity, identities, config, loading, events, eventSeq, login, logout, refresh, can: (p) => !!identity?.permissions.includes(p) }),
    [identity, identities, config, loading, events, eventSeq, login, logout, refresh],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession() {
  return useContext(Ctx);
}

/** Re-run `fn` whenever the live event stream emits matching topics (debounced). */
export function useLive(fn: () => void | Promise<void>, topics: string[], deps: unknown[] = []) {
  const { events, eventSeq } = useSession();
  const last = useRef(0);
  useEffect(() => {
    void fn();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    if (eventSeq === last.current) return;
    const fresh = events.filter((e) => e.seq > last.current && topics.includes(e.topic));
    last.current = eventSeq;
    if (fresh.length) {
      const h = setTimeout(() => void fn(), 150);
      return () => clearTimeout(h);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventSeq]);
}
