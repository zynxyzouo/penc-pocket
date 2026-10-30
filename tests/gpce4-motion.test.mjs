import test from 'node:test';
import assert from 'node:assert/strict';
import {access,readFile} from 'node:fs/promises';

const source=new URL('../public/gpce4-motion.js',import.meta.url);
async function adapter(){
 assert.equal(await access(source).then(()=>true,()=>false),true,'Admitted full-machine motion adapter must exist');
 return import(source);
}
async function core(bin=null,irom=null){
 const wasm=Buffer.from((await readFile(new URL('../public/core/gpce4.wasm.b64',import.meta.url),'utf8')).trim(),'base64');
 const {instance}=await WebAssembly.instantiate(wasm,{}),e=instance.exports;
 if(bin)new Uint8Array(e.memory.buffer,e.gp_flash_ptr(),bin.length).set(bin);
 if(irom)new Uint8Array(e.memory.buffer,e.gp_irom_ptr(),irom.length).set(irom);
 else {const rom=new Uint16Array(e.memory.buffer,e.gp_irom_ptr(),0xc000);rom[0x17]=0x4000;rom[0]=0xee41;}
 assert.equal(e.gp_reset(12000000),1);
 return {e,ram:new Uint16Array(e.memory.buffer,e.gp_ram_ptr(),0x3000),cpu:new Uint32Array(e.memory.buffer,e.gp_cpu_ptr(),24)};
}
const snapshot=e=>new Uint8Array(e.memory.buffer,e.gp_state_ptr(),e.gp_state_size()).slice();
function entry(c,pc){
 c.cpu[0]=0xff0;c.cpu[6]=pc>>>16;c.cpu[7]=pc&65535;c.cpu[8]=0;
 c.ram[0xff1]=0;c.ram[0xff2]=0x1100;c.ram[0x1100]=0xee41;
}
test('foreign firmware refuses motion without changing machine state',async()=>{
 const {Gpce4Motion}=await adapter(),c=await core(),before=snapshot(c.e);
 const motion=await Gpce4Motion.create(new Uint8Array(8388608),()=>c.e);
 assert.equal(motion.enable(),false);assert.equal(motion.pulse(true),false);motion.clear();
 assert.deepEqual(motion.metadata(),{motion_supported:false,motion_ready:false,motion_count:0});
 assert.deepEqual(snapshot(c.e),before);
});
test('motion accepts a single boolean pulse rather than arbitrary counts',async()=>{
 const {Gpce4Motion}=await adapter(),c=await core();
 const motion=await Gpce4Motion.create(new Uint8Array(8388608),()=>c.e);
 for(const input of [undefined,null,1,0,'true',[],{}])assert.throws(()=>motion.pulse(input),/boolean/i);
 assert.equal(motion.pulse(false),false);
});

const binPath=process.env.PENC_AUDIO_BIN,romPath=process.env.PENC_AUDIO_IROM;
test('private firmware native consumer alone advances count once per bounded pending pulse',
 {skip:!binPath||!romPath},async()=>{
 const {Gpce4Motion}=await adapter(),bin=new Uint8Array(await readFile(binPath)),rom=new Uint8Array(await readFile(romPath));
 let c=await core(bin,rom);const motion=await Gpce4Motion.create(bin,()=>c.e);
 assert.equal(motion.enable(),true);
 entry(c,0x201bcc);assert.equal(c.e.gp_run(1),1);
 assert.deepEqual(motion.metadata(),{motion_supported:true,motion_ready:true,motion_count:0});
 const before=snapshot(c.e);assert.equal(motion.pulse(true),true);assert.equal(motion.pulse(true),true);
 assert.deepEqual(snapshot(c.e),before,'host input must not directly change firmware state');
 entry(c,0x201cda);c.e.gp_run(500);
 assert.equal(c.ram[0xd41],1);assert.equal(c.ram[0xd3d],0);
 entry(c,0x201cda);c.e.gp_run(500);assert.equal(c.ram[0xd41],1,'pending input must be consumed once');
 motion.pulse(true);motion.clear();entry(c,0x201cda);c.e.gp_run(500);assert.equal(c.ram[0xd41],1);
 motion.pulse(true);c.e.gp_run(3000001);entry(c,0x201cda);c.e.gp_run(500);assert.equal(c.ram[0xd41],1,'expired input must not reach a later consumer');
 entry(c,0x201d1e);c.e.gp_run(1);assert.equal(motion.metadata().motion_ready,false);assert.equal(motion.pulse(true),false);
 // New/restored machine has no pending gesture. Re-enable admission for the
 // replacement exports without carrying input across the identity boundary.
 c=await core(bin,rom);motion.enable();entry(c,0x201bcc);c.e.gp_run(1);
 motion.pulse(true);const saved=snapshot(c.e);new Uint8Array(c.e.memory.buffer,c.e.gp_state_ptr(),saved.length).set(saved);
 assert.equal(c.e.gp_restore(),1);assert.equal(motion.enable(),true);
 entry(c,0x201cda);c.e.gp_run(500);assert.equal(c.ram[0xd41],0);
 // Admission uses every sensor function, not a release filename.
 for(const offset of [2*0x1bcc,2*0x1cda,2*0x1d1e]){
  const changed=bin.slice();changed[offset]^=1;
  const rejected=await Gpce4Motion.create(changed,()=>c.e);assert.equal(rejected.enable(),false);
 }
 assert.equal(new Uint32Array(c.e.memory.buffer,c.e.gp_metrics_ptr(),24)[1],0);
});
