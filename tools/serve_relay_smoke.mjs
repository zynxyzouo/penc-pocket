// SPDX-License-Identifier: GPL-3.0-or-later
// Loopback QA server only. No TURN or external credentials.
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const {Miniflare,convertV4MiniflareOptions}=await import(process.env.PENC_MINIFLARE_MODULE||'miniflare');
const origin='http://127.0.0.1:8766';
const modules=['worker.mjs','state.mjs'].map(name=>({type:'ESModule',path:fileURLToPath(new URL('../cloudflare/'+name,import.meta.url))}));
const runtime=vars=>new Miniflare(convertV4MiniflareOptions({cf:false,modules,compatibilityDate:'2026-10-28',
 durableObjects:{PAIRING:{className:'PairingObject',useSQLite:true}},bindings:{ALLOWED_ORIGINS:origin,...vars},
 outboundService:async()=>{throw Error('External network forbidden in relay QA');}}));
const normal=runtime({}),limited=runtime({REQUESTS_GLOBAL_DAY:'2'});
const files={'/':['relay-smoke.html','text/html; charset=utf-8'],'/relay-transport.js':['../public/relay-transport.js','text/javascript; charset=utf-8']};
const server=createServer(async(req,res)=>{
 try{
  if(['/api/link','/quota/api/link'].includes(req.url)&&req.method==='POST'){
   let size=0;const chunks=[];for await(const c of req){size+=c.length;if(size>8192){res.writeHead(413).end();return;}chunks.push(c);}
   const mf=req.url.startsWith('/quota')?limited:normal;
   const r=await mf.dispatchFetch(origin+'/api/link',{method:'POST',headers:req.headers,body:Buffer.concat(chunks)});
   res.writeHead(r.status,Object.fromEntries(r.headers));res.end(Buffer.from(await r.arrayBuffer()));return;
  }
  if(req.method==='GET'&&files[req.url]){const [file,type]=files[req.url];res.writeHead(200,{'Content-Type':type,'Cache-Control':'no-store'});res.end(await readFile(new URL(file,import.meta.url)));return;}
  res.writeHead(404).end();
 }catch{res.writeHead(500).end('Local QA error');}
});
await Promise.all([normal.ready,limited.ready]);server.listen(8766,'127.0.0.1',()=>console.log('Local free relay QA: '+origin));
process.on('SIGINT',()=>{server.close();void Promise.all([normal.dispose(),limited.dispose()]).finally(()=>process.exit());});
