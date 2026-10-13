import { PROFILE_LABELS, type WarehouseManifest } from "./data-warehouse";

// Context and disclosures come from the pinned manifest. The route note is the v1
// finding, checked against all six recorded trajectories (no sample inside an aisle).
export function WarehouseBanner({ manifest: m }: { manifest: WarehouseManifest }) {
  const crashed = m.teardown.status === "CRASHED_AFTER_EVIDENCE_FINALIZED";
  return <section className="benchmark-note" aria-label="Benchmark context">
    <p><strong>Warehouse Navigation Benchmark v1 · {m.dataset_id}</strong> · {PROFILE_LABELS[m.conditions.profile]} · pair {m.benchmark.pair}, trial {m.benchmark.profile_trial} of 3 · exploratory, not qualified · normal backend campaign path</p>
    <p className="route-note">Route: around the rack block on the perimeter — the robot never enters the 1.2 m aisles, so this run does not show narrow-aisle navigation.</p>
    {crashed && <p className="teardown-disclosure"><strong>Disclosure:</strong> {m.teardown.detail} The original results shown here are unchanged. At the time, the campaign's cleanup check did not include process exit status.</p>}
  </section>;
}
