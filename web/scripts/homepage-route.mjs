// Derives the homepage route figure from the pinned W01 dataset: its localized
// map-frame display poses, kept at least SPACING_M apart and rounded to 1 cm.
// Offline only; the website embeds the result and never reads private paths.
import { readFile } from 'node:fs/promises';
import { gunzipSync } from 'node:zlib';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { digest, pins } from './stage-release.mjs';
export const SPACING_M = 0.25;
export async function deriveRoute(dir) {
  const bytes = await readFile(resolve(dir, 'manifest.json'));
  if (digest(bytes) !== pins.w01) throw Error('Unapproved W01 manifest');
  const points = [];
  for (const asset of JSON.parse(bytes).assets.filter(a => a.path.startsWith('poses-'))) {
    const chunk = await readFile(resolve(dir, asset.path));
    if (digest(chunk) !== asset.sha256) throw Error('Corrupt W01 pose chunk');
    for (const s of JSON.parse(gunzipSync(chunk)).samples) if (s.quality === 'SUPPORTED_TF' && s.transform && s.frame === 'map') points.push(s.transform.position.slice(0, 2));
  }
  const route = [points[0]];
  for (const p of points.slice(1)) { const q = route.at(-1); if (Math.hypot(p[0] - q[0], p[1] - q[1]) >= SPACING_M) route.push(p); }
  if (route.at(-1) !== points.at(-1)) route.push(points.at(-1));
  // + 0 turns a rounded -0 into 0, matching the JSON-generated module.
  return route.map(([x, y]) => [Number(x.toFixed(2)) + 0, Number(y.toFixed(2)) + 0]);
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 3) throw Error('Usage: node scripts/homepage-route.mjs <W01 dataset directory>');
  console.log(JSON.stringify(await deriveRoute(process.argv[2])));
}
