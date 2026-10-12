import { useCallback, useEffect, useRef, useState } from "react";
import { campaignClient, CampaignRequestError, submitCampaignIntent } from "./campaignClient";
import type { BackendCampaign, CampaignDefinition, CampaignEvent, CampaignIntent, CampaignRuntime } from "./campaignTypes";
import { createRefreshGate } from "./refreshGate";

const INTENT_KEY = "robotops.campaignRequest.v1";
function loadIntent(): CampaignIntent | null {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(INTENT_KEY) ?? "null");
    if (value && typeof value === "object" && "key" in value && typeof value.key === "string"
      && "definition" in value && value.definition && typeof value.definition === "object") return value as CampaignIntent;
  } catch { /* No request to retry. Backend ownership is discovered independently. */ }
  return null;
}
function persistIntent(intent: CampaignIntent | null) {
  // Only retry intent lives here, never campaign execution state or evidence.
  if (intent) window.localStorage.setItem(INTENT_KEY, JSON.stringify(intent));
  else window.localStorage.removeItem(INTENT_KEY);
}

export function useCampaigns() {
  const [runtime, setRuntime] = useState<CampaignRuntime | null>(null);
  const [current, setCurrent] = useState<BackendCampaign | null>(null);
  const [history, setHistory] = useState<BackendCampaign[]>([]);
  const [events, setEvents] = useState<CampaignEvent[]>([]);
  const [pending, setPending] = useState<CampaignIntent | null>(loadIntent);
  const [busy, setBusy] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [fresh, setFresh] = useState(false);
  const gate = useRef(createRefreshGate());
  const selected = useRef<string | null>(null);
  const cursor = useRef({ id: "", sequence: 0 });
  const pageRef = useRef(0);
  const busyRef = useRef(false);
  const intentRef = useRef(pending);
  const mounted = useRef(false);

  const refresh = useCallback(() => gate.current.run(async isCurrent => {
    try {
      const [ownership, records] = await Promise.all([campaignClient.runtime(), campaignClient.history(pageRef.current * 20)]);
      const id = ownership.campaign_id ?? selected.current ?? records[0]?.id;
      const record = id ? await campaignClient.get(id) : null;
      const after = id === cursor.current.id ? cursor.current.sequence : 0;
      const changes = id ? await campaignClient.events(id, after) : [];
      if (!isCurrent() || !mounted.current) return;
      setRuntime(ownership);
      setHistory(records);
      setCurrent(record);
      const sameCampaign = cursor.current.id === id;
      setEvents(previous => [...(sameCampaign ? previous : []), ...changes].slice(-100));
      cursor.current = { id: id ?? "", sequence: changes.at(-1)?.sequence ?? after };
      setPollError(null);
      setFresh(true);
    } catch (error) {
      if (!isCurrent() || !mounted.current) return;
      setPollError(error instanceof Error ? error.message : "Campaign status unavailable");
      setFresh(false); // Retain last known state; never infer completion from transport loss.
    }
  }), []);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1500);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
      gate.current.invalidate(); // Observation cleanup must never cancel a campaign.
    };
  }, [refresh]);

  async function action(work: () => Promise<BackendCampaign>) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setActionError(null);
    const resume = gate.current.suspend();
    try {
      const record = await work();
      selected.current = record.id;
      if (mounted.current) setCurrent(record);
    } catch (error) {
      if (mounted.current) setActionError(error instanceof Error ? error.message : "Campaign request failed");
    } finally {
      resume();
      busyRef.current = false;
      if (mounted.current) { setBusy(false); void refresh(); }
    }
  }
  function updateIntent(intent: CampaignIntent | null) {
    persistIntent(intent); // A failed write stops creation before a non-retryable request is sent.
    intentRef.current = intent;
    if (mounted.current) setPending(intent);
  }
  async function submit(definition?: CampaignDefinition) {
    await action(async () => {
      const intent = intentRef.current ?? (definition ? { key: crypto.randomUUID(), definition } : null);
      if (!intent) throw new Error("No pending campaign request");
      updateIntent(intent);
      try {
        const record = await submitCampaignIntent(intent);
        updateIntent(null);
        return record;
      } catch (error) {
        // A rejected definition/start validation cannot have dispatched a mission.
        if (error instanceof CampaignRequestError && error.status === 422) updateIntent(null);
        throw error;
      }
    });
  }
  function select(id: string) {
    if (busyRef.current) return;
    selected.current = id;
    gate.current.invalidate();
    void refresh();
  }
  function changePage(value: number) {
    if (busyRef.current) return;
    pageRef.current = Math.max(0, value);
    setPage(pageRef.current);
    gate.current.invalidate();
    void refresh();
  }
  return {
    runtime, current, history, events, pending, busy, fresh, page, pollError, actionError,
    submit, select, changePage,
    startDraft: (id: string) => action(() => campaignClient.start(id)),
    cancel: (id: string) => action(() => campaignClient.cancel(id)),
    reconcile: (id: string) => action(() => campaignClient.reconcile(id)),
    cancelPending: () => action(async () => {
      if (!intentRef.current) throw new Error("No pending campaign request");
      const record = await campaignClient.create(intentRef.current);
      const saved = ["draft", "queued", "running", "canceling"].includes(record.state)
        ? await campaignClient.cancel(record.id) : record;
      updateIntent(null);
      return saved;
    }),
  };
}
