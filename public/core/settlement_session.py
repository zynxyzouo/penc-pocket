# SPDX-License-Identifier: GPL-3.0-or-later
"""Freeze the offline target while the browser is busy settling it.

Only committed native seconds move the normal watermark. A snapshot taken
mid-job excludes processing time in its exported watermark, without changing
the live target; reloading therefore preserves remaining debt exactly once.
"""
import continuity


def policy(bench, available):
    return getattr(bench,'_offline_policy',None) or ('custody' if available else 'native')


def restore_policy(bench, payload, available):
    if payload is None:
        bench._offline_policy=None
        return
    if (type(payload) is not dict or set(payload)!= {'version','mode'}
            or type(payload.get('version')) is not int or payload['version']!=1
            or payload.get('mode') not in ('native','custody')
            or (payload['mode']=='custody' and not available)):
        raise ValueError('Invalid or unsupported offline policy')
    bench._offline_policy=payload['mode']


def begin(bench, now=None):
    if now is None:now=continuity.now_ms()
    if getattr(bench,'_settlement_window',None) is None:
        bench._settlement_window={'target_ms':now,'started_ms':now}


def metadata(bench, now=None):
    window=getattr(bench,'_settlement_window',None)
    return continuity.metadata(bench,now=window['target_ms'] if window else now)


def snapshot(bench, now=None):
    if now is None:now=continuity.now_ms()
    value=continuity.snapshot(bench)
    window=getattr(bench,'_settlement_window',None)
    if window:value['anchor_ms']+=max(0,now-window['started_ms'])
    return value


def end(bench, now=None):
    if getattr(bench,'_settlement_window',None) is not None:
        bench._continuity=snapshot(bench,now=now)
        reset(bench)


def reset(bench):
    bench._settlement_window=None
