import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,mkdtemp,writeFile,mkdir,cp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import * as jsx from 'react/jsx-runtime';
import ts from 'typescript';
import {inspectBundle,inspectSite,stage,exposure,pins} from '../scripts/stage-release.mjs';
const read=async path=>readFile(new URL(path,import.meta.url),'utf8');
test('portfolio is honest, semantic and uses approved repository link without live imports',async()=>{
 const source=await read('../src/portfolio/Portfolio.tsx');
 const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 const m={exports:{}};new Function('require','module','exports',compiled)(name=>{assert.equal(name,'react/jsx-runtime');return jsx;},m,m.exports);
 const html=renderToStaticMarkup(React.createElement(m.exports.Portfolio));
 for(const value of ['Explore Recorded Lab','ROS 2','Gazebo','Nav2','FastAPI','SQLite','Three.js','Draft','awaiting approval','https://github.com/Kaung31/robotops','not a controlled algorithm ranking','not published'])assert(html.includes(value),value);
 assert.equal((html.match(/<h1/g)||[]).length,1);assert.match(html,/<main id="main"/);assert.match(html,/href="\/replay.html"/);
 assert.doesNotMatch(source,/fetch\(|WebSocket\s*\(|useTelemetry|useControlCenter|from .*App/);
});
test('site build is a separate code-only multipage entry with no proxy/public assets',async()=>{
 const source=await read('../vite.site.config.ts');assert.match(source,/publicDir: false/);assert.match(source,/portfolio.html/);assert.match(source,/replay.html/);assert.doesNotMatch(source,/proxy\s*:|index.html/);
 const finalize=await read('../scripts/finalize-site.mjs');assert.doesNotMatch(finalize,/artifacts\/|p4b-export/);assert.match(finalize,/robots.txt/);
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
  await mkdir(join(temp,'assets'));await writeFile(join(temp,'assets','site.js'),'static code');assert.equal((await inspectSite(temp)).size,8);
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
