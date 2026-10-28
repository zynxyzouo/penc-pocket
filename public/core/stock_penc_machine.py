# SPDX-License-Identifier: GPL-3.0-or-later
# Portions adapted from MAME 0.289 unSP, upstream GPL-2.0-or-later.
# Upstream copyright holders: Segher Boessenkool, Ryan Holtz, David Haywood.
# Copyright 2008-2017 Segher Boessenkool.
# Source: https://github.com/mamedev/mame/tree/mame0289/src/devices/cpu/unsp
# Modified for PenC Pocket: Python instruction implementation and host adapters.
# Release/license notice updated: 2026-10-28. See LICENSE and MODIFICATIONS.md.
"""Original TEST4 PenC machine: native save, input, UI, care and persistence.

This is a selected native startup/main-loop adapter, not a hardware reset or
internal-ROM emulator. The imported strict CPU is unchanged. Unknown services
stop. RGB565 pixels, RTC edges, power and NOR storage are explicit host devices.
"""
from collections import deque
import hashlib
import struct
from cpu import CPU,STOP,nz

FIRMWARE_SHA256='a21e573ba40741603b8b4068817c789c625196ab5e53ddb188b1f57c63c612a1'
SLEEP_STATES=frozenset((0x25,0x26,0x27,0x28,0x2e,0x30,0x31))

class StockLinkUnavailable(RuntimeError):
    """Physical-link setup is unavailable; caller must roll back the frame."""


