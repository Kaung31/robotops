import type { Pose2D } from "./types";

export interface CampaignDefinition {
  name: string;
  runtime_mode: "mock" | "sim";
  robot_model: "robotops_base";
  world: string;
  map_id: string;
  profiles: string[];
  repetitions: number;
  waypoints: Pose2D[];
  start: Pose2D & { position_tolerance: number; yaw_tolerance: number };
  timeouts: { response: number; trial: number; cancel: number };
}
export type CampaignState = "draft" | "queued" | "running" | "canceling" | "completed" | "failed" | "canceled" | "interrupted";
export interface PoseValidation {
  schema_version: 1;
  verdict: "POSE_VERIFIED" | "POSE_REJECTED" | "INCONCLUSIVE" | "MISSION_FAILED";
  reasons: string[];
  scope?: string;
  ros_outcome?: string;
  xy_error_m?: number | null;
  yaw_error_rad?: number | null;
  policy?: Record<string, number>;
  nav2_goal_checkers?: Record<string, unknown>;
}
export interface BackendTrial {
  id: string;
  profile: string;
  repetition: number;
  state: "planned" | "starting" | "running" | "succeeded" | "failed" | "canceled" | "interrupted";
  evidence: {
    manifest_path: string;
    experiment_id: string;
    mission_run_id: string | null;
    outcome: string;
    metrics: Record<string, unknown>;
    validation?: PoseValidation | null;
    collision?: ContactValidation | null;
  } | null;
}
export interface BackendCampaign {
  schema_version: 1;
  id: string;
  state: CampaignState;
  cancel_requested: boolean;
  error: string | null;
  termination_confirmed: boolean | null;
  cleanup_confirmed: boolean | null;
  created_at: string;
  updated_at: string;
  definition: CampaignDefinition;
  trials: BackendTrial[];
}
export interface CampaignRuntime {
  worker_active: boolean;
  execution_enabled: boolean;
  supported_modes: ("mock" | "sim")[];
  campaign_id: string | null;
}
export interface CampaignEvent {
  sequence: number;
  campaign_id: string;
  at: string;
  kind: "created" | "canceled" | "started" | "trial_started" | "trial_finished" | "cancel_requested" | "completed" | "failed" | "interrupted" | "reconciled";
}
export interface CampaignIntent { key: string; definition: CampaignDefinition }

export interface ContactValidation {
  schema_version: 1;
  verdict: "NO_CONTACT_OBSERVED" | "CONTACT_DETECTED" | "UNKNOWN";
  reasons: string[];
  contacts?: { body_a: string; body_b: string; first_ns?: number; last_ns?: number }[];
  frame_count?: number;
  monitored_bodies?: string[];
  support_pairs?: string[];
  scope?: string;
  provenance_state?: string;
  artifact?: { path: string; sha256: string };
}
export interface ArtifactCheck {
  reference: string;
  state: "VERIFIED" | "MISSING" | "MISMATCH" | "UNAVAILABLE" | "UNTRUSTED";
  reason: string | null;
  expected_sha256: string | null;
  actual_sha256: string | null;
}
export interface CampaignReport {
  schema_version: 1;
  id: string;
  created_at: string;
  source_sha256: string;
  campaign: BackendCampaign;
  profiles: {
    profile: string; requested: number; attempted: number; ros_successes: number;
    ros_success_rate: number | null;
    duration_seconds: { mean: number | null; samples: number };
    odom_metres: { mean: number | null; samples: number };
    pose_verdicts: Record<string, number>; contact_verdicts: Record<string, number>;
  }[];
  integrity: { trial_id: string; state: "VERIFIED" | "ISSUES" | "UNAVAILABLE";
    reasons: string[]; artifacts: ArtifactCheck[] }[];
  limitations: string[];
}
