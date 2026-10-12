import type { ControlOptions, MapArtifact, NavigationReadiness, Pose2D, RobotSnapshot, StackRequest, StackStatus } from "./types";

async function errorText(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail ?? `Request failed: ${response.status}`;
  } catch {
    return (await response.text()) || `Request failed: ${response.status}`;
  }
}

export async function getRobot(): Promise<RobotSnapshot> {
  const response = await fetch("/api/v1/robot");
  if (!response.ok) throw new Error(await errorText(response));
  return response.json() as Promise<RobotSnapshot>;
}

export async function submitMissionWaypoints(waypoints: Pose2D[], label = "web-mission") {
  const response = await fetch("/api/v1/missions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label, waypoints, record: true }),
  });
  if (!response.ok) throw new Error(await errorText(response));
  return response.json() as Promise<{ request_id: string; accepted: boolean; message: string }>;
}

export async function submitMission(x: number, y: number, yaw: number) {
  return submitMissionWaypoints([{ x, y, yaw }], "web-goal");
}

export async function cancelMission(requestId: string) {
  const response = await fetch(`/api/v1/missions/${encodeURIComponent(requestId)}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(await errorText(response));
  return response.json() as Promise<{ request_id: string; confirmed: boolean; message: string }>;
}

export async function getControlOptions(): Promise<ControlOptions> {
  const response = await fetch("/api/v1/control/options");
  if (!response.ok) throw new Error(await errorText(response));
  return response.json() as Promise<ControlOptions>;
}

export async function getStackStatus(): Promise<StackStatus> {
  const response = await fetch("/api/v1/control/stack");
  if (!response.ok) throw new Error(await errorText(response));
  return response.json() as Promise<StackStatus>;
}

export async function startStack(request: StackRequest): Promise<StackStatus> {
  const response = await fetch("/api/v1/control/stack", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) throw new Error(await errorText(response));
  return response.json() as Promise<StackStatus>;
}

export async function stopStack(): Promise<StackStatus> {
  const response = await fetch("/api/v1/control/stack", { method: "DELETE" });
  if (!response.ok) throw new Error(await errorText(response));
  return response.json() as Promise<StackStatus>;
}


export async function openRviz(): Promise<StackStatus> {
  const response = await fetch("/api/v1/control/rviz", { method: "POST" });
  if (!response.ok) throw new Error(await errorText(response));
  return response.json() as Promise<StackStatus>;
}

export async function closeRviz(): Promise<StackStatus> {
  const response = await fetch("/api/v1/control/rviz", { method: "DELETE" });
  if (!response.ok) throw new Error(await errorText(response));
  return response.json() as Promise<StackStatus>;
}

export async function saveMap(name: string, overwrite = false): Promise<{
  map: MapArtifact;
  message: string;
}> {
  const response = await fetch("/api/v1/maps/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, overwrite }),
  });
  if (!response.ok) throw new Error(await errorText(response));
  return response.json();
}

export async function setInitialPose(x: number, y: number, yaw: number) {
  const response = await fetch("/api/v1/localization/initial-pose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ x, y, yaw }),
  });
  if (!response.ok) throw new Error(await errorText(response));
  return response.json() as Promise<{ accepted: boolean; message: string }>;
}

export async function sendTeleop(linearX: number, angularZ: number) {
  const response = await fetch("/api/v1/teleop", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ linear_x: linearX, angular_z: angularZ }),
  });
  if (!response.ok) throw new Error(await errorText(response));
  return response.json() as Promise<{ accepted: boolean; message: string }>;
}

export async function getNavigationReadiness(): Promise<NavigationReadiness> {
  const response = await fetch("/api/v1/navigation/readiness");
  if (!response.ok) throw new Error(await errorText(response));
  return response.json() as Promise<NavigationReadiness>;
}

export async function prepareNavigation(): Promise<NavigationReadiness> {
  const response = await fetch("/api/v1/navigation/prepare", { method: "POST" });
  if (!response.ok) throw new Error(await errorText(response));
  return response.json() as Promise<NavigationReadiness>;
}
