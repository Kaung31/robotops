import type { NavigationReadiness as NavigationReadinessModel } from "../lib/types";

export function NavigationReadiness({
  readiness,
  busy,
  onRetry,
}: {
  readiness: NavigationReadinessModel | null;
  busy: boolean;
  onRetry: () => Promise<void>;
}) {
  if (!readiness) {
    return (
      <section className="panel readiness-panel">
        <h2>Navigation readiness</h2>
        <p className="muted">Checking Nav2 readiness…</p>
      </section>
    );
  }

  const checks = [
    ["Robot odometry", readiness.odom_available],
    ["LiDAR scan", readiness.scan_available],
    ["odom → base_link", readiness.odom_to_base],
    ["Saved map", readiness.map_available],
    ["AMCL localized", readiness.localized],
    ["map → base_link", readiness.map_to_base],
  ] as const;

  return (
    <section className={`panel readiness-panel ${readiness.ready ? "ready" : "not-ready"}`}>
      <div className="panel-heading">
        <div>
          <h2>Navigation readiness</h2>
          <span className="muted">{readiness.message}</span>
        </div>
        <span className={`readiness-badge ${readiness.ready ? "ready" : "waiting"}`}>
          {readiness.ready ? "READY" : "NOT READY"}
        </span>
      </div>

      <div className="readiness-list">
        {checks.map(([label, ok]) => (
          <div key={label} className={ok ? "ok" : "waiting"}>
            <span>{ok ? "✓" : "…"}</span>
            <strong>{label}</strong>
          </div>
        ))}
        {readiness.lifecycle_nodes.map((node) => (
          <div key={node.name} className={node.state === "active" ? "ok" : "waiting"}>
            <span>{node.state === "active" ? "✓" : "…"}</span>
            <strong>{node.name}</strong>
            <small>{node.state}</small>
          </div>
        ))}
      </div>

      {!readiness.ready && (
        <button className="secondary" disabled={busy} onClick={() => void onRetry()}>
          {busy ? "Preparing…" : "Retry automatic readiness"}
        </button>
      )}
    </section>
  );
}
