import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {Gpce4Machine,validateInputs,decodeBytes,encodeBytes} from '../public/gpce4-engine.js';

test('full machine requires both exact local image sizes',()=>{
 assert.throws(()=>validateInputs(new Uint8Array(8),new Uint8Array(98304)),/8 MiB/);
 assert.throws(()=>validateInputs(new Uint8Array(8388608),new Uint8Array(2)),/96 KiB/);
 assert.doesNotThrow(()=>validateInputs(new Uint8Array(8388608),new Uint8Array(98304)));
});
test('binary snapshot codec rejects noncanonical and oversized content',()=>{
 const raw=new Uint8Array([0,255,13,44]);assert.deepEqual(decodeBytes(encodeBytes(raw),4),raw);
 for(const value of ['AAAAAA==\n','*','AAAAAA==AAAA','AAAA'])assert.throws(()=>decodeBytes(value,4));
});
function fixture(){
 const irom=new Uint8Array(98304),v=new DataView(irom.buffer);
 v.setUint16((0x4017-0x4000)*2,0x480d,true);
 v.setUint16((0x480d-0x4000)*2,0xf165,true);
 v.setUint16((0x480e-0x4000)*2,0xee42,true);
 return {irom,bin:new Uint8Array(8388608).fill(255)};
}
async function machine(){
 const bytes=Buffer.from((await readFile(new URL('../public/core/gpce4.wasm.b64',import.meta.url),'utf8')).trim(),'base64');
 return Gpce4Machine.create(bytes,{internal_rom_sha256:null});
}
test('actual Wasm runs synthetic reset ROM and restores atomically',async()=>{
 const m=await machine(),f=fixture();await m.load(f.bin,f.irom);
 const first=m.run(1000,0);assert.equal(first.instructions,1000);assert.equal(first.steps,1000);
 const snapshot=await m.snapshot();m.run(2000,8);const expected=await m.snapshot();
 await m.restore(snapshot);m.run(2000,8);assert.deepEqual(await m.snapshot(),expected);
 const before=await m.snapshot();const broken=structuredClone(snapshot);broken.state=broken.state.slice(4);
 await assert.rejects(m.restore(broken));assert.deepEqual(await m.snapshot(),before);
 const wrong=structuredClone(snapshot);wrong.firmware_sha256='0'.repeat(64);
 await assert.rejects(m.restore(wrong),/不同/);assert.deepEqual(await m.snapshot(),before);
});
test('invalid replacement input preserves running machine',async()=>{
 const m=await machine(),f=fixture();await m.load(f.bin,f.irom);m.run(1000,0);const before=await m.snapshot();
 await assert.rejects(m.load(new Uint8Array(1),f.irom));assert.deepEqual(await m.snapshot(),before);
});

test('disconnecting a QR pair before native battle preserves a busy setup screen',async()=>{
 const m=await machine(),f=fixture();await m.load(f.bin,f.irom);m.keys(0);
 const ram=new Uint16Array(m.e.memory.buffer,m.e.gp_ram_ptr(),0x3000);
 // Synthetic UI fixture: DAD is a shared screen lock, not a link-active flag.
 ram[0xc9c]=2;ram[0xdad]=1;
 m.link.profile={firmware:m.identity.firmware_sha256,transport:'a'.repeat(64)};
 const before=await m.snapshot();m.connect('setup-pair',0);
 assert.equal(m.disconnect().native_link.connected,false);
 assert.deepEqual(await m.snapshot(),before);
});

test('private native title can pair and disconnect without advancing or resetting the game',
 {skip:!process.env.PENC_AUDIO_BIN||!process.env.PENC_AUDIO_IROM},async()=>{
 const m=await machine();await m.load(new Uint8Array(await readFile(process.env.PENC_AUDIO_BIN)),new Uint8Array(await readFile(process.env.PENC_AUDIO_IROM)));
 for(let i=0;i<96;i++)m.run(250000);
 const ram=new Uint16Array(m.e.memory.buffer,m.e.gp_ram_ptr(),0x3000);
 assert.ok(![15,16,19].includes(ram[0xc9c]));assert.notEqual(ram[0xdad],0);
 const before=await m.snapshot();m.connect('native-title',0);
 assert.equal(m.disconnect().native_link.connected,false);
 assert.deepEqual(await m.snapshot(),before);
});
