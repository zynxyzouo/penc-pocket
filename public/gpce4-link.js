// SPDX-License-Identifier: GPL-3.0-or-later
// Packet peripheral for admitted PenC firmware. The firmware owns packet
// construction, validation, battle/Jogres outcomes, animation and Flash writes.
// This is a network cable adapter, not an emulation of physical wire timing.
const SIGNATURES=[
 [0x2084e9,0x208571,'25c92b9a8e6a27673c3e77a6a4579204efe02aa696398134d708838b32a630fb'],
 [0x208571,0x208595,'938cb122f598d585552454d20b099095adfd7690145d1c5d72312da284336406'],
 [0x208595,0x2085bf,'d1320b01c4b9be3008c4983ad37857379013039a73dc201af96fff6ce8918d70'],
 [0x2085bf,0x208763,'1bf6e237470a822813856bd0329d46badf89e1ea50c03c2bd152b0253beab76f'],
 [0x208763,0x208926,'8855ca1f7b7d91aa1d288b54d2167c69c496be18b8f7540d0577f9103ff5945f'],
 [0x208926,0x208a82,'b3459df2929ad8ad9d53871039c5acb16b4ecf2324c016c84ba810040dd54497'],
 [0x21f3d0,0x21f562,'18c241eb6134710b3320678e8f8e005d5ae126c64c99241cc4ca771f2c106f3b'],
 // Native UI dispatcher entry is the boundary for delivery/network waiting.
 [0x2005e9,0x2005f9,'390f763a7a673e4a873856e2e0729409007d1450316a0e8389999d872ac315d1'],
 // Disconnect executes the existing native C branch and HOME ownership return.
 [0x201f36,0x2020f6,'82da8b739e08f640c862d13bfdbff8751d771aaee50a62c94f22001bddff7773'],
 [0x2d8a02,0x2d8a85,'fe534d1e1431a0d800c2bac3c0a36cc91e1be456b847d79e3f91c33cf6795b44'],
];
const TRANSPORT='77a6e9d5d083278cbf726f3e4d82d6239dab919c0f4a2c8211d807e5cd48dc53';
const MAX_PACKETS=512,HEX=/^[0-9a-f]{64}$/;
const integer=(n,min,max)=>Number.isSafeInteger(n)&&n>=min&&n<=max;
const same=(a,b)=>a.length===b.length&&a.every((v,i)=>v===b[i]);
const digest=async bytes=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(n=>n.toString(16).padStart(2,'0')).join('');

