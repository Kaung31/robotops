import { visitorDuration, type Metric } from "./data";

export type CheckId = "duration" | "xy" | "yaw";
export type CheckResult = { outcome: "PASS" | "FAIL" | "UNKNOWN"; reason: string };
export const CHECKS = [
  { id: "duration", label: "Mission duration", unit: "s", unitName: "seconds", metric: "mission_ros_seconds", pointer: "/campaign/trials/0/evidence/metrics/mission_ros_seconds", initial: "25" },
  { id: "xy", label: "Final XY error", unit: "m", unitName: "metres", metric: "xy_error_m", pointer: "/campaign/trials/0/evidence/validation/xy_error_m", initial: "0.2" },
  { id: "yaw", label: "Final yaw error", unit: "rad", unitName: "radians", metric: "yaw_error_rad", pointer: "/campaign/trials/0/evidence/validation/yaw_error_rad", initial: "0.1" },
] as const;

// Only qualified source measurements; never replay poses, graphics or report verdicts.
export function visitorCheck(id: CheckId, metrics: readonly Metric[], maximum: string, trusted: boolean): CheckResult {
  const check = CHECKS.find(c => c.id === id)!;
  const threshold = maximum.trim() === "" ? NaN : Number(maximum);
  // Decimal/scientific input only; reject JS-specific hex/binary coercions.
  if (!/^[+]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(maximum.trim()) || !Number.isFinite(threshold) || threshold < 0) {
    return { outcome: "UNKNOWN", reason: `Enter a finite nonnegative maximum in ${check.unitName}.` };
  }
  const matches = metrics.filter(m => m.name === check.metric);
  const metric = matches.length === 1 ? matches[0] : undefined;
  if (id === "duration") return visitorDuration(metric, maximum, trusted);
  if (!trusted || !metric || metric.unit !== check.unit || metric.quality !== "ORIGINAL_VERIFIED" || metric.source_ref !== "report" || metric.pointer !== check.pointer || typeof metric.value !== "number" || !Number.isFinite(metric.value) || metric.value < 0) {
    return { outcome: "UNKNOWN", reason: `Qualified original ${check.label.toLowerCase()} evidence unavailable.` };
  }
  return { outcome: metric.value <= threshold ? "PASS" : "FAIL", reason: `Original ${check.unit} ≤ maximum (equality passes).` };
}
