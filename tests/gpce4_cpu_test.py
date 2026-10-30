"""CPU behavior tests against the supplied unmodified Python reference.

Run: python tests/gpce4_cpu_test.py
Optional GPCE4_REFERENCE and ZIG environment variables override local tools.
The native test bus is deterministic and contains no proprietary ROM bytes.
"""
import ctypes as ct
import importlib.util
import os
from pathlib import Path
import random
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = Path(os.environ.get('GPCE4_REFERENCE', ROOT / 'reference' / 'gpce4' / 'unsp.py'))
ZIG = Path(os.environ.get('POCKET_ZIG') or os.environ.get('ZIG') or shutil.which('zig') or
           ROOT.parents[1] / 'wasm-core-20261030' / 'toolchain' / 'zig-x86_64-windows-0.15.2' / 'zig.exe')
spec = importlib.util.spec_from_file_location('gpce4_cpu_reference', REFERENCE)
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)


class State(ct.Structure):
    _fields_ = [('r', ct.c_uint32 * 8), ('fr', ct.c_uint32),
                ('secbank', ct.c_uint32 * 4), ('sirq', ct.c_uint32),
                ('irq_active', ct.c_uint32), ('fiq_active', ct.c_uint32),
                ('sleeping', ct.c_uint32), ('steps', ct.c_uint64),
                ('fault', ct.c_uint32), ('fault_pc', ct.c_uint32),
                ('fault_op', ct.c_uint32), ('fault_address', ct.c_uint32)]


class Bus:
    def __init__(self, seed):
        self.seed, self.data, self.trace = seed, {}, []

    def read(self, address):
        value = self.data.get(address, ((address * 109 + self.seed) ^ (address >> 8)) & 65535)
        self.trace.append((0, address, value))
        return value

    def write(self, address, value):
        self.data[address] = value & 65535
        self.trace.append((1, address, value & 65535))


class CpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = ROOT / 'src' / 'gpce4_cpu.c'
        if not source.exists():
            return
        build = ROOT / 'build' / 'gpce4_cpu'
        build.mkdir(parents=True, exist_ok=True)
        temp = build / 'tmp'
        temp.mkdir(exist_ok=True)
        library = build / ('gpce4_cpu.dll' if os.name == 'nt' else 'gpce4_cpu.so')
        command = [str(ZIG), 'cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                   str(source), str(ROOT / 'tests' / 'gpce4_cpu_bus.c'), '-o', str(library)]
        if os.name != 'nt':
            command.insert(2, '-fPIC')
        env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(ROOT / 'build' / 'zig-cache'),
                   ZIG_LOCAL_CACHE_DIR=str(ROOT / 'build' / 'zig-local-cache'),
                   TMP=str(temp), TEMP=str(temp))
        subprocess.run(command, check=True, env=env)
        cls.lib = ct.CDLL(str(library))
        cls.lib.gpce4_cpu_test_state.restype = ct.POINTER(State)
        cls.lib.gpce4_cpu_test_trace.restype = ct.POINTER(ct.c_uint32)
        cls.lib.gpce4_cpu_test_pc.restype = ct.c_uint32
        cls.state = cls.lib.gpce4_cpu_test_state().contents

    def setUp(self):
        self.assertTrue(hasattr(self, 'lib'), 'CPU implementation is missing: reset and instruction execution cannot run')

    def setup_pair(self, opcode=0xF165, seed=7, registers=None, fr=0x0808, pc=0x20000):
        bus = Bus(seed)
        py = ref.Unsp(bus)
        py.r = list(registers or [0xF000, 1, 2, 3, 4, 5, 0, 0])
        py.setpc(pc)
        py.fr = fr
        py.secbank = [0x1111, 0x2222, 0x3333, 0x4444]
        bus.trace.clear()
        bus.data[pc] = opcode
        self.lib.gpce4_cpu_test_begin(seed)
        ct.memset(ct.addressof(self.state), 0, ct.sizeof(State))
        for i, value in enumerate(py.r):
            self.state.r[i] = value
        for i, value in enumerate(py.secbank):
            self.state.secbank[i] = value
        self.state.fr = py.fr
        self.lib.gpce4_cpu_test_poke(pc, opcode)
        return py, bus

    def poke(self, bus, address, value):
        bus.data[address] = value
        self.lib.gpce4_cpu_test_poke(address, value)

    def trace(self):
        p = self.lib.gpce4_cpu_test_trace()
        return [tuple(p[3*i+j] for j in range(3)) for i in range(self.lib.gpce4_cpu_test_trace_count())]

    def compare(self, py, bus, label=''):
        actual = (list(self.state.r), self.state.fr, list(self.state.secbank), self.state.sirq,
                  bool(self.state.irq_active), bool(self.state.fiq_active), bool(self.state.sleeping), self.state.steps)
        expected = (py.r, py.fr, py.secbank, py.sirq, py.irq_active, py.fiq_active, py.sleeping, py.steps)
        self.assertEqual(actual, expected, label)
        self.assertEqual(self.trace(), bus.trace, label + ' bus access sequence')
        self.assertEqual(self.lib.gpce4_cpu_test_pc(), py.pc, label + ' PC')

    def paired_step(self, py, bus, label=''):
        expected = py.step()
        self.assertEqual(self.lib.gpce4_cpu_test_step(), int(expected), label)
        self.assertEqual(self.state.fault, 0, label)
        self.compare(py, bus, label)

    def test_reset_fetches_vector_and_clears_prior_machine_state(self):
        ct.memset(ct.addressof(self.state), 0xAA, ct.sizeof(State))
        self.lib.gpce4_cpu_test_begin(0)
        self.lib.gpce4_cpu_test_poke(0x4017, 0x8123)
        self.lib.gpce4_cpu_test_reset()
        self.assertEqual(list(self.state.r), [0, 0, 0, 0, 0, 0, 0, 0x8123])
        self.assertEqual(self.state.fr, 0x0808)
        self.assertEqual((self.state.steps, self.state.sirq, self.state.fault), (0, 0, 0))
        self.assertEqual(list(self.state.secbank), [0]*4)
        self.assertEqual(self.trace(), [(0, 0x4017, 0x8123)])

    def test_all_instruction_encodings_match_reference(self):
        # Removing/misdecoding any implemented instruction, flag or addressing side effect fails.
        rng = random.Random(0x4C0DE)
        supported = unsupported = invalid_stack = 0
        for op in range(65536):
            dst, mode, src = (op >> 9) & 7, (op >> 3) & 7, op & 7
            group, top = (op >> 6) & 7, op >> 12
            regs = [rng.randrange(65536) for _ in range(8)]
            py, bus = self.setup_pair(op, seed=op*17, registers=regs, fr=rng.randrange(32768), pc=0x20FFFE)
            self.poke(bus, 0x20FFFF, rng.randrange(65536))
            invalid = group == 2 and ((top == 13 and mode > dst + 1) or (top == 9 and op != ref.RETI and dst + mode > 7))
            if invalid:
                # Reference accidentally wraps negative PUSH indices and raises IndexError for POP.
                # The C public boundary explicitly rejects both malformed encodings before writes.
                self.assertEqual(self.lib.gpce4_cpu_test_step(), -1, hex(op))
                self.assertEqual((self.state.fault, self.state.fault_pc, self.state.fault_op), (1, 0x20FFFE, op))
                self.assertEqual(self.trace(), [(0, 0x20FFFE, op)])
                invalid_stack += 1
                continue
            try:
                py.step()
            except RuntimeError:
                self.assertEqual(self.lib.gpce4_cpu_test_step(), -1, hex(op))
                self.assertEqual((self.state.fault, self.state.fault_pc, self.state.fault_op), (1, 0x20FFFE, op))
                self.compare(py, bus, hex(op))
                unsupported += 1
            else:
                self.assertEqual(self.lib.gpce4_cpu_test_step(), 1, hex(op))
                self.assertEqual(self.state.fault, 0, hex(op))
                self.compare(py, bus, hex(op))
                supported += 1
        print(f'CPU full opcode differential: supported={supported}, unsupported={unsupported}, invalid_stack={invalid_stack}')

    def test_register_shifts_at_zero_sign_and_width_boundaries(self):
        for kind in range(6):
            for n in [0, 1, 15, 16, 17, 31, 32, 65535]:
                for value in [0, 1, 0x7FFF, 0x8000, 0xFFFF]:
                    op = 0xE108 | (1 << 9) | (kind << 4) | 2
                    py, bus = self.setup_pair(op, registers=[0xF000, value, n, 0xA5A5, 0x5A5A, 0, 0x03C0, 0])
                    self.paired_step(py, bus, f'{op:04X} n={n} value={value:04X}')

    def test_irq_pushes_return_pc_sr_and_reti_defers_reentry(self):
        py, bus = self.setup_pair(fr=0x0828)
        self.poke(bus, 0x4018, 0x8200)
        self.poke(bus, 0x8200, ref.RETI)
        py.set_line(1, True)
        self.lib.gpce4_cpu_test_irq(1, 1)
        self.paired_step(py, bus)
        self.assertEqual((py.pc, py.r[0], py.irq_active), (0x8200, 0xEFFE, True))
        self.assertEqual(bus.data[0xF000], 1)
        self.assertEqual(bus.data[0xEFFF], 2)
        self.paired_step(py, bus)
        self.assertEqual((py.pc, py.r[0], py.irq_active), (0x20001, 0xF000, False))

    def test_nested_irq_priority_and_full_fr_restore(self):
        py, bus = self.setup_pair(fr=0xA838)
        self.poke(bus, 0x401B, 0x8300)  # IRQ3
        self.poke(bus, 0x4019, 0x8400)  # IRQ1
        self.poke(bus, 0x8300, 0xF165)
        self.poke(bus, 0x8301, ref.RETI)
        self.poke(bus, 0x8400, ref.RETI)
        py.set_line(4, True)
        self.lib.gpce4_cpu_test_irq(4, 1)
        self.paired_step(py, bus)
        self.assertEqual((py.pc, py.fr & 15), (0x8300, 3))
        py.set_line(2, True)
        self.lib.gpce4_cpu_test_irq(2, 1)
        self.paired_step(py, bus)
        self.assertEqual((py.pc, py.fr & 15), (0x8400, 1))
        py.set_line(2, False)
        self.lib.gpce4_cpu_test_irq(2, 0)
        self.paired_step(py, bus)
        self.assertEqual((py.pc, py.fr & 15), (0x8301, 3))
        self.paired_step(py, bus)
        self.assertEqual((py.pc, py.fr), (0x20001, 0xA838))

    def test_disabled_lower_line_blocks_irq_and_sleep_wakes_for_fiq(self):
        py, bus = self.setup_pair(fr=0x0828)
        py.sirq = self.state.sirq = 3
        self.paired_step(py, bus)
        self.assertFalse(py.irq_active)
        py.sleeping = self.state.sleeping = True
        self.paired_step(py, bus)
        py.fr = self.state.fr = 0x0868
        self.poke(bus, 0x4016, 0x8500)
        self.poke(bus, 0x8500, 0xF165)
        self.poke(bus, 0x8501, ref.RETI)
        self.paired_step(py, bus)
        # The still-asserted active FIQ remains the lowest line and blocks IRQ entry.
        self.assertTrue(py.fiq_active)
        self.assertFalse(py.irq_active)
        self.assertFalse(py.sleeping)
        py.set_line(0, False)
        self.lib.gpce4_cpu_test_irq(0, 0)
        self.paired_step(py, bus)
        self.assertEqual((py.pc, py.fiq_active, py.irq_active), (0x20001, False, False))
        self.poke(bus, py.pc, 0xF165)
        self.paired_step(py, bus)
        self.assertTrue(py.irq_active)

    def test_reference_fiq_reti_ine_stack_mismatch_is_preserved_explicitly(self):
        # Characterization of a reference defect, not a claim of hardware accuracy:
        # FIQ pushes two words, but RETI with INE set pops three, consuming the sentinel.
        py, bus = self.setup_pair(fr=0x0858)
        self.poke(bus, 0x4016, 0x8600)
        self.poke(bus, 0x8600, ref.RETI)
        self.poke(bus, 0xF001, 0x1357)
        py.set_line(0, True)
        self.lib.gpce4_cpu_test_irq(0, 1)
        self.paired_step(py, bus)
        self.paired_step(py, bus)
        self.assertEqual((py.pc, py.r[0], py.fr), (0x11357, 0xF001, 2))
        self.assertFalse(py.fiq_active)

    def test_fr_write_swaps_register_bank_once_and_masks_bit15(self):
        py, bus = self.setup_pair(0xF03D)
        py.r[5] = self.state.r[5] = 0xA8A8
        self.paired_step(py, bus)
        self.assertEqual(py.r[1:5], [0x1111, 0x2222, 0x3333, 0x4444])
        self.assertEqual(py.secbank, [1, 2, 3, 4])
        self.assertEqual(py.fr, 0x28A8)
        self.poke(bus, py.pc, 0xF03D)
        self.paired_step(py, bus)
        self.assertEqual(py.r[1:5], [0x1111, 0x2222, 0x3333, 0x4444])
        self.poke(bus, py.pc, 0xF14A)
        self.paired_step(py, bus)
        self.assertEqual(py.r[1:5], [1, 2, 3, 4])

    def test_pc_and_data_segment_wrap_and_64bit_steps(self):
        py, bus = self.setup_pair(0x9241, pc=0x3FFFFF)
        py.steps = self.state.steps = (1 << 32) - 1
        self.paired_step(py, bus)
        self.assertEqual((py.pc, py.steps), (0, 1 << 32))
        for mode, src_value, want_ds, want_src in [(6, 0xFFFF, 0, 0), (5, 0, 62, 0xFFFF), (7, 0xFFFF, 0, 0)]:
            py, bus = self.setup_pair(0x9200 | (3 << 6) | (mode << 3) | 2, registers=[0xF000, 0, src_value, 0, 0, 0, 0xFC00, 0])
            self.paired_step(py, bus)
            self.assertEqual((py.ds, py.r[2]), (want_ds, want_src))

    def test_bus_fault_stops_before_later_stack_writes_and_latches(self):
        py, bus = self.setup_pair(0xF041)
        self.poke(bus, 0x20001, 0x1234)
        self.lib.gpce4_cpu_test_fail(0xEFFF)
        self.assertEqual(self.lib.gpce4_cpu_test_step(), -1)
        self.assertEqual((self.state.fault, self.state.fault_address), (2, 0xEFFF))
        self.assertEqual((self.state.fault_pc, self.state.fault_op), (0x20000, 0xF041))
        self.assertEqual((self.lib.gpce4_cpu_test_pc(), self.state.r[0]), (0x20002, 0xEFFF))
        trace, steps = self.trace(), self.state.steps
        self.assertEqual(self.lib.gpce4_cpu_test_step(), -1)
        self.assertEqual((self.trace(), self.state.steps), (trace, steps))

    def test_out_of_range_irq_line_is_ignored_without_undefined_shift(self):
        self.setup_pair()
        for line in [32, 63, 0xFFFFFFFF]:
            self.lib.gpce4_cpu_test_irq(line, 1)
        self.assertEqual(self.state.sirq, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
