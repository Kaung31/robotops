import assert from 'node:assert/strict';
import {readFile,access} from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const schema=JSON.parse(await readFile(new URL('../src/replay/schema-v1.json',import.meta.url),'utf8'));
const source=(await readFile(new URL('../src/replay/data.ts',import.meta.url),'utf8')).replace('import schemas from "./schema-v1.json";',`const schemas=${JSON.stringify(schema)};`);
async function esm(source) {const {outputText}=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}});return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);}
const engine=await esm(source);
const validationSource=(await readFile(new URL('../src/replay/validation.ts',import.meta.url),'utf8')).replace('import { visitorDuration, type Metric } from "./data";',`const visitorDuration=${engine.visitorDuration.toString()};`);
const {visitorCheck,CHECKS}=await esm(validationSource);
// Synthetic portable measurements; never served as a recording.
const values=[20.668,.15552255266952078,.0541354424180002];
const metrics=CHECKS.map((c,i)=>({name:c.metric,unit:c.unit,value:values[i],quality:'ORIGINAL_VERIFIED',source_ref:'report',pointer:c.pointer}));
for (const [i,c] of CHECKS.entries()) {
  test(`${c.id}: exact equality passes, lower fails, higher passes without rounding`,()=>{
    assert.equal(visitorCheck(c.id,metrics,String(values[i]),true).outcome,'PASS');
    assert.equal(visitorCheck(c.id,metrics,String(values[i]-1e-12),true).outcome,'FAIL');
    assert.equal(visitorCheck(c.id,metrics,String(values[i]+1e-12),true).outcome,'PASS');
    const rounded=[20.67,.1555,.0541][i];
    assert.equal(visitorCheck(c.id,metrics,String(rounded),true).outcome,values[i]<=rounded?'PASS':'FAIL');
    assert.equal(visitorCheck(c.id,metrics,'0',true).outcome,'FAIL');
  });
  test(`${c.id}: invalid thresholds are UNKNOWN`,()=>{
    for(const v of ['', ' ', '-1','NaN','Infinity','1e309','0x20','1,5','3 rad','--2']) assert.equal(visitorCheck(c.id,metrics,v,true).outcome,'UNKNOWN',v);
    assert.equal(visitorCheck(c.id,metrics,'1e2',true).outcome,'PASS');
  });
  test(`${c.id}: missing, duplicate, untrusted, malformed and wrong-unit evidence fails closed`,()=>{
    assert.equal(visitorCheck(c.id,[], '999',true).outcome,'UNKNOWN');
    assert.equal(visitorCheck(c.id,metrics, '999',false).outcome,'UNKNOWN');
    assert.equal(visitorCheck(c.id,[...metrics,metrics[i]], '999',true).outcome,'UNKNOWN');
    for(const change of [{value:null},{value:NaN},{value:Infinity},{value:-.1},{value:'0'},{unit:['ms','cm','deg'][i]},{quality:'UNAVAILABLE'},{pointer:'/invented'},{source_ref:'graphics'},{name:'invented'}]) {
      const changed=structuredClone(metrics);Object.assign(changed[i],change);
      assert.equal(visitorCheck(c.id,changed, '999',true).outcome,'UNKNOWN',JSON.stringify(change));
    }
  });
  test(`${c.id}: zero measurement equals zero; inputs use their declared SI unit`,()=>{
    const zero=structuredClone(metrics);zero[i].value=0;assert.equal(visitorCheck(c.id,zero,'0',true).outcome,'PASS');
    assert.equal(visitorCheck(c.id,metrics,String(values[i]),true).outcome,'PASS');
  });
}
test('calculations preserve frozen originals and do not depend on replay graphics',()=>{
  const original=engine.freeze({metrics:structuredClone(metrics),original_validation:{ros_outcome:'succeeded',pose_verdict:'POSE_VERIFIED',contact_verdict:'NO_CONTACT_OBSERVED'}});
  const before=JSON.stringify(original);
  for(const c of CHECKS) for(const t of ['0','999','']) visitorCheck(c.id,original.metrics,t,true);
  assert.equal(JSON.stringify(original),before);assert(Object.isFrozen(original.metrics[0]));
});
let available=process.env.ROBOTOPS_SKIP_PRIVATE!=='1';
const root=new URL('../../artifacts/p2-n0-20261011/dataset-final/',import.meta.url);
try{await access(new URL('manifest.json',root));}catch{available=false;}
test('qualified private N0: all three checks use exact original measurements and leave original report intact',{skip:available?false:'Private N0 intentionally absent'},async()=>{
  const data=await engine.loadN0(async url=>new Response(await readFile(new URL(url.split('/').at(-1),root))));
  const before=JSON.stringify(data.manifest);
  for(const c of CHECKS){
    const metric=data.manifest.metrics.find(m=>m.name===c.metric);
    assert.equal(visitorCheck(c.id,data.manifest.metrics,String(metric.value),data.trusted).outcome,'PASS');
    assert.equal(visitorCheck(c.id,data.manifest.metrics,String(metric.value-1e-12),data.trusted).outcome,'FAIL');
    assert.equal(visitorCheck(c.id,data.manifest.metrics,'',data.trusted).outcome,'UNKNOWN');
  }
  assert.equal(JSON.stringify(data.manifest),before);
});
