// SPDX-License-Identifier: GPL-3.0-or-later
// Explicit R23 host care policy. Growth, sleep, routes and save/album commits
// remain native. Private firmware/ROM data are supplied by the user's machine.
const FIRMWARE='0c7953432d89c924221ee8b30054a25fd7c954ec35565b32bd499a5ac2daf882';
const IROM='d032000318fb0c7944064db6a3ac1479bdb498aa61715ca0ffaf34182f266b79';
const SIGNATURES=[
 [0x2da400,0x2da800,'0aa58992a35228078f70d298d5fd47850d60611d8889854cbaa713ab67a1b044'],
 [0x2dae00,0x2daf00,'1e1e6c2d3e0b02b81acede56f6ba25ff964a898a2c34a7f46b735a9cb127349d'],
 [0x210918,0x211000,'f93b71ca65c58459c392875f509c406c5afa0f0e4449de404ef3825e7fbe7b7a'],
 [0x2d1800,0x2d2000,'3d096081117305569f023afee705ce613aa047517f2a5ae122053068facdc446'],
 [0x2d1700,0x2d1800,'5b1d1966a7f73434fac10517ec283871e90857576861db4f2600c4e9c3e026d0'],
 [0x206900,0x207000,'0b593d1f2b85ea3dd4db0e8da70fbdebe999f23303259ee29407c5b174db1f2f'],
 [0x2cde00,0x2cdf00,'b8148e90c9a6f9f273a085696dffefec98bb5a39d35f4b055ba9469ef4ef3aa4']
];
const CONTEXT=[...Array.from({length:18},(_,i)=>0x826+i),...Array.from({length:19},(_,i)=>0xcf4+i)];
const hash=async bytes=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
const savedPage=p=>p===0x5f||(p>=0x7fd&&p<=0x7fe);

