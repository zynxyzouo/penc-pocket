import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {CompiledEngine} from '../public/compiled-engine.js';
const bytes=Buffer.from((await readFile(new URL('../public/core/pocket_cpu.wasm.b64',import.meta.url),'utf8')).trim(),'base64');
const buffer=data=>({getBuffer:()=>({data,release(){}})});
test('Wasm executes a complete arithmetic loop with a bounded budget',async()=>{
  const e=await CompiledEngine.create(bytes);
  e.load_rom(buffer(new Uint8Array([0x41,0x02,0x42,0xee])));e.start(4,0);
  const result=e.exchange(buffer(new Uint32Array([0x1f00,0,0,0,0,0x1e12,0x20,0,0x3e0,0])),5000);
  assert.equal(result[1],2500);assert.equal(result[9],5000);assert.equal(result[10],2);
});
test('Wasm reloads same-size firmware and yields missing RAM without changing state',async()=>{
  const e=await CompiledEngine.create(bytes);
  for(const value of [123,456]) {
    e.load_rom(buffer(new Uint8Array([8,0x93,value&255,value>>8])));e.start(4,0);
    const r=e.exchange(buffer(new Uint32Array([0x1f00,0,0,0,0,0x1e12,0x20,0,0x3e0,0])),1);
    assert.equal(r[1],value);assert.equal(r[9],1);
  }
  e.load_rom(buffer(new Uint8Array([0x10,0x93,0x34,0x12])));e.start(4,0);
  const r=e.exchange(buffer(new Uint32Array([0x1f00,0,0,0,0,0x1e12,0x20,0,0x3e0,0])),1);
  assert.equal(r[10],1);assert.equal(r[9],0);assert.equal(r[7],0);
});
