# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Bounded host sound completion; not an implementation of the missing ROM IRQ.

The audited native start sets CA1=1; native200109 returns exactly CA1. The
original host ROM00578C no-op never completed it, trapping sound-waiting pages.
Only this busy word is completed after the same approximate note duration used
by sound.js. Explicit host elapsed milliseconds advance only on committed native
frames, independent of browser playback/permissions. A restored request is bounded
again, without audible replay. Duration units remain provisional, not ROM timing.
"""
import hashlib
import math
import struct
import audio_bridge as audio

SIGNATURE = 'b73ada5c59b03a23bc686a5211297b3f2089e95fff4a758839d143e2684121b7'

def supports(code):
    return hashlib.sha256(code[0xa0:0x222]).hexdigest() == SIGNATURE

def duration_ms(event):
    # decode_sequence already bounds each word, pair count and total raw duration.
    # Keep the complete admitted sequence and preserve relative note/rest timing.
    return sum(word for _,word in event['notes'])


def duration_frames(event):
    """Compatibility helper for nominal 64 Hz fixtures, not the browser clock."""
    return max(1,math.ceil(duration_ms(event)*64/1000))

class CompletionClock:
    def __init__(self):
        self.clear()

    def clear(self):
        self.code=None
        self.active=False
        self.pending=None
        self.remaining=None
        self.marker=None
        self.speed=1
        self.requested_speed=1
        self.elapsed_ms=0
        self.admitted=False
        self.just_started=False

    def begin(self,code,elapsed_ms=None,speed=1):
        """Stage one frame; explicit elapsed is charged only by commit().

        Browser batches supply elapsed once, then zero for subsequent frames.
        None preserves nominal 64 Hz time for legacy direct-native fixtures.
        """
        if elapsed_ms is None:elapsed_ms=1000/64
        if type(elapsed_ms) not in (int,float) or not math.isfinite(elapsed_ms) or not 0<=elapsed_ms<=5000:
            raise ValueError('Sound elapsed time must be a finite 0..5000 milliseconds')
        if type(speed) not in (int,float) or not math.isfinite(speed) or not 1<=speed<=4:
            raise ValueError('Sound speed must be a finite 1..4 multiplier')
        if self.code is not code:
            self.clear()
            self.code=code
            self.admitted=supports(code)
        self.pending=None
        self.just_started=False
        self.elapsed_ms=elapsed_ms
        self.requested_speed=speed
        self.active=self.admitted

    def observe(self,cpu,target):
        if not self.active or target!=0x2000a9 or cpu.code is not self.code:return
        event=audio.decode_sequence(cpu.code,cpu.read(cpu.r[0]+1))
        if event is not None:self.pending=duration_ms(event)

    def restored_duration(self,ram):
        if ram.get(0xcaa)!=0:return None
        for sound_id in range(audio.SOUND_COUNT):
            low=struct.unpack_from('<H',self.code,audio.TABLE+sound_id*4)[0]
            if ram.get(0xca9)==low*2+2:
                event=audio.decode_sequence(self.code,sound_id)
                return duration_ms(event) if event else None
        return None

    def commit(self,bench):
        if not self.active:return
        self.active=False
        ram=bench.ram
        if ram.get(0xca1)!=1:
            self.remaining=None
            self.marker=None
            return
        marker=(ram.get(0xca9),ram.get(0xcaa))
        if self.pending is not None:
            self.remaining=self.pending/self.requested_speed
            self.marker=marker
            self.just_started=True
        elif self.remaining is None or marker!=self.marker:
            duration=self.restored_duration(ram)
            self.remaining=duration/self.requested_speed if duration is not None else None
            self.marker=marker
            self.just_started=duration is not None
        else:
            self.remaining=self.remaining*self.speed/self.requested_speed-self.elapsed_ms
            if self.remaining<=1e-9:
                ram[0xca1]=0
                self.remaining=None
                self.marker=None
        self.speed=self.requested_speed

    def abort(self):
        self.pending=None
        self.active=False
        self.elapsed_ms=0

clock=CompletionClock()
