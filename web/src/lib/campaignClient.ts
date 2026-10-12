import type { BackendCampaign, BackendTrial, CampaignDefinition, CampaignEvent, CampaignIntent, CampaignRuntime, CampaignReport } from "./campaignTypes";

export class CampaignRequestError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1/campaigns${path}`, { ...init, signal: AbortSignal.timeout(10000) });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail = body && typeof body === "object" && "detail" in body ? body.detail : null;
    throw new CampaignRequestError(typeof detail === "string" ? detail : `Campaign request failed (${response.status})`, response.status);
  }
  return response.json() as Promise<T>;
}
export const campaignClient = {
  runtime: () => request<CampaignRuntime>("/runtime"),
  history: (offset = 0) => request<BackendCampaign[]>(`?limit=20&offset=${offset}`),
  get: (id: string) => request<BackendCampaign>(`/${encodeURIComponent(id)}`),
  events: (id: string, after = 0) => request<CampaignEvent[]>(`/${encodeURIComponent(id)}/events?after=${after}`),
  create: (intent: CampaignIntent) => request<BackendCampaign>("", {
    method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": intent.key },
    body: JSON.stringify(intent.definition),
  }),
  start: (id: string) => request<BackendCampaign>(`/${encodeURIComponent(id)}/start`, { method: "POST" }),
  cancel: (id: string) => request<BackendCampaign>(`/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  reconcile: (id: string) => request<BackendCampaign>(`/${encodeURIComponent(id)}/reconcile`, { method: "POST" }),
  reports: (id: string) => request<CampaignReport[]>(`/${encodeURIComponent(id)}/reports`),
  generateReport: (id: string) => request<CampaignReport>(`/${encodeURIComponent(id)}/reports`, { method: "POST" }),
};

export function reportDownloadUrl(campaignId: string, reportId: string, format: "json" | "html"): string {
  return `/api/v1/campaigns/${encodeURIComponent(campaignId)}/reports/${encodeURIComponent(reportId)}/download?format=${format}`;
}

/** Explicit retry only: creation is idempotent; a finalized record is never restarted. */
export async function submitCampaignIntent(intent: CampaignIntent): Promise<BackendCampaign> {
  const record = await campaignClient.create(intent);
  return record.state === "draft" ? campaignClient.start(record.id) : record;
}
export function isCampaignActive(record: BackendCampaign): boolean {
  return ["queued", "running", "canceling"].includes(record.state);
}
export function measured(trial: BackendTrial, key: string): number | null {
  const value = trial.evidence?.metrics[key];
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}
export function summarizeCampaign(record: BackendCampaign) {
  return record.definition.profiles.map(profile => {
    const trials = record.trials.filter(t => t.profile === profile);
    const attempted = trials.filter(t => t.evidence !== null || ["succeeded", "failed", "interrupted"].includes(t.state));
    const successes = attempted.filter(t => t.state === "succeeded" && t.evidence?.outcome === "succeeded");
    const mean = (key: string) => {
      const values = successes.map(t => measured(t, key)).filter((v): v is number => v !== null);
      return { value: values.length ? values.reduce((a, b) => a + b, 0) / values.length : null, samples: values.length };
    };
    return { profile, requested: trials.length, attempted: attempted.length, successes: successes.length,
      successRate: attempted.length ? 100 * successes.length / attempted.length : null,
      time: mean("mission_ros_seconds"), distance: mean("odom_path_metres") };
  });
}
export function campaignDefinition(
  config: Omit<CampaignDefinition, "waypoints">, route: CampaignDefinition["waypoints"], returnToStart: boolean,
): CampaignDefinition {
  const waypoints = route.map(p => ({ ...p }));
  if (returnToStart) {
    const { x, y, yaw } = config.start;
    const last = waypoints.at(-1);
    if (!last || last.x !== x || last.y !== y || last.yaw !== yaw) waypoints.push({ x, y, yaw });
  }
  return { ...config, waypoints };
}
