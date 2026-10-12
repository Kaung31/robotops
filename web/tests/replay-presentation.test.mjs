import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
function compile(source, imports = {}) {
  const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } });
  const module = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(name => { assert(name in imports, `Unexpected dependency ${name}`); return imports[name]; }, module, module.exports);
  return module.exports;
}
const presentation = compile(await readFile(new URL('../src/replay/presentation.ts', import.meta.url), 'utf8'));
const transform = { position: [0, 0, 0], quaternion: [0, 0, 0, 1] };
const fixture = { manifest: { time: { mission_start_ns: '0', mission_end_ns: '10000000000', recorded_start_ns: '1000000000', recorded_end_ns: '9000000000' }, segments: [{id:'s', start_ros_ns:'2000000000',end_ros_ns:'7000000000', interpolate_within_max_gap_ns: 1000000000}] }, poses: [2,3,6,7].map(t=>({ros_ns:String(t*1e9),segment_id:'s',frame:'map',quality:'SUPPORTED_TF',transform})) };
test('clock rounds for display only, including minute carry', ()=> { assert.equal(presentation.formatTime(20.668),'00:20.7'); assert.equal(presentation.formatTime(59.99),'01:00.0'); });
test('initial preview is an actual supported sample; empty coverage starts at head', ()=> { assert.equal(presentation.initialPreviewTime(fixture),6); assert.equal(presentation.initialPreviewTime({...fixture,poses:[]}),0); });
test('pattern bands distinguish unrecorded, recorded without pose, and supported intervals without bridging gaps', ()=> {
  assert.deepEqual(presentation.coverageBands(fixture), [
    {start:0,end:10,kind:'missing'},{start:10,end:20,kind:'recorded'}, {start:20,end:30,kind:'pose'}, {start:30,end:60,kind:'recorded'}, {start:60,end:70,kind:'pose'}, {start:70,end:90,kind:'recorded'}, {start:90,end:100,kind:'missing'}]);
});
test('coverage decoration refuses segment/frame/quality discontinuity and never mutates data', ()=> {
  const before=JSON.stringify(fixture);
  for (const change of [{segment_id:'other'}, {frame:'odom'}, {quality:'TF_UNAVAILABLE'}, {transform:null}]) {
    const d=structuredClone(fixture); Object.assign(d.poses[1],change);
    assert(!presentation.coverageBands(d).some(b=>b.kind==='pose'&&b.start===20));
  }
  assert.equal(JSON.stringify(fixture),before);
});
const schema = JSON.parse(await readFile(new URL('../src/replay/schema-v1.json', import.meta.url),'utf8'));
const engine = compile(await readFile(new URL('../src/replay/data.ts', import.meta.url),'utf8'), {'./schema-v1.json':schema});
const jsx = await import('react/jsx-runtime');
const validation = compile(await readFile(new URL('../src/replay/validation.ts',import.meta.url),'utf8'), {'./data':engine});
const panel = compile(await readFile(new URL('../src/replay/ValidationPanel.tsx',import.meta.url),'utf8'), {'react':React, 'react/jsx-runtime':jsx, './validation':validation});
let mapProps;
const {ReplayLab} = compile(await readFile(new URL('../src/replay/ReplayLab.tsx',import.meta.url),'utf8'), {'react':React, 'react/jsx-runtime':jsx, './data':engine, './presentation':presentation, './ValidationPanel':panel, '../components/MapView':{MapView:props=>{mapProps=props;return React.createElement('div',null,'map fixture');}}, './RecordedScene':{RecordedScene:()=>React.createElement('div',null,'scene fixture')}});
// Synthetic UI fixture; never served as an experiment record.
const ui = {...fixture, trusted:true, pixels:new Uint8Array([255]), scans:[], manifest:{...fixture.manifest, scene:{width:1,height:1,resolution_m:.05,origin:[0,0,0],free_threshold:.196,occupied_threshold:.65,negate:0},metrics:[{name:'mission_ros_seconds',value:20.668,unit:'s',quality:'ORIGINAL_VERIFIED',source_ref:'report',pointer:'/campaign/trials/0/evidence/metrics/mission_ros_seconds'},{name:'odom_path_metres',value:1.5568730774647175,unit:'m'},{name:'xy_error_m',value:.15552255266952078,unit:'m'}], original_validation:{ros_outcome:'succeeded',pose_verdict:'POSE_VERIFIED',contact_verdict:'NO_CONTACT_OBSERVED',final_localized_pose:{x:0,y:0,yaw:0},final_pose_ros_ns:'12000000000',contact_frame_count:417,contact_scope:'ADAPTER_MONITORED_GEOMETRY_ONLY'}, coverage:{gaps:[],missing_channels:[]},limitations:[]}};
test('rendered layout starts paused with real sample; player precedes visuals; private/read-only and critical limits remain visible', ()=> {
  const html=renderToStaticMarkup(React.createElement(ReplayLab,{data:ui}));
  assert(html.indexOf('class="player"')<html.indexOf('class="workspace"'));
  assert.match(html,/00:06.0/); assert.match(html,/>Play<| Play<\/button>/);
  assert.match(html,/Private local preview/); assert.match(html,/Recorded · Read-only · N0/); assert.match(html,/Partial recording/); assert.match(html,/LiDAR unavailable/);
  assert.equal((html.match(/<details/g)||[]).length,4); assert.doesNotMatch(html,/<details[^>]* open/);
  assert.match(html,/20.67/); assert.match(html,/1.56/); assert.match(html,/15.6/); assert.match(html,/1.5568730774647175/);
  assert.equal(mapProps.readOnly,true); assert.equal(mapProps.snapshot.runtime_mode,'replay'); assert.deepEqual(mapProps.selectedGoal,null);
});
test('rendered missing pose explicitly hides movement; unsupported visitor result remains UNKNOWN', ()=> {
  const data={...ui,poses:[],trusted:false};
  const html=renderToStaticMarkup(React.createElement(ReplayLab,{data}));
  assert.match(html,/Pose unavailable — no movement reconstructed/); assert.match(html,/robot hidden/); assert.match(html,/UNKNOWN/); assert.equal(mapProps.snapshot.pose,null);
});

test('three fixed-unit criteria and explicit Run checks follow the visual workspace',()=>{
  const html=renderToStaticMarkup(React.createElement(ReplayLab,{data:ui}));
  for (const label of ['Maximum mission duration seconds','Maximum final xy error metres','Maximum final yaw error radians']) assert(html.includes(label));
  assert.match(html,/Run checks/); assert.match(html,/Inputs use seconds, metres and radians only/);
  assert(html.indexOf('class="workspace"')<html.indexOf('id="validation-title"'));
  assert.match(html,/Preview starts at a recorded moment with a reliable pose/);
});
