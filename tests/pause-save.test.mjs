import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

// Exercise the actual UI pause lifecycle with isolated worker/storage edges.
const app=readFileSync(new URL('../public/app.js',import.meta.url),'utf8');
const pause=app.slice(app.indexOf('function pause('),app.indexOf('function fail('));
function session({refreshFails=false,newSession=false}={}){
  const saves=[],shown=[],errors=[],calls=[];
  const snapshot={committed:42};
  const context=vm.createContext({autoLoading:false,catching:true,machineFamily:'penc',
    running:true,playGeneration:1,generation:1,loaded:true,worker:{},timer:0,
    fraction:0,lastClock:0,motionPending:false,
    sound:{stop(){}},phoneMotion:{reset(){}},clearTimeout(){},clearKeys(){},controls(){},
    async rpc(op){calls.push(op);if(op==='release'){if(newSession)context.generation++;return snapshot;}
      if(refreshFails)throw Error('render failed');return {clock:'12:00:00'};},
    async persist(s){saves.push(s);},display(r){shown.push(r);},storageError(e){errors.push(e.message);}});
  vm.runInContext(pause,context);
  return {context,saves,shown,errors,calls,snapshot};
}
test('cancelling catch-up saves the committed state even if presentation fails',async()=>{
  const s=session({refreshFails:true});await s.context.pause();
  assert.deepEqual(s.saves,[s.snapshot]);assert.deepEqual(s.errors,['render failed']);
});
test('cancel refresh never advances a frame and saves the release snapshot',async()=>{
  const s=session();await s.context.pause();
  assert.deepEqual(s.calls,['release','present']);assert.deepEqual(s.saves,[s.snapshot]);
  assert.equal(s.shown.length,1);
});
test('a replaced game receives neither stale presentation nor stale save',async()=>{
  const s=session({newSession:true});await s.context.pause();
  assert.deepEqual(s.saves,[]);assert.deepEqual(s.shown,[]);assert.deepEqual(s.calls,['release']);
});
