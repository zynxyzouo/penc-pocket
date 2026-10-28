// SPDX-License-Identifier: GPL-3.0-or-later
import test from 'node:test';
import assert from 'node:assert/strict';
import {RelayTransport} from '../public/relay-transport.js';

const token='a'.repeat(64), code='AB23CD45', earlier='23456789';
const profile={firmware:'b'.repeat(64),transport:'c'.repeat(64)};
const peerProfile={firmware:'d'.repeat(64),transport:profile.transport};
const packet=(seq,word=seq)=>({seq,words:[word,2,3,4,5,6,7,65535]});
const turn=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
function fixture(){
 assert.equal(typeof RelayTransport,'function','RelayTransport facade must exist');
 let clock=1000;
 const calls=[],server={code,slot:0,expires:1801000,connected:false,closed:false,peerProfile:null,accepted:0,packets:[]};
 const f={server,calls,hook:null};
 f.transport=new RelayTransport({endpoint:'https://pair.example/api/link',now:()=>clock,fetchImpl:async function(url,options){
  calls.push({url,options,body:JSON.parse(options.body),receiver:this});
  return await f.hook?.(calls.at(-1))||Response.json(server);
 }});
 f.session={token,code:null};
 f.request=async(action,fields={})=>{const s=await f.transport.request(action,fields,f.session);f.session.code=s.code;return s;};
 f.start=()=>f.request('create',{profile});
 f.connect=async()=>{await f.start();Object.assign(server,{connected:true,peerProfile});return f.request('pair',{peer:'BC23DE45',profile});};
 f.setNow=value=>{clock=value;};
 return f;
}

test('create and pair use native relay and accept matching transport with different firmware',async()=>{
 const f=fixture();const s=await f.connect();
 assert.equal(s.connected,true);assert.deepEqual(s.peerProfile,peerProfile);
 assert.deepEqual(f.calls.map(c=>c.body),[
  {action:'create',token,code:null,profile},
  {action:'pair',token,code,peer:'BC23DE45',profile}
 ]);
 assert.equal(f.calls[0].receiver,globalThis);
 assert.equal(f.calls[0].options.credentials,'omit');
});

test('server receipt never advances peer ACK and retransmission keeps exact packet words',async()=>{
 const f=fixture();await f.connect();
 const first=await f.request('exchange',{received:0,packets:[packet(1)]});
 assert.equal(first.accepted,0);
 const retry=await f.request('exchange',{received:0,packets:[packet(1)]});assert.equal(retry.accepted,0);
 Object.assign(f.server,{accepted:1,packets:[packet(1,99),packet(2,123)]});
 const ack=await f.request('exchange',{received:0,packets:[packet(1)]});
 assert.equal(ack.accepted,1);assert.deepEqual(ack.packets,[packet(1,99),packet(2,123)]);
 f.server.packets=[packet(2,123)];await f.request('exchange',{received:1,packets:[]});
 assert.equal(f.calls.at(-1).body.received,1);
});

test('an invitation scanned by the other phone accepts the lexical canonical code once',async()=>{
 const f=fixture();await f.start();Object.assign(f.server,{code:earlier,slot:1,connected:true,peerProfile});
 assert.equal((await f.request('exchange',{received:0,packets:[]})).code,earlier);
 f.server.code='23456788';
 await assert.rejects(f.request('exchange',{received:0,packets:[]}),e=>e.terminal===true);
});

