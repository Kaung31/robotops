import assert from 'node:assert/strict';
import { readFile, access } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import * as jsx from 'react/jsx-runtime';
function compile(source, imports = {}) {
  const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } });
  const module = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(name => { assert(name in imports, `Unexpected dependency ${name}`); return imports[name]; }, module, module.exports);
  return module.exports;
}
const read = async file => readFile(new URL(file, import.meta.url), 'utf8');
const v1schema = JSON.parse(await read('../src/replay/schema-v1.json'));
const schema = JSON.parse(await read('../src/replay/schema-warehouse-v1.json'));
const engine = compile(await read('../src/replay/data.ts'), { './schema-v1.json': { default: v1schema } });
const loader = compile(await read('../src/replay/data-warehouse.ts'), { './data': engine, './schema-warehouse-v1.json': { default: schema } });
const compare = compile(await read('../src/replay/comparison.ts'), { './data': engine });
const wcompare = compile(await read('../src/replay/warehouse-comparison.ts'), { './comparison': compare, './data-warehouse': loader });
const strip = compile(await read('../src/site/StripChart.tsx'), { 'react/jsx-runtime': jsx });
const { WarehouseResults, WarehouseComparison } = compile(await read('../src/replay/WarehouseComparisonPanel.tsx'), { 'react/jsx-runtime': jsx, './comparison': compare, './data-warehouse': loader, './warehouse-comparison': wcompare, '../site/StripChart': strip });
const { BenchmarkCautions } = compile(await read('../src/site/BenchmarkCautions.tsx'), { 'react/jsx-runtime': jsx });
const { WarehouseBanner } = compile(await read('../src/replay/WarehouseBanner.tsx'), { 'react/jsx-runtime': jsx, './data-warehouse': loader });
const validation = compile(await read('../src/replay/validation.ts'), { './data': engine });
const presentation = compile(await read('../src/replay/presentation.ts'));
const panel = compile(await read('../src/replay/ValidationPanel.tsx'), { react: React, 'react/jsx-runtime': jsx, './validation': validation });
const { ReplayLab } = compile(await read('../src/replay/ReplayLab.tsx'), { react: React, 'react/jsx-runtime': jsx, './data': engine, './presentation': presentation, './ValidationPanel': panel, '../components/MapView': { MapView: () => React.createElement('div', null, 'map fixture') }, './RecordedScene': { RecordedScene: () => React.createElement('div', null, 'scene fixture') } });

test('warehouse schema matches the Python model artifact byte for byte', async () => {
  assert.equal(await read('../src/replay/schema-warehouse-v1.json'), await read('../../scripts/replay-schema-warehouse-v1.json'));
});
test('only the six pinned warehouse identities are accepted', () => {
  assert.deepEqual(loader.WAREHOUSE_IDS, ['W01', 'W02', 'W03', 'W04', 'W05', 'W06']);
  for (const id of ['W00', 'W07', 'w01', 'N0', '../W01', 'https://example.com', '']) assert.throws(() => loader.warehouseId(id));
  assert.deepEqual(['W01', 'W04', 'W05'].map(id => loader.WAREHOUSE[id].profile), ['navfn_rpp', 'navfn_rpp', 'navfn_rpp']);
  assert.deepEqual(['W02', 'W03', 'W06'].map(id => loader.WAREHOUSE[id].profile), ['smac_dwb', 'smac_dwb', 'smac_dwb']);
  assert.deepEqual(loader.assetNames('W01').slice(0, 3), ['map.pgm.gz', 'poses-000.json.gz', 'poses-001.json.gz']);
  assert.equal(loader.assetNames('W01').length, 1 + Math.ceil(2357 / 100) + Math.ceil(707 / 100));
});

