"""Differential CPU checks use synthetic instructions, never firmware extracts."""
import importlib.util
import os
from pathlib import Path
import random
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'public/core'))
from cpu import CPU, STOP


def state(cpu):
    return (cpu.r, cpu.fr, cpu.mem, cpu.steps, list(cpu.trace), cpu.calls,
            cpu.adapters, cpu.writes, bytes(cpu.virtual_flash),
            bytes(cpu.virtual_album), cpu.clock_seconds)


def outcome(cpu, method, *args, **kwargs):
    try:
        getattr(cpu, method)(*args, **kwargs)
    except Exception as exc:
        return type(exc), str(exc)
    return None


class AcceleratorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('cpu_accelerator'),
                             'The additive decoded CPU accelerator is missing')
        from cpu_accelerator import AcceleratedCPU
        self.fast = AcceleratedCPU

    def test_all_instruction_words_preserve_state_and_failure(self):
        rng = random.Random(28409)
        ram = dict.fromkeys(range(0x100), 0)
        ram.update(dict.fromkeys(range(0x1ee0, 0x1f21), 0))
        for op in range(65536):
            code = struct.pack('<HH', op, rng.randrange(65536))
            registers = [0x1f00, rng.randrange(256), rng.randrange(65536),
                         rng.randrange(65536), rng.randrange(65536),
                         0x20, 0x20 | rng.randrange(64) << 6, 0]
            pair = [cls(code, ram, adapters=False) for cls in (CPU, self.fast)]
            for cpu in pair:
                cpu.r[:] = registers
            errors = [outcome(cpu, 'step') for cpu in pair]
            if errors[0] != errors[1] or state(pair[0]) != state(pair[1]):
                self.fail(f'Opcode {op:04X}: errors {errors}; state mismatch')
            pair = [cls(code, ram, adapters=False) for cls in (CPU, self.fast)]
            for cpu in pair:
                cpu.r[:] = registers
            errors = [outcome(cpu, 'run', 0x200000, direct=True, budget=1) for cpu in pair]
            if errors[0] != errors[1] or state(pair[0]) != state(pair[1]):
                self.fail(f'Block opcode {op:04X}: errors {errors}; state mismatch')

    def test_budget_and_trace_survive_loop_and_cache_reuse(self):
        # ADD R1,1; unconditional backwards branch two words.
        code = struct.pack('<HH', 0x0241, 0xee42)
        for budget in (0, 1, 2, 7, 20003):
            pair = [cls(code, {}, adapters=False) for cls in (CPU, self.fast)]
            errors = [outcome(cpu, 'run', 0x200000, direct=True, budget=budget)
                      for cpu in pair]
            self.assertEqual(errors[0], errors[1])
            self.assertEqual(state(pair[0]), state(pair[1]))
            self.assertEqual(pair[1].steps, budget)
        self.assertEqual(len(pair[1].trace), 20000)

    def test_straight_line_run_reduces_python_dispatch_calls(self):
        # Deterministic interpreter-work regression: no wall-clock threshold.
        code = struct.pack('<33H', *([0x0241] * 32 + [0xee61]))
        counts = []
        pair = [cls(code, {}, adapters=False) for cls in (CPU, self.fast)]
        for cpu in pair:
            count = 0
            def profile(frame, event, arg):
                nonlocal count
                if event == 'call':
                    count += 1
            sys.setprofile(profile)
            try:
                outcome(cpu, 'run', 0x200000, direct=True, budget=3300)
            finally:
                sys.setprofile(None)
            counts.append(count)
        self.assertEqual(state(pair[0]), state(pair[1]))
        self.assertLess(counts[1], counts[0] * .55, counts)

    def test_bank_and_flag_loop_reduces_dispatch_work(self):
        code = struct.pack('<5H', 0xfe00, 0xf034, 0xf03c, 0xf02a, 0xee45)
        pair = [cls(code, {}, adapters=False) for cls in (CPU, self.fast)]
        counts = []
        for cpu in pair:
            count = 0
            def profile(frame, event, arg):
                nonlocal count
                if event == 'call':
                    count += 1
            sys.setprofile(profile)
            try:
                outcome(cpu, 'run', 0x200000, direct=True, budget=5000)
            finally:
                sys.setprofile(None)
            counts.append(count)
        self.assertEqual(state(pair[0]), state(pair[1]))
        self.assertEqual(pair[1].steps, 5000)
        self.assertLess(counts[1], counts[0] * .4, counts)

    def test_stack_control_loop_reduces_dispatch_work(self):
        # PUSH R1; POP R1; CALL subroutine; branch back; subroutine RET.
        code = struct.pack('<7H', 0xd288, 0x9088, 0xf060, 6, 0xee45, 0xf165, 0x9a90)
        pair = [cls(code, {}, adapters=False) for cls in (CPU, self.fast)]
        counts = []
        for cpu in pair:
            count = 0
            def profile(frame, event, arg):
                nonlocal count
                if event == 'call':
                    count += 1
            sys.setprofile(profile)
            try:
                outcome(cpu, 'run', 0x200000, direct=True, budget=5000)
            finally:
                sys.setprofile(None)
            counts.append(count)
        self.assertEqual(state(pair[0]), state(pair[1]))
        self.assertEqual(pair[1].steps, 5000)
        self.assertLess(counts[1], counts[0] * .65, counts)

    def test_clock_and_flash_adapters_keep_order_and_failure(self):
        # CALL internal ROM; pop SR/PC back to the host sentinel.
        for target, ram, kwargs in (
            (0x5fbe, {0xcc2:59, 0xcc3:59, 0xcc4:23}, {'clock_seconds':1}),
            (0x5fbe, {0xcc2:59, 0xcc3:59, 0xcc4:23}, {}),
            (0x4a75, {0x1f01:0x100, 0x1f02:1, 0x1f03:0xd000,
                      0x1f04:0x7f, 0x100:0x1234}, {}),
            (0x4a75, {0x1f01:0x100, 0x1f02:1, 0x1f03:0xf000,
                      0x1f04:5, 0x100:0x1234}, {'local_play':True}),
        ):
            code = struct.pack('<HHH', 0xf040, target, 0x9a90)
            pair = [cls(code, ram, **kwargs) for cls in (CPU, self.fast)]
            errors = [outcome(cpu, 'run', 0x200000, direct=True, budget=1) for cpu in pair]
            self.assertEqual(errors[0], errors[1])
            self.assertEqual(state(pair[0]), state(pair[1]))
            if target == 0x4a75:
                flash = pair[1].virtual_album if kwargs.get('local_play') else pair[1].virtual_flash
                self.assertEqual(flash[:2], b'\x34\x12')
            elif kwargs.get('clock_seconds') == 1:
                self.assertEqual([pair[1].mem[a] for a in (0xcc2, 0xcc3, 0xcc4)], [0, 0, 0])

    def test_blocks_preserve_bank_boundary_and_sr_alias(self):
        code = bytearray(0x20004)
        struct.pack_into('<4H', code, 0x1fffc, 0x9309, 0x4321, 0x0241, 0x9d01)
        for budget in range(1, 5):
            pair = [cls(code, {}, adapters=False) for cls in (CPU, self.fast)]
            errors = [outcome(cpu, 'run', 0x20fffe, direct=True, budget=budget) for cpu in pair]
            self.assertEqual(errors[0], errors[1])
            self.assertEqual(state(pair[0]), state(pair[1]))

    def test_stack_aliases_partial_failures_and_custom_stack_hooks(self):
        # Every stack register, including SR/PC aliases, with reads failing
        # partway through a multi-register POP and writes redirecting the PC.
        for op in (0xd2b0, 0xd2b6, 0xd2b7, 0x90b0, 0x90b6, 0x90b7,
                   0xf036, 0xf037, 0xfe36, 0xfe37):
            code = struct.pack('<4H', op, 0x0241, 0x0241, 0x0241)
            for ram in ({}, {0x1f01: 3, 0x1f02: 4}):
                pair = [cls(code, ram, adapters=False) for cls in (CPU, self.fast)]
                errors = [outcome(cpu, 'run', 0x200000, direct=True, budget=4) for cpu in pair]
                self.assertEqual(errors[0], errors[1], hex(op))
                self.assertEqual(state(pair[0]), state(pair[1]), hex(op))
        def push(cpu, reg, value):
            cpu.adapters.append(('push', reg, value))
            CPU.push(cpu, reg, value)
        def pop(cpu, reg):
            cpu.adapters.append(('pop', reg))
            return CPU.pop(cpu, reg)
        code = struct.pack('<3H', 0xd288, 0x9088, 0xee43)
        pair = [type('StackHooks', (cls,), {'push': push, 'pop': pop})(code, {})
                for cls in (CPU, self.fast)]
        errors = [outcome(cpu, 'run', 0x200000, direct=True, budget=17) for cpu in pair]
        self.assertEqual(errors[0], errors[1])
        self.assertEqual(state(pair[0]), state(pair[1]))
        self.assertTrue(pair[1].adapters)

    def test_word_boundaries_and_truncated_immediate(self):
        for code in (b'', b'\x00', b'\x08\x93', b'\x08\x93\xff'):
            for address in (0x1fffff, 0x200000, 0x200001, 0x600000):
                pair = [cls(code, {}) for cls in (CPU, self.fast)]
                self.assertEqual(outcome(pair[0], 'word', address),
                                 outcome(pair[1], 'word', address))
            pair = [cls(code, {}) for cls in (CPU, self.fast)]
            self.assertEqual(outcome(pair[0], 'step'), outcome(pair[1], 'step'))
            self.assertEqual(state(pair[0]), state(pair[1]))

    def test_two_word_instruction_wraps_the_22_bit_pc_before_next_fetch(self):
        # The immediate occupies STOP, but the next PC wraps to unmapped zero.
        # Bytes after the CPU window must never become executable block text.
        code = bytearray(0x400010)
        struct.pack_into('<4H', code, 0x3ffffc, 0x9309, 0x4321, 0x0241, 0x0241)
        code = bytes(code)
        for repeat in range(2):
            pair = [cls(code, {}, adapters=False) for cls in (CPU, self.fast)]
            errors = [outcome(cpu, 'run', 0x3ffffe, direct=True, budget=100)
                      for cpu in pair]
            self.assertEqual(errors[0], (RuntimeError, 'Unmapped instruction/internal ROM 000000'))
            self.assertEqual(errors[0], errors[1], repeat)
            self.assertEqual(state(pair[0]), state(pair[1]), repeat)
            self.assertEqual((pair[1].pc, pair[1].steps, pair[1].r[1]), (0, 1, 0x4321))

    def test_cached_blocks_preserve_random_programs_and_partial_failures(self):
        rng = random.Random(42116)
        # Include aliases of SR/PC, pre/post increments, RAM/Flash reads,
        # stores, shifts, invalid opcodes and both one/two-word encodings.
        for case in range(512):
            words = [rng.randrange(65536) for _ in range(48)]
            # At least eight contiguous ordinary ALU instructions before the
            # mixed tail; otherwise random instructions fail too early.
            for i in range(8):
                words[i] = rng.choice((0x0241, 0x9541, 0x674f, 0x8757,
                                       0x9953, 0xab48, 0xcd42, 0xf165))
            code = struct.pack('<48H', *words)
            ram = dict.fromkeys(range(0x2000), 0)
            budget = rng.randrange(1, 65)
            for repeat in range(2):
                pair = [cls(code, ram, adapters=False) for cls in (CPU, self.fast)]
                errors = [outcome(cpu, 'run', 0x200000, direct=True, budget=budget)
                          for cpu in pair]
                self.assertEqual(errors[0], errors[1], (case, repeat))
                self.assertEqual(state(pair[0]), state(pair[1]), (case, repeat))

    def test_call_override_can_replace_register_bank(self):
        def call(cpu, target, ret):
            cpu.calls.append(target)
            cpu.r = list(cpu.r)
            cpu.setpc(ret)
        code = struct.pack('<3H', 0xf040, 0, 0xf165)
        pair = [type('ReplaceCallBank', (cls,), {'call': call})(code, {})
                for cls in (CPU, self.fast)]
        errors = [outcome(cpu, 'run', 0x200000, direct=True, budget=10) for cpu in pair]
        self.assertEqual(errors[0], errors[1])
        self.assertEqual(state(pair[0]), state(pair[1]))
        self.assertEqual([pc for pc, op in pair[1].trace], [0x200000, 0x200002])

    def test_memory_overrides_can_replace_register_bank_within_instructions(self):
        def read(cpu, address):
            value = CPU.read(cpu, address)
            cpu.r = list(cpu.r)
            cpu.r[2] = 0x1234
            return value
        def write(cpu, address, value):
            CPU.write(cpu, address, value)
            cpu.r = list(cpu.r)
            cpu.r[2] = 0x1234
        # Load then ADD in same block, postincrement load, PUSH and POP.
        for op in (0x9200, 0x92d2, 0xd288, 0x9088):
            code = struct.pack('<3H', op, 0x0441, 0xf165)
            for method in ('step', 'run'):
                pair = [type('ReplaceMemoryBank', (cls,), {'read': read, 'write': write})(
                    code, {0: 5, 0x1e12: 5, 0x1f01: 5}) for cls in (CPU, self.fast)]
                kwargs = {'direct': True, 'budget': 3} if method == 'run' else {}
                args = (0x200000,) if method == 'run' else ()
                errors = [outcome(cpu, method, *args, **kwargs) for cpu in pair]
                self.assertEqual(errors[0], errors[1], (hex(op), method))
                self.assertEqual(state(pair[0]), state(pair[1]), (hex(op), method))

    def test_read_override_redirect_and_instruction_override_are_honored(self):
        code = struct.pack('<5H', 0x9200, 0x0241, 0x0241, 0x0241, 0x0241)
        def read(cpu, address):
            cpu.setpc(0x200003)
            return CPU.read(cpu, address)
        pair = [type('Redirect', (cls,), {'read':read})(code, {0x1e12:3})
                for cls in (CPU, self.fast)]
        errors = [outcome(cpu, 'run', 0x200000, direct=True, budget=2) for cpu in pair]
        self.assertEqual(errors[0], errors[1])
        self.assertEqual(state(pair[0]), state(pair[1]))
        def step(cpu):
            cpu.mem[1] = cpu.mem.get(1, 0) + 1
            CPU.step(cpu)
        pair = [type('StepOverride', (cls,), {'step':step})(code, {0x1e12:3})
                for cls in (CPU, self.fast)]
        errors = [outcome(cpu, 'run', 0x200000, direct=True, budget=3) for cpu in pair]
        self.assertEqual(errors[0], errors[1])
        self.assertEqual(state(pair[0]), state(pair[1]))


