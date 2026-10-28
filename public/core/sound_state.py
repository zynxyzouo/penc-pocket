# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Validated host sound-completion remainder for additive web snapshots.

Native CA1/CA9/CAA remain authoritative. The record preserves only the host
completion clock already in progress; it never starts sound or changes RAM.
Old snapshots without a record retain the existing decoded-duration fallback.
"""
import hashlib
import math

import audio_completion

FIRMWARE_SHA256=frozenset((
    '78a066bf272712aee1bf1868522dbcccbca0ee6586963940bdc61ca111c4809d',
    '16e635693650ee76dbae80b8d831a1b0557d5aafa04f0858e673f7e272cf6981',
    '3cf1d684b408da7e6917eb198798eb1f25ef2e4cfed347074f988995591c7191',
    '188d650f63b8bf694b1b8f7904a23089f6308f9f9774c2f608c9fdf463d7d772',
    'aa7227c3f5cc5bfd459352ffc936269e1f61b8ab62d6e19f6564cf39f933d204',
    '0c7953432d89c924221ee8b30054a25fd7c954ec35565b32bd499a5ac2daf882',  # R23; native adapter regions verified unchanged.
))
_last_code=None
_last_supported=False


def _supported(code):
    global _last_code,_last_supported
    if type(code)is not bytes:return False
    if code is _last_code:return _last_supported
    valid=(len(code)==0x800000 and hashlib.sha256(code).hexdigest()in FIRMWARE_SHA256
           and audio_completion.supports(code))
    _last_code,_last_supported=code,valid
    return valid


def _validate(bench,payload):
    if (not isinstance(payload,dict)
            or set(payload)!= {'version','remaining_ms','marker','speed'}
            or type(payload.get('version'))is not int or payload['version']!=1):
        raise ValueError('Invalid sound-completion snapshot format')
    remaining,speed,marker=payload['remaining_ms'],payload['speed'],payload['marker']
    # Python JSON integers are unbounded. Do not convert an arbitrary integer
    # to float merely to test finiteness; the native duration bound rejects it.
    finite=lambda value:type(value)is int or(type(value)is float and math.isfinite(value))
    if (not finite(remaining)or remaining<=0
            or not finite(speed)or not 1<=speed<=4
            or type(marker)is not list or len(marker)!=2
            or any(type(v)is not int or not 0<=v<=65535 for v in marker)):
        raise ValueError('Invalid sound-completion values')
    if bench is None or not _supported(bench.code):
        raise ValueError('Unsupported sound-completion firmware')
    ram=bench.ram
    if ram.get(0xca1)!=1 or marker!=[ram.get(0xca9),ram.get(0xcaa)]:
        raise ValueError('Sound-completion record does not match native sound')
    # A separate reader avoids touching the live clock before all validation
    # succeeds. Its decoder uses the actual native sound table and sequence.
    reader=audio_completion.CompletionClock()
    reader.code=bench.code
    duration=reader.restored_duration(ram)
    if duration is None or duration<=0 or remaining>duration/speed:
        raise ValueError('Sound-completion remainder exceeds native sequence')
    return remaining,speed,tuple(marker)


def snapshot(bench):
    """Read-only record for an owned, committed, still-busy sound clock."""
    clock=audio_completion.clock
    if (bench is None or clock.code is not bench.code or not clock.admitted
            or clock.active or clock.remaining is None or clock.marker is None):
        return None
    try:
        payload={'version':1,'remaining_ms':clock.remaining,
                 'marker':list(clock.marker),'speed':clock.speed}
        _validate(bench,payload)
    except (ValueError,TypeError):return None
    return payload


def restore(bench,payload):
    """Validate before mutation; a missing legacy record only clears the clock."""
    clock=audio_completion.clock
    if payload is None:
        clock.clear()
        return
    remaining,speed,marker=_validate(bench,payload)
    clock.clear()
    clock.code=bench.code
    clock.admitted=True
    clock.remaining=remaining
    clock.marker=marker
    clock.speed=speed
    clock.requested_speed=speed