const metric = (name, value, unit, category) => ({ name, value, unit, quality: 'ORIGINAL_VERIFIED', source_ref: 'report', pointer: `/campaign/trials/0/evidence/${category}/${name}` });
const fake = (id, seconds, yaw, teardown = 'NO_CHILD_FAILURE_LOGGED') => ({ dataset_id: id, metrics: [metric('mission_ros_seconds', seconds, 's', 'metrics'), metric('odom_path_metres', 28, 'm', 'metrics'), metric('xy_error_m', .1, 'm', 'validation'), metric('yaw_error_rad', yaw, 'rad', 'validation')], original_validation: { pose_verdict: 'POSE_VERIFIED', contact_verdict: 'NO_CONTACT_OBSERVED' }, teardown: { status: teardown }, conditions: { environment: 'warehouse_v1', map_id: 'warehouse_v1', map_image_sha256: 'a', map_yaml_sha256: 'b', waypoints: [], requested_start: { x: 0, y: 0, yaw: 0 }, profile: loader.WAREHOUSE[id].profile, parameters_sha256: loader.WAREHOUSE[id].profile }, benchmark: { matrix_sha256: 'm' } });
const fakes = { W01: fake('W01', 137, .05), W02: fake('W02', 133, .2), W03: fake('W03', 132, .19, 'CRASHED_AFTER_EVIDENCE_FINALIZED'), W04: fake('W04', 138, .06), W05: fake('W05', 139, .04), W06: fake('W06', 134, .21) };
test('per-configuration summaries use exact values of all three planned trials only', () => {
  const rows = wcompare.trialRows(fakes);
  assert.deepEqual(wcompare.profileSummary(rows, 'navfn_rpp', 'mission_ros_seconds'), { mean: 138, min: 137, max: 139, n: 3 });
  assert.equal(wcompare.differenceOfMeans(rows, 'mission_ros_seconds'), 133 - 138);
  assert.equal(wcompare.verdictCounts(rows, 'smac_dwb', 'pose'), 'POSE_VERIFIED 3/3');
  const partial = structuredClone(fakes); partial.W05.metrics[0].unit = 'ms';
  const summary = wcompare.profileSummary(wcompare.trialRows(partial), 'navfn_rpp', 'mission_ros_seconds');
  assert.equal(summary.mean, null); assert.equal(summary.n, 2);
  assert.equal(wcompare.differenceOfMeans(wcompare.trialRows(partial), 'mission_ros_seconds'), null);
  assert.equal(wcompare.verdictCounts(wcompare.trialRows({}), 'smac_dwb', 'contact'), 'Unavailable');
});
test('results and comparison disclose W03 teardown and the aisle finding without ranking', () => {
  const results = renderToStaticMarkup(React.createElement(WarehouseResults, { originals: fakes, error: '', selected: 'W03', onReplay: () => undefined }));
  for (const text of ['Key finding — no aisle driving', 'does not demonstrate narrow-aisle navigation', 'Crashed after evidence finalized', 'W03: the simulator crashed while the stack was shutting down', 'All six trials, in run order', 'Replay W02 in the player', 'NavFn + Regulated Pure Pursuit', 'Smac 2D + DWB']) assert(results.includes(text), text);
  assert.match(results, /aria-current="true"/); assert.match(results, />Showing</);
  const comparison = renderToStaticMarkup(React.createElement(WarehouseComparison, { originals: fakes, error: '' }));
  for (const text of ['Descriptive only', 'no winner', 'Δ of means (Smac − NavFn)', 'Per-configuration summary', 'Mission time, seconds', 'Final heading error, radians']) assert(comparison.includes(text), text);
  for (const html of [results, comparison]) assert.doesNotMatch(html, /winner score:|superior|best profile|statistically significant/i);
  const empty = renderToStaticMarkup(React.createElement(WarehouseResults, { originals: {}, error: 'Unapproved', selected: null }));
  assert.match(empty, /Comparison evidence unavailable/); assert.doesNotMatch(empty, /finished every trial sooner/); assert.doesNotMatch(empty, /Replay W0/);
  const emptyComparison = renderToStaticMarkup(React.createElement(WarehouseComparison, { originals: {}, error: 'Unapproved' }));
  assert.match(emptyComparison, /Unavailable until all six pinned manifests are verified/); assert.match(emptyComparison, /Charts are unavailable/);
});
test('findings are stated only when every trial supports them', () => {
  const rows = wcompare.trialRows(fakes);
  assert.equal(wcompare.separated(rows, 'smac_dwb', 'navfn_rpp', 'mission_ros_seconds'), true);
  assert.equal(wcompare.separated(rows, 'navfn_rpp', 'smac_dwb', 'mission_ros_seconds'), false);
  const overlap = structuredClone(fakes); overlap.W02.metrics[0].value = 137.5;
  assert.equal(wcompare.separated(wcompare.trialRows(overlap), 'smac_dwb', 'navfn_rpp', 'mission_ros_seconds'), false);
  assert.doesNotMatch(renderToStaticMarkup(React.createElement(WarehouseResults, { originals: overlap, error: '', selected: null })), /finished every trial sooner/);
  const missing = structuredClone(fakes); delete missing.W06;
  assert.equal(wcompare.separated(wcompare.trialRows(missing), 'smac_dwb', 'navfn_rpp', 'mission_ros_seconds'), false);
});
test('shared benchmark cautions carry every required disclosure', () => {
  const html = renderToStaticMarkup(React.createElement(BenchmarkCautions, { id: 'caution' }));
  for (const text of ['never entered the 1.2 m aisles', 'does not show narrow-aisle navigation', 'Three trials per configuration', 'not statistical significance', 'planner and the controller both differ', 'Not formally qualified', 'W3/W4', 'normal backend campaigns', 'simulator ground truth was not recorded', 'W03 teardown crash', 'Navigation succeeded and the evidence was finalized, then Gazebo crashed while the stack shut down', 'results are unchanged']) assert(html.includes(text), text);
});

