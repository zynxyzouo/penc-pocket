import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {FramePacer} from '../public/pacing.js';
const app=readFileSync(new URL('../public/app.js',import.meta.url),'utf8');
function session({now=40,events=[{keys:['A']}],complete=1}={}){
  const calls=[],scheduled=[];let resolveFrame;
  const pacer=new FramePacer();pacer.reset(0);
  const context=vm.createContext({inFrame:false,catching:false,loaded:true,fatal:false,running:true,
    events,performance:{now:()=>now},pacer,generation:1,playGeneration:1,lastClock:0,fraction:0,
    machineCapabilities:{},soundTimeline:{claim:()=>0,acknowledge(){}},held:new Set(),motionPending:false,
    phoneMotion:{enabled:false},deviceUI:{setKeys(){}},sound:{playbackRate:2},display(){},
    machineFamily:'penc-stock',awayAutoRetry:false,lastSave:Date.now(),Date,
    rpc(op,fields){calls.push({op,...fields});return new Promise(r=>resolveFrame=()=>r({completed_frames:complete}));},
    schedule(ms){scheduled.push(ms);},fail(e){throw e;}});
  vm.runInContext(app.slice(app.indexOf('async function pump('),app.indexOf('function keyEvent(')),context);
  return {context,pacer,calls,scheduled,finish(){resolveFrame();},setNow(value){now=value;}};
}
test('urgent input is presented after one native update even when three are due',async()=>{
  const s=session();const done=s.context.pump();assert.equal(s.calls[0].frames,1);s.finish();await done;
  assert.equal(s.scheduled.at(-1),0);assert.equal(s.pacer.claim(40),2);
});
test('forced input before deadline does not postpone later native cadence',()=>{
  const p=new FramePacer();p.reset(0);assert.equal(p.claim(0),1);
  for(let i=0;i<10;i++)assert.equal(p.claim(1,true),1);
  assert.equal(p.claim(15.625),1);
});
test('partially completed worker batch retains owed updates and schedules them immediately',async()=>{
  const s=session({events:[]});const done=s.context.pump();assert.equal(s.calls[0].frames,3);
  s.finish();await done;assert.equal(s.scheduled.at(-1),0);assert.equal(s.pacer.claim(40),2);
});
test('queued press long press release remain ordered while worker is busy',async()=>{
  const s=session();const done=s.context.pump();
  s.context.events.push({keys:['A'],long:true},{keys:[]});await s.context.pump();assert.equal(s.calls.length,1);
  s.finish();await done;assert.equal(s.scheduled.at(-1),0);
  for(const expected of [{keys:['A'],long:true},{keys:[],long:false}]){
    const next=s.context.pump();const sent=s.calls.at(-1);
    assert.deepEqual(Array.from(sent.keys),expected.keys);assert.equal(sent.long,expected.long);assert.equal(sent.frames,1);
    s.finish();await next;
  }
});
test('old worker result cannot refund debt into a restarted session',async()=>{
  const s=session({events:[]});const done=s.context.pump();s.context.playGeneration++;s.pacer.reset(1000);
  s.finish();await done;assert.equal(s.pacer.claim(1000),1);
});
test('sustained slow worker debt is bounded to three updates per transaction',()=>{
  const p=new FramePacer();p.reset(0);
  for(let now=1000;now<=10000;now+=1000){assert.equal(p.claim(now),3);p.complete(1);}
  assert.equal(p.claim(10000),2);p.complete(2);assert.equal(p.claim(10000),0);
  assert.ok(p.dropped>0);
});
test('reset after pause discards old debt and starts immediately',()=>{
  const p=new FramePacer();p.reset(0);p.claim(40);p.reset(1000);
  assert.equal(p.claim(1000),1);assert.equal(p.claim(1001),0);
});
