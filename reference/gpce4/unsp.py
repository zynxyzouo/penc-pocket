# SPDX-License-Identifier: GPL-3.0-or-later
# Instruction semantics follow MAME 0.289 src/devices/cpu/unsp (GPL-2.0-or-later;
# Segher Boessenkool, Ryan Holtz, David Haywood) and the audited PenC cpu.py.
"""unSP CPU core with interrupts, for running a GPCE4 machine from reset.

Unlike the host-fixture CPUs in the PenC emulators, nothing is stubbed here: every
memory access goes to a bus object (read(address22) / write(address22, value)), and
the internal ROM runs as code. Unknown opcodes raise instead of guessing.

Registers: r0 SP, r1..r4, r5 BP, r6 SR (CS 0..5, C 6, S 7, Z 8, N 9, DS 10..15), r7 PC.
FR (MAME layout): PRI 0..3, INE 4, IRQ enable 5, FIQ enable 6, SB 7..10, FIR_MOV 11,
FRA 12, BNK 13, AQ 14.
"""
N, Z, S, C = 0x200, 0x100, 0x80, 0x40
INE, IRQ_EN, FIQ_EN = 0x10, 0x20, 0x40
FIQ_LINE = 0                  # sirq bit 0 = FIQ, bit 1 + n = IRQn (MAME order)
RETI = 0x9A98


class Halt(Exception):
    pass


def flags_nz(sr, value):
    return (sr & ~(N | Z)) | (N if value & 0x8000 else 0) | (Z if value & 0xFFFF == 0 else 0)


def flags_nzsc(sr, value, left, right):
    return ((sr & ~(N | Z | S | C)) | (S if ((value >> 16) & 1) != (((left ^ right) >> 15) & 1) else 0)
            | (N if value & 0x8000 else 0) | (Z if value & 0xFFFF == 0 else 0) | (C if value & 0x10000 else 0))


BRANCH = (lambda s: not s & C, lambda s: s & C, lambda s: not s & S, lambda s: s & S,
          lambda s: not s & Z, lambda s: s & Z, lambda s: not s & N, lambda s: s & N,
          lambda s: s & Z or not s & C, lambda s: not s & Z and s & C,
          lambda s: s & Z or s & S, lambda s: not s & Z and not s & S,
          lambda s: bool(s & N) == bool(s & S), lambda s: bool(s & N) != bool(s & S), lambda s: True)


