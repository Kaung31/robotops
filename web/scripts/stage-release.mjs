// Offline only. Never uploads, never changes evidence or approves publication.
import { readFile, lstat, realpath, readdir, mkdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { dirname, resolve, relative, join } from 'node:path';
import { fileURLToPath } from 'node:url';
export const pins = Object.freeze({ n0: '670ccd62c5b5d0e74fc379c2ce9e478534995fd6af2571fc9933fc377d1f85f8', n2: 'a4d2c77a28e74d7124429ccc7f8c56010f81802898315bcc1d3de097912028d4',
  w01: '2c9007b91dd0d09c76d83e3f948303c678daf547a4b492860d6109d7106a7345', w02: '6cc4928691c9f6e5fa47cee749c60a8f8f354e05dac53db16002cd59a4481561', w03: 'e1cce11951245ec85c9a7e00b3d5f5b48bc18c1fd87c820f81bb409d307b38ca',
  w04: '5804cbb05697b7ac6b06991f95f0fc92538e77841f99bbe7995f77d85da31313', w05: '8a3e4b9c51686dc2bdb737cf6c4b842469f63ef5613568a52a2096c0d3066e4b', w06: 'efdfaab4b5a2b25da3c7cfe81d250c7b60d942850d3f8b3ea315aec9de65e4a7' });
export const assetNames = ['map.pgm.gz','poses-000.json.gz','poses-001.json.gz','poses-002.json.gz','poses-003.json.gz','scans-000.json.gz'];
// Warehouse Benchmark v1 sample counts [poses, scans]; chunk names follow from them.
const warehouseCounts = Object.freeze({ w01: [2357, 707], w02: [2283, 685], w03: [2269, 681], w04: [2365, 710], w05: [2363, 709], w06: [2289, 687] });
export const warehouseIds = Object.keys(warehouseCounts);
const chunks = (kind, n) => Array.from({ length: Math.ceil(n / 100) }, (_, i) => `${kind}-${String(i).padStart(3, '0')}.json.gz`);
export function expectedAssets(id) {
  if (!Object.hasOwn(warehouseCounts, id)) return assetNames;
  const [poses, scans] = warehouseCounts[id];
  return ['map.pgm.gz', ...chunks('poses', poses), ...chunks('scans', scans)];
}
export const digest = bytes => createHash('sha256').update(bytes).digest('hex');
async function regular(root, name) {
  const path = resolve(root, name), stat = await lstat(path);
  if (!path.startsWith(root + '/') || !stat.isFile() || stat.isSymbolicLink() || stat.size > 5 * 1024 * 1024 || await realpath(path) !== path) throw Error('Not a bounded regular release file');
  return readFile(path);
}
export async function inspectBundle(root, id) {
  if (!Object.hasOwn(pins, id)) throw Error('Unapproved dataset');
  const bytes = await regular(root, 'manifest.json');
  if (digest(bytes) !== pins[id]) throw Error('Unapproved manifest');
  const m = JSON.parse(bytes);
  const warehouse = warehouseIds.includes(id), expected = expectedAssets(id);
  if (m.schema_version !== (warehouse ? 3 : 2) || m.dataset_id !== id.toUpperCase() || m.publication_review !== 'PRIVATE_NOT_APPROVED_FOR_UPLOAD') throw Error('Version/identity/publication conflict');
  if (warehouse && (m.benchmark.qualification !== 'NOT_QUALIFIED' || (m.teardown.status === 'CRASHED_AFTER_EVIDENCE_FINALIZED') !== m.limitations.includes('TEARDOWN_CRASH_AFTER_FINALIZATION'))) throw Error('Benchmark status/disclosure conflict');
  if (m.assets.length !== expected.length || new Set(m.assets.map(a => a.path)).size !== expected.length || m.assets.some(a => !expected.includes(a.path))) throw Error('Unexpected inventory');
  const names = ['manifest.json', 'dataset.sha256', ...expected];
  if (JSON.stringify((await readdir(root)).sort()) !== JSON.stringify([...names].sort())) throw Error('Unexpected source file');
  const files = new Map([['manifest.json', bytes]]);
  const checksum = await regular(root, 'dataset.sha256');
  if (checksum.toString() !== `${pins[id]}  manifest.json\n`) throw Error('Checksum mismatch');
  files.set('dataset.sha256', checksum);
  for (const a of m.assets) {
    const content = await regular(root, a.path);
    if (content.length !== a.bytes || digest(content) !== a.sha256) throw Error('Asset hash/size mismatch');
    files.set(a.path, content);
  }
  // P4b already removed paths/personal fields. Preserve qualified bytes and pins.
  if (/\/home\/|\/tmp\/|mailto:|https?:\/\/|password|token|secret|hostname/i.test(bytes.toString())) throw Error('Unexpected private field in manifest');
  return files;
}
export async function inspectSite(root) {
  const files = new Map();
  const required = ['index.html','replay.html','404.html','_headers','_redirects','robots.txt','THIRD_PARTY_NOTICES.txt'];
  for (const name of required) files.set(name, await regular(root, name));
  if ((await readdir(root)).some(n => ![...required, 'assets'].includes(n))) throw Error('Unexpected site file');
  const assets = await readdir(resolve(root, 'assets'));
  if (!assets.length || assets.some(n => !/^[a-zA-Z0-9_-]+\.(js|css)$/.test(n))) throw Error('Unexpected compiled asset');
  for (const name of assets) files.set(`assets/${name}`, await regular(root, `assets/${name}`));
  for (const [name, bytes] of files) if (/\.(js|html|css)$/.test(name) && /\/api\/v1|WebSocket\s*\(|@vite\/client|\/home\/|\.mcap|useTelemetry|useControlCenter/.test(bytes.toString())) throw Error('Operational/private content in website');
  return files;
}
export function exposure(path) {
  if (/^__local_v2\/w0[1-6]\/manifest\.json$/.test(path)) return 'Sanitised Warehouse Benchmark v1 provenance: opaque campaign/trial/run/report IDs, source hashes (private recorder and launch logs are hashed, never included), ROS times, map/mission/profile/parameters, original metrics/verdicts, exploratory not-qualified status, teardown and recorder-loss disclosures, conditions and limitations. Publication flag remains private.';
  if (path.includes('/manifest.json')) return 'Sanitised v2 provenance: opaque campaign/trial/run/report IDs, source hashes, ROS times, map/mission/profile/parameters, original metrics/verdicts, conditions and limitations. Not raw report; publication flag remains private.';
  if (path.includes('/dataset.sha256')) return 'Integrity hash of the exact v2 manifest; not a signature or publication approval.';
  if (path.endsWith('/map.pgm.gz')) return 'Derived simulated occupancy map with obstacle layout; geometry disclosed.';
  if (/\/poses-/.test(path)) return 'Downsampled recorded localised TF trajectory, exact source stamps/transform references and explicit missing samples.';
  if (/\/scans-/.test(path)) return 'Downsampled recorded LiDAR ranges, source stamps, supported transforms and gaps.';
  if (path.startsWith('assets/')) return 'Compiled presentation/replay/validation code or styles, schema and dataset allowlist pins. No operational entry or recorded telemetry embedded.';
  if (path === 'THIRD_PARTY_NOTICES.txt') return 'Runtime dependency names, versions, MIT copyright and licence notices.';
  if (path.startsWith('_')) return 'Static host routing/security configuration only.';
  return 'Portfolio/lab page shell, draft wording, owner-supplied GitHub link, error page or no-index robots directive.';
}
export async function stage(output) {
  const web = resolve(dirname(fileURLToPath(import.meta.url)), '..'), repo = resolve(web, '..');
  output = resolve(output);
  if (!output.startsWith(resolve(repo, 'artifacts') + '/') || relative(repo, output).split('/').includes('..')) throw Error('Staging must remain in private artifacts');
  try { await lstat(output); throw Error('Output exists; refusing overwrite'); } catch (e) { if (e.code !== 'ENOENT') throw e; }
  const files = await inspectSite(resolve(web, 'dist/site'));
  for (const id of ['n0','n2']) for (const [name, bytes] of await inspectBundle(resolve(repo, `artifacts/p4b-export-20261011/dataset-${id}-final`), id)) files.set(`__local_v2/${id}/${name}`, bytes);
  for (const id of warehouseIds) for (const [name, bytes] of await inspectBundle(resolve(repo, `artifacts/warehouse-lab-20261013/dataset-${id}-final`), id)) files.set(`__local_v2/${id}/${name}`, bytes);
  // Finish all validation before creating output. New output only, never history.
  await mkdir(output, { mode: 0o700 });
  for (const [name, bytes] of files) { await mkdir(dirname(join(output, name)), {recursive:true, mode:0o700}); await writeFile(join(output, name), bytes, {flag:'wx',mode:0o600}); }
  const inventory = [...files].sort(([a],[b])=>a.localeCompare(b)).map(([path,bytes])=>({path,bytes:bytes.length,sha256:digest(bytes),exposes:exposure(path)}));
  const manifest = { status:'PRIVATE_CANDIDATE_NOT_APPROVED_FOR_PUBLICATION', datasets:['N0 v2','N2 v2',...warehouseIds.map(id=>`${id.toUpperCase()} warehouse v1`)], unchanged_manifest_pins:pins, total_bytes:inventory.reduce((n,f)=>n+f.bytes,0), files:inventory };
  // Inventory outside served directory, self-hash intentionally not recursive.
  await writeFile(output + '-manifest.json', JSON.stringify(manifest,null,2)+'\n', {flag:'wx',mode:0o600});
  console.log(`Private staged candidate: ${inventory.length} files, ${manifest.total_bytes} bytes. NO publication approval.`);
  return manifest;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 4 || process.argv[2] !== '--output') throw Error('Usage: node scripts/stage-release.mjs --output <new private artifacts directory>');
  await stage(process.argv[3]);
}
