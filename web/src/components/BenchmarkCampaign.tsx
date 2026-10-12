import { useEffect, useMemo, useState } from "react";
import { campaignDefinition, isCampaignActive, measured, summarizeCampaign } from "../lib/campaignClient";
import { loadCampaigns } from "../lib/campaignHistory";
import type { CampaignDefinition } from "../lib/campaignTypes";
import { useCampaigns } from "../lib/useCampaigns";
import type { ControlOptions, Pose2D, RobotSnapshot, StackStatus } from "../lib/types";
import { ContactEvidence } from "./ContactEvidence";
import { CampaignReports } from "./CampaignReports";

interface Props {
  options: ControlOptions;
  stack: StackStatus;
  snapshot: RobotSnapshot;
  selectedGoal: Pose2D | null;
}
function downloadJson(name: string, value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}
const quantity = (value: number | null, unit: string) => value === null ? "unavailable" : `${value.toFixed(2)} ${unit}`;

export function BenchmarkCampaign({ options, stack, snapshot, selectedGoal }: Props) {
  const client = useCampaigns();
  const [world, setWorld] = useState(stack.world ?? options.worlds[0]?.id ?? "mapping_lab");
  const compatibleMaps = useMemo(() => options.maps.filter(map => map.world_id === world), [options.maps, world]);
  const [mapId, setMapId] = useState(stack.map_id ?? compatibleMaps[0]?.id ?? "");
  const [profiles, setProfiles] = useState(() => options.navigation_profiles.map(item => item.id));
  const [repetitions, setRepetitions] = useState(1);
  const [timeoutS, setTimeoutS] = useState(180);
  const [returnToStart, setReturnToStart] = useState(true);
  const [route, setRoute] = useState<Pose2D[]>([]);
  const [start, setStart] = useState<CampaignDefinition["start"]>({ x: 0, y: 0, yaw: 0, position_tolerance: .35, yaw_tolerance: .4 });
  const [legacy] = useState(loadCampaigns);
  const owned = client.runtime?.campaign_id !== null && client.runtime?.campaign_id !== undefined;
  const locked = client.busy || owned || client.pending !== null;
  const current = client.current;
  const summaries = useMemo(() => current ? summarizeCampaign(current) : [], [current]);
  const supported = client.runtime?.execution_enabled && client.runtime.supported_modes.includes("sim");
  const liveMode = snapshot.runtime_mode === "replay" || snapshot.runtime_mode === "real";
  const canStart = client.fresh && supported && !locked && !liveMode && stack.state === "stopped"
    && mapId !== "" && profiles.length > 0 && route.length > 0 && profiles.length * repetitions <= 100
    && Object.values(start).every(Number.isFinite) && start.position_tolerance > 0 && start.position_tolerance <= 10
    && start.yaw_tolerance > 0 && start.yaw_tolerance <= Math.PI;

  useEffect(() => {
    if (!compatibleMaps.some(map => map.id === mapId)) setMapId(compatibleMaps[0]?.id ?? "");
  }, [compatibleMaps, mapId]);

  function run() {
    if (!canStart) return;
    void client.submit(campaignDefinition({
      name: `Benchmark ${new Date().toLocaleString()}`, runtime_mode: "sim", robot_model: "robotops_base",
      world, map_id: mapId, profiles: [...profiles], repetitions, start: { ...start },
      timeouts: { response: 15, trial: timeoutS, cancel: 30 },
    }, route, returnToStart));
  }
  const phase = current ? `${current.state} · ${current.definition.name}` : "Configure a repeatable campaign.";

  return <section className="panel campaign-panel" aria-label="Automated benchmark campaign">
    <div className="panel-heading campaign-heading">
      <div><h2>Automated benchmark campaign</h2><span className="muted">Backend-owned trials · recorded ROS metrics · refresh without stopping a run</span></div>
      <div className="campaign-actions">
        {current && <button type="button" className="secondary" onClick={() => downloadJson(`robotops-${current.id}.json`, current)}>Export campaign</button>}
        {current && isCampaignActive(current)
          ? <button type="button" className="danger" disabled={client.busy || !client.fresh || liveMode} onClick={() => void client.cancel(current.id)}>Stop campaign</button>
          : <button type="button" disabled={!canStart} onClick={run}>Run campaign</button>}
      </div>
    </div>
    {client.pollError && <p className="warning" role="status">Campaign connection unavailable: {client.pollError}. Showing last known state; execution may continue.</p>}
    {client.actionError && <p className="warning" role="alert">{client.actionError}</p>}
    {!supported && client.fresh && <p className="muted">Backend simulation campaign execution is unavailable.</p>}
    {client.fresh && stack.state !== "stopped" && !owned && <p className="muted">Stop the manual stack before starting a campaign.</p>}
    {owned && <p className="muted">Campaign {client.runtime?.campaign_id} owns the runtime. Manual robot commands are blocked until cleanup or reconciliation finishes.</p>}
    {owned && !client.runtime?.worker_active && <p className="warning">This backend process has no active worker for the reserved campaign. Its runner may still be executing; ownership remains reserved.</p>}
    {client.pending && <div className="campaign-phase">
      <p>A campaign request needs a response. Retry uses the same request identity and does not restart a finalized campaign.</p>
      <button type="button" disabled={client.busy || !client.fresh || liveMode} onClick={() => void client.submit()}>Retry campaign request</button>{" "}
      <button type="button" className="secondary" disabled={client.busy || !client.fresh || liveMode} onClick={() => void client.cancelPending()}>Cancel pending request</button>
    </div>}
    {!owned && <>
    <div className="campaign-config-grid">
      <label>World<select disabled={locked} value={world} onChange={e => setWorld(e.target.value)}>{options.worlds.map(item => <option key={item.id} value={item.id}>{item.label} · {item.difficulty}</option>)}</select></label>
      <label>Saved map<select disabled={locked} value={mapId} onChange={e => setMapId(e.target.value)}>{compatibleMaps.map(item => <option key={item.id} value={item.id}>{item.label}{item.is_latest ? " · latest" : ""}</option>)}</select></label>
      <label>Repetitions<input disabled={locked} type="number" min={1} max={10} value={repetitions} onChange={e => setRepetitions(Math.min(10, Math.max(1, Number(e.target.value) || 1)))} /></label>
      <label>Trial timeout (s)<input disabled={locked} type="number" min={30} max={600} value={timeoutS} onChange={e => setTimeoutS(Math.min(600, Math.max(30, Number(e.target.value) || 180)))} /></label>
    </div>
    <div className="campaign-profiles"><strong>Profiles</strong>{options.navigation_profiles.map(profile => <label key={profile.id}><input disabled={locked} type="checkbox" checked={profiles.includes(profile.id)} onChange={() => setProfiles(items => items.includes(profile.id) ? items.filter(p => p !== profile.id) : [...items, profile.id])} />{profile.label}</label>)}</div>
    <fieldset disabled={locked} className="campaign-route-builder"><legend>Required start pose</legend>
      <div className="campaign-config-grid">{([
        ["x", "Start x (m)"], ["y", "Start y (m)"], ["yaw", "Start yaw (rad)"],
        ["position_tolerance", "Position tolerance (m)"], ["yaw_tolerance", "Yaw tolerance (rad)"],
      ] as const).map(([key, label]) => <label key={key}>{label}<input type="number" step="0.01" value={Number.isFinite(start[key]) ? start[key] : ""} onChange={e => setStart(value => ({ ...value, [key]: e.target.value === "" ? NaN : Number(e.target.value) }))} /></label>)}</div>
      <p className="muted">The runner checks this pose before every mission. This sets required conditions; it does not reposition the robot.</p>
    </fieldset>
    <div className="campaign-route-builder">
      <div className="route-title"><strong>Campaign route</strong><span>{route.length} waypoints</span></div>
      <div className="campaign-actions">
        <button type="button" className="secondary" disabled={locked || !selectedGoal || route.length >= 99} onClick={() => selectedGoal && setRoute(items => [...items, { ...selectedGoal }])}>Add selected map goal</button>
        <button type="button" className="secondary" disabled={locked || !snapshot.pose || route.length >= 99} onClick={() => snapshot.pose && setRoute(items => [...items, { ...snapshot.pose! }])}>Add displayed robot pose</button>
        <button type="button" className="ghost" disabled={locked || !route.length} onClick={() => setRoute([])}>Clear route</button>
      </div>
      {!route.length ? <p className="muted">Select a point on the map and add it to the route.</p> : <ol className="waypoint-list">{route.map((point, index) => <li key={index}><span>#{index + 1} · {point.x.toFixed(2)}, {point.y.toFixed(2)} · {point.yaw.toFixed(2)} rad</span><button type="button" aria-label={`Remove waypoint ${index + 1}`} disabled={locked} className="ghost tiny" onClick={() => setRoute(items => items.filter((_, i) => i !== index))}>×</button></li>)}</ol>}
      <label className="campaign-checkbox"><input disabled={locked} type="checkbox" checked={returnToStart} onChange={e => setReturnToStart(e.target.checked)} />Append the configured start pose as the final waypoint</label>
      <p className="muted">Every trial starts a fresh stack. Closing or refreshing this page does not stop execution.</p>
    </div>
    </>}
    <div className={`campaign-phase ${owned ? "running" : ""}`} role="status">{phase}</div>
    {current && <>
      <div className="campaign-actions"><button type="button" className="secondary" disabled={locked} onClick={() => {
        const definition = current.definition;
        setWorld(definition.world); setMapId(definition.map_id); setProfiles([...definition.profiles]);
        setRepetitions(definition.repetitions); setTimeoutS(definition.timeouts.trial);
        setStart({ ...definition.start }); setRoute(definition.waypoints.map(point => ({ ...point })));
        setReturnToStart(false);
      }}>Use campaign configuration</button></div>
      <details open={owned} className="campaign-history"><summary>Submitted route and start conditions</summary>
        <p>Start: {current.definition.start.x}, {current.definition.start.y} m · yaw {current.definition.start.yaw} rad · tolerances {current.definition.start.position_tolerance} m / {current.definition.start.yaw_tolerance} rad</p>
        <ol>{current.definition.waypoints.map((point, index) => <li key={index}>{point.x}, {point.y} m · yaw {point.yaw} rad</li>)}</ol>
      </details>
      <div className="campaign-progress">
        <span>Campaign ID<strong>{current.id}</strong></span>
        <span>Resolved trials<strong>{current.trials.filter(t => !["planned", "starting", "running"].includes(t.state)).length}/{current.trials.length}</strong></span>
        <span>Map<strong>{current.definition.map_id}</strong></span>
      </div>
      {current.error && <p className="warning">{current.error}</p>}
      {current.state === "draft" && <div className="campaign-actions">
        <button type="button" disabled={client.busy || client.pending !== null || owned || !client.fresh || !supported || liveMode || stack.state !== "stopped"} onClick={() => void client.startDraft(current.id)}>Start saved draft</button>
        <button type="button" disabled={client.busy || !client.fresh || liveMode} className="secondary" onClick={() => void client.cancel(current.id)}>Cancel saved draft</button>
      </div>}
      {(current.state === "interrupted" || !client.runtime?.worker_active) && owned && <div className="campaign-phase">
        <p>Outcome is uncertain. Stop the orphaned runtime before releasing ownership. Reconciliation preserves this result and never retries the mission.</p>
        <button type="button" disabled={client.busy || !client.fresh || liveMode} onClick={() => void client.reconcile(current.id)}>Reconcile stopped runtime</button>
      </div>}
      <div className="campaign-summary-grid">{summaries.map(item => <article key={item.profile}>
        <span>{item.profile}</span><strong>{item.successRate === null ? "No finalized attempts" : `${item.successRate.toFixed(0)}% ROS success`}</strong>
        <small>{item.successes}/{item.attempted} finalized attempts · {item.requested} requested</small>
        <small>Mean ROS duration: {quantity(item.time.value, "s")} ({item.time.samples} {item.time.samples === 1 ? "sample" : "samples"})</small>
        <small>Mean recorded odometry distance: {quantity(item.distance.value, "m")} ({item.distance.samples} {item.distance.samples === 1 ? "sample" : "samples"})</small>
      </article>)}</div>
      <p className="muted">ROS outcome, localized pose validation and contact evidence are separate. Missing measurements stay unavailable; older results remain unvalidated. Contact evidence assesses monitored geometry and coverage, not physical safety.</p>
      <div className="campaign-trials"><table><thead><tr><th>Profile</th><th>Trial</th><th>State</th><th>ROS duration</th><th>Recorded odometry</th><th>Pose validation</th><th>Contact evidence</th><th>Evidence</th></tr></thead><tbody>{current.trials.map(trial => <tr key={trial.id}>
        <td>{trial.profile}</td><td>{trial.repetition}</td><td>{trial.state}{trial.evidence && trial.evidence.outcome !== trial.state ? ` (${trial.evidence.outcome})` : ""}</td>
        <td>{quantity(measured(trial, "mission_ros_seconds"), "s")}</td><td>{quantity(measured(trial, "odom_path_metres"), "m")}</td>
        <td>{trial.evidence?.validation ? <details>
          <summary>{{ POSE_VERIFIED: "Pose verified", POSE_REJECTED: "Pose rejected", INCONCLUSIVE: "Inconclusive", MISSION_FAILED: "Mission failed" }[trial.evidence.validation.verdict] ?? "Unavailable"}</summary>
          <p>XY error: {quantity(trial.evidence.validation.xy_error_m ?? null, "m")} · yaw error: {quantity(trial.evidence.validation.yaw_error_rad ?? null, "rad")}</p>
          {trial.evidence.validation.reasons.map((reason, index) => <p key={index}>{reason}</p>)}
          {trial.evidence.validation.policy && <p>RobotOps tolerances: {trial.evidence.validation.policy.xy_tolerance_m} m / {trial.evidence.validation.policy.yaw_tolerance_rad} rad</p>}
          <p className="muted">Localized pose only. Contact evidence is reported separately.</p>
        </details> : "Unvalidated"}</td>
        <td><ContactEvidence evidence={trial.evidence?.collision} /></td>
        <td>{trial.evidence ? <details><summary>{trial.evidence.mission_run_id ?? trial.evidence.experiment_id}</summary><p>Runner manifest: {trial.evidence.manifest_path}</p></details> : "No recorded result"}</td>
      </tr>)}</tbody></table></div>
      <CampaignReports key={current.id} campaign={current} />
      <details className="campaign-history"><summary>Campaign events ({client.events.length} most recent loaded)</summary><ol>{client.events.map(event => <li key={event.sequence}>{new Date(event.at).toLocaleTimeString()} · {event.kind}</li>)}</ol></details>
    </>}
    <details className="campaign-history"><summary>Backend campaign history</summary><div>{client.history.map(item => <article key={item.id}>
      <button type="button" className="ghost" disabled={client.busy || owned} onClick={() => client.select(item.id)}>{new Date(item.created_at).toLocaleString()} · {item.definition.map_id} · {item.id.slice(0, 8)}</button><strong>{item.state}</strong><small>{item.trials.length} requested trials</small>
    </article>)}</div><div className="campaign-actions"><button type="button" disabled={client.busy || client.page === 0} onClick={() => client.changePage(client.page - 1)}>Newer campaigns</button><span>Page {client.page + 1}</span><button type="button" disabled={client.busy || client.history.length < 20} onClick={() => client.changePage(client.page + 1)}>Older campaigns</button></div></details>
    {legacy.length > 0 && <details className="campaign-history"><summary>Legacy browser campaigns ({legacy.length}) · approximate metrics</summary>
      <p className="muted">Preserved local history. These browser-estimated results are separate from backend recorded evidence; a saved running state may be incomplete.</p>
      <button type="button" className="secondary" onClick={() => downloadJson("robotops-legacy-browser-campaigns.json", legacy)}>Export legacy browser history</button>
      <div>{legacy.map(item => <article key={item.id}><span>{new Date(item.createdAt).toLocaleString()} · {item.mapId}</span><strong>{item.state}</strong><small>{item.trials.length} browser results</small></article>)}</div>
    </details>}
  </section>;
}
