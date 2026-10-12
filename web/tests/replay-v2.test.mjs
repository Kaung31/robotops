import assert from 'node:assert/strict';
import { readFile, access, readdir } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import * as jsx from 'react/jsx-runtime';
function compile(source, imports={}) {
  const {outputText}=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}});
  const module={exports:{}};
  new Function('require','module','exports',outputText)(name=>{assert(name in imports,`Unexpected dependency ${name}`);return imports[name];},module,module.exports);
  return module.exports;
}
const read=async file=>readFile(new URL(file,import.meta.url),'utf8');
const v1schema=JSON.parse(await read('../src/replay/schema-v1.json'));
const v2schema=JSON.parse(await read('../src/replay/schema-v2.json'));
const engine=compile(await read('../src/replay/data.ts'),{'./schema-v1.json':{default:v1schema}});
const loader=compile(await read('../src/replay/data-v2.ts'),{'./data':engine,'./schema-v2.json':{default:v2schema}});
const selection=compile(await read('../src/replay/selection.ts'));
const compare=compile(await read('../src/replay/comparison.ts'),{'./data':engine});
const {ComparisonPanel}=compile(await read('../src/replay/ComparisonPanel.tsx'),{'react/jsx-runtime':jsx,'./comparison':compare,'./data':engine});
const validation=compile(await read('../src/replay/validation.ts'),{'./data':engine});

