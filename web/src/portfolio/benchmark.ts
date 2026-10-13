// Warehouse Navigation Benchmark v1 values shown on the homepage, from the six
// original campaign reports (docs/WAREHOUSE_BENCHMARK.md) at display precision.
// Tests re-derive every value from the pinned W01-W06 manifests when present.
export type Profile = "navfn_rpp" | "smac_dwb";
export const CONFIGURATIONS: Record<Profile, { name: string; short: string }> = {
  navfn_rpp: { name: "NavFn + Regulated Pure Pursuit", short: "NavFn + RPP" },
  smac_dwb: { name: "Smac 2D + DWB", short: "Smac 2D + DWB" },
};
// Run order AB/BA/AB. seconds: mission ROS time; yaw: final heading error (rad); xy: final position error (m).
export const TRIALS: readonly { id: string; profile: Profile; seconds: number; yaw: number; xy: number }[] = [
  { id: "W01", profile: "navfn_rpp", seconds: 137.372, yaw: 0.0593, xy: 0.1513 },
  { id: "W02", profile: "smac_dwb", seconds: 132.936, yaw: 0.1938, xy: 0.1310 },
  { id: "W03", profile: "smac_dwb", seconds: 132.080, yaw: 0.1908, xy: 0.1192 },
  { id: "W04", profile: "navfn_rpp", seconds: 137.861, yaw: 0.0531, xy: 0.1404 },
  { id: "W05", profile: "navfn_rpp", seconds: 137.780, yaw: 0.0546, xy: 0.1343 },
  { id: "W06", profile: "smac_dwb", seconds: 133.317, yaw: 0.1923, xy: 0.1505 },
];
// Means of the exact report values (not of the rounded values above).
export const SUMMARY: Record<Profile, { seconds: number; secondsMin: number; secondsMax: number; yawRad: number; yawDeg: number; xy: number; path: number }> = {
  navfn_rpp: { seconds: 137.67, secondsMin: 137.37, secondsMax: 137.86, yawRad: 0.056, yawDeg: 3.2, xy: 0.142, path: 28.09 },
  smac_dwb: { seconds: 132.78, secondsMin: 132.08, secondsMax: 133.32, yawRad: 0.192, yawDeg: 11.0, xy: 0.134, path: 27.98 },
};
export const HEADLINE = { trials: 6, goals: 5, faster: 4.9, fasterPercent: 3.6, navfnSpread: 0.49, smacSpread: 1.24 } as const;
// Validation limits and the Nav2 goal-checker yaw tolerance used by all six trials.
export const LIMITS = { xy: 0.2, yaw: 0.25, nav2Yaw: 0.2 } as const;
