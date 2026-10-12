import schemas from "./schema-v1.json";

export const N0_HASH = "755424dae361089465281af6706e51852ed1aa221cffe9504434b0fb6419aab4";
export type Vec3 = [number, number, number];
export type Quat = [number, number, number, number];
export interface Transform { position: Vec3; quaternion: Quat }
export interface Pose { ros_ns: string; offset_us: number; segment_id: string | null; frame: "map"; transform: Transform | null; quality: string }
export interface Scan { ros_ns: string; offset_us: number; segment_id: string | null; map_base: Transform | null; base_lidar: Transform | null; map_quality: string; angle_min_rad: number; angle_increment_rad: number; selected_indices: number[]; ranges_m: (number | null)[]; validity: string[] }
export interface Metric { name: string; value: number | null; unit: string; quality: string; source_ref: string; pointer: string }
export interface Manifest {
  schema_version: 1 | 2; dataset_id: string; publication_review: string;
  time: { mission_start_ns: string; mission_end_ns: string; recorded_start_ns: string; recorded_end_ns: string; offset_origin_ns: string; domain: string };
  scene: { width: number; height: number; resolution_m: number; origin: Vec3; free_threshold: number; occupied_threshold: number; negate: number; map_asset: string };
  assets: { path: string; bytes: number; sha256: string; kind: string; schema_version: number }[];
  segments: { id: string; start_ros_ns: string; end_ros_ns: string; interpolate_within_max_gap_ns: number; epoch: number; frame: string }[];
  coverage: { full_mission_replay: boolean; gaps: { start_ros_ns: string; end_ros_ns: string; reason: string }[]; missing_channels: string[] };
  metrics: Metric[]; sources: { id: string; sha256: string; integrity: string; scope: string }[];
  original_validation: { ros_outcome: string; pose_verdict: string; contact_verdict: string; contact_scope: string; contact_frame_count: number; final_pose_ros_ns: string; final_localized_pose: { x: number; y: number; yaw: number }; universal_collision_freedom_assessable: boolean };
  limitations: string[];
}
export interface Dataset { manifest: Manifest; poses: Pose[]; scans: Scan[]; pixels: Uint8Array; trusted: boolean }
// This deliberately implements only the keywords present in the checked-in P2
// schema. It is not a general JSON Schema engine; schema parity is regression-tested.
type Schema = { $ref?: string; $defs?: Record<string, Schema>; anyOf?: Schema[]; type?: string; const?: unknown; enum?: unknown[]; properties?: Record<string, Schema>; required?: string[]; additionalProperties?: boolean; items?: Schema; minItems?: number; maxItems?: number; pattern?: string; minimum?: number; maximum?: number; exclusiveMinimum?: number; exclusiveMaximum?: number };
export function validate(value: unknown, schema: Schema, root = schema): void {
  const bad = () => { throw Error("Unsupported or malformed v1 dataset"); };
  if (schema.$ref) return validate(value, root.$defs?.[schema.$ref.split("/").at(-1)!] ?? bad(), root);
  if (schema.anyOf) {
    for (const option of schema.anyOf) { try { validate(value, option, root); return; } catch { /* try union alternative */ } }
    return bad();
  }
  if ("const" in schema && value !== schema.const) bad();
  if (schema.enum && !schema.enum.includes(value)) bad();
  if (schema.type === "boolean" && typeof value !== "boolean") bad();
  if (schema.type === "null" && value !== null) bad();
  if (schema.type === "object") {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return bad();
    const object = value as Record<string, unknown>;
    for (const key of schema.required ?? []) if (!(key in object)) bad();
    for (const [key, item] of Object.entries(object)) {
      const property = schema.properties?.[key];
      if (property) validate(item, property, root); else if (schema.additionalProperties === false) bad();
    }
  }
  if (schema.type === "array") {
    if (!Array.isArray(value)) return bad();
    if (value.length < (schema.minItems ?? 0) || value.length > (schema.maxItems ?? Infinity)) bad();
    if (schema.items) for (const item of value) validate(item, schema.items, root);
  }
  if (schema.type === "string" && (typeof value !== "string" || (schema.pattern && !new RegExp(schema.pattern).test(value)))) bad();
  if (schema.type === "number" || schema.type === "integer") {
    if (typeof value !== "number" || !Number.isFinite(value)) return bad();
    if (schema.type === "integer" && !Number.isSafeInteger(value)) bad();
    if (value < (schema.minimum ?? -Infinity) || value > (schema.maximum ?? Infinity) || value <= (schema.exclusiveMinimum ?? -Infinity) || value >= (schema.exclusiveMaximum ?? Infinity)) bad();
  }
}
export function freeze<T>(value: T): T {
  if (value && typeof value === "object" && !ArrayBuffer.isView(value)) {
    Object.values(value).forEach(freeze); Object.freeze(value);
  }
  return value;
}
export async function sha256(bytes: Uint8Array): Promise<string> {
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", Uint8Array.from(bytes).buffer))].map(v => v.toString(16).padStart(2, "0")).join("");
}
export async function readBounded(stream: ReadableStream<Uint8Array>, limit: number): Promise<Uint8Array> {
  const reader = stream.getReader(); const parts: Uint8Array[] = []; let size = 0;
  try {
    for (;;) { const { done, value } = await reader.read(); if (done) break; size += value.length; if (size > limit) throw Error("Asset exceeds size budget"); parts.push(value); }
  } finally { await reader.cancel().catch(() => undefined); reader.releaseLock(); }
  const result = new Uint8Array(size); let offset = 0; for (const part of parts) { result.set(part, offset); offset += part.length; } return result;
}
export async function gunzip(bytes: Uint8Array): Promise<Uint8Array> {
  return readBounded(new Blob([Uint8Array.from(bytes).buffer]).stream().pipeThrough(new DecompressionStream("gzip")), 8 * 1024 * 1024);
}
export function parsePgm(bytes: Uint8Array, width: number, height: number): Uint8Array {
  const header = `P5\n${width} ${height}\n255\n`;
  if (new TextDecoder().decode(bytes.slice(0, header.length)) !== header || bytes.length !== header.length + width * height) throw Error("Unsupported map encoding/dimensions");
  return bytes.slice(header.length);
}
export async function loadN0(fetcher: typeof fetch = fetch): Promise<Dataset> {
  async function get(name: string, limit: number) {
    const response = await fetcher(`/__local_n0/${name}`, { cache: "no-store", redirect: "error" });
    if (!response.ok || !response.body) throw Error(`Approved local N0 asset unavailable: ${name}`);
    return readBounded(response.body, limit);
  }
  const bytes = await get("manifest.json", 250 * 1024);
  if (await sha256(bytes) !== N0_HASH) throw Error("Unapproved or corrupt manifest");
  const raw: unknown = JSON.parse(new TextDecoder().decode(bytes)); validate(raw, schemas.schemas.manifest as Schema);
  const manifest = raw as Manifest;
  if (manifest.schema_version !== 1 || manifest.dataset_id !== "N0" || manifest.publication_review !== "PRIVATE_NOT_APPROVED_FOR_UPLOAD") throw Error("Unsupported dataset/version");
  const poses: Pose[] = []; const scans: Scan[] = []; let pixels: Uint8Array | null = null;
  for (const asset of manifest.assets) {
    if (!/^(map\.pgm|poses-00[0-3]\.json|scans-000\.json)\.gz$/.test(asset.path) || asset.bytes > 1024 * 1024 || asset.schema_version !== 1) throw Error("Unsupported asset");
    const compressed = await get(asset.path, asset.bytes);
    if (compressed.length !== asset.bytes || await sha256(compressed) !== asset.sha256) throw Error(`Corrupt asset: ${asset.path}`);
    const decoded = await gunzip(compressed);
    if (asset.kind === "map") pixels = parsePgm(decoded, manifest.scene.width, manifest.scene.height);
    else {
      const chunk: unknown = JSON.parse(new TextDecoder().decode(decoded));
      const kind = asset.kind === "poses" ? "poses" : "scans";
      validate(chunk, schemas.schemas[kind] as Schema);
      const envelope = chunk as { schema_version: number; kind: string; samples: unknown[] };
      if (envelope.schema_version !== 1 || envelope.kind !== `robotops.playback_${kind}`) throw Error("Unsupported chunk version/kind");
      if (kind === "poses") poses.push(...envelope.samples as Pose[]); else scans.push(...envelope.samples as Scan[]);
    }
  }
  if (!pixels || poses.length !== 327 || scans.length !== 98) throw Error("Incomplete N0 assets");
  for (const samples of [poses, scans]) {
    let previous = -1n;
    for (const sample of samples) {
      const stamp = BigInt(sample.ros_ns);
      if (stamp <= previous || stamp < BigInt(manifest.time.recorded_start_ns) || stamp > BigInt(manifest.time.recorded_end_ns) || Number((stamp - BigInt(manifest.time.offset_origin_ns)) / 1000n) !== sample.offset_us) throw Error("Invalid playback timestamps");
      previous = stamp;
    }
  }
  for (const tf of [...poses.map(p => p.transform), ...scans.flatMap(s => [s.map_base, s.base_lidar])]) {
    if (tf && Math.abs(Math.hypot(...tf.quaternion) - 1) > 1e-6) throw Error("Invalid rotation");
  }
  return freeze({ manifest, poses, scans, pixels, trusted: true });
}
export function secondsBetween(a: string, b: string): number {
  const delta = BigInt(b) - BigInt(a); if (delta < 0n || delta > BigInt(Number.MAX_SAFE_INTEGER)) throw Error("Unsafe relative time"); return Number(delta) / 1e9;
}
export function poseAt(data: Dataset, stamp: bigint): Transform | null {
  const samples = data.poses;
  const next = samples.findIndex(p => BigInt(p.ros_ns) >= stamp);
  if (next < 0) return null;
  const b = samples[next];
  if (BigInt(b.ros_ns) === stamp) return b.quality === "SUPPORTED_TF" ? b.transform : null;
  const a = samples[next - 1];
  if (!a?.transform || !b.transform || a.quality !== "SUPPORTED_TF" || b.quality !== "SUPPORTED_TF" || !a.segment_id || a.segment_id !== b.segment_id || a.frame !== b.frame) return null;
  const segment = data.manifest.segments.find(s => s.id === a.segment_id);
  const gap = BigInt(b.ros_ns) - BigInt(a.ros_ns);
  if (!segment || segment.epoch !== 0 || stamp < BigInt(segment.start_ros_ns) || stamp > BigInt(segment.end_ros_ns) || gap > BigInt(segment.interpolate_within_max_gap_ns)) return null;
  const t = Number(stamp - BigInt(a.ros_ns)) / Number(gap);
  let q = b.transform.quaternion; const qa = a.transform.quaternion;
  let dot = qa.reduce((sum, v, i) => sum + v * q[i], 0); if (dot < 0) { q = q.map(v => -v) as Quat; dot = -dot; }
  let wa = 1 - t, wb = t;
  if (dot < 0.9995) { const angle = Math.acos(Math.min(1, dot)); wa = Math.sin((1 - t) * angle) / Math.sin(angle); wb = Math.sin(t * angle) / Math.sin(angle); }
  const quaternion = qa.map((v, i) => wa * v + wb * q[i]) as Quat;
  const norm = Math.hypot(...quaternion);
  return { position: a.transform.position.map((v, i) => v + t * (b.transform!.position[i] - v)) as Vec3, quaternion: quaternion.map(v => v / norm) as Quat };
}
export function transformPoint(tf: Transform, p: Vec3): Vec3 {
  const [x, y, z, w] = tf.quaternion; const [px, py, pz] = p;
  const tx = 2 * (y * pz - z * py), ty = 2 * (z * px - x * pz), tz = 2 * (x * py - y * px);
  return [px + w * tx + y * tz - z * ty + tf.position[0], py + w * ty + z * tx - x * tz + tf.position[1], pz + w * tz + x * ty - y * tx + tf.position[2]];
}
export function scanAt(data: Dataset, stamp: bigint): Scan | null {
  if (stamp < BigInt(data.manifest.time.recorded_start_ns) || stamp > BigInt(data.manifest.time.recorded_end_ns)) return null;
  const scan = [...data.scans].reverse().find(s => BigInt(s.ros_ns) <= stamp);
  return scan?.map_quality === "SUPPORTED_TF" && scan.map_base && scan.base_lidar && stamp - BigInt(scan.ros_ns) <= 200000000n ? scan : null;
}
export function scanPoints(scan: Scan | null): Vec3[] {
  if (!scan?.map_base || !scan.base_lidar) return [];
  return scan.ranges_m.flatMap((range, i) => {
    if (range === null || scan.validity[i] !== "valid") return [];
    const angle = scan.angle_min_rad + scan.selected_indices[i] * scan.angle_increment_rad;
    return [transformPoint(scan.map_base!, transformPoint(scan.base_lidar!, [range * Math.cos(angle), range * Math.sin(angle), 0]))];
  });
}
export function visitorDuration(metric: Metric | undefined, maximum: string, trusted: boolean): { outcome: "PASS" | "FAIL" | "UNKNOWN"; reason: string } {
  const threshold = maximum.trim() === "" ? NaN : Number(maximum);
  if (!Number.isFinite(threshold) || threshold < 0) return { outcome: "UNKNOWN", reason: "Enter a finite nonnegative maximum in seconds" };
  if (!trusted || !metric || metric.name !== "mission_ros_seconds" || metric.unit !== "s" || metric.quality !== "ORIGINAL_VERIFIED" || metric.source_ref !== "report" || metric.pointer !== "/campaign/trials/0/evidence/metrics/mission_ros_seconds" || metric.value === null || !Number.isFinite(metric.value) || metric.value < 0) return { outcome: "UNKNOWN", reason: "Qualified original duration evidence unavailable" };
  return { outcome: metric.value <= threshold ? "PASS" : "FAIL", reason: "visitor.duration.v1 · original ROS seconds ≤ maximum (equality passes)" };
}
export function advance(current: number, elapsed: number, playing: boolean, speed: number, duration: number): number {
  return Math.max(0, Math.min(duration, current + (playing ? Math.max(0, elapsed) * speed : 0)));
}
export function cellCentre(u: number, v: number, scene: Manifest["scene"]): Vec3 {
  const x = scene.resolution_m * (u + .5), y = scene.resolution_m * (scene.height - v - .5), yaw = scene.origin[2];
  return [scene.origin[0] + Math.cos(yaw) * x - Math.sin(yaw) * y, scene.origin[1] + Math.sin(yaw) * x + Math.cos(yaw) * y, 0];
}
export function displayPoint([x, y, z]: Vec3): Vec3 { return [x, z, -y]; }
export function displayQuaternion([x, y, z, w]: Quat): Quat { return [x, z, -y, w]; }

export function occupancyRows(pixels: Uint8Array, scene: Manifest["scene"]): number[] {
  return Array.from(pixels, (_, i) => {
    const row = Math.floor(i / scene.width), col = i % scene.width;
    const gray = pixels[(scene.height - row - 1) * scene.width + col];
    const probability = scene.negate ? gray / 255 : (255 - gray) / 255;
    return probability > scene.occupied_threshold ? 100 : probability < scene.free_threshold ? 0 : -1;
  });
}
