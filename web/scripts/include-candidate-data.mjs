// Explicit candidate-only build. Inputs are staged for review, not publication.
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {inspectBundle,inspectSite,warehouseIds} from './stage-release.mjs';
const web=resolve(dirname(fileURLToPath(import.meta.url)),'..');
await inspectSite(resolve(web,'dist/site'));
const files=[];
for(const id of ['n0','n2',...warehouseIds])for(const [name,bytes] of await inspectBundle(resolve(web,`candidate-data/${id}`),id))files.push([`__local_v2/${id}/${name}`,bytes]);
for(const [name,bytes] of files){const dest=resolve(web,'dist/site',name);await mkdir(dirname(dest),{recursive:true});await writeFile(dest,bytes,{flag:'wx'});}
console.log('Exact N0/N2 and W01-W06 candidate bytes included. PRIVATE; owner publication approval still required.');
