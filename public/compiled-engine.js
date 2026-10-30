// SPDX-License-Identifier: GPL-3.0-or-later
// Own freestanding instruction engine; no external emulator library linked.
export class CompiledEngine {
  static async create(bytes) {
    const {instance}=await WebAssembly.instantiate(bytes,{});
    return new CompiledEngine(instance.exports);
  }
  constructor(exports) {
    this.api=exports;this.busy=false;this.code=null;
    const memory=exports.memory.buffer;
    this.state=new Uint32Array(memory,exports.state_ptr(),14);
    this.ram=new Uint32Array(memory,exports.ram_ptr(),65536);
    this.valid=new Uint8Array(memory,exports.valid_ptr(),65536);
    this.dirty=new Uint32Array(memory,exports.dirty_ptr(),65536);
    this.calls=new Uint32Array(memory,exports.calls_ptr(),65536);
    this.rom=new Uint8Array(memory,exports.rom_ptr(),0x800000);
  }
  load_rom(code) {
    // Called only when a retained Python bytes identity changes; memory addresses
    // alone are insufficient because Python can recycle an old allocation.
    const view=code.getBuffer('u8');
    try {
      if(view.data.length>this.rom.length)throw Error('Firmware exceeds compiled ROM bounds');
      this.rom.set(view.data);
    } finally { view.release(); }
  }
  start(size,adapters) { this.api.reset(size,adapters); }
  exchange(packed,budget) {
    const view=packed.getBuffer('u32');
    try {
      const input=view.data;
      this.state.set(input.subarray(0,10));
      for(let i=10;i<input.length;i+=2) {
        const a=input[i],v=input[i+1];
        if(a>=65536 || v>65535)throw Error('Compiled RAM value outside uint16 boundary');
        this.ram[a]=v;this.valid[a]=1;
      }
    } finally { view.release(); }
    this.api.clear_dirty();this.api.run(budget);
    const result=new Uint32Array(14+this.state[11]*2+this.state[13]);
    result.set(this.state.subarray(0,11));result[11]=this.state[12];
    result[12]=this.state[11];result[13]=this.state[13];
    for(let i=0;i<this.state[11];i++) {
      const a=this.dirty[i];result[14+i*2]=a;result[15+i*2]=this.ram[a];
    }
    result.set(this.calls.subarray(0,this.state[13]),14+this.state[11]*2);
    return result;
  }
}
