"use client";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { pick, useI18n } from "@/lib/i18n";
import { useLive, useSession } from "@/lib/session";
import type { Incident, IncidentDetail } from "@/lib/types";
import { BandChip, StatusChip } from "./ui";

/** Loads the incident list + selected detail, refreshing on live events. */
export function useIncidentDetail() {
  const { identity } = useSession();
  const [list, setList] = useState<Incident[]>([]);
  const [id, setId] = useState<string | null>(null);
  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [includeClosed, setIncludeClosed] = useState(false);

  const loadList = useCallback(async () => {
    if (!identity) return;
    try {
      const l = await api<Incident[]>(`/api/incidents?include_closed=${includeClosed}`);
      setList(l);
      setId((cur) => (cur && l.some((i) => i.id === cur) ? cur : l[0]?.id ?? cur));
    } catch (e) {
      setError(e);
    }
  }, [identity, includeClosed]);

  const loadDetail = useCallback(async () => {
    if (!identity || !id) return;
    try {
      setDetail(await api<IncidentDetail>(`/api/incidents/${id}`));
      setError(null);
    } catch (e) {
      setError(e);
    }
  }, [identity, id]);

  const topics = ["incident", "agent_run", "tool_call", "proposal", "approval", "execution_blocked", "dispatch", "work_order", "escalation", "field_report", "security", "system"];
  useLive(loadList, topics, [identity?.id, includeClosed]);
  useLive(loadDetail, topics, [identity?.id, id]);

  return { list, id, setId, detail, error, reload: loadDetail, includeClosed, setIncludeClosed };
}

function PickerInner({ list, id, setId, includeClosed, setIncludeClosed }: { list: Incident[]; id: string | null; setId: (s: string) => void; includeClosed: boolean; setIncludeClosed: (b: boolean) => void }) {
  const { t, locale } = useI18n();
  const params = useSearchParams();
  useEffect(() => {
    const q = params.get("id");
    if (q) setId(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);
  return (
    <div className="card flex flex-wrap items-center gap-2 p-2" data-testid="incident-picker">
      <label className="label">{t("select_incident")}</label>
      <select className="min-w-[260px] flex-1 rounded-lg border border-ink-100 p-1.5 text-sm" value={id ?? ""} onChange={(e) => setId(e.target.value)} data-testid="incident-select">
        {list.length === 0 && <option value="">—</option>}
        {list.map((i) => (
          <option key={i.id} value={i.id}>
            {pick(locale, i, "title")} · {i.status} · v{i.version}
          </option>
        ))}
      </select>
      {id && list.find((i) => i.id === id) && (
        <>
          <BandChip band={list.find((i) => i.id === id)!.severity_band} />
          <StatusChip status={list.find((i) => i.id === id)!.status} />
        </>
      )}
      <label className="ms-auto flex items-center gap-1 text-xs">
        <input type="checkbox" checked={includeClosed} onChange={(e) => setIncludeClosed(e.target.checked)} /> include closed
      </label>
    </div>
  );
}

export function IncidentPicker(props: Parameters<typeof PickerInner>[0]) {
  return (
    <Suspense fallback={null}>
      <PickerInner {...props} />
    </Suspense>
  );
}