for(const [name,mutate] of [
 ['ACK for unsent packet',s=>s.accepted=1],
 ['packet sequence gap',s=>s.packets=[packet(2)]],
 ['word outside uint16',s=>s.packets=[packet(1,65536)]],
 ['extra packet word',s=>{s.packets=[packet(1)];s.packets[0].words.push(0);}],
 ['too many packets',s=>s.packets=Array.from({length:17},(_,i)=>packet(i+1))],
 ['invalid slot',s=>s.slot=2],
 ['non-string code',s=>s.code=[code]],
 ['non-string profile hash',s=>s.peerProfile={...peerProfile,firmware:[peerProfile.firmware]}],
 ['wrong transport',s=>s.peerProfile={...peerProfile,transport:'e'.repeat(64)}],
 ['expired invitation',s=>s.expires=999],
 ['unexpected code',s=>s.code='ZZZZZZZZ'],
 ['disappearing peer',s=>{s.connected=false;s.peerProfile=null;}],
 ['closed room with packets',s=>{s.closed=true;s.connected=false;s.packets=[packet(1)];}],
])test(`rejects ${name} as terminal before native delivery`,async()=>{
 const f=fixture();await f.connect();mutate(f.server);
 await assert.rejects(f.request('exchange',{received:0,packets:[]}),e=>e.terminal===true);
 const count=f.calls.length;
 await assert.rejects(f.request('exchange',{received:0,packets:[]}),e=>e.terminal===true);
 assert.equal(f.calls.length,count,'terminal failure must not issue another poll');
});

test('peer ACK cannot decrease and repeated inbound words cannot change',async()=>{
 const f=fixture();await f.connect();f.server.accepted=1;
 await f.request('exchange',{received:0,packets:[packet(1)]});f.server.accepted=0;
 await assert.rejects(f.request('exchange',{received:0,packets:[]}),e=>e.terminal===true);
 const g=fixture();await g.connect();g.server.packets=[packet(1)];
 await g.request('exchange',{received:0,packets:[]});g.server.packets=[packet(1,999)];
 await assert.rejects(g.request('exchange',{received:0,packets:[]}),e=>e.terminal===true);
});

for(const [name,fields] of [
 ['unsent receive cursor',{received:1,packets:[]}],
 ['outbound sequence gap',{received:0,packets:[packet(2)]}],
 ['invalid outbound word',{received:0,packets:[packet(1,-1)]}],
])test(`rejects ${name} without posting data`,async()=>{
 const f=fixture();await f.connect();const count=f.calls.length;
 await assert.rejects(f.request('exchange',fields),e=>e.terminal===true);assert.equal(f.calls.length,count);
});

test('changed outbound retry is rejected even after a lost HTTP response',async()=>{
 const f=fixture();await f.connect();f.hook=()=>{throw new TypeError('offline');};
 await assert.rejects(f.request('exchange',{received:0,packets:[packet(1)]}),e=>e.retryable===true);
 f.hook=null;const count=f.calls.length;
 await assert.rejects(f.request('exchange',{received:0,packets:[packet(1,23)]}),e=>e.terminal===true);
 assert.equal(f.calls.length,count);
});

for(const status of [400,401,403,404,409,413,429,503])test(`HTTP ${status} is terminal and cannot poll again`,async()=>{
 const f=fixture();await f.connect();f.hook=()=>Response.json({error:'Relay stopped.'},{status});
 await assert.rejects(f.request('exchange',{received:0,packets:[]}),e=>e.terminal===true&&e.status===status);
 const count=f.calls.length;await assert.rejects(f.request('exchange',{received:0,packets:[]}),e=>e.terminal===true);
 assert.equal(f.calls.length,count);
});

test('Cloudflare quota HTML with error 1027 stops instead of becoming a network retry',async()=>{
 const f=fixture();await f.connect();f.hook=()=>new Response('<html>Error 1027: quota exceeded</html>',{status:500});
 await assert.rejects(f.request('exchange',{received:0,packets:[]}),e=>e.terminal===true&&/1027|額度/.test(e.message));
});

test('oversized and malformed JSON responses stop before delivery',async()=>{
 for(const value of ['x'.repeat(8193),'{broken']){
  const f=fixture();await f.connect();f.hook=()=>new Response(value);
  await assert.rejects(f.request('exchange',{received:0,packets:[]}),e=>e.terminal===true);
 }
});

