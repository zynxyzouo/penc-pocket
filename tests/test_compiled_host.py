import importlib.util, os, sys, unittest, struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'public/core'),str(ROOT/'tools')]
from cpu import CPU, STOP
NATIVE=Path(os.environ.get('POCKET_NATIVE_CORE',ROOT/'build'/('pocket_cpu.dll' if sys.platform=='win32' else 'pocket_cpu.so')))

@unittest.skipUnless(NATIVE.exists(),'Build optional native differential core with tools/build-core.py --native')
class HostTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('compiled_cpu'),'Compiled host bridge missing')
        from compiled_cpu import make_run
        from native_engine import NativeEngine
        self.engine=NativeEngine(NATIVE)
        self.fast=type('TestCompiledCPU',(CPU,),{})
        self.fast.run=make_run(self.fast,self.engine)
    def compare(self,code,ram,**kwargs):
        pair=[c(code,ram) for c in (CPU,self.fast)];errors=[]
        for cpu in pair:
            try:cpu.run(0x200000,direct=True,**kwargs);errors.append(None)
            except Exception as exc:errors.append((type(exc),str(exc)))
        self.assertEqual(errors[0],errors[1])
        a,b=pair
        self.assertEqual((a.r,a.fr,a.mem,a.steps,a.clock_seconds,bytes(a.virtual_flash)),
                         (b.r,b.fr,b.mem,b.steps,b.clock_seconds,bytes(b.virtual_flash)))
        return pair
    def test_loop_budget_and_missing_ram_match_reference(self):
        self.compare(struct.pack('<HH',0x0241,0xee42),{},budget=20003)
        self.compare(struct.pack('<HH',0x9310,0x1234),{},budget=100)
    def test_native_call_history_survives_compiled_segments(self):
        code=struct.pack('<5H',0xf060,3,0x9a90,0xf165,0x9a90)
        a,b=CPU(code,{}),self.fast(code,{})
        for c in (a,b):c.run(0x200000)
        self.assertEqual(b.calls,a.calls)
        self.assertEqual(b.calls,[0x200000,0x200003])
    def test_pure_arithmetic_and_host_spi_keep_current_ram(self):
        # Multiply stack operands then read two BIN words into RAM, then return.
        words=[0xf040,0x63cf,0xf040,0x49db,0x9a90]
        # dest=0x100,count=2,offset=0,bank=0; native return at stack+1/2
        ram={0x1f01:0x100,0x1f02:2,0x1f03:0,0x1f04:0,0x1f05:0x20}
        self.compare(struct.pack('<5H',*words),ram,budget=5)
    def test_custom_instance_hook_uses_reference(self):
        code=struct.pack('<H',0xee00)
        cpu=self.fast(code,{})
        old=cpu.setpc
        cpu.setpc=lambda value:old(STOP if value==0x200001 else value)
        cpu.run(0x200000,direct=True,budget=10)
        self.assertEqual(cpu.steps,1)
    def test_preinstalled_class_read_hook_is_not_trusted(self):
        from compiled_cpu import make_run
        class Hooked(CPU):
            def read(self,address):return 123
        Hooked.run=make_run(Hooked,self.engine)
        c=Hooked(struct.pack('<HH',0x9310,0x100),{0x100:99})
        try:c.run(0x200000,direct=True,budget=1)
        except RuntimeError:pass
        self.assertEqual(c.r[1],123)
    def test_two_wrappers_sharing_engine_reload_their_own_rom(self):
        from compiled_cpu import make_run
        second=type('SecondCPU',(CPU,),{})
        second.run=make_run(second,self.engine)
        code_a=struct.pack('<HH',0x9308,123);code_b=struct.pack('<HH',0x9308,456)
        actual=[]
        for cls,code in ((self.fast,code_a),(second,code_b),(self.fast,code_a)):
            c=cls(code,{})
            try:c.run(0x200000,direct=True,budget=1)
            except RuntimeError:pass
            actual.append(c.r[1])
        self.assertEqual(actual,[123,456,123])
    def test_non_uint16_host_arguments_keep_reference_semantics(self):
        self.compare(struct.pack('<HH',0x9308,1),{},args=(-1,),budget=1)
    def test_generator_arguments_are_not_consumed_twice(self):
        c=self.fast(struct.pack('<HH',0x9308,1),{})
        with self.assertRaisesRegex(RuntimeError,'Instruction budget'):
            c.run(0x200000,args=(v for v in [3]),direct=True,budget=1)
        self.assertEqual(c.mem[0x1f01],3)
    def test_custom_pc_descriptor_after_install_keeps_reference_exit(self):
        old=CPU.pc
        try:
            CPU.pc=property(lambda cpu:STOP if cpu.r[1]==1 else old.__get__(cpu))
            c=self.fast(struct.pack('<HH',0x0241,0xee42),{})
            c.run(0x200000,direct=True,budget=10)
            self.assertEqual(c.steps,1)
        finally:CPU.pc=old
    def test_real_r23_clock_and_cry_equal(self):
        rom=os.environ.get('PENC_R23_BIN')
        if not rom:self.skipTest('Set PENC_R23_BIN to a local private firmware')
        import runtime_bridge as rt, web_adapter as n, bench, audio_completion, native_connector
        from compiled_cpu import make_run
        original=rt.MotionCPU.run
        outputs=[]
        try:
            for compiled in (False,True):
                rt.MotionCPU.run=make_run(rt.MotionCPU,self.engine) if compiled else original
                b=bench.Bench(rom,ROOT/'public/profiles/r23.json');b.ram[0xcc7]=0;n.bench=b
                n.sprite_cache={};n.last_scene=None;audio_completion.clock.clear();native_connector.cable.clear();rt.clear_motion()
                rows=[]
                for keys in ([[]]*2+[['B']]+[[]]*23+[['B']]+[[]]*23):
                    r=rt.advance(keys,audio_elapsed_ms=15.625,audio_speed=2)
                    rows.append((dict(b.ram),bytes(b.virtual_flash),bytes(b.virtual_album),b.total_steps,r['rgba'],r['sound_events']))
                outputs.append(rows)
            self.assertEqual(outputs[0],outputs[1])
        finally:rt.MotionCPU.run=original

if __name__=='__main__':unittest.main()