export class Gpce4Link{
 static async create(bin,firmware,getExports){
  let supported=bin instanceof Uint8Array&&bin.length===8388608&&typeof firmware==='string'&&HEX.test(firmware);
  if(supported){const checks=await Promise.all(SIGNATURES.map(async([start,end,hash])=>await digest(bin.subarray(2*(start-0x200000),2*(end-0x200000)))===hash));supported=checks.every(Boolean);}
  const ranges=supported?SIGNATURES.map(([a,z])=>({offset:2*(a-0x200000),bytes:bin.subarray(2*(a-0x200000),2*(z-0x200000))})):[];
  return new Gpce4Link({getExports,profile:supported?{firmware,transport:TRANSPORT}:null,ranges});
 }
 constructor({getExports,profile,ranges=[]}){
  this.getExports=getExports;this.profile=profile?{...profile}:null;
  this.ranges=ranges.map(({offset,bytes})=>({offset,bytes:new Uint8Array(bytes)}));this.clear();
 }
 clear(){this.connected=false;this.session=null;this.slot=null;this.received=0;this.accepted=0;this.nextSeq=1;this.rx=new Map();this.history=new Map();this.tx=[];}
 get e(){return this.getExports();}
 assertCurrentCode(){
  const e=this.e;
  for(const {offset,bytes} of this.ranges){
   const current=new Uint8Array(e.memory.buffer,e.gp_flash_ptr()+offset,bytes.length);
   if(!same(bytes,current))throw Error('目前 Flash 的原生通訊程式已變更，無法接通連線。');
  }
 }
 connect(session,slot){
  if(!this.profile)throw Error('這份 BIN 的原生通訊尚未支援。');
  if(typeof session!=='string'||session.length<1||session.length>128||!integer(slot,0,1))throw Error('連線識別資料不正確。');
  this.assertCurrentCode();
  if(this.connected){if(this.session===session&&this.slot===slot)return this.metadata();throw Error('請先中斷目前連線。');}
  this.e.gp_link_enable(1);this.clear();this.connected=true;this.session=session;this.slot=slot;return this.metadata();
 }
 receive(session,packets,accepted){
  if(!this.connected||session!==this.session)throw Error('連線已中斷或封包屬於舊連線。');
  if(!Array.isArray(packets)||packets.length>MAX_PACKETS)throw Error('連線封包數量不正確。');
  const trial=new Map(this.rx);let maximum=this.received+trial.size;
  for(const packet of packets){
   if(!packet||typeof packet!=='object'||Array.isArray(packet)||Object.keys(packet).length!==2||!Object.hasOwn(packet,'seq')||!Object.hasOwn(packet,'words'))throw Error('連線封包格式不正確。');
   const {seq,words}=packet;
   if(!integer(seq,1,MAX_PACKETS)||!Array.isArray(words)||words.length!==8||words.some(w=>!integer(w,0,65535)))throw Error('原生封包需要八個 16 位元字組。');
   const previous=this.history.get(seq)||trial.get(seq);
   if(previous){if(!same(previous,words))throw Error('重送封包的內容不一致。');continue;}
   if(seq!==maximum+1)throw Error('原生封包順序不正確。');
   trial.set(seq,words.slice());maximum=seq;
  }
  if(accepted!==undefined&&(!integer(accepted,this.accepted,this.nextSeq-1)))throw Error('服務確認了尚未送出的封包。');
  this.rx=trial;
  if(accepted!==undefined){this.accepted=accepted;this.tx=this.tx.filter(p=>p.seq>accepted);}
  this.service();return this.metadata();
 }
 service(){
  if(!this.connected)return;
  const e=this.e;
  if(e.gp_link_status()===1){
   if(this.nextSeq>MAX_PACKETS)throw Error('本次連線封包已達上限，請重新配對。');
   const words=[...new Uint16Array(e.memory.buffer,e.gp_link_tx_ptr(),8)];
   if(e.gp_link_tx_take()!==1)throw Error('原生傳送封包狀態不一致。');
   this.tx.push({seq:this.nextSeq++,words});
  }
  const seq=this.received+1,words=this.rx.get(seq);
  if(words){
   new Uint16Array(e.memory.buffer,e.gp_link_rx_ptr(),8).set(words);
   // Acceptance transfers custody into the core's single inbox. The C core
   // applies those exact words only at its admitted native UI boundary.
   if(e.gp_link_receive()===1){this.rx.delete(seq);this.history.set(seq,words);this.received=seq;}
  }
 }
 run(instructions,onBatch){
  if(!integer(instructions,1,250000))throw Error('執行批次超出範圍。');
  let done=0;
  for(let attempts=0;done<instructions&&attempts<=MAX_PACKETS+1;attempts++){
   if(this.connected)this.assertCurrentCode();
   this.service();const n=this.e.gp_run(instructions-done);done+=n;onBatch?.(n);
   const pending=this.connected&&this.e.gp_link_status()===1;this.service();
   if(!n&&!pending)break;
  }
  return done;
 }
 // The caller first finishes native C cancellation or the already-settled
 // animation. Clearing the network session must never assign game results.
 detach(){this.e.gp_link_enable(0);this.clear();return this.metadata();}
 metadata(){return {supported:!!this.profile,connected:this.connected,session:this.session,slot:this.slot,
  received:this.received,packets:this.tx.map(p=>({seq:p.seq,words:p.words.slice()})),
  waiting:this.connected&&this.e.gp_link_status()===2,profile:this.profile?{...this.profile}:null};}
}
