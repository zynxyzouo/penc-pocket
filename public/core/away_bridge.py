# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Bounded native HOME care catch-up; no host-computed pet state.

The host supplies RTC seconds, released keys and the existing approximate sound
completion clock. Native tick/prefix/C/UI own hunger, age, sleep and events.
Settled HOME runs one complete native frame per second. Sound and admitted care
animations retain nominal 64 Hz frames. The existing HOME display-awake fixture
is retained; this is not hardware display sleep/wake or full lifecycle emulation.
"""
import hashlib
import math
import time

import audio_bridge
import audio_completion
import native_connector
from host_clock import native_frame

FIRMWARE_SHA256=frozenset((
    '78a066bf272712aee1bf1868522dbcccbca0ee6586963940bdc61ca111c4809d',
    '16e635693650ee76dbae80b8d831a1b0557d5aafa04f0858e673f7e272cf6981',
    '3cf1d684b408da7e6917eb198798eb1f25ef2e4cfed347074f988995591c7191',
    '188d650f63b8bf694b1b8f7904a23089f6308f9f9774c2f608c9fdf463d7d772',
    'aa7227c3f5cc5bfd459352ffc936269e1f61b8ab62d6e19f6564cf39f933d204',
    '0c7953432d89c924221ee8b30054a25fd7c954ec35565b32bd499a5ac2daf882',  # R23; native adapter regions verified unchanged.
))
SIGNATURES=(
    (0x2da400,0x2da800,'0aa58992a35228078f70d298d5fd47850d60611d8889854cbaa713ab67a1b044'),
    (0x2dae00,0x2daf00,'1e1e6c2d3e0b02b81acede56f6ba25ff964a898a2c34a7f46b735a9cb127349d'),
    (0x210918,0x211000,'f93b71ca65c58459c392875f509c406c5afa0f0e4449de404ef3825e7fbe7b7a'),
    (0x2d1800,0x2d2000,'3d096081117305569f023afee705ce613aa047517f2a5ae122053068facdc446'),
    (0x2d1700,0x2d1800,'5b1d1966a7f73434fac10517ec283871e90857576861db4f2600c4e9c3e026d0'),
    (0x206900,0x207000,'0b593d1f2b85ea3dd4db0e8da70fbdebe999f23303259ee29407c5b174db1f2f'),
    (0x2cde00,0x2cdf00,'b8148e90c9a6f9f273a085696dffefec98bb5a39d35f4b055ba9469ef4ef3aa4'),
)
CARE_TRANSIENTS=(24,25,36)
_last_code=None
_last_supported=False


def supports(code):
    """Exact admitted release bytes plus independently pinned care functions."""
    global _last_code,_last_supported
    if type(code)is not bytes:return False
    if code is _last_code:return _last_supported
    valid=(len(code)==0x800000 and hashlib.sha256(code).hexdigest()in FIRMWARE_SHA256
           and all(hashlib.sha256(code[2*(a-0x200000):2*(z-0x200000)]).hexdigest()==sha for a,z,sha in SIGNATURES))
    _last_code,_last_supported=code,valid
    return valid


def _reason(bench):
    if bench is None:return 'no-firmware'
    if not supports(bench.code)or bench.r8_time is None:return 'unsupported-firmware'
    if bench.entries.get('input_home')!=0x2005e9:return 'unsupported-native-entry'
    cable=native_connector.cable
    if cable.connected or cable.finishing:return 'connected-native-cable'
    m=bench.ram
    if bench.previous_keys or m.get(0x81c,0)or m.get(0x820,0)or m.get(0x3000,65535)!=65535:
        return 'input-still-held'
    if m.get(0xdab,0)&0x8000:return 'native-context-fatal'
    if m.get(0xdad,0):return 'native-action-pending'
    main=m.get(0xc9c)
    if main==4:
        if m.get(0xc9e)not in(0,2)or m.get(0xcf3,0):return 'home-selection-or-scroll'
        return None
    if main in CARE_TRANSIENTS and getattr(bench,'_away_transient_owned',False):return None
    return 'native-state-'+str(main)


def safe(bench):
    """Read-only admission, including transient states entered by this adapter."""
    return _reason(bench)is None


def _checkpoint(bench):
    # Native execution replaces trace/call lists and Flash bytes; only RAM,
    # previous_keys and adapters_seen are modified in place across calls.
    saved=dict(bench.__dict__)
    for key in('ram','previous_keys','adapters_seen'):
        if key in saved:saved[key]=saved[key].copy()
    return saved,dict(audio_completion.clock.__dict__)


def _frame(bench,seconds,elapsed_ms):
    m=bench.ram
    if (m.get(0xc9c)==4 and 0<=m.get(0xc9e,99)<=3
            and(m[0xc9e]!=0 or m.get(0xcf3,0)==0)and 0<m.get(0xc9a,0)<0x42a):
        m[0xc9a]=0x42a
    audio_completion.clock.begin(bench.code,elapsed_ms=elapsed_ms,speed=2)
    native_frame(bench,set(),seconds=seconds)
    audio_completion.clock.commit(bench)
    if bench.ram.get(0xc9c)in CARE_TRANSIENTS:
        bench._away_transient_owned=True
    reason=_reason(bench)
    if reason:raise RuntimeError(reason)


def catch_up(bench,seconds,budget_ms=25):
    """Commit whole native seconds under a soft wall-time budget.

    A single second may exceed the budget while an animation runs its 64 frames.
    On failure that entire second, including the sound clock, is restored; prior
    committed seconds stay committed. Remaining time must be retained by the
    caller. No rendering, output audio, peer packets or source BIN writes occur.
    """
    if type(seconds)is not int or not 0<=seconds<=2**31-1:
        raise ValueError('Away seconds must be a nonnegative bounded integer')
    if type(budget_ms)not in(int,float)or not math.isfinite(budget_ms)or not 0<budget_ms<=5000:
        raise ValueError('Away budget must be a finite positive 0..5000 milliseconds')
    result={'processed_seconds':0,'remaining_seconds':seconds,'blocked_reason':None,
            'completed_frames':0,'native_ms':0.0}
    if seconds==0:return result
    reason=_reason(bench)
    if reason:result['blocked_reason']=reason;return result
    # Output capture is deliberately suppressed; only native sound completion
    # continues. This does not clear the native CA1 busy word or its timer.
    audio_bridge.end(discard=True)
    started=time.perf_counter()
    while result['remaining_seconds']:
        if result['processed_seconds']and(time.perf_counter()-started)*1000>=budget_ms:break
        reason=_reason(bench)
        if reason:result['blocked_reason']=reason;break
        saved,sound=_checkpoint(bench)
        frames=0
        try:
            slow=bench.ram.get(0xc9c)!=4 or bench.ram.get(0xca1)==1
            _frame(bench,1,1000/64 if slow else 1000);frames=1
            slow=slow or bench.ram.get(0xc9c)!=4 or bench.ram.get(0xca1)==1
            if slow:
                for _ in range(63):_frame(bench,0,1000/64);frames+=1
            if bench.ram.get(0xc9c)==4:bench._away_transient_owned=False
        except Exception as exc:
            bench.__dict__.clear();bench.__dict__.update(saved)
            audio_completion.clock.__dict__.clear();audio_completion.clock.__dict__.update(sound)
            result['blocked_reason']='native-error: '+str(exc)
            break
        result['processed_seconds']+=1;result['remaining_seconds']-=1
        result['completed_frames']+=frames
    result['native_ms']=round((time.perf_counter()-started)*1000,3)
    return result