test('close aborts an ignored fetch and old response cannot revive the room; leave still posts',async()=>{
 const f=fixture();await f.connect();const pending=deferred();let signal;
 f.hook=call=>{if(call.body.action==='exchange'){signal=call.options.signal;return pending.promise;}};
 const request=f.request('exchange',{received:0,packets:[]});await turn();f.transport.close();
 assert.equal(signal.aborted,true);await assert.rejects(request,e=>e.terminal===true);
 pending.resolve(Response.json(f.server));await turn();
 Object.assign(f.server,{closed:true,connected:false});await f.request('leave');
 assert.equal(f.calls.at(-1).body.action,'leave');assert.equal(f.calls.at(-1).options.keepalive,true);
 await assert.rejects(f.request('exchange',{received:0,packets:[]}),e=>e.terminal===true);
});

test('eight second deadline includes a stalled response body',async t=>{
 const f=fixture();await f.connect();let cancelled=false;
 f.hook=()=>new Response(new ReadableStream({cancel(){cancelled=true;}}));
 t.mock.timers.enable({apis:['setTimeout']});
 const request=f.request('exchange',{received:0,packets:[]});await turn();
 t.mock.timers.tick(8000);
 await assert.rejects(request,e=>e.retryable===true);assert.equal(cancelled,true);
});

test('explicit creation after close needs a fresh private token',async()=>{
 const f=fixture();await f.start();f.transport.close();
 await assert.rejects(f.transport.request('create',{profile},{token,code:null}),e=>e.terminal===true);
 const s=await f.transport.request('create',{profile},{token:'f'.repeat(64),code:null});assert.equal(s.connected,false);
});

test('cancelled old generation cannot close a newly requested invitation',async()=>{
 const f=fixture();await f.connect();const pending=deferred();
 f.hook=call=>call.body.action==='exchange'?pending.promise:undefined;
 const old=f.request('exchange',{received:0,packets:[]});await turn();f.transport.close();
 Object.assign(f.server,{connected:false,peerProfile:null});
 const session={token:'f'.repeat(64),code:null};
 const fresh=f.transport.request('create',{profile},session);
 await assert.rejects(old,e=>e.terminal===true);
 const s=await fresh;assert.equal(s.connected,false);session.code=s.code;
 f.hook=null;await f.transport.request('exchange',{received:0,packets:[]},session);
 pending.resolve(Response.json(f.server));
});

test('server-expired invitation cannot produce another network poll',async()=>{
 const f=fixture();await f.connect();
 f.hook=()=>Response.json({error:'Invitation expired or unavailable.'},{status:404});
 await assert.rejects(f.request('exchange',{received:0,packets:[]}),e=>e.terminal===true&&e.status===404);
 const count=f.calls.length;
 await assert.rejects(f.request('exchange',{received:0,packets:[]}),e=>e.terminal===true);
 assert.equal(f.calls.length,count);
});

test('returned packet mutation cannot rewrite retry validation history',async()=>{
 const f=fixture();await f.connect();f.server.packets=[packet(1)];
 const result=await f.request('exchange',{received:0,packets:[]});result.packets[0].words[0]=999;
 f.server.packets=[packet(1,999)];
 await assert.rejects(f.request('exchange',{received:0,packets:[]}),e=>e.terminal===true);
});

test('first response requires a string code and string profile hashes',async()=>{
 const f=fixture();f.server.code=[code];
 await assert.rejects(f.start(),e=>e.terminal===true);
 const g=fixture();await g.start();Object.assign(g.server,{connected:true,peerProfile:{...peerProfile,firmware:[peerProfile.firmware]}});
 await assert.rejects(g.request('pair',{peer:'BC23DE45',profile}),e=>e.terminal===true);
});

test('phone wall clock skew does not reject valid server invitations',async()=>{
 for(const now of [-86400000,86400000]){
  const f=fixture();f.setNow(now);
  await f.connect();
  f.setNow(now+86400000);
  assert.equal((await f.request('exchange',{received:0,packets:[]})).connected,true);
  f.hook=()=>Response.json({error:'Invitation expired or unavailable.'},{status:404});
  await assert.rejects(f.request('exchange',{received:0,packets:[]}),e=>e.status===404&&e.terminal);
 }
});
