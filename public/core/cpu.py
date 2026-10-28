# SPDX-License-Identifier: GPL-3.0-or-later
# Portions adapted from MAME 0.289 unSP, upstream GPL-2.0-or-later.
# Upstream copyright holders: Segher Boessenkool, Ryan Holtz, David Haywood.
# Copyright 2008-2017 Segher Boessenkool.
# Source: https://github.com/mamedev/mame/tree/mame0289/src/devices/cpu/unsp
# Modified for PenC Pocket: Python instruction implementation and host adapters.
# Release/license notice updated: 2026-10-28. See LICENSE and MODIFICATIONS.md.
"""Strict selected unSP CPU, not a full GPCE4064B hardware emulator.

Instruction semantics derive from the local source-grounded reference harness
and checked-in MAME 0.289 unSP sources. Unimplemented instructions, missing RAM,
and unknown internal-ROM calls stop execution. No arbitrary BIN write or I/O.
"""
from collections import deque
import struct

N, Z, S, C = 0x200, 0x100, 0x80, 0x40
STOP = 0x3fffff


def nz(sr, value):
    return (sr & ~(N | Z)) | (N if value & 0x8000 else 0) | (Z if value & 0xffff == 0 else 0)


def nzsc(sr, value, left, right):
    return (sr & ~(N | Z | S | C)) | (S if ((value >> 16) & 1) != (((left ^ right) >> 15) & 1) else 0) | (N if value & 0x8000 else 0) | (Z if value & 0xffff == 0 else 0) | (C if value & 0x10000 else 0)


def branch(sr, condition):
    n, z, s, c = bool(sr & N), bool(sr & Z), bool(sr & S), bool(sr & C)
    return (not c, c, not s, s, not z, z, not n, n, z or not c,
            not z and c, z or s, not z and not s, n == s, n != s, True)[condition]


