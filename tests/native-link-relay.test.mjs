// SPDX-License-Identifier: GPL-3.0-or-later
import test from 'node:test';
import assert from 'node:assert/strict';
import {LinkRoom} from '../public/native-link.js';

function harness(transport){
 const nodes=new Map(),calls=[];
 globalThis.document={hidden:false,addEventListener(){},getElementById(id){
  if(!nodes.has(id))nodes.set(id,{open:false,textContent:'',setAttribute(){},addEventListener(){},close(){this.open=false;},showModal(){this.open=true;}});
  return nodes.get(id);
 }};
 const room=new LinkRoom({endpoint:'https://pair.example/api/link',transport,
  scanner:{stop(){}},renderQR(){},prepare:async()=>{},resume:()=>calls.push('resume'),display(){},
  rpc:async(action,fields)=>{calls.push([action,fields]);return {native_link:{received:0,packets:[]}};}
 });
 room.session={token:'a'.repeat(64),code:'AB23CD45'};
 room.profile={firmware:'a'.repeat(64),transport:'b'.repeat(64)};
 return {room,calls,nodes};
}

test('native game is connected only when relay facade reports validated peer',async()=>{
 let connected=false;const transport={async request(action,fields,session){return {code:session.code,slot:0,connected,closed:false,accepted:0,packets:[]};},close(){}};
 const {room,calls}=harness(transport);
 try{
  await room.exchange();assert.equal(room.engine,false);assert.equal(calls.length,0);
  connected=true;room.autoResume=true;await room.exchange();
  assert.equal(room.engine,true);
  assert.deepEqual(calls[0],['native-link-connect',{session:'AB23CD45',slot:0}]);
  assert.equal(calls[1],'resume');
  assert.deepEqual(calls[2],['native-link-receive',{session:'AB23CD45',packets:[],accepted:0}]);
 }finally{await room.end(false);}
});

test('remote close releases relay locally and disconnects the native game',async()=>{
 let closed=0;const transport={async request(){return {code:'AB23CD45',slot:0,closed:true,connected:false};},close(){closed++;}};
 const {room,calls}=harness(transport);room.engine=true;
 await room.exchange();
 assert.equal(room.session,null);assert.equal(room.engine,false);assert.equal(closed,1);
 assert.ok(calls.some(x=>Array.isArray(x)&&x[0]==='native-link-disconnect'));
});

test('user disconnect cancels relay before awaiting native cleanup',async()=>{
 const order=[];const transport={async request(action){order.push(action);return {};},close(){order.push('close');}};
 const {room}=harness(transport);room.engine=true;
 room.rpc=async()=>{order.push('native-disconnect');return {};};
 await room.end();
 assert.deepEqual(order,['close','native-disconnect','leave']);
});

test('default transport creates the native HTTP relay invitation',async t=>{
 const bodies=[];
 t.mock.method(globalThis,'fetch',async(url,options)=>{
  bodies.push({url,body:JSON.parse(options.body)});
  return Response.json({code:'AB23CD45',slot:0,expires:Date.now()+1800000,connected:false,closed:false,peerProfile:null,accepted:0,packets:[]});
 });
 const {room}=harness();room.session.code=null;
 try{
  await room.exchange();assert.equal(room.session?.code,'AB23CD45');
  assert.equal(bodies[0].url,'https://pair.example/api/link');
  assert.deepEqual(bodies[0].body,{action:'create',token:'a'.repeat(64),code:null,profile:room.profile});
 }finally{await room.end(false);}
});

for(const status of [400,403,404,409,413,429,503])test(`HTTP ${status} disconnects native game without automatic repair`,async()=>{
 const actions=[];let closes=0;
 const transport={async request(action){actions.push(action);if(action==='leave')return {};throw Object.assign(Error('relay quota or protocol stop'),{status,terminal:true});},close(){closes++;}};
 const {room,calls,nodes}=harness(transport);room.engine=true;
 try{
  await room.exchange();assert.equal(room.session,null);assert.equal(room.engine,false);assert.equal(closes,1);
  assert.ok(calls.some(x=>Array.isArray(x)&&x[0]==='native-link-disconnect'));
  assert.match(nodes.get('link-status').textContent,/relay quota or protocol stop/);
  await room.exchange();assert.deepEqual(actions,['exchange','leave']);
 }finally{if(room.session)await room.end(false);}
});

test('terminal pairing error ends the invitation instead of polling or rescanning automatically',async()=>{
 const transport={async request(action){if(action==='leave')return {};throw Object.assign(Error('incompatible transport'),{status:409,terminal:true});},close(){}};
 const {room,nodes}=harness(transport);room.session.peer='BC23DE45';
 try{
  await room.exchange();assert.equal(room.session,null);assert.match(nodes.get('link-status').textContent,/incompatible transport/);
 }finally{if(room.session)await room.end(false);}
});

test('three consecutive network failures stop native game without re-pair or replay',async()=>{
 const actions=[];
 const transport={async request(action){actions.push(action);if(action==='leave')return {};throw Object.assign(Error('offline'),{retryable:true});},close(){}};
 const {room,calls}=harness(transport);room.engine=true;
 try{
  await room.exchange();assert.equal(room.engine,true);
  await room.exchange();assert.equal(room.engine,true);
  await room.exchange();assert.equal(room.session,null);assert.equal(room.engine,false);
  assert.deepEqual(actions,['exchange','exchange','exchange','leave']);
  assert.equal(calls.filter(x=>Array.isArray(x)&&x[0]==='native-link-disconnect').length,1);
 }finally{if(room.session)await room.end(false);}
});

test('a newly opened invitation starts its own bounded network retry count',async()=>{
 const transport={async request(action){if(action==='leave')return {};throw Object.assign(Error('offline'),{retryable:true});},close(){}};
 const {room}=harness(transport);
 try{
  await room.exchange();await room.exchange();await room.exchange();assert.equal(room.session,null);
  await room.enter();assert.ok(room.session,'first failure in a new invitation must allow a bounded retry');
  assert.equal(room.failures,1);
 }finally{if(room.session)await room.end(false);}
});

test('quota stop is visible after automatic return to native gameplay',async()=>{
 let quota=false;
 const transport={async request(action,fields,session){
  if(action==='leave')return {};
  if(quota)throw Object.assign(Error('免費連線服務額度已用盡'),{status:429,terminal:true});
  return {code:session.code,slot:0,connected:true,closed:false,accepted:0,packets:[]};
 },close(){}};
 const {room,nodes}=harness(transport);room.autoResume=true;
 try{
  await room.exchange();assert.equal(nodes.get('link-dialog').open,false);
  quota=true;await room.exchange();
  assert.equal(room.session,null);assert.equal(room.engine,false);
  assert.equal(nodes.get('link-dialog').open,true,'quota notice must be visible over game');
  assert.match(nodes.get('link-status').textContent,/額度已用盡/);
 }finally{if(room.session)await room.end(false);}
});
