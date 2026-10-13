import { COMPARABLE, showNumber } from "./comparison";
import { PROFILE_LABELS, WAREHOUSE_IDS, type WarehouseId } from "./data-warehouse";
import { differenceOfMeans, EXPLORATORY, PROFILES, profileSummary, trialRows, verdictCounts, type Summary, type WarehouseOriginals } from "./warehouse-comparison";

const TEARDOWN = { NO_CHILD_FAILURE_LOGGED: "Clean", CRASHED_AFTER_EVIDENCE_FINALIZED: "Crashed after evidence finalized" } as const;
function summary(s: Summary, digits: number, unit: string): string {
  return s.mean === null ? `Unavailable (${s.n}/3 verified)` : `${showNumber(s.mean, digits, unit)} (${s.min!.toFixed(digits)}–${s.max!.toFixed(digits)})`;
}
export function WarehouseComparisonPanel({ originals, error, selected }: { originals: WarehouseOriginals; error: string; selected: WarehouseId | null }) {
  const rows = trialRows(originals);
  const loaded = WAREHOUSE_IDS.map(id => originals[id]).filter(m => m !== undefined);
  const same = (pick: (m: NonNullable<typeof loaded[number]>) => string) => loaded.length === WAREHOUSE_IDS.length && new Set(loaded.map(pick)).size === 1;
  const crashed = rows.filter(r => r.teardown === "CRASHED_AFTER_EVIDENCE_FINALIZED").map(r => r.id);
  return <section className="comparison-panel result-card" aria-labelledby="warehouse-comparison-title">
    <div className="comparison-heading"><div><div className="section-kicker">ORIGINAL EVIDENCE · NO PROFILE RANKING</div><h2 id="warehouse-comparison-title">Compare the six warehouse trials</h2></div><span className="comparison-badge">W01–W06 · 2 configurations × 3</span></div>
    <p className="comparison-subtitle">Warehouse Navigation Benchmark v1 · exploratory · ran through the normal backend campaign path · not qualified.</p>
    <p className="key-finding"><strong>Key finding — no aisle driving:</strong> the goals sit at both ends of the two 1.2 m aisles between the racks, but in all six trials both configurations drove around the rack block on the perimeter and never entered an aisle. This benchmark does not demonstrate narrow-aisle navigation.</p>
    {error && <p role="alert">Comparison evidence unavailable: {error}. No estimated values or stale fallback.</p>}
    <table className="comparison-table warehouse-trials"><caption className="sr-only">Original source measurements and verdicts for each trial, in run order.</caption><thead><tr><th scope="col">Trial</th><th scope="col">Configuration</th>{COMPARABLE.map(c => <th scope="col" key={c.name}>{c.label}</th>)}<th scope="col">Pose verification</th><th scope="col">Scoped contact</th><th scope="col">Stack teardown</th></tr></thead><tbody>
      {rows.map(row => <tr key={row.id} className={row.id === selected ? "selected-trial" : undefined} aria-current={row.id === selected ? "true" : undefined}><th scope="row">{row.id}</th><td data-label="Configuration">{PROFILE_LABELS[row.profile]}</td>
        {COMPARABLE.map(c => <td key={c.name} data-label={c.label}>{showNumber(row.values[c.name], c.digits, c.unit)}</td>)}
        <td data-label="Pose verification">{row.pose ?? "Unavailable"}</td><td data-label="Scoped contact">{row.contact ?? "Unavailable"}</td><td data-label="Stack teardown">{row.teardown ? TEARDOWN[row.teardown] : "Unavailable"}</td></tr>)}
    </tbody></table>
    <h3>Per-configuration summary</h3>
    <table className="comparison-table"><caption className="sr-only">Mean and range of the three original values per configuration, and the difference of means (Smac 2D + DWB minus NavFn + RPP). Descriptive only.</caption><thead><tr><th scope="col">Original measurement</th>{PROFILES.map(p => <th scope="col" key={p}>{PROFILE_LABELS[p]} · mean (range)</th>)}<th scope="col">Δ of means (Smac − NavFn)</th></tr></thead><tbody>
      {COMPARABLE.map(c => <tr key={c.name}><th scope="row">{c.label}</th>{PROFILES.map(p => <td key={p} data-label={PROFILE_LABELS[p]}>{summary(profileSummary(rows, p, c.name), c.digits, c.unit)}</td>)}<td data-label="Δ of means">{showNumber(differenceOfMeans(rows, c.name), c.digits, c.unit, true)}</td></tr>)}
      {(["pose", "contact"] as const).map(key => <tr key={key}><th scope="row">{key === "pose" ? "Independent pose verification" : "Scoped contact observation"}</th>{PROFILES.map(p => <td key={p} data-label={PROFILE_LABELS[p]}>{verdictCounts(rows, p, key)}</td>)}<td data-label="Δ of means">Not numerical</td></tr>)}
    </tbody></table>
    <p className="comparison-qualification">{EXPLORATORY}</p>
    <p className="card-footnote">Every value is the exact original report value; summaries are computed in your browser and displayed rounded. A summary is shown only when all three trials of a configuration are verified. {crashed.length ? `${crashed.join(", ")}: the simulator crashed while the stack was shutting down, after the trial's evidence had been finalized and hashed. Its recorded results are unchanged and disclosed here.` : ""}</p>
    <details><summary>Experimental conditions &amp; comparison limits</summary><div className="detail-body"><h3>Documented matching conditions</h3>{loaded.length === WAREHOUSE_IDS.length ? <ul>
      <li>World and map: {same(m => `${m.conditions.environment}/${m.conditions.map_id}`) ? "match" : "differ — do not treat as controlled"} · <code>{loaded[0]!.conditions.environment}</code></li>
      <li>Map image and YAML hashes: {same(m => m.conditions.map_image_sha256 + m.conditions.map_yaml_sha256) ? "match" : "differ"}</li>
      <li>Ordered five-goal mission: {same(m => JSON.stringify(m.conditions.waypoints)) ? "matches" : "differs"} · requested start {same(m => JSON.stringify(m.conditions.requested_start)) ? "matches" : "differs"}</li>
      <li>Frozen matrix hash: {same(m => m.benchmark.matrix_sha256) ? "matches" : "differs"} · <code>{loaded[0]!.benchmark.matrix_sha256}</code></li>
      {PROFILES.map(p => { const ofProfile = loaded.filter(m => m.conditions.profile === p); return <li key={p}>{PROFILE_LABELS[p]} saved parameters: {new Set(ofProfile.map(m => m.conditions.parameters_sha256)).size === 1 ? "identical across its trials" : "differ"} · <code>{ofProfile[0]?.conditions.parameters_sha256}</code></li>; })}
    </ul> : <p>Unavailable until all six pinned manifests are verified.</p>}
    <h3>Unknown or unverified</h3><p>Original software revisions were not recorded (the runs used one local checkout with uncommitted changes). Random seeds, exact localisation initialisation, host load and the historical install binaries are not established. Final pose is localized TF, not simulator ground truth. Planning latency, obstacle clearance and recovery count were not recorded.</p>
    <p>Each recording covers the whole navigation window; elapsed times are mission-relative, never compared as absolute ROS stamps.</p></div></details>
  </section>;
}
