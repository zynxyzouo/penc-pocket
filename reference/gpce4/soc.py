# SPDX-License-Identifier: GPL-3.0-or-later
# Register map and interrupt wiring follow MAME 0.289 generalplus_gpce4_soc.cpp /
# generalplus_gpce4.cpp (BSD-3-Clause, David Haywood); details marked 'guess' are not
# from MAME and not measured on the device.
"""GPCE4064B machine: internal ROM + SPI flash + ST7735 LCD, booted from the reset vector.

Memory (word addresses):
  0000..2FFF  RAM (0000..0FFF on-chip; 1000..17FF cache-as-RAM; above that logged)
  3000..30FF  I/O registers
  4000..FFFF  internal ROM as dumped by R23d (C000.. is the chip's own mirror)
  200000..3FFFFF  SPI flash window (byte offset bank*4 MiB + 2*(a-200000))
Time is counted in executed instructions; `ips` converts to seconds (a guess until the
real cycle timing is known).
"""
from collections import deque
import struct

from unsp import Unsp, FIQ_LINE

IRQ = [1 + n for n in range(8)]          # cpu.set_line index of IRQ0..IRQ7

# INT_Ctrl / INT_Status (3050/3051) bit -> IRQ line; INT2 (3053/3054) bit -> IRQ line (MAME comments)
INT1_LINES = {15: 0, 14: 1, 13: 2, 11: 3, 9: 3, 8: 3, 7: 3, 6: 3, 5: 4, 4: 4, 1: 5, 0: 5}
INT2_LINES = {12: 6, 11: 6, 10: 6, 9: 6, 8: 6, 5: 7, 4: 7, 2: 7, 1: 7, 0: 7}
TIMEBASE = {0: 2, 1: 16, 2: 64, 8: 512, 9: 2048, 10: 4096}     # INT2 bit -> Hz (32768 Hz crystal)


class SpiFlash:
    """MX25L6433F-style NOR flash: commands on the SPI1 byte stream, CS from IOA bit 12."""
    JEDEC = (0xC2, 0x20, 0x17)

    def __init__(self, data):
        self.data = bytearray(data)
        self.selected = False
        self.wel = False
        self.deep_sleep = False
        self.cmd, self.args, self.addr = None, [], 0
        self.log = []
        self.programmed, self.erased = set(), set()

    def select(self):
        self.selected, self.cmd, self.args = True, None, []

    def deselect(self):
        if self.selected and self.cmd == 0x20 and len(self.args) >= 3 and self.wel:
            at = self.addr & ~0xFFF
            self.data[at:at + 0x1000] = b'\xFF' * 0x1000
            self.erased.add(at)
            self.log.append(('erase4k', at))
        if self.cmd in (0x02, 0x20, 0xD8, 0x52, 0x60, 0xC7, 0x01) and len(self.args) >= (0 if self.cmd in (0x60, 0xC7) else 1):
            self.wel = False
        self.selected, self.cmd = False, None

    def transfer(self, byte):
        if not self.selected:
            return 0xFF
        if self.cmd is None:
            self.cmd, self.args = byte, []
            if self.deep_sleep and byte != 0xAB:
                self.log.append(('ignored_in_deep_sleep', byte))
                self.cmd = -1
                return 0xFF
            if byte == 0x06:
                self.wel = True
            elif byte == 0x04:
                self.wel = False
            elif byte == 0xB9:
                self.deep_sleep = True
            elif byte not in (0x03, 0x0B, 0x02, 0x20, 0x05, 0x9F, 0xAB, 0x90, 0x01, 0x35, 0x15, 0xD8, 0x52):
                self.log.append(('unknown_cmd', byte))
            return 0xFF
        c = self.cmd
        self.args.append(byte)
        n = len(self.args)
        if c == 0x05:
            return 0x02 if self.wel else 0x00                # WIP never set: operations are instant
        if c == 0x9F:
            return self.JEDEC[n - 1] if n <= 3 else 0xFF
        if c == 0xAB:
            self.deep_sleep = False
            return 0x16 if n >= 4 else 0xFF
        if c in (0x03, 0x0B, 0x02, 0x20, 0xD8, 0x52, 0x90):
            if n <= 3:
                self.addr = (self.addr << 8 | byte) & 0xFFFFFF if n > 1 else byte
                return 0xFF
            if c == 0x0B and n == 4:
                return 0xFF
            if c in (0x03, 0x0B):
                value = self.data[self.addr % len(self.data)]
                self.addr = (self.addr + 1) % len(self.data)
                return value
            if c == 0x02 and self.wel:
                at = self.addr
                self.data[at] &= byte
                self.programmed.add(at & ~0xFFF)
                self.addr = (at & ~0xFF) | ((at + 1) & 0xFF)       # wraps inside the 256-byte page
                return 0xFF
            return 0xFF
        return 0xFF