const pending=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const synthetic=id=>({manifest:{dataset_id:id},poses:[{transform:'test'}],scans:[{}]});
test('selection synchronously clears all scene/results by publishing null data, then only selected result',async()=>{
  const request=pending(),events=[];const ctrl=selection.createSelection(()=>request.promise,s=>events.push(s));
  const load=ctrl.select('N2');assert.deepEqual(events[0],{id:'N2',generation:1,phase:'loading',data:null,error:null});
  request.resolve(synthetic('N2'));await load;assert.equal(events.at(-1).phase,'ready');assert.equal(events.at(-1).data.manifest.dataset_id,'N2');ctrl.dispose();
});
test('rapid N0→N2→N0 switching rejects delayed successes even when loader ignores abort',async()=>{
  const requests=[],events=[];const ctrl=selection.createSelection((id,signal)=>{const p=pending();requests.push({...p,id,signal});return p.promise;},s=>events.push(s));
  const a=ctrl.select('N0'),b=ctrl.select('N2'),c=ctrl.select('N0');
  assert(requests[0].signal.aborted);assert(requests[1].signal.aborted);
  requests[2].resolve(synthetic('N0'));await c;const ready=events.at(-1);
  requests[1].resolve(synthetic('N2'));requests[0].resolve(synthetic('N0'));await Promise.all([a,b]);assert.equal(events.at(-1),ready);assert.equal(ready.generation,3);
});
test('stale failures cannot replace selected success; current failure never restores old data',async()=>{
  const requests=[],events=[];const ctrl=selection.createSelection(()=>{const p=pending();requests.push(p);return p.promise;},s=>events.push(s));
  const a=ctrl.select('N0'),b=ctrl.select('N2');requests[1].resolve(synthetic('N2'));await b;requests[0].reject(Error('late'));await a;assert.equal(events.at(-1).phase,'ready');
  const c=ctrl.select('N0');assert.equal(events.at(-1).data,null);requests[2].reject(Error('unavailable'));await c;assert.equal(events.at(-1).phase,'error');assert.equal(events.at(-1).data,null);assert.match(events.at(-1).error,/unavailable/);
});
test('unmount ignores completion; selected-identity mismatch fails closed',async()=>{
  const request=pending(),events=[];const ctrl=selection.createSelection(()=>request.promise,s=>events.push(s));const p=ctrl.select('N0');ctrl.dispose();request.resolve(synthetic('N0'));await p;assert.equal(events.length,1);
  const bad=selection.createSelection(async()=>synthetic('N2'),s=>events.push(s));await bad.select('N0');assert.equal(events.at(-1).phase,'error');assert.match(events.at(-1).error,/identity/);
});
test('source schema parity and strict unsupported version/type/field rejection',async()=>{
  assert.equal(await read('../src/replay/schema-v2.json'),await read('../../scripts/replay-schema-v2.json'));
  for(const id of ['N1','N3','../N0','https://example.com','n0',''])assert.throws(()=>loader.datasetId(id));
  for(const v of [{schema_version:1},{schema_version:3},{schema_version:2,dataset_id:'N3'}])assert.throws(()=>engine.validate(v,v2schema.ManifestV2));
});
const metric=(name,value,unit,category)=>({name,value,unit,quality:'ORIGINAL_VERIFIED',source_ref:'report',pointer:`/campaign/trials/0/evidence/${category}/${name}`});
const fakeOriginal={N0:{metrics:[metric('mission_ros_seconds',10,'s','metrics'),metric('odom_path_metres',2,'m','metrics'),metric('xy_error_m',.2,'m','validation'),metric('yaw_error_rad',.1,'rad','validation')]},N2:{metrics:[metric('mission_ros_seconds',12,'s','metrics'),metric('odom_path_metres',1.5,'m','metrics'),metric('xy_error_m',.15,'m','validation'),metric('yaw_error_rad',.1,'rad','validation')]}};
test('signed differences are full precision N2 minus N0; SI units and rounded display only',()=>{
  const rows=compare.comparisonRows(fakeOriginal);assert.deepEqual(rows.map(r=>r.difference),[2,-.5,.15-.2,0]);
  assert.equal(compare.showNumber(rows[0].difference,3,'s',true),'+2.000 s');assert.equal(compare.showNumber(rows[1].difference,4,'m',true),'-0.5000 m');
  assert.equal(compare.showNumber(null,3,'s'),'Unavailable');
});
test('missing, conflicting-unit, duplicate, unqualified and non-comparable measurements remain unavailable',()=>{
  for(const change of [{value:null},{value:NaN},{value:'1'},{unit:'cm'},{quality:'UNKNOWN'},{pointer:'/display'},{source_ref:'graphics'}]){
    const values=structuredClone(fakeOriginal);Object.assign(values.N2.metrics[2],change);const row=compare.comparisonRows(values)[2];assert.equal(row.n2,null);assert.equal(row.difference,null);
  }
  const values=structuredClone(fakeOriginal);values.N2.metrics.push(values.N2.metrics[0]);assert.equal(compare.comparisonRows(values)[0].difference,null);
  assert(compare.comparisonRows({}).every(r=>r.difference===null));
});
test('comparison renders honest labels, categorical results separate and unavailable data without winner',()=>{
  const html=renderToStaticMarkup(React.createElement(ComparisonPanel,{originals:{},error:''}));
  for(const text of ['Compare recorded experiments','Observational repeated baselines','Δ N2 − N0','Original ROS navigation outcome','Independent pose verification','Scoped contact observation','Recording coverage','Unavailable','random seeds','localisation initialisation','Planning latency'])assert(html.includes(text));
  assert.equal((html.match(/<details/g)||[]).length,1);assert.doesNotMatch(html,/winner score:|superior|best profile/i);
  assert.match(html,/saved ExecuteMission|Saved ExecuteMission/);
});
test('composition keys entire replay scene/visitor form to selection generation; no old data rendered in loading branch',async()=>{
  const source=await read('../src/replay/main.tsx');assert.match(source,/state\.phase !== "ready"/);assert.match(source,/key=\{`\$\{state\.id\}:\$\{state\.generation\}`\}/);
  assert.match(source,/previous robot, LiDAR, trajectory and visitor results cleared/);
  assert.match(source,/loadDatasetV2\(id, fetch, signal\)/);assert.doesNotMatch(source,/loadN0\(/);
});
let available=process.env.ROBOTOPS_SKIP_PRIVATE!=='1';
const folder=id=>new URL(`../../artifacts/p4b-export-20261011/dataset-${id.toLowerCase()}-final/`,import.meta.url);
try{await access(new URL('manifest.json',folder('N2')));}catch{available=false;}
const fetcher=async url=>{const match=/^\/__local_v2\/(n0|n2)\/([a-z0-9.-]+)$/.exec(url);assert(match,`Unexpected fetch ${url}`);return new Response(await readFile(new URL(match[2],folder(match[1].toUpperCase()))));};
test('private N0/N2 v2 fixtures available',{skip:available?false:'Private v2 fixtures intentionally absent'},()=>assert(available));
if(available){
  const datasets={N0:await loader.loadDatasetV2('N0',fetcher),N2:await loader.loadDatasetV2('N2',fetcher)};
  for(const id of ['N0','N2']){
    test(`${id} v2 pin, provenance, sample count and exact original metric checks`,()=>{
      const d=datasets[id];assert.equal(d.manifest.schema_version,2);assert.equal(d.manifest.dataset_id,id);assert.equal(d.poses.length,loader.DATASETS[id].poses);assert.equal(d.scans.length,loader.DATASETS[id].scans);
      assert.equal(d.manifest.original_validation.action_status,4);assert.equal(d.manifest.original_validation.mission_action.scope,'SAVED_MISSION_ACTION_RESULT_SNAPSHOT');
      assert(Object.isFrozen(d.manifest));const before=JSON.stringify(d.manifest);
      for(const c of validation.CHECKS){const m=d.manifest.metrics.find(m=>m.name===c.metric);assert.equal(validation.visitorCheck(c.id,d.manifest.metrics,String(m.value),d.trusted).outcome,'PASS');assert.equal(validation.visitorCheck(c.id,d.manifest.metrics,String(m.value-1e-12),d.trusted).outcome,'FAIL');assert.equal(validation.visitorCheck(c.id,d.manifest.metrics,'',d.trusted).outcome,'UNKNOWN');}
      assert.equal(JSON.stringify(d.manifest),before);
    });
    test(`${id} replay uses its own ROS epoch and preserves head/tail/TF gaps and scans`,()=>{
      const d=datasets[id];for(const ns of [d.manifest.time.mission_start_ns,d.manifest.time.recorded_start_ns,d.manifest.time.mission_end_ns])assert.equal(engine.poseAt(d,BigInt(ns)),null);
      const first=d.poses.find(p=>p.transform);assert.deepEqual(engine.poseAt(d,BigInt(first.ros_ns)),first.transform);
      const scan=d.scans.find(s=>s.map_base);assert(engine.scanPoints(scan).length>0);assert.equal(engine.scanAt(d,BigInt(d.manifest.time.mission_end_ns)),null);
      assert.equal(d.manifest.coverage.full_mission_replay,false);assert.equal(d.manifest.original_validation.final_pose_is_playback_sample,false);
    });
    test(`${id} missing/tampered assets and wrong manifest fail closed`,async()=>{
      await assert.rejects(loader.loadDatasetV2(id,async()=>new Response('missing',{status:404})),/unavailable/);
      await assert.rejects(loader.loadDatasetV2(id,async()=>new Response('{}')),/manifest/);
      await assert.rejects(loader.loadDatasetV2(id,async url=>url.endsWith('manifest.json')?fetcher(url):new Response('corrupt')),/Corrupt|size/);
      await assert.rejects(loader.loadDatasetV2(id,async url=>fetcher(url.replace(id.toLowerCase(),id==='N0'?'n2':'n0'))),/manifest/);
    });
  }
  test('actual comparison values and condition hash matches retain precision and original verdicts',()=>{
    const originals={N0:datasets.N0.manifest,N2:datasets.N2.manifest},before=JSON.stringify(originals),rows=compare.comparisonRows(originals);
    assert.equal(rows[0].difference,20.937-20.668);assert.equal(rows[1].difference,1.5912764637507903-1.5568730774647175);assert.equal(rows[2].difference,.14142858354404214-.15552255266952078);assert.equal(rows[3].difference,.03867569747578893-.0541354424180002);
    const html=renderToStaticMarkup(React.createElement(ComparisonPanel,{originals,error:''}));assert.match(html,/20.668 s/);assert.match(html,/20.937 s/);assert.match(html,/\+0.269 s/);assert.match(html,/POSE_VERIFIED/);assert.match(html,/NO_CONTACT_OBSERVED/);assert.match(html,/matches/);assert.equal(JSON.stringify(originals),before);
  });
  test('strict v2 schema rejects malformed identity, units, status scopes, pointers and extra fields',()=>{
    for(const mutate of [m=>m.schema_version=1,m=>m.dataset_id='N3',m=>m.time.mission_start_ns=4031000000,m=>m.extra='/home/private',m=>m.original_validation.mission_action.recorded_action_stream=true,m=>m.metrics[0].unit='cm',m=>m.metrics[0].pointer='/graphics']){
      const m=structuredClone(datasets.N0.manifest);mutate(m);assert.throws(()=>engine.validate(m,v2schema.ManifestV2));
    }
  });
}
test('read-only replay dependency graph and private server keep explicit boundary',async()=>{
  for(const file of await readdir(new URL('../src/replay/',import.meta.url))){if(!/\.tsx?$/.test(file))continue;assert.doesNotMatch(await read(`../src/replay/${file}`),/useTelemetry|useControlCenter|useCampaigns|lib\/api|new WebSocket|\/api\/v1/);}
  const server=await read('../scripts/serve-replay.mjs');assert.match(server,/127\.0\.0\.1/);assert.match(server,/n0\|n2/);assert.match(server,/names\.has/);assert.match(server,/server\.on\("upgrade"/);assert.doesNotMatch(server,/createReadStream|serve-static/);
});
