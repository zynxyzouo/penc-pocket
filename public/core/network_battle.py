# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Read-only native battle/Jogress previews for a canonical two-player room.

This module does not communicate, settle battles, evolve a pet, or save anything.
Both clients must receive exactly the same ordered players, shakes and RNG words.
All native instructions run in a private copy of the current Bench/CPU state.
"""
import copy
import hashlib
import json
import re
import struct

from cpu import CPU
import web_adapter as native


PROTO_VERSION = 1
PEER_FIELDS = ('firmware_sha256', 'rules_sha256', 'species', 'strength', 'bonus_a', 'bonus_b')
RULES_SHA256 = '1e38806decf1a72c289205324451aee7afd45b7c95b5892a3505a512be8d0948'
JOGRESS_SHA256 = '9a27e5e129f3c618cdc5cc970acdf0bfbbeda568424527bde6f715dffb93288a'
ADMISSION_SHA256 = 'f0baceca9e7f94c251800561696307a06236a43010dcc4341777c2dc0882629f'
# File byte ranges, end exclusive. Include data tables and native dependencies,
# so identical entry addresses alone never admit different game rules.
BATTLE_RANGES = ((0x5b6,0x68e), (0x1410e,0x14bd0), (0x209f0,0x20ba8),
                 (0xaec6,0xaf2a), (0xb1f2,0xb230), (0x2b000,0x2dbe0))
ADMISSION_RANGES = ((0x1a0000,0x1a3000), (0x1e7200,0x1e7a00))
JOGRESS_RANGES = ((0xd5c,0xd60), (0xe40,0xe44), (0x49000,0x49086),
                  (0x2a800,0x2a8c2), (0x49110,0x49a0c), (0x300c0,0x30a80),
                  (0x39ee0,0x3a150), (0x3a2e8,0x3a558), (0x2b000,0x2dbe0))
CONTEXT = tuple(range(0x826,0x838)) + tuple(range(0xcf4,0xd07))
HEX_SHA = re.compile(r'^[0-9a-f]{64}$')


def _fingerprint(code, ranges):
    return hashlib.sha256(b''.join(code[start:end] for start,end in ranges)).hexdigest()


def _world():
    if native.bench is None:
        raise ValueError('請先載入 BIN。')
    if _fingerprint(native.bench.code, BATTLE_RANGES) != RULES_SHA256:
        raise ValueError('這份 BIN 的原生對戰規則尚未驗證，無法連線切磋。')
    # Deep-copy mutable diagnostic collections too; Bench.execute updates them.
    return copy.deepcopy(native.bench)


def _integer(value, maximum, label):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('Invalid ' + label)
    return value


def _peer(value):
    if not isinstance(value, dict) or set(value) != set(PEER_FIELDS):
        raise ValueError('Peer must contain exactly the six supported fields')
    for key in ('firmware_sha256', 'rules_sha256'):
        if not isinstance(value[key], str) or not HEX_SHA.fullmatch(value[key]):
            raise ValueError('Invalid peer ' + key)
    if value['rules_sha256'] != RULES_SHA256:
        raise ValueError('雙方的原生對戰規則不相容。')
    _integer(value['species'], 311, 'species')
    _integer(value['strength'], 4, 'strength')
    _integer(value['bonus_a'], 1, 'bonus_a')
    _integer(value['bonus_b'], 1, 'bonus_b')
    return {key:value[key] for key in PEER_FIELDS}


def _players(values):
    if not isinstance(values, list) or len(values) != 2:
        raise ValueError('Exactly two ordered players are required')
    return [_peer(value) for value in values]


def describe():
    """Describe the currently resident/selected L or R pet, never its companion.

    The native dual-training admission is exercised with two isolated copies of
    this selected pet. This reuses its actual hatched/alive/sleep/light/illness
    rules without requiring a second local pet. Sparring requires no DP.
    """
    b = _world()
    if _fingerprint(b.code, ADMISSION_RANGES) != ADMISSION_SHA256:
        raise ValueError('這份 BIN 的原生切磋資格檢查尚未驗證。')
    m = b.ram
    if m.get(0xdab,0) & 0x8000 or m.get(0xdad,0) != 0 or m.get(0xc9c) != 4:
        raise ValueError('請先完成目前操作並回到主畫面，再建立連線。')
    if m[0xdab] & 1 and not m[0xdab] & 0x40:
        raise ValueError('目前選中的怪獸不存在。')
    peer = _peer({'firmware_sha256':b.sha256, 'rules_sha256':RULES_SHA256,
                  'species':m[0x826], 'strength':m[0xcf6],
                  'bonus_a':int(bool(m[0x834])), 'bonus_b':int(bool(m[0x835]))})
    stage = b.execute(0x2104f8, (peer['species'], 1))
    if stage < 2:
        raise ValueError('目前怪獸尚未達到可切磋的成長階段。')
    active = {address:m[address] for address in CONTEXT}
    b.ram[0xdab] = (b.ram[0xdab] & ~1) | 0x40
    if b.execute(0x2d1700, register1=1) != 1:
        raise ValueError('無法建立原生切磋資格檢查。')
    b.ram.update(active)
    if b.execute(0x2d1700, register1=0) != 1 or b.execute(0x2f3900) != 1:
        raise ValueError('目前怪獸不符合原生切磋條件，請確認睡眠、燈光與健康狀態。')
    return peer


def _native_stats(b, peer, shakes):
    b.ram.update({0x826:peer['species'], 0xcf6:peer['strength'],
                  0x834:peer['bonus_a'], 0x835:peer['bonus_b']})
    stage = b.execute(0x2104f8, (peer['species'], 1))
    if not 2 <= stage <= 6:
        raise ValueError('Peer species cannot use the native sparring classifier')
    attribute = b.execute(0x2104f8, (peer['species'], 2)) & 3
    power = b.execute(0x210526)
    bucket = b.execute(0x20a54e, (shakes, stage, attribute))
    row = b.execute(0x20a582, (stage, attribute, bucket))
    if not 0 <= row < 15 or not 0 <= bucket <= 3:
        raise ValueError('Native attack classifier returned an unsupported row')
    return {'power':power, 'stage':stage, 'attribute':attribute, 'bucket':bucket, 'attack_row':row}


class _BattleCPU(CPU):
    """Observe real native damage-table reads; do not reconstruct a winner."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.exchanges = []

    def read(self, address):
        value = super().read(address)
        # CPU.step has advanced PC by one before these two table reads.
        # Both callsites and their table are included in BATTLE_RANGES.
        if 0x20a230 <= address < 0x20a28a and self.pc in (0x20a1e0, 0x20a215):
            self.exchanges.append((0 if self.pc == 0x20a1e0 else 1, value))
        return value


