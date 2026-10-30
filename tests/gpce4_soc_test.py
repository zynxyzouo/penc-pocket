"""Behavioral peripheral / snapshot checks for the full-machine C port.

Run after tools/build-gpce4.py --native. No private ROMs are needed.
"""
import ctypes as C
from pathlib import Path
import struct
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]


class Core:
    def __init__(self):
        binary = ROOT / 'build' / 'gpce4.dll'
        assert binary.exists(), 'Full-machine compiled core has not been implemented'
        self.lib = C.CDLL(str(binary))
        for name in ('gp_irom_ptr', 'gp_flash_ptr', 'gp_rgba_ptr', 'gp_cpu_ptr',
                     'gp_ram_ptr', 'gp_io_ptr', 'gp_metrics_ptr', 'gp_state_ptr', 'gp_dirty_ptr'):
            getattr(self.lib, name).restype = C.c_void_p
        for name in ('gp_state_size', 'gp_run', 'gp_bus_read'):
            getattr(self.lib, name).restype = C.c_uint32
        self.lib.gp_run.argtypes = [C.c_uint32]
        self.lib.gp_bus_write.argtypes = [C.c_uint32, C.c_uint32]
        self.lib.gp_bus_read.argtypes = [C.c_uint32]
        self.irom = (C.c_uint16 * 0xC000).from_address(self.lib.gp_irom_ptr())
        self.flash = (C.c_uint8 * 0x800000).from_address(self.lib.gp_flash_ptr())
        self.ram = (C.c_uint16 * 0x3000).from_address(self.lib.gp_ram_ptr())
        self.io = (C.c_uint16 * 0x1000).from_address(self.lib.gp_io_ptr())

    def reset(self):
        C.memset(self.lib.gp_irom_ptr(), 0, 0x18000)
        # Branch to self; no IRQs enabled, suitable for exact virtual-time tests.
        self.irom[0x17] = 0x4000
        self.irom[0] = 0xEE41
        C.memset(self.lib.gp_flash_ptr(), 255, 0x800000)
        assert self.lib.gp_reset(12_000_000) == 1

    def metrics(self):
        return list((C.c_uint32 * 24).from_address(self.lib.gp_metrics_ptr()))

    def snapshot(self):
        return C.string_at(self.lib.gp_state_ptr(), self.lib.gp_state_size())

    def restore(self, data):
        C.memmove(self.lib.gp_state_ptr(), data, len(data))
        return self.lib.gp_restore()

    def write(self, a, v):
        self.lib.gp_bus_write(a, v)

    def read(self, a):
        return self.lib.gp_bus_read(a)

    def cs(self, selected):
        self.write(0x3000, 0 if selected else 0x1000)

    def spi(self, byte):
        self.write(0x30E2, byte)
        return self.read(0x30E4)

    def command(self, *data):
        self.cs(True)
        result = [self.spi(x) for x in data]
        self.cs(False)
        return result

    def lcd(self, command, *data):
        self.write(0x3005, 0)
        self.write(0x3092, command)
        self.write(0x3005, 0x400)
        for v in data:
            self.write(0x3092, v)


