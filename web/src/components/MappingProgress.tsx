import { useMemo } from "react";
import type { Pose2D, RobotSnapshot } from "../lib/types";

interface Props {
  snapshot: RobotSnapshot;
  trajectory: Pose2D[];
}

function travelledDistance(points: Pose2D[]) {
  let total = 0;
  for (let i = 1; i < points.length; i += 1) {
    total += Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
  }
  return total;
}

export function MappingProgress({ snapshot, trajectory }: Props) {
  const stats = useMemo(() => {
    const map = snapshot.map;
    if (!map || map.data.length === 0) return null;
    let known = 0;
    let free = 0;
    let occupied = 0;
    let unknown = 0;
    for (const value of map.data) {
      if (value < 0) unknown += 1;
      else {
        known += 1;
        if (value <= 25) free += 1;
        if (value >= 65) occupied += 1;
      }
    }
    const total = map.data.length;
    const cellArea = map.resolution * map.resolution;
    return {
      knownPercent: total ? (known / total) * 100 : 0,
      unknownPercent: total ? (unknown / total) * 100 : 0,
      knownArea: known * cellArea,
      freeArea: free * cellArea,
      occupiedArea: occupied * cellArea,
      widthM: map.width * map.resolution,
      heightM: map.height * map.resolution,
    };
  }, [snapshot.map]);

  const distance = useMemo(() => travelledDistance(trajectory), [trajectory]);

  let guidance = "Start driving slowly so SLAM can receive scans and odometry.";
  if (snapshot.connection !== "connected") {
    guidance = "Telemetry is not live. Wait for the stack to connect before judging map coverage.";
  } else if (!snapshot.map) {
    guidance = "Waiting for the first occupancy map. Move a short distance and rotate to expose nearby walls.";
  } else if (snapshot.scan.length === 0) {
    guidance = "Map exists, but no LiDAR scan is currently reaching the web gateway. Check sensor telemetry before continuing.";
  } else if (stats && stats.unknownPercent > 45) {
    guidance = "Large unknown regions remain inside the current map bounds. Keep exploring boundaries and unobserved corridors.";
  } else if (stats && stats.unknownPercent > 20) {
    guidance = "Coverage is improving. Revisit remaining unknown pockets and complete loops where possible.";
  } else {
    guidance = "Coverage inside the current map bounds is high. If walls look stable and the travel trail covers the environment, this is a reasonable point to save the map.";
  }

  return (
    <section className="panel mapping-progress">
      <div className="panel-heading">
        <h2>Mapping progress</h2>
        <span className="muted">SLAM coverage</span>
      </div>
      <div className="mapping-metrics">
        <article><span>Travelled</span><strong>{distance.toFixed(1)} m</strong></article>
        <article><span>Trail samples</span><strong>{trajectory.length}</strong></article>
        <article><span>Known area</span><strong>{stats ? `${stats.knownArea.toFixed(1)} m²` : "—"}</strong></article>
        <article><span>Unknown</span><strong>{stats ? `${stats.unknownPercent.toFixed(1)}%` : "—"}</strong></article>
      </div>
      {stats && (
        <div className="coverage-bar" aria-label={`Known map coverage ${stats.knownPercent.toFixed(1)} percent`}>
          <span style={{ width: `${Math.max(0, Math.min(100, stats.knownPercent))}%` }} />
        </div>
      )}
      <div className="mapping-detail">
        <span>Grid: {stats ? `${stats.widthM.toFixed(1)} × ${stats.heightM.toFixed(1)} m` : "waiting for /map"}</span>
        <span>LiDAR: {snapshot.scan.length ? `${snapshot.scan.length} points` : "no live scan"}</span>
      </div>
      <p className="mapping-guidance">{guidance}</p>
      <p className="mapping-note">Coverage is a progress indicator, not a proof that the map is complete. Stop when important spaces have been observed, walls are stable, and the trail has covered the intended environment.</p>
    </section>
  );
}
