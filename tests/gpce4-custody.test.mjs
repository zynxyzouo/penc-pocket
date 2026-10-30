import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {Gpce4Machine,sha256} from '../public/gpce4-engine.js';

const custody=await import('../public/gpce4-custody.js').catch(e=>{
 if(e.code==='ERR_MODULE_NOT_FOUND')return {};throw e;
});
const {Gpce4Custody}=custody;
test('bounded custody bridge is available to the full machine',()=>assert.equal(typeof Gpce4Custody,'function'));

async function machine(bin,irom){
 const core=Buffer.from((await readFile(new URL('../public/core/gpce4.wasm.b64',import.meta.url),'utf8')).trim(),'base64');
 const m=await Gpce4Machine.create(core,{});await m.load(bin,irom);return m;
}
test('unadmitted firmware and invalid elapsed values never mutate a running machine',async()=>{
 if(!Gpce4Custody)return;
 const bin=new Uint8Array(8388608).fill(255),irom=new Uint8Array(98304);
 const m=await machine(bin,irom),c=await Gpce4Custody.create(m),before=await m.snapshot();
 assert.match(c.catchUp(172800).blocked_reason,/unsupported/);
 for(const seconds of [-1,true,0.5,2**31])assert.throws(()=>c.catchUp(seconds),/seconds/);
 for(const budget of [0,NaN,Infinity,true])assert.throws(()=>c.catchUp(1,{budgetMs:budget}),/budget/);
 assert.deepEqual(await m.snapshot(),before);
});

const external=!!(process.env.PENC_R23_BIN&&process.env.PENC_INTERNAL_ROM&&process.env.PENC_GPCE4_SNAPSHOT);
async function externalFixture({seed=true}={}){
 const [bin,irom,envelope]=await Promise.all([
  readFile(process.env.PENC_R23_BIN),readFile(process.env.PENC_INTERNAL_ROM),
  readFile(process.env.PENC_GPCE4_SNAPSHOT,'utf8').then(JSON.parse)
 ]);
 const m=await machine(new Uint8Array(bin),new Uint8Array(irom));
 // The private fixture uses the unchanged v1 state ABI. Re-sign only its core
 // identity for this explicit test migration; product imports remain strict.
 const snapshot={...envelope.snapshot,core_sha256:m.core};delete snapshot.checksum;
 snapshot.checksum=await sha256(new TextEncoder().encode(JSON.stringify(snapshot)));
 await m.restore(snapshot);
 if(seed){
  // Explicit host HOME fixture, same two contexts as the existing R23 oracle.
  // This does not claim a native boot/hatch interaction produced these pets.
  const profile=JSON.parse(await readFile(new URL('../public/profiles/r23.json',import.meta.url),'utf8'));
  const ram=new Uint16Array(m.e.memory.buffer,m.e.gp_ram_ptr(),0x3000);
  for(const [address,value] of Object.entries(profile.initial_ram))ram[parseInt(address,16)]=value;
  for(const [address,value] of [[0xcc2,0],[0xcc3,0],[0xcc4,12],[0xcc7,0],[0x81b,65535],[0x81c,0],[0x820,0],[0xcf3,0]])ram[address]=value;
  // Native-call tests begin at the audited UI entry. This fixture does not
  // claim the seeded pets were reached through a native boot/hatch journey.
  const cpu=new Uint32Array(m.e.memory.buffer,m.e.gp_cpu_ptr(),24);
  cpu[6]=0x20;cpu[7]=0x5e9;cpu[14]=cpu[15]=cpu[16]=0;
  m.keys(0);
 }
 return {m,c:await Gpce4Custody.create(m)};
}
function ram(m){return new Uint16Array(m.e.memory.buffer,m.e.gp_ram_ptr(),0x3000);}
function select(m,slot){assert.equal(m.e.gp_custody_call(0x2d1700,slot,500000),1);}
function pets(m){const owner=ram(m)[0xdab]&1,result=[];for(const slot of [0,1]){select(m,slot);result.push(ram(m).slice());}select(m,owner);return result;}
function finish(c,seconds){const rows=[];for(let i=0;seconds&&i<2000;i++){
 const row=c.catchUp(seconds,{budgetMs:5000});assert.equal(row.blocked_reason,null,JSON.stringify(row));
 assert.ok(row.processed_seconds>0,JSON.stringify(row));rows.push(row);seconds=row.remaining_seconds;
 }assert.equal(seconds,0);return rows;}

