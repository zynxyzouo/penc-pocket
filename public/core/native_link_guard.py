# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Return unsupported physical-connector routes via the real native C handler.

No serial status, successful handshake, battle result or pet field is fabricated.
This also recovers snapshots saved by earlier previews while waiting for hardware.
"""
import copy
import hashlib

PHYSICAL_MAINS=(0x0f,0x10,0x13)
CANCEL_SHA='82da8b739e08f640c862d13bfdbff8751d771aaee50a62c94f22001bddff7773'
HOME_ENTER=0x2d8a02
HOME_ENTER_SHA='fe534d1e1431a0d800c2bac3c0a36cc91e1be456b847d79e3f91c33cf6795b44'
CONTEXT=tuple(range(0x826,0x838))+tuple(range(0xcf4,0xd07))
NOTICE='尚未接通另一支手機，已返回主畫面。請先在 Menu「配對另一支手機」，接通後再從遊戲裡選擇對戰或合體。'

def pending(bench):
    return bench.ram.get(0xc9c) in PHYSICAL_MAINS

def protected(bench):
    b=copy.deepcopy(bench)
    pets=[]
    for owner in (0,1):
        if owner and not b.ram.get(0xdab,0)&0x40:continue
        if b.execute(0x2d1700,register1=owner)!=1:
            raise ValueError('無法核對連線角色，原進度保留。')
        pets.append(tuple(b.ram[a] for a in CONTEXT))
    return tuple(pets),bytes(b.virtual_flash),bytes(b.virtual_album)

def recover(bench):
    if not pending(bench):return None
    if (hashlib.sha256(bench.code[0x3e6c:0x41ec]).hexdigest()!=CANCEL_SHA
            or hashlib.sha256(bench.code[0x1b1404:0x1b150a]).hexdigest()!=HOME_ENTER_SHA):
        raise ValueError('這個版本的實體連線返回路徑尚未核對，原進度保留。')
    m=bench.ram
    if m.get(0xdab,0)&0x8000 or (m.get(0xdad,0) and m[0xdad]&0xf000!=0xa000):
        raise ValueError('連線角色狀態不一致，原進度保留。')
    if m.get(0xca0) not in (0,2):
        raise ValueError('此快照包含尚未支援的實體連線狀態，原進度保留。')
    if m.get(0xdad,0):
        token=m[0xdad]
        selected,original=(token>>11)&1,(token>>10)&1
        if (selected!=(m[0xdab]&1) or (token&255)!=((m[0xdac]>>(8*selected))&255)
                or ((selected or original) and not m[0xdab]&0x40)):
            raise ValueError('連線角色已變更，無法套用舊連線狀態；原進度保留。')
    original=copy.deepcopy(bench.__dict__)
    try:
        before=protected(bench)
        if m.get(0xca0)==2:
            bench.execute(0x201d1e)
        # At most one initialization pass, then the handler's genuine C branch.
        for _ in range(2):
            bench.sample_keys({'C'})
            bench.execute(0x201f36)
            if bench.ram[0xc9c]==4:break
        if bench.ram[0xc9c]!=4:
            raise ValueError('原生返回流程尚未完成，原進度保留。')
        bench.previous_keys=set()
        bench.sample_keys(set())
        # Only the complete native ownership-return function is needed here.
        # A full HOME frame also autosaves dirty virtual Flash; leave that for
        # normal resumed gameplay, outside this strictly preserving transaction.
        bench.execute(HOME_ENTER)
        if bench.ram[0xdad]!=0 or bench.ram[0xdab]&0x8000 or protected(bench)!=before:
            raise ValueError('返回後角色核對未通過，原進度保留。')
        return NOTICE
    except Exception:
        bench.__dict__.clear()
        bench.__dict__.update(original)
        raise