class ST7735:
    """Enough of the ST7735 to place pixels: CASET/RASET/RAMWR/MADCTL/COLMOD, RGB565."""
    W = H = 162                    # logical frame, large enough for either MV setting

    def __init__(self):
        self.mem = [0] * (self.W * self.H)
        self.cmd, self.params = None, []
        self.x0, self.x1, self.y0, self.y1 = 0, self.W - 1, 0, self.H - 1
        self.x, self.y = 0, 0
        self.madctl, self.colmod = 0, 0x06
        self.pending_byte = None
        self.on = False
        self.commands = []
        self.pixels_written = 0

    def command(self, byte):
        self.cmd, self.params, self.pending_byte = byte, [], None
        if len(self.commands) < 4000:
            self.commands.append(byte)
        if byte == 0x2C:
            self.x, self.y = self.x0, self.y0
        elif byte == 0x29:
            self.on = True
        elif byte == 0x28:
            self.on = False

    def data(self, byte):
        c = self.cmd
        if c == 0x2C:
            if self.pending_byte is None:
                self.pending_byte = byte
                return
            self.put((self.pending_byte << 8) | byte)
            self.pending_byte = None
            return
        self.params.append(byte)
        p = self.params
        if c == 0x2A and len(p) == 4:
            self.x0, self.x1 = p[0] << 8 | p[1], p[2] << 8 | p[3]
        elif c == 0x2B and len(p) == 4:
            self.y0, self.y1 = p[0] << 8 | p[1], p[2] << 8 | p[3]
        elif c == 0x36 and len(p) == 1:
            self.madctl = p[0]
        elif c == 0x3A and len(p) == 1:
            self.colmod = p[0]

    def put(self, rgb565):
        # Stored in the controller's logical address frame (column counter = x, row counter = y);
        # MADCTL 0xA8 (MY|MV|BGR) is the panel-mounting correction, so this frame is upright.
        if 0 <= self.x < self.W and 0 <= self.y < self.H:
            self.mem[self.y * self.W + self.x] = rgb565
        self.pixels_written += 1
        self.x += 1
        if self.x > self.x1:
            self.x = self.x0
            self.y += 1
            if self.y > self.y1:
                self.y = self.y0

    def rgb(self, x0=0, y0=18, w=96, h=96):
        """Visible 96x96 window (MAME digicolr visarea 0..95 x 18..113) as RGB888.

        The firmware sets MADCTL BGR, and the panel then shows the top five bits as red
        (checked against the reference boot screen: blue logo, red 'C')."""
        out = bytearray()
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                v = self.mem[y * self.W + x]
                hi, g, lo = ((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31
                out += bytes((hi, g, lo))
        return bytes(out)


class Machine:
    def __init__(self, irom, flash, ips=12_000_000, keys_active_low=0x0038, lcd_dc_bit=10, adc=0xE000):
        self.irom = list(irom)                    # 0xC000 words for 4000..FFFF
        assert len(self.irom) == 0xC000
        self.ram = [0] * 0x3000
        self.flash = SpiFlash(flash)
        self.lcd = ST7735()
        self.ips = ips
        self.lcd_dc_bit = lcd_dc_bit
        self.adc = adc                            # 3071 reading (battery); guess
        self.io = {}
        self.unknown = {}
        self.ioa_in = 0xFFFF                      # pins pulled up; keys pull low
        self.iob_in = 0x0000
        self.keys_mask = keys_active_low
        self.int_status = 0                       # 32 bits: 3051 << 16 | 3054
        self.int_ctrl = self.int2_ctrl = 0
        self.spi_rx = deque()
        self.spi_bank = 0
        self.timebase_next = {bit: 0 for bit in TIMEBASE}
        self.timer_next = {}
        self.instr = self.next_event = 0
        self.ram_high = set()
        self.cpu = Unsp(self)
        self.reset_timebase()

    # --- time ------------------------------------------------------------------------------------
    def reset_timebase(self):
        for bit, hz in TIMEBASE.items():
            self.timebase_next[bit] = self.instr + self.ips // hz

    # Timers A/B/C: 16-bit up-counters reloaded from TimerX_Data on overflow, which sets
    # INT_Status bit 15/14/13 (IRQ0/1/2). Clock 48 MHz is a guess that makes the ROM's
    # Timer C reload 0x4480 exactly 1 kHz (MAME also runs timer C at 1 kHz).
    TIMERS = {'A': (0x3010, 0x3011, 15, 0), 'B': (0x3012, 0x3013, 14, 4), 'C': (0x3014, 0x3015, 13, 8)}
    TIMER_HZ = 48_000_000

    def timer_period(self, count):
        return max(1, (0x10000 - count) * self.ips // self.TIMER_HZ)

    def start_timer(self, name):
        data, cntr, _, nibble = self.TIMERS[name]
        if (self.io.get(0x3016, 0) >> nibble) & 15:
            self.timer_next[name] = self.instr + self.timer_period(self.io.get(cntr, 0))
        else:
            self.timer_next.pop(name, None)

    def tick_timers(self):
        for bit, due in self.timebase_next.items():
            if self.instr >= due:
                self.timebase_next[bit] = due + self.ips // TIMEBASE[bit]
                self.int_status |= 1 << bit
        for name, due in list(self.timer_next.items()):
            if self.instr >= due:
                data, _, status_bit, _ = self.TIMERS[name]
                self.timer_next[name] = due + self.timer_period(self.io.get(data, 0))
                self.int_status |= 1 << (16 + status_bit)
        self.update_irqs()
        return min(min(self.timebase_next.values()), min(self.timer_next.values(), default=1 << 62))

    def update_irqs(self):
        lines = [False] * 8
        s1, s2 = self.int_status >> 16, self.int_status & 0xFFFF
        for bit, line in INT1_LINES.items():
            if s1 >> bit & 1 and self.int_ctrl >> bit & 1:
                lines[line] = True
        for bit, line in INT2_LINES.items():
            if s2 >> bit & 1 and self.int2_ctrl >> bit & 1:
                lines[line] = True
        for n in range(8):
            self.cpu.set_line(IRQ[n], lines[n])

    def run(self, instructions, stop=None):
        cpu = self.cpu
        end = self.instr + instructions
        self.next_event = self.instr
        while self.instr < end:
            if self.instr >= self.next_event:
                self.next_event = self.tick_timers()
            if cpu.sleeping and not cpu.sirq:
                self.instr = max(self.instr + 1, min(self.next_event, end))
                continue
            cpu.step()
            self.instr += 1
            if stop is not None and stop(self):
                return True
        return False

    # --- bus ---------------------------------------------------------------------------------------
    def read(self, a):
        if a < 0x3000:
            if a >= 0x1000:
                self.ram_high.add(a & ~0xFF)
            return self.ram[a]
        if a < 0x4000:
            return self.io_read(a)
        if a < 0x10000:
            return self.irom[a - 0x4000]
        if 0x200000 <= a < 0x400000:
            at = self.spi_bank * 0x400000 + 2 * (a - 0x200000)
            d = self.flash.data
            return d[at] | d[at + 1] << 8
        raise RuntimeError(f'read of unmapped {a:06X} at PC {self.cpu.pc:06X}')

    def write(self, a, v):
        v &= 0xFFFF
        if a < 0x3000:
            if a >= 0x1000:
                self.ram_high.add(a & ~0xFF)
            self.ram[a] = v
            return
        if a < 0x4000:
            return self.io_write(a, v)
        raise RuntimeError(f'write {v:04X} to {a:06X} at PC {self.cpu.pc:06X}')

    def note(self, kind, a, v=None):
        key = (kind, a)
        if key not in self.unknown:
            self.unknown[key] = (self.cpu.pc, v)

    # --- I/O -----------------------------------------------------------------------------------------
    def io_read(self, a):
        io = self.io
        if a in (0x3000, 0x3001):                              # IOA data/buffer: pins
            buf, dirn = io.get(0x3001, 0), io.get(0x3002, 0)
            pins = self.ioa_in
            return (buf & dirn) | (pins & ~dirn & 0xFFFF) if a == 0x3000 else buf
        if a == 0x3004:
            buf, dirn = io.get(0x3005, 0), io.get(0x3006, 0)
            return (buf & dirn) | (self.iob_in & ~dirn & 0xFFFF)
        if a in (0x3002, 0x3003, 0x3005, 0x3006, 0x3007, 0x3009, 0x300A, 0x300B, 0x300F, 0x3016,
                 0x3020, 0x3021, 0x3022, 0x3023, 0x3030, 0x30E0, 0x30E7, 0x3090, 0x3072, 0x3070):
            return io.get(a, 0)
        if a == 0x3008:
            return io.get(0x3009, 0)
        if a == 0x3039:
            return io.get(a, 0) & ~0x0002
        if a == 0x3050:
            return self.int_ctrl
        if a == 0x3053:
            return self.int2_ctrl
        if a == 0x3051:
            return self.int_status >> 16
        if a == 0x3054:
            return self.int_status & 0xFFFF
        if a == 0x30E9:
            return self.spi_bank | (io.get(a, 0) & ~15)
        if a == 0x30E3:
            return 0x8000 | min(len(self.spi_rx), 8)
        if a == 0x30E4:
            if not self.spi_rx:
                self.note('spi_rx_underflow', a)
                return 0
            return self.spi_rx.popleft()
        if a == 0x30E5:
            return (0x0004 if self.spi_rx else 0) | 0x0003      # RNE, TNF, TFE; never BSY
        if a == 0x3071:
            return self.adc
        if a in (0x3091, 0x3093, 0x3094):
            return 0
        if a == 0x3095:
            return 0x0003                                      # SPI2: TNF/TFE, never BSY
        self.note('io_read', a)
        return io.get(a, 0)

    def io_write(self, a, v):
        io = self.io
        old = io.get(a, 0)
        io[a] = v
        if a in (0x3000, 0x3001):
            io[0x3001] = v
            if (old ^ v) & 0x1000 or a == 0x3000:
                cs_low = not v & 0x1000
                if cs_low and not self.flash.selected:
                    self.flash.select()
                elif not cs_low and self.flash.selected:
                    self.flash.deselect()
            return
        if a == 0x3004:
            io[0x3005] = v
            return
        if a == 0x3050:
            self.int_ctrl = v
            self.update_irqs()
            return
        if a == 0x3053:
            self.int2_ctrl = v
            self.update_irqs()
            return
        if a == 0x3051:
            self.int_status &= ~(v << 16)
            self.update_irqs()
            return
        if a == 0x3054:
            self.int_status &= ~v
            self.update_irqs()
            return
        if a == 0x3033:
            self.reset_timebase()
            self.next_event = self.instr
            return
        if 0x3010 <= a <= 0x3016:
            for name, (data, cntr, _, _) in self.TIMERS.items():
                if a in (cntr, 0x3016) or (a == data and name not in self.timer_next):
                    self.start_timer(name)
            self.next_event = self.instr
            return
        if a == 0x3036:
            self.cpu.sleeping = True
            return
        if a == 0x30E0:
            if v & 0x0800:
                self.spi_rx.clear()
            return
        if a == 0x30E2:
            self.spi_rx.append(self.flash.transfer(v & 0xFF))
            return
        if a == 0x30E9:
            self.spi_bank = v & 15
            return
        if a == 0x3092:
            if io.get(0x3005, 0) >> self.lcd_dc_bit & 1:
                self.lcd.data(v & 0xFF)
            else:
                self.lcd.command(v & 0xFF)
            return
        if a in (0x3002, 0x3003, 0x3005, 0x3006, 0x3007, 0x3008, 0x3009, 0x300A, 0x300B, 0x300C, 0x300D,
                 0x300E, 0x300F, 0x3010, 0x3011, 0x3012, 0x3013, 0x3014, 0x3015, 0x3016, 0x3020, 0x3021,
                 0x3022, 0x3023, 0x3030, 0x3032, 0x3034, 0x3035, 0x3039, 0x3040, 0x3041, 0x3042, 0x3043,
                 0x3052, 0x3055, 0x3070, 0x3071, 0x3072, 0x3073, 0x3090, 0x3091, 0x3093, 0x3095,
                 0x30E1, 0x30E3, 0x30E5, 0x30E6, 0x30E7):
            return
        self.note('io_write', a, v)

    # --- keys ----------------------------------------------------------------------------------------
    KEYS = {'A': 0x08, 'B': 0x10, 'C': 0x20}      # IOA, active low (firmware 200CF8: ~[3000] & 38)

    def set_keys(self, held=()):
        """held: iterable of 'A'/'B'/'C' currently pressed."""
        bits = 0
        for k in held:
            bits |= self.KEYS[k]
        self.ioa_in = 0xFFFF & ~bits


def load_rom(path):
    data = open(path, 'rb').read()
    return list(struct.unpack(f'<{len(data) // 2}H', data))
