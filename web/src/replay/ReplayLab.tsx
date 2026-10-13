import type { ManifestV2 } from "./data-v2";
import type { WarehouseManifest } from "./data-warehouse";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { MapView } from "../components/MapView";
import type { MapSnapshot, RobotSnapshot } from "../lib/types";
import { ValidationPanel, type Criteria } from "./ValidationPanel";
import { RecordedScene } from "./RecordedScene";
import { advance, occupancyRows, poseAt, scanAt, scanPoints, secondsBetween, N0_HASH, type Dataset, type Transform } from "./data";
import { initialPreviewTime, formatTime, coverageBands, frameClock } from "./presentation";
function planar(tf: Transform) {
  const [x, y, z, w] = tf.quaternion;
  return { x: tf.position[0], y: tf.position[1], yaw: Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)) };
}
// Section headings shared with the page's loading state.
export function ReplayHeading({ id, badge }: { id: string; badge?: string }) {
  return <div className="lab-section-heading"><div><p className="eyebrow"><span className="step-number">03</span>Watch the robot</p><h2 id="replay-title" className="section-title" tabIndex={-1}>Replay a recorded trial</h2>
    <p className="section-lead">Press play and follow the robot on the map, in 3D and through its LiDAR. Everything shown comes from the recording of {id}; nothing is simulated in your browser.</p></div>
    {badge && <span className="recorded-badge">{badge}</span>}</div>;
}
export function EvidenceHeading({ id }: { id: string }) {
  return <div className="lab-section-heading"><div><p className="eyebrow"><span className="step-number">05</span>Inspect the evidence</p><h2 id="evidence-title" className="section-title" tabIndex={-1}>Check {id} yourself</h2>
    <p className="section-lead">On the left, the verdicts originally recorded for this trial. On the right, your own acceptance limits, evaluated against its exact original measurements. Your checks never change the original result.</p></div></div>;
}
export function ReplayLab({ data, selector, banner, between, manifestHash, criteria }: { data: Dataset; selector?: ReactNode; banner?: ReactNode; between?: ReactNode; manifestHash?: string; criteria?: Criteria }) {
  const m = data.manifest;
  const id = m.dataset_id ?? "N0";
  const warehouse = m.schema_version === 3 ? m as WarehouseManifest : null;
  const action = m.schema_version === 2 ? (m as ManifestV2).original_validation : warehouse?.original_validation ?? null;
  // Full-window recordings start at the mission start; partial ones preview a supported moment.
  const full = m.coverage.full_mission_replay === true;
  const [view, setView] = useState<"map" | "scene">("map");
  const coverageRef = useRef<HTMLDetailsElement>(null);
  const duration = secondsBetween(m.time.mission_start_ns, m.time.mission_end_ns);
  const [time, setTime] = useState(() => full ? 0 : initialPreviewTime(data)), [playing, setPlaying] = useState(false), [speed, setSpeed] = useState(1);
  useEffect(() => {
    if (!playing) return;
    const elapsedSince = frameClock(performance.now());
    let frame = 0;
    const tick = (now: number) => { const elapsed = elapsedSince(now); setTime(t => advance(t, elapsed, true, speed, duration)); frame = requestAnimationFrame(tick); };
    frame = requestAnimationFrame(tick); return () => cancelAnimationFrame(frame);
  }, [playing, speed, duration]);
  useEffect(() => { if (time >= duration) setPlaying(false); }, [time, duration]);
  const stamp = BigInt(m.time.mission_start_ns) + BigInt(Math.round(time * 1e9));
  const pose = poseAt(data, stamp), scan = scanAt(data, stamp), points = scanPoints(scan);
  // After the last 20 Hz display sample but still inside the recording: say how far
  // back the last sample is instead of implying the recording itself has a gap.
  const lastSupported = useMemo(() => [...data.poses].reverse().find(p => p.transform && p.quality === "SUPPORTED_TF"), [data]);
  const displayTail = !pose && lastSupported && stamp > BigInt(lastSupported.ros_ns) && stamp <= BigInt(m.time.recorded_end_ns) ? secondsBetween(lastSupported.ros_ns, stamp.toString()) : null;
  const segment = data.poses.find(p => p.transform && BigInt(p.ros_ns) <= stamp)?.segment_id;
  const trail = data.poses.filter(p => p.transform && p.segment_id === segment && BigInt(p.ros_ns) <= stamp);
  const map = useMemo<MapSnapshot>(() => ({ frame_id: "map", width: m.scene.width, height: m.scene.height, resolution: m.scene.resolution_m,
    origin: { x: m.scene.origin[0], y: m.scene.origin[1], yaw: m.scene.origin[2] },
    data: occupancyRows(data.pixels, m.scene) }), [data, m.scene]);
  const snapshot: RobotSnapshot = { robot_id: id, runtime_mode: "replay", connection: "disconnected", source_timestamp_ns: stamp.toString(), received_monotonic_ns: null, pose: pose ? planar(pose) : null, map, scan: [], global_path: [], local_path: [], mission_state: null, mission_run_id: null };
  const metric = m.metrics.find(v => v.name === "mission_ros_seconds");
  const durationMetric = metric?.value;
  const distance = m.metrics.find(v => v.name === "odom_path_metres")?.value;
  const xy = m.metrics.find(v => v.name === "xy_error_m")?.value;
  const bands = useMemo(() => coverageBands(data), [data]);
  function openCoverage() {
    if (coverageRef.current) { coverageRef.current.open = true; coverageRef.current.scrollIntoView({ block: "start", behavior: "auto" }); coverageRef.current.querySelector("summary")?.focus(); }
  }
  function tabKey(event: KeyboardEvent<HTMLButtonElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? "map" : event.key === "End" ? "scene" : view === "map" ? "scene" : "map";
    setView(next); document.getElementById(`tab-${next}`)?.focus();
  }
  return <>
    <section id="replay" className="lab-section replay-section" aria-labelledby="replay-title">
    <ReplayHeading id={id} badge={`Recorded · Read-only · ${id}`} />
    {selector}
    {banner}
    <div className="coverage-note"><span><i aria-hidden="true">◧</i> {full ? "Whole navigation window recorded — reliable pose at every 20 Hz display sample of the mission." : "Partial recording — some moments have no reliable pose."}</span><button className="text-button" onClick={openCoverage}>Coverage details ↓</button></div>
    <section className="metric-strip" aria-label="Original reported metrics"><div className="metric-tile"><span>Mission</span><strong>{durationMetric?.toFixed(2) ?? "Unknown"} <small>s</small></strong></div><div className="metric-tile"><span>Distance · odometry</span><strong>{distance?.toFixed(2) ?? "Unknown"} <small>m</small></strong></div><div className="metric-tile"><span>Final position error</span><strong>{xy == null ? "Unknown" : (xy * 100).toFixed(1)} <small>cm</small></strong></div><div className="metric-tile"><span>Navigation · original ROS result</span><strong className="navigation-result">{m.original_validation.ros_outcome === "succeeded" ? "Succeeded" : m.original_validation.ros_outcome}</strong></div></section>
    <section className="player" aria-label="Recorded mission player"><div className="player-toolbar"><div className="player-actions"><button className="play-button" onClick={() => { if (time >= duration) setTime(0); setPlaying(!playing); }}><span aria-hidden="true">{playing ? "Ⅱ" : "▶"}</span> {playing ? "Pause" : "Play"}</button><button onClick={() => { setTime(0); setPlaying(false); }}>↺ Restart</button><label className="speed-control"><span className="sr-only">Playback speed</span><select aria-label="Playback speed" value={speed} onChange={e => setSpeed(Number(e.target.value))}>{[.25, .5, 1, 2, 4].map(v => <option key={v} value={v}>{v}×</option>)}</select></label></div><output className="player-clock" aria-live="off">{formatTime(time)} <span>/ {formatTime(duration)}</span></output></div>
    <p className="preview-explanation">{full ? `Playback starts at mission start. Recording began ${secondsBetween(m.time.recorded_start_ns, m.time.mission_start_ns).toFixed(1)} s earlier, before dispatch; result finalization after navigation is not recorded.` : "Preview starts at a recorded moment with a reliable pose; the mission beginning is missing. Restart shows the original start."}</p>
    <div className="timeline-track"><div className="coverage-bands" aria-hidden="true">{bands.map((b, i) => <span key={i} className={`coverage-band ${b.kind}`} style={{ left: `${b.start}%`, width: `${b.end - b.start}%` }} />)}</div><input aria-label="Mission timeline seconds" aria-valuetext={`mission +${time.toFixed(3)} seconds of ${duration}; ${pose ? "supported pose" : "pose unavailable"}`} type="range" min="0" max={duration} step="0.001" value={time} onChange={e => setTime(Number(e.target.value))} /></div>
    <div className="timeline-legend"><span><i className="pose" />Supported pose</span><span><i className="recorded" />Recorded, no display pose</span><span><i className="missing" />Unrecorded</span><span className="original-label">Original reported metrics above · mission time</span></div>
    </section>
    <section className="workspace" aria-label="Synchronized recorded visualizations"><div className="view-tabs" role="tablist" aria-label="Recorded visualization"><button id="tab-map" role="tab" aria-selected={view === "map"} aria-controls="panel-map" tabIndex={view === "map" ? 0 : -1} onKeyDown={tabKey} onClick={() => setView("map")}>2D navigation map</button><button id="tab-scene" role="tab" aria-selected={view === "scene"} aria-controls="panel-scene" tabIndex={view === "scene" ? 0 : -1} onKeyDown={tabKey} onClick={() => setView("scene")}>Schematic 3D</button></div>
    <section id="panel-map" className={`visual-panel map-panel ${view === "map" ? "selected" : ""}`} aria-labelledby="map-title"><div className="panel-heading"><h3 id="map-title">2D navigation map</h3><span>Occupancy · localized TF</span></div><div className={`visual-status ${pose ? "" : "unavailable"}`} role="status" data-testid="pose-status">{pose ? "Pose available · recorded localized TF" : displayTail !== null ? `Pose unavailable — last 20 Hz display sample is ${displayTail.toFixed(3)} s earlier; no movement reconstructed` : "Pose unavailable — no movement reconstructed"}</div><MapView snapshot={snapshot} selectedGoal={null} onGoalSelect={() => undefined} trajectory={trail.map(p => planar(p.transform!))} mappingActive readOnly recordedScan={points.map(p => ({ x: p[0], y: p[1] }))} /></section>
    <section id="panel-scene" className={`visual-panel scene-panel ${view === "scene" ? "selected" : ""}`} aria-labelledby="scene-title"><div className="panel-heading"><h3 id="scene-title">Schematic 3D</h3><span>Recorded observations</span></div><div className={`visual-status ${pose ? "" : "unavailable"}`}>{pose ? "Schematic robot · not exact CAD or physical truth" : "Pose unavailable — robot hidden"}</div><RecordedScene pose={pose} points={points} trail={trail.map(p => p.transform!.position)} /></section>
    </section>
    <div className={`sensor-status ${scan ? "" : "unavailable"}`}>{scan ? `LiDAR available · ${points.length} supported rays · scan age ${secondsBetween(scan.ros_ns, stamp.toString()).toFixed(3)} s` : "LiDAR unavailable — missing TF, recording coverage, or scan older than 0.200 s"}<span>Views share the same mission cursor. Scans stay at their recorded transforms.</span></div>
    </section>
    {between}
    <section id="evidence" className="lab-section evidence-section" aria-labelledby="evidence-title">
    <EvidenceHeading id={id} />
    <div className="results-row">
    <section className="result-card originals" aria-labelledby="originals-title"><div className="section-kicker">ORIGINAL RECORDED EVIDENCE · UNCHANGED</div><h3 id="originals-title">Recorded experiment outcome</h3><dl className="original-results"><div><dt>ROS navigation</dt><dd>{m.original_validation.ros_outcome}</dd></div><div><dt>Localized pose</dt><dd>{m.original_validation.pose_verdict}</dd></div><div><dt>Scoped contact</dt><dd>{m.original_validation.contact_verdict}</dd></div></dl><p className="card-footnote">No contact observed within monitored geometry. Universal collision freedom is <strong>not assessable</strong>.</p>{warehouse && <p className="card-footnote">Benchmark status: exploratory, not qualified. Stack teardown: {warehouse.teardown.status === "CRASHED_AFTER_EVIDENCE_FINALIZED" ? warehouse.teardown.detail : "no child failure logged"}. Recorder transport loss: {warehouse.recorder_loss.transport_lost_messages} messages (accounting complete).</p>}</section>
    <ValidationPanel data={data} initial={criteria} /></div>
    <div className="engineering-evidence" role="group" aria-labelledby="technical-title"><div className="evidence-heading"><h3 id="technical-title">Technical detail</h3><span>Original precision, provenance and recording limits</span></div>
    <details ref={coverageRef} id="coverage"><summary>Recording coverage &amp; gaps</summary><div className="detail-body"><p>Original mission: {durationMetric} s{full ? " (mission start → navigation end)" : ""}. Recorded clock coverage: {secondsBetween(m.time.recorded_start_ns, m.time.recorded_end_ns)} s. TF-supported segment: {secondsBetween(m.segments[0].start_ros_ns, m.segments[0].end_ros_ns)} s. {full ? "The recording covers the whole navigation window; the only pose gap is before dispatch." : "These are different intervals; this is not a full-mission recording."}</p><p>Actual display pose samples: ROS ns {data.poses.find(p => p.transform)?.ros_ns} → {data.poses.at(-1)?.ros_ns}. Playback initially previews a supported recorded moment. Restart begins at the unavailable mission head.</p><ul>{m.coverage.gaps.map(g => <li key={g.reason}>{g.reason}: ROS ns {g.start_ros_ns} → {g.end_ros_ns}</li>)}</ul><p>No interpolation across invalid intervals, extrapolation, or invented missing motion.</p></div></details>
    <details><summary>Technical timestamps / TF &amp; frames</summary><div className="detail-body"><p>Cursor ROS ns: <code>{stamp.toString()}</code> · mission +{time.toFixed(9)} s.</p><p>Current scan ROS ns: {scan?.ros_ns ?? "UNAVAILABLE"}. Scan age: {scan ? `${secondsBetween(scan.ros_ns, stamp.toString())} s` : "UNAVAILABLE"}. Scans step without interpolation; maximum display age 0.200 s.</p><p>ROS right-handed metres, Z up; map → odom → base_link → lidar_link. Recorded localized TF is not physical ground truth. Three display coordinates (x, z, −y), quaternion (qx, qz, −qy, qw), applied only for rendering.</p><p>Visitor checks compare exact qualified original measurements with your maximum; equality passes. They do not change original verdicts.</p></div></details>
    <details><summary>Original measurements &amp; evidence</summary><div className="detail-body"><table><thead><tr><th>Original metric</th><th>Exact exported value</th></tr></thead><tbody>{m.metrics.map(v => <tr key={v.name}><td>{v.name}</td><td>{v.value ?? "UNKNOWN"} {v.unit}</td></tr>)}</tbody></table><p>Separate final report pose at ROS ns {m.original_validation.final_pose_ros_ns}: ({m.original_validation.final_localized_pose.x}, {m.original_validation.final_localized_pose.y}), yaw {m.original_validation.final_localized_pose.yaw}. Never animated as a recording sample.</p><p>Contact: {m.original_validation.contact_frame_count} monitored frames · {m.original_validation.contact_scope}. Universal collision freedom: NOT ASSESSABLE.</p></div></details>
    <details><summary>Provenance and limitations</summary><div className="detail-body"><p>Manifest SHA-256: <code>{manifestHash ?? (m.schema_version === 2 ? (m.dataset_id === "N0" ? "670ccd62c5b5d0e74fc379c2ce9e478534995fd6af2571fc9933fc377d1f85f8" : "a4d2c77a28e74d7124429ccc7f8c56010f81802898315bcc1d3de097912028d4") : N0_HASH)}</code>. Exact private version {m.schema_version}; hashes are integrity checks, not signatures. Sanitized derivative; original report remains separate. Original software revision unavailable.</p><ul>{m.coverage.missing_channels.map(v => <li key={v}>{v}</li>)}</ul><p>No Nav2 action or fault events reconstructed. Downsampled graphics are not authoritative metrics. Schematic robot dimensions are illustrative, not a measurement or reconstruction of physical geometry.</p><ul>{m.limitations.map(v => <li key={v}>{v}</li>)}</ul>{action && <p>Saved ExecuteMission status source: <code>{action.mission_action.pointer}</code>. Scope: {action.mission_action.scope}; no recorded action stream or event timestamp.</p>}</div></details>
    </div>{action && <p className="action-snapshot-note">Saved mission-action result: ExecuteMission {action.action_status_reason === "AVAILABLE" ? `STATUS_SUCCEEDED (${action.action_status})` : "unavailable"}, observed by {action.mission_action.observer}. This is a result snapshot, not a timestamped Nav2 action stream or execution-start time. </p>}
    </section>
  </>;
}
