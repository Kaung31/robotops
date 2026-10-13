import { COMPARABLE, showNumber } from "./comparison";
import { PROFILE_LABELS, PROFILE_SHORT, WAREHOUSE_IDS, type WarehouseId } from "./data-warehouse";
import { differenceOfMeans, EXPLORATORY, PROFILES, profileSummary, separated, trialRows, verdictCounts, type Summary, type TrialRow, type WarehouseOriginals } from "./warehouse-comparison";
import { StripChart, type StripGroup } from "../site/StripChart";

const TEARDOWN = { NO_CHILD_FAILURE_LOGGED: "Clean", CRASHED_AFTER_EVIDENCE_FINALIZED: "Crashed after evidence finalized" } as const;
const degrees = (rad: number) => (rad * 180 / Math.PI).toFixed(1);
function summary(s: Summary, digits: number, unit: string): string {
  return s.mean === null ? `Unavailable (${s.n}/3 verified)` : `${showNumber(s.mean, digits, unit)} (${s.min!.toFixed(digits)}–${s.max!.toFixed(digits)})`;
}
const range = (s: Summary, digits: number, unit: string) => s.min === null ? "unavailable" : `${s.min.toFixed(digits)}–${s.max!.toFixed(digits)} ${unit}`;

// Section 2: what happened in the six trials, straight from the verified manifests.
export function WarehouseResults({ originals, error, selected, onReplay }: { originals: WarehouseOriginals; error: string; selected: WarehouseId | null; onReplay?: (id: WarehouseId) => void }) {
  const rows = trialRows(originals), complete = rows.every(r => r.available);
  const count = (ok: (r: TrialRow) => boolean) => complete ? `${rows.filter(ok).length}/${rows.length}` : "–";
  const goals = complete && rows.every(r => r.outcome === "succeeded") && new Set(rows.map(r => r.goals)).size === 1 ? rows[0].goals : null;
  const time = (p: typeof PROFILES[number]) => profileSummary(rows, p, "mission_ros_seconds");
  const yaw = (p: typeof PROFILES[number]) => profileSummary(rows, p, "yaw_error_rad");
  const xy = (p: typeof PROFILES[number]) => profileSummary(rows, p, "xy_error_m");
  const faster = differenceOfMeans(rows, "mission_ros_seconds"), navfnTime = time("navfn_rpp").mean;
  const findings = [
    separated(rows, "smac_dwb", "navfn_rpp", "mission_ros_seconds") && faster !== null && navfnTime !== null && <li key="time"><strong>Smac 2D + DWB finished every trial sooner:</strong> {(-faster).toFixed(1)} s ({(-faster / navfnTime * 100).toFixed(1)}%) faster on average.</li>,
    separated(rows, "navfn_rpp", "smac_dwb", "yaw_error_rad") && yaw("navfn_rpp").mean !== null && <li key="yaw"><strong>NavFn + RPP stopped closer to the goal heading in every trial:</strong> mean {degrees(yaw("navfn_rpp").mean!)}° against {degrees(yaw("smac_dwb").mean!)}°.</li>,
    complete && !separated(rows, "navfn_rpp", "smac_dwb", "xy_error_m") && !separated(rows, "smac_dwb", "navfn_rpp", "xy_error_m") && <li key="xy"><strong>Final position errors overlap:</strong> {range(xy("navfn_rpp"), 3, "m")} for NavFn + RPP and {range(xy("smac_dwb"), 3, "m")} for Smac 2D + DWB.</li>,
  ].filter(Boolean);
  const crashed = rows.filter(r => r.teardown === "CRASHED_AFTER_EVIDENCE_FINALIZED").map(r => r.id);
  return <div className="warehouse-results">
    {error && <p className="evidence-error" role="alert">Comparison evidence unavailable: {error}. No estimated values or stale fallback.</p>}
    <ul className="result-stats" aria-label="Outcome counts across the six trials">
      <li><strong>{count(r => r.outcome === "succeeded")}</strong><span>navigation succeeded</span></li>
      <li><strong>{goals === null ? "–" : `${goals}/${goals}`}</strong><span>goals reached in every trial</span></li>
      <li><strong>{count(r => r.pose === "POSE_VERIFIED")}</strong><span>final pose verified</span></li>
      <li><strong>{count(r => r.contact === "NO_CONTACT_OBSERVED")}</strong><span>no contact observed (monitored geometry)</span></li>
    </ul>
    <div className="config-summary">{PROFILES.map(p => <article key={p} className={`config-summary-card ${p}`}>
      <h3><i className={`swatch ${p}`} />{PROFILE_LABELS[p]}</h3>
      <dl>
        <div><dt>Mean mission time</dt><dd><strong>{time(p).mean === null ? "Unavailable" : `${time(p).mean!.toFixed(2)} s`}</strong><span>range {range(time(p), 2, "s")}</span></dd></div>
        <div><dt>Mean final heading error</dt><dd><strong>{yaw(p).mean === null ? "Unavailable" : `${degrees(yaw(p).mean!)}°`}</strong><span>{yaw(p).mean === null ? "" : `${yaw(p).mean!.toFixed(4)} rad`}</span></dd></div>
        <div><dt>Mean final position error</dt><dd><strong>{xy(p).mean === null ? "Unavailable" : `${xy(p).mean!.toFixed(3)} m`}</strong><span>range {range(xy(p), 3, "m")}</span></dd></div>
      </dl>
    </article>)}</div>
    {findings.length > 0 && <ul className="lab-findings">{findings}</ul>}
    <p className="key-finding"><strong>Key finding — no aisle driving:</strong> the goals sit at both ends of the two 1.2 m aisles between the racks, but in all six trials both configurations drove around the rack block on the perimeter and never entered an aisle. This benchmark does not demonstrate narrow-aisle navigation.</p>
    <h3 className="table-title" id="six-trials-title">All six trials, in run order</h3>
    <table className="comparison-table warehouse-trials" aria-labelledby="six-trials-title"><caption className="sr-only">Original source measurements and verdicts for each trial, in run order. Replay buttons load that trial into the player.</caption><thead><tr><th scope="col">Trial</th><th scope="col">Configuration</th>{COMPARABLE.map(c => <th scope="col" key={c.name}>{c.label}</th>)}<th scope="col">Pose verification</th><th scope="col">Scoped contact</th><th scope="col">Stack teardown</th>{onReplay && <th scope="col"><span className="sr-only">Replay</span></th>}</tr></thead><tbody>
      {rows.map(row => <tr key={row.id} className={row.id === selected ? "selected-trial" : undefined} aria-current={row.id === selected ? "true" : undefined}><th scope="row">{row.id}</th><td data-label="Configuration"><i className={`swatch ${row.profile}`} />{PROFILE_LABELS[row.profile]}</td>
        {COMPARABLE.map(c => <td key={c.name} data-label={c.label}>{showNumber(row.values[c.name], c.digits, c.unit)}</td>)}
        <td data-label="Pose verification">{row.pose ?? "Unavailable"}</td><td data-label="Scoped contact">{row.contact ?? "Unavailable"}</td><td data-label="Stack teardown">{row.teardown ? TEARDOWN[row.teardown] : "Unavailable"}</td>
        {onReplay && <td className="replay-cell"><button type="button" className="replay-button" onClick={() => onReplay(row.id)} aria-label={`Replay ${row.id} in the player`}>{row.id === selected ? "Showing" : "Replay"}</button></td>}</tr>)}
    </tbody></table>
    <p className="card-footnote">Every value is the exact original report value, displayed rounded. Counts and summaries are computed in your browser from the six verified manifests. {crashed.length ? `${crashed.join(", ")}: the simulator crashed while the stack was shutting down, after the trial's evidence had been finalized and hashed. Its recorded results are unchanged and disclosed here.` : ""}</p>
  </div>;
}

