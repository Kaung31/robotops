import type { Pose2D } from "./types";

export type MissionOutcome = "succeeded" | "failed" | "canceled" | "cancellation_unconfirmed" | "result_unavailable";

export interface MissionRunRecord {
  id: string;
  requestId: string;
  runId: string | null;
  label: string;
  startedAt: string;
  endedAt: string;
  outcome: MissionOutcome;
  durationS: number;
  distanceM: number;
  waypointCount: number;
  waypoints: Pose2D[];
  navigationProfile: string;
  mapId: string;
}

const KEY = "robotops.missionRuns.v1";
const MAX_RECORDS = 250;
const OUTCOMES = new Set<MissionOutcome>(["succeeded", "failed", "canceled", "cancellation_unconfirmed", "result_unavailable"]);

function isPose(value: unknown): value is Pose2D {
  if (!value || typeof value !== "object") return false;
  const pose = value as Partial<Pose2D>;
  return Number.isFinite(pose.x) && Number.isFinite(pose.y) && Number.isFinite(pose.yaw);
}

export function isMissionRunRecord(value: unknown): value is MissionRunRecord {
  if (!value || typeof value !== "object") return false;
  const run = value as Partial<MissionRunRecord>;
  return typeof run.id === "string"
    && typeof run.requestId === "string"
    && (run.runId === null || typeof run.runId === "string")
    && typeof run.label === "string"
    && typeof run.startedAt === "string"
    && typeof run.endedAt === "string"
    && typeof run.outcome === "string" && OUTCOMES.has(run.outcome as MissionOutcome)
    && Number.isFinite(run.durationS)
    && Number.isFinite(run.distanceM)
    && Number.isInteger(run.waypointCount)
    && Array.isArray(run.waypoints) && run.waypoints.every(isPose)
    && typeof run.navigationProfile === "string"
    && typeof run.mapId === "string";
}

export function loadMissionRuns(): MissionRunRecord[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isMissionRunRecord).slice(0, MAX_RECORDS);
  } catch {
    return [];
  }
}

export function saveMissionRun(record: MissionRunRecord): MissionRunRecord[] {
  const next = [record, ...loadMissionRuns().filter((item) => item.id !== record.id)].slice(0, MAX_RECORDS);
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Storage is a convenience layer only; mission controls must continue working.
  }
  window.dispatchEvent(new CustomEvent("robotops-runs-changed"));
  return next;
}

export function mergeMissionRuns(value: unknown): MissionRunRecord[] {
  if (!Array.isArray(value)) throw new Error("Benchmark import must be a JSON array.");
  const imported = value.filter(isMissionRunRecord);
  if (!imported.length && value.length) throw new Error("No valid RobotOps mission runs were found in this file.");
  const byId = new Map<string, MissionRunRecord>();
  for (const run of [...imported, ...loadMissionRuns()]) {
    if (!byId.has(run.id)) byId.set(run.id, run);
  }
  const next = [...byId.values()]
    .sort((a, b) => Date.parse(b.startedAt) - Date.parse(a.startedAt))
    .slice(0, MAX_RECORDS);
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Import should not break the UI if storage is unavailable.
  }
  window.dispatchEvent(new CustomEvent("robotops-runs-changed"));
  return next;
}

export function clearMissionRuns(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Ignore storage failures and keep the UI usable.
  }
  window.dispatchEvent(new CustomEvent("robotops-runs-changed"));
}