let available = process.env.ROBOTOPS_SKIP_PRIVATE !== '1';
const folder = id => new URL(`../../artifacts/warehouse-lab-20261013/dataset-${id.toLowerCase()}-final/`, import.meta.url);
try { await access(new URL('manifest.json', folder('W06'))); } catch { available = false; }
const fetcher = async url => { const match = /^\/__local_v2\/(w0[1-6])\/([a-z0-9.-]+)$/.exec(url); assert(match, `Unexpected fetch ${url}`); return new Response(await readFile(new URL(match[2], folder(match[1])))); };
test('private warehouse exports available', { skip: available ? false : 'Private warehouse exports intentionally absent' }, () => assert(available));
if (available) {
  const datasets = {};
  for (const id of loader.WAREHOUSE_IDS) datasets[id] = await loader.loadWarehouseDataset(id, fetcher);
  test('six pinned datasets load with exact counts, frozen originals and visitor checks separate', () => {
    for (const id of loader.WAREHOUSE_IDS) {
      const d = datasets[id];
      assert.equal(d.manifest.schema_version, 3); assert.equal(d.manifest.dataset_id, id); assert.equal(d.manifest.benchmark.qualification, 'NOT_QUALIFIED');
      assert.equal(d.poses.length, loader.WAREHOUSE[id].poses); assert.equal(d.scans.length, loader.WAREHOUSE[id].scans);
      assert.equal(d.manifest.coverage.full_mission_replay, true); assert.equal(d.manifest.original_validation.pose_verdict, 'POSE_VERIFIED');
      assert(Object.isFrozen(d.manifest)); const before = JSON.stringify(d.manifest);
      for (const c of validation.CHECKS) { const m = d.manifest.metrics.find(m => m.name === c.metric); assert.equal(validation.visitorCheck(c.id, d.manifest.metrics, String(m.value), d.trusted).outcome, 'PASS'); assert.equal(validation.visitorCheck(c.id, d.manifest.metrics, String(m.value - 1e-9), d.trusted).outcome, 'FAIL'); }
      assert.equal(JSON.stringify(d.manifest), before);
    }
    assert.equal(datasets.W03.manifest.teardown.status, 'CRASHED_AFTER_EVIDENCE_FINALIZED');
    for (const id of ['W01', 'W02', 'W04', 'W05', 'W06']) assert.equal(datasets[id].manifest.teardown.status, 'NO_CHILD_FAILURE_LOGGED');
  });
  test('replay covers the whole navigation window with real poses and scans', () => {
    for (const d of Object.values(datasets)) {
      const { mission_start_ns: start, mission_end_ns: end } = d.manifest.time;
      assert(engine.poseAt(d, BigInt(start))); assert(engine.poseAt(d, (BigInt(start) + BigInt(end)) / 2n));
      assert(engine.scanPoints(engine.scanAt(d, BigInt(start) + 1000000000n)).length > 0);
    }
  });
  test('actual comparison reproduces the documented per-configuration means', () => {
    const originals = Object.fromEntries(Object.entries(datasets).map(([id, d]) => [id, d.manifest]));
    const rows = wcompare.trialRows(originals);
    assert.equal(wcompare.profileSummary(rows, 'navfn_rpp', 'mission_ros_seconds').mean.toFixed(2), '137.67');
    assert.equal(wcompare.profileSummary(rows, 'smac_dwb', 'mission_ros_seconds').mean.toFixed(2), '132.78');
    assert.equal(wcompare.verdictCounts(rows, 'navfn_rpp', 'contact'), 'NO_CONTACT_OBSERVED 3/3');
    const results = renderToStaticMarkup(React.createElement(WarehouseResults, { originals, error: '', selected: 'W01' }));
    assert.match(results, /137\.372 s/); assert.match(results, />6\/6</); assert.match(results, />5\/5</);
    assert.match(results, /4\.9 s \(3\.6%\) faster on average/); assert.match(results, /mean 3\.2° against 11\.0°/); assert.match(results, /Final position errors overlap/);
    const comparison = renderToStaticMarkup(React.createElement(WarehouseComparison, { originals, error: '' }));
    assert.match(comparison, /matches/); assert.doesNotMatch(comparison, /differ — do not treat as controlled/); assert.match(comparison, /Validation limit \(original policy\)/);
  });
  test('W03 view shows the disclosure; ReplayLab starts at mission start for full recordings', () => {
    const banner = renderToStaticMarkup(React.createElement(WarehouseBanner, { manifest: datasets.W03.manifest }));
    assert.match(banner, /Disclosure:/); assert.match(banner, /gazebo_runner exited -11/); assert.match(banner, /Not formally qualified/); assert.match(banner, /W3\/W4/); assert.match(banner, /never entered the 1.2 m aisles/);
    assert.match(banner, /three trials per configuration/); assert.match(banner, /Simulator ground truth was not recorded/); assert.match(banner, /navigation succeeded and the evidence was finalized; Gazebo then crashed during post-run teardown/);
    assert.doesNotMatch(renderToStaticMarkup(React.createElement(WarehouseBanner, { manifest: datasets.W01.manifest })), /Disclosure:/);
    const html = renderToStaticMarkup(React.createElement(ReplayLab, { data: datasets.W03, manifestHash: loader.WAREHOUSE.W03.hash, criteria: { duration: '140', xy: '0.2', yaw: '0.25' } }));
    assert.match(html, /Whole navigation window recorded/); assert.match(html, /00:00\.0/); assert.match(html, /Playback starts at mission start/);
    assert.match(html, new RegExp(loader.WAREHOUSE.W03.hash)); assert.match(html, /exploratory, not qualified/); assert.match(html, /value="140"/);
    assert.doesNotMatch(html, /mission beginning is missing|not a full-mission recording/);
  });
  test('missing, tampered, swapped and unlisted warehouse assets fail closed', async () => {
    await assert.rejects(loader.loadWarehouseDataset('W02', async () => new Response('missing', { status: 404 })), /unavailable/);
    await assert.rejects(loader.loadWarehouseDataset('W02', async url => url.endsWith('manifest.json') ? fetcher(url) : new Response('corrupt')), /Corrupt|size/);
    await assert.rejects(loader.loadWarehouseDataset('W02', async url => fetcher(url.replace('w02', 'w03'))), /manifest/);
    await assert.rejects(loader.loadWarehouseManifest('W07', fetcher), /identity/);
  });
  test('strict warehouse schema rejects promotion, hidden disclosures and private fields', () => {
    for (const mutate of [m => m.schema_version = 2, m => m.dataset_id = 'W07', m => m.benchmark.qualification = 'QUALIFIED', m => m.benchmark.execution_path = 'W4_PERMISSION', m => m.teardown.status = 'CLEAN', m => m.extra = '/home/private', m => m.recorder_loss.transport_lost_messages = 3, m => m.metrics[0].pointer = '/graphics', m => m.sources[0].scope = 'public']) {
      const m = structuredClone(datasets.W03.manifest); mutate(m); assert.throws(() => engine.validate(m, schema.WarehouseManifest));
    }
  });
}

