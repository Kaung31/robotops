import { ControlCenter } from "./components/ControlCenter";
import { LaserView } from "./components/LaserView";
import { LocalizationPanel } from "./components/LocalizationPanel";
import { MapView } from "./components/MapView";
import { MappingProgress } from "./components/MappingProgress";
import { Robot3DView } from "./components/Robot3DView";
import { MissionOperations } from "./components/MissionOperations";
import { BenchmarkDashboard } from "./components/BenchmarkDashboard";
import { NavigationReadiness } from "./components/NavigationReadiness";
import { TeleopPanel } from "./components/TeleopPanel";
import { SystemSnapshotPanel } from "./components/SystemSnapshotPanel";
import { BenchmarkCampaign } from "./components/BenchmarkCampaign";
import { useControlCenter } from "./lib/useControlCenter";
import { useTelemetry } from "./lib/useTelemetry";
import { useEffect, useRef, useState } from "react";
import type { Pose2D } from "./lib/types";
import "./styles.css";

export default function App() {
  const { snapshot, error: telemetryError } = useTelemetry();
  const control = useControlCenter();
  const [selectedGoal, setSelectedGoal] = useState<Pose2D | null>(null);
  const [visualMode, setVisualMode] = useState<"map" | "3d">("map");
  const [mappingTrajectory, setMappingTrajectory] = useState<Pose2D[]>([]);
  const mappingWasRunning = useRef(false);

  const mappingRunning = control.stack?.state === "running" && control.stack?.mode === "mapping";

  useEffect(() => {
    if (mappingRunning && !mappingWasRunning.current) {
      setMappingTrajectory([]);
    }
    mappingWasRunning.current = mappingRunning;
  }, [mappingRunning]);

  useEffect(() => {
    const pose = snapshot?.pose;
    if (!mappingRunning || snapshot?.connection !== "connected" || !pose) return;
    setMappingTrajectory((points) => {
      const last = points[points.length - 1];
      if (last && Math.hypot(pose.x - last.x, pose.y - last.y) < 0.035) return points;
      const next = [...points, pose];
      return next.length > 5000 ? next.slice(next.length - 5000) : next;
    });
  }, [mappingRunning, snapshot?.connection, snapshot?.pose]);

  if (!snapshot || !control.options || !control.stack) {
    return (
      <main className="shell">
        <h1>RobotOps</h1>
        <p>Connecting to RobotOps services…</p>
        {(telemetryError || control.error) && <p className="warning">{telemetryError ?? control.error}</p>}
      </main>
    );
  }

  const navigationRunning = control.stack.state === "running" && control.stack.mode === "navigation";

  return (
    <main className="shell">
      <header>
        <div>
          <p className="eyebrow">ROBOTOPS</p>
          <h1>Operations Console</h1>
          <p className="subtitle">Simulation-first mapping, navigation and validation control center</p>
        </div>
        <div className="header-status">
          <span className={`stack-state ${control.stack.state}`}>stack {control.stack.state}</span>
          <div className={`connection ${snapshot.connection}`}>{snapshot.connection}</div>
        </div>
      </header>

      {(telemetryError || control.error) && <p className="warning banner">{telemetryError ?? control.error}</p>}

      <ControlCenter
        options={control.options}
        stack={control.stack}
        busy={control.busy}
        onStart={control.start}
        onStop={control.stop}
        onOpenRviz={control.launchRviz}
        onCloseRviz={control.stopRviz}
        onSaveMap={control.saveCurrentMap}
      />

      <div className="status-grid">
        <article><span>Runtime</span><strong>{snapshot.runtime_mode}</strong></article>
        <article><span>Workflow</span><strong>{control.stack.mode ?? "stopped"}</strong></article>
        <article><span>Mission</span><strong>{snapshot.mission_state ?? "idle / unknown"}</strong></article>
        <article><span>Pose</span><strong>{snapshot.pose ? `${snapshot.pose.x.toFixed(2)}, ${snapshot.pose.y.toFixed(2)}` : "unavailable"}</strong></article>
      </div>

      <div className="layout">
        <section className="panel map-panel">
          <div className="panel-heading visual-heading">
            <div>
              <h2>{visualMode === "map" ? "Live map & robot pose" : "3D robot view"}</h2>
              <span className="muted">{visualMode === "map" ? (snapshot.map?.frame_id ?? "no map") : "pose + LiDAR"}</span>
            </div>
            <div className="view-switch" role="tablist" aria-label="Visualization mode">
              <button className={visualMode === "map" ? "selected" : "ghost"} onClick={() => setVisualMode("map")}>2D Map</button>
              <button className={visualMode === "3d" ? "selected" : "ghost"} onClick={() => setVisualMode("3d")}>3D Robot</button>
            </div>
          </div>
          <div className={`visual-status ${snapshot.connection}`}>
            <span className={`live-dot ${snapshot.connection}`} />
            {snapshot.connection === "connected" ? "LIVE" : snapshot.connection === "stale" ? "STALE · showing last received data" : "OFFLINE · showing cached data if available"}
          </div>
          {visualMode === "map" ? (
            snapshot.map ? (
              <MapView snapshot={snapshot} selectedGoal={selectedGoal} onGoalSelect={setSelectedGoal} trajectory={mappingTrajectory} mappingActive={mappingRunning} />
            ) : <div className="empty-visual"><strong>No map received yet</strong><span>Start Mapping or Navigation to populate /map.</span></div>
          ) : (
            <Robot3DView snapshot={snapshot} trajectory={mappingTrajectory} mappingActive={mappingRunning} />
          )}
        </section>
        <div className="side-stack">
          <TeleopPanel mode={snapshot.runtime_mode} connection={snapshot.connection} />
          {(mappingRunning || control.stack.mode === "mapping") && <MappingProgress snapshot={snapshot} trajectory={mappingTrajectory} />}
          {navigationRunning && (
            <NavigationReadiness
              readiness={control.navigationReadiness}
              busy={control.busy}
              onRetry={control.retryNavigationReadiness}
            />
          )}
          {navigationRunning && <LocalizationPanel connection={snapshot.connection} />}
          {navigationRunning && (
            <MissionOperations
              snapshot={snapshot}
              mode={snapshot.runtime_mode}
              connection={snapshot.connection}
              selectedGoal={selectedGoal}
              navigationReady={control.navigationReadiness?.ready ?? false}
              navigationProfile={control.stack.navigation_profile}
              mapId={control.stack.map_id}
            />
          )}
          <section className="panel">
            <div className="panel-heading"><h2>LiDAR</h2><span className="muted">{snapshot.scan.length} points</span></div>
            {snapshot.scan.length ? <LaserView points={snapshot.scan} /> : <p>No scan received.</p>}
          </section>
        </div>
      </div>

      <BenchmarkDashboard />
      <BenchmarkCampaign options={control.options} stack={control.stack} snapshot={snapshot} selectedGoal={selectedGoal} />
      <SystemSnapshotPanel snapshot={snapshot} stack={control.stack} readiness={control.navigationReadiness} />

      <footer>
        <span>Robot: {snapshot.robot_id}</span>
        <span>Run: {snapshot.mission_run_id ?? "—"}</span>
        <span>Processes: {control.stack.processes.length ? control.stack.processes.join(", ") : "none"}</span>
      </footer>
    </main>
  );
}