def calculate(payload):
    """Return deterministic native results for canonical room players [A,B]."""
    if not isinstance(payload, dict) or set(payload) != {'players','shakes','seed'}:
        raise ValueError('Battle input must contain players, shakes and seed')
    players = _players(payload['players'])
    shakes, seed = payload['shakes'], payload['seed']
    if not isinstance(shakes, list) or len(shakes) != 2:
        raise ValueError('Exactly two shake counts are required')
    shakes = [_integer(v, 200, 'shake count') for v in shakes]
    if not isinstance(seed, list) or len(seed) != 8:
        raise ValueError('Native RNG requires eight uint16 words')
    seed = [_integer(v, 65535, 'seed word') for v in seed]
    if not any(seed):
        raise ValueError('An all-zero native RNG state is not supported')
    b = _world()
    stats = [_native_stats(b, player, count) for player,count in zip(players,shakes)]
    a, other = stats
    b.ram.update({0xc9c:13, 0xd09:a['power'], 0xd0a:a['attribute'],
                  0xd10:other['power'], 0xd11:other['attribute'], 0xd13:0,
                  0xd1c:a['attack_row'], 0xd14:other['attack_row'], 0xd17:65535, 0xd18:0})
    b.ram.update({0x600+i:value for i,value in enumerate(seed)})
    cpu = _BattleCPU(b.code, b.ram, flash=b.virtual_flash, album_flash=b.virtual_album,
                     local_play=b.r8_local_play is not None)
    cpu.run(0x20a087, budget=500000)
    if cpu.mem[0xd17] not in (0,1) or not 1 <= len(cpu.exchanges) <= 6:
        raise ValueError('Native calculator did not produce a complete match')
    result = {'proto_version':PROTO_VERSION, 'rules_sha256':RULES_SHA256,
              'winner':0 if cpu.mem[0xd17] else 1,
              'rounds':[actor for actor,damage in cpu.exchanges],
              'round_damage':[damage for actor,damage in cpu.exchanges],
              'event_bits':cpu.mem[0xd18], 'native_stats':stats,
              'rng_after':[cpu.mem[0x600+i] for i in range(8)], 'settled':False}
    canonical = {'proto_version':PROTO_VERSION, 'players':players, 'shakes':shakes,
                 'seed':seed, 'result':result}
    result['digest'] = hashlib.sha256(json.dumps(canonical, sort_keys=True,
                                               separators=(',', ':')).encode('utf-8')).hexdigest()
    return result


def preview_jogress(players):
    """Both directional native results only; do not consume or evolve a pet."""
    players = _players(players)
    b = _world()
    if _fingerprint(b.code, JOGRESS_RANGES) != JOGRESS_SHA256:
        raise ValueError('這份 BIN 的原生合體規則尚未驗證。')
    species = [player['species'] for player in players]
    stages = [b.stat(sid,1) for sid in species]
    results = []
    for host,peer in (species, list(reversed(species))):
        if min(stages) <= 2:
            results.append(None)
            continue
        b.ram.update({0x826:host,
                      0xd1d:struct.unpack_from('<H', b.code, 0x39ee0+peer*2)[0],
                      0xd1e:struct.unpack_from('<H', b.code, 0x3a2e8+peer*2)[0],
                      0xd1f:b.stat(peer,2), 0xd20:b.stat(peer,1)})
        result = b.execute(0x2006ae)
        results.append(result if 0 <= result < 312 else None)
    return {'proto_version':PROTO_VERSION, 'rules_sha256':JOGRESS_SHA256,
            'results':results, 'preview_only':True, 'committed':False}
