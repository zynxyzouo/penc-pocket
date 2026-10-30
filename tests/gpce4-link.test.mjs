import test from 'node:test';
import assert from 'node:assert/strict';
const module=await import('../public/gpce4-link.js').catch(()=>({}));
const profile={firmware:'a'.repeat(64),transport:'b'.repeat(64)};
function peripheral(){
 const memory=new WebAssembly.Memory({initial:1});let enabled=false,tx=null,inbox=null,waiting=false;
 const e={memory,gp_link_enable(n){enabled=!!n;tx=null;inbox=null;},gp_link_status:()=>tx?1:waiting?2:0,
  gp_link_tx_ptr:()=>0,gp_link_rx_ptr:()=>16,gp_link_tx_take(){if(!tx)return 0;tx=null;return 1;},
  gp_link_receive(){if(!enabled||inbox)return 0;inbox=[...new Uint16Array(memory.buffer,16,8)];return 1;},
  gp_run(n){return waiting&&!inbox?0:n;}};
 return {e,send(words){tx=words;new Uint16Array(memory.buffer,0,8).set(words);},consume(){const packet=inbox;inbox=null;return packet;},wait(){waiting=true;}};
}
function fixture(){
 assert.equal(typeof module.Gpce4Link,'function','native full-machine packet bridge must exist');
 const p=peripheral(),link=new module.Gpce4Link({getExports:()=>p.e,profile});link.connect('room-1',0);return {p,link};
}
const packet=(seq,first=0)=>({seq,words:[first,1,2,3,4,5,6,65535]});

test('complete firmware packets leave unchanged and are retained until relay acknowledgement',()=>{
 const {link,p}=fixture();p.send(packet(1,23).words);link.service();
 assert.deepEqual(link.metadata().packets,[packet(1,23)]);
 link.receive('room-1',[],1);assert.deepEqual(link.metadata().packets,[]);
});

test('metadata cannot mutate the authenticated identity or outgoing packet history',()=>{
 const {link,p}=fixture();p.send(packet(1,23).words);link.service();
 const meta=link.metadata();meta.profile.firmware='c'.repeat(64);meta.packets[0].words[0]=99;
 assert.deepEqual(link.metadata().profile,profile);assert.deepEqual(link.metadata().packets,[packet(1,23)]);
});

test('incoming packets wait for peripheral capacity and preserve every uint16 word',()=>{
 const {link,p}=fixture();link.receive('room-1',[packet(1,10),packet(2,20)],0);
 assert.equal(link.metadata().received,1);assert.deepEqual(p.consume(),packet(1,10).words);
 link.service();assert.equal(link.metadata().received,2);assert.deepEqual(p.consume(),packet(2,20).words);
});

test('identical retries are idempotent before and after peripheral delivery',()=>{
 const {link,p}=fixture();link.receive('room-1',[packet(1)],0);link.receive('room-1',[packet(1),packet(1)],0);
 assert.deepEqual(p.consume(),packet(1).words);link.service();assert.equal(p.consume(),null);
 assert.equal(link.metadata().received,1);
});

test('changed retry bytes, sequence gaps and stale sessions fail before any delivery',()=>{
 const {link,p}=fixture();link.receive('room-1',[packet(1)],0);p.consume();
 for(const [session,packets] of [['room-1',[packet(1,9)]],['room-1',[packet(3)]],['old',[packet(2)]]]){
  assert.throws(()=>link.receive(session,packets,0));assert.equal(p.consume(),null);assert.equal(link.metadata().received,1);
 }
});

test('invalid acknowledgement rolls back the entire received batch',()=>{
 const {link,p}=fixture();assert.throws(()=>link.receive('room-1',[packet(1)],1));
 assert.equal(link.metadata().received,0);assert.equal(p.consume(),null);
});

test('malformed packet envelopes and words never enter native memory',()=>{
 const {link,p}=fixture();
 for(const item of [{...packet(1),extra:0},{seq:1,words:[1]},packet(0),{seq:1,words:[-1,1,2,3,4,5,6,7]},{seq:1,words:[true,1,2,3,4,5,6,7]}]){
  assert.throws(()=>link.receive('room-1',[item],0));assert.equal(p.consume(),null);
 }
});

test('waiting pauses virtual execution without manufacturing a reply',()=>{
 const {link,p}=fixture();p.wait();assert.equal(link.run(250000),0);
 assert.deepEqual(link.metadata().packets,[]);assert.equal(link.metadata().received,0);
 assert.equal(link.metadata().waiting,true);
});

test('each stopped core batch exposes its audio before the next batch resets observations',()=>{
 const {link,p}=fixture();let calls=0;const observations=[];
 p.e.gp_run=n=>{calls++;if(calls===1){p.send(packet(1).words);return 17;}return n;};
 assert.equal(link.run(100,()=>observations.push(calls)),100);
 assert.deepEqual(observations,[1,2]);
});

test('disconnect clears peripheral custody and rejects delayed session packets',()=>{
 const {link,p}=fixture();link.receive('room-1',[packet(1)],0);link.detach();
 assert.equal(link.metadata().connected,false);assert.equal(p.consume(),null);
 assert.throws(()=>link.receive('room-1',[packet(2)],0));
 link.connect('room-2',1);assert.equal(link.metadata().received,0);assert.deepEqual(link.metadata().packets,[]);
});

test('mutated or unknown firmware is unsupported without changing core state',async()=>{
 assert.equal(typeof module.Gpce4Link,'function','native full-machine packet bridge must exist');
 const p=peripheral();const link=await module.Gpce4Link.create(new Uint8Array(8388608),'a'.repeat(64),()=>p.e);
 assert.equal(link.metadata().supported,false);assert.equal(link.metadata().profile,null);assert.throws(()=>link.connect('room',0));
});

test('restored Flash cannot retain admission after replacing native code',()=>{
 const p=peripheral();p.e.gp_flash_ptr=()=>32;
 const bytes=new Uint8Array(p.e.memory.buffer,32,8);bytes.set([1,2,3,4]);
 const link=new module.Gpce4Link({getExports:()=>p.e,profile,ranges:[{offset:0,bytes:new Uint8Array([1,2,3,4])}]});
 bytes[1]=99;assert.throws(()=>link.connect('room',0));assert.equal(link.metadata().connected,false);
 bytes[1]=2;link.connect('room',0);bytes[2]=99;assert.throws(()=>link.connect('room',0));assert.throws(()=>link.run(100));
});
