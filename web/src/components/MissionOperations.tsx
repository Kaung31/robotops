import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { cancelMission, submitMissionWaypoints } from "../lib/api";
import { saveMissionRun, type MissionOutcome } from "../lib/runHistory";
import type { ConnectionState, Pose2D, RobotSnapshot, RuntimeMode } from "../lib/types";

interface Props {
  snapshot: RobotSnapshot;
  mode: RuntimeMode;
  connection: ConnectionState;
  selectedGoal: Pose2D | null;
  navigationReady: boolean;
  navigationProfile: string | null;
  mapId: string | null;
}

interface ActiveRun {
  requestId: string;
  navigationProfile: string;
  mapId: string;
  startedMs: number;
  lastPose: Pose2D | null;
  distanceM: number;
  waypoints: Pose2D[];
  label: string;
  observedProgress: boolean;
}

const ACTIVE_STATES = new Set(["preparing", "recording", "navigating", "canceling", "finalizing"]);
const MAX_WAYPOINTS = 100;
const TERMINAL_STATES = new Set<MissionOutcome>(["succeeded", "failed", "canceled", "cancellation_unconfirmed", "result_unavailable"]);

export function MissionOperations({ snapshot, mode, connection, selectedGoal, navigationReady, navigationProfile, mapId }: Props) {
  const [x, setX] = useState("1.0");
  const [y, setY] = useState("0.0");
  const [yaw, setYaw] = useState("0.0");
  const [route, setRoute] = useState<Pose2D[]>([]);
  const [message, setMessage] = useState("Build a route or send a single goal.");
  const [active, setActive] = useState<ActiveRun | null>(null);
  const [missionPhase, setMissionPhase] = useState("ready for goal");
  const [elapsedS, setElapsedS] = useState(0);
  const activeRef = useRef<ActiveRun | null>(null);

  useEffect(() => { activeRef.current = active; }, [active]);

  useEffect(() => {
    if (!active) { setElapsedS(0); return; }
    const update = () => setElapsedS(Math.max(0, (Date.now() - active.startedMs) / 1000));
    update();
    const timer = window.setInterval(update, 250);
    return () => window.clearInterval(timer);
  }, [active?.requestId, active?.startedMs]);

  useEffect(() => {
    if (!selectedGoal) return;
    setX(selectedGoal.x.toFixed(2));
    setY(selectedGoal.y.toFixed(2));
    setYaw(selectedGoal.yaw.toFixed(2));
    setMessage("Goal selected from map. Add it to the route or send it directly.");
  }, [selectedGoal]);

  useEffect(() => {
    const current = activeRef.current;
    if (!current || !snapshot.pose) return;
    const previous = current.lastPose;
    if (!previous) {
      const next = { ...current, lastPose: snapshot.pose };
      activeRef.current = next;
      setActive(next);
      return;
    }
    const delta = Math.hypot(snapshot.pose.x - previous.x, snapshot.pose.y - previous.y);
    if (delta < 0.001 || delta > 1.0) return;
    const next = { ...current, lastPose: snapshot.pose, distanceM: current.distanceM + delta };
    activeRef.current = next;
    setActive(next);
  }, [snapshot.pose]);

  useEffect(() => {
    const current = activeRef.current;
    if (!current) return;
    const state = snapshot.mission_state?.toLowerCase() ?? "";
    if (ACTIVE_STATES.has(state)) {
      if (!current.observedProgress) {
        const next = { ...current, observedProgress: true };
        activeRef.current = next;
        setActive(next);
      }
      setMissionPhase(state);
      return;
    }
    if (!current.observedProgress || !TERMINAL_STATES.has(state as MissionOutcome)) return;

    const endedMs = Date.now();
    saveMissionRun({
      id: `${current.requestId}-${endedMs}`,
      requestId: current.requestId,
      runId: snapshot.mission_run_id,
      label: current.label,
      startedAt: new Date(current.startedMs).toISOString(),
      endedAt: new Date(endedMs).toISOString(),
      outcome: state as MissionOutcome,
      durationS: Math.max(0, (endedMs - current.startedMs) / 1000),
      distanceM: current.distanceM,
      waypointCount: current.waypoints.length,
      waypoints: current.waypoints,
      navigationProfile: current.navigationProfile,
      mapId: current.mapId,
    });
    activeRef.current = null;
    setActive(null);
    setMissionPhase("ready for next goal");
    setMessage(`Mission ${state}. Ready for the next goal.`);
  }, [snapshot.mission_state, snapshot.mission_run_id]);

  const mutatingDisabled = mode === "replay" || mode === "unknown";
  const startDisabled = mutatingDisabled || connection !== "connected" || !navigationReady || active !== null;
  const currentPoint = useMemo(() => ({ x: Number(x), y: Number(y), yaw: Number(yaw) }), [x, y, yaw]);
  const pointValid = Number.isFinite(currentPoint.x) && Number.isFinite(currentPoint.y) && Number.isFinite(currentPoint.yaw);

  function addWaypoint() {
    if (!pointValid) { setMessage("Waypoint coordinates must be valid numbers."); return; }
    if (route.length >= MAX_WAYPOINTS) { setMessage(`Route limit is ${MAX_WAYPOINTS} waypoints.`); return; }
    setRoute((items) => [...items, currentPoint]);
    setMessage(`Waypoint ${route.length + 1} added.`);
  }

  function removeWaypoint(index: number) {
    setRoute((items) => items.filter((_, i) => i !== index));
  }

  async function launch(waypoints: Pose2D[], label: string) {
    if (!waypoints.length || startDisabled) return;
    try {
      setMissionPhase("sending");
      setMessage("Sending mission to RobotOps…");
      const result = await submitMissionWaypoints(waypoints, label);
      const next: ActiveRun = {
        requestId: result.request_id,
        navigationProfile: navigationProfile ?? "unknown",
        mapId: mapId ?? "unknown",
        startedMs: Date.now(),
        lastPose: snapshot.pose,
        distanceM: 0,
        waypoints: waypoints.map((item) => ({ ...item })),
        label,
        observedProgress: false,
      };
      activeRef.current = next;
      setActive(next);
      setMissionPhase("accepted / waiting for feedback");
      setMessage(result.message);
    } catch (error) {
      setMissionPhase("ready for goal");
      setMessage(error instanceof Error ? error.message : "Mission request failed");
    }
  }

  async function submitSingle(event: FormEvent) {
    event.preventDefault();
    if (!pointValid) { setMessage("Goal coordinates must be valid numbers."); return; }
    await launch([currentPoint], "web-goal");
  }

  async function submitRoute() {
    await launch(route, `web-route-${route.length}`);
  }

  async function cancel() {
    const current = activeRef.current;
    if (!current) return;
    try {
      setMissionPhase("canceling");
      const result = await cancelMission(current.requestId);
      setMessage(result.message);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cancellation failed");
    }
  }

  return (
    <section className="panel mission-ops">
      <div className="panel-heading mission-heading">
        <div><h2>Mission operations</h2><span className="muted">{missionPhase}</span></div>
        <span className={`mission-state-pill ${active ? "active" : "idle"}`}>{active ? "ACTIVE" : "READY"}</span>
      </div>
      {mode === "replay" && <p className="warning">Replay is read-only.</p>}
      {!navigationReady && mode !== "replay" && <p className="warning">Navigation is not ready yet.</p>}

      <form onSubmit={submitSingle} className="mission-form compact-mission-form">
        <label>X <input value={x} onChange={(e) => setX(e.target.value)} inputMode="decimal" /></label>
        <label>Y <input value={y} onChange={(e) => setY(e.target.value)} inputMode="decimal" /></label>
        <label>Yaw <input value={yaw} onChange={(e) => setYaw(e.target.value)} inputMode="decimal" /></label>
        <div className="mission-actions-row">
          <button type="button" className="secondary" disabled={!pointValid || active !== null || route.length >= MAX_WAYPOINTS} onClick={addWaypoint}>Add waypoint</button>
          <button disabled={startDisabled || !pointValid}>Send single goal</button>
        </div>
      </form>

      <div className="route-builder">
        <div className="route-title"><strong>Route</strong><span>{route.length} waypoint{route.length === 1 ? "" : "s"}</span></div>
        {route.length === 0 ? <p className="muted route-empty">No queued waypoints.</p> : (
          <ol className="waypoint-list">
            {route.map((point, index) => <li key={`${index}-${point.x}-${point.y}`}><span>#{index + 1} · {point.x.toFixed(2)}, {point.y.toFixed(2)} · {point.yaw.toFixed(2)} rad</span><button type="button" className="ghost tiny" disabled={active !== null} onClick={() => removeWaypoint(index)}>×</button></li>)}
          </ol>
        )}
        <div className="mission-actions-row">
          <button type="button" className="secondary" disabled={route.length === 0 || active !== null} onClick={() => setRoute([])}>Clear</button>
          <button type="button" disabled={startDisabled || route.length === 0} onClick={submitRoute}>Run route</button>
        </div>
      </div>

      {active && <div className="active-mission-metrics"><span>Elapsed <strong>{elapsedS.toFixed(1)} s</strong></span><span>Travel <strong>{active.distanceM.toFixed(2)} m</strong></span><span>Goals <strong>{active.waypoints.length}</strong></span></div>}
      <button type="button" className="secondary cancel-mission" disabled={!active || mutatingDisabled} onClick={cancel}>Cancel active mission</button>
      <p className="message mission-message">{message}</p>
    </section>
  );
}
