import test from 'node:test';
import assert from 'node:assert/strict';
import {MachineKeys, MachineSession, machineKey,validateRememberedCore} from '../public/machine-app.js';
test('browser timers are not invoked with MachineSession as their receiver',()=>{
 const oldSet=globalThis.setTimeout,oldClear=globalThis.clearTimeout;
 try{
  globalThis.setTimeout=function(){assert.equal(this===undefined||this===globalThis,true);return 1;};
  globalThis.clearTimeout=function(){assert.equal(this===undefined||this===globalThis,true);};
  const s=new MachineSession({});assert.equal(s.setTimer(()=>{},1),1);s.clearTimer(1);
 }finally{globalThis.setTimeout=oldSet;globalThis.clearTimeout=oldClear;}
});
test('changed compiled core cannot silently restart a remembered machine',()=>{
 assert.throws(()=>validateRememberedCore({core_sha256:'a'.repeat(64)},{core_sha256:'b'.repeat(64)}),/核心版本/);
 assert.doesNotThrow(()=>validateRememberedCore({core_sha256:'a'.repeat(64)},{core_sha256:'a'.repeat(64)}));
});

const identity={firmware_sha256:'a'.repeat(64),irom_sha256:'b'.repeat(64),core_sha256:'c'.repeat(64)};
const inputs=()=>({bin:new ArrayBuffer(8388608),irom:new ArrayBuffer(98304),binName:'test.bin',iromName:'internal.bin'});
const frame=seconds=>({rgba:'',family:'gpce4',clock:'00:00:00',time_rate:1,steps:seconds*12000000,pc:0,pixels:0,instructions:187500,virtual_seconds:seconds,sleeping:false,worker_ms:2});
function fixture(){
  let seconds=0,now=0,pendingRun,restoreFails=false;
  const data=new Map(),calls=[],timers=[],writes=[],frames=[];
  const session=new MachineSession({
    async rpc(op,fields={}){
      calls.push({op,...fields});
      if(op==='load')return {...frame(0),identity};
      if(op==='keys')return {};
      if(op==='run')return new Promise(resolve=>{pendingRun=()=>{seconds+=1/64;now+=2;resolve(frame(seconds));};});
      if(op==='snapshot')return {exactState:seconds};
      if(op==='restore'){if(restoreFails)throw Error('corrupt state');seconds=fields.snapshot.exactState;return frame(seconds);}
      throw Error('unexpected op: '+op);
    },
    read:async key=>data.get(key),
    writeMany:async entries=>{writes.push(entries);for(const [key,value] of entries)data.set(key,value);},
    erase:async keys=>keys.forEach(key=>data.delete(key)),
    now:()=>now,setTimer:(fn,ms)=>{timers.push({fn,ms});return timers.length;},clearTimer(){},
    onFrame:r=>frames.push(r),onState(){},onError:e=>{throw e;},
  });
  return {session,data,calls,timers,writes,frames,finish:()=>pendingRun(),setNow:value=>now=value,setRestoreFails:value=>restoreFails=value};
}

test('a released tap still reaches four 64 Hz batches; a held key survives debounce',()=>{
  const keys=new MachineKeys();keys.press('pointer:1','A');keys.release('pointer:1');
  for(let i=0;i<4;i++){assert.equal(keys.mask(),8);keys.advance(1/64,8);}
  assert.equal(keys.mask(),0);
  keys.press('keyboard:B','B');for(let i=0;i<10;i++)keys.advance(1/64,16);
  assert.equal(keys.mask(),16);keys.clear();assert.equal(keys.mask(),0);
});

test('input arriving during a batch is not prematurely debounced',()=>{
  const keys=new MachineKeys();keys.press('pointer:1','A');keys.release('pointer:1');
  keys.advance(.1,0);assert.equal(keys.mask(),8);
});

test('identities isolate machine saves and reject malformed keys',()=>{
  assert.notEqual(machineKey(identity),machineKey({...identity,irom_sha256:'d'.repeat(64)}));
  assert.notEqual(machineKey(identity),machineKey({...identity,core_sha256:'e'.repeat(64)}));
  assert.throws(()=>machineKey({...identity,firmware_sha256:'../old-save'}));
});

test('running has one batch in flight and a positive real-time pacing delay',async()=>{
  const f=fixture();await f.session.load(inputs());f.session.start();
  f.session.pump();f.session.pump();assert.equal(f.calls.filter(c=>c.op==='run').length,1);
  f.finish();await f.session.inFlight;
  assert.equal(f.timers.at(-1).ms,13.625);
  assert.equal(f.calls.find(c=>c.op==='run').instructions,187500);
});

