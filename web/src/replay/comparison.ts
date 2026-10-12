import { secondsBetween, type Metric } from "./data";
import type { DatasetId, ManifestV2 } from "./data-v2";
export type Originals = Partial<Record<DatasetId, ManifestV2>>;
export const OBSERVATIONAL = "Observational comparison — documented configurations match, but original software revisions, random seeds and exact localisation initialisation are not fully established.";
export const COMPARABLE = [
  { name: "mission_ros_seconds", label: "Mission duration", unit: "s", category: "metrics", digits: 3 },
  { name: "odom_path_metres", label: "Odometry path length", unit: "m", category: "metrics", digits: 4 },
  { name: "xy_error_m", label: "Final XY position error", unit: "m", category: "validation", digits: 4 },
  { name: "yaw_error_rad", label: "Final yaw error", unit: "rad", category: "validation", digits: 4 },
] as const;
export function measured(metrics: readonly Metric[] | undefined, check: typeof COMPARABLE[number]): number | null {
  const matches = metrics?.filter(m => m.name === check.name) ?? [], m = matches.length === 1 ? matches[0] : undefined;
  return m && m.unit === check.unit && m.quality === "ORIGINAL_VERIFIED" && m.source_ref === "report" && m.pointer === `/campaign/trials/0/evidence/${check.category}/${check.name}` && typeof m.value === "number" && Number.isFinite(m.value) && m.value >= 0 ? m.value : null;
}
export function comparisonRows(originals: Originals) {
  return COMPARABLE.map(check => {
    const n0 = measured(originals.N0?.metrics, check), n2 = measured(originals.N2?.metrics, check);
    return { ...check, n0, n2, difference: n0 === null || n2 === null ? null : n2 - n0 };
  });
}
export function showNumber(value: number | null, digits: number, unit: string, signed = false): string {
  if (value === null || !Number.isFinite(value)) return "Unavailable";
  return `${signed && value > 0 ? "+" : ""}${value.toFixed(digits)} ${unit}`;
}
export function coverageLabel(m?: ManifestV2): string {
  if (!m) return "Unavailable";
  return `${secondsBetween(m.time.recorded_start_ns, m.time.recorded_end_ns).toFixed(3)} s recorded · partial`;
}
