// SPDX-License-Identifier: GPL-3.0-or-later
// Full-machine adapter: ROMs are supplied locally and never fetched or uploaded.
import {Gpce4AudioObserver} from './gpce4-audio.js';
import {Gpce4Motion} from './gpce4-motion.js';
import {Gpce4Link} from './gpce4-link.js';
import {Gpce4Custody} from './gpce4-custody.js';
export const PREVIOUS_CORES=Object.freeze(['03ddb497ec7559d88bc563e0eddaff2f847137edaebb10c1841db0a9f34cd76b']);
export const compatibleCore=(current,previous)=>current===previous||PREVIOUS_CORES.includes(previous);
const FLASH_SIZE=8388608,ROM_SIZE=98304,PAGE_SIZE=4096;
const FORMAT='penc-gpce4-machine-v1';
export function validateInputs(bin,irom){
 if(!(bin instanceof Uint8Array)||bin.byteLength!==FLASH_SIZE)throw Error('請選取 8 MiB 的 PenC 韌體 BIN。');
 if(!(irom instanceof Uint8Array)||irom.byteLength!==ROM_SIZE)throw Error('請選取 96 KiB 的 PenC 內建 ROM。');
}
export function encodeBytes(bytes){let s='';for(let i=0;i<bytes.length;i+=8192)s+=String.fromCharCode(...bytes.subarray(i,i+8192));return btoa(s);}
export function decodeBytes(text,size){
 if(typeof text!=='string'||text.length!==4*Math.ceil(size/3)||!/^[A-Za-z0-9+/]*={0,2}$/.test(text))throw Error('快照內容或長度不正確。');
 let raw;try{raw=atob(text);}catch{throw Error('快照編碼不正確。');}
 const bytes=Uint8Array.from(raw,c=>c.charCodeAt(0));
 if(bytes.length!==size||encodeBytes(bytes)!==text)throw Error('快照內容不正確。');return bytes;
}
export async function sha256(bytes){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');}
const snapshotDigest=data=>sha256(new TextEncoder().encode(JSON.stringify(data)));
const clock=s=>{const n=Math.floor(s);return [Math.floor(n/3600),Math.floor(n/60)%60,n%60].map(x=>String(x).padStart(2,'0')).join(':');};
export class Gpce4Machine{
 static async create(bytes,config){
  const core=await sha256(bytes);
  if(config.sha256&&config.sha256!==core)throw Error('整機核心版本不一致，請重新整理。');
  return new Gpce4Machine(await WebAssembly.compile(bytes),core,config.internal_rom_sha256);
 }
 constructor(module,core,expectedRom){this.module=module;this.core=core;this.expectedRom=expectedRom;this.instance=null;}
 async candidate(bin,irom){
  const instance=await WebAssembly.instantiate(this.module,{}),e=instance.exports;
  new Uint8Array(e.memory.buffer,e.gp_irom_ptr(),ROM_SIZE).set(irom);
  new Uint8Array(e.memory.buffer,e.gp_flash_ptr(),FLASH_SIZE).set(bin);
  if(e.gp_reset(12000000)!==1)throw Error('無法初始化整機核心。');
  return instance;
 }
 async load(bin,irom){
  validateInputs(bin,irom);
  const [fwHash,romHash]=await Promise.all([sha256(bin),sha256(irom)]);
  if(this.expectedRom&&romHash!==this.expectedRom)throw Error('這份內建 ROM 尚未驗證；目前需要 PenC 的 96 KiB 讀出檔，DMC ROM 不適用。');
  const instance=await this.candidate(bin,irom);
  this.baseline=bin.slice();this.irom=irom.slice();this.identity={firmware_sha256:fwHash,irom_sha256:romHash,core_sha256:this.core};
  this.instance=instance;
  [this.audio,this.motion,this.link]=await Promise.all([Gpce4AudioObserver.create(this.baseline),Gpce4Motion.create(this.baseline,()=>this.e),Gpce4Link.create(this.baseline,fwHash,()=>this.e)]);
  this.motion.enable();this.custody=await Gpce4Custody.create(this);return this.present();
 }
 get e(){if(!this.instance)throw Error('請先載入內建 ROM 與韌體。');return this.instance.exports;}
 metrics(){const e=this.e;return new Uint32Array(e.memory.buffer,e.gp_metrics_ptr(),24).slice();}
 checkFault(){const m=this.metrics();if(m[1])throw Error(`整機核心停止：錯誤 ${m[1]}，PC ${m[2].toString(16)}，指令 ${m[3].toString(16)}，位址 ${m[4].toString(16)}。可先匯出快照。`);}
 keys(mask){if(!Number.isInteger(mask)||mask<0||(mask&~0x38)!==0)throw Error('按鍵資料不正確。');this.e.gp_keys(mask);}
 get linkConnected(){return !!this.link?.connected;}
 run(instructions,keys=0,motion=false){
  if(!Number.isInteger(instructions)||instructions<1||instructions>250000)throw Error('執行批次超出範圍。');
  this.keys(keys);this.motion?.pulse(motion);const events=[];
  if(this.link?.connected)this.link.run(instructions,()=>events.push(...this.audio.consume(this.e)));
  else{this.e.gp_run(instructions);this.checkFault();events.push(...(this.audio?.consume(this.e)||[]));}
  this.checkFault();return {...this.present(),audio:events};
 }
 present(){
  const e=this.e,m=this.metrics(),instructions=m[5]+m[6]*4294967296,steps=m[7]+m[8]*4294967296,seconds=instructions/m[18];
  return {family:'gpce4',execution_core:'gpce4-wasm-reset',identity:{...this.identity},clock:clock(seconds),time_rate:1,
   steps,pc:m[9],pixels:m[10]+m[11]*4294967296,instructions,virtual_seconds:seconds,sleeping:!!m[14],
   unknown_io:m[15],dirty_pages:m[17],lcd_on:!!m[19],fault:m[1],
   ...(this.motion?.metadata()||{}),native_link:this.link?.metadata(),
   native_settings:{supported:!!this.audio?.supported,volume_level:new Uint16Array(e.memory.buffer,e.gp_ram_ptr(),0x3000)[0xCAC]},
   custody_supported:!!this.custody?.admitted,
   rgba:encodeBytes(new Uint8Array(e.memory.buffer,e.gp_rgba_ptr(),96*96*4))};
 }
 async snapshot(){
  if(this.linkConnected)throw Error('連線期間請先中斷連線，再保存完整快照。');
  const e=this.e,state=encodeBytes(new Uint8Array(e.memory.buffer,e.gp_state_ptr(),e.gp_state_size()));
  const dirty=new Uint8Array(e.memory.buffer,e.gp_dirty_ptr(),2048),flash=new Uint8Array(e.memory.buffer,e.gp_flash_ptr(),FLASH_SIZE),pages=[];
  for(let p=0;p<2048;p++)if(dirty[p])pages.push([p,encodeBytes(flash.subarray(p*PAGE_SIZE,(p+1)*PAGE_SIZE))]);
  const data={format:FORMAT,...this.identity,state,flash_pages:pages};
  return {...data,checksum:await snapshotDigest(data)};
 }
 async restore(snapshot){
  const e=this.e;
  if(!snapshot||snapshot.format!==FORMAT)throw Error('這不是整機核心的快照，原模式快照不能直接匯入。');
  if(this.linkConnected)throw Error('請先中斷連線再匯入快照。');
  for(const key of ['firmware_sha256','irom_sha256'])if(snapshot[key]!==this.identity[key])throw Error('快照的 BIN、內建 ROM 或核心版本不同，原進度保留。');
  if(!compatibleCore(this.core,snapshot.core_sha256))throw Error('快照的核心版本不同，原進度保留。');
  const state=decodeBytes(snapshot.state,e.gp_state_size());
  if(!Array.isArray(snapshot.flash_pages)||snapshot.flash_pages.length>2048)throw Error('Flash 快照頁數不正確。');
  let previous=-1;
  const pages=snapshot.flash_pages.map(pair=>{
   if(!Array.isArray(pair)||pair.length!==2||!Number.isInteger(pair[0])||pair[0]<=previous||pair[0]>2047)throw Error('Flash 快照頁序不正確。');
   previous=pair[0];return [pair[0],decodeBytes(pair[1],PAGE_SIZE)];
  });
  const data={format:FORMAT,...this.identity,core_sha256:snapshot.core_sha256,state:snapshot.state,flash_pages:snapshot.flash_pages};
  if(snapshot.checksum!==await snapshotDigest(data))throw Error('快照校驗不符，原進度保留。');
  // A failed restore never mutates the active machine or the immutable BIN.
  const candidate=await this.candidate(this.baseline,this.irom),ce=candidate.exports;
  new Uint8Array(ce.memory.buffer,ce.gp_state_ptr(),ce.gp_state_size()).set(state);
  if(ce.gp_restore()!==1)throw Error('快照機器狀態不正確，原進度保留。');
  const dirty=new Uint8Array(ce.memory.buffer,ce.gp_dirty_ptr(),2048),pageSet=new Set(pages.map(p=>p[0]));
  for(let p=0;p<2048;p++)if(!!dirty[p]!==pageSet.has(p))throw Error('快照 Flash 頁面不完整，原進度保留。');
  const flash=new Uint8Array(ce.memory.buffer,ce.gp_flash_ptr(),FLASH_SIZE);
  for(const [p,bytes] of pages)flash.set(bytes,p*PAGE_SIZE);
  this.instance=candidate;this.link?.detach();this.motion?.enable();return this.present();
 }
 connect(session,slot){this.link.connect(session,slot);return this.present();}
 receive(session,packets,accepted){this.link.receive(session,packets,accepted);return {native_link:this.link.metadata()};}
 disconnect(){
  if(!this.linkConnected)return this.present();
  const ram=()=>new Uint16Array(this.e.memory.buffer,this.e.gp_ram_ptr(),0x3000);
  const physical=()=>[15,16,19].includes(ram()[0xC9C]);
  const phase={15:5,16:3,19:3},finishing=physical()&&ram()[0xC9E]>=phase[ram()[0xC9C]];
  // Native C input cancels waiting. Settled animations retain their outcome.
  if(finishing&&ram()[0xCA0]===0&&ram()[0xCCC]===0){this.keys(0);this.e.gp_audio_clear();this.motion?.clear();this.link.detach();return this.present();}
  if(!finishing&&physical())this.e.gp_link_cancel();
  for(let n=0;(physical()||ram()[0xDAD])&&n<256;n++){this.keys(0);this.link.run(187500);this.checkFault();}
  this.keys(0);this.e.gp_audio_clear();this.motion?.clear();
  if(physical()||ram()[0xDAD])throw Error('原生連線尚未完成返回；請回遊戲再重試中斷。');
  this.link.detach();return this.present();
 }
 async catchUp(seconds){const result=await this.custody.catchUp(seconds,{budgetMs:35});return {...this.present(),custody:result};}
 flash(){const e=this.e;return new Uint8Array(e.memory.buffer,e.gp_flash_ptr(),FLASH_SIZE).slice().buffer;}
}