@unittest.skipUnless(os.environ.get('PENC_R23_BIN'), 'External R23 BIN not provided')
class R23AcceleratorTests(unittest.TestCase):
    def test_native_frames_match_reference_cpu_and_transaction_rollback(self):
        import bench as bench_module
        import runtime_bridge as rt
        import audio_completion
        import native_connector
        import native_boot
        from host_clock import native_frame
        class ReferenceMotionCPU(rt.MotionCPU):
            step = CPU.step
            word = CPU.word
        original_cpu = bench_module.CPU
        records = []
        try:
            for cls in (ReferenceMotionCPU, rt.MotionCPU):
                native_connector.cable.clear()
                audio_completion.clock.clear()
                rt.clear_motion()
                bench_module.CPU = cls
                b = bench_module.Bench(os.environ['PENC_R23_BIN'], ROOT/'public/profiles/r23.json')
                native_boot.new_game(b)
                frames = []
                # Real title -> clock -> egg startup, including key edges,
                # then continuous hatching animation and sound adapters.
                keys = [(), ('B',), (), ('A',), (), ('B',), (), ('C',)]
                keys += [()] * 40 + [('A',), (), ('B',), ()] + [()] * 128
                for i, held in enumerate(keys):
                    audio_completion.clock.begin(b.code, elapsed_ms=15.625, speed=2)
                    native_frame(b, set(held), seconds=int(i % 64 == 63))
                    audio_completion.clock.commit(b)
                    frames.append((dict(b.ram), b.virtual_flash, b.virtual_album,
                                   b.total_steps, list(b.last_trace), list(b.last_calls),
                                   list(b.last_adapters), b.last_result, set(b.previous_keys)))
                # Unknown instruction fetch must discard the transaction.
                before = (dict(b.ram), b.virtual_flash, b.virtual_album)
                with self.assertRaises(RuntimeError):
                    b.execute(0x600001, direct=True)
                self.assertEqual((b.ram, b.virtual_flash, b.virtual_album), before)
                records.append((frames, b.stop_reason))
            self.assertEqual(records[0], records[1])
        finally:
            bench_module.CPU = original_cpu
            native_connector.cable.clear()
            audio_completion.clock.clear()
            rt.clear_motion()


if __name__ == '__main__':
    unittest.main()