test('pause clears inputs immediately and a finishing batch cannot restart the loop',async()=>{
  const f=fixture();await f.session.load(inputs());f.session.keys.press('pointer:1','C');f.session.start();
  const pending=f.session.inFlight;const paused=f.session.pause();
  assert.equal(f.session.running,false);assert.equal(f.session.keys.mask(),0);
  f.finish();await pending;await paused;
  assert.equal(f.timers.length,0);
  assert.equal(f.calls.filter(c=>c.op==='keys').at(-1).keys,0);
});

test('restart during an unfinished pause cannot strand the runner without a timer',async()=>{
  const f=fixture();await f.session.load(inputs());f.session.start();
  const pending=f.session.inFlight,paused=f.session.pause();f.session.start();
  assert.equal(f.session.running,false);
  f.finish();await pending;await paused;f.session.start();
  assert.equal(f.calls.filter(c=>c.op==='run').length,2);
  f.finish();await f.session.inFlight;
});

test('a faulting in-flight batch still permits paused diagnostic snapshot export',async()=>{
  const f=fixture();await f.session.load(inputs());
  const rpc=f.session.rpc;f.session.rpc=(op,fields)=>op==='run'?Promise.reject(Error('unsupported instruction')):rpc(op,fields);
  f.session.onError=()=>{};f.session.start();
  const backup=await f.session.exportBackup();
  assert.equal(backup.schema,'penc-pocket-gpce4-v1');assert.equal(f.session.running,false);
  assert.equal(f.session.saveBlocked,true);assert.deepEqual(backup.snapshot,{exactState:0});
});

test('a new same-key tap during a batch retains its own minimum duration',async()=>{
  const f=fixture();await f.session.load(inputs());f.session.keys.press('one','A');f.session.start();
  f.session.keys.release('one');f.session.keys.press('two','A');f.session.keys.release('two');
  f.finish();await f.session.inFlight;
  for(let i=0;i<4;i++){
    const pumped=f.session.pump();
    assert.equal(f.calls.filter(c=>c.op==='run').at(-1).keys,8);
    f.finish();await pumped;
  }
});

test('remembered inputs and snapshot restore paused without offline advancement',async()=>{
  const f=fixture();await f.session.load(inputs());
  await f.session.importBackup({schema:'penc-pocket-gpce4-v1',identity,saved_at:'2026-01-01',snapshot:{exactState:9}});
  const last=f.data.get('gpce4:last');assert.ok(last.key.startsWith('gpce4:'));
  await f.session.load(f.data.get(last.key+':inputs'));
  assert.equal(f.session.running,false);assert.equal(f.session.frame.virtual_seconds,9);
  assert.equal(f.calls.some(c=>c.op==='run'),false);
  assert.ok([...f.data.keys()].every(key=>key.startsWith('gpce4:')));
});

test('a corrupt remembered snapshot is retained and blocks later automatic saving',async()=>{
  const f=fixture();const key=machineKey(identity),bad={schema:'penc-pocket-gpce4-v1',identity,snapshot:{bad:true}};
  f.data.set(key+':save',bad);f.setRestoreFails(true);
  await assert.rejects(f.session.load(inputs()),/corrupt/);
  assert.equal(f.session.saveBlocked,true);await f.session.save();
  assert.equal(f.data.get(key+':save'),bad);assert.equal(f.session.running,false);
});

test('mismatched or corrupt import leaves the previous save untouched',async()=>{
  const f=fixture();await f.session.load(inputs());await f.session.save();
  const key=machineKey(identity)+':save',previous=f.data.get(key),count=f.writes.length;
  await assert.rejects(f.session.importBackup({schema:'penc-pocket-gpce4-v1',identity:{...identity,irom_sha256:'d'.repeat(64)},snapshot:{exactState:99}}),/不相符/);
  f.setRestoreFails(true);
  await assert.rejects(f.session.importBackup({schema:'penc-pocket-gpce4-v1',identity,snapshot:{exactState:99}}),/corrupt/);
  assert.equal(f.data.get(key),previous);assert.equal(f.writes.length,count);
});

test('forgetting inputs removes only this machine input record and keeps its snapshot',async()=>{
  const f=fixture();await f.session.load(inputs());await f.session.save();await f.session.remember(false);
  const key=machineKey(identity);assert.equal(f.data.has(key+':inputs'),false);assert.ok(f.data.has(key+':save'));
  assert.equal(f.data.get('gpce4:remember'),false);
});
