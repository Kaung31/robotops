import { COMPARABLE, measured } from "./comparison";
import { PROFILE_LABELS, WAREHOUSE, WAREHOUSE_IDS, type Profile, type WarehouseId, type WarehouseManifest } from "./data-warehouse";

export type WarehouseOriginals = Partial<Record<WarehouseId, WarehouseManifest>>;
export const PROFILES = Object.keys(PROFILE_LABELS) as Profile[];
export const EXPLORATORY = "Exploratory benchmark — three trials per configuration in a frozen AB/BA/AB order on one simulated world and start. Each configuration bundles a planner with a controller. Descriptive only: no statistical significance, no algorithm ranking, no winner.";
type Metric = typeof COMPARABLE[number]["name"];
export interface TrialRow {
  id: WarehouseId; profile: Profile; available: boolean;
  values: Record<Metric, number | null>;
  pose: string | null; contact: string | null; teardown: WarehouseManifest["teardown"]["status"] | null;
}
export interface Summary { mean: number | null; min: number | null; max: number | null; n: number }

// Exact original values only; graphics, playback samples and visitor inputs never enter.
export function trialRows(originals: WarehouseOriginals): TrialRow[] {
  return WAREHOUSE_IDS.map(id => {
    const m = originals[id];
    const values = Object.fromEntries(COMPARABLE.map(check => [check.name, measured(m?.metrics, check)])) as Record<Metric, number | null>;
    return { id, profile: WAREHOUSE[id].profile, available: !!m, values, pose: m?.original_validation.pose_verdict ?? null, contact: m?.original_validation.contact_verdict ?? null, teardown: m?.teardown.status ?? null };
  });
}
// A configuration summary needs every planned trial; a partial mean would silently change n.
export function profileSummary(rows: TrialRow[], profile: Profile, metric: Metric): Summary {
  const planned = rows.filter(r => r.profile === profile), values = planned.map(r => r.values[metric]);
  if (!planned.length || values.some(v => v === null)) return { mean: null, min: null, max: null, n: values.filter(v => v !== null).length };
  const exact = values as number[];
  return { mean: exact.reduce((a, b) => a + b, 0) / exact.length, min: Math.min(...exact), max: Math.max(...exact), n: exact.length };
}
export function differenceOfMeans(rows: TrialRow[], metric: Metric): number | null {
  const a = profileSummary(rows, "navfn_rpp", metric).mean, b = profileSummary(rows, "smac_dwb", metric).mean;
  return a === null || b === null ? null : b - a;
}
export function verdictCounts(rows: TrialRow[], profile: Profile, key: "pose" | "contact"): string {
  const planned = rows.filter(r => r.profile === profile);
  if (planned.some(r => r[key] === null)) return "Unavailable";
  const counts = new Map<string, number>();
  for (const r of planned) counts.set(r[key]!, (counts.get(r[key]!) ?? 0) + 1);
  return [...counts].map(([verdict, n]) => `${verdict} ${n}/${planned.length}`).join(" · ");
}
