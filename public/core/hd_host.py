# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Host-side reader of the R15h / R16h Height48 frames (same rules as the renderer hook, for tests and previews).

R15h rows are a byte stream (hd/hd_pack.py); R16h rows are bit-packed, CB+0 = bits per index (hd/r16h_pack.py).
"""
import struct

P0, SLOTS = 0x2F5A5F, 3744
OLD_START = 2 * P0
HOOKS = {'r15h': (0x3FC2AB, 0x3FC800), 'r16h': (0x3FC6E9, 0x3FCA00)}   # site (goto), hook entry


def present(code):
    """'r15h' / 'r16h' when that renderer hook is in the upper copy, else None."""
    for name, (site, hook) in HOOKS.items():
        at = 2 * (site - 0x200000) + 0x400000
        if code[at:at + 4] == struct.pack('<HH', 0xFE80 | (hook >> 16), hook & 0xFFFF):
            return name
    return None


def _w(code, cpu, bank):
    return struct.unpack_from('<H', code, 2 * (cpu - 0x200000) + (0 if bank == 0 else 0x400000))[0]


def slot_of(descriptor):
    """Old-frame slot of a 16x16 character pointer, or None (bank1 pointer at P0 + 256 * slot)."""
    if descriptor[7] & 0x2000:
        return None
    ptr = descriptor[6] | ((descriptor[7] & 0x3F) << 16)
    d = ptr - P0
    if d < 0 or d & 0xFF or d >> 8 >= SLOTS:
        return None
    return d >> 8


def frame(code, slot):
    """(dx, H, rows) with rows[y] = (x0, [indices]) or None, plus the palette; None without a DIR entry."""
    lo, hi = _w(code, P0 + 2 * slot, 1), _w(code, P0 + 2 * slot + 1, 1)
    if not lo and not hi:
        return None
    bank = 0 if hi & 0x8000 else 1
    fr = ((hi & 0x3F) << 16) | lo
    dx, h, cb = _w(code, fr, bank), _w(code, fr + 1, bank), _w(code, fr + 2, bank)
    dx = dx - 0x10000 if dx & 0x8000 else dx
    seg = fr & 0x3F0000
    palette = [None] + [_w(code, seg | ((cb + i) & 0xFFFF), bank) for i in range(1, 256)]
    bits = None
    if present(code) == 'r16h':                 # CB+0 = K << 8 | b
        head = _w(code, seg | cb, bank)
        bits, palette = head & 255, palette[:1 + (head >> 8)]
    rows = []
    for y in range(h):
        off = _w(code, fr + 3 + y, bank)
        if off == 0xFFFF:
            rows.append(None)
            continue
        at = seg | ((cb + off) & 0xFFFF)
        if bits is not None:
            rows.append(_bit_row(lambda i: _w(code, seg | ((cb + off + i) & 0xFFFF), bank), bits))
            continue
        head = _w(code, at, bank)
        x0, n = head >> 8, head & 255
        data = []
        for k in range(1, n + 3):
            w = _w(code, at + k, bank)
            data += [w >> 8, w & 255]
        px, k = [], 0
        while len(px) < n:
            c = data[k]
            k += 1
            if c < 128:
                px += data[k:k + c + 1]
                k += c + 1
            else:
                px += [data[k]] * (c - 126)
                k += 1
        rows.append((x0, px[:n]))
    return dx, h, rows, palette, bank


def _bit_row(get_word, b):
    """R16h row: header x0 << 8 | n, then LSB-first 4-bit tokens (t < 8: t+1 literals, else t-6 copies)."""
    head = get_word(0)
    x0, n = head >> 8, head & 255
    st = [0, 0, 1]                              # bits, count, next word

    def get(k):
        while st[1] < k:
            st[0] |= get_word(st[2]) << st[1]
            st[1] += 16
            st[2] += 1
        v = st[0] & ((1 << k) - 1)
        st[0] >>= k
        st[1] -= k
        return v
    px = []
    while len(px) < n:
        t = get(4)
        px += [get(b) for _ in range(t + 1)] if t < 8 else [get(b)] * (t - 6)
    return x0, px[:n]


def draw(code, descriptor, lines, first=0, count=96):
    """Draw an HD slot into lines (96 rows of 96 RGB565) like the hook does; False if not HD."""
    slot = slot_of(descriptor)
    f = frame(code, slot) if slot is not None else None
    if f is None:
        return False
    dx, h, rows, palette, _ = f
    x, y, x2, y2 = (v - 0x10000 if v & 0x8000 else v for v in (descriptor[2], descriptor[3], descriptor[9], descriptor[10]))
    if x2 < 0 or x > 95:                       # the renderer's slot checks (box), before the hook
        return True
    mirror = descriptor[11] != 0
    for ry in range(48):
        row = y + ry
        if not first <= row < first + count or not 0 <= row < 96 or row > y2:
            continue
        fy = ry - (48 - h)
        if fy < 0 or rows[fy] is None:
            continue
        x0, px = rows[fy]
        for i, c in enumerate(px):
            if not c:
                continue
            sx = x + 47 - (dx + x0 + i) if mirror else x + dx + x0 + i
            if 0 <= sx < 96:
                lines[row][sx] = palette[c]
    return True


def image(code, descriptor):
    """Host preview: (W, 48, colours or None, x offset from the box for plain and for mirrored drawing)."""
    slot = slot_of(descriptor)
    f = frame(code, slot) if slot is not None else None
    if f is None:
        return None
    dx, h, rows, palette, _ = f
    w = max([x0 + len(px) for r in rows if r for x0, px in [r]] + [1])
    out = [None] * (w * 48)
    for y, r in enumerate(rows):
        if r:
            x0, px = r
            for i, c in enumerate(px):
                if c:
                    v = palette[c]
                    out[(48 - h + y) * w + x0 + i] = '#%02x%02x%02x' % (((v >> 11) & 31) * 255 // 31,
                                                                        ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31)
    return w, 48, out, dx, 48 - dx - w
