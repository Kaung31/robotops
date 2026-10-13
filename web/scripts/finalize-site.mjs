import { readFile, writeFile, rename, copyFile, readdir } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
const web = resolve(dirname(fileURLToPath(import.meta.url)), '..'), out = resolve(web, 'dist/site');
await rename(resolve(out, 'portfolio.html'), resolve(out, 'index.html'));
for (const name of ['_headers', '_redirects', '404.html']) await copyFile(resolve(web, 'release-config', name), resolve(out, name));
// Deliberately no dataset copy: clean builds need only the source lockfile.
await writeFile(resolve(out, 'robots.txt'), 'User-agent: *\nDisallow: /\n');
let notices = 'RobotOps private release candidate — publication not approved.\nProject source/dataset licence decisions remain with the owner.\n\nBundled runtime dependencies and their notices:\n';
for (const name of ['react', 'react-dom', 'scheduler', 'three']) {
  const pkg = JSON.parse(await readFile(resolve(web, 'node_modules', name, 'package.json'), 'utf8'));
  notices += `\n--- ${name} ${pkg.version} (${pkg.license}) ---\n${await readFile(resolve(web, 'node_modules', name, 'LICENSE'), 'utf8')}`;
}
// Vite injects its MIT module-preload polyfill into the site code; include only
// its core notice, not the licences of Vite's own build-time dependencies.
const vite = JSON.parse(await readFile(resolve(web, 'node_modules', 'vite', 'package.json'), 'utf8'));
const viteLicence = (await readFile(resolve(web, 'node_modules', 'vite', 'LICENSE.md'), 'utf8')).split('\n# Licenses of bundled dependencies')[0];
notices += `\n--- vite ${vite.version} module-preload polyfill (${vite.license}) ---\n${viteLicence.trim()}\n`;
await writeFile(resolve(out, 'THIRD_PARTY_NOTICES.txt'), notices);
const entries = await readdir(out);
if (entries.some(name => !['index.html', 'replay.html', 'assets', '_headers', '_redirects', '404.html', 'robots.txt', 'THIRD_PARTY_NOTICES.txt'].includes(name))) throw Error('Unexpected site output');
console.log('Code-only static website prepared; recordings absent, publication blocked.');
