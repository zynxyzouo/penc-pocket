# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Disposable web adapter for the existing partial native bench, never a full boot."""
import base64
import hashlib
import json
import math
import time
from pathlib import Path

from bench import Bench
from host_clock import native_frame

FORMAT = 'PENC_WEB_SNAPSHOT_V1'
ADAPTER = 'penc-web-spike-1'
bench = None
profile_sha = None
core_sha = None
sprite_cache = {}
last_scene = None


def load(firmware_path, profile_path, identity):
    global bench, profile_sha, core_sha, sprite_cache, last_scene
    candidate = Bench(firmware_path, profile_path)
    if candidate.entries.get('input_home') != 0x2005e9:
        raise ValueError('這份清單沒有受支援的互動入口。')
    candidate.ram[0xcc7] = 0
    bench = candidate
    profile_sha = hashlib.sha256(Path(profile_path).read_bytes()).hexdigest()
    core_sha = identity
    sprite_cache = {}
    last_scene = None
    return frame([], 0, False)


def keep_preview_awake():
    m = bench.ram
    if (m[0xc9c] == 4 and 0 <= m[0xc9e] <= 3
            and (m[0xc9e] != 0 or m[0xcf3] == 0) and 0 < m[0xc9a] < 0x42a):
        m[0xc9a] = 0x42a


def frame(keys, seconds=0, long=False):
    if bench is None:
        raise ValueError('請先選取 BIN。')
    if not isinstance(keys, list) or any(k not in ('A', 'B', 'C') for k in keys):
        raise ValueError('Invalid key input')
    keep_preview_awake()
    started = time.perf_counter()
    native_frame(bench, set(keys), seconds=seconds, long=bool(long))
    result = render()
    result['frame_ms'] = round((time.perf_counter() - started) * 1000, 1)
    return result


def render(force=False):
    global last_scene
    ds = bench.descriptors()
    slots = bench.drawn_slots()
    scene = (tuple(slots), tuple(tuple(d) for d in ds))
    rgba = None
    if force or scene != last_scene:
        canvas = bytearray([216, 229, 208, 255] * (96 * 96))
        for slot in slots:
            d = ds[slot]
            key = (d[0], *d[4:8], d[11])
            if key not in sprite_cache:
                w, h, colors = bench.sprite(d)
                if w * h > 1024 * 1024:
                    raise ValueError('Sprite exceeds preview limit')
                pixels = [None if c is None else bytes.fromhex(c[1:]) + b'\xff' for c in colors]
                if len(sprite_cache) >= 256:
                    sprite_cache.clear()
                sprite_cache[key] = (w, h, pixels)
            w, h, pixels = sprite_cache[key]
            if not pixels:
                continue
            x0 = d[2] - 65536 if d[2] & 32768 else d[2]
            y0 = d[3] - 65536 if d[3] & 32768 else d[3]
            x0 += bench.sprite_offset(d)
            for y in range(max(0, -y0), min(h, 96-y0)):
                for x in range(max(0, -x0), min(w, 96-x0)):
                    c = pixels[y*w + (w-1-x if d[11] else x)]
                    if c is not None:
                        p = ((y+y0)*96 + x+x0)*4
                        canvas[p:p+4] = c
        rgba = base64.b64encode(canvas).decode('ascii')
        last_scene = scene
    m = bench.ram
    return {'rgba': rgba, 'sha256': bench.sha256,
            'clock': f'{m[0xcc4]:02}:{m[0xcc3]:02}:{m[0xcc2]:02}',
            'state': m[0xc9c], 'substate': m[0xc9e],
            'species': [m[0x826], m[0x838]], 'steps': bench.total_steps,
            'warnings': sorted(bench.device_warnings),
            'time_rate': (1, 120, 600, 3000)[(m[0xdab] >> 9) & 3]}


def release_inputs():
    """Neutralize host-only sampled keys without advancing firmware or game time."""
    bench.previous_keys = set()
    bench.ram.update({0x81b:65535, 0x81c:0, 0x820:0, 0x3000:65535})


def snapshot():
    if bench is None:
        raise ValueError('No firmware loaded')
    return {'format': FORMAT, 'adapter': ADAPTER, 'core_sha256': core_sha,
            'profile_sha256': profile_sha, 'firmware_sha256': bench.sha256,
            'not_device_save': True,
            'ram': {f'{a:04X}': v for a, v in bench.ram.items()},
            'virtual_flash_mirrors_hex': bench.virtual_flash.hex(),
            'virtual_album_hex': bench.virtual_album.hex(),
            'previous_keys': sorted(bench.previous_keys),
            'executed_instructions': bench.total_steps}


def restore(payload):
    """Validate everything before changing the live session. Resume with keys released."""
    if not isinstance(payload, dict):
        raise ValueError('快照格式不正確。')
    for k, expected in [('format', FORMAT), ('adapter', ADAPTER),
                        ('core_sha256', core_sha), ('profile_sha256', profile_sha),
                        ('firmware_sha256', bench.sha256), ('not_device_save', True)]:
        if payload.get(k) != expected:
            raise ValueError('快照與目前 BIN／核心版本不符：' + k)
    raw = payload.get('ram')
    if not isinstance(raw, dict) or not 8192 <= len(raw) <= 16384:
        raise ValueError('RAM 快照大小不正確。')
    ram = {}
    for key, value in raw.items():
        if not isinstance(key, str) or len(key) != 4:
            raise ValueError('Invalid RAM address')
        a = int(key, 16)
        if key != f'{a:04X}' or not (0 <= a < 0x2000 or a in (0x3000, 0x30e9)):
            raise ValueError('Unsupported RAM address')
        if type(value) is not int or not 0 <= value <= 65535:
            raise ValueError('Invalid RAM value')
        ram[a] = value
    if not set(range(0x2000)).issubset(ram):
        raise ValueError('Incomplete RAM')
    if not (0 <= ram[0xcc2] < 60 and 0 <= ram[0xcc3] < 60 and 0 <= ram[0xcc4] < 24):
        raise ValueError('Invalid clock')
    flash = bytes.fromhex(payload['virtual_flash_mirrors_hex'])
    album = bytes.fromhex(payload['virtual_album_hex'])
    if len(flash) != 8192 or len(album) != 64:
        raise ValueError('Flash 快照長度不正確。')
    steps = payload.get('executed_instructions', 0)
    if type(steps) is not int or not 0 <= steps <= 10**15:
        raise ValueError('Invalid instruction count')
    old = (bench.ram, bench.virtual_flash, bench.virtual_album, bench.total_steps, bench.previous_keys)
    try:
        bench.ram, bench.virtual_flash, bench.virtual_album = ram, flash, album
        bench.total_steps = steps
        release_inputs()
        result = render(force=True)
    except Exception:
        bench.ram, bench.virtual_flash, bench.virtual_album, bench.total_steps, bench.previous_keys = old
        raise
    bench.stop_reason = ''
    return result


def dispatch(request_json):
    req = json.loads(request_json)
    op = req['op']
    if op == 'load':
        out = load(req['bin_path'], req['profile_path'], req['core_sha256'])
    elif op == 'frame':
        out = frame(req.get('keys', []), req.get('seconds', 0), req.get('long', False))
    elif op == 'snapshot':
        out = snapshot()
    elif op == 'release':
        release_inputs()
        out = snapshot()
    elif op == 'restore':
        out = restore(req['snapshot'])
    else:
        raise ValueError('Unknown web adapter operation')
    return json.dumps(out, separators=(',', ':'))
