# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Pinned DMC v4.1 presentation, checked against native2078EF scanout.

Descriptors and game decisions remain native. Decode its top-down RGB565 and
private4bpp pixels on the host; execute the BIN's own transparent UI routine in
scratch RAM. No PenC bank offset, glyph table, or sprite flags are reused.
"""
import hashlib
import struct

FIRMWARE_SHA256 = '3457140c5f07211abdd756462693c67c824c4c45c26a7ca91e4323df476701dc'
UI_ROW = 0x21b600
SIZE = 96
TRANSPARENT = 0x07e0
_UNPAINTED = 0x10000


def _signed(value):
    return value - 65536 if value & 32768 else value


class _Renderer:
    def __init__(self, code):
        if not isinstance(code, bytes) or hashlib.sha256(code).hexdigest() != FIRMWARE_SHA256:
            raise ValueError('DMC renderer requires the admitted v4.1 firmware')
        self.code = code
        self.sprites = {}
        self.colours = {}
        self.ui_key = None
        self.ui = None

    def sprite(self, d):
        key = (d[0], d[1] if d[0] == 0xfffe else 0, *d[4:8])
        if key in self.sprites:
            return self.sprites[key]
        w, h = d[4:6]
        if not 1 <= w <= 96 or not 1 <= h <= 96:
            raise ValueError('Invalid DMC sprite dimensions')
        if d[0] == 0xfffe:
            pixels = (d[1],) * (w * h)
        else:
            pointer = d[6] | ((d[7] & 63) << 16)
            offset = 2 * (pointer - 0x200000)
            packed = bool(d[7] & 0x8000)
            length = 1184 if packed else w * h * 2
            if not 0 <= offset < offset + length <= 0x400000:
                raise ValueError('Invalid DMC sprite pointer')
            if packed:
                if (w, h) != (48, 48):
                    raise ValueError('Invalid DMC private sprite dimensions')
                words = struct.unpack_from('<592H', self.code, offset)
                if words[0] != TRANSPARENT:
                    raise ValueError('Invalid DMC private palette')
                pixels = tuple(words[(word >> shift) & 15]
                               for word in words[16:] for shift in (0, 4, 8, 12))
            else:
                pixels = struct.unpack_from('<%dH' % (w * h), self.code, offset)
        if len(self.sprites) >= 256:
            self.sprites.clear()
        self.sprites[key] = pixels
        return pixels

    def overlay(self, cpu, descriptors, count):
        m = cpu.mem
        # Pinned row21B600 reads extension fields, biological type, main/menu
        # selection, and the eight native toolbar descriptors. It does not read
        # animation positions, RTC/care timers, or pre-existing row pixels.
        key = (tuple(m.get(a, 0) for a in range(0x885, 0x894)),
               m.get(0x826, 0), m.get(0xc88, 0), m.get(0xcdd, 0), count,
               tuple(descriptors[1:9]))
        if key == self.ui_key:
            return self.ui
        original, registers, flags = cpu.mem, list(cpu.r), cpu.fr
        ink = []
        try:
            cpu.mem = dict(original)
            for y in range(SIZE):
                # Sentinel is outside RGB565. This pinned transparent routine
                # only writes row pixels; untouched cells remain unambiguous.
                cpu.mem.update((0x7ba + x, _UNPAINTED) for x in range(SIZE))
                cpu.r[1] = y
                cpu.invoke(UI_ROW)
                ink.append(tuple((x, cpu.mem[0x7ba + x]) for x in range(SIZE)
                                 if cpu.mem[0x7ba + x] != _UNPAINTED))
        finally:
            cpu.mem = original
            cpu.r[:] = registers
            cpu.fr = flags
        self.ui_key, self.ui = key, tuple(ink)
        return self.ui

    def render(self, cpu):
        m = cpu.mem
        count = m.get(0x7b8, 0)
        if not 0 <= count <= 36:
            raise ValueError('Invalid DMC descriptor count')
        ds = [tuple(m.get(0x608 + slot * 12 + i, 0) for i in range(12))
              for slot in range(36)]
        modal = m.get(0xc88) == 4 and m.get(0x885) == 0x5744 and m.get(0x886) == 1
        mode = m.get(0x88f)
        stop = 10 if modal and mode == 1 else 9 if modal and mode == 2 else 36
        sprites = []
        for slot, d in enumerate(ds[:min(count, stop)]):
            if d[0] == 0xffff or d[8] != 1:
                continue
            flip = bool(d[11])
            if d[7] & 0xc000 == 0xc000 and d[0] != 0xfffe:
                flip = not flip
            sprites.append((_signed(d[2]), _signed(d[3]), d[4], d[5], _signed(d[10]),
                            flip, d[0] == 0xfffe, self.sprite(d)))
        ink = self.overlay(cpu, ds, count)
        # Native2078EF retains its scanline scratch between rows. Opaque
        # backgrounds normally cover it; preserve the behavior for sparse scenes.
        row = [m.get(0x7ba + x, 0) for x in range(SIZE)]
        colours, out = self.colours, bytearray()
        for y in range(SIZE):
            row = list(row)
            for x0, y0, w, h, bottom, flip, solid, pixels in sprites:
                if not y0 <= y <= min(y0 + h - 1, bottom):
                    continue
                base = (y - y0) * w
                for x in range(max(0, -x0), min(w, SIZE - x0)):
                    value = pixels[base + (w - 1 - x if flip else x)]
                    if solid or value != TRANSPARENT:
                        row[x + x0] = value
            for x, value in ink[y]:
                row[x] = value
            for value in row:
                if value not in colours:
                    colours[value] = bytes((((value >> 11) & 31) * 255 // 31,
                                            ((value >> 5) & 63) * 255 // 63,
                                            (value & 31) * 255 // 31, 255))
                out.extend(colours[value])
        return bytes(out)


def render(cpu):
    """Return 96×96 RGBA bytes; preserve all RAM and execution registers."""
    cache = getattr(cpu, '_dmc_render_cache', None)
    if cache is None or cache.code is not cpu.code:
        cache = _Renderer(cpu.code)
        cpu._dmc_render_cache = cache
    return cache.render(cpu)
