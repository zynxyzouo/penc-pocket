# SPDX-License-Identifier: GPL-3.0-or-later
# Instruction semantics adapted from cpu.py; see its MAME attribution and LICENSE.
"""Cache decoded instruction handlers without changing the strict CPU contract.

Only numeric instruction fields enter generated Python; there is no firmware
text execution. Cache entries depend on the opcode, never RAM or BIN identity.
Uncommon/special instructions use the original CPU.step, including adapters.
All reads, writes and calls still dispatch through the instance's overrides.
Instruction budgets and every instruction/trace record are preserved.
"""
import sys

from cpu import CPU, STOP, nz, nzsc

_handlers = {}
_CACHE_LIMIT = 4096
_namespace = {'nz': nz, 'nzsc': nzsc}
_block_code = None
_blocks = {}
_BLOCK_LIMIT = 8192
_BLOCK_LENGTH = 16


def _pc_lines(value):
    return [f'r[7] = {value & 65535}', f'r[6] = (r[6] & 65472) | {(value >> 16) & 63}']


def _decode(op):
    top, dst, group, mode, src = op >> 12, (op >> 9) & 7, (op >> 6) & 7, (op >> 3) & 7, op & 7
    body = []
    if op == 0xf165:
        body = ['pass']
    elif top < 15 and dst == 7 and group < 2:
        conditions = ('not r[6]&64', 'r[6]&64', 'not r[6]&128', 'r[6]&128',
                      'not r[6]&256', 'r[6]&256', 'not r[6]&512', 'r[6]&512',
                      'r[6]&256 or not r[6]&64', 'not r[6]&256 and r[6]&64',
                      'r[6]&256 or r[6]&128', 'not r[6]&256 and not r[6]&128',
                      'bool(r[6]&512)==bool(r[6]&128)',
                      'bool(r[6]&512)!=bool(r[6]&128)', 'True')
        delta = (op & 63) * (1 if group == 0 else -1)
        body = [f'if {conditions[top]}: self.setpc(self.pc + ({delta}))']
    elif top not in (0, 1, 2, 3, 4, 6, 8, 9, 10, 11, 12, 13):
        return CPU.step
    elif group == 2:
        return CPU.step  # Stack operations and unsupported group-2 opcodes.
    else:
        body.append(f'left = r[{dst}]')
        addressed = False
        if group == 0:
            body.append(f'address = (r[5] + {op & 63}) & 65535')
            addressed = True
        elif group == 1:
            body.append(f'right = {op & 63}')
        elif group == 3:
            def adjust(delta):
                lines = [f'r[{src}] = (r[{src}] + ({delta})) & 65535']
                if mode & 4:
                    lines.append(f'if r[{src}] == {0 if delta > 0 else 65535}: r[6] = (r[6] + ({1024 if delta > 0 else -1024})) & 65535')
                return lines
            if mode & 3 == 3:
                body.extend(adjust(1))
            prefix = '(((r[6] >> 10) & 63) << 16) | ' if mode & 4 else ''
            body.append(f'address = {prefix}r[{src}]')
            body.append('right = self.read(address)' if top != 13 else 'right = 0')
            if mode & 3 in (1, 2):
                body.extend(adjust(-1 if mode & 3 == 1 else 1))
            addressed = True
        elif group == 4 and mode == 0:
            body.append(f'right = r[{src}]')
        elif group == 4 and mode == 1:
            body.extend((f'left = r[{src}]', 'right = self.word(self.pc)', 'self.setpc(self.pc + 1)'))
        elif group == 4 and mode in (2, 3):
            body.extend(('address = self.word(self.pc)', 'self.setpc(self.pc + 1)'))
            if mode == 3:
                body.append('right = left')
            body.append(f'left = r[{src}]')
            addressed = True
        elif group == 5:
            if mode & 4:
                body.extend((f'shifted = ((r[{src}] << 4) | self.sb) >> {mode - 3}',
                             'self.sb = shifted & 15', 'right = (shifted >> 4) & 65535'))
            else:
                body.extend((f'shifted = ((self.sb << 16) | r[{src}]) << {mode + 1}',
                             'self.sb = (shifted >> 16) & 15', 'right = shifted & 65535'))
        elif group == 6:
            body.append(f'shifted = (((self.sb << 16) | r[{src}]) << 4) | self.sb')
            if mode & 4:
                body.extend((f'shifted >>= {mode - 3}', 'self.sb = shifted & 15'))
            else:
                body.extend((f'shifted <<= {mode + 1}', 'self.sb = (shifted >> 20) & 15'))
            body.append('right = (shifted >> 4) & 65535')
        else:
            return CPU.step
        if addressed and top != 13 and group != 3 and not (group == 4 and mode == 3):
            body.append('right = self.read(address)')
        if top == 13:
            if not addressed:
                return CPU.step
            body.append('self.write(address, left)')
        else:
            if top in (0, 1, 2, 3, 4):
                body.append('operand = right' if top in (0, 1) else 'operand = (~right) & 65535')
                carry = 'int(bool(r[6] & 64))' if top in (1, 3) else str(int(top in (2, 4)))
                body.append(f'result = left + operand + {carry}')
                if dst != 7:
                    body.append('r[6] = nzsc(r[6], result, left, operand)')
            else:
                expression = {6:'-right', 8:'left ^ right', 9:'right', 10:'left | right',
                              11:'left & right', 12:'left & right'}[top]
                body.append(f'result = {expression}')
                if dst != 7:
                    body.append('r[6] = nz(r[6], result)')
            if top not in (4, 12):
                body.append('self.write(address, result)' if group == 4 and mode == 3
                            else f'r[{dst}] = result & 65535')
    source = 'def instruction(self, pc):\n    r = self.r\n' + ''.join('    ' + line + '\n' for line in body)
    scope = {}
    exec(compile(source, '<decoded unSP instruction>', 'exec'), _namespace, scope)
    handler = scope['instruction']
    handler.lines = body
    return handler