test('after the last display sample inside the recording, the pose status says how far back it is', () => {
  // Synthetic UI fixture: one supported sample 15 ms before mission start, recording continues.
  const transform = { position: [0, 0, 0], quaternion: [0, 0, 0, 1] };
  const data = { trusted: true, pixels: new Uint8Array([255]), scans: [], poses: [{ ros_ns: '985000000', offset_us: 0, segment_id: 's', frame: 'map', transform, quality: 'SUPPORTED_TF' }],
    manifest: { schema_version: 3, dataset_id: 'W01', time: { mission_start_ns: '1000000000', mission_end_ns: '2000000000', recorded_start_ns: '985000000', recorded_end_ns: '2000000000', offset_origin_ns: '985000000' },
      segments: [{ id: 's', start_ros_ns: '985000000', end_ros_ns: '985000000', interpolate_within_max_gap_ns: 100000000, epoch: 0, frame: 'map' }],
      scene: { width: 1, height: 1, resolution_m: .05, origin: [0, 0, 0], free_threshold: .196, occupied_threshold: .65, negate: 0 }, metrics: [], coverage: { full_mission_replay: true, gaps: [], missing_channels: [] },
      original_validation: { ros_outcome: 'succeeded', pose_verdict: 'POSE_VERIFIED', contact_verdict: 'NO_CONTACT_OBSERVED', final_localized_pose: { x: 0, y: 0, yaw: 0 }, final_pose_ros_ns: '2000000000', contact_frame_count: 1, contact_scope: 'ADAPTER_MONITORED_GEOMETRY_ONLY', action_status: 4, action_status_reason: 'AVAILABLE', mission_action: { pointer: '/campaign/trials/0/evidence/validation/action_status', scope: 'SAVED_MISSION_ACTION_RESULT_SNAPSHOT', observer: 'experiment_runner' } },
      teardown: { status: 'NO_CHILD_FAILURE_LOGGED' }, recorder_loss: { transport_lost_messages: 0 }, limitations: [] } };
  const html = renderToStaticMarkup(React.createElement(ReplayLab, { data }));
  assert.match(html, /Pose unavailable — last 20 Hz display sample is 0\.015 s earlier; no movement reconstructed/);
});
