# SPDX-License-Identifier: GPL-3.0-or-later
"""R23 host custody policy with native minute, sleep and evolution settlement.

Custody feeds, cleans and turns off bedtime lights without editing historical
care/training/battle counters. Existing illness, injury and death stop custody.
The immutable firmware decides growth, routes, stage resets and album commits.
Between events, admitted countdown arithmetic stops before zero, daily age and
each species' sleep/wake edge. Every boundary still runs native code; no route,
sleep transition or growth outcome is computed by the host.
Animation-only waits use R23's own phase skip and the existing host sound clock.
This is an explicit host policy, not hardware RTC or feeding-UI emulation.
"""
import hashlib
import math
import time

import audio_bridge
import audio_completion
import native_connector
from away_bridge import _checkpoint
from host_clock import native_frame

PIN = '0c7953432d89c924221ee8b30054a25fd7c954ec35565b32bd499a5ac2daf882'
CONTEXT = tuple(range(0x826, 0x838)) + tuple(range(0xcf4, 0xd07))
_last_code = None
_last_supported = False


def supports(bench):
    global _last_code, _last_supported
    code = getattr(bench, 'code', None)
    if type(code) is not bytes:
        return False
    if code is not _last_code:
        _last_code = code
        _last_supported = len(code) == 0x800000 and hashlib.sha256(code).hexdigest() == PIN
    return (_last_supported and getattr(bench, 'entries', {}).get('input_home') == 0x2005e9
            and isinstance(getattr(bench, 'r8_time', None), dict)
            and bench.r8_time.get('tick_entry') == 0x2da400
            and bench.r8_time.get('frame_entry') == 0x2dae00)


def _restore(bench, checkpoint):
    saved, sound = checkpoint
    bench.__dict__.clear()
    bench.__dict__.update(saved)
    audio_completion.clock.__dict__.clear()
    audio_completion.clock.__dict__.update(sound)


def _reason(bench):
    if not supports(bench): return 'unsupported-custody-firmware'
    m = bench.ram
    if native_connector.cable.connected or native_connector.cable.finishing:
        return 'connected-native-cable'
    if bench.previous_keys or m.get(0x81c,0) or m.get(0x820,0) or m.get(0x3000)!=65535:
        return 'input-still-held'
    if m.get(0xdab,0)&0x8000: return 'native-context-fatal'
    if m.get(0xdad,0): return 'native-action-pending'
    if m.get(0xc9c)!=4: return 'native-state-'+str(m.get(0xc9c))
    if m.get(0xc9e) not in (0,2) or m.get(0xcf3,0): return 'home-selection-or-scroll'
    if not all(type(m.get(a)) is int and 0<=m[a]<limit for a,limit in ((0xcc2,60),(0xcc3,60),(0xcc4,24))):
        return 'invalid-native-clock'
    return None


def _select(bench, owner):
    if bench.execute(0x2d1700, register1=owner)!=1:
        raise RuntimeError('native-owner-selection-failed')


def _owners(bench):
    return (0,1) if bench.ram[0xdab]&0x40 else (0,)


def _health(bench):
    m = bench.ram
    if not 0<=m[0x826]<312 or m[0xd04] not in (0,1,2):
        raise RuntimeError('invalid-native-pet-context')
    if m[0x827]&0x30: raise RuntimeError('preexisting-death-or-terminal')
    if m[0x827]&1: raise RuntimeError('unhatched-pet')
    if m[0xcf4]&3 or m[0xd00]!=65535 or m[0xd01]!=65535:
        raise RuntimeError('preexisting-illness-or-injury')


def _care(bench):
    """The only custody policy writes; history and growth fields stay native."""
    m = bench.ram
    _health(bench)
    if m[0x827]&0x40: return
    before = tuple(m[a] for a in CONTEXT)
    m[0xcf5] = m[0xcf6] = 4
    m[0xcfd] = m[0xcfe] = m[0xcff] = 65535
    bedtime = bench.execute(0x210e61) if bench.stat(m[0x826],1)>0 else 0
    m = bench.ram
    if m[0xd04] in (1,2) or bedtime: m[0xd06]=0
    m[0xcf9]=0
    if m[0xcfc]==65535:
        m[0xcfc]=bench.stat(m[0x826],11)//(2 if m[0x836]==65535 else 1)
    if before!=tuple(m[a] for a in CONTEXT): m[0x85d]=1


def _prepare(bench, resolve=False):
    owner = bench.ram[0xdab]&1
    pets=[]
    for slot in _owners(bench):
        _select(bench,slot)
        _care(bench)
        if resolve and not bench.ram[0x827]&0x73:
            if bench.ram[0xcf4]&4: bench.execute(0x2d1f40)
            bench.execute(0x210b53)
            if bench.ram[0xcf4]&4: bench.execute(0x2d1f40)
        _health(bench)
        pets.append({a:bench.ram[a] for a in CONTEXT})
    _select(bench,owner)
    return pets


def _settle(bench, pets=None):
    """Native HOME dispatch, native phase skip, native species/album/save commit."""
    frames=0
    for _ in range(2000):
        if pets is None:pets=_prepare(bench)
        if bench.ram[0xc9c]==4 and all(not p[0x827]&2 for p in pets):
            # Evolution may return with its animation substate. A true HOME
            # entry executes once to rebuild and normalize that state.
            if bench.ram[0xc9d]==4 and bench.ram[0xc9e] in (0,2): return frames
        m=bench.ram
        if m[0xc9c] not in (4,24,36): raise RuntimeError('unsupported-native-event-'+str(m[0xc9c]))
        if m[0xc9c]==4 and 0<m.get(0xc9a,0)<0x42a: m[0xc9a]=0x42a
        skip=(m[0xc9c]==24 and m[0xc9d]==24 and m[0xc9e]==m[0xc9f])
        audio_completion.clock.begin(bench.code,elapsed_ms=5000,speed=2)
        bench.previous_keys=set()
        native_frame(bench,{'B'} if skip else set(),seconds=0)
        bench.sample_keys(set())
        bench.previous_keys=set()
        audio_completion.clock.commit(bench)
        frames+=1
        pets=None
    raise RuntimeError('native-event-settlement-limit')