class Unsp:
    def __init__(self, bus, vector_base=0x4010):
        self.bus = bus
        self.vector_base = vector_base
        self.reset()

    def reset(self):
        self.r = [0] * 8
        self.fr = 0x0808                       # PRI 8, FIR_MOV 1 (MAME device_reset)
        self.irq_active = self.fiq_active = False
        self.sirq = 0
        self.sleeping = False
        self.steps = 0
        self.secbank = [0] * 4
        self.r[7] = self.bus.read(self.vector_base + 7)

    # --- program counter / flags -------------------------------------------------
    @property
    def pc(self):
        return ((self.r[6] & 63) << 16) | self.r[7]

    def setpc(self, value):
        self.r[7] = value & 0xFFFF
        self.r[6] = (self.r[6] & 0xFFC0) | ((value >> 16) & 63)

    @property
    def ds(self):
        return self.r[6] >> 10

    @property
    def sb(self):
        return (self.fr >> 7) & 15

    @sb.setter
    def sb(self, value):
        self.fr = (self.fr & ~0x780) | ((value & 15) << 7)

    def fetch(self):
        pc = self.pc
        self.setpc(pc + 1)
        return self.bus.read(pc)

    def push(self, value, reg=0):
        self.bus.write(self.r[reg], value & 0xFFFF)
        self.r[reg] = (self.r[reg] - 1) & 0xFFFF

    def pop(self, reg=0):
        self.r[reg] = (self.r[reg] + 1) & 0xFFFF
        return self.bus.read(self.r[reg])

    # --- interrupts ---------------------------------------------------------------
    def set_line(self, line, state):
        """line FIQ_LINE or 1 + n for IRQn; state True = asserted."""
        if state:
            self.sirq |= 1 << line
        else:
            self.sirq &= ~(1 << line)

    def check_irqs(self):
        if not self.sirq:
            return False
        line = (self.sirq & -self.sirq).bit_length() - 1        # lowest set bit wins (MAME)
        if line == FIQ_LINE:
            if not self.fr & FIQ_EN or self.fiq_active:
                return False
            self.fiq_active = True
            self.push(self.r[7])
            self.push(self.r[6])
            self.r[7] = self.bus.read(self.vector_base + 6)
            self.r[6] = 0
        else:
            irq = line - 1
            ine = self.fr & INE
            if (not ine and self.irq_active) or (self.fr & 15) <= irq or not self.fr & IRQ_EN:
                return False
            self.irq_active = True
            self.push(self.r[7])
            self.push(self.r[6])
            if ine:
                self.push(self.fr)
                self.fr = (self.fr & ~15) | irq
            self.r[7] = self.bus.read(self.vector_base + 8 + irq)
            self.r[6] = 0
        self.sleeping = False
        return True

    def reti(self):
        if self.fr & INE:
            self.fr = self.pop()
        self.r[6] = self.pop()
        self.r[7] = self.pop()
        if self.fiq_active:
            self.fiq_active = False
        elif self.irq_active:
            self.irq_active = False

    # --- execution ------------------------------------------------------------------
    def step(self):
        if self.sleeping:
            if not self.check_irqs():
                return False
        pc = self.pc
        op = self.fetch()
        self.steps += 1
        self.execute(op, pc)
        if op != RETI and self.sirq:
            self.check_irqs()
        return True

    def call(self, target):
        self.push(self.r[7])
        self.push(self.r[6])
        self.setpc(target)

    def execute(self, op, pc):
        top, dst, group, mode, src = op >> 12, (op >> 9) & 7, (op >> 6) & 7, (op >> 3) & 7, op & 7
        r = self.r
        if top < 15 and dst == 7 and group < 2:                 # conditional / relative jumps
            if BRANCH[top](r[6]):
                self.setpc(self.pc + ((op & 63) if group == 0 else -(op & 63)))
            return
        if top == 15:
            return self.op_fxxx(op, dst, group, mode, src)
        if top == 14:
            return self.op_exxx(op, dst, group, mode, src)
        if group == 2 and top == 13:                             # push Rd..Rd-N+1 to [Rs]
            for reg in range(dst, dst - mode, -1):
                self.push(r[reg], src)
            return
        if group == 2 and top == 9:
            if op == RETI:
                return self.reti()
            for reg in range(dst + 1, dst + mode + 1):           # pop (retf = pop sr, pc)
                r[reg] = self.pop(src)
            return
        left, address, right = r[dst], None, 0
        if group == 0:
            address = (r[5] + (op & 63)) & 0xFFFF
        elif group == 1:
            right = op & 63
        elif group == 3:
            ds_mode = mode & 4

            def adjust(delta):
                r[src] = (r[src] + delta) & 0xFFFF
                if ds_mode and r[src] == (0 if delta > 0 else 0xFFFF):
                    r[6] = (r[6] + (0x400 if delta > 0 else -0x400)) & 0xFFFF
            if mode & 3 == 3:
                adjust(1)
            address = ((r[6] >> 10) << 16 if ds_mode else 0) | r[src]
            if top != 13:
                right = self.bus.read(address)
            if mode & 3 in (1, 2):
                adjust(-1 if mode & 3 == 1 else 1)
        elif group == 4:
            if mode == 0:
                right = r[src]
            elif mode == 1:
                left, right = r[src], self.fetch()
            elif mode in (2, 3):
                address = self.fetch()
                if mode == 3:
                    right = left
                left = r[src]
            else:                                                # ASR by mode-3 through SB
                v = (r[src] << 4) | self.sb
                if v & 0x80000:
                    v |= 0xF00000
                v >>= mode - 3
                self.sb = v & 15
                right = (v >> 4) & 0xFFFF
        elif group == 5:
            if mode & 4:                                         # LSR
                v = ((r[src] << 4) | self.sb) >> (mode - 3)
                self.sb = v & 15
                right = (v >> 4) & 0xFFFF
            else:                                                # LSL
                v = ((self.sb << 16) | r[src]) << (mode + 1)
                self.sb = (v >> 16) & 15
                right = v & 0xFFFF
        elif group == 6:
            v = (((self.sb << 16) | r[src]) << 4) | self.sb
            if mode & 4:                                         # ROR
                v >>= mode - 3
                self.sb = v & 15
            else:                                                # ROL
                v <<= mode + 1
                self.sb = (v >> 20) & 15
            right = (v >> 4) & 0xFFFF
        elif group == 7:                                         # [imm6]
            address = op & 63
        else:
            raise RuntimeError(f'Unsupported push/pop form {op:04X} at {pc:06X}')
        if address is not None and top != 13 and group != 3 and not (group == 4 and mode == 3):
            right = self.bus.read(address)
        if top == 13:                                            # STORE
            if address is None:
                raise RuntimeError(f'Unsupported store {op:04X} at {pc:06X}')
            self.bus.write(address, left)
            return
        if top <= 4:
            operand = right if top in (0, 1) else (~right) & 0xFFFF
            carry = (1 if r[6] & C else 0) if top in (1, 3) else int(top in (2, 4))
            result = left + operand + carry
            if dst != 7:
                r[6] = flags_nzsc(r[6], result, left, operand)
            if top == 4:
                return
        elif top in (6, 8, 9, 10, 11, 12):
            if top == 6:
                result = -right
            elif top == 8:
                result = left ^ right
            elif top == 9:
                result = right
            elif top == 10:
                result = left | right
            else:
                result = left & right
            if dst != 7:
                r[6] = flags_nz(r[6], result)
            if top == 12:
                return
        else:
            raise RuntimeError(f'Unsupported ALU {op:04X} at {pc:06X}')
        if group == 4 and mode == 3:
            self.bus.write(address, result & 0xFFFF)
        else:
            r[dst] = result & 0xFFFF

    # --- 0xExxx: bit ops, MUL uu, register shifts -----------------------------------------------
    def bitop(self, kind, value, bit):
        self.r[6] = (self.r[6] & ~Z) | (0 if value >> bit & 1 else Z)
        return (value, value | 1 << bit, value & ~(1 << bit), value ^ 1 << bit)[kind]

    def op_exxx(self, op, dst, group, mode, src):
        r = self.r
        kind = (op >> 4) & 3
        if op & 0xF1C8 == 0xE000 or op & 0xF1C0 == 0xE040:     # BITOP Rd,Rs / Rd,offset
            bit = r[src] & 15 if op & 0xF1C8 == 0xE000 else op & 15
            r[dst] = self.bitop(kind, r[dst], bit) & 0xFFFF
            return
        if op & 0xF180 == 0xE180 or op & 0xF188 == 0xE100 or op & 0xF188 == 0xE140:
            ds_form = op & 0xF1C0 in (0xE1C0, 0xE140)
            bit = op & 15 if op & 0xF180 == 0xE180 else r[src] & 15
            address = (self.ds << 16 if ds_form else 0) | r[dst]
            orig = self.bus.read(address)
            new = self.bitop(kind, orig, bit)
            if kind:
                self.bus.write(address, new & 0xFFFF)
            return
        if op & 0xF1F8 == 0xE008:                               # MUL uu
            v = r[dst] * r[src]
            r[3], r[4] = v & 0xFFFF, v >> 16
            return
        if op & 0xF188 == 0xE108:                               # 16-bit shift by register
            kind, n, v = (op >> 4) & 7, r[src] & 31, r[dst]
            if kind == 0:
                r[dst] = ((v - 0x10000 if v & 0x8000 else v) >> n) & 0xFFFF
            elif kind == 1:
                res = ((v - 0x10000 if v & 0x8000 else v) << 16) >> n
                r[3] |= res & 0xFFFF
                r[4] = (res >> 16) & 0xFFFF
            elif kind == 2:
                r[dst] = (v << n) & 0xFFFF
            elif kind == 3:
                res = v << n
                r[3] = res & 0xFFFF
                r[4] |= (res >> 16) & 0xFFFF
            elif kind == 4:
                r[dst] = v >> n
            elif kind == 5:
                res = (v << 16) >> n
                r[3] |= res & 0xFFFF
                r[4] = (res >> 16) & 0xFFFF
            else:
                raise RuntimeError(f'rol/ror by register unimplemented {op:04X} at {self.pc - 1:06X}')
            return
        raise RuntimeError(f'Unsupported Exxx {op:04X} at {self.pc - 1:06X}')

    # --- 0xFxxx ----------------------------------------------------------------------------------
    def op_fxxx(self, op, dst, group, mode, src):
        r = self.r
        if group == 0:
            if op & 0xFFC0 == 0xFE00:
                r[6] = (r[6] & 0x3FF) | ((op & 63) << 10)
            elif op & 0xF1F8 == 0xF020:
                r[src] = r[6] >> 10
            elif op & 0xF1F8 == 0xF028:
                r[6] = (r[6] & 0x3FF) | ((r[src] & 63) << 10)
            elif op & 0xF1F8 == 0xF030:
                r[src] = self.fr
            elif op & 0xF1F8 == 0xF038:
                self.set_fr(r[src])
            elif op & 0xF1F8 == 0xF008:                          # MUL us (rd unsigned, rs signed)
                v = r[dst] * r[src]
                if r[src] & 0x8000:
                    v -= r[dst] << 16
                v &= 0xFFFFFFFF
                r[3], r[4] = v & 0xFFFF, v >> 16
            else:
                raise RuntimeError(f'Unsupported F/0 {op:04X} at {self.pc - 1:06X}')
            return
        if group == 1:
            if op & 0xF3C0 == 0xF040:                            # CALL A22
                low = self.fetch()
                self.call(((op & 63) << 16) | low)
            elif op & 0xF3C0 == 0xF240:                          # BITOP {ds:}[A16],offset
                address = self.fetch() | (self.ds << 16 if op & 0x0400 else 0)
                kind = (op >> 4) & 3
                orig = self.bus.read(address)
                new = self.bitop(kind, orig, op & 15)
                if kind:
                    self.bus.write(address, new & 0xFFFF)
            else:
                raise RuntimeError(f'Unsupported F/1 {op:04X} at {self.pc - 1:06X}')
            return
        if group == 2 and op & 0xFFC0 == 0xFE80:                  # GOTO A22
            low = self.fetch()
            self.setpc(((op & 63) << 16) | low)
            return
        if group == 3 and op & 0xFFC0 == 0xFEC0:                  # GOTO MR
            self.setpc(((r[4] & 63) << 16) | r[3])
            return
        if group == 4 and op & 0xF1F8 == 0xF108:                  # MUL ss
            a = r[dst] - 0x10000 if r[dst] & 0x8000 else r[dst]
            b = r[src] - 0x10000 if r[src] & 0x8000 else r[src]
            v = (a * b) & 0xFFFFFFFF
            r[3], r[4] = v & 0xFFFF, v >> 16
            return
        if group == 5:
            low = op & 0x3F
            if low in (0, 1, 2, 3):                              # int off / irq / fiq / fiq,irq
                self.fr = (self.fr & ~(IRQ_EN | FIQ_EN)) | (IRQ_EN if low & 1 else 0) | (FIQ_EN if low & 2 else 0)
            elif low in (8, 9):
                self.fr = (self.fr & ~IRQ_EN) | (IRQ_EN if low & 1 else 0)
            elif low in (0xC, 0xE):
                self.fr = (self.fr & ~FIQ_EN) | (FIQ_EN if low & 2 else 0)
            elif low in (4, 5):
                self.fr = (self.fr & ~0x800) | (0x800 if low == 4 else 0)
            elif low in (6, 7):
                self.fr = (self.fr & ~0x1000) | (0x1000 if low == 7 else 0)
            elif low in (0xD, 0xF):
                self.fr = (self.fr & ~INE) | (INE if low == 0xF else 0)
            elif low in (0xA, 0xB):
                self.set_bank(low == 0xB)
            elif low & 0x27 == 0x25:                             # NOP family f165/f16d/...
                pass
            elif low & 0x27 == 0x21:                             # CALL MR
                self.call(((r[4] & 63) << 16) | r[3])
            elif low & 0x27 == 0x24:                             # r2 = exp r4
                v = r[4]
                if v & 0x8000:
                    v = ~v & 0xFFFF
                r[2] = (16 - v.bit_length()) - 1
            else:
                raise RuntimeError(f'Unsupported F/5 {op:04X} at {self.pc - 1:06X}')
            return
        raise RuntimeError(f'Unsupported Fxxx {op:04X} at {self.pc - 1:06X}')

    def set_fr(self, value):
        self.set_bank(bool(value & 0x2000))
        self.fr = value & 0x7FFF

    def set_bank(self, on):
        if bool(self.fr & 0x2000) != on:
            self.r[1:5], self.secbank = self.secbank, self.r[1:5]
            self.fr ^= 0x2000
