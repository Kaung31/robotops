import type { MissionOutcome } from "./runHistory";
import type { Pose2D } from "./types";

export interface CampaignTrialRecord {
  id: string;
  profile: string;
  repetition: number;
  outcome: MissionOutcome;
  durationS: number;
  distanceM: number;
  startedAt: string;
  endedAt: string;
  requestId: string | null;
  missionRunId: string | null;
  error: string | null;
}

export interface CampaignRecord {
  id: string;
  name: string;
  createdAt: string;
  completedAt: string | null;
  world: string;
  mapId: string;
  profiles: string[];
  repetitions: number;
  timeoutS: number;
  returnToStart: boolean;
  route: Pose2D[];
  state: "running" | "completed" | "canceled" | "failed";
  trials: CampaignTrialRecord[];
}

const KEY = "robotops.benchmarkCampaigns.v1";
const MAX_CAMPAIGNS = 30;

function validTrial(value: unknown): value is CampaignTrialRecord {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<CampaignTrialRecord>;
  return typeof item.id === "string"
    && typeof item.profile === "string"
    && Number.isInteger(item.repetition)
    && typeof item.outcome === "string"
    && Number.isFinite(item.durationS)
    && Number.isFinite(item.distanceM)
    && typeof item.startedAt === "string"
    && typeof item.endedAt === "string";
}

function validCampaign(value: unknown): value is CampaignRecord {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<CampaignRecord>;
  return typeof item.id === "string"
    && typeof item.name === "string"
    && typeof item.createdAt === "string"
    && typeof item.world === "string"
    && typeof item.mapId === "string"
    && Array.isArray(item.profiles) && item.profiles.every((profile) => typeof profile === "string")
    && Number.isInteger(item.repetitions)
    && Number.isFinite(item.timeoutS)
    && typeof item.returnToStart === "boolean"
    && Array.isArray(item.route)
    && Array.isArray(item.trials) && item.trials.every(validTrial)
    && ["running", "completed", "canceled", "failed"].includes(item.state ?? "");
}

export function loadCampaigns(): CampaignRecord[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(validCampaign).slice(0, MAX_CAMPAIGNS);
  } catch {
    return [];
  }
}