def _handler(op):
    handler = _handlers.get(op)
    if handler is None:
        handler = _decode(op)
        if len(_handlers) >= _CACHE_LIMIT:
            _handlers.clear()
        _handlers[op] = handler
    return handler


class AcceleratedCPU(CPU):
    def __init__(self, *args, **kwargs):
        global _block_code, _blocks
        super().__init__(*args, **kwargs)
        # A view shares the immutable BIN bytes and avoids a four-million-int
        # expansion. Pyodide and supported desktop hosts are little endian.
        self._words = (memoryview(self.code)[:len(self.code) & ~1].cast('H')
                       if sys.byteorder == 'little' else None)
        if self.code is not _block_code:
            _block_code, _blocks = self.code, {}
        self._blocks = _blocks

    def word(self, address):
        if self._words is None:
            return super().word(address)
        index = address - 0x200000
        if not 0 <= index < len(self._words):
            raise RuntimeError(f'Unmapped instruction/internal ROM {address:06X}')
        return self._words[index]

    def step(self):
        pc = self.pc
        op = self.word(pc)
        handler = _handler(op)
        if handler is CPU.step:
            return CPU.step(self)
        self.trace.append((pc, op))
        self.steps += 1
        self.setpc(pc + 1)
        handler(self, pc)

    def _block(self, pc):
        """Compile at most sixteen straight instructions from immutable bytes.

        Looking ahead never raises a guest fetch error or executes a read.
        Unmapped/unsupported operations remain the next strict CPU step. Keep
        every per-instruction side effect in order, so exceptions expose the
        same partial CPU state to the existing transaction rollback boundary.
        """
        source = ['def block(self):', '    r = self.r', '    trace = self.trace']
        count = 0
        for _ in range(_BLOCK_LENGTH):
            index = pc - 0x200000
            if not 0 <= index < len(self._words) or pc == STOP:
                break
            op = self._words[index]
            handler = _handler(op)
            if handler is CPU.step:
                break
            top, dst, group, mode, src = op >> 12, (op >> 9) & 7, (op >> 6) & 7, (op >> 3) & 7, op & 7
            # setpc wraps the full 22-bit PC, including a two-word instruction
            # whose immediate sits at STOP. Never compile past that CPU window.
            following = (pc + (2 if group == 4 and mode in (1, 2, 3) else 1)) & 0x3fffff
            source.extend((f'    trace.append(({pc}, {op}))', '    self.steps += 1'))
            source.extend('    ' + line for line in _pc_lines(pc + 1))
            for line in handler.lines:
                # Embed valid immutable immediate words as well. Missing
                # immediates still reach word() at the original instruction.
                if following == pc + 2 and index + 1 < len(self._words):
                    if line in ('right = self.word(self.pc)', 'address = self.word(self.pc)'):
                        line = line.split(' = ')[0] + ' = ' + str(self._words[index + 1])
                    elif line == 'self.setpc(self.pc + 1)':
                        source.extend('    ' + item for item in _pc_lines(pc + 2))
                        continue
                source.append('    ' + line)
            count += 1
            if dst in (6, 7) or (group == 3 and src in (6, 7)):
                break
            # Preserve dispatch if a read/write override changes the PC. Host
            # MMIO adapters also observe the exact intermediate PC above.
            if group in (0, 3) or (group == 4 and mode in (2, 3)):
                source.append(f'    if self.pc != {following}: return')
            pc = following
        if not count:
            return None
        scope = {}
        exec(compile('\n'.join(source), '<decoded unSP block>', 'exec'), _namespace, scope)
        return count, scope['block']

    def run(self, entry, args=(), budget=100000, register1=None, direct=False):
        # Custom instruction/fetch implementations and big-endian hosts keep
        # the base run loop rather than entering a block with different hooks.
        if (type(self).step is not AcceleratedCPU.step or type(self).word is not AcceleratedCPU.word
                or type(self).setpc is not CPU.setpc or self._words is None):
            return CPU.run(self, entry, args, budget, register1, direct)
        for i, value in enumerate(args, 1):
            self.mem[self.r[0] + i] = value
        if register1 is not None:
            self.r[1] = register1
        if direct:
            self.setpc(entry)
        else:
            self.call(entry, STOP)
        while self.pc != STOP:
            pc = self.pc
            remaining = budget - self.steps
            if remaining <= 0:
                raise RuntimeError(f'Instruction budget {budget} exhausted at {pc:06X}')
            if pc not in self._blocks:
                block = self._block(pc)
                if len(self._blocks) >= _BLOCK_LIMIT:
                    self._blocks.clear()
                self._blocks[pc] = block
            block = self._blocks[pc]
            # Whole blocks fit the instruction budget. At its boundary, use
            # single steps so stopping PC, trace and instruction count match.
            if block is not None and block[0] <= remaining:
                block[1](self)
            else:
                self.step()
        if self.r[0] != 0x1f00:
            raise RuntimeError(f'Unbalanced host stack: {self.r[0]:04X}')
        return self
