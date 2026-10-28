# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Observe accepted native sound requests; never emulate IRQs or write RAM.

The flash sequence structure is known from 2000A9 and the selected BIN.
Pitch conversion, duration units, code74 as rest, waveform and physical gain
are NOT decoded internal-ROM behavior. Consumers must label playback approximate.
Call begin(code) only for a live frame batch, capture(cpu,target) before
CPU.call, then end() after successful execution or end(discard=True) on failure.
Load/restore/release/snapshot must not start a batch or replay pending RAM.
"""
import hashlib
import struct


FRONT_START = 0x200050
FRONT_END = 0x200109
FRONT_SHA256 = '7dc6f900aef5b3c220f15acb6514f22b5d455304040032214beb6a5e7d44ad85'
TABLE = 0x40000
SOUND_COUNT = 24
MAX_EVENTS = 8
MAX_NOTES = 128
MAX_DURATION_WORD = 4096
MAX_TOTAL_DURATION_WORDS = 32768
# Values observed in the 24 hash-admitted R18 sequences. Do not invent notes
# for unknown codes; leave 74 raw for the approximate browser synthesizer.
NOTE_CODES = frozenset((29,31,34,36,38,40,41,43,45,46,47,48,49,50,51,
                       53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,
                       68,69,70,72,73,74))
_active_code = None
_events = []


def supports(code):
    if not isinstance(code, (bytes, bytearray)) or len(code) < TABLE + SOUND_COUNT*4:
        return False
    return hashlib.sha256(code[2*(FRONT_START-0x200000):2*(FRONT_END-0x200000)]).hexdigest() == FRONT_SHA256


def decode_sequence(code, sound_id):
    """Return bounded raw pairs, or None when admission/data is unknown."""
    if type(sound_id) is not int or not 0 <= sound_id < SOUND_COUNT or not supports(code):
        return None
    low, high = struct.unpack_from('<HH', code, TABLE + sound_id*4)
    # Native2000A9 uses low*2 as SPI byte offset; the known table's high word
    # is CPU window20. No arbitrary pointer chasing or peripheral access.
    if high != 0x20:
        return None
    start = low*2
    if not 0 < start < TABLE-4:
        return None
    limit = min(start + 4*(MAX_NOTES+1), TABLE, len(code))
    if sound_id + 1 < SOUND_COUNT:
        following, next_high = struct.unpack_from('<HH', code, TABLE + (sound_id+1)*4)
        if next_high != 0x20 or not start+4 <= following*2 <= TABLE:
            return None
        limit = min(limit, following*2)
    if struct.unpack_from('<H', code, start)[0] != 1:
        return None
    notes, total = [], 0
    offset = start + 2
    while offset + 2 <= limit:
        note = struct.unpack_from('<H', code, offset)[0]
        if note == 0xffff:
            if not notes:
                return None
            if sound_id+1 < SOUND_COUNT and offset+2 != following*2:
                return None
            return {'id':sound_id, 'notes':notes, 'approximate':True}
        if len(notes) >= MAX_NOTES or offset+4 > limit or note not in NOTE_CODES:
            return None
        duration = struct.unpack_from('<H', code, offset+2)[0]
        total += duration
        if not 0 < duration <= MAX_DURATION_WORD or total > MAX_TOTAL_DURATION_WORDS:
            return None
        notes.append([note, duration])
        offset += 4
    return None


def begin(code):
    """Start a fresh, nonpersistent observation batch; erase any stale queue."""
    global _active_code, _events
    _events = []
    _active_code = code if supports(code) else None
    return _active_code is not None


def capture(cpu, target):
    """Observe 2000A9's argument before CALL pushes its return address.

    200050/200091 gating already ran, so one 2000A9 means one accepted
    request. Do not use repeated00578C pending-sound polling as an event.
    Observation must never change native execution or fail an otherwise valid
    frame. Foreign CPU instances and malformed/unknown sequences stay silent.
    """
    if target != 0x2000a9 or _active_code is None or len(_events) >= MAX_EVENTS:
        return False
    try:
        if cpu.code is not _active_code:
            return False
        event = decode_sequence(cpu.code, cpu.read(cpu.r[0]+1))
        if event is None:
            return False
        _events.append(event)
        return True
    except (AttributeError, IndexError, TypeError, ValueError, RuntimeError, struct.error):
        return False


def end(discard=False):
    """Commit successful events once, or discard a failed/abandoned batch."""
    global _active_code, _events
    result = [] if discard else _events
    _active_code, _events = None, []
    return result
