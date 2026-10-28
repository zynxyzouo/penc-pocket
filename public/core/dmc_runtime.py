# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""DMC web session. Source image is immutable; snapshots never program a device."""
import base64
import copy
import hashlib
import json
import time
from pathlib import Path
from dmc_machine import DmcCPU
from dmc_render import render as render_pixels

SHA='3457140c5f07211abdd756462693c67c824c4c45c26a7ca91e4323df476701dc'
FORMAT='DMC_WEB_SNAPSHOT_V1'
ADAPTER='dmc-linedog-v41-1'
CAPABILITIES={'new_game':False,'link':False,'motion':False,'audio':False,'away':False}

class Session:
    def __init__(self,firmware_path,profile_path,identity):
        code=Path(firmware_path).read_bytes()
        raw=Path(profile_path).read_bytes();profile=json.loads(raw.decode('utf-8-sig'))
        if len(code)!=8388608 or hashlib.sha256(code).hexdigest()!=SHA:
            raise ValueError('這份 DMC BIN 尚未驗證，未更換執行中的機器。')
        if profile.get('family')!='dmc' or profile.get('sha256')!=SHA or profile.get('adapter')!='dmc-linedog-v41':
            raise ValueError('DMC BIN 與機型設定不符。')
        self.profile_sha=hashlib.sha256(raw).hexdigest();self.identity=identity
        self.cpu=DmcCPU(code);self.cpu.boot();self.cpu.release_inputs();self.last_image=None

    def render(self,force=False):
        sleeping=self.cpu.mem[0xc88] in (0x1c,0x1d,0x1e,0x1f)
        pixels=bytes([0,0,0,255])*9216 if sleeping else render_pixels(self.cpu)
        encoded=base64.b64encode(pixels).decode('ascii') if force or pixels!=self.last_image else None
        self.last_image=pixels
        m=self.cpu.mem
        return {'family':'dmc','family_name':'DMC 彩機 · 線條小狗 v4.1',
                'capabilities':CAPABILITIES.copy(),'rgba':encoded,'sha256':SHA,'display_sleeping':sleeping,
                'clock':f'{m[0xcaf]:02}:{m[0xcae]:02}:{m[0xcad]:02}',
                'state':m[0xc88],'substate':m[0xc8a],'species':[m[0x826]],
                'steps':self.cpu.steps,'warnings':['DMC 部分硬體介面尚未接上'],
                'time_rate':1,'motion_ready':False,'motion_supported':False,
                'sound_events':[],'native_link':{'supported':False,'connected':False},
                'native_settings':{'supported':False},
                'native_boot':{'supported':True,'hardware_boot':False,'phase':'native-embedded-save'},
                'continuity':{'supported':False,'started':False,'pending_seconds':0,'safe':False}}

    def snapshot(self):
        c=self.cpu
        return {'format':FORMAT,'adapter':ADAPTER,'family':'dmc','core_sha256':self.identity,
                'profile_sha256':self.profile_sha,'firmware_sha256':SHA,'not_device_save':True,
                'ram':{f'{a:04X}':v for a,v in c.mem.items()},
                'registers':list(c.r),'fr':c.fr,
                'virtual_flash_mirrors_hex':bytes(c.flash).hex(),'executed_instructions':c.steps}

    def restore(self,p):
        if not isinstance(p,dict):raise ValueError('DMC 快照格式不正確。')
        for k,v in [('format',FORMAT),('adapter',ADAPTER),('family','dmc'),('core_sha256',self.identity),
                    ('profile_sha256',self.profile_sha),('firmware_sha256',SHA),('not_device_save',True)]:
            if p.get(k)!=v:raise ValueError('快照與目前 DMC BIN／核心不符：'+k)
        raw=p.get('ram')
        if not isinstance(raw,dict) or not 8192<=len(raw)<=8193:raise ValueError('DMC RAM 大小不正確。')
        mem={}
        for k,v in raw.items():
            if not isinstance(k,str) or len(k)!=4:raise ValueError('DMC RAM 位址錯誤。')
            try:a=int(k,16)
            except ValueError:raise ValueError('DMC RAM 位址錯誤。') from None
            if k!=f'{a:04X}' or not(0<=a<8192 or a==0x3000) or type(v)is not int or not 0<=v<=65535:
                raise ValueError('DMC RAM 資料錯誤。')
            mem[a]=v
        if not set(range(8192)).issubset(mem):raise ValueError('DMC RAM 不完整。')
        if not(0<=mem[0xcad]<60 and 0<=mem[0xcae]<60 and 0<=mem[0xcaf]<24):raise ValueError('DMC 時鐘錯誤。')
        registers=p.get('registers');fr=p.get('fr');steps=p.get('executed_instructions')
        if not isinstance(registers,list) or len(registers)!=8 or any(type(v)is not int or not 0<=v<=65535 for v in registers):raise ValueError('DMC 暫存器錯誤。')
        if type(fr)is not int or not 0<=fr<=65535 or type(steps)is not int or not 0<=steps<=10**15:raise ValueError('DMC 執行狀態錯誤。')
        flash_hex=p.get('virtual_flash_mirrors_hex')
        if not isinstance(flash_hex,str) or len(flash_hex)!=16384:raise ValueError('DMC Flash 長度錯誤。')
        try:flash=bytes.fromhex(flash_hex)
        except ValueError:raise ValueError('DMC Flash 格式錯誤。') from None
        if len(flash)!=8192:raise ValueError('DMC Flash 長度錯誤。')
        candidate=DmcCPU(self.cpu.code)
        candidate.mem=mem;candidate.r=list(registers);candidate.fr=fr;candidate.steps=steps;candidate.flash=bytearray(flash)
        candidate.release_inputs()
        previous=self.cpu;last=self.last_image
        try:
            self.cpu=candidate
            return self.render(force=True)
        except Exception:
            self.cpu=previous;self.last_image=last;raise

    def dispatch(self,req):
        op=req.get('op')
        if op=='snapshot':return self.snapshot()
        if op=='restore':return self.restore(req.get('snapshot'))
        if op=='release':self.cpu.release_inputs();return self.snapshot()
        if op=='catch-up':
            out=self.render();out['catch_up']={'processed_seconds':0,'remaining_seconds':0,'blocked_reason':''};return out
        if op in ('new-game','reset'):raise ValueError('彩機目前從 BIN 原有進度開機；網頁重開新遊戲尚未驗證。')
        if op and op.startswith('native-link'):raise ValueError('彩機的連線介面尚未接上。')
        if op!='frame':raise ValueError('DMC 不支援此操作。')
        keys=req.get('keys',[]);seconds=req.get('seconds',0);frames=req.get('frames',1)
        if not isinstance(keys,list) or any(k not in ('A','B','C') for k in keys):raise ValueError('按鍵資料錯誤。')
        if type(seconds)is not int or not 0<=seconds<=5 or type(frames)is not int or not 1<=frames<=3:raise ValueError('DMC 更新範圍錯誤。')
        gpio=65535^sum({'A':8,'B':16,'C':32}[k] for k in set(keys))
        # Browser taps (including accessibility/paused controls) may enqueue
        # down/up immediately. Hold each edge through the actual native four
        # scan debounce; never manufacture an 081B event or gameplay decision.
        minimum=4 if self.cpu.mem.get(0x3000,65535)!=gpio else 1
        frames=max(frames,minimum)
        # Decoded immutable pixels are presentation cache, not game state.
        previous={k:copy.deepcopy(v) for k,v in self.cpu.__dict__.items() if k!='_dmc_render_cache'}
        cache=getattr(self.cpu,'_dmc_render_cache',None)
        last=self.last_image;start=time.perf_counter();completed=0
        try:
            for i in range(frames):
                self.cpu.frame(keys,seconds=seconds if i==0 else 0,long=bool(req.get('long',False)))
                completed+=1
                if completed>=minimum and (time.perf_counter()-start)*1000>=25:break
            native_ms=(time.perf_counter()-start)*1000
            out=self.render();out.update(completed_frames=completed,native_ms=round(native_ms,1),frame_ms=round((time.perf_counter()-start)*1000,1))
            return out
        except Exception:
            self.cpu.__dict__.clear();self.cpu.__dict__.update(previous)
            if cache is not None:self.cpu._dmc_render_cache=cache
            self.last_image=last;raise
