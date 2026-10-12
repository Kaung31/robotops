import assert from "node:assert/strict";
import { readFile, readdir, access } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const schema = JSON.parse(await readFile(new URL("../src/replay/schema-v1.json", import.meta.url), "utf8"));
let source = await readFile(new URL("../src/replay/data.ts", import.meta.url), "utf8");
source = source.replace('import schemas from "./schema-v1.json";', `const schemas = ${JSON.stringify(schema)};`);
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } });
const replay = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
const root = new URL("../../artifacts/p2-n0-20261011/dataset-final/", import.meta.url);
const requests = [];
const fetcher = async url => { requests.push(url); assert.match(url, /^\/__local_n0\/[a-z0-9.-]+$/); return new Response(await readFile(new URL(url.split("/").at(-1), root))); };
let available = process.env.ROBOTOPS_SKIP_PRIVATE !== "1";
try { await access(new URL("manifest.json", root)); } catch { available = false; }
const data = available ? await replay.loadN0(fetcher) : null;
test("private N0 integration fixtures available", { skip: available ? false : "Private N0 is intentionally absent from source/CI" }, () => assert(data));
if (data) {
const metric = data.manifest.metrics.find(m => m.name === "mission_ros_seconds");
const clone = () => structuredClone(data);

test("exact N0 loads hashes, bounded gzip, v1 schemas and all samples without API", () => {
  assert.equal(data.poses.length, 327); assert.equal(data.scans.length, 98); assert.equal(data.pixels.length, 199 * 159);
  assert.equal(requests.length, 7); assert(requests.every(v => !v.includes("/api")));
  assert.equal(data.manifest.coverage.full_mission_replay, false);
  assert.equal(data.poses.filter(p => p.transform).length, 318);
});
test("browser schema is byte-identical to authoritative P2 schema", async () => {
  assert.equal(await readFile(new URL("../src/replay/schema-v1.json", import.meta.url), "utf8"), await readFile(new URL("../../scripts/replay-schema-v1.json", import.meta.url), "utf8"));
});
test("schema rejects unknown fields, versions, malformed time, numbers and booleans", () => {
  for (const mutate of [m => m.schema_version = 2, m => m.time.mission_start_ns = 4031000000, m => m.scene.width = 1.5, m => m.coverage.full_mission_replay = "false", m => m.extra = true, m => delete m.time]) {
    const m = structuredClone(data.manifest); mutate(m); assert.throws(() => replay.validate(m, schema.schemas.manifest));
  }
});
test("safe exact timestamp subtraction beyond JS full-ns precision", () => {
  assert.equal(replay.secondsBetween("9007199254740993123", "9007199254741993123"), .001);
  assert.throws(() => replay.secondsBetween("2", "1")); assert.throws(() => replay.secondsBetween("0", "9007199254740992"));
});
test("map top-down cell centres, bottom-left origin and positive map yaw", () => {
  const scene = data.manifest.scene;
  replay.cellCentre(0, 158, scene).forEach((v, i) => assert(Math.abs(v - [-4.942, -3.944, 0][i]) < 1e-12));
  const top = replay.cellCentre(198, 0, scene); assert(Math.abs(top[0] - 4.958) < 1e-12); assert(Math.abs(top[1] - 3.956) < 1e-12);
  const rotated = replay.cellCentre(0, 0, { ...scene, width: 1, height: 1, resolution_m: 2, origin: [0, 0, Math.PI / 2] });
  assert(Math.abs(rotated[0] + 1) < 1e-12); assert(Math.abs(rotated[1] - 1) < 1e-12);
  assert.deepEqual(replay.displayPoint([1, 2, 3]), [1, 3, -2]); assert.deepEqual(replay.displayQuaternion([1, 2, 3, 4]), [1, 3, -2, 4]);
});
test("map parser refuses invalid dimensions/encoding", () => {
  assert.throws(() => replay.parsePgm(new TextEncoder().encode("P2\n1 1\n255\n0"), 1, 1));
});
test("recorded coordinates preserved at sample and interpolated only between supported samples", () => {
  const p = data.poses.find(p => p.transform);
  assert.deepEqual(replay.poseAt(data, BigInt(p.ros_ns)), p.transform);
  const i = data.poses.indexOf(p), b = data.poses[i + 1], stamp = (BigInt(p.ros_ns) + BigInt(b.ros_ns)) / 2n;
  const interpolated = replay.poseAt(data, stamp);
  p.transform.position.forEach((v, j) => assert(Math.abs(interpolated.position[j] - (v + b.transform.position[j]) / 2) < 1e-12));
  const copy = clone(); copy.poses[i + 1].transform.quaternion = copy.poses[i + 1].transform.quaternion.map(v => -v);
  assert(Math.abs(Math.hypot(...replay.poseAt(copy, stamp).quaternion) - 1) < 1e-12);
});
test("head, initial TF gap, display tail and mission tail never extrapolate report pose", () => {
  for (const ns of ["4031000000", "4748000000", "5000000000", "5299999999", "24340000001", "24347000000", "24699000000", "24780000000"]) assert.equal(replay.poseAt(data, BigInt(ns)), null);
  assert.equal(replay.poseAt(data, 5300000000n), null); assert(replay.poseAt(data, 5320000000n)); assert(replay.poseAt(data, 24340000000n));
});
test("different segments, frame discontinuities, unavailable pose and long gap prohibit interpolation", () => {
  const i = data.poses.findIndex(p => p.transform), a = data.poses[i], b = data.poses[i + 1], stamp = (BigInt(a.ros_ns) + BigInt(b.ros_ns)) / 2n;
  for (const mutate of [p => p.segment_id = "other", p => p.frame = "odom", p => p.transform = null, p => p.quality = "TF_UNAVAILABLE"]) {
    const d = clone(); mutate(d.poses[i + 1]); assert.equal(replay.poseAt(d, stamp), null);
  }
  const d = clone(); d.manifest.segments[0].interpolate_within_max_gap_ns = 1; assert.equal(replay.poseAt(d, stamp), null);
});
test("LiDAR uses recorded map-base and base-lidar at scan time, no interpolation", () => {
  const scan = data.scans.find(s => s.map_base), points = replay.scanPoints(scan);
  const angle = scan.angle_min_rad + scan.selected_indices[0] * scan.angle_increment_rad;
  const local = [scan.ranges_m[0] * Math.cos(angle), scan.ranges_m[0] * Math.sin(angle), 0];
  const expected = replay.transformPoint(scan.map_base, replay.transformPoint(scan.base_lidar, local)); assert.deepEqual(points[0], expected);
  const tf = { position: [1, 2, 3], quaternion: [0, 0, Math.SQRT1_2, Math.SQRT1_2] };
  const rotated = replay.transformPoint(tf, [1, 0, 0]); assert(Math.abs(rotated[0] - 1) < 1e-12); assert(Math.abs(rotated[1] - 3) < 1e-12);
  assert.equal(replay.scanAt(data, BigInt(scan.ros_ns) + 1n), scan);
  assert.equal(replay.scanAt(data, 5000000000n), null); assert.equal(replay.scanAt(data, 24699000000n), null);
  const d = clone(); d.scans = [scan]; assert.equal(replay.scanAt(d, BigInt(scan.ros_ns) + 200000001n), null);
  const invalid = { ...scan, ranges_m: [null], validity: ["no_return"], selected_indices: [0] }; assert.deepEqual(replay.scanPoints(invalid), []);
});
test("pause, resume, speed, seek clamping and end boundary deterministic", () => {
  assert.equal(replay.advance(2, 3, false, 1, 20.668), 2); assert.equal(replay.advance(2, 3, true, 2, 20.668), 8);
  assert.equal(replay.advance(20, 3, true, 1, 20.668), 20.668); assert.equal(replay.advance(-4, 0, false, 1, 20.668), 0);
  assert.equal(replay.advance(9, 0, false, 1, 20.668), 9);
});
for (const [threshold, expected] of [["25", "PASS"], ["20", "FAIL"], ["20.668", "PASS"], ["20.667999999", "FAIL"], ["", "UNKNOWN"], ["-1", "UNKNOWN"], ["NaN", "UNKNOWN"], ["Infinity", "UNKNOWN"]]) {
  test(`duration maximum ${JSON.stringify(threshold)} => ${expected}`, () => assert.equal(replay.visitorDuration(metric, threshold, true).outcome, expected));
}
test("invalid, missing or untrusted evidence never passes with a relaxed threshold", () => {
  for (const m of [undefined, { ...metric, value: null }, { ...metric, value: NaN }, { ...metric, quality: "UNAVAILABLE" }, { ...metric, unit: "ms" }, { ...metric, source_ref: "other" }, { ...metric, pointer: "/invented" }]) assert.equal(replay.visitorDuration(m, "999", true).outcome, "UNKNOWN");
  assert.equal(replay.visitorDuration(metric, "25", false).outcome, "UNKNOWN");
});
test("visitor does not mutate original values, verdicts, or frozen graph", () => {
  const before = JSON.stringify(data.manifest); replay.visitorDuration(metric, "20", true); assert.equal(JSON.stringify(data.manifest), before);
  assert.throws(() => data.manifest.original_validation.pose_verdict = "PASS", TypeError);
  assert.throws(() => data.poses[20].transform.position[0] = 999, TypeError);
  assert.equal(metric.value, 20.668); assert.equal(data.manifest.metrics[1].value, 1.5568730774647175);
});
test("missing, corrupt, truncated assets and unapproved manifests fail closed", async () => {
  await assert.rejects(replay.loadN0(async () => new Response("missing", { status: 404 })), /unavailable/);
  await assert.rejects(replay.loadN0(async () => new Response("{}")), /manifest/);
  await assert.rejects(replay.loadN0(async url => url.endsWith("manifest.json") ? fetcher(url) : new Response("corrupt")), /size budget|Corrupt asset/);
  await assert.rejects(replay.gunzip(new Uint8Array([1, 2, 3])));
  await assert.rejects(replay.readBounded(new Blob([new Uint8Array(100)]).stream(), 99), /size budget/);
});
test("replay dependency graph has no operational imports/WS; live entry preserved", async () => {
  for (const name of await readdir(new URL("../src/replay/", import.meta.url))) {
    if (!name.endsWith(".tsx") && !name.endsWith(".ts")) continue;
    const text = await readFile(new URL(`../src/replay/${name}`, import.meta.url), "utf8");
    assert.doesNotMatch(text, /useTelemetry|useControlCenter|useCampaigns|lib\/api|campaignClient|new WebSocket|\/api\/v1/);
  }
  const config = await readFile(new URL("../vite.replay.config.ts", import.meta.url), "utf8"); assert.doesNotMatch(config, /proxy:/); assert.match(config, /publicDir: false/);
  const live = await readFile(new URL("../src/main.tsx", import.meta.url), "utf8"); assert.match(live, /import App from "\.\/App"/);
  assert.doesNotMatch(live, /replay/);
});

}
// Portable unit fixtures below are synthetic calculation inputs, never displayed
// as experiment records. Private integration cases above do not run in clean CI.
const qualified = { name: "mission_ros_seconds", value: 20.668, unit: "s", quality: "ORIGINAL_VERIFIED", source_ref: "report", pointer: "/campaign/trials/0/evidence/metrics/mission_ros_seconds" };
for (const [maximum, outcome] of [["25", "PASS"], ["20", "FAIL"], ["20.668", "PASS"], ["", "UNKNOWN"], ["-1", "UNKNOWN"]]) {
  test(`portable duration ${maximum} => ${outcome}`, () => assert.equal(replay.visitorDuration(qualified, maximum, true).outcome, outcome));
}
test("portable invalid/untrusted metric cannot pass", () => {
  assert.equal(replay.visitorDuration(undefined, "25", true).outcome, "UNKNOWN");
  assert.equal(replay.visitorDuration(qualified, "25", false).outcome, "UNKNOWN");
});
test("portable orientation converts top-down PGM to bottom-up occupancy exactly once", () => {
  const scene = { width: 2, height: 2, free_threshold: .196, occupied_threshold: .65, negate: 0 };
  assert.deepEqual(replay.occupancyRows(new Uint8Array([0, 255, 205, 0]), scene), [-1, 100, 100, 0]);
});
test("portable pause/resume and exact nanosecond subtraction", () => {
  assert.equal(replay.advance(4, 2, false, 1, 10), 4); assert.equal(replay.advance(4, 2, true, 2, 10), 8);
  assert.equal(replay.secondsBetween("9007199254740993123", "9007199254741993123"), .001);
});
test("portable strict schema rejects unknown versions and malformed envelope", () => {
  assert.throws(() => replay.validate({ schema_version: 2, samples: [] }, schema.schemas.poses));
  assert.throws(() => replay.validate({ samples: [], unexpected: 1 }, schema.schemas.poses));
});
test("portable corrupt gzip and excessive decoded stream fail safely", async () => {
  await assert.rejects(replay.gunzip(new Uint8Array([1, 2, 3])));
  await assert.rejects(replay.readBounded(new Blob([new Uint8Array(10)]).stream(), 9));
});
