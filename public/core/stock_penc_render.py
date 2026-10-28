# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""96x96 host projection of the original PenC Metal Empire descriptors.

The BIN's20D23E redraw calls unavailable internal ROM004E8F. This module
decodes its native descriptor output and original bank1 RGB565 resources; it
does not claim native rasterizer or physical LCD timing parity. No R8 private
bank, threefold scaling, HD crop, DMC packed-palette, or wide-screen rules apply.
Uncovered pixels are opaque black. All machine state remains unchanged.
"""
import hashlib
import struct

FIRMWARE_SHA256 = 'a21e573ba40741603b8b4068817c789c625196ab5e53ddb188b1f57c63c612a1'
SIZE = 96
TRANSPARENT = 0x07e0
ASSET_START = 0x400000 + 759 * 4
# All759 table entries form one contiguous RGB565 range ending here. Do not
# admit padding or the save journal merely because it is in the upper bank.
ASSET_END = 0x7413fe


def _signed(value):
    return value - 65536 if value & 32768 else value


class _Renderer:
    def __init__(self, code):
        if (type(code) is not bytes or len(code) != 0x800000
                or hashlib.sha256(code).hexdigest() != FIRMWARE_SHA256):
            raise ValueError('Stock renderer requires the admitted Metal Empire firmware')
        self.code = code
        self.sprites = {}
        self.colours = {}
        self.scene = None
        self.image = None

    def sprite(self, d):
        key = (d[0], d[1] if d[0] == 0xfffe else 0, *d[4:8])
        if key in self.sprites:
            return self.sprites[key]
        w, h = d[4:6]
        if not 1 <= w <= SIZE or not 1 <= h <= SIZE:
            raise ValueError('Invalid stock sprite dimensions')
        if d[0] == 0xfffe:
            # Native20D0D7 writes ID=-2 and field1=RGB565. A green fill is
            # opaque, unlike a green-key pixel in an ordinary bitmap.
            pixels = (d[1],) * (w * h)
        else:
            if not 0 <= d[0] < 759 or not 0x20 <= d[7] < 0x40:
                raise ValueError('Invalid stock sprite ID or unsupported bank/format flag')
            pointer = d[6] | (d[7] << 16)
            offset = 0x400000 + 2 * (pointer - 0x200000)
            if not ASSET_START <= offset < offset + w * h * 2 <= ASSET_END:
                raise ValueError('Invalid stock sprite resource pointer')
            pixels = struct.unpack_from('<%dH' % (w * h), self.code, offset)
        if len(self.sprites) >= 256:
            self.sprites.clear()
        self.sprites[key] = pixels
        return pixels

    def render(self, cpu):
        count = cpu.mem.get(0x7b8, 0)
        if type(count) is not int or not 0 <= count <= 36:
            raise ValueError('Invalid stock descriptor count')
        descriptors = tuple(tuple(cpu.mem.get(0x608 + slot * 12 + i, 0)
                                  for i in range(12)) for slot in range(count))
        if descriptors == self.scene:
            return self.image
        canvas = [0] * (SIZE * SIZE)
        for d in descriptors:
            if d[0] == 0xffff or d[8] != 1:
                continue
            if d[11] not in (0, 1):
                raise ValueError('Unsupported stock sprite flip flag')
            pixels = self.sprite(d)
            x0, y0, w, h = _signed(d[2]), _signed(d[3]), d[4], d[5]
            right, bottom = min(x0 + w - 1, _signed(d[9])), min(y0 + h - 1, _signed(d[10]))
            for y in range(max(0, y0), min(SIZE - 1, bottom) + 1):
                source_row, dest_row = (y - y0) * w, y * SIZE
                for x in range(max(0, x0), min(SIZE - 1, right) + 1):
                    sx = x - x0
                    value = pixels[source_row + (w - 1 - sx if d[11] else sx)]
                    if d[0] == 0xfffe or value != TRANSPARENT:
                        canvas[dest_row + x] = value
        out, colours = bytearray(), self.colours
        for value in canvas:
            if value not in colours:
                colours[value] = bytes((((value >> 11) & 31) * 255 // 31,
                                        ((value >> 5) & 63) * 255 // 63,
                                        (value & 31) * 255 // 31, 255))
            out.extend(colours[value])
        self.scene, self.image = descriptors, bytes(out)
        return self.image


def render(cpu):
    """Return native-size RGBA without CPU execution, RAM writes, or timer ticks."""
    cache = getattr(cpu, '_stock_render_cache', None)
    if cache is None or cache.code is not cpu.code:
        cache = _Renderer(cpu.code)
        cpu._stock_render_cache = cache
    return cache.render(cpu)