class CPU:
    def __init__(self, code, ram, adapters=True, flash=None, clock_seconds=None,
                 album_flash=None, local_play=False):
        self.code, self.mem = bytes(code), dict(ram)
        # Host stack fixture, kept separate from native object/RNG records.
        self.r = [0x1f00, 0, 0, 0, 0, 0x1e12, 0x20, 0]
        self.fr = 0x03e0
        self.trace = deque(maxlen=20000)
        self.steps = 0
        self.calls, self.adapters, self.writes = [], [], []
        self.allow_adapters = adapters
        self.local_play = bool(local_play)
        if clock_seconds is not None and (type(clock_seconds) is not int or clock_seconds not in (0, 1)):
            raise ValueError('005FBE host fixture accepts exactly 0 or 1 second')
        self.clock_seconds = clock_seconds
        # Two explicit 4KiB persistent-mirror fixtures, copied from the input
        # image. No file handle is retained and no input BIN can be programmed.
        initial=code[0x7fd000:0x7ff000] if len(code)>=0x7ff000 else b'\xff'*0x2000
        self.virtual_flash=bytearray(initial if flash is None else flash)
        if len(self.virtual_flash)!=0x2000:raise ValueError('Virtual mirror fixture must be 8192 bytes')
        album_initial=code[0x5f000:0x5f040] if len(code)>=0x5f040 else b'\xff'*64
        self.virtual_album=bytearray(album_initial if album_flash is None else album_flash)
        if len(self.virtual_album)!=64:raise ValueError('Virtual album fixture must be 64 bytes')
        if self.local_play:self.mem.setdefault(0x30e9,0)

    @property
    def pc(self):
        return ((self.r[6] & 63) << 16) | self.r[7]

    @property
    def sb(self):
        return (self.fr >> 7) & 15

    @sb.setter
    def sb(self, value):
        self.fr = (self.fr & ~0x780) | ((value & 15) << 7)

    def setpc(self, value):
        self.r[7] = value & 65535
        self.r[6] = (self.r[6] & 0xffc0) | ((value >> 16) & 63)

    def word(self, address):
        at = 2 * (address - 0x200000)
        if not 0 <= at < len(self.code)-1:
            raise RuntimeError(f'Unmapped instruction/internal ROM {address:06X}')
        return struct.unpack_from('<H', self.code, at)[0]

    def read(self, address):
        if 0x200000 <= address < 0x600000:
            return self.word(address)
        if address not in self.mem:
            raise RuntimeError(f'Uninitialized RAM/peripheral {address:06X} at PC {self.pc:06X}')
        return self.mem[address]

    def write(self, address, value):
        if address==0x30e9 and self.local_play and self.allow_adapters:
            # Source resolver224800 saves/restores this bank register. Direct
            # local image addressing is a host fixture, not hardware banking.
            self.mem[address]=value&65535
            self.writes.append((address,value&65535))
            return
        if not 0 <= address < 0x2000:
            raise RuntimeError(f'Unsupported RAM/peripheral write {address:06X} at PC {self.pc:06X}')
        self.mem[address] = value & 65535
        self.writes.append((address, value & 65535))

    def push(self, reg, value):
        self.write(self.r[reg], value)
        self.r[reg] = (self.r[reg]-1) & 65535

    def pop(self, reg):
        self.r[reg] = (self.r[reg]+1) & 65535
        return self.read(self.r[reg])

    def call(self, target, ret):
        self.calls.append(target)
        if target < 0x200000:
            if not self.allow_adapters:
                raise RuntimeError(f'Unmodelled internal ROM {target:06X}')
            if target == 0x5fbe:
                if self.clock_seconds is None:
                    raise RuntimeError('005FBE requires an explicit single-use host clock edge')
                second, minute, hour = (self.read(a) for a in (0xcc2, 0xcc3, 0xcc4))
                if not (0 <= second < 60 and 0 <= minute < 60 and 0 <= hour < 24):
                    raise RuntimeError('005FBE host fixture encountered invalid clock fields')
                delta, self.clock_seconds = self.clock_seconds, None
                before = hour*3600+minute*60+second
                after = (before+delta) % 86400
                for a, value in ((0xcc2,after%60),(0xcc3,after//60%60),(0xcc4,after//3600),
                                 (0xcc7,int(bool(delta) and before//60 != after//60))):
                    self.write(a, value)
                # Match the audited adverse caller-clobber fixture. This is
                # not a complete ROM ABI or an implementation of its body.
                self.r[1:5] = [0x1234, 0xabcd, 0x5678, 0x9abc]
                self.adapters.append({'target':'005FBE','kind':'explicit host 0/1-second edge; partial ROM fixture, no hardware RTC',
                                      'seconds':delta,'before':before,'after':after,
                                      'writes':['CC2','CC3','CC4','CC7'],'R1_R4':'adverse caller-clobber fixture',
                                      'unmodelled':'CC5/CC6, other ROM effects, interrupts and hardware timing'})
            elif target in (0x49db,0x4a75) and self.read(self.r[0]+4)==5 and self.local_play:
                ptr,count,low,bank=[self.read(self.r[0]+i) for i in range(1,5)]
                if count!=1 or low%2 or not (0xf000<=low<=0xf03e and 0<=ptr<0x2000):
                    raise RuntimeError('Album access outside explicit 64-byte acquired-bit fixture')
                at=low-0xf000
                old=struct.unpack_from('<H',self.virtual_album,at)[0]
                if target==0x49db:self.write(ptr,old)
                else:struct.pack_into('<H',self.virtual_album,at,old&self.read(ptr))
                self.adapters.append({'target':f'{target:06X}','kind':'host acquired-album NOR fixture; no physical Flash guarantee',
                                      'byte_offset':0x50000+low,'words':count})
            elif target in (0x49db,0x4a75) and self.read(self.r[0]+4)==0x7f:
                ptr,count,low,bank=[self.read(self.r[0]+i) for i in range(1,5)]
                if low%2 or not (0xd000<=low<=low+count*2<=0xf000 and 0<=ptr<=0x2000-count):
                    raise RuntimeError('Virtual Flash request outside isolated D000/E000 mirror fixtures')
                for i in range(count):
                    off=low-0xd000+2*i
                    old=struct.unpack_from('<H',self.virtual_flash,off)[0]
                    if target==0x49db:self.write(ptr+i,old)
                    else:struct.pack_into('<H',self.virtual_flash,off,old&self.read(ptr+i))
                self.adapters.append({'target':f'{target:06X}','kind':'host virtual NOR read' if target==0x49db else 'host virtual NOR program; source BIN untouched','low':low,'words':count})
            elif target==0x4c29:
                low,bank=self.read(self.r[0]+1),self.read(self.r[0]+2)
                if bank!=0x7f or low not in (0xd000,0xe000):
                    raise RuntimeError('Erase outside explicit D000/E000 virtual mirror fixture')
                off=low-0xd000;self.virtual_flash[off:off+0x1000]=b'\xff'*0x1000
                self.adapters.append({'target':'004C29','kind':'host 4KiB mirror erase fixture; physical erase geometry unproved','low':low})
            elif target==0x4e73:
                hidden=(*range(0x838,0x84a),0xd9f,0xda0,0xda1,0xda2,*range(0xda5,0xdae))
                for i,addr in enumerate(hidden):self.write(addr,0xd000+i)
                self.adapters.append({'target':'004E73','kind':'UNKNOWN ROM body: adversarial host fixture, NOT hardware-equivalent; native caller must restore protected RAM','clobbered_words':len(hidden)})
            elif target in (0x6129,0x6186):
                a,b=self.read(self.r[0]+1),self.read(self.r[0]+2)
                # Native20424C..204289 starts place=1 and extracts a digit as
                # (value % (place*10)) / place, then multiplies place by10.
                # The old b==10 guard rejected the very first /1 in Status.
                # Native209CEE..209D45 also divides the Strength maximum by
                # 14, then (maximum-1) by13 with remainder for its gauge.
                # Retain a bounded, caller-grounded arithmetic adapter rather
                # than claiming the complete internal ROM's ABI is known.
                if b not in (1,10,13,14,100,1000,10000):
                    raise RuntimeError('Only audited decimal/gauge divisors 1/10/13/14/100/1000/10000 are adapted')
                self.r[1]=a%b if target==0x6129 else a//b
                self.adapters.append({'target':f'{target:06X}','kind':'host unsigned arithmetic; native20424C/209CEE caller evidence; ROM ABI clobbers unmodelled','a':a,'b':b,'result':self.r[1]})
            elif target in (0x63cf, 0x603c, 0x60b3):
                a = self.read(self.r[0]+1) | (self.read(self.r[0]+2) << 16)
                b = self.read(self.r[0]+3) | (self.read(self.r[0]+4) << 16)
                if target != 0x63cf and b == 0:
                    raise RuntimeError('ROM arithmetic adapter division by zero')
                v = a*b if target == 0x63cf else a//b if target == 0x603c else a%b
                self.r[1:3] = [v & 65535, (v >> 16) & 65535]
                self.adapters.append({'target':f'{target:06X}', 'kind':'host arithmetic; ROM ABI clobbers unmodelled', 'a':a, 'b':b, 'result':v & 0xffffffff})
            elif target == 0x6260:
                # 64-bit shift right used by the native album bit counter 200760 at the end of every
                # evolution / jogress animation: [sp+1..4] = value (low word first), [sp+5] = count -> R1..R4.
                sp = self.r[0]
                v = sum(self.read(sp+i) << (16*(i-1)) for i in range(1,5)) >> self.read(sp+5)
                self.r[1:5] = [(v >> s) & 65535 for s in (0, 16, 32, 48)]
                self.adapters.append({'target':'006260', 'kind':'host 64-bit shift right (album bit counter)'})
            elif target == 0x578c:
                # Sound start called by 200071 when a sound is pending (evolution end); no audio on the host.
                self.adapters.append({'target':'00578C', 'kind':'host no-op (sound)'})
            elif target == 0x49db:
                dest, size, lo, hi = [self.read(self.r[0]+i) for i in range(1,5)]
                at = lo | (hi << 16)
                if not (1 <= size <= 0x1000 and 0 <= dest <= 0x2000-size and
                        0 <= at <= len(self.code)-size*2):
                    raise RuntimeError('SPI read exceeds local BIN or host RAM bounds')
                for i in range(size):
                    self.write(dest+i, struct.unpack_from('<H', self.code, at+2*i)[0])
                self.adapters.append({'target':'0049DB', 'kind':'read-only local BIN SPI byte read; no physical bus timing', 'byte_offset':at, 'words':size})
            else:
                raise RuntimeError(f'Unmodelled internal ROM {target:06X}')
            self.setpc(ret)
            return
        self.setpc(ret)
        self.push(0, self.r[7])
        self.push(0, self.r[6])
        self.setpc(target)

    def step(self):
        pc = self.pc
        op = self.word(pc)
        self.trace.append((pc, op)); self.steps += 1
        self.setpc(pc+1)
        top, dst, group, mode, src = op >> 12, (op >> 9)&7, (op >> 6)&7, (op >> 3)&7, op&7
        if op == 0xf165:  # NOP
            return
        # MAME0.289 unsp_fxxx.cpp239..257: scalar signed16 * signed16,
        # MR=R4:R3. Read both operands before overwriting their possible aliases.
        # Unlike ALU operations this instruction does not update SR/FR flags.
        if op & 0xf1f8 == 0xf108:
            left,right=self.r[dst],self.r[src]
            product=((left if left<0x8000 else left-0x10000)*
                     (right if right<0x8000 else right-0x10000))&0xffffffff
            self.r[3],self.r[4]=product&65535,product>>16
            return
        # MAME0.289 unsp_fxxx.cpp360..371: CALL MR saves PC and full SR.
        if op & 0xf1e7 == 0xf161:
            self.call(self.r[3]|((self.r[4]&63)<<16),pc+1)
            return
        interrupt=op&0xf1ff
        if interrupt in (0xf140,0xf141,0xf142,0xf143):
            self.fr=(self.fr&~0x60)|((op&3)<<5);return
        if interrupt in (0xf148,0xf149):
            self.fr=(self.fr&~0x20)|((op&1)<<5);return
        if interrupt in (0xf14c,0xf14e):
            self.fr=(self.fr&~0x40)|((op&2)<<5);return
        if (op & 0xf1f8) in (0xf030, 0xf038):
            if op & 0xf1f8 == 0xf030:
                self.r[src] = self.fr
            else:
                if (self.fr ^ self.r[src]) & 0x2000:
                    raise RuntimeError('Register-bank switch unsupported')
                self.fr = self.r[src]
            return
        if op & 0xf188 == 0xe108:
            shift, n, v = (op >> 4)&7, self.r[src]&31, self.r[dst]
            if shift == 2: self.r[dst] = (v << n)&65535
            elif shift == 3:
                self.r[3] = (v << n)&65535; self.r[4] |= (v << n >> 16)&65535
            elif shift == 4: self.r[dst] = v >> n
            else: raise RuntimeError(f'Unsupported variable shift {op:04X} at {pc:06X}')
            return
        if top < 15 and dst == 7 and group < 2:
            if branch(self.r[6], top):
                self.setpc(self.pc+((op&63) if group == 0 else -(op&63)))
            return
        if op & 0xf3c0 == 0xf040:
            self.call(((op&63) << 16)|self.word(pc+1), pc+2); return
        if op & 0xffc0 == 0xfe80:
            self.setpc(((op&63) << 16)|self.word(pc+1)); return
        if op & 0xffc0 == 0xfe00 or op & 0xf1f8 == 0xf028:
            value = op&63 if op & 0xffc0 == 0xfe00 else self.r[src]&63
            self.r[6] = (self.r[6]&0x3ff)|(value << 10); return
        if group == 2 and top == 13:
            for reg in range(dst, dst-mode, -1): self.push(src, self.r[reg])
            return
        if group == 2 and top == 9:
            if op == 0x9a98: raise RuntimeError('RETI/interrupt controller unsupported')
            for reg in range(dst+1, dst+mode+1): self.r[reg] = self.pop(src)
            return
        left, address = self.r[dst], None
        if group == 0:
            address = (self.r[5]+(op&63))&65535
        elif group == 1:
            right = op&63
        elif group == 3:
            def adjust(delta):
                self.r[src] = (self.r[src]+delta)&65535
                if mode&4 and self.r[src] == (0 if delta > 0 else 65535):
                    self.r[6] = (self.r[6]+(0x400 if delta > 0 else -0x400))&65535
            if mode&3 == 3: adjust(1)
            address = ((((self.r[6] >> 10)&63) << 16) if mode&4 else 0)|self.r[src]
            right = self.read(address) if top != 13 else 0
            if mode&3 in (1,2): adjust(-1 if mode&3 == 1 else 1)
        elif group == 4 and mode == 0:
            right = self.r[src]
        elif group == 4 and mode == 1:
            left, right = self.r[src], self.word(self.pc); self.setpc(self.pc+1)
        elif group == 4 and mode in (2,3):
            address=self.word(self.pc);self.setpc(self.pc+1)
            if mode==3:right=left
            left=self.r[src]
        elif group == 5:
            if mode&4:
                shifted = ((self.r[src] << 4)|self.sb) >> (mode-3)
                self.sb = shifted&15; right = (shifted >> 4)&65535
            else:
                shifted = ((self.sb << 16)|self.r[src]) << (mode+1)
                self.sb = (shifted >> 16)&15; right = shifted&65535
        elif group == 6:
            shifted = (((self.sb << 16)|self.r[src]) << 4)|self.sb
            if mode&4:
                shifted >>= mode-3; self.sb = shifted&15
            else:
                shifted <<= mode+1; self.sb = (shifted >> 20)&15
            right = (shifted >> 4)&65535
        else:
            raise RuntimeError(f'Unsupported opcode {op:04X} at {pc:06X}')
        if address is not None and top != 13 and group != 3 and not (group==4 and mode==3): right = self.read(address)
        if top == 13:
            if address is None: raise RuntimeError(f'Unsupported store {op:04X} at {pc:06X}')
            self.write(address, left); return
        if top in (0,1,2,3,4):
            operand = right if top in (0,1) else (~right)&65535
            carry = int(bool(self.r[6]&C)) if top in (1,3) else int(top in (2,4))
            result = left+operand+carry
            if dst != 7: self.r[6] = nzsc(self.r[6], result, left, operand)
            if top == 4: return
        elif top in (6,8,9,10,11,12):
            result = {6:lambda:-right,8:lambda:left^right,9:lambda:right,
                      10:lambda:left|right,11:lambda:left&right,12:lambda:left&right}[top]()
            if dst != 7: self.r[6] = nz(self.r[6], result)
            if top == 12: return
        else:
            raise RuntimeError(f'Unsupported ALU {op:04X} at {pc:06X}')
        if group==4 and mode==3:self.write(address,result)
        else:self.r[dst] = result&65535

    def run(self, entry, args=(), budget=100000, register1=None, direct=False):
        for i, value in enumerate(args, 1): self.mem[self.r[0]+i] = value
        if register1 is not None: self.r[1] = register1
        if direct: self.setpc(entry)
        else: self.call(entry, STOP)
        while self.pc != STOP:
            if self.steps >= budget: raise RuntimeError(f'Instruction budget {budget} exhausted at {self.pc:06X}')
            self.step()
        if self.r[0] != 0x1f00: raise RuntimeError(f'Unbalanced host stack: {self.r[0]:04X}')
        return self