class PeripheralTests(unittest.TestCase):
    def setUp(self):
        if not hasattr(self.__class__, 'c'):
            self.__class__.c = Core()
        self.c.reset()

    def test_gpio_keys_direction_and_guessed_adc(self):
        c = self.c
        c.lib.gp_keys(0x28)
        self.assertEqual(c.read(0x3000), 0xFFD7)
        c.write(0x3002, 0x10)
        c.write(0x3001, 0)
        self.assertEqual(c.read(0x3000), 0xFFC7)
        self.assertEqual(c.read(0x3071), 0xE000)

    def test_flash_jedec_sleep_pagewrap_and_erase_dirty(self):
        c = self.c
        self.assertEqual(c.command(0x9F, 0, 0, 0), [255, 0xC2, 0x20, 0x17])
        c.command(0xB9)
        self.assertEqual(c.command(0x9F, 0), [255, 255])
        self.assertEqual(c.command(0xAB, 0, 0, 0, 0)[-1], 0x16)
        c.command(0x06)
        c.command(0x02, 0, 1, 255, 0x12, 0x34)
        self.assertEqual((c.flash[0x1FF], c.flash[0x100]), (0x12, 0x34))
        self.assertEqual(c.command(0x05, 0)[-1], 0)
        self.assertEqual(c.metrics()[17], 1)
        c.command(0x06)
        c.command(0x20, 0, 1, 0)
        self.assertEqual(bytes(c.flash[:4096]), b'\xff' * 4096)
        self.assertEqual(c.metrics()[17], 1)

    def test_lcd_window_and_partial_pixel_snapshot(self):
        c = self.c
        c.lcd(0x2A, 0, 0, 0, 1)
        c.lcd(0x2B, 0, 18, 0, 18)
        c.lcd(0x2C, 0xF8)
        state = c.snapshot()
        c.write(0x3092, 0)
        rgba = C.string_at(c.lib.gp_rgba_ptr(), 96 * 96 * 4)
        self.assertEqual(rgba[:4], bytes((255, 0, 0, 255)))
        self.assertEqual(c.restore(state), 1)
        c.write(0x3092, 0)
        self.assertEqual(C.string_at(c.lib.gp_rgba_ptr(), len(rgba)), rgba)

    def test_snapshot_retains_active_spi_transaction_and_unread_fifo(self):
        c = self.c
        c.flash[0x123] = 0x56
        c.flash[0x124] = 0x78
        c.cs(True)
        for byte in (3, 0, 1, 0x23):
            c.write(0x30E2, byte)
        state = c.snapshot()
        c.write(0x30E2, 0)
        c.write(0x30E2, 0)
        expected = [c.read(0x30E4) for _ in range(6)]
        self.assertEqual(expected, [255, 255, 255, 255, 0x56, 0x78])
        self.assertEqual(c.restore(state), 1)
        c.write(0x30E2, 0)
        c.write(0x30E2, 0)
        self.assertEqual([c.read(0x30E4) for _ in range(6)], expected)

    def test_timebase_and_timer_irq_lines_acknowledge_independently(self):
        c = self.c
        c.write(0x3014, 0x4480)
        c.write(0x3015, 0x4480)
        c.write(0x3016, 0x100)
        c.write(0x3050, 0x2000)
        c.write(0x3053, 4)
        c.write(0x3036, 1)
        c.lib.gp_run(187_501)
        self.assertEqual(c.metrics()[13], (1 << 3) | (1 << 8))
        c.write(0x3054, 4)
        self.assertEqual(c.metrics()[13], 1 << 3)
        c.write(0x3051, 0x2000)
        self.assertEqual(c.metrics()[13], 0)

    def test_timer_boundary_ack_and_split_batches_are_exact(self):
        c = self.c
        c.write(0x3014, 0x4480)
        c.write(0x3015, 0x4480)
        c.write(0x3016, 0x100)
        c.write(0x3036, 1)
        c.lib.gp_run(12000)
        self.assertEqual(c.read(0x3051), 0)
        c.lib.gp_run(1)
        self.assertEqual(c.read(0x3051), 0x2000)
        c.write(0x3051, 0x2000)
        self.assertEqual(c.read(0x3051), 0)
        start = c.snapshot()
        c.lib.gp_run(90000)
        whole = c.snapshot()
        self.assertEqual(c.restore(start), 1)
        for n in [3, 100, 3000, 20000, 1, 66896]:
            c.lib.gp_run(n)
        self.assertEqual(c.snapshot(), whole)

    def test_snapshot_crc_rejection_preserves_current_session(self):
        c = self.c
        c.write(5, 1234)
        original = c.snapshot()
        broken = bytearray(original)
        broken[-16] ^= 1
        self.assertEqual(c.restore(bytes(broken)), 0)
        self.assertEqual(c.snapshot(), original)
        # Valid CRC with impossible 32-bit CPU register must also be rejected.
        broken = bytearray(original)
        struct.pack_into('<I', broken, 16, 0x10000)
        struct.pack_into('<I', broken, 12, zlib.crc32(broken[16:]))
        self.assertEqual(c.restore(bytes(broken)), 0)
        self.assertEqual(c.snapshot(), original)

    def test_bank_overflow_and_unmapped_bus_fail_closed(self):
        c = self.c
        c.write(0x30E9, 2)
        c.read(0x200000)
        self.assertEqual(c.metrics()[1], 2)
        self.assertEqual(c.lib.gp_run(100), 0)
        c.reset()
        c.read(0xFFFFFFFF)
        self.assertEqual(c.metrics()[1], 2)
        c.reset()
        c.command(0x06)
        c.command(0x02, 0xFF, 0xFF, 0xFF, 0)
        self.assertEqual(c.metrics()[1], 2)

    def test_unknown_io_is_bounded_and_fifo_overflow_faults(self):
        c = self.c
        for _ in range(100):
            self.assertEqual(c.read(0x3FFF), 0)
        self.assertEqual(c.metrics()[15], 1)
        cap = c.metrics()[22]
        for _ in range(cap + 1):
            c.write(0x30E2, 0)
        self.assertEqual(c.metrics()[1], 3)
        self.assertEqual(c.metrics()[16], cap)


if __name__ == '__main__':
    unittest.main()
