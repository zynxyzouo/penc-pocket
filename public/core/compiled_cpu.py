# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional compiled instruction stretches, with existing host adapters intact.

Normal mode records host-boundary traces only. Use the reference backend for
per-instruction debugging. Snapshot architectural state and steps are unchanged.
"""
from array import array
from cpu import CPU, STOP
import runtime_bridge as _runtime

METHODS=('read','write','word','setpc','push','pop','step','call','pc','sb')
# The Worker imports this module during pristine, hash-checked bootstrap, before
# any session or debug hook. This is a compatibility guard, not a security
# boundary against code replacing methods before trusted bootstrap.
_CONTRACT={(base,name):getattr(base,name) for cls in (CPU,_runtime.MotionCPU)
           for base in cls.__mro__ if issubclass(base,CPU) for name in METHODS}
_ROM_ENGINE=None
_ROM_CODE=None

class TrackedRAM(dict):
    def __init__(self,values):
        super().__init__(values);self.changed=set()
    def __setitem__(self,key,value):
        super().__setitem__(key,value);self.changed.add(key)
    def update(self,*args,**kwargs):
        for k,v in dict(*args,**kwargs).items():self[k]=v
    def setdefault(self,key,value=None):
        if key not in self:self[key]=value
        return self[key]

def make_run(cls,engine,minimum_work=0):
    """Only install for a known CPU class; custom hooks keep reference execution."""
    original=cls.run
    history={};history_code=None
    trusted=_runtime.MotionCPU if issubclass(cls,_runtime.MotionCPU) else CPU
    def unchanged(cpu):
        return (type(cpu) is cls and not any(k in cpu.__dict__ for k in METHODS)
                and all(getattr(base,name) is fn for (base,name),fn in _CONTRACT.items())
                and all(getattr(cls,name) is _CONTRACT[trusted,name] for name in METHODS))
    def run(self,entry,args=(),budget=100000,register1=None,direct=False):
        nonlocal history_code
        global _ROM_ENGINE,_ROM_CODE
        if history_code is not self.code:history.clear();history_code=self.code
        def reference():
            before=self.steps
            try:return original(self,entry,args,budget,register1,direct)
            finally:
                if len(history)>=512:history.clear()
                history[entry]=self.steps-before
        if minimum_work and history.get(entry,0)<minimum_work:return reference()
        if type(args) not in (tuple,list):return reference()
        if (not unchanged(self) or engine.busy or len(self.code)>0x800000
            or any(type(v) is not int or not 0<=v<=65535 for v in (*self.r,self.fr,*args))
            or any(not 0<=self.r[0]+i<65536 for i in range(1,len(args)+1))
            or (register1 is not None and (type(register1) is not int or not 0<=register1<=65535))
            or type(self.mem) is not dict or any(type(k) is not int or not 0<=k<65536
                or type(v) is not int or not 0<=v<=65535 for k,v in self.mem.items())
            or type(budget) is not int or not 0<=budget<=0xffffffff):
            return reference()
        engine.busy=True
        before=self.steps
        old_mem=self.mem;self.mem=TrackedRAM(old_mem)
        try:
            for i,value in enumerate(args,1):self.mem[self.r[0]+i]=value
            if register1 is not None:self.r[1]=register1
            if direct:self.setpc(entry)
            else:self.call(entry,STOP)
            # Initial host calls may install custom instrumentation. Preserve it.
            if not unchanged(self):
                while self.pc!=STOP:
                    if self.steps>=budget:raise RuntimeError(f'Instruction budget {budget} exhausted at {self.pc:06X}')
                    self.step()
            else:
                if engine is not _ROM_ENGINE or self.code is not _ROM_CODE:
                    engine.load_rom(self.code)
                    _ROM_ENGINE,_ROM_CODE=engine,self.code
                engine.start(len(self.code),int(self.allow_adapters))
                self.mem.changed=set(self.mem)
                while self.pc!=STOP:
                    if self.steps>=budget:raise RuntimeError(f'Instruction budget {budget} exhausted at {self.pc:06X}')
                    if not unchanged(self):self.step();continue
                    packed=array('I',(*self.r,self.fr,self.steps))
                    for a in self.mem.changed:packed.extend((a,self.mem[a]))
                    self.mem.changed.clear()
                    output=engine.exchange(packed,budget)
                    proxy=hasattr(output,'to_py')
                    values=output.to_py() if proxy else output
                    self.r[:]=values[:8];self.fr=values[8];self.steps=values[9]
                    reason,mathmask=values[10],values[11]
                    calls_at=14+values[12]*2
                    for i in range(14,calls_at,2):dict.__setitem__(self.mem,values[i],values[i+1])
                    self.calls.extend(values[calls_at:])
                    if reason==2:raise RuntimeError(f'Instruction budget {budget} exhausted at {self.pc:06X}')
                    if reason==1:self.step()
                    for bit,target in ((1,'0063CF'),(2,'00603C'),(4,'0060B3')):
                        if mathmask&bit and not any(a['target']==target for a in self.adapters):
                            self.adapters.append({'target':target,'kind':'compiled pure arithmetic; detailed trace available in reference mode'})
            if self.r[0]!=0x1f00:raise RuntimeError(f'Unbalanced host stack: {self.r[0]:04X}')
            return self
        finally:
            self.mem=dict(self.mem)
            engine.busy=False
            if len(history)>=512:history.clear()
            history[entry]=self.steps-before
    return run

def install(engine):
    import runtime_bridge
    runtime_bridge.MotionCPU.run=make_run(runtime_bridge.MotionCPU,engine,minimum_work=4096)
