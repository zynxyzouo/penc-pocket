import test from 'node:test';
import assert from 'node:assert/strict';
import {access,readFile} from 'node:fs/promises';

const source=new URL('../public/gpce4-audio.js',import.meta.url);
async function audio(){
 assert.equal(await access(source).then(()=>true,()=>false),true,'Full-machine audio observer must be implemented');
 return import(source);
}
function sequence(){
 const bytes=new Uint8Array(8388608),v=new DataView(bytes.buffer);
 for(const [at,word] of [[0x40000,0x800],[0x40002,0x20],[0x40004,0x806],[0x40006,0x20],
   [0x1000,1],[0x1002,60],[0x1004,100],[0x1006,74],[0x1008,50],[0x100a,65535]])v.setUint16(at,word,true);
 return bytes;
}
test('raw decoder preserves note/rest duration pairs and rejects unknown ids',async()=>{
 const {decodeGpce4Sequence}=await audio(),bytes=sequence();
 assert.deepEqual(decodeGpce4Sequence(bytes,0),{id:0,notes:[[60,100],[74,50]],approximate:true});
 for(const id of [-1,24,1.5,null,'0'])assert.equal(decodeGpce4Sequence(bytes,id),null);
});
test('raw decoder refuses malformed pointers, unknown notes, and unterminated sequences',async()=>{
 const {decodeGpce4Sequence}=await audio();
 for(const [at,value] of [[0x40002,0x21],[0x40004,0x804],[0x1000,0],[0x1002,75],[0x1004,0],[0x1004,4097],[0x100a,60]]){
  const bytes=sequence();new DataView(bytes.buffer).setUint16(at,value,true);
  assert.equal(decodeGpce4Sequence(bytes,0),null,`malformed word at ${at.toString(16)}`);
 }
 assert.equal(decodeGpce4Sequence(new Uint8Array(20),0),null);
});
test('unrecognized firmware stays silent even if a native request was observed',async()=>{
 const {Gpce4AudioObserver}=await audio(),observer=await Gpce4AudioObserver.create(sequence());
 const memory=new WebAssembly.Memory({initial:1});new Uint32Array(memory.buffer,0,4).set([0,0,123,0]);
 let count=1;
 const e={memory,gp_audio_event_count:()=>count,gp_audio_events_ptr:()=>0,gp_audio_clear:()=>{count=0;}};
 assert.equal(observer.supported,false);assert.deepEqual(observer.consume(e),[]);assert.equal(count,0);
});

const privateBin=process.env.PENC_AUDIO_BIN,privateRom=process.env.PENC_AUDIO_IROM;
test('private BIN admission consumes actual Wasm call events once without changing native state',
 {skip:!privateBin||!privateRom},async()=>{
 const {Gpce4AudioObserver}=await audio();
 const bin=new Uint8Array(await readFile(privateBin)),irom=new Uint8Array(await readFile(privateRom));
 const wasm=Buffer.from((await readFile(new URL('../public/core/gpce4.wasm.b64',import.meta.url),'utf8')).trim(),'base64');
 const {instance}=await WebAssembly.instantiate(wasm,{}),e=instance.exports;
 new Uint8Array(e.memory.buffer,e.gp_flash_ptr(),bin.length).set(bin);
 new Uint8Array(e.memory.buffer,e.gp_irom_ptr(),irom.length).set(irom);assert.equal(e.gp_reset(12000000),1);
 const observer=await Gpce4AudioObserver.create(bin);assert.equal(observer.supported,true);
 const ram=new Uint16Array(e.memory.buffer,e.gp_ram_ptr(),0x3000),cpu=new Uint32Array(e.memory.buffer,e.gp_cpu_ptr(),24);
 // A synthetic RAM CALL reaches the actual admitted native function. SP+1 is its argument.
 ram[0x100]=0xf060;ram[0x101]=0x00a9;ram[0x801]=0;cpu[0]=0x800;cpu[6]=0;cpu[7]=0x100;cpu[8]=0;
 assert.equal(e.gp_run(1),1);assert.equal(e.gp_audio_event_count(),1);
 const snapshot=()=>new Uint8Array(e.memory.buffer,e.gp_state_ptr(),e.gp_state_size()).slice();
 const before=snapshot(),events=observer.consume(e);
 assert.equal(events.length,1);assert.equal(events[0].id,0);assert.equal(events[0].approximate,true);
 assert.ok(events[0].notes.length>0);assert.deepEqual(snapshot(),before);assert.deepEqual(observer.consume(e),[]);
 // Restoring a busy sound must neither enqueue nor replay it.
 ram[0xca1]=1;const busy=snapshot();new Uint8Array(e.memory.buffer,e.gp_state_ptr(),busy.length).set(busy);
 assert.equal(e.gp_restore(),1);assert.deepEqual(observer.consume(e),[]);assert.equal(ram[0xca1],1);
 // Changed front-end code loses admission instead of inventing semantics.
 cpu[0]=0x800;cpu[6]=0;cpu[7]=0x100;ram[0x801]=0;e.gp_run(1);
 new Uint8Array(e.memory.buffer,e.gp_flash_ptr(),bin.length)[0xa0]^=1;
 assert.deepEqual(observer.consume(e),[]);
});