test('actual imported startup and ongoing menu states are blocked without mutation',{skip:!external},async()=>{
 const {m,c}=await externalFixture({seed:false});const before=await m.snapshot();
 assert.ok(c.catchUp(172800).blocked_reason);assert.deepEqual(await m.snapshot(),before);
 for(const state of [5,17,26,37]){ram(m)[0xc9c]=state;ram(m)[0xdad]=0;const saved=await m.snapshot();
  assert.match(c.catchUp(100).blocked_reason,/native-state/);assert.deepEqual(await m.snapshot(),saved);
 }
});
test('a native hatched HOME can sleep, wake and settle two offline days without seeded pet RAM',{skip:!external},async()=>{
 const {m,c}=await externalFixture({seed:false});
 const advance=(seconds,keys=0)=>{m.keys(keys);for(let i=0;i<seconds*4;i++){m.e.gp_run(3000000);m.checkFault();}};
 advance(.25,32);advance(.25);advance(.25,16);advance(.25);advance(20);
 assert.equal(ram(m)[0xc9c],4);assert.equal(ram(m)[0x827]&1,0);
 advance(15);assert.deepEqual([ram(m)[0xc9c],ram(m)[0xc9d],m.metrics()[14]],[38,4,1]);
 const misses=ram(m)[0x82e],started=performance.now(),rows=finish(c,172800);
 assert.equal(ram(m)[0xc9c],4);assert.equal(ram(m)[0x82e],misses);
 assert.ok(ram(m)[0x826]>0,'the original native hatch continues growing');
 assert.equal(m.metrics()[1],0);assert.equal(m.metrics()[9],0x2005e9);
 // Continuation must execute the new state, without stale interrupted locals.
 advance(1);assert.equal(ram(m)[0xc9c],4);assert.equal(m.metrics()[1],0);
 console.log(JSON.stringify({fixture:'native-C-B-hatch-idle-no-RAM-seed',event:'sleep-home-48h',elapsed_ms:performance.now()-started,species:ram(m)[0x826],rows}));
});
test('native minute settlement preserves care history and advances clock and growth',{skip:!external},async()=>{
 const {m,c}=await externalFixture();
 for(const slot of [0,1]){select(m,slot);const r=ram(m);r[0x82e]=2+slot;r[0x82b]=100+slot;r[0x832]=6+slot;r[0x836]=5000;r[0xcfa]=5;r[0xcfb]=5;r[0xcfc]=5;}
 const before=pets(m);const rows=finish(c,3600),after=pets(m);
 for(let p=0;p<2;p++){
  for(const a of [0x82e,0x82b,0x832])assert.equal(after[p][a],before[p][a]);
  assert.equal(after[p][0x837],before[p][0x837]+60);assert.equal(after[p][0x836],4940);
 }
 assert.deepEqual([ram(m)[0xcc4],ram(m)[0xcc3],ram(m)[0xcc2]],[13,0,0]);
 assert.ok(rows.reduce((n,r)=>n+r.batched_minutes,0)>0);
});
test('hidden illness restores RAM CPU peripherals and Flash',{skip:!external},async()=>{
 const {m,c}=await externalFixture();select(m,1);ram(m)[0xcf4]=2;ram(m)[0xd01]=1;select(m,0);
 const before=await m.snapshot(),flash=new Uint8Array(m.flash());
 assert.match(c.catchUp(3600).blocked_reason,/illness/);assert.deepEqual(await m.snapshot(),before);assert.deepEqual(new Uint8Array(m.flash()),flash);
});
test('failed UI synchronization rolls back even the attempted native execution',{skip:!external},async()=>{
 const {m,c}=await externalFixture();const cpu=new Uint32Array(m.e.memory.buffer,m.e.gp_cpu_ptr(),24);
 cpu[6]=1;cpu[7]=0; // Unmapped interrupted PC: real bus fault, not a mock.
 const before=await m.snapshot(),flash=new Uint8Array(m.flash()),row=c.catchUp(60);
 assert.equal(row.processed_seconds,0);assert.match(row.blocked_reason,/sync/);
 assert.deepEqual(await m.snapshot(),before);assert.deepEqual(new Uint8Array(m.flash()),flash);
});
test('custody rollback keeps admitted motion usable without replaying pending input',{skip:!external},async()=>{
 const {m,c}=await externalFixture();ram(m)[0xcf4]=2;ram(m)[0xd01]=1;
 const before=await m.snapshot();assert.match(c.catchUp(60).blocked_reason,/illness/);assert.deepEqual(await m.snapshot(),before);
 const entry=pc=>{const cpu=new Uint32Array(m.e.memory.buffer,m.e.gp_cpu_ptr(),24),r=ram(m);
  cpu[0]=0xff0;cpu[6]=pc>>>16;cpu[7]=pc&65535;cpu[8]=0;r[0xff1]=0;r[0xff2]=0x1100;r[0x1100]=0xee41;};
 entry(0x201bcc);m.e.gp_run(1);assert.equal(m.motion.metadata().motion_ready,true);
 entry(0x201cda);m.e.gp_run(500);assert.equal(ram(m)[0xd41],0,'rollback cannot replay a gesture');
 assert.equal(m.motion.pulse(true),true);entry(0x201cda);m.e.gp_run(500);assert.equal(ram(m)[0xd41],1);
});
test('connected peers and altered executable Flash are rejected before care edits',{skip:!external},async()=>{
 const {m,c}=await externalFixture();m.connect('custody-guard',0);let before=c.checkpoint();
 assert.equal(c.catchUp(60).blocked_reason,'connected-native-cable');assert.deepEqual(c.checkpoint(),before);m.link.detach();
 const transaction=bytes=>{m.e.gp_bus_write(0x3000,0);for(const byte of bytes){m.e.gp_bus_write(0x30e2,byte);m.e.gp_bus_read(0x30e4);}m.e.gp_bus_write(0x3000,0x1000);};
 transaction([6]);transaction([2,0,0,0,0]);before=await m.snapshot();
 assert.equal(c.catchUp(60).blocked_reason,'modified-custody-code');assert.deepEqual(await m.snapshot(),before);
});
test('native pending growth settles both evolution commits with sound enabled',{skip:!external},async()=>{
 const {m,c}=await externalFixture();ram(m)[0xcc0]=0;
 for(const slot of [0,1]){select(m,slot);ram(m)[0x827]|=2;}
 const before=pets(m),started=performance.now(),rows=finish(c,120),after=pets(m);
 assert.deepEqual(after.map(p=>p[0x826]),[12,45]);
 assert.ok(after.every(p=>!(p[0x827]&2)));
 for(let p=0;p<2;p++)assert.equal(after[p][0x82e],before[p][0x82e]);
 assert.ok(m.metrics()[17]>0,'native evolution must commit real dirty Flash');
 console.log(JSON.stringify({fixture:'explicit-host-home-real-r23-irom',event:'both-pending-growth-sound-on',elapsed_ms:performance.now()-started,sound_busy:ram(m)[0xca1],rows}));
});
test('eligible baby growth deadlines evolve natively and continue for two offline days',{skip:!external},async()=>{
 const {m,c}=await externalFixture();ram(m)[0xcc0]=0;
 for(const slot of [0,1]){select(m,slot);ram(m)[0x826]=1;ram(m)[0x827]=0;ram(m)[0x836]=1;}
 const before=pets(m),started=performance.now(),rows=finish(c,172800),after=pets(m);
 assert.ok(after.every(p=>p[0x826]!==1&&!(p[0x827]&2)));
 for(let p=0;p<2;p++)assert.equal(after[p][0x82e],before[p][0x82e]);
 assert.ok(m.metrics()[17]>0);
 console.log(JSON.stringify({fixture:'explicit-host-home-real-r23-irom',event:'baby-deadline-48h-sound-on',elapsed_ms:performance.now()-started,species:after.map(p=>p[0x826]),sound_busy:ram(m)[0xca1],rows}));
});
test('a fault after real SPI programming restores every programmed page and machine state',{skip:!external},async()=>{
 const {m,c}=await externalFixture();ram(m)[0xcc2]=59;
 const before=await m.snapshot(),flash=new Uint8Array(m.flash()),call=c.call.bind(c);
 const transaction=bytes=>{m.e.gp_bus_write(0x3000,0);for(const byte of bytes){m.e.gp_bus_write(0x30e2,byte);m.e.gp_bus_read(0x30e4);}m.e.gp_bus_write(0x3000,0x1000);};
 c.call=(entry,r1)=>{const value=call(entry,r1);if(entry===0x2da800){
  transaction([6]);transaction([2,0x7f,0xd0,0,0]);
  assert.ok(m.metrics()[17]>0);throw Error('injected-after-program');
 }return value;};
 const row=c.catchUp(1);
 assert.equal(row.processed_seconds,0);assert.match(row.blocked_reason,/injected-after-program/);
 assert.deepEqual(await m.snapshot(),before);assert.deepEqual(new Uint8Array(m.flash()),flash);
});
test('two offline days cross native age and sleep boundaries without instruction replay',{skip:!external},async()=>{
 const {m,c}=await externalFixture();for(const slot of [0,1]){select(m,slot);ram(m)[0x836]=5000;}
 const before=pets(m),instructions=m.metrics()[5],rows=finish(c,172800),after=pets(m);
 for(let p=0;p<2;p++){
  assert.equal(after[p][0x836],2120);assert.equal(after[p][0x828],before[p][0x828]+2);
  assert.equal(after[p][0x837],before[p][0x837]);assert.equal(after[p][0x82e],before[p][0x82e]);
 }
 assert.ok(rows.reduce((n,r)=>n+r.native_minutes,0)<200);
 assert.ok(rows.reduce((n,r)=>n+r.batched_minutes,0)>2680);
 assert.ok(m.metrics()[5]-instructions<12000000*60,'only bounded native event time may execute');
 const snapshot=await m.snapshot();await m.restore(snapshot);assert.deepEqual(await m.snapshot(),snapshot);
});
