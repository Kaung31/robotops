import type { NavigationReadiness, RobotSnapshot, StackStatus } from "../lib/types";

interface Props {
  snapshot: RobotSnapshot;
  stack: StackStatus;
  readiness: NavigationReadiness | null;
}

function downloadJson(name: string, value: unknown) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

export function SystemSnapshotPanel({ snapshot, stack, readiness }: Props) {
  const capture = () => downloadJson(`robotops-system-snapshot-${new Date().toISOString().replaceAll(":", "-")}.json`, {
    captured_at: new Date().toISOString(),
    robot: {
      robot_id: snapshot.robot_id,
      runtime_mode: snapshot.runtime_mode,
      connection: snapshot.connection,
      pose: snapshot.pose,
      mission_state: snapshot.mission_state,
      mission_run_id: snapshot.mission_run_id,
      scan_points: snapshot.scan.length,
      map: snapshot.map ? {
        frame_id: snapshot.map.frame_id,
        width: snapshot.map.width,
        height: snapshot.map.height,
        resolution: snapshot.map.resolution,
        origin: snapshot.map.origin,
      } : null,
      global_path_points: snapshot.global_path.length,
      local_path_points: snapshot.local_path.length,
    },
    stack,
    navigation_readiness: readiness,
  });

  return (
    <section className="panel diagnostics-panel">
      <div className="panel-heading">
        <div><h2>Operations snapshot</h2><span className="muted">Lightweight diagnostics export — no rosbag or map data included</span></div>
        <button type="button" className="secondary" onClick={capture}>Export snapshot</button>
      </div>
      <div className="diagnostic-strip">
        <span>Stack <strong>{stack.state}</strong></span>
        <span>Connection <strong>{snapshot.connection}</strong></span>
        <span>Mode <strong>{stack.mode ?? "stopped"}</strong></span>
        <span>Scan <strong>{snapshot.scan.length}</strong></span>
        <span>Paths <strong>{snapshot.global_path.length}/{snapshot.local_path.length}</strong></span>
        <span>Nav <strong>{readiness ? (readiness.ready ? "ready" : "waiting") : "n/a"}</strong></span>
      </div>
    </section>
  );
}
