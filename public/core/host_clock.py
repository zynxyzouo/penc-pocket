# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Explicit wall-time adapters, not implementations of internal ROM 005FBE.

The audited main loop calls 2C8000 (clock), then 2D1F00 (pair minute +
hidden resolver), then 2005E9 (UI, including the resident resolver).
Here only seconds/minutes/hours and the minute pulse are supplied by the host.
Legacy files retain the old1x path. A hash-bound R8 manifest opts into real
tick2DA400, frameguard2DAE00, C-monitor200000 and UI2005E9. Only the clock
edge is supplied by the host; the native code decides all accelerated care.
"""
import math
import struct
import time


class ClockGap(RuntimeError):
    pass


class WallSeconds:
    def __init__(self):
        self.last = None
        self.fraction = 0.0

    def start(self, now=None):
        self.last = time.monotonic() if now is None else now

    def stop(self):
        self.last = None

    def due(self, now=None):
        now = time.monotonic() if now is None else now
        if self.last is None:
            return 0
        elapsed = now-self.last
        self.last = now
        if elapsed < 0 or elapsed > 5:
            self.stop()
            raise ClockGap('電腦超過 5 秒未更新，已暫停且不補算離開時間。按「開始測試」繼續。')
        self.fraction += elapsed
        seconds = math.floor(self.fraction)
        self.fraction -= seconds
        return seconds


def pending_local_album(bench):
    """Only this hash-admitted committed recovery state may use BUSY as a lock."""
    cfg=getattr(bench,'r8_local_play',None)
    m=bench.ram
    return (isinstance(cfg,dict) and 'jogress' in cfg.get('components',())
            and bench.entries.get('jogress_reconcile')==0x2f1c00
            and (m.get(0xc9c),m.get(0xc9d),m.get(0xc9e),m.get(0xc9f))==(17,17,3,3)
            and m.get(0xdab,0)&0x8000 and m.get(0xdad)==0
            and not (m.get(0xdab,0)&1 and not m.get(0xdab,0)&0x40)
            and 0<=m.get(0x826,65535)<312
            and (not m.get(0xdab,0)&0x40 or 0<=m.get(0x838,65535)<312))


def r8_frame(bench, held, seconds=0, long=False):
    """Sample once per frame, native tick/prefix/C/UI, rollback all on failure.

    More than one elapsed host second is split into separate one-second edges.
    New press and host-long events occur only on the first edge. Native code
    can stop acceleration between edges; the host never adds game minutes.
    """
    cfg = bench.r8_time
    saved_ram, saved_flash, saved_keys = dict(bench.ram), bench.virtual_flash, set(bench.previous_keys)
    saved_album=bench.virtual_album
    trace, calls, adapters = [], [], []
    def execute(entry, clock_seconds=None):
        value = bench.execute(entry, clock_seconds=clock_seconds)
        trace.extend(bench.last_trace); calls.extend(bench.last_calls); adapters.extend(bench.last_adapters)
        return value
    try:
        result = 0
        for index in range(max(1,seconds)):
            sampled = bench.sample_keys(held, long=bool(long and index == 0))
            execute(cfg['tick_entry'], clock_seconds=int(seconds > 0))
            execute(cfg['frame_entry'])
            if bench.ram[0xdab] & 0x8000 and not pending_local_album(bench):
                raise RuntimeError('Native dual-pet context reported a fatal condition')
            execute(0x200000)
            result = execute(0x2005e9)
            bench.previous_keys = sampled
            bench.ram[0xcc7] = 0
        bench.last_trace, bench.last_calls, bench.last_adapters = trace[-20000:], calls, adapters
        bench.host_clock_last = {'mode':'R8 native time with explicit host RTC edge',
            'seconds':seconds,'edge_frames':max(1,seconds),'native_tick':f"{cfg['tick_entry']:06X}",
            'native_prefix':f"{cfg['frame_entry']:06X}",'native_C_monitor':'200000','native_UI':'2005E9',
            'cosmetic_FAST_seconds':bool(bench.ram[0xda4]&1),
            'ROM_limits':'005FBE CC2/CC3/CC4/CC7 only; no hardware timing or full ROM ABI claim'}
        return result
    except Exception:
        bench.ram, bench.virtual_flash, bench.previous_keys = saved_ram, saved_flash, saved_keys
        bench.virtual_album=saved_album
        raise


def native_frame(bench, held, seconds=0, long=False):
    """One audited native frame, with a host clock edge and rollback on error."""
    if type(seconds) is not int or not 0 <= seconds <= 5:
        raise ValueError('Host clock frames accept 0..5 seconds; no bulk catch-up')
    if getattr(bench,'r8_time',None) is not None:
        return r8_frame(bench,held,seconds,long)
    entry = bench.entries.get('frame_minute', 0x2d1f00)
    if (bench.entries.get('input_home') != 0x2005e9 or
        struct.unpack_from('<5H',bench.code,2*(entry-0x200000)) !=
            (0xf06d,0x1800,0xf06d,0x1c00,0x9a90)):
        raise RuntimeError('This BIN has no audited dual-pet frame prefix for host time')
    saved_ram, saved_flash, saved_keys = dict(bench.ram),bench.virtual_flash,set(bench.previous_keys)
    try:
        second,minute,hour = (bench.ram[a] for a in (0xcc2,0xcc3,0xcc4))
        if not (0 <= second < 60 and 0 <= minute < 60 and 0 <= hour < 24):
            raise RuntimeError('Host clock encountered invalid native clock fields')
        total = second + minute*60 + hour*3600
        pulse = int((total % 60)+seconds >= 60)
        total = (total+seconds) % 86400
        bench.ram.update({0xcc2:total%60,0xcc3:total//60%60,0xcc4:total//3600,0xcc7:pulse})
        # The prefix owns both pets' minute processing and the hidden resolver.
        # UI owns the foreground resolver. Do not run either a second time.
        bench.execute(entry)
        if bench.ram[0xdab]&0x8000:
            raise RuntimeError('Native dual-pet context reported a fatal condition')
        bench.keys(held,long=long)
        bench.ram[0xcc7]=0
        bench.host_clock_last={'mode':'explicit host 1x', 'seconds':seconds,
                               'minute_pulse':pulse,'native_prefix':f'{entry:06X}'}
    except Exception:
        bench.ram,bench.virtual_flash,bench.previous_keys = saved_ram,saved_flash,saved_keys
        raise
