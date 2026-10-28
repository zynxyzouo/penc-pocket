# SPDX-License-Identifier: GPL-3.0-or-later
# Portions adapted from MAME 0.289 unSP, upstream GPL-2.0-or-later.
# Upstream copyright holders: Segher Boessenkool, Ryan Holtz, David Haywood.
# Copyright 2008-2017 Segher Boessenkool.
# Source: https://github.com/mamedev/mame/tree/mame0289/src/devices/cpu/unsp
# Modified for PenC Pocket: Python instruction implementation and host adapters.
# Release/license notice updated: 2026-10-28. See LICENSE and MODIFICATIONS.md.
"""Hash-admitted DMC LineDog native machine with explicit device boundaries.

This executes a selected save/title startup prefix and native input, care,
scene, journal and display code. Internal ROM, electrical reset/IRQ timing,
audio output and physical links are not emulated. No source file is writable.
"""
from collections import deque
import hashlib
import struct
from cpu import CPU, STOP, nz

FIRMWARE_SHA256='3457140c5f07211abdd756462693c67c824c4c45c26a7ca91e4323df476701dc'

class DmcCPU(CPU):
    def __init__(self,code):
        code=bytes(code)
        if len(code)!=0x800000 or hashlib.sha256(code).hexdigest()!=FIRMWARE_SHA256:
            raise ValueError('DMC machine requires the admitted LineDog v4.1 BIN')
        super().__init__(code,dict.fromkeys(range(0x2000),0),adapters=False)
        self.mem[0x3000]=65535
        self.flash=bytearray(code[0x7fd000:0x7ff000])
        self.r[0]=0x17ff
        self.trace=deque(maxlen=64)
        self.calls=deque(maxlen=128)
        self.writes=deque(maxlen=128)
        self.adapters=deque(maxlen=64)
        self.lines=deque(maxlen=96)
        self.window_commands=deque(maxlen=16)
        self.flash_events=deque(maxlen=64)
        self.warnings={'DMC_SELECTED_NATIVE_STARTUP_NO_HARDWARE_RESET',
                       'DMC_HOST_RTC_EDGE_NO_IRQ_TIMING','DMC_AUDIO_UNSUPPORTED',
                       'DMC_PHYSICAL_LINK_UNSUPPORTED','DMC_BATTERY_MONITOR_UNMODELED'}

    def read(self,address):
        if address==0x3000:return self.mem[address]
        if address==0x3053 and self.pc==0x2045b1:return 0x0205
        if 0x200000<=address<0x600000:return self.word(address)
        if not 0<=address<0x2000:
            raise RuntimeError(f'DMC unmapped data {address:06X} at {self.pc:06X}')
        return self.mem[address]

    def write(self,address,value):
        if ((self.pc,address,value) in ((0x2045ac,0x3054,1),
                (0x2045b7,0x3053,0x0205),(0x2045be,0x3033,0x5555))):
            self.adapters.append(('native_clock_commit_mmio',address,value));return
        return super().write(address,value)

    def call(self,target,ret):
        self.calls.append(target)
        sp=self.r[0]
        def args(n):return [self.read(sp+i) for i in range(1,n+1)]
        if target==0x2000c2:
            # Explicit muted sink at the sound-start ABI. The command's native
            # caller executes; no audio job starts, so native 200122 sees idle.
            self.mem[0xc8c]=0
            self.adapters.append(('muted_sound_start',args(1)[0]))
            self.setpc(ret);return
        if target>=0x200000:
            self.setpc(ret);self.push(0,self.r[7]);self.push(0,self.r[6]);self.setpc(target);return
        if target in (0x49cc,0x4a66):
            ptr,count,low,bank=args(4);offset=low|(bank<<16)
            if not 1<=count<=4096 or not 0<=ptr<=0x2000-count:
                raise RuntimeError('DMC Flash transfer exceeds RAM')
            if target==0x49cc:
                if not 0<=offset<=len(self.code)-2*count:raise RuntimeError('DMC Flash read exceeds image')
                for i in range(count):
                    at=offset+2*i
                    source=self.flash if 0x7fd000<=at<0x7ff000 else self.code
                    self.write(ptr+i,struct.unpack_from('<H',source,at-0x7fd000 if source is self.flash else at)[0])
            else:
                if not (bank==0x7f and 0xd000<=low<low+2*count<=0xf000
                        and 0x885<=ptr<ptr+count<=0xc85 and count in (1,137,138)):
                    raise RuntimeError('DMC program outside native journal')
                at=low-0xd000
                for i in range(count):
                    old=struct.unpack_from('<H',self.flash,at+2*i)[0]
                    struct.pack_into('<H',self.flash,at+2*i,old&self.read(ptr+i))
                self.flash_events.append(('program',at,count))
            self.r[1:5]=[0,0x1357,0x2468,0xabcd]
        elif target==0x4c1a:
            low,bank=args(2)
            if bank!=0x7f or low not in (0xd000,0xe000):raise RuntimeError('DMC erase outside journal')
            at=low-0xd000;self.flash[at:at+4096]=b'\xff'*4096
            self.flash_events.append(('erase',at,4096));self.r[1:5]=[0,0x1357,0x2468,0xabcd]
        elif target in (0x4e64,0x5898):
            # Flash preparation and watchdog service have no physical device.
            self.adapters.append(('flash_prepare' if target==0x4e64 else 'watchdog',target))
        elif target in (0x5f8b,0x5c60,0x5cd7):
            lo,hi,dlo,dhi=args(4);a=lo|(hi<<16);b=dlo|(dhi<<16)
            if target!=0x5f8b and b==0:raise RuntimeError('DMC arithmetic division by zero')
            value=a*b if target==0x5f8b else a//b if target==0x5c60 else a%b
            self.r[1:5]=[value&65535,(value>>16)&65535,0xcafe,0xbeef]
        elif target in (0x5daa,0x5d4d):
            a,b=args(2)
            if b==0:raise RuntimeError('DMC uint16 division by zero')
            self.r[1]=a//b if target==0x5daa else a%b
        elif target in (0x5acf,0x5ae4):
            self.window_commands.append((target,args(1)[0]));self.r[1:5]=[0x1234,0x5678,0x9abc,0xdef0]
        elif target==0x5b41:
            ptr,count=args(2)
            if (ptr,count)!=(0x7ba,96):raise RuntimeError('DMC LCD scanline ABI changed')
            self.lines.append([self.read(ptr+i) for i in range(count)])
            self.r[1:5]=[0x1234,0x5678,0x9abc,0xdef0]
        else:raise RuntimeError(f'DMC unmodelled internal ROM {target:06X} at {self.pc:06X}')
        self.setpc(ret)

    def step(self):
        pc=self.pc;op=self.word(pc)
        # MAME unSP scalar unsigned multiply, DS immediate precedence, and ASR
        # from the independently exercised DMC compositor instruction harness.
        if op&0xf1f8==0xe008 and ((op>>9)&7)!=7:
            self.steps+=1;self.trace.append((pc,op));self.setpc(pc+1)
            v=self.r[(op>>9)&7]*self.r[op&7];self.r[3:5]=[v&65535,v>>16];return
        if op&0xffc0==0xfe00:
            self.steps+=1;self.trace.append((pc,op));self.setpc(pc+1)
            self.r[6]=(self.r[6]&0x3ff)|((op&63)<<10);return
        top,dst,group,mode,src=op>>12,(op>>9)&7,(op>>6)&7,(op>>3)&7,op&7
        if top==9 and group==4 and mode>=4:
            self.steps+=1;self.trace.append((pc,op));self.setpc(pc+1)
            shifted=(self.r[src]<<4)|self.sb
            if shifted&0x80000:shifted|=0xf00000
            shifted>>=mode-3;self.sb=shifted&15
            value=(shifted>>4)&65535;self.r[dst]=value;self.r[6]=nz(self.r[6],value);return
        super().step()

    def invoke(self,entry,args=(),limit=1000000):
        sp,bp=self.r[0],self.r[5]
        for i,value in enumerate(args,1):self.mem[sp+i]=value&65535
        self.call(entry,STOP);end=self.steps+limit
        while self.pc!=STOP:
            if self.steps>=end:raise RuntimeError(f'DMC instruction budget at {self.pc:06X}')
            self.step()
        if (self.r[0],self.r[5])!=(sp,bp):raise RuntimeError('DMC native stack imbalance')
        return self.r[1]

    def boot(self):
        # These actual adjacent native calls elect the embedded pet journal and
        # initialize transient state. No HOME/care/unlock fixture is applied.
        self.setpc(0x23003e);end=self.steps+300000
        while self.pc!=0x230042:
            if self.steps>=end:raise RuntimeError('DMC embedded save recovery failed; no replacement pet created')
            self.step()
        if self.mem[0x885]!=0x5744 or self.mem[0x886]!=1:
            raise RuntimeError('DMC native save extension failed initialization')
        self.invoke(0x200bf3)
        self.frame([])

    def release_inputs(self):
        # Only host sampled-key state; native pet/clock state is untouched.
        self.mem.update({0x3000:65535,0x81b:0,0x81c:0,0x81d:0,
                         0x81e:0,0x81f:0,0x820:0,0x821:0})

    def _span(self,start,stops,limit=100000):
        """Execute an audited main-loop fragment up to a native boundary."""
        sp,bp=self.r[0],self.r[5]
        self.setpc(start);end=self.steps+limit
        while self.pc not in stops:
            if self.steps>=end:raise RuntimeError(f'DMC boundary budget at {self.pc:06X}')
            self.step()
        if (self.r[0],self.r[5])!=(sp,bp):raise RuntimeError('DMC boundary stack imbalance')
        return self.pc

    def _wake_display(self):
        # The absent low-power ROM 0051F5 returns on a key IRQ or a native care
        # event. Only the host wake edge replaces that electrical boundary.
        # Execute the actual two-GPIO-sample debounce, native state recovery,
        # and post-LCD bookkeeping. No pet, RTC or progress field is supplied.
        bp=self.r[5];scratch=(self.r[0]-16)&65535;old=self.mem[scratch]
        self.r[5]=scratch
        try:
            self._span(0x2301c7,{0x230216})
            self._span(0x23026e,{0x2302bd})
            self._span(0x2302f8,{0x230320})
        finally:
            self.mem[scratch]=old;self.r[5]=bp
        self.adapters.append(('virtual_display_wake_native_resume',0x23026e))

    def frame(self,keys,seconds=0,long=False):
        if not isinstance(keys,(list,tuple,set)) or any(k not in ('A','B','C') for k in keys):
            raise ValueError('Invalid DMC key input')
        if type(seconds) is not int or not 0<=seconds<=5:raise ValueError('DMC accepts 0..5 host seconds')
        # Long presses are recognized by native 200CA1 as held frames accrue.
        # The generic host long hint never injects a native event.
        held=sum({'A':8,'B':16,'C':32}[k] for k in set(keys))
        self.mem[0x3000]=65535^held
        for _ in range(max(1,seconds)):
            self.mem[0xcb2]=0
            if seconds and self.mem[0xcb0]:
                s,m,h=(self.mem[a] for a in (0xcad,0xcae,0xcaf))
                if not (0<=s<60 and 0<=m<60 and 0<=h<24):raise RuntimeError('Invalid DMC RTC fields')
                t=(h*3600+m*60+s+1)%86400
                self.mem.update({0xcad:t%60,0xcae:t//60%60,0xcaf:t//3600,0xcb2:int(s==59)})
            if self.mem[0xc88] in (0x1c,0x1d,0x1e,0x1f):
                # Native230172..2301A1 processes a minute while the display is
                # suspended and branches to2301AA when care itself requests wake.
                boundary=self._span(0x230172,{0x2301a1,0x2301aa})
                self.mem[0xcb2]=0
                if held or boundary==0x2301aa:self._wake_display()
                else:continue
            self.invoke(0x200c1a)
            self.invoke(0x20923c)
            self.invoke(0x200019)
            self.invoke(0x2005f3)
            self.mem[0xcb2]=0
        return self.mem[0xc88]