class StockPenCCPU(CPU):
    def __init__(self,code):
        code=bytes(code)
        if len(code)!=0x800000 or hashlib.sha256(code).hexdigest()!=FIRMWARE_SHA256:
            raise ValueError('Stock PenC requires the byte-exact original TEST4 BIN')
        super().__init__(code,dict.fromkeys(range(0x2000),0),adapters=False)
        self.r[0]=0x17ff
        self.mem[0x3000]=65535
        self.flash=bytearray(code[0x7fd000:0x7ff000])
        self.trace=deque(maxlen=128);self.calls=deque(maxlen=256)
        self.writes=deque(maxlen=128);self.adapters=deque(maxlen=64)
        self.flash_events=deque(maxlen=64);self.display_requests=deque(maxlen=16)
        self.on_native_call=None
        self.motion_supported=True
        self.motion_pending=False
        self.mmio={a:0 for a in (*range(0x3001,0x3008),0x3014,0x3015,0x3016,0x3050,0x3051)}
        self.warnings={'STOCK_SELECTED_NATIVE_STARTUP_NO_HARDWARE_RESET',
            'STOCK_HOST_RTC_EDGE_NO_IRQ_TIMING','STOCK_HOST_POWER_NORMAL',
            'STOCK_HOST_RGB565_PROJECTION_NO_INTERNAL_ROM_RASTER',
            'STOCK_PHYSICAL_LINK_UNSUPPORTED','STOCK_HOST_SENSOR_EDGE_NO_PHYSICAL_ACCELEROMETER',
            'STOCK_AUDIO_TIMING_APPROXIMATE'}

    @property
    def ram(self):return self.mem

    def _config_access(self,address):
        return address in self.mmio and (0x2050bd<=self.pc<=0x2052bc or
            0x201c2b<=self.pc<=0x201ca1 or 0x201d7d<=self.pc<=0x201da8)

    def read(self,address):
        if self._config_access(address):return self.mmio[address]
        if address==0x3053 and self.pc==0x208090:return 0x0205
        if address==0x3000:return self.mem[address]
        if 0x200000<=address<0x600000:return self.word(address)
        if not 0<=address<0x2000:
            raise RuntimeError(f'Stock PenC unmapped data {address:06X} at {self.pc:06X}')
        return self.mem[address]

    def write(self,address,value):
        if self._config_access(address):
            self.mmio[address]=value&65535
            self.adapters.append(("motion_gpio_config_latch_no_sensor",address,value&65535));return
        if (self.pc,address,value) in ((0x20808b,0x3054,1),
                (0x208096,0x3053,0x0205),(0x20809d,0x3033,0x5555)):
            self.adapters.append(('native_clock_commit_mmio',address,value));return
        if address==0x3022 and self.pc==0x2039ec:
            level=self.mem.get((self.r[5]+3)&65535)
            if type(level)is int and 0<=level<=5:
                expected=struct.unpack_from('<H',self.code,2*(0x20378c-0x200000)+2*level)[0]|0x100
                if value==expected:
                    self.adapters.append(('native_brightness',level,value));return
        super().write(address,value)

    def call(self,target,ret):
        if target==0x208dd2:
            raise StockLinkUnavailable("Original PenC physical-link connection is unavailable in this browser")
        self.calls.append(target)
        if self.on_native_call is not None:self.on_native_call(self,target)
        if target==0x201d39 and self.mem[0xca0]==2 and self.motion_pending:
            if self.mem[0xd3d]==0:
                self.write(0xd3d,1);self.motion_pending=False
                self.adapters.append(('host_sensor_edge_native_consumer_owns_count',target))
        if target>=0x200000:
            self.setpc(ret);self.push(0,self.r[7]);self.push(0,self.r[6]);self.setpc(target);return
        sp=self.r[0]
        def args(n):return [self.read(sp+i) for i in range(1,n+1)]
        if target in (0x49db,0x4a75):
            ptr,count,lo,hi=args(4);offset=lo|(hi<<16)
            if not (1<=count<=4096 and 0<=ptr<=0x2000-count and offset%2==0):
                raise RuntimeError('Stock Flash transfer outside word/RAM bounds')
            if target==0x49db:
                if not 0<=offset<=len(self.code)-2*count:raise RuntimeError('Stock Flash read exceeds image')
                for i in range(count):
                    at=offset+2*i
                    source=self.flash if 0x7fd000<=at<0x7ff000 else self.code
                    self.write(ptr+i,struct.unpack_from('<H',source,at-0x7fd000 if source is self.flash else at)[0])
            else:
                if not (ptr==0x822 and count==0x3b and hi==0x7f and lo in (0xd000,0xe000)):
                    raise RuntimeError('Stock Flash program outside native 59-word journal')
                at=lo-0xd000
                for i in range(count):
                    old=struct.unpack_from('<H',self.flash,at+2*i)[0]
                    struct.pack_into('<H',self.flash,at+2*i,old&self.read(ptr+i))
                self.flash_events.append(('program',at,count))
        elif target==0x4c29:
            lo,hi=args(2)
            if hi!=0x7f or lo not in (0xd000,0xe000):raise RuntimeError('Stock erase outside native mirrors')
            at=lo-0xd000;self.flash[at:at+4096]=b'\xff'*4096
            self.flash_events.append(('erase',at,4096))
        elif target==0x4e73:
            if self.pc!=0x205ed1:raise RuntimeError('Stock unknown flash preparation caller')
            self.adapters.append(('native_flash_prepare_host_boundary',target))
        elif target==0x4e8f:
            first,count,bank=args(3)
            if (first,count,bank) not in ((0,24,1),(24,48,1),(72,24,1)):
                raise RuntimeError('Stock unknown internal-ROM display region')
            self.display_requests.append((first,count,bank))
        elif target==0x578c:
            self.adapters.append(('sound_poll_host_completion_owned_by_runtime',target))
        elif target==0x5fbe:
            if self.clock_seconds not in (0,1):raise RuntimeError('Stock RTC requires a single explicit host edge')
            seconds=self.clock_seconds;self.clock_seconds=None
            self.mem[0xcc7]=0
            if seconds and self.mem[0xcc5]:
                s,m,h=[self.mem[a] for a in (0xcc2,0xcc3,0xcc4)]
                if not(0<=s<60 and 0<=m<60 and 0<=h<24):raise RuntimeError('Stock RTC contains invalid native fields')
                t=(h*3600+m*60+s+1)%86400
                self.mem.update({0xcc2:t%60,0xcc3:t//60%60,0xcc4:t//3600,0xcc7:int(s==59)})
            self.adapters.append(('rtc_edge',seconds))
        elif target in (0x63cf,0x603c,0x60b3):
            al,ah,bl,bh=args(4);a=al|(ah<<16);b=bl|(bh<<16)
            if target!=0x63cf and not b:raise RuntimeError('Stock arithmetic division by zero')
            value=a*b if target==0x63cf else a//b if target==0x603c else a%b
            self.r[1:3]=[value&65535,(value>>16)&65535]
        elif target in (0x6129,0x6186):
            a,b=args(2)
            if not b:raise RuntimeError('Stock arithmetic division by zero')
            self.r[1]=a%b if target==0x6129 else a//b
        elif target==0x6260:
            parts=args(5);v=sum(parts[i]<<(16*i) for i in range(4))>>parts[4]
            self.r[1:5]=[(v>>i)&65535 for i in (0,16,32,48)]
        else:raise RuntimeError(f'Stock unmodelled internal ROM {target:06X} at {self.pc:06X}')
        self.setpc(ret)

    def step(self):
        pc=self.pc;op=self.word(pc)
        # These scalar unSP semantics are independent of firmware identity.
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
            shifted>>=mode-3;self.sb=shifted&15;v=(shifted>>4)&65535
            self.r[dst]=v;self.r[6]=nz(self.r[6],v);return
        super().step()

    def invoke(self,entry,args=(),limit=1000000):
        sp,bp=self.r[0],self.r[5]
        for i,v in enumerate(args,1):self.mem[sp+i]=v&65535
        self.call(entry,STOP);end=self.steps+limit
        while self.pc!=STOP:
            if self.steps>=end:raise RuntimeError(f'Stock instruction budget at {self.pc:06X}')
            self.step()
        if (sp,bp)!=(self.r[0],self.r[5]):raise RuntimeError('Stock native stack imbalance')
        return self.r[1]

    def _span(self,start,stops,limit=100000):
        sp,bp=self.r[0],self.r[5];self.setpc(start);end=self.steps+limit
        while self.pc not in stops:
            if self.steps>=end:raise RuntimeError(f'Stock boundary budget at {self.pc:06X}')
            self.step()
        if (sp,bp)!=(self.r[0],self.r[5]):raise RuntimeError('Stock boundary stack imbalance')
        return self.pc

    def boot(self):
        # The adjacent source calls at230082/84 elect and validate the BIN's
        # own 59-word records, then initialize transient UI/RNG/care fields.
        # Zero reset RAM, stack, released GPIO and normal power are host devices.
        self._span(0x230008,{0x230048})
        self.invoke(0x200d21)
        self._span(0x230082,{0x230086},limit=200000)
        self.mem[0xcae]=3
        self.frame(())
        self.release_inputs()

    @property
    def motion_ready(self):return self.mem[0xca0]==2

    @property
    def motion_count(self):return self.mem[0xd41]

    def release_inputs(self):
        # Released host input is deliberately idempotent across snapshots;
        # no clock, pet, stack, register or executed-instruction field changes.
        self.mem.update({0x3000:65535,0x81b:0,0x81c:0,0x81d:0,0x81e:0,
                         0x81f:0,0x820:0,0x821:0})
        self.motion_pending=False

    def _wake(self):
        if self.mem[0xc9c]==0x2e:
            raise RuntimeError('Stock low-battery power wake has no virtual-device contract')
        bp=self.r[5];scratch=(self.r[0]-16)&65535;old=self.mem[scratch]
        self.r[5]=scratch
        try:
            self._span(0x230219,{0x230268})
            self._span(0x230268,{0x23030f})
            self.invoke(0x20c7e6)
            self._span(0x23034c,{0x230354})
            self._span(0x230356,{0x23037e})
        finally:self.mem[scratch]=old;self.r[5]=bp
        self.adapters.append(('selected_native_display_wake',0x230268))

    def frame(self,keys,seconds=0,long=False,motion=False):
        if not isinstance(keys,(list,tuple,set)) or any(k not in ('A','B','C') for k in keys):
            raise ValueError('Invalid stock PenC keys')
        if type(seconds)is not int or not 0<=seconds<=5:raise ValueError('Stock accepts 0..5 host seconds')
        if type(motion)is not bool:raise ValueError('Stock motion event must be boolean')
        self.motion_pending=motion
        # Native200D48 owns debounce/chords; native200DCF owns held-key timing.
        # The generic long hint does not write a firmware input event.
        held=sum({'A':8,'B':16,'C':32}[k] for k in set(keys))
        self.mem[0x3000]=65535^held
        for _ in range(max(1,seconds)):
            self.clock_seconds=int(seconds>0)
            if self.mem[0xc9c] in SLEEP_STATES:
                self.call(0x5fbe,STOP)
                boundary=self._span(0x2301c4,{0x2301f3,0x2301fc})
                self.mem[0xcc7]=0
                if held or boundary==0x2301fc:self._wake()
                else:continue
                self.clock_seconds=0
            self._span(0x230151,{0x23015f},limit=1000000)
            self.invoke(0x2002db)
            self.mem[0xcc7]=0
        self.motion_pending=False
        return self.mem[0xc9c]

# Stable caller-facing name; the explicit class name records the CPU family.
StockCPU=StockPenCCPU
