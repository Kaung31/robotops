import { secondsBetween } from "./data";
import type { ManifestV2 } from "./data-v2";
import { comparisonRows, coverageLabel, OBSERVATIONAL, showNumber, type Originals } from "./comparison";
export function ComparisonPanel({ originals, error }: { originals: Originals; error: string }) {
  const a = originals.N0, b = originals.N2;
  const category = (m: ManifestV2 | undefined, key: "ros_outcome" | "pose_verdict" | "contact_verdict") => m?.original_validation[key] ?? "Unavailable";
  const same = a && b ? [
    ["Robot", a.conditions.robot_model, b.conditions.robot_model], ["Environment", a.conditions.environment, b.conditions.environment],
    ["Map", a.conditions.map_id, b.conditions.map_id], ["Profile", a.conditions.profile, b.conditions.profile],
    ["Map image hash", a.conditions.map_image_sha256, b.conditions.map_image_sha256],
    ["Map YAML hash", a.conditions.map_yaml_sha256, b.conditions.map_yaml_sha256],
    ["Saved parameter hash", a.conditions.parameters_sha256, b.conditions.parameters_sha256],
    ["Ordered mission goals", JSON.stringify(a.conditions.waypoints), JSON.stringify(b.conditions.waypoints)],
  ] : [];
  return <section className="comparison-panel result-card" aria-labelledby="comparison-title">
    <div className="comparison-heading"><div><div className="section-kicker">ORIGINAL EVIDENCE · NO PROFILE RANKING</div><h2 id="comparison-title">Compare recorded experiments</h2></div><span className="comparison-badge">N0 ↔ N2 · navfn_rpp</span></div>
    <p className="comparison-subtitle">Observational repeated baselines using the same documented navigation configuration.</p>
    {error && <p role="alert">Comparison evidence unavailable: {error}. No estimated values or stale fallback.</p>}
    <table className="comparison-table"><caption className="sr-only">Original source measurements. Signed difference is N2 minus N0; each recording has its own ROS epoch.</caption><thead><tr><th scope="col">Original measurement</th><th scope="col">Baseline N0</th><th scope="col">Repeated Baseline N2</th><th scope="col">Δ N2 − N0</th></tr></thead><tbody>
      {comparisonRows(originals).map(row => <tr key={row.name}><th scope="row">{row.label}</th><td data-label="N0">{showNumber(row.n0, row.digits, row.unit)}</td><td data-label="N2">{showNumber(row.n2, row.digits, row.unit)}</td><td data-label="Δ N2 − N0">{showNumber(row.difference, row.digits, row.unit, true)}</td></tr>)}
      {([['Original ROS navigation outcome', 'ros_outcome'], ['Independent pose verification', 'pose_verdict'], ['Scoped contact observation', 'contact_verdict']] as const).map(([label, key]) => <tr key={key}><th scope="row">{label}</th><td data-label="N0">{category(a, key)}</td><td data-label="N2">{category(b, key)}</td><td data-label="Difference">Not numerical</td></tr>)}
      <tr><th scope="row">Recording coverage</th><td data-label="N0">{coverageLabel(a)}</td><td data-label="N2">{coverageLabel(b)}</td><td data-label="Difference">Different head/tail &amp; TF gaps</td></tr>
    </tbody></table>
    <p className="comparison-qualification">{OBSERVATIONAL}</p>
    <p className="card-footnote">Differences use exact source values; display is rounded. No winner score. No contact observed applies only to monitored geometry. Planning latency, obstacle clearance, physical accuracy and recovery count: unavailable.</p>
    <details><summary>Experimental conditions &amp; comparison limits</summary><div className="detail-body"><h3>Documented matching conditions</h3>{same.length ? <ul>{same.map(([label, n0, n2]) => <li key={label}>{label}: {n0 === n2 ? "matches" : "differs — do not treat as controlled"} · <code>{n0}</code>{n0 !== n2 && <> / <code>{n2}</code></>}</li>)}</ul> : <p>Unavailable until both pinned manifests are verified.</p>}
    <h3>Documented differences</h3><p>Separate campaigns and ROS epochs; N0 campaign has {a?.conditions.campaign_repetitions ?? "unavailable"} trial, N2 campaign has {b?.conditions.campaign_repetitions ?? "unavailable"} trials. Original config hashes include different campaign/trial context. Recording coverage differs; compare mission-relative elapsed time, never absolute ROS stamps or percentage progress.</p>
    {[a, b].map(m => m && <p key={m.dataset_id}>{m.dataset_id} missing mission head {secondsBetween(m.time.mission_start_ns, m.time.recorded_start_ns).toFixed(3)} s; tail {secondsBetween(m.time.recorded_end_ns, m.time.mission_end_ns).toFixed(3)} s. TF gaps: {m.coverage.gaps.filter(g => g.reason === "TF_UNAVAILABLE").map(g => `mission +${secondsBetween(m.time.mission_start_ns, g.start_ros_ns).toFixed(3)}–${secondsBetween(m.time.mission_start_ns, g.end_ros_ns).toFixed(3)} s`).join(", ")}. Measured runner start: <code>{JSON.stringify(m.conditions.measured_runner_start)}</code>; not proof of identical physical/localisation state.</p>)}
    <h3>Unknown or unverified</h3><p>Original software revisions and random seeds are unavailable. Exact localisation initialisation, host resources and historical world binary identity are unproven. No causal improvement, algorithm A/B or statistical reliability claim.</p><p>Saved ExecuteMission result snapshots are not Nav2 action streams. Missing motion is never reconstructed, and final report poses never fill recording gaps.</p></div></details>
  </section>;
}