export class Gpce4Custody{
 static async create(machine){
  const c=new Gpce4Custody(machine),bin=machine.baseline;
  if(machine.identity?.firmware_sha256===FIRMWARE&&machine.identity?.irom_sha256===IROM&&bin?.length===0x800000){
   c.admitted=await hash(bin)===FIRMWARE&&await hash(machine.irom)===IROM&&
    (await Promise.all(SIGNATURES.map(async([a,z,digest])=>await hash(bin.subarray(2*(a-0x200000),2*(z-0x200000)))===digest))).every(Boolean);
  }
  return c;
 }
 constructor(machine){this.machine=machine;this.baseline=machine.baseline;this.admitted=false;}
 get e(){return this.machine.e;}
 get ram(){return new Uint16Array(this.e.memory.buffer,this.e.gp_ram_ptr(),0x3000);}
 get flash(){return new Uint8Array(this.e.memory.buffer,this.e.gp_flash_ptr(),0x800000);}
 get dirty(){return new Uint8Array(this.e.memory.buffer,this.e.gp_dirty_ptr(),2048);}
 reason(allowHomeSleep=false){
  if(!this.admitted||this.machine.baseline!==this.baseline||this.machine.identity?.firmware_sha256!==FIRMWARE)return 'unsupported-custody-firmware';
  if(typeof this.e.gp_custody_call!=='function'||typeof this.e.gp_sync_ui!=='function')return 'unsupported-custody-core';
  // An imported snapshot may contain programmed pages. Only R23's admitted
  // album/save regions may differ from the immutable firmware used for gates.
  const dirty=this.dirty,flash=this.flash;
  for(let p=0;p<2048;p++)if(dirty[p]&&!savedPage(p)){
   for(let n=p*4096;n<(p+1)*4096;n++)if(flash[n]!==this.baseline[n])return 'modified-custody-code';
  }
  const m=this.ram,metrics=this.machine.metrics();
  if(metrics[1])return 'native-machine-fault';
  if(this.machine.linkConnected||this.machine.linkFinishing)return 'connected-native-cable';
  if(m[0x81c]||m[0x820]||(this.e.gp_bus_read(0x3000)&0x38)!==0x38)return 'input-still-held';
  if(m[0xdab]&0x8000)return 'native-context-fatal';
  const homeSleep=allowHomeSleep&&m[0xc9c]===38&&m[0xc9d]===4&&metrics[14]===1;
  if(m[0xc9c]!==4&&!homeSleep)return 'native-state-'+m[0xc9c];
  if(m[0xdad])return 'native-action-pending';
  if(![0,2].includes(m[0xc9e])||m[0xcf3])return 'home-selection-or-scroll';
  if(m[0xcc2]>=60||m[0xcc3]>=60||m[0xcc4]>=24)return 'invalid-native-clock';
  return null;
 }
 call(entry,r1=0){
  const result=this.e.gp_custody_call(entry,r1,500000);
  if(result<0)throw Error('native-call-'+entry.toString(16)+'-'+result);
  return result;
 }
 select(owner){if(this.call(0x2d1700,owner)!==1)throw Error('native-owner-selection-failed');}
 owners(){return this.ram[0xdab]&0x40?[0,1]:[0];}
 stat(species,field){
  if(!Number.isInteger(species)||species<0||species>=312)throw Error('invalid-native-species');
  const at=0x2b000+2*(species*18+field);return this.baseline[at]|this.baseline[at+1]<<8;
 }
 health(){
  const m=this.ram;
  if(m[0x826]>=312||![0,1,2].includes(m[0xd04]))throw Error('invalid-native-pet-context');
  if(m[0x827]&0x30)throw Error('preexisting-death-or-terminal');
  if(m[0x827]&1)throw Error('unhatched-pet');
  if(m[0xcf4]&3||m[0xd00]!==65535||m[0xd01]!==65535)throw Error('preexisting-illness-or-injury');
 }
 care(){
  this.health();let m=this.ram;if(m[0x827]&0x40)return;
  const before=CONTEXT.map(a=>m[a]);
  m[0xcf5]=m[0xcf6]=4;m[0xcfd]=m[0xcfe]=m[0xcff]=65535;
  const bedtime=this.stat(m[0x826],1)>0?this.call(0x210e61):0;
  m=this.ram;if(m[0xd04]===1||m[0xd04]===2||bedtime)m[0xd06]=0;
  m[0xcf9]=0;
  if(m[0xcfc]===65535)m[0xcfc]=Math.floor(this.stat(m[0x826],11)/(m[0x836]===65535?2:1));
  if(CONTEXT.some((a,i)=>m[a]!==before[i]))m[0x85d]=1;
 }
 prepare(resolve=false){
  const owner=this.ram[0xdab]&1,pets=[];
  for(const slot of this.owners()){
   this.select(slot);this.care();
   if(resolve&&!(this.ram[0x827]&0x73)){
    if(this.ram[0xcf4]&4)this.call(0x2d1f40);
    this.call(0x210b53);
    if(this.ram[0xcf4]&4)this.call(0x2d1f40);
   }
   this.health();pets.push(this.ram.slice());
  }
  this.select(owner);return pets;
 }
 settle(pets=null){
  for(let frames=0;frames<128;frames++){
   if(!pets)pets=this.prepare();
   const m=this.ram;
   if(m[0xc9c]===4&&m[0xc9d]===4&&[0,2].includes(m[0xc9e])&&pets.every(p=>!(p[0x827]&2)))return frames;
   if(![4,24,36].includes(m[0xc9c]))throw Error('unsupported-native-event-'+m[0xc9c]);
   if(m[0xc9c]===4&&m[0xc9a]>0&&m[0xc9a]<0x42a)m[0xc9a]=0x42a;
   const skip=m[0xc9c]===24&&m[0xc9d]===24&&m[0xc9e]===m[0xc9f];
   m[0x81b]=skip?16:65535;m[0x81c]=skip?16:0;m[0x820]=0;
   this.call(0x2dae00);this.call(0x200000);this.call(0x2005e9);
   this.ram[0x81b]=65535;this.ram[0x81c]=this.ram[0x820]=0;pets=null;
  }
  throw Error('native-event-settlement-limit');
 }
 clock(seconds){
  const m=this.ram,total=(m[0xcc4]*3600+m[0xcc3]*60+m[0xcc2]+seconds)%86400;
  m[0xcc4]=Math.floor(total/3600);m[0xcc3]=Math.floor(total/60)%60;m[0xcc2]=total%60;m[0xcc7]=0;
 }
 span(pets,remaining){
  const m=this.ram;if(m[0xcc2])return 0;
  let limit=Math.floor(remaining/60);const now=m[0xcc4]*60+m[0xcc3];
  for(const p of pets){
   if(p[0x827]&0x40)continue;
   if(p[0x827]&0x33||p[0xcf4]&7||![0,2].includes(p[0xd04]))return 0;
   limit=Math.min(limit,1439-p[0x837]);const timers=[0x836];
   if(p[0xd04]!==2){limit=Math.min(limit,p[0xcfa]-1,p[0xcfb]-1);timers.push(0xcfc);}else timers.push(0xd03);
   for(const a of timers)if(p[a]!==65535)limit=Math.min(limit,p[a]-1);
   for(const [hfield,mfield] of [[5,6],[7,8]]){
    const hour=this.stat(p[0x826],hfield),minute=this.stat(p[0x826],mfield);
    if(hour>=24||minute>=60)return 0;
    const distance=((hour*60+minute-now+1440)%1440)||1440;limit=Math.min(limit,distance-1);
   }
  }
  return Math.max(0,limit);
 }
 advanceSpan(minutes){
  const owner=this.ram[0xdab]&1;
  for(const slot of this.owners()){
   this.select(slot);const m=this.ram;if(m[0x827]&0x40)continue;
   if(m[0x836]!==65535)m[0x836]-=minutes;m[0x837]+=minutes;
   if(m[0xd04]!==2){m[0xcfa]-=minutes;m[0xcfb]-=minutes;if(m[0xcfc]!==65535)m[0xcfc]-=minutes;}
   else if(m[0xd03]!==65535)m[0xd03]-=minutes;
   m[0x85d]=1;
  }
  this.select(owner);this.ram[0xdab]|=0x30;this.clock(minutes*60);
 }
 checkpoint(){
  const e=this.e,state=new Uint8Array(e.memory.buffer,e.gp_state_ptr(),e.gp_state_size()).slice(),pages=[];
  const dirty=this.dirty,flash=this.flash;
  for(let p=0;p<2048;p++)if(dirty[p])pages.push([p,flash.slice(p*4096,(p+1)*4096)]);
  return {state,pages};
 }
 rollback(saved){
  const e=this.e,dirty=this.dirty,flash=this.flash;
  for(let p=0;p<2048;p++)if(dirty[p])flash.set(this.baseline.subarray(p*4096,(p+1)*4096),p*4096);
  for(const [p,bytes] of saved.pages)flash.set(bytes,p*4096);
  const pointer=e.gp_state_ptr();new Uint8Array(e.memory.buffer,pointer,e.gp_state_size()).set(saved.state);
  if(e.gp_restore()!==1)throw Error('custody-rollback-failed');
  this.machine.motion?.enable();
  e.gp_audio_clear?.();
 }
 catchUp(seconds,{budgetMs=35}={}){
  if(!Number.isInteger(seconds)||seconds<0||seconds>2147483647)throw Error('Custody seconds must be a nonnegative bounded integer');
  if(typeof budgetMs!=='number'||!Number.isFinite(budgetMs)||budgetMs<=0||budgetMs>5000)throw Error('Custody budget must be finite positive milliseconds <=5000');
  const result={processed_seconds:0,remaining_seconds:seconds,blocked_reason:null,completed_frames:0,native_ms:0,native_minutes:0,batched_minutes:0};
  if(!seconds)return result;
  result.blocked_reason=this.reason(true);if(result.blocked_reason)return result;
  const start=performance.now();let first=true;
  // A restored PC may be inside an interrupted render/minute routine with
  // stale pet locals. Reach the real, IRQ-free native UI entry before edits.
  // Failed synchronization includes its peripheral and Flash effects in the
  // transaction; it must not cost a care miss while seeking the safe point.
  const initial=this.checkpoint(),history=[this.ram[0x82e],this.ram[0x840]].sort((a,b)=>a-b);
  try{
   // R23 native HOME display sleep is main 0x26, previous state HOME (4).
   // Wake via the actual IOA edge and native ROM; never assign a UI state.
   // Initial/setup sleep (0x25) and sleep from other activities stay blocked.
   if(this.ram[0xc9c]===38){
    this.e.gp_keys(16);
    if(this.e.gp_sync_ui(24000000)!==1)throw Error('native-home-wake-limit');
    this.e.gp_keys(0);
    if(![0,65535].includes(this.ram[0x81b]))throw Error('native-wake-key-event-pending');
    // Consume only native no-edge samples. The scanner needs four debounce
    // frames in the real sleep fixture; stop after eight rather than assign
    // key RAM or let an unexpected wake enter a menu.
    for(let frames=0;this.ram[0x81c]&&frames<8;frames++){
     if(this.ram[0xc9c]!==4||![0,65535].includes(this.ram[0x81b]))throw Error('native-wake-state-changed');
     this.e.gp_run(1);
     if(this.e.gp_sync_ui(24000000)!==1)throw Error('native-wake-release-limit');
    }
   }
   if(this.e.gp_sync_ui(24000000)!==1)throw Error('native-ui-sync-limit');
   const reason=this.reason();if(reason)throw Error(reason);
   const after=[this.ram[0x82e],this.ram[0x840]].sort((a,b)=>a-b);
   if(after.some((n,i)=>n>history[i]))throw Error('care-edge-during-native-sync');
  }catch(error){this.rollback(initial);result.blocked_reason='native-error: '+error.message;result.native_ms=performance.now()-start;return result;}
  while(result.remaining_seconds){
   if(result.processed_seconds&&performance.now()-start>=budgetMs)break;
   const saved=first?initial:this.checkpoint();let step=0,span=0,minute=0,frames=0;
   try{
    let pets=this.prepare(first);frames=this.settle(pets);if(frames)pets=this.prepare();
    span=this.span(pets,result.remaining_seconds);
    if(span){step=span*60;this.advanceSpan(span);}
    else{
     step=Math.min(result.remaining_seconds,60-this.ram[0xcc2]);this.clock(step);minute=Number(this.ram[0xcc2]===0);
     if(minute){this.prepare();this.call(0x2da800);pets=this.prepare();frames+=this.settle(pets);}
    }
    const reason=this.reason();if(reason)throw Error(reason);
   }catch(error){this.rollback(saved);result.blocked_reason='native-error: '+error.message;break;}
   this.e.gp_audio_clear?.();first=false;result.processed_seconds+=step;result.remaining_seconds-=step;
   result.completed_frames+=frames;result.native_minutes+=minute;result.batched_minutes+=span;
  }
  result.native_ms=Math.round((performance.now()-start)*1000)/1000;return result;
 }
}