// Section 4: the two configurations side by side. Descriptive only.
export function WarehouseComparison({ originals, error }: { originals: WarehouseOriginals; error: string }) {
  const rows = trialRows(originals);
  const loaded = WAREHOUSE_IDS.map(id => originals[id]).filter(m => m !== undefined);
  const complete = loaded.length === WAREHOUSE_IDS.length;
  const same = (pick: (m: NonNullable<typeof loaded[number]>) => string) => complete && new Set(loaded.map(pick)).size === 1;
  // Reference lines only when every manifest records the same original pose policy.
  const policy = same(m => JSON.stringify([m.original_validation.pose_policy?.xy_tolerance_m, m.original_validation.pose_policy?.yaw_tolerance_rad])) ? loaded[0]!.original_validation.pose_policy ?? null : null;
  const groups = (metric: typeof COMPARABLE[number]["name"]): StripGroup[] => PROFILES.map(p => ({ id: p, label: PROFILE_SHORT[p], values: rows.filter(r => r.profile === p).map(r => ({ id: r.id, value: r.values[metric]! })) }));
  const times = rows.map(r => r.values.mission_ros_seconds), verified = complete && rows.every(r => COMPARABLE.every(c => r.values[c.name] !== null));
  const low = verified ? Math.floor(Math.min(...times as number[])) - 1 : 0, high = verified ? Math.ceil(Math.max(...times as number[])) + 1 : 1;
  const step = Math.max(1, Math.ceil((high - low) / 4)), ticks = Array.from({ length: Math.floor((high - low) / step) + 1 }, (_, i) => low + i * step);
  return <div className="warehouse-comparison comparison-panel">
    {error && <p className="evidence-error" role="alert">Comparison evidence unavailable: {error}. No estimated values or stale fallback.</p>}
    {verified ? <div className="lab-charts">
      <StripChart title="Mission time, seconds" note={`Axis ${low}–${high} s`} unit="s" digits={2} min={low} max={high} ticks={ticks} tickDigits={0} groups={groups("mission_ros_seconds")} />
      <StripChart title="Final position error, metres" note="Localized pose against the goal" unit="m" digits={3} min={0} max={0.25} ticks={[0, 0.05, 0.1, 0.15, 0.2, 0.25]} tickDigits={2} groups={groups("xy_error_m")} references={policy ? [{ value: policy.xy_tolerance_m, label: "Validation limit (original policy)" }] : []} />
      <StripChart title="Final heading error, radians" note="Localized pose against the goal" unit="rad" digits={3} min={0} max={0.3} ticks={[0, 0.1, 0.2, 0.3]} tickDigits={1} groups={groups("yaw_error_rad")} references={policy ? [{ value: policy.yaw_tolerance_rad, label: "Validation limit (original policy)" }] : []} />
    </div> : <p className="evidence-unavailable">Charts are unavailable until all six pinned manifests are verified.</p>}
    <h3 className="table-title" id="summary-title">Per-configuration summary</h3>
    <table className="comparison-table" aria-labelledby="summary-title"><caption className="sr-only">Mean and range of the three original values per configuration, and the difference of means (Smac 2D + DWB minus NavFn + RPP). Descriptive only.</caption><thead><tr><th scope="col">Original measurement</th>{PROFILES.map(p => <th scope="col" key={p}>{PROFILE_LABELS[p]} · mean (range)</th>)}<th scope="col">Δ of means (Smac − NavFn)</th></tr></thead><tbody>
      {COMPARABLE.map(c => <tr key={c.name}><th scope="row">{c.label}</th>{PROFILES.map(p => <td key={p} data-label={PROFILE_LABELS[p]}>{summary(profileSummary(rows, p, c.name), c.digits, c.unit)}</td>)}<td data-label="Δ of means">{showNumber(differenceOfMeans(rows, c.name), c.digits, c.unit, true)}</td></tr>)}
      {(["pose", "contact"] as const).map(key => <tr key={key}><th scope="row">{key === "pose" ? "Independent pose verification" : "Scoped contact observation"}</th>{PROFILES.map(p => <td key={p} data-label={PROFILE_LABELS[p]}>{verdictCounts(rows, p, key)}</td>)}<td data-label="Δ of means">Not numerical</td></tr>)}
    </tbody></table>
    <p className="comparison-qualification">{EXPLORATORY}</p>
    <p className="card-footnote">Means and differences use exact source values and are displayed rounded. A summary is shown only when all three trials of a configuration are verified.</p>
    <details><summary>Experimental conditions &amp; comparison limits</summary><div className="detail-body"><h3>Documented matching conditions</h3>{complete ? <ul>
      <li>World and map: {same(m => `${m.conditions.environment}/${m.conditions.map_id}`) ? "match" : "differ — do not treat as controlled"} · <code>{loaded[0]!.conditions.environment}</code></li>
      <li>Map image and YAML hashes: {same(m => m.conditions.map_image_sha256 + m.conditions.map_yaml_sha256) ? "match" : "differ"}</li>
      <li>Ordered five-goal mission: {same(m => JSON.stringify(m.conditions.waypoints)) ? "matches" : "differs"} · requested start {same(m => JSON.stringify(m.conditions.requested_start)) ? "matches" : "differs"}</li>
      <li>Frozen matrix hash: {same(m => m.benchmark.matrix_sha256) ? "matches" : "differs"} · <code>{loaded[0]!.benchmark.matrix_sha256}</code></li>
      {PROFILES.map(p => { const ofProfile = loaded.filter(m => m.conditions.profile === p); return <li key={p}>{PROFILE_LABELS[p]} saved parameters: {new Set(ofProfile.map(m => m.conditions.parameters_sha256)).size === 1 ? "identical across its trials" : "differ"} · <code>{ofProfile[0]?.conditions.parameters_sha256}</code></li>; })}
    </ul> : <p>Unavailable until all six pinned manifests are verified.</p>}
    <h3>Unknown or unverified</h3><p>Original software revisions were not recorded (the runs used one local checkout with uncommitted changes). Random seeds, exact localisation initialisation, host load and the historical install binaries are not established. Final pose is localized TF, not simulator ground truth. Planning latency, obstacle clearance and recovery count were not recorded.</p>
    <p>Each recording covers the whole navigation window; elapsed times are mission-relative, never compared as absolute ROS stamps.</p></div></details>
  </div>;
}
