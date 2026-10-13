import { PROFILE_LABELS, type WarehouseManifest } from "./data-warehouse";

// Context and disclosures come from the pinned manifest. The route note is the v1
// finding, checked against all six recorded trajectories (no sample inside an aisle).
export function WarehouseBanner({ manifest: m }: { manifest: WarehouseManifest }) {
  const crashed = m.teardown.status === "CRASHED_AFTER_EVIDENCE_FINALIZED";
  return <section className="benchmark-note" aria-label="Benchmark context and disclosures">
    <p><strong>Warehouse Navigation Benchmark v1 · {m.dataset_id}</strong> · {PROFILE_LABELS[m.conditions.profile]} · pair {m.benchmark.pair}, trial {m.benchmark.profile_trial} of 3</p>
    <ul className="benchmark-disclosures">
      <li>Exploratory: three trials per configuration. Not formally qualified — the earlier W3/W4 qualification process was not completed; the trials ran through the normal campaign path.</li>
      <li className="route-note">Route: the robot drove around the rack block on the perimeter and never entered the 1.2 m aisles, so this run does not show narrow-aisle navigation.</li>
      <li>Simulator ground truth was not recorded: positions and the final error come from the robot's own localization.</li>
      {crashed && <li className="teardown-disclosure"><strong>Disclosure:</strong> navigation succeeded and the evidence was finalized; Gazebo then crashed during post-run teardown. {m.teardown.detail} The original results shown here are unchanged. At the time, the campaign's cleanup check did not include process exit status.</li>}
    </ul>
  </section>;
}
