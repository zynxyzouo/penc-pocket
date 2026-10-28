// SPDX-License-Identifier: GPL-3.0-or-later
// Real workerd + SQLite; no paid services or external network permitted.
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const {Miniflare,convertV4MiniflareOptions}=await import(process.env.PENC_MINIFLARE_MODULE||'miniflare');
const origin='https://zynxyzouo.github.io';
const modules=['worker.mjs','state.mjs'].map(name=>({type:'ESModule',path:fileURLToPath(new URL('../cloudflare/'+name,import.meta.url))}));
let outgoing=0;
const make=(bindings={})=>new Miniflare(convertV4MiniflareOptions({modules,cf:false,compatibilityDate:'2026-10-28',
 durableObjects:{PAIRING:{className:'PairingObject',useSQLite:true}},bindings:{ALLOWED_ORIGINS:origin,...bindings},
 outboundService:async()=>{outgoing++;throw Error('Unexpected external network');}}));
const call=async(mf,body,allowed=origin)=>{
 const r=await mf.dispatchFetch('http://pair.test/api/link',{method:'POST',headers:{Origin:allowed,'Content-Type':'application/json'},body:JSON.stringify(body)});
 return {status:r.status,body:await r.json(),cors:r.headers.get('Access-Control-Allow-Origin')};
};
const p=n=>({firmware:n.repeat(64),transport:'f'.repeat(64)});
const mf=make();
try{
 assert.equal((await mf.dispatchFetch('http://pair.test/health')).status,200);
 const a={token:'a'.repeat(64),code:null},b={token:'b'.repeat(64),code:null};
 assert.equal((await call(mf,{...a,action:'create',profile:p('a')},'https://wrong.example')).status,403);
 for(const [session,profile] of [[a,p('a')],[b,p('b')]]){
  const r=await call(mf,{...session,action:'create',profile});assert.equal(r.status,200,JSON.stringify(r.body));session.code=r.body.code;assert.equal(r.cors,origin);
 }
 const originalCodes=[a.code,b.code];
 const paired=await Promise.all([call(mf,{...a,action:'pair',profile:p('a'),peer:b.code}),call(mf,{...b,action:'pair',profile:p('b'),peer:a.code})]);
 assert.equal(paired[0].status,200);assert.equal(paired[1].status,200);assert.equal(paired[0].body.code,paired[1].body.code);assert.notEqual(paired[0].body.slot,paired[1].body.slot);
 const packetA={seq:1,words:[0,1,2,3,4,5,6,65535]},packetB={seq:1,words:[65535,6,5,4,3,2,1,0]};
 const ex=(session,received=0,packets=[])=>call(mf,{...session,action:'exchange',received,packets});
 assert.equal((await ex({...a,token:'c'.repeat(64)})).status,403);
 assert.equal((await ex(a,0,[packetA])).body.accepted,0,'storage is not peer acknowledgement');
 let rb=await ex(b,0,[packetB]);assert.deepEqual(rb.body.packets,[packetA]);assert.equal(rb.body.accepted,0);
 let ra=await ex(a,0,[packetA]);assert.deepEqual(ra.body.packets,[packetB]);assert.equal(ra.body.accepted,0);
 await ex(a,1);rb=await ex(b,1);assert.equal(rb.body.accepted,1);assert.deepEqual(rb.body.packets,[]);
 ra=await ex(a,1);assert.equal(ra.body.accepted,1);
 assert.equal((await ex(a,2)).status,409);
 assert.equal((await ex(a,1,[{...packetA,words:Array(8).fill(7)}])).status,409);
 assert.equal((await call(mf,{...a,action:'ice'})).status,400);
 assert.equal((await call(mf,{...a,action:'leave'})).body.closed,true);
 assert.equal((await ex(b,1)).body.closed,true);
 assert.equal(a.code,originalCodes[0]);assert.equal(b.code,originalCodes[1]); // both aliases were exercised
 assert.equal(outgoing,0);
 console.log(JSON.stringify({status:'PASS',runtime:'workerd + SQLite DO',checks:['CORS','reciprocal QR','mixed firmware','member authentication','duplex native-size packets','peer ACK','idempotent retry','bounds','leave aliases','no TURN egress'],realIPhoneVerified:false}));
}finally{await mf.dispose();}
const limited=make({REQUESTS_GLOBAL_DAY:'2'});
try{
 const a={token:'a'.repeat(64),code:null,profile:p('a'),action:'create'};
 assert.equal((await call(limited,a)).status,200);
 assert.equal((await call(limited,a)).status,200);
 assert.equal((await call(limited,a)).status,429);
 assert.equal((await call(limited,a)).status,429);
 assert.equal(outgoing,0);
 console.log(JSON.stringify({status:'PASS',checks:['global quota fails closed','no external fallback']}));
}finally{await limited.dispose();}
