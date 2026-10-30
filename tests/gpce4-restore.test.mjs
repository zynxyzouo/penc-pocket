import test from 'node:test';import assert from 'node:assert/strict';import {readFile} from 'node:fs/promises';
import {Gpce4Machine} from '../public/gpce4-engine.js';import {MachineSession,machineKey} from '../public/machine-app.js';
async function fixture(){
 const bytes=Buffer.from((await readFile(new URL('../public/core/gpce4.wasm.b64',import.meta.url),'utf8')).trim(),'base64');
 const m=await Gpce4Machine.create(bytes,{internal_rom_sha256:null});const irom=new ArrayBuffer(98304),v=new DataView(irom);
 v.setUint16(0x17*2,0x480d,true);v.setUint16(0x80d*2,0xf165,true);v.setUint16(0x80e*2,0xee42,true);
 const bin=new ArrayBuffer(8388608),data=new Map();let full=false;
 const s=new MachineSession({rpc:async(op,f)=>{
  if(op==='load')return m.load(new Uint8Array(f.bin),new Uint8Array(f.irom));
  if(op==='keys'){m.keys(f.keys);return {};}
  if(op==='snapshot')return m.snapshot();if(op==='restore')return m.restore(f.snapshot);throw Error(op);
 },read:async k=>data.get(k),writeMany:async pairs=>{if(full)throw Error('QuotaExceededError');for(const [k,val] of pairs)data.set(k,val);},erase:async()=>{}});
 await s.load({bin,irom});s.show(m.run(1000));await s.save();const previous=await m.snapshot();
 return {m,s,data,previous,setFull:()=>{full=true;}};
}
test('storage failure after valid import rolls actual Wasm back and preserves save',async()=>{
 const f=await fixture(),key=machineKey(f.s.identity)+':save',stored=f.data.get(key);
 f.m.run(2000);const other=f.s.envelope(await f.m.snapshot());await f.m.restore(f.previous);f.s.show(f.m.present());f.setFull();
 await assert.rejects(f.s.importBackup(other),/Quota/);
 assert.equal((await f.m.snapshot()).checksum,f.previous.checksum);assert.equal(f.data.get(key),stored);assert.equal(f.s.fault,false);assert.equal(f.s.frame.instructions,1000);
});
test('importing a faulted diagnostic snapshot cannot replace healthy live state',async()=>{
 const f=await fixture();f.m.run(1000);f.m.e.gp_bus_read(0x10000);const bad=f.s.envelope(await f.m.snapshot());
 await f.m.restore(f.previous);f.s.show(f.m.present());await assert.rejects(f.s.importBackup(bad),/停止/);
 assert.equal((await f.m.snapshot()).checksum,f.previous.checksum);assert.equal(f.s.fault,false);assert.equal(f.s.saveBlocked,false);
});
test('failed rollback preserves an exportable recovery until a successful load',async()=>{
 const f=await fixture();f.m.e.gp_bus_read(0x10000);const bad=f.s.envelope(await f.m.snapshot());
 await f.m.restore(f.previous);f.s.show(f.m.present());const rpc=f.s.rpc;let restores=0;
 f.s.rpc=(op,args)=>op==='restore'&&++restores===2?Promise.reject(Error('worker unavailable')):rpc(op,args);
 await assert.rejects(f.s.importBackup(bad),/無法回復/);
 assert.equal((await f.s.exportBackup()).snapshot.checksum,f.previous.checksum);
 f.s.rpc=rpc;await f.s.load(f.s.inputs);
 assert.equal(f.s.recoveryBackup,null);
});
