import type { Dataset } from "./data";

// Formatting and coverage decoration only: never changes engine time/pose/quality.
export function formatTime(seconds: number): string {
  const tenths = Math.round(seconds * 10);
  return `${Math.floor(tenths / 600).toString().padStart(2, "0")}:${(Math.floor(tenths / 10) % 60).toString().padStart(2, "0")}.${tenths % 10}`;
}
export function initialPreviewTime(data: Dataset): number {
  const supported = data.poses.filter(p => p.transform && p.quality === "SUPPORTED_TF");
  const sample = supported[Math.floor(supported.length / 2)];
  return sample ? Number(BigInt(sample.ros_ns) - BigInt(data.manifest.time.mission_start_ns)) / 1e9 : 0;
}
export function coverageBands(data: Dataset) {
  const m = data.manifest, start = BigInt(m.time.mission_start_ns), end = BigInt(m.time.mission_end_ns);
  const intervals: [bigint, bigint][] = [];
  for (let i = 1; i < data.poses.length; i++) {
    const a = data.poses[i - 1], b = data.poses[i];
    const segment = m.segments.find(s => s.id === a.segment_id);
    if (a.transform && b.transform && a.quality === "SUPPORTED_TF" && b.quality === "SUPPORTED_TF" && a.segment_id === b.segment_id && a.frame === b.frame && segment && BigInt(b.ros_ns) - BigInt(a.ros_ns) <= BigInt(segment.interpolate_within_max_gap_ns)) intervals.push([BigInt(a.ros_ns), BigInt(b.ros_ns)]);
  }
  const recordedStart = BigInt(m.time.recorded_start_ns), recordedEnd = BigInt(m.time.recorded_end_ns);
  const boundaries = [...new Set([start, end, recordedStart, recordedEnd, ...intervals.flat()])].filter(v => v >= start && v <= end).sort((a, b) => a < b ? -1 : a > b ? 1 : 0);
  const bands: { start: number; end: number; kind: "pose" | "recorded" | "missing" }[] = [];
  for (let i = 1; i < boundaries.length; i++) {
    const a = boundaries[i - 1], b = boundaries[i], mid = (a + b) / 2n;
    const kind = intervals.some(([s, e]) => mid >= s && mid <= e) ? "pose" : mid >= recordedStart && mid <= recordedEnd ? "recorded" : "missing";
    const previous = bands.at(-1);
    if (previous?.kind === kind) previous.end = Number(b - start) / Number(end - start) * 100;
    else bands.push({ start: Number(a - start) / Number(end - start) * 100, end: Number(b - start) / Number(end - start) * 100, kind });
  }
  return bands;
}
// Seconds since the previous frame, captured when the frame runs. React may
// evaluate a state updater after the next frame's timestamp has been stored, so
// the updater must receive this value rather than read a shared variable.
export function frameClock(start: number): (now: number) => number {
  let previous = start;
  return now => { const elapsed = Math.max(0, now - previous) / 1000; previous = now; return elapsed; };
}
