# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Original TEST4 session; no R8 fixtures, patches, or shared save identity."""
import base64
import copy
import hashlib
import json
import time
from pathlib import Path
import audio_bridge as audio
from audio_completion import CompletionClock
from stock_penc_machine import StockPenCCPU as StockCPU, SLEEP_STATES, StockLinkUnavailable
from stock_penc_render import render as render_pixels
import stock_penc_peripherals as peripherals

SHA='a21e573ba40741603b8b4068817c789c625196ab5e53ddb188b1f57c63c612a1'
FORMAT='PENC_STOCK_WEB_SNAPSHOT_V1'
ADAPTER='penc-stock-test4-1'
CAPABILITIES={'new_game':False,'link':False,'motion':False,'audio':True,'away':False}
# Original200545 dispatcher table200575 maps these three states to20B4AF,
# 2086BA and205878: the physical communication handlers. Their setup occurs
# a later frame after entry, so rejecting only208DD2 can strand the C debounce.
# Reject the complete transition before any of these states becomes a save.
LINK_STATES=frozenset((15,16,19))

class Session:
    def __init__(self,firmware_path,profile_path,identity):
        code=Path(firmware_path).read_bytes()
        raw=Path(profile_path).read_bytes();profile=json.loads(raw.decode('utf-8-sig'))
        if len(code)!=8388608 or hashlib.sha256(code).hexdigest()!=SHA:
            raise ValueError('這份原版超代彩 BIN 尚未驗證。')
        if profile.get('family')!='penc-stock' or profile.get('sha256')!=SHA or profile.get('adapter')!='penc-stock-test4':
            raise ValueError('原版超代彩 BIN 與機型設定不符。')
        self.profile_sha=hashlib.sha256(raw).hexdigest();self.identity=identity
        self.cpu=StockCPU(code);self.cpu.boot();self.cpu.release_inputs()
        self.last_image=None;self.sound=CompletionClock();self._attach()

    def _attach(self):
        self.cpu.on_native_call=lambda cpu,target:(audio.capture(cpu,target),self.sound.observe(cpu,target))

    def render(self,force=False):
        c=self.cpu;m=c.mem
        sleeping=m[0xc9c] in SLEEP_STATES
        pixels=bytes([0,0,0,255])*9216 if sleeping else render_pixels(c)
        encoded=base64.b64encode(pixels).decode('ascii') if force or pixels!=self.last_image else None
        self.last_image=pixels
        result={'family':'penc-stock','family_name':'PenC 原版超代彩 · TEST4 Metal Empire',
                'capabilities':CAPABILITIES.copy(),'rgba':encoded,'sha256':SHA,'display_sleeping':sleeping,
                'clock':f'{m[0xcc4]:02}:{m[0xcc3]:02}:{m[0xcc2]:02}',
                'state':m[0xc9c],'substate':m[0xc9e],'species':[m[0x826]],
                'steps':c.steps,'warnings':[],'time_rate':1,
                'motion_supported':False,'motion_ready':False,'motion_count':0,
                'sound_events':[],'native_link':{'supported':False,'connected':False},
                'native_settings':peripherals.settings(c),
                'native_boot':{'supported':True,'hardware_boot':False,'phase':'native-embedded-save'},
                'continuity':{'supported':False,'started':False,'pending_seconds':0,'safe':False}}
        if hasattr(peripherals,'motion_metadata'):result.update(peripherals.motion_metadata(c))
        result['capabilities']['motion']=result['motion_supported']
        return result

    def _sound_snapshot(self):
        c=self.sound;m=self.cpu.mem
        if c.remaining is None or c.remaining<=0 or m.get(0xca1)!=1 or c.marker!=(m.get(0xca9),m.get(0xcaa)):
            return None
        return {'remaining_ms':c.remaining,'speed':c.speed,'marker':list(c.marker)}

    def snapshot(self):
        c=self.cpu
        return {'format':FORMAT,'adapter':ADAPTER,'family':'penc-stock','core_sha256':self.identity,
                'profile_sha256':self.profile_sha,'firmware_sha256':SHA,'not_device_save':True,
                'ram':{f'{a:04X}':v for a,v in c.mem.items()},'registers':list(c.r),'fr':c.fr,
                'mmio':{f'{a:04X}':v for a,v in c.mmio.items()},
                'virtual_flash_mirrors_hex':bytes(c.flash).hex(),'executed_instructions':c.steps,
                'sound_completion':self._sound_snapshot()}

    def restore(self,p):
        if not isinstance(p,dict):raise ValueError('原版快照格式不正確。')
        for k,v in [('format',FORMAT),('adapter',ADAPTER),('family','penc-stock'),('core_sha256',self.identity),
                    ('profile_sha256',self.profile_sha),('firmware_sha256',SHA),('not_device_save',True)]:
            if p.get(k)!=v:raise ValueError('快照與目前原版 BIN／核心不符：'+k)
        raw=p.get('ram')
        if not isinstance(raw,dict) or len(raw)!=8193:raise ValueError('原版 RAM 大小不正確。')
        mem={}
        for k,v in raw.items():
            if not isinstance(k,str) or len(k)!=4:raise ValueError('原版 RAM 位址錯誤。')
            try:a=int(k,16)
            except ValueError:raise ValueError('原版 RAM 位址錯誤。') from None
            if k!=f'{a:04X}' or not(0<=a<8192 or a==0x3000) or type(v)is not int or not 0<=v<=65535:
                raise ValueError('原版 RAM 資料錯誤。')
            mem[a]=v
        if not set(range(8192)).issubset(mem):raise ValueError('原版 RAM 不完整。')
        if mem[0xc9c] in LINK_STATES:raise ValueError('此快照停在尚未支援的原版連線流程，未取代目前進度。')
        if not(0<=mem[0xcc2]<60 and 0<=mem[0xcc3]<60 and 0<=mem[0xcc4]<24):raise ValueError('原版時鐘錯誤。')
        registers=p.get('registers');fr=p.get('fr');steps=p.get('executed_instructions')
        if not isinstance(registers,list) or len(registers)!=8 or any(type(v)is not int or not 0<=v<=65535 for v in registers):raise ValueError('原版暫存器錯誤。')
        if type(fr)is not int or not 0<=fr<=65535 or type(steps)is not int or not 0<=steps<=10**15:raise ValueError('原版執行狀態錯誤。')
        flash_hex=p.get('virtual_flash_mirrors_hex')
        if not isinstance(flash_hex,str) or len(flash_hex)!=16384:raise ValueError('原版 Flash 長度錯誤。')
        try:flash=bytes.fromhex(flash_hex)
        except ValueError:raise ValueError('原版 Flash 格式錯誤。') from None
        if len(flash)!=8192:raise ValueError('原版 Flash 長度錯誤。')
        sound=CompletionClock();state=p.get('sound_completion')
        if state is not None:
            if not isinstance(state,dict) or set(state)!={'remaining_ms','speed','marker'}:raise ValueError('音效快照格式錯誤。')
            remaining,speed,marker=state['remaining_ms'],state['speed'],state['marker']
            if (type(remaining)not in (int,float) or not 0<remaining<=32768 or
                type(speed)not in (int,float) or not 1<=speed<=4 or
                type(marker)is not list or len(marker)!=2 or any(type(v)is not int or not 0<=v<=65535 for v in marker) or
                mem.get(0xca1)!=1 or marker!=[mem.get(0xca9),mem.get(0xcaa)]):raise ValueError('音效快照資料錯誤。')
            sound.code=self.cpu.code;duration=sound.restored_duration(mem)
            if duration is None or remaining>duration/speed:raise ValueError('音效剩餘時間超出原生音符範圍。')
            sound.admitted=True;sound.remaining=remaining;sound.marker=tuple(marker);sound.speed=speed;sound.requested_speed=speed
        mmio=p.get('mmio')
        allowed={0x3001,0x3002,0x3003,0x3004,0x3005,0x3006,0x3007,0x3014,0x3015,0x3016,0x3050,0x3051}
        if not isinstance(mmio,dict) or set(mmio)!={f'{a:04X}' for a in allowed}:raise ValueError('原版裝置快照錯誤。')
        device={}
        for key,value in mmio.items():
            if not isinstance(key,str) or key not in {f'{a:04X}' for a in allowed} or type(value)is not int or not 0<=value<=65535:raise ValueError('原版裝置資料錯誤。')
            device[int(key,16)]=value
        candidate=StockCPU(self.cpu.code)
        candidate.mem=mem;candidate.r=list(registers);candidate.fr=fr;candidate.steps=steps;candidate.flash=bytearray(flash)
        candidate.mmio=device
        candidate.release_inputs()
        previous,last,old_sound=self.cpu,self.last_image,self.sound
        try:
            self.cpu=candidate;self.sound=sound;self._attach()
            return self.render(force=True)
        except Exception:
            self.cpu,self.last_image,self.sound=previous,last,old_sound;self._attach();raise

    def dispatch(self,req):
        op=req.get('op')
        if op=='snapshot':return self.snapshot()
        if op=='restore':return self.restore(req.get('snapshot'))
        if op=='release':self.cpu.release_inputs();return self.snapshot()
        if op=='catch-up':
            out=self.render();out['catch_up']={'processed_seconds':0,'remaining_seconds':0,'blocked_reason':''};return out
        if op in ('new-game','reset'):raise ValueError('原版目前依 BIN 原有進度開機；新遊戲重置尚未驗證。')
        if op and op.startswith('native-link'):raise ValueError('原版超代彩的網路連線介面尚未接上。')
        if op!='frame':raise ValueError('原版超代彩不支援此操作。')
        keys=req.get('keys',[]);seconds=req.get('seconds',0);frames=req.get('frames',1)
        if not isinstance(keys,list) or any(k not in ('A','B','C') for k in keys):raise ValueError('按鍵資料錯誤。')
        if type(seconds)is not int or not 0<=seconds<=5 or type(frames)is not int or not 1<=frames<=3:raise ValueError('原版更新範圍錯誤。')
        gpio=65535^sum({'A':8,'B':16,'C':32}[k] for k in set(keys))
        minimum=4 if self.cpu.mem.get(0x3000,65535)!=gpio else 1
        frames=max(frames,minimum)
        previous={k:copy.deepcopy(v) for k,v in self.cpu.__dict__.items() if k not in ('_stock_render_cache','on_native_call')}
        cache=getattr(self.cpu,'_stock_render_cache',None)
        old_sound=copy.deepcopy(self.sound);last=self.last_image;start=time.perf_counter();completed=0;started=False
        audio.begin(self.cpu.code)
        try:
            for i in range(frames):
                self.sound.begin(self.cpu.code,req.get('audio_elapsed_ms') if i==0 else 0,req.get('audio_speed',2))
                self.cpu.frame(keys,seconds=seconds if i==0 else 0,long=bool(req.get('long',False)),motion=bool(req.get('motion',False)) if i==0 else False)
                if self.cpu.mem[0xc9c] in LINK_STATES:raise StockLinkUnavailable('Original physical communication state is not admitted')
                self.sound.commit(self.cpu);started=started or self.sound.just_started;completed+=1
                if completed>=minimum and (time.perf_counter()-start)*1000>=25:break
            native_ms=(time.perf_counter()-start)*1000
            out=self.render();out.update(completed_frames=completed,native_ms=round(native_ms,1),frame_ms=round((time.perf_counter()-start)*1000,1),sound_events=audio.end(),sound_clock_started=started)
            return out
        except Exception as error:
            audio.end(discard=True)
            self.cpu.__dict__.clear();self.cpu.__dict__.update(previous)
            if cache is not None:self.cpu._stock_render_cache=cache
            self.sound=old_sound;self.last_image=last;self._attach()
            if isinstance(error,StockLinkUnavailable):
                out=self.render(force=True)
                out['native_link_notice']='原版 TEST4 的網路連線尚未接上。進度已保留；關閉選單後按 C 可返回遊戲。'
                return out
            raise
