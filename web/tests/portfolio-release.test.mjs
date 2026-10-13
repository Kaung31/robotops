import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,mkdtemp,writeFile,mkdir,cp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import * as jsx from 'react/jsx-runtime';
import ts from 'typescript';
import {inspectBundle,inspectSite,stage,exposure,pins,warehouseIds,expectedAssets} from '../scripts/stage-release.mjs';
const read=async path=>readFile(new URL(path,import.meta.url),'utf8');
// Compiles a TS/TSX module and its relative imports; React is the only package allowed.
const loaded=new Map();
async function load(url){
 if(loaded.has(url.href))return loaded.get(url.href);
 const compiled=ts.transpileModule(await readFile(url,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 const deps={};
 for(const [,name] of compiled.matchAll(/require\("([^"]+)"\)/g)){
  if(name==='react/jsx-runtime')deps[name]=jsx;else if(name==='react')deps[name]=React;
  else{assert(name.startsWith('.'),`Unexpected dependency ${name}`);let dep;for(const ext of ['.tsx','.ts'])try{dep=await load(new URL(name+ext,url));break;}catch(e){if(e.code!=='ENOENT')throw e;}assert(dep,`Unresolved ${name}`);deps[name]=dep;}
 }
 const m={exports:{}};new Function('require','module','exports',compiled)(n=>deps[n],m,m.exports);loaded.set(url.href,m.exports);return m.exports;
}
test('homepage explains RobotOps, features benchmark v1 with every disclosure, and stays static',async()=>{
 const source=await read('../src/portfolio/Portfolio.tsx');
 const {Portfolio}=await load(new URL('../src/portfolio/Portfolio.tsx',import.meta.url));
 const html=renderToStaticMarkup(React.createElement(Portfolio));
 for(const value of ['Robotics,','evidence.','ROS 2 experimentation and evaluation platform','Explore the Recorded Lab','Warehouse Navigation Benchmark v1','137.67 s','132.78 s','3.2°','11.0°','6/6','5/5','4.9 s (3.6%) faster','Gazebo','Nav2','RViz','Foxglove','FastAPI','SQLite','Three.js','ros2_control','C++','https://github.com/Kaung31/robotops','datasets CC BY 4.0','href="/DATA-LICENSE.txt"',
  'never entered the 1.2 m aisles','Three trials per configuration','planner and the controller both differ','Not formally qualified','W3/W4','simulator ground truth was not recorded','W03 teardown crash','Not done yet','not implemented'])assert(html.includes(value),value);
 for(const banned of [/Draft/,/awaiting approval/i,/not published|release candidate/i,/@gmail|mailto:/i,/superior(?!ity)/i,/statistically significant/i,/best (configuration|planner)/i,/winner/i])assert.doesNotMatch(html,banned);
 assert.equal((html.match(/<h1/g)||[]).length,1);assert.match(html,/<main id="main"/);assert.match(html,/href="\/replay.html"/);
 const levels=[...html.matchAll(/<h([1-6])/g)].map(m=>+m[1]);assert(levels.every((l,i)=>i===0||l<=levels[i-1]+1),`heading levels skip: ${levels}`);
 assert.doesNotMatch(source,/fetch\(|WebSocket\s*\(|useTelemetry|useControlCenter|from .*App/);
});
test('homepage route figure is the recorded W01 route and never enters an aisle',async()=>{
 const {W01_ROUTE}=await load(new URL('../src/portfolio/w01-route.ts',import.meta.url));
 assert(W01_ROUTE.length>50);assert.deepEqual([...W01_ROUTE[0]],[0,0]);
 // Racks are 0.8 m wide at x = 2, 4, 6 and span y 1.5-5.5 m: aisles are x 2.4-3.6 and 4.4-5.6.
 assert.deepEqual(W01_ROUTE.filter(([x,y])=>((x>2.4&&x<3.6)||(x>4.4&&x<5.6))&&y>1.5&&y<5.5),[]);
});
test('site build is a separate code-only multipage entry with no proxy/public assets',async()=>{
 const source=await read('../vite.site.config.ts');assert.match(source,/publicDir: false/);assert.match(source,/portfolio.html/);assert.match(source,/replay.html/);assert.doesNotMatch(source,/proxy\s*:|index.html/);
 const finalize=await read('../scripts/finalize-site.mjs');assert.doesNotMatch(finalize,/artifacts\/|p4b-export/);assert.match(finalize,/robots.txt/);assert.match(finalize,/module-preload polyfill/);assert.match(finalize,/Licenses of bundled dependencies/);assert.match(finalize,/'DATA-LICENSE.txt', 'RELEASE.json'\]\) await copyFile/);assert.doesNotMatch(finalize,/publication not approved/);assert.match(finalize,/'User-agent: \*\\nAllow: \/\\n'/);assert.doesNotMatch(finalize,/Disallow/);assert.match(finalize,/@rollup\\\/plugin-commonjs/);
 assert.match(await read('../release-config/_headers'),/connect-src 'self'/);assert.equal(await read('../release-config/_redirects'),'/lab /replay.html 302\n/lab/ /replay.html 302\n');
});
test('stager forbids public/output reuse and unknown dataset, exposes inventory categories',async()=>{
 await assert.rejects(stage('/tmp/robotops-public'),/private artifacts/);await assert.rejects(inspectBundle('/tmp','n3'),/Unapproved dataset/);
 for(const name of ['__local_v2/n0/manifest.json','__local_v2/n2/dataset.sha256','__local_v2/n0/map.pgm.gz','__local_v2/n0/poses-000.json.gz','__local_v2/n2/scans-000.json.gz','assets/site.js','THIRD_PARTY_NOTICES.txt','_headers','index.html'])assert(exposure(name).length>30);
});
test('site inspector fails closed on missing files and unintended artifacts',async()=>{
 const temp=await mkdtemp(join(tmpdir(),'robotops-site-'));
 try {
  await assert.rejects(inspectSite(temp));
  for(const name of ['index.html','replay.html','404.html','_headers','_redirects','robots.txt','THIRD_PARTY_NOTICES.txt'])await writeFile(join(temp,name),'shell');
  for(const name of ['DATA-LICENSE.txt','RELEASE.json'])await cp(new URL(`../release-config/${name}`,import.meta.url),join(temp,name));
  await mkdir(join(temp,'assets'));await writeFile(join(temp,'assets','site.js'),'static code');assert.equal((await inspectSite(temp)).size,10);
  const release=JSON.parse(await readFile(join(temp,'RELEASE.json'),'utf8'));release.datasets.W03='0'.repeat(64);await writeFile(join(temp,'RELEASE.json'),JSON.stringify(release));await assert.rejects(inspectSite(temp),/Release record/);
  await cp(new URL('../release-config/RELEASE.json',import.meta.url),join(temp,'RELEASE.json'));await writeFile(join(temp,'DATA-LICENSE.txt'),'DRAFT CC BY 4.0');await assert.rejects(inspectSite(temp),/Dataset licence/);
  await cp(new URL('../release-config/DATA-LICENSE.txt',import.meta.url),join(temp,'DATA-LICENSE.txt'));
  await writeFile(join(temp,'private.mcap'),'private');await assert.rejects(inspectSite(temp),/Unexpected site/);await rm(join(temp,'private.mcap'));
  await writeFile(join(temp,'assets','site.js'),'new WebSocket("control")');await assert.rejects(inspectSite(temp),/Operational/);
 }finally{await rm(temp,{recursive:true,force:true});}
});
let available=process.env.ROBOTOPS_SKIP_PRIVATE!=='1';const fixtures=resolve(new URL('../../artifacts/p4b-export-20261011/',import.meta.url).pathname);
try{await readFile(join(fixtures,'dataset-n2-final/manifest.json'));}catch{available=false;}
test('exact approved bundles survive staging inspection byte-for-byte',{skip:available?false:'Private bundles intentionally absent'},async()=>{
 for(const id of ['n0','n2']){const files=await inspectBundle(join(fixtures,`dataset-${id}-final`),id);assert.equal(files.size,8);assert.equal(files.get('dataset.sha256').toString(),`${pins[id]}  manifest.json\n`);}
});
test('bundle tampering/missing/extra files rejected without modifying original evidence',{skip:available?false:'Private bundles intentionally absent'},async()=>{
 const temp=await mkdtemp(join(tmpdir(),'robotops-bundle-'));
 try{
  const source=join(fixtures,'dataset-n0-final');await cp(source,temp,{recursive:true});await writeFile(join(temp,'poses-000.json.gz'),'tampered');await assert.rejects(inspectBundle(temp,'n0'),/hash\/size/);
  await cp(join(source,'poses-000.json.gz'),join(temp,'poses-000.json.gz'));await writeFile(join(temp,'private.txt'),'private');await assert.rejects(inspectBundle(temp,'n0'),/Unexpected source/);await rm(join(temp,'private.txt'));
  await rm(join(temp,'scans-000.json.gz'));await assert.rejects(inspectBundle(temp,'n0'));
 }finally{await rm(temp,{recursive:true,force:true});}
});

test('data inclusion is explicit candidate-only and fixed allowlist, not default build',async()=>{
 const p=JSON.parse(await read('../package.json'));assert(!p.scripts['build:site'].includes('include-candidate-data'));assert.match(p.scripts['build:candidate'],/include-candidate-data/);
 const s=await read('../scripts/include-candidate-data.mjs');assert.match(s,/inspectBundle/);assert.match(s,/candidate-data/);assert.match(s,/flag:'wx'/);assert.doesNotMatch(s,/fetch\(|process.env|process.argv/);
});

const warehouseFixtures=resolve(new URL('../../artifacts/warehouse-lab-20261013/',import.meta.url).pathname);
let warehouseAvailable=process.env.ROBOTOPS_SKIP_PRIVATE!=='1';
try{await readFile(join(warehouseFixtures,'dataset-w06-final/manifest.json'));}catch{warehouseAvailable=false;}
test('warehouse bundles: exact pinned inventories survive staging inspection; exposure is explicit',{skip:warehouseAvailable?false:'Private warehouse bundles intentionally absent'},async()=>{
 for(const id of warehouseIds){const files=await inspectBundle(join(warehouseFixtures,`dataset-${id}-final`),id);assert.equal(files.size,2+expectedAssets(id).length);assert.equal(files.get('dataset.sha256').toString(),`${pins[id]}  manifest.json\n`);}
 assert.match(exposure('__local_v2/w03/manifest.json'),/not-qualified/);assert.match(exposure('__local_v2/w03/manifest.json'),/never included/);
 const temp=await mkdtemp(join(tmpdir(),'robotops-warehouse-'));
 try{await cp(join(warehouseFixtures,'dataset-w03-final'),temp,{recursive:true});await rm(join(temp,'scans-006.json.gz'));await assert.rejects(inspectBundle(temp,'w03'));await assert.rejects(inspectBundle(join(warehouseFixtures,'dataset-w03-final'),'w04'),/Unapproved manifest/);}
 finally{await rm(temp,{recursive:true,force:true});}
});
test('homepage route and headline values re-derive from the pinned warehouse datasets',{skip:warehouseAvailable?false:'Private warehouse bundles intentionally absent'},async()=>{
 const {deriveRoute}=await import('../scripts/homepage-route.mjs');const {W01_ROUTE}=await load(new URL('../src/portfolio/w01-route.ts',import.meta.url));
 assert.deepEqual(await deriveRoute(join(warehouseFixtures,'dataset-w01-final')),W01_ROUTE.map(p=>[...p]));
 const b=await load(new URL('../src/portfolio/benchmark.ts',import.meta.url));
 const manifests=Object.fromEntries(await Promise.all(warehouseIds.map(async id=>[id.toUpperCase(),JSON.parse(await readFile(join(warehouseFixtures,`dataset-${id}-final`,'manifest.json'),'utf8'))])));
 const value=(m,name)=>m.metrics.find(x=>x.name===name).value;
 assert.deepEqual(b.TRIALS.map(t=>t.id),Object.keys(manifests));
 for(const t of b.TRIALS){const m=manifests[t.id];
  assert.equal(m.conditions.profile,t.profile);assert.equal(value(m,'mission_ros_seconds').toFixed(3),t.seconds.toFixed(3));assert.equal(value(m,'yaw_error_rad').toFixed(4),t.yaw.toFixed(4));assert.equal(value(m,'xy_error_m').toFixed(4),t.xy.toFixed(4));
  // A mission succeeds only when every waypoint is reached, so success + 5 waypoints = 5/5 goals.
  assert.equal(m.original_validation.ros_outcome,'succeeded');assert.equal(m.conditions.waypoints.length,b.HEADLINE.goals);
  assert.equal(m.original_validation.pose_verdict,'POSE_VERIFIED');assert.equal(m.original_validation.contact_verdict,'NO_CONTACT_OBSERVED');
  assert.equal(m.original_validation.pose_policy.xy_tolerance_m,b.LIMITS.xy);assert.equal(m.original_validation.pose_policy.yaw_tolerance_rad,b.LIMITS.yaw);}
 const stats=p=>{const ms=Object.values(manifests).filter(m=>m.conditions.profile===p),mean=n=>ms.reduce((a,m)=>a+value(m,n),0)/ms.length,s=ms.map(m=>value(m,'mission_ros_seconds'));return {seconds:mean('mission_ros_seconds'),min:Math.min(...s),max:Math.max(...s),yaw:mean('yaw_error_rad'),xy:mean('xy_error_m'),path:mean('odom_path_metres')};};
 for(const p of ['navfn_rpp','smac_dwb']){const x=stats(p),want=b.SUMMARY[p];
  assert.deepEqual([x.seconds.toFixed(2),x.min.toFixed(2),x.max.toFixed(2),x.yaw.toFixed(3),(x.yaw*180/Math.PI).toFixed(1),x.xy.toFixed(3),x.path.toFixed(2),(x.max-x.min).toFixed(2)],
   [want.seconds.toFixed(2),want.secondsMin.toFixed(2),want.secondsMax.toFixed(2),want.yawRad.toFixed(3),want.yawDeg.toFixed(1),want.xy.toFixed(3),want.path.toFixed(2),(p==='navfn_rpp'?b.HEADLINE.navfnSpread:b.HEADLINE.smacSpread).toFixed(2)]);}
 const nav=stats('navfn_rpp'),smac=stats('smac_dwb');
 assert.equal((nav.seconds-smac.seconds).toFixed(1),b.HEADLINE.faster.toFixed(1));assert.equal(((nav.seconds-smac.seconds)/nav.seconds*100).toFixed(1),b.HEADLINE.fasterPercent.toFixed(1));
 assert(smac.max<nav.min,'every Smac 2D + DWB trial finished sooner');
});
test('approved CC BY 4.0 licence and release record cover exactly the eight pinned datasets',async()=>{
 const licence=await read('../release-config/DATA-LICENSE.txt'),release=JSON.parse(await read('../release-config/RELEASE.json'));
 assert.match(licence,/Creative Commons\nAttribution 4\.0 International licence \(CC BY 4\.0\)/);assert.match(licence,/https:\/\/creativecommons\.org\/licenses\/by\/4\.0\/legalcode/);assert.doesNotMatch(licence,/DRAFT|NOT APPLIED/);
 for(const hash of Object.values(pins))assert(licence.includes(hash),hash);
 assert.equal(release.dataset_licence,'CC-BY-4.0');assert.equal(release.licence_approved_on,'2026-10-13');
 assert.deepEqual(Object.fromEntries(Object.entries(release.datasets).map(([k,v])=>[k.toLowerCase(),v])),{...pins});
 assert.doesNotMatch(licence+JSON.stringify(release),/@gmail|\/home\/|password|token/i);
});
