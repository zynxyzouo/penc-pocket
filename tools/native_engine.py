"""Native build test bridge; the browser uses compiled-engine.js instead."""
import ctypes as ct
from array import array

class NativeEngine:
    def __init__(self,path):
        self.lib=ct.CDLL(str(path));self.busy=False;self.code=None;self.executed=0
        for name in ('state','ram','dirty','calls'):
            f=getattr(self.lib,name+'_ptr');f.restype=ct.POINTER(ct.c_uint32);setattr(self,name,f())
        for name in ('rom','valid'):
            f=getattr(self.lib,name+'_ptr');f.restype=ct.POINTER(ct.c_ubyte);setattr(self,name,f())
    def load_rom(self,code):
        ct.memmove(self.rom,code,len(code))
    def start(self,size,adapters):
        self.lib.reset(size,adapters)
    def exchange(self,packed,budget):
        for i in range(10):self.state[i]=packed[i]
        for i in range(10,len(packed),2):
            a,v=packed[i:i+2]
            if not 0<=a<65536 or not 0<=v<=65535:raise ValueError('Compiled RAM value outside uint16 boundary')
            self.ram[a]=v;self.valid[a]=1
        self.lib.clear_dirty();self.lib.run(budget)
        self.executed+=self.state[9]-packed[9]
        result=array('I',self.state[:11]);result.append(self.state[12])
        result.extend((self.state[11],self.state[13]))
        for i in range(self.state[11]):
            a=self.dirty[i];result.extend((a,self.ram[a]))
        result.extend(self.calls[:self.state[13]])
        return result
