import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import * as jsx from 'react/jsx-runtime';
// Compiles a TS/TSX module and its relative imports; React is the only package allowed.
const loaded = new Map();
async function load(path) {
  const url = path instanceof URL ? path : new URL(path, import.meta.url);
  if (loaded.has(url.href)) return loaded.get(url.href);
  const compiled = ts.transpileModule(await readFile(url, 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const deps = {};
  for (const [, name] of compiled.matchAll(/require\("([^"]+)"\)/g)) {
    if (name === 'react/jsx-runtime') deps[name] = jsx; else if (name === 'react') deps[name] = React;
    else { assert(name.startsWith('.'), `Unexpected dependency ${name}`); let dep; for (const ext of ['.tsx', '.ts']) try { dep = await load(new URL(name + ext, url)); break; } catch (e) { if (e.code !== 'ENOENT') throw e; } assert(dep, `Unresolved ${name}`); deps[name] = dep; }
  }
  const m = { exports: {} }; new Function('require', 'module', 'exports', compiled)(n => deps[n], m, m.exports); loaded.set(url.href, m.exports); return m.exports;
}
const render = (component, props = {}, ...children) => renderToStaticMarkup(React.createElement(component, props, ...children));
const lab = await load('../src/replay/LabSections.tsx');

test('lab introduction leads through the five-step journey, then the separate baselines', () => {
  const html = render(lab.LabIntro, { status: 'Private release candidate · not published', overview: true });
  assert.equal((html.match(/<h1/g) || []).length, 1);
  const order = [...html.matchAll(/href="#([a-z]+)"/g)].map(m => m[1]);
  assert.deepEqual(order, ['experiment', 'results', 'replay', 'compare', 'evidence', 'baselines']);
  for (const text of ['The experiment', 'Results', 'Watch the robot', 'Compare configurations', 'Inspect the evidence', 'Earlier baseline experiments', 'Read-only: no robot, simulator or server connected', 'Private release candidate · not published', 'Read the project overview']) assert(html.includes(text), text);
  assert.doesNotMatch(render(lab.LabIntro, { status: 'x', overview: false }), /project overview/);
});
test('experiment section explains both configurations and carries every benchmark disclosure', () => {
  const html = render(lab.ExperimentSection);
  for (const text of ['A mission succeeds only when all five goals are reached', 'NavFn + Regulated Pure Pursuit', 'Smac 2D + DWB', 'AB/BA/AB', 'limits 0.20 m and 0.25 rad', 'never entered the 1.2 m aisles', 'Three trials per configuration', 'planner and the controller both differ', 'Not formally qualified', 'W3/W4', 'simulator ground truth was not recorded', 'Gazebo crashed while the stack shut down']) assert(html.includes(text), text);
});
test('earlier baselines are separate, observational and flagged as partial recordings', () => {
  const html = render(lab.BaselinesSection, { selected: 'N2', onReplay: () => undefined }, React.createElement('p', null, 'comparison fixture'));
  for (const text of ['Earlier baseline experiments', 'not an algorithm comparison', 'Partial recordings', 'Replay N0 in the player', 'Showing N2', 'comparison fixture']) assert(html.includes(text), text);
  const banner = render(lab.BaselineBanner, { id: 'N0' });
  for (const text of ['Earlier baseline N0', 'Not part of Warehouse Navigation Benchmark v1', 'not an algorithm comparison', 'Partial recording']) assert(banner.includes(text), text);
});
test('shared header and footer link both pages, mark the current page and show release status', async () => {
  const chrome = await load('../src/site/SiteChrome.tsx'), { RELEASE } = await load('../src/site/release.ts');
  const header = render(chrome.SiteHeader, { current: 'lab' });
  assert.match(header, /href="\/"/); assert.match(header, /href="\/replay.html" aria-current="page"/); assert.match(header, /href="\/#benchmark"/);
  assert.doesNotMatch(render(chrome.SiteHeader, { current: 'home' }), /aria-current/);
  const footer = render(chrome.SiteFooter);
  assert(footer.includes(RELEASE.status)); assert.match(footer, /THIRD_PARTY_NOTICES\.txt/);
  assert.equal(RELEASE.datasetLicence === null, !/Dataset licence/.test(footer));
  for (const html of [header, footer]) assert.doesNotMatch(html, /\/api\/|ws:|localhost|127\.0\.0\.1|mailto:/);
});
test('strip chart states every value, mean and axis range in its accessible summary', async () => {
  const { StripChart } = await load('../src/site/StripChart.tsx');
  const html = render(StripChart, { title: 'Mission time', unit: 's', digits: 2, min: 131, max: 139, ticks: [131, 135, 139], tickDigits: 0, references: [{ value: 138, label: 'Limit' }],
    groups: [{ id: 'navfn_rpp', label: 'NavFn + RPP', values: [{ id: 'W01', value: 137.372 }, { id: 'W04', value: 137.861 }] }, { id: 'smac_dwb', label: 'Smac 2D + DWB', values: [{ id: 'W02', value: 132.936 }] }] });
  const label = /role="img" aria-label="([^"]+)"/.exec(html)[1];
  for (const text of ['W01 137.37 s', 'W04 137.86 s', 'mean 137.62 s', 'W02 132.94 s', 'Axis 131.00 s to 139.00 s', 'Limit 138.00 s']) assert(label.includes(text), text);
});
