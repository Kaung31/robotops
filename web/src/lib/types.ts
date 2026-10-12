export type RuntimeMode = "mock" | "sim" | "replay" | "real" | "unknown";
export type ConnectionState = "connected" | "stale" | "disconnected";

export interface Pose2D { x: number; y: number; yaw: number }
export interface ScanPoint { x: number; y: number }
export interface MapSnapshot {
  frame_id: string;
  width: number;
  height: number;
  resolution: number;
  origin: Pose2D;
  data: number[];
}
export interface RobotSnapshot {
  robot_id: string;
  runtime_mode: RuntimeMode;
  connection: ConnectionState;
  source_timestamp_ns: string | null;
  received_monotonic_ns: string | null;
  pose: Pose2D | null;
  map: MapSnapshot | null;
  scan: ScanPoint[];
  global_path: Pose2D[];
  local_path: Pose2D[];
  mission_state: string | null;
  mission_run_id: string | null;
}

export type StackMode = "mapping" | "navigation";
export type StackState = "stopped" | "starting" | "running" | "stopping" | "failed";

export interface WorldOption {
  id: string;
  label: string;
  difficulty: string;
}

export interface NavigationProfile {
  id: string;
  label: string;
  planner: string;
  controller: string;
}

export interface MapArtifact {
  id: string;
  label: string;
  yaml_path: string;
  world_id: string | null;
  created_at_ns: string | null;
  resolution: number | null;
  width: number | null;
  height: number | null;
  preview_url: string | null;
  is_latest: boolean;
}

export interface ControlOptions {
  worlds: WorldOption[];
  navigation_profiles: NavigationProfile[];
  maps: MapArtifact[];
}

export interface StackRequest {
  mode: StackMode;
  runtime_mode: "sim";
  world: string;
  map_id?: string | null;
  navigation_profile?: string | null;
  headless_rendering: boolean;
  open_rviz?: boolean;
}

export interface StackStatus {
  state: StackState;
  mode: StackMode | null;
  runtime_mode: RuntimeMode;
  world: string | null;
  map_id: string | null;
  navigation_profile: string | null;
  processes: string[];
  started_at_ns: string | null;
  stopped_at_ns: string | null;
  error: string | null;
  rviz_running: boolean;
  rviz_error: string | null;
}

export interface LifecycleNodeStatus {
  name: string;
  state: string;
}

export interface NavigationReadiness {
  ready: boolean;
  phase: string;
  message: string;
  odom_available: boolean;
  scan_available: boolean;
  odom_to_base: boolean;
  map_available: boolean;
  localized: boolean;
  map_to_base: boolean;
  lifecycle_nodes: LifecycleNodeStatus[];
  updated_at_ns: string | null;
}
