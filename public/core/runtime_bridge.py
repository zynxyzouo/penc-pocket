# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Optional host cadence and motion input for the immutable native web core.

Motion supplies accepted host shake events at the audited native consumer. It
does not emulate the physical accelerometer, IRQ timing, or choose game results.
The BIN and the five snapshot-identity core files are never changed.
"""
import hashlib
import copy
import json
import math
import time

import bench as bench_module
from cpu_accelerator import AcceleratedCPU as CPU
import web_adapter as n
import audio_bridge as audio
import audio_completion
import network_battle as link
import native_link_guard
import native_connector
import native_boot
import native_settings
import continuity
import away_bridge
import sound_state


SENSOR_SIGNATURES = (
    (0x201bcc, 0x201c42, '60601d930236234396d672a6423a5552cbe2f93c3b752ebfb8e0652fed23b172'),
    (0x201cda, 0x201d1e, 'd0875163bdc59798c9ca51e0d09999a0a9ae2374784b5989404078363ad3c22d'),
    (0x201d1e, 0x201d49, '5f71630944839ed811e61b2df0c9bda18108e3ad4f2ee8204cb4d6c992de565d'),
)
BATCH_BUDGET_SECONDS = .025
_pending = False
_active_code = None
_consumer_seen = False


def supports_motion(code):
    """Admit only matching native functions, independent of release filenames."""
    return all(hashlib.sha256(code[2*(start-0x200000):2*(end-0x200000)]).hexdigest() == digest
               for start, end, digest in SENSOR_SIGNATURES)


class MotionCPU(CPU):
    def read(self,address):
        if address==0x3053:
            handled,value=native_boot.handles_read(self,address)
            if handled:return value
        return super().read(address)

    def write(self,address,value):
        if address in (0x3054,0x3053,0x3033) and native_boot.handles_write(self,address,value):return
        if address==0x3022 and native_settings.handles_write(self,address,value):return
        return super().write(address,value)

    def __init__(self, code, *args, **kwargs):
        super().__init__(code, *args, **kwargs)
        self.motion_supported = self.allow_adapters and supports_motion(code)
        self.host_motion_request = code is _active_code

    def call(self, target, ret):
        global _pending, _consumer_seen
        if native_connector.cable.call(self,target,ret):
            return
        audio.capture(self, target)
        audio_completion.clock.observe(self, target)
        if self.motion_supported:
            if target == 0x201bcc:
                # Audited RAM effects of setup; peripheral writes are replaced
                # by the host event source. Gameplay countdowns remain native.
                initial = {0xd33:0, 0xca0:2, 0xd3d:0, 0xd3f:60,
                           0xd3e:0, 0xd40:0, 0xd41:0}
                initial.update({a:0 for a in range(0xd37, 0xd3d)})
                for address, value in initial.items():
                    self.write(address, value)
                self.calls.append(target)
                self.adapters.append({'target':'201BCC', 'kind':'host sensor setup; no hardware IRQ emulation'})
                self.setpc(ret)
                return
            if target == 0x201d1e:
                self.write(0xca0, 0)
                self.write(0xd3d, 0)
                if self.host_motion_request:
                    _pending = False
                self.calls.append(target)
                self.adapters.append({'target':'201D1E', 'kind':'host sensor teardown; accepted native count retained'})
                self.setpc(ret)
                return
            if target == 0x201cda and self.host_motion_request and self.mem.get(0xca0) == 2:
                _consumer_seen = True
                if _pending and self.mem.get(0xd3d) == 0:
                    self.write(0xd3d, 1)
                    _pending = False
                    self.adapters.append({'target':'201CDA', 'kind':'one host shake latch; native consumer owns count and result'})
        # Native CALL pushes its own return address. The setup/teardown adapters
        # above return directly; the consumer executes unchanged native code.
        return super().call(target, ret)


# Bench.execute resolves CPU through its module globals, including instances
# created by web_adapter.load. Unknown signatures retain strict CPU behavior.
bench_module.CPU = MotionCPU


def clear_motion():
    global _pending, _active_code, _consumer_seen
    _pending = False
    _active_code = None
    _consumer_seen = False


def motion_metadata():
    if n.bench is None:
        return {'motion_supported':False, 'motion_ready':False, 'motion_count':0}
    supported = supports_motion(n.bench.code)
    m = n.bench.ram
    # Known capture states also make a restored capture immediately ready.
    # Other native consumers may report ready only when observed this update.
    capture = ((m.get(0xc9c) == 10 and m.get(0xc9e) == m.get(0xc9f) == 1)
               or (m.get(0xc9c) == 13 and m.get(0xc9e) == m.get(0xc9f) == 3))
    return {'motion_supported':supported,
            'motion_ready':bool(supported and m.get(0xca0) == 2 and (capture or _consumer_seen)),
            'motion_count':m.get(0xd41, 0) if supported else 0}


def advance(keys, seconds=0, long=False, frames=1, motion=False, audio_elapsed_ms=None, audio_speed=1):
    """Run 1..3 atomic native calls under a soft 25ms budget, then draw once.

    RTC seconds and host-long input occur only on the first call. Native key
    sampling retains held keys while suppressing repeated press edges. A
    motion event lives only for this request, including when execution fails.
    """
    global _pending, _active_code, _consumer_seen
    if n.bench is None:
        raise ValueError('請先選取 BIN。')
    if not isinstance(keys, list) or any(k not in ('A', 'B', 'C') for k in keys):
        raise ValueError('Invalid key input')
    if type(frames) is not int or not 1 <= frames <= 3:
        raise ValueError('Native batch requires 1..3 frames')
    if type(seconds) is not int or not 0 <= seconds <= 5:
        raise ValueError('Host clock frames accept 0..5 seconds; no bulk catch-up')
    if type(motion) is not bool:
        raise ValueError('Motion input must be a single boolean pulse')
    if audio_elapsed_ms is not None and (type(audio_elapsed_ms) not in (int,float) or not math.isfinite(audio_elapsed_ms) or not 0<=audio_elapsed_ms<=5000):
        raise ValueError('Sound elapsed time must be a finite 0..5000 milliseconds')
    if type(audio_speed) not in (int,float) or not math.isfinite(audio_speed) or not 1<=audio_speed<=4:
        raise ValueError('Sound speed must be a finite 1..4 multiplier')
    clear_motion()
    audio.end(discard=True)
    _active_code = n.bench.code
    audio.begin(_active_code)
    _pending = motion and supports_motion(_active_code)
    started = time.perf_counter()
    completed = 0
    sound_clock_started = False
    link_notice = None
    try:
        for index in range(frames):
            if native_connector.cable.connected and 'C' in keys and native_link_guard.pending(n.bench):
                native_connector.cable.disconnect(n.bench)
                break
            if native_link_guard.pending(n.bench) and not native_connector.cable.handles(n.bench):
                link_notice = native_link_guard.recover(n.bench)
                break
            if index and time.perf_counter()-started >= BATCH_BUDGET_SECONDS:
                break
            if not native_connector.cable.begin(n.bench):
                break
            try:
                n.keep_preview_awake()
                audio_completion.clock.begin(n.bench.code,
                    elapsed_ms=audio_elapsed_ms if index==0 or audio_elapsed_ms is None else 0,
                    speed=audio_speed)
                n.native_frame(n.bench, set(keys), seconds=seconds if index == 0 else 0,
                               long=bool(long and index == 0))
                audio_completion.clock.commit(n.bench)
                native_connector.cable.commit(n.bench)
                continuity.consume(n.bench,seconds if index==0 else 0)
                sound_clock_started = sound_clock_started or audio_completion.clock.just_started
            except Exception:
                native_connector.cable.rollback(n.bench)
                raise
            completed += 1
            if native_link_guard.pending(n.bench) and not native_connector.cable.handles(n.bench):
                link_notice = native_link_guard.recover(n.bench)
                break
        native_ms = (time.perf_counter()-started)*1000
        result = n.render()
        result.update({'completed_frames':completed, 'native_ms':round(native_ms, 1),
                       'frame_ms':round((time.perf_counter()-started)*1000, 1)})
        result.update(motion_metadata())
        result['native_link'] = native_connector.cable.metadata(n.bench)
        result['sound_events'] = audio.end()
        result['sound_clock_started'] = sound_clock_started
        if link_notice:
            result['native_link_notice'] = link_notice
        return result
    finally:
        audio.end(discard=True)
        audio_completion.clock.abort()
        _pending = False
        _active_code = None


def _dispatch(request_json):
    """Compatible JSON dispatcher; only frame cadence and optional motion change."""
    req = json.loads(request_json)
    op = req['op']
    audio.end(discard=True)
    if op.startswith('native-link-'):
        if n.bench is None:raise ValueError('請先載入 BIN。')
        cable=native_connector.cable
        if op=='native-link-info':
            return json.dumps({'native_link':cable.metadata(n.bench)},separators=(',', ':'))
        if op=='native-link-connect':
            cable.connect(n.bench,req['session'],req['slot'])
        elif op=='native-link-receive':
            meta=cable.receive(n.bench,req['session'],req['packets'],req.get('accepted'))
            return json.dumps({'native_link':meta},separators=(',', ':'))
        elif op=='native-link-disconnect':
            cable.disconnect(n.bench)
        else:raise ValueError('Unknown native link operation')
        result=n.render(force=True)
        result.update(motion_metadata())
        result['native_link']=cable.metadata(n.bench)
        return json.dumps(result,separators=(',', ':'))
    if op.startswith('link-'):
        clear_motion()
        if op == 'link-describe':
            result = link.describe()
        elif op == 'link-calculate':
            result = link.calculate({k:req[k] for k in ('players', 'shakes', 'seed')})
        elif op == 'link-jogress-preview':
            result = link.preview_jogress(req['players'])
        else:
            raise ValueError('Unknown link operation')
        return json.dumps(result, separators=(',', ':'))
    if op == 'frame':
        result = advance(req.get('keys', []), req.get('seconds', 0), req.get('long', False),
                         req.get('frames', 1), req.get('motion', False),
                         req.get('audio_elapsed_ms'), req.get('audio_speed', 1))
        return json.dumps(result, separators=(',', ':'))
    if op=='present':
        if n.bench is None:raise ValueError('No firmware loaded')
        # Refresh after cancelling catch-up without advancing a native frame.
        result=n.render(force=True)
        result.update(motion_metadata())
        result['native_link']=native_connector.cable.metadata(n.bench)
        return json.dumps(result,separators=(',',':'))
    if op=='catch-up':
        if n.bench is None:raise ValueError('No firmware loaded')
        present=req.get('present',True)
        if type(present) is not bool:raise ValueError('Presentation flag must be boolean')
        due=continuity.metadata(n.bench)['pending_seconds']
        if native_connector.cable.connected:
            progress={'processed_seconds':0,'remaining_seconds':due,'blocked_reason':'連線中請先完成或中斷連線，再補算離開時間。'}
        else:
            progress=away_bridge.catch_up(n.bench,due,budget_ms=35)
            continuity.consume(n.bench,progress['processed_seconds'])
        # Progress packets need no image/clock projection. Always present the
        # final committed state and any native boundary that prevents catch-up.
        result=n.render() if present or progress['remaining_seconds']==0 or progress['blocked_reason'] else {}
        result['catch_up']=progress
        result.update(motion_metadata())
        result['native_link']=native_connector.cable.metadata(n.bench)
        return json.dumps(result,separators=(',',':'))
    if op=='new-game':
        if n.bench is None:raise ValueError('No firmware loaded')
        candidate=copy.deepcopy(n.bench)
        native_boot.new_game(candidate)
        n.bench=candidate;n.sprite_cache={};n.last_scene=None
        clear_motion();native_connector.cable.clear();audio_completion.clock.clear()
        continuity.initialize(candidate)
        result=advance([])
        result.pop('sound_events',None)
        return json.dumps(result,separators=(',',':'))
    if op in ('load', 'release', 'restore', 'reset'):
        clear_motion()
    if op in ('load', 'restore', 'reset'):
        audio_completion.clock.clear()
        native_connector.cable.clear()
    if op == 'reset':
        if n.bench is None:
            raise ValueError('請先選取 BIN。')
        n.bench.reset()
        continuity.initialize(n.bench)
        n.sprite_cache = {}
        n.last_scene = None
        result = advance([])
        result.pop('sound_events', None)
    else:
        # Original loader/snapshot validation and snapshot identity stay intact.
        result = json.loads(n.dispatch(request_json))
        if op=='load':continuity.initialize(n.bench)
        elif op=='restore':
            continuity.restore(n.bench,req['snapshot'].get('continuity'))
            sound_state.restore(n.bench,req['snapshot'].get('sound_completion'))
        if op in ('load', 'restore'):
            if native_connector.supports(n.bench.code) and native_link_guard.pending(n.bench):
                native_connector.cable.disconnect(n.bench)
                result=n.render(force=True)
            result.update(motion_metadata())
            result['native_link']=native_connector.cable.metadata(n.bench)
    return json.dumps(result, separators=(',', ':'))


def _transaction(request_json):
    # Restore includes native transport cleanup. Commit both, or preserve the
    # entire live game/session if either snapshot validation or cleanup fails.
    req=json.loads(request_json)
    if req.get('op') not in ('restore','new-game') or n.bench is None:
        return _dispatch(request_json)
    previous_bench=n.bench
    previous_state=copy.deepcopy(previous_bench.__dict__)
    previous_cache,previous_scene=n.sprite_cache,n.last_scene
    cable=native_connector.cable
    previous_cable=copy.deepcopy({k:v for k,v in cable.__dict__.items() if k!='bench'})
    previous_owner=cable.bench
    previous_clock=copy.deepcopy(audio_completion.clock.__dict__)
    try:
        return _dispatch(request_json)
    except Exception:
        n.bench=previous_bench
        previous_bench.__dict__.clear();previous_bench.__dict__.update(previous_state)
        n.sprite_cache,n.last_scene=previous_cache,previous_scene
        cable.__dict__.clear();cable.__dict__.update(previous_cable);cable.bench=previous_owner
        audio_completion.clock.__dict__.clear();audio_completion.clock.__dict__.update(previous_clock)
        raise


def dispatch(request_json):
    req=json.loads(request_json)
    result=json.loads(_transaction(request_json))
    if n.bench is not None:
        if result.get('format')==n.FORMAT:
            result['continuity']=continuity.snapshot(n.bench)
            result['sound_completion']=sound_state.snapshot(n.bench)
        elif 'clock' in result or 'catch_up' in result:
            result['native_boot']=native_boot.metadata(n.bench)
            result['native_settings']=native_settings.metadata(n.bench)
            result['continuity']=continuity.metadata(n.bench)
            result['continuity']['safe']=away_bridge.safe(n.bench)
    return json.dumps(result,separators=(',',':'))
