# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Wall-time watermark paired with native state; never edits care or RTC RAM.

The browser can stop at any time. Only committed native elapsed seconds move
this watermark; saving/reopening does not. Old snapshots begin tracking now.
Title/time/egg setup starts the watermark on first entering ordinary play.
"""
import math
import time

def now_ms():
    return int(time.time()*1000)

def initialize(bench, now=None):
    if now is None:now=now_ms()
    bench._continuity={'version':1,'anchor_ms':now,'started':bench.ram.get(0xc9c) not in (0,2,3)}
    bench._away_transient_owned=False

def snapshot(bench):
    if not hasattr(bench,'_continuity'):initialize(bench)
    return {**bench._continuity,'away_transient':bool(getattr(bench,'_away_transient_owned',False))}

def restore(bench,payload,now=None):
    if payload is None:
        initialize(bench,now)
        return
    if (not isinstance(payload,dict) or payload.get('version')!=1
        or type(payload.get('started')) is not bool
        or type(payload.get('away_transient',False)) is not bool
        or type(payload.get('anchor_ms')) not in (int,float)
        or not 946684800000<=payload['anchor_ms']<=4102444800000
        or not math.isfinite(payload['anchor_ms'])):
        raise ValueError('Invalid elapsed-care watermark')
    bench._continuity={k:payload[k] for k in ('version','anchor_ms','started')}
    bench._away_transient_owned=payload.get('away_transient',False) and bench.ram.get(0xc9c) in (24,25,36)

def consume(bench,seconds,now=None):
    if type(seconds) is not int or seconds<0:raise ValueError('Invalid committed seconds')
    if now is None:now=now_ms()
    data=snapshot(bench)
    if not data['started']:
        data['anchor_ms']=now
        if bench.ram.get(0xc9c)==4:data['started']=True
    else:
        data['anchor_ms']+=seconds*1000
    bench._continuity=data

def metadata(bench,now=None):
    if now is None:now=now_ms()
    data=snapshot(bench)
    gap=now-data['anchor_ms']
    return {'started':data['started'],'pending_seconds':max(0,int(gap//1000)) if data['started'] else 0,
            'clock_rollback':bool(data['started'] and gap<-1000)}
