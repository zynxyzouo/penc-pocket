import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const app=readFileSync(new URL('../public/app.js',import.meta.url),'utf8');
const start=app.slice(app.indexOf('async function start('),app.indexOf('function schedule('));
const keyEvent=app.slice(app.indexOf('function keyEvent('),app.indexOf('function storageError('));
test('pending policy persistence prevents resume using the old policy',async()=>{
  const calls=[];
  const context=vm.createContext({autoLoading:false,offlineChanging:true,loaded:true,
    fatal:false,document:{hidden:false},running:false,catching:false,
    activateInputsFromGesture(){calls.push('activate');},rpc(op){calls.push(op);}});
  vm.runInContext(start,context);
  await context.start({fromGesture:true});
  assert.deepEqual(calls,[]);
});
test('pending policy persistence prevents queued keyboard/pointer frames',()=>{
  const events=[];
  const context=vm.createContext({autoLoading:false,offlineChanging:true,loaded:true,
    fatal:false,catching:false,events,awayAutoRetry:false});
  vm.runInContext(keyEvent,context);context.keyEvent();
  assert.deepEqual(events,[]);assert.equal(context.awayAutoRetry,false);
});
