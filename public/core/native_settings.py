# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Read native sound/brightness settings and consume one known display output.

The BIN owns all settings, preview, commit, cancel and save behavior. This
module never repairs RAM, initializes defaults, changes game state, or stores
MMIO in the save snapshot. Browser gain/luminance mappings are approximations;
physical audio gain and backlight behavior have not been measured.
"""
import hashlib

FIRMWARE_SHA256 = frozenset((
    '78a066bf272712aee1bf1868522dbcccbca0ee6586963940bdc61ca111c4809d',
    '16e635693650ee76dbae80b8d831a1b0557d5aafa04f0858e673f7e272cf6981',
    '3cf1d684b408da7e6917eb198798eb1f25ef2e4cfed347074f988995591c7191',
    '188d650f63b8bf694b1b8f7904a23089f6308f9f9774c2f608c9fdf463d7d772',
    'aa7227c3f5cc5bfd459352ffc936269e1f61b8ab62d6e19f6564cf39f933d204',
))
SIGNATURES = (
    (0x200050, 0x200109, '7dc6f900aef5b3c220f15acb6514f22b5d455304040032214beb6a5e7d44ad85'),
    (0x2096d3, 0x209841, '64839c4e5d95bfd9ae6b45549313727cd52d9ff17cfbb749e86ba701b16c4ff9'),
    (0x207055, 0x207077, '1e3307aeb5cd47937555d6a02c1762c098faeee52f5f14e3b26f0f1be21e065e'),
    (0x206eab, 0x20700f, '401754907c79d459620da2d5e7c75bda49263e76566476e47f7f45a47029acda'),
    (0x209392, 0x2095f4, '32429f23486e847358d4e17ad65908a957d416398fdaafc6244f37969ea3a042'),
    (0x203706, 0x20370c, 'cf9c3f4d50391dea72a82dfcd123cc4dd364fa76758dcaf93e37824ea832da1c'),
    (0x203953, 0x203967, '823a1668d7d4e4473f8cd2c670df7a4ff15a6c6c2fa189e8757609d47219c095'),
    (0x20285b, 0x202865, '329bff4439bddc214d73f667b1b849984230d390017437c4a3d1c3dca8e5e30c'),
    (0x206023, 0x206028, 'bc01e8d3eda03d11974f57b12d7cedaa62e474ac80bfc7b8e40c5f141a7064ee'),
    (0x20626f, 0x206282, '23dff87c39840206c690681e7b4190a41ee0a79b15b3f638d243a6f574635792'),
)
# Native203706 table, OR0100 by203953. Index0 is a known bounded output,
# but is not one of the valid user brightness settings1..5.
BRIGHTNESS_WRITES = (0x1fe, 0x1a6, 0x17d, 0x153, 0x12b, 0x100)
_last_code = None
_last_supported = False


def supports(code):
    """Admit exact known releases; only immutable bytes can be cached safely."""
    global _last_code, _last_supported
    if type(code) is not bytes:
        return False
    if code is _last_code:
        return _last_supported
    admitted = (len(code) == 0x800000 and hashlib.sha256(code).hexdigest() in FIRMWARE_SHA256
        and all(hashlib.sha256(code[2*(a-0x200000):2*(z-0x200000)]).hexdigest() == digest
                for a, z, digest in SIGNATURES))
    _last_code, _last_supported = code, admitted
    return admitted


def handles_write(cpu, address, value):
    """Consume only203953's exact MMIO output; every other write stays strict.

    CPU.pc already points past the store instruction. The unchanged helper's
    stack argument and result must match its admitted table. No peripheral
    RAM entry is added, so the original snapshot format remains unchanged.
    """
    if (address != 0x3022 or type(value) is not int or cpu.pc != 0x203966
            or not cpu.allow_adapters or not supports(cpu.code)):
        return False
    level = cpu.mem.get((cpu.r[5] + 3) & 0xffff)
    if type(level) is not int or not 0 <= level < len(BRIGHTNESS_WRITES):
        return False
    if value != BRIGHTNESS_WRITES[level]:
        return False
    cpu.adapters.append({'target': '003022',
        'kind': 'native brightness output observed; no hardware backlight emulation',
        'level': level, 'value': value})
    return True


def metadata(bench):
    """Return host-readable settings without changing any native/saved state.

    CAC0/1/2 is mute/small/loud. CC0 is a native sound-start lock and is not
    substituted for volume: native20007B can intentionally play with CC0=1.
    BRIGHT uses086B only after its native entry initialized that page. Invalid
    old-demo brightness0 remains explicitly unknown rather than repaired.
    """
    result = {'supported': False, 'volume_level': None, 'volume_valid': False,
              'brightness_level': None, 'brightness_valid': False,
              'brightness_preview': False}
    if bench is None or not supports(bench.code):
        return result
    m = bench.ram
    volume = m.get(0xcac)
    preview = m.get(0xc9c) == 23 and m.get(0xc9e) == m.get(0xc9f) == 2
    brightness = m.get(0x86b if preview else 0x825)
    volume_valid = type(volume) is int and 0 <= volume <= 2
    brightness_valid = type(brightness) is int and 1 <= brightness <= 5
    result.update({'supported': True,
                   'volume_level': volume if volume_valid else None,
                   'volume_valid': volume_valid,
                   'brightness_level': brightness if brightness_valid else None,
                   'brightness_valid': brightness_valid,
                   'brightness_preview': preview})
    return result
