# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Presentation only: expand native frames without changing machine state.

The original 96x96 frame is copied verbatim into the middle of a 144x96 view.
Foreground overhangs retain their original pixel scale. No CPU tick or RAM write.
This module is deliberately separate from the pinned save-compatible core.
"""
import base64
import web_adapter as native

WIDTH, HEIGHT, PAD = 144, 96, 24
MARGIN_COLUMNS = tuple(range(PAD)) + tuple(range(PAD + 96, WIDTH))
_source_bench = None
_source_scene = None
_source_rgba = None


def cached_sprite(descriptor):
    key = (descriptor[0], *descriptor[4:8], descriptor[11])
    return native.sprite_cache.get(key)


def project_wide(encoded):
    global _source_bench, _source_scene, _source_rgba
    source = base64.b64decode(encoded)
    if len(source) != 96 * 96 * 4:
        raise ValueError('Unexpected native frame size')
    _source_bench, _source_scene, _source_rgba = native.bench, native.last_scene, source
    # Each edge extends its own row colour, preserving menu panels and text
    # bands without mirroring text or assuming that every screen is green.
    canvas = bytearray(WIDTH * HEIGHT * 4)
    for y in range(HEIGHT):
        row = source[y*96*4:(y+1)*96*4]
        canvas[y*WIDTH*4:(y+1)*WIDTH*4] = row[:4]*PAD + row + row[-4:]*PAD
    bench = native.bench
    slots, descriptors = bench.drawn_slots(), bench.descriptors()
    home = bench.ram[0xc9c] == 4 and bench.ram[0xc9e] in (0, 1, 2, 3)
    if home and slots:
        d = descriptors[slots[0]]
        background = cached_sprite(d)
        if (background and background[:2] == (96, 96)
                and d[2] == d[3] == 0 and not d[11]
                and all(p is not None for p in background[2])):
            pixels = background[2]
            for y in range(HEIGHT):
                # The native center is copied verbatim below. Only synthesize
                # the two margins; drawing its 9,216 center pixels was wasted.
                for x in MARGIN_COLUMNS:
                    sx = PAD - 1 - x if x < PAD else (x - PAD if x < PAD + 96 else 95 - (x - PAD - 96))
                    at = (y * WIDTH + x) * 4
                    canvas[at:at+4] = pixels[y * 96 + sx]
            # Native sprites can straddle an original edge; show those pixels,
            # retaining their native position and scale, not a stretched pet.
            for slot in slots[1:]:
                d = descriptors[slot]
                sprite = cached_sprite(d)
                if sprite is None:
                    continue
                w, h, pixels = sprite
                x0 = d[2] - 65536 if d[2] & 32768 else d[2]
                y0 = d[3] - 65536 if d[3] & 32768 else d[3]
                x0 += PAD + bench.sprite_offset(d)
                for y in range(max(0, -y0), min(h, HEIGHT-y0)):
                    for x in range(max(0, -x0), min(w, WIDTH-x0)):
                        px = x + x0
                        if PAD <= px < PAD + 96:
                            continue
                        color = pixels[y*w + (w-1-x if d[11] else x)]
                        if color is not None:
                            at = ((y+y0)*WIDTH + px)*4
                            canvas[at:at+4] = color
    for y in range(HEIGHT):
        at = (y * WIDTH + PAD) * 4
        canvas[at:at+96*4] = source[y*96*4:(y+1)*96*4]
    return base64.b64encode(canvas).decode('ascii')


def project_hud(encoded=None):
    """Two 432x18 strips on every page, without duplicating toolbar icons.

    A decoded backdrop supplies the quiet margin colours. Other screens keep
    their actual 96-pixel strip centered, extending only the two edge colours.
    The normal worker calls project_wide first, so its raw frame is reusable.
    """
    b = native.bench
    slots, ds = b.drawn_slots(), b.descriptors()
    d = ds[slots[0]] if slots else None
    bg = cached_sprite(d) if d else None
    has_background = (bg and bg[:2] == (96, 96) and d[2] == d[3] == 0
                      and not d[11] and all(c is not None for c in bg[2]))
    canvas = bytearray(432 * 36 * 4)
    if not has_background:
        if encoded is not None:
            source = base64.b64decode(encoded)
        elif _source_bench is b and _source_scene == native.last_scene and _source_rgba is not None:
            source = _source_rgba
        else:
            # The pinned adapter has no last_image; a force render only reads
            # machine state and supplies the current raw frame for direct calls.
            image = getattr(native, 'last_image', None)
            source = image if isinstance(image, (bytes, bytearray)) else None
            if source is None:
                source = base64.b64decode(image or native.render(force=True)['rgba'])
        if len(source) != 96*96*4:
            raise ValueError('Unexpected native HUD source size')
        for row in range(36):
            sy = row if row < 18 else row + 60
            pixels = source[sy*96*4:(sy+1)*96*4]
            canvas[row*432*4:(row+1)*432*4] = pixels[:4]*168 + pixels + pixels[-4:]*168
        return base64.b64encode(canvas).decode('ascii')
    for row in range(36):
        sy = row if row < 18 else row + 60
        pixels = bg[2][sy * 96:(sy + 1) * 96]
        # Use the current backdrop, not a fixed green. A uniform row makes
        # the full strip continuous behind the icons and out to both edges.
        colour = bytes(sum(p[c] for p in pixels) // 96 for c in range(3)) + b'\xff'
        canvas[row * 432 * 4:(row + 1) * 432 * 4] = colour * 432
    for slot in slots[1:]:
        d = ds[slot]
        sprite = cached_sprite(d)
        if not sprite:
            continue
        w, h, pixels = sprite
        x0 = (d[2] - 65536 if d[2] & 32768 else d[2]) + b.sprite_offset(d)
        y0 = d[3] - 65536 if d[3] & 32768 else d[3]
        for y in range(max(0, -y0), min(h, 96-y0)):
            sy = y + y0
            if 18 <= sy < 78:
                continue
            row = sy if sy < 18 else sy - 60
            for x in range(max(0, -x0), min(w, 96-x0)):
                colour = pixels[y*w + (w-1-x if d[11] else x)]
                if colour is not None:
                    at = (row*432 + 168+x+x0)*4
                    canvas[at:at+4] = colour
    return base64.b64encode(canvas).decode('ascii')


_clock_bench = None
_clock_glyphs = {}
_clock_time = None


def project_clock(value):
    """Reuse R18 native clock glyphs, read-only; never enter its clock page.

    207A8D descriptors: main digits 147+d / 52558+288*d / bank34,
    seconds 158+d / 55726+288*d / bank34, colon713 / 47058 / bank43.
    AM/PM and the five seconds segments retain their original second row.
    Decode from the locally selected, hash-pinned BIN, never bundle its art.
    """
    global _clock_bench, _clock_glyphs, _clock_time
    b = native.bench
    if b is not _clock_bench:
        _clock_bench, _clock_glyphs, _clock_time = b, {}, None
    fmt = native.bench.ram[0xcc8]
    key = (value, fmt)
    if key == _clock_time:
        return None
    canvas = bytearray(96 * 48 * 4)
    hh, mm, ss = value.split(':')
    hour = int(hh) if fmt else int(hh) % 12
    # Match this BIN's own 12-hour convention (0 AM / 0 PM) and hidden
    # leading zero; the web clock does not rewrite the emulated RTC.
    digits = [(hour % 10, 21), (int(mm[0]), 42), (int(mm[1]), 57)]
    if hour >= 10:
        digits.insert(0, (hour // 10, 6))
    specs = [(147+d, 52558+288*d, 34, 12, x, 0) for d, x in digits]
    specs += [(158+int(c), 55726+288*int(c), 34, 12, x, 0)
              for c, x in zip(ss, (72, 84))]
    specs += [(713, 47058, 43, 9, 33, 0)]
    if not fmt:
        pm = int(hh) >= 12
        specs += [(712 if pm else 711, 45906 if pm else 44754, 43, 48, 0, 24)]
    phase = int(ss) % 10
    for i in range(5):
        if (i < phase if phase <= 5 else i >= phase-5):
            specs.append((714, 47274, 43, 9, 51+9*i, 24))
    for sid, ptr, bank, width, left, top in specs:
        if sid not in _clock_glyphs:
            d = [sid, 0, 0, 0, width, 24, ptr, bank, 1, width-1, 23, 0]
            _, _, colours = b.sprite(d)
            _clock_glyphs[sid] = [None if c is None else bytes.fromhex(c[1:])+b'\xff' for c in colours]
        for i, colour in enumerate(_clock_glyphs[sid]):
            if colour is not None:
                at = ((top+i//width)*96 + left+i%width)*4
                canvas[at:at+4] = colour
    _clock_time = key
    return base64.b64encode(canvas).decode('ascii')
