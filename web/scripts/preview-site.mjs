// Private inspection of exact staged inventory only; no generic filesystem server.
import { createServer } from 'node:http';
import { readFile, lstat, realpath } from 'node:fs/promises';
import { resolve } from 'node:path';
import { digest } from './stage-release.mjs';
const root = resolve(process.argv[2] || '');
if (!root.includes('/artifacts/') || process.argv.length !== 3) throw Error('Explicit private candidate directory required');
const manifest = JSON.parse(await readFile(root+'-manifest.json','utf8'));
if (manifest.status !== 'PRIVATE_CANDIDATE_NOT_APPROVED_FOR_PUBLICATION') throw Error('Not a private candidate');
const routes = new Map(manifest.files.map(f=>['/'+f.path,f]));
const headers = await readFile(resolve(root,'_headers'),'utf8');
const server = createServer(async(req,res)=>{
  const path = req.url?.split('?')[0];console.log(`${req.method} ${path}`);
  res.setHeader('Cache-Control','no-store');
  for (const line of headers.split('\n').slice(1)) { const match=/^  ([A-Za-z-]+): (.+)$/.exec(line);if(match)res.setHeader(match[1],match[2]); }
  if (req.method!=='GET' || req.headers.host!=='127.0.0.1:5175' || req.socket.remoteAddress!=='127.0.0.1' || path!==req.url) {res.writeHead(403);res.end('Private preview only');return;}
  if(path==='/lab'||path==='/lab/'){res.writeHead(302,{Location:'/replay.html'});res.end();return;}
  const asset = routes.get(path==='/'?'/index.html':path==='/replay'?'/replay.html':path);
  const file=asset??routes.get('/404.html');
  try {
    const target=resolve(root,file.path),stat=await lstat(target),bytes=await readFile(target);
    if (!stat.isFile()||stat.isSymbolicLink()||await realpath(target)!==target||!target.startsWith(root+'/')||bytes.length!==file.bytes||digest(bytes)!==file.sha256)throw Error('Unavailable inventory file');
    const mime=file.path.endsWith('.html')?'text/html':file.path.endsWith('.js')?'application/javascript':file.path.endsWith('.css')?'text/css':file.path.endsWith('.json')?'application/json':file.path.endsWith('.gz')?'application/octet-stream':'text/plain';
    res.writeHead(asset?200:404,{'Content-Type':mime});res.end(bytes);
  }catch{res.writeHead(503);res.end('Approved candidate unavailable');}
});
server.on('upgrade',(_req,socket)=>socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n'));
server.listen(5175,'127.0.0.1',()=>console.log('Private candidate: http://127.0.0.1:5175/'));
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>{server.close();server.closeAllConnections();});
