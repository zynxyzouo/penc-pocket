"""Private reset-boot differential: Python reference versus native C.

All external files are explicit CLI parameters. The JSON receipt contains only
hashes and counters, never ROM or saved gameplay bytes.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import struct
import sys
import time

from gpce4_soc_test import Core


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--irom', required=True, type=Path)
    parser.add_argument('--flash', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--instructions', type=int, default=24_000_000)
    args = parser.parse_args()
    sys.path.insert(0, str(args.reference))
    from soc import Machine

    irom, flash = args.irom.read_bytes(), args.flash.read_bytes()
    assert len(irom) == 0x18000 and len(flash) == 0x800000
    c = Core()
    C.memmove(c.lib.gp_irom_ptr(), irom, len(irom))
    C.memmove(c.lib.gp_flash_ptr(), flash, len(flash))
    assert c.lib.gp_reset(12_000_000) == 1
    m = Machine(struct.unpack('<49152H', irom), flash)
    checkpoints = sorted(set([min(1000, args.instructions), min(100_000, args.instructions),
                              min(2_000_000, args.instructions), args.instructions]))
    receipt = {'irom_sha256': digest(irom), 'flash_sha256': digest(flash),
               'instructions': args.instructions, 'checkpoints': [],
               'timing_assumptions': {'ips': 12_000_000, 'timer_hz': 48_000_000, 'adc': 0xE000}}
    previous = 0
    for end in checkpoints:
        start = time.perf_counter()
        executed = c.lib.gp_run(end - previous)
        native_seconds = time.perf_counter() - start
        stats = c.metrics()
        assert executed == end - previous, f'C fault {stats}'
        start = time.perf_counter()
        m.run(end - previous)
        python_seconds = time.perf_counter() - start
        cpu_words = (C.c_uint32 * 24).from_address(c.lib.gp_cpu_ptr())
        native_cpu = {'r': list(cpu_words[:8]), 'fr': cpu_words[8],
                      'secbank': list(cpu_words[9:13]), 'sirq': cpu_words[13],
                      'irq_active': cpu_words[14], 'fiq_active': cpu_words[15],
                      'sleeping': cpu_words[16], 'steps': stats[7] | (stats[8] << 32)}
        python_cpu = {name: getattr(m.cpu, name) for name in native_cpu}
        assert native_cpu == python_cpu, (end, native_cpu, python_cpu)
        native_ram = C.string_at(c.lib.gp_ram_ptr(), 0x6000)
        python_ram = struct.pack('<12288H', *m.ram)
        assert native_ram == python_ram, f'RAM diverged at {end}'
        assert list(c.io) == [m.io.get(0x3000 + a, 0) for a in range(0x1000)], f'IO diverged at {end}'
        # GpSoc starts with the RAM and IO arrays, then all 162x162 LCD words.
        native_full_lcd = C.string_at(c.lib.gp_ram_ptr() + 0x8000, 162 * 162 * 2)
        assert native_full_lcd == struct.pack('<26244H', *m.lcd.mem), f'Full LCD RAM diverged at {end}'
        native_rgba = C.string_at(c.lib.gp_rgba_ptr(), 96 * 96 * 4)
        native_rgb = b''.join(native_rgba[n:n + 3] for n in range(0, len(native_rgba), 4))
        python_rgb = m.lcd.rgb()
        assert native_rgb == python_rgb, f'LCD diverged at {end}'
        assert bytes(c.flash) == bytes(m.flash.data), f'Flash diverged at {end}'
        assert stats[10] == m.lcd.pixels_written
        assert stats[12] == m.int_status
        assert stats[15] == len(m.unknown)
        assert stats[16] == len(m.spi_rx)
        result = {'instructions': end, 'pc': stats[9], 'steps': native_cpu['steps'],
                  'native_seconds': native_seconds, 'python_seconds': python_seconds,
                  'ram_sha256': digest(native_ram), 'lcd_rgb_sha256': digest(native_rgb),
                  'full_lcd_ram_sha256': digest(native_full_lcd),
                  'flash_sha256': digest(bytes(c.flash)), 'lcd_pixels': stats[10],
                  'unknown_io': stats[15], 'int_status': stats[12], 'passed': True}
        receipt['checkpoints'].append(result)
        print(json.dumps(result), flush=True)
        previous = end
    # Resume from a state with live IRQ/LCD/SPI/timers and vary batch sizes.
    state, saved_flash = c.snapshot(), bytes(c.flash)
    c.lib.gp_keys(0x10)
    c.lib.gp_run(500_000)
    uninterrupted, resumed_flash = c.snapshot(), bytes(c.flash)
    C.memmove(c.lib.gp_flash_ptr(), saved_flash, len(saved_flash))
    assert c.restore(state) == 1
    c.lib.gp_keys(0x10)
    for n in (1, 17, 4096, 101, 200_000, 295_785):
        assert c.lib.gp_run(n) == n
    assert c.snapshot() == uninterrupted, 'Split batch snapshot diverged'
    assert bytes(c.flash) == resumed_flash, 'Split batch Flash diverged'
    receipt['snapshot_split_resume_passed'] = True
    receipt['snapshot_bytes'] = len(state)
    receipt['status'] = 'PASS_PYTHON_NATIVE_RESET_BOOT_EXPERIMENTAL_TIMING'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(f'PASS receipt: {args.output}')


if __name__ == '__main__':
    main()
