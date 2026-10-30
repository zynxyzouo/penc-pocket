"""Compare architectural results, not debug trace implementation details."""
import ctypes as ct
from pathlib import Path
import os, random, struct, sys, unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'public/core'))
from cpu import CPU, STOP
NATIVE=Path(os.environ.get('POCKET_NATIVE_CORE',ROOT/'build'/('pocket_cpu.dll' if sys.platform=='win32' else 'pocket_cpu.so')))

class Engine:
    def __init__(self):
        self.lib=ct.CDLL(str(NATIVE))
        for name in ('state','ram','dirty'):
            f=getattr(self.lib,name+'_ptr'); f.restype=ct.POINTER(ct.c_uint32)
            setattr(self,name,f())
        for name in ('rom','valid'):
            f=getattr(self.lib,name+'_ptr'); f.restype=ct.POINTER(ct.c_ubyte)
            setattr(self,name,f())
    def load(self,cpu):
        self.lib.reset(len(cpu.code),int(cpu.allow_adapters))
        ct.memmove(self.rom,cpu.code,len(cpu.code))
        for k,v in cpu.mem.items():
            if 0<=k<65536:self.ram[k]=v;self.valid[k]=1
        for i,v in enumerate(cpu.r):self.state[i]=v
        self.state[8]=cpu.fr;self.state[9]=cpu.steps
    def state_out(self):
        return list(self.state[:8]),self.state[8],{a:self.ram[a] for a in range(65536) if self.valid[a]},self.state[9]

def arch(cpu):return cpu.r,cpu.fr,cpu.mem,cpu.steps

@unittest.skipUnless(NATIVE.exists(),'Build optional native differential core with tools/build-core.py --native')
class CompiledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine=Engine()
    def setUp(self):
        self.assertTrue(NATIVE.exists(),'Compiled engine must be built')

    def test_arithmetic_loop_runs_without_host_dispatch(self):
        cpu=CPU(struct.pack('<HH',0x0241,0xee42),{},adapters=False)
        try:cpu.run(0x200000,direct=True,budget=5000)
        except RuntimeError:pass
        initial=CPU(cpu.code,{},adapters=False)
        self.engine.load(initial)
        self.assertEqual(self.engine.lib.run(5000),2)
        self.assertEqual(self.engine.state_out(),arch(cpu))
        self.assertEqual(cpu.r[1],2500)

    def test_all_opcode_words_commit_or_yield_before_any_effect(self):
        rng=random.Random(91234);supported=0
        ram=dict.fromkeys(range(256),0);ram.update(dict.fromkeys(range(0x1ee0,0x1f20),0))
        for op in range(65536):
            cpu=CPU(struct.pack('<HH',op,rng.randrange(65536)),ram,adapters=False)
            cpu.r[:]=[0x1f00,rng.randrange(256),rng.randrange(65536),rng.randrange(65536),rng.randrange(65536),0x20,0x20|rng.randrange(64)<<6,0]
            self.engine.load(cpu)
            result=self.engine.lib.run(1)
            # Check registers+known RAM only here; full missing-address checks below.
            before=cpu.r[:],cpu.fr,cpu.steps
            actual=list(self.engine.state[:8]),self.engine.state[8],self.engine.state[9]
            if result==1:
                self.assertEqual(actual,before,f'{op:04x} yield mutated state')
                self.assertEqual(self.engine.state[11],0)
                continue
            supported+=1
            try:cpu.step()
            except Exception as exc:self.fail(f'{op:04x} fast path should yield: {exc}')
            self.assertEqual(actual,(cpu.r,cpu.fr,cpu.steps),f'{op:04x}')
            for a in ram:self.assertEqual(self.engine.ram[a],cpu.mem[a],f'{op:04x} RAM {a:x}')
            for i in range(self.engine.state[11]):
                a=self.engine.dirty[i];self.assertEqual(self.engine.ram[a],cpu.mem[a])
        self.assertGreater(supported,25000)

    def test_host_and_invalid_memory_instructions_yield_atomically(self):
        for words,ram in [([0xf040,0x5fbe],{}),([0x9310,0x1234],{}),([0xd310,0x3053],{}),([0xf020,0],{}),([0xffff],{})]:
            cpu=CPU(struct.pack('<'+'H'*len(words),*words),ram)
            self.engine.load(cpu);before=self.engine.state_out()
            self.assertEqual(self.engine.lib.run(100),1)
            self.assertEqual(self.engine.state_out(),before)

    def test_budget_does_not_execute_extra_instruction(self):
        cpu=CPU(struct.pack('<H',0xf165),{})
        self.engine.load(cpu)
        self.assertEqual(self.engine.lib.run(0),2)
        self.assertEqual(self.engine.state_out(),arch(cpu))

if __name__=='__main__':unittest.main()
