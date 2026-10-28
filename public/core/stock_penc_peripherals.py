# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Pinned stock peripheral boundaries and read-only output settings.

Audio200050..200111 and all24 decoded note/duration sequences match the admitted
R18 frontend. The sensor consumer is byte-identical at201D39; setup/teardown
only relocate their hardware-helper calls. Host shake pulses remain a sensor
source approximation. Physical audio gain, backlight, IRQs and links are not
emulated. The original settings handlers own preview, save and cancellation.
"""
import hashlib

FIRMWARE_SHA256 = 'a21e573ba40741603b8b4068817c789c625196ab5e53ddb188b1f57c63c612a1'
MOTION_SETUP, MOTION_CONSUMER, MOTION_TEARDOWN = 0x201c2b, 0x201d39, 0x201d7d
MOTION_SIGNATURES = (
    (MOTION_SETUP, 0x201ca1, '14b9f5824018d0c2c93070fd56714486eff97a0627fee4b62651d0bc7ae63c95'),
    (MOTION_CONSUMER, 0x201d7d, 'd0875163bdc59798c9ca51e0d09999a0a9ae2374784b5989404078363ad3c22d'),
    (MOTION_TEARDOWN, 0x201da8, '4df37bb4fd9ea9b9b9af3a6ca8249645a51e4bcd95c052fb4a45bc8ec73ce2de'),
)
SIGNATURES = MOTION_SIGNATURES + (
    (0x200050, 0x200111, 'b73ada5c59b03a23bc686a5211297b3f2089e95fff4a758839d143e2684121b7'),
    (0x20378c, 0x203792, 'cf9c3f4d50391dea72a82dfcd123cc4dd364fa76758dcaf93e37824ea832da1c'),
    (0x2039d9, 0x2039ed, '252b39279de295a863658867dda9c4e694dd6dfb2ef94c584f0b74080f7a9452'),
    (0x209e39, 0x20a09b, '21e18d0f7d8a710d91d075089c0b25dd3fabae36acc43d583955453c488fc371'),
    (0x20a17a, 0x20a2f7, '20521ea970e3601b1e3671d3812578e6b80e65cb332920cdde910f25266a4a77'),
    (0x200e46, 0x200f90, '2b493ceec78e53967f88b2add22c7c9d38c7c8434d5dc9e6bca89fa4783808c4'),
)
_last_code = None
_last_supported = False


def supports(code):
    global _last_code, _last_supported
    if type(code) is not bytes:
        return False
    if code is _last_code:
        return _last_supported
    admitted = (len(code) == 0x800000 and hashlib.sha256(code).hexdigest() == FIRMWARE_SHA256
                and all(hashlib.sha256(code[2*(a-0x200000):2*(z-0x200000)]).hexdigest() == sha
                        for a, z, sha in SIGNATURES))
    _last_code, _last_supported = code, admitted
    return admitted


def settings(cpu):
    result = {'supported': False, 'volume_level': None, 'volume_valid': False,
              'brightness_level': None, 'brightness_valid': False, 'brightness_preview': False}
    if not supports(cpu.code):
        return result
    m = cpu.mem
    # Native200E46 substate2 dispatches209E39. Its entry copies0825 into086B;
    # C9E=C9F means that entry has run, so the preview word is initialized.
    preview = m.get(0xc9c) == 23 and m.get(0xc9e) == m.get(0xc9f) == 2
    volume, brightness = m.get(0xcac), m.get(0x86b if preview else 0x825)
    valid_volume = type(volume) is int and 0 <= volume <= 2
    valid_brightness = type(brightness) is int and 1 <= brightness <= 5
    result.update(supported=True, volume_level=volume if valid_volume else None,
                  volume_valid=valid_volume, brightness_level=brightness if valid_brightness else None,
                  brightness_valid=valid_brightness, brightness_preview=preview)
    return result


def motion_metadata(cpu):
    admitted = supports(cpu.code)
    # CA0=2 is set by the native sensor setup and cleared by native teardown.
    # The machine consumes a host pulse only at201D39; D41 remains native-owned.
    return {'motion_supported': admitted,
            'motion_ready': bool(admitted and cpu.mem.get(0xca0) == 2),
            'motion_count': cpu.mem.get(0xd41, 0) if admitted else 0}