def _clock(bench, seconds):
    m=bench.ram
    total=(m[0xcc4]*3600+m[0xcc3]*60+m[0xcc2]+seconds)%86400
    m.update({0xcc4:total//3600,0xcc3:total//60%60,0xcc2:total%60,0xcc7:0})
    if m.get(0xca1)==1:
        # A restored request first needs the existing sound decoder to recover
        # its duration. Then charge only this committed offline interval. Stop
        # once complete or unknown, rather than iterating over the entire gap.
        clock=audio_completion.clock
        clock.begin(bench.code,elapsed_ms=0,speed=2)
        clock.commit(bench)
        elapsed=seconds*1000
        while bench.ram.get(0xca1)==1 and clock.remaining is not None and elapsed:
            part=min(5000,elapsed)
            clock.begin(bench.code,elapsed_ms=part,speed=2)
            clock.commit(bench)
            elapsed-=part


def _span(bench, pets, remaining):
    """Strictly interior minutes: no timer/age/sleep edge may be crossed."""
    if bench.ram[0xcc2]!=0:return 0
    limit=remaining//60
    now=bench.ram[0xcc4]*60+bench.ram[0xcc3]
    for p in pets:
        if p[0x827]&0x40:continue  # Native cold freezes this entire context.
        if p[0x827]&0x33 or p[0xcf4]&7 or p[0xd04] not in (0,2):return 0
        limit=min(limit,1439-p[0x837])
        timers=[0x836]
        if p[0xd04]!=2:
            # CFA/CFB do not have the FFFF sentinel used by other timers.
            limit=min(limit,p[0xcfa]-1,p[0xcfb]-1)
            timers.append(0xcfc)
        else:timers.append(0xd03)
        for address in timers:
            if p[address]!=65535:limit=min(limit,p[address]-1)
        for hfield,mfield in ((5,6),(7,8)):
            hour,minute=bench.stat(p[0x826],hfield),bench.stat(p[0x826],mfield)
            if not 0<=hour<24 or not 0<=minute<60:return 0
            distance=(hour*60+minute-now)%1440 or 1440
            limit=min(limit,distance-1)
    return max(0,limit)


def _advance_span(bench, minutes):
    """Interior-only equations from hash-admitted native 210918..210AC9."""
    owner=bench.ram[0xdab]&1
    for slot in _owners(bench):
        _select(bench,slot)
        m=bench.ram
        if m[0x827]&0x40:continue
        if m[0x836]!=65535:m[0x836]-=minutes
        m[0x837]+=minutes
        if m[0xd04]!=2:
            m[0xcfa]-=minutes
            m[0xcfb]-=minutes
            if m[0xcfc]!=65535:m[0xcfc]-=minutes
        elif m[0xd03]!=65535:m[0xd03]-=minutes
        m[0x85d]=1
    _select(bench,owner)
    bench.ram[0xdab]|=0x30
    _clock(bench,minutes*60)


def catch_up(bench, seconds, budget_ms=35):
    if type(seconds) is not int or not 0<=seconds<=2**31-1:
        raise ValueError('Custody seconds must be a nonnegative bounded integer')
    if type(budget_ms) not in (int,float) or not math.isfinite(budget_ms) or not 0<budget_ms<=5000:
        raise ValueError('Custody budget must be finite positive milliseconds <=5000')
    result={'processed_seconds':0,'remaining_seconds':seconds,'blocked_reason':None,
            'completed_frames':0,'native_ms':0.0,'native_minutes':0,'batched_minutes':0}
    if not seconds:return result
    reason=_reason(bench)
    if reason:result['blocked_reason']=reason;return result
    audio_bridge.end(discard=True)
    started=time.perf_counter()
    first=True
    while result['remaining_seconds']:
        if result['processed_seconds'] and (time.perf_counter()-started)*1000>=budget_ms:break
        checkpoint=_checkpoint(bench)
        try:
            pets=_prepare(bench,resolve=first)
            frames=_settle(bench,pets)
            if frames:pets=_prepare(bench)
            span=_span(bench,pets,result['remaining_seconds'])
            minute=0
            if span:
                step=span*60
                _advance_span(bench,span)
            else:
                step=min(result['remaining_seconds'],60-bench.ram[0xcc2])
                _clock(bench,step)
                minute=int(bench.ram[0xcc2]==0)
                if minute:
                    _prepare(bench)
                    bench.execute(0x2da800)
                    pets=_prepare(bench)
                    frames+=_settle(bench,pets)
            reason=_reason(bench)
            if reason:raise RuntimeError(reason)
        except Exception as exc:
            _restore(bench,checkpoint)
            result['blocked_reason']='native-error: '+str(exc)
            break
        first=False
        result['processed_seconds']+=step
        result['remaining_seconds']-=step
        result['completed_frames']+=frames
        result['native_minutes']+=minute
        result['batched_minutes']+=span
    result['native_ms']=round((time.perf_counter()-started)*1000,3)
    return result
