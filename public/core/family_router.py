# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Family selection is independent of the legacy PenC snapshot identity."""
import json
from pathlib import Path
import runtime_bridge as penc
from dmc_runtime import Session as DmcSession
from stock_penc_runtime import Session as StockSession
active='penc'
dmc=None
stock=None

def dispatch(request_json):
    global active,dmc,stock
    req=json.loads(request_json)
    if req.get('op')=='load':
        profile=json.loads(Path(req['profile_path']).read_text(encoding='utf-8-sig'))
        family=profile.get('family','penc')
        if family=='dmc':
            candidate=DmcSession(req['bin_path'],req['profile_path'],req.get('dmc_core_sha256',req['core_sha256']))
            out=candidate.render(force=True)
            dmc=candidate;active='dmc'
        elif family=='penc-stock':
            candidate=StockSession(req['bin_path'],req['profile_path'],req.get('stock_core_sha256',req['core_sha256']))
            out=candidate.render(force=True)
            stock=candidate;active='penc-stock'
        elif family=='penc':
            out=json.loads(penc.dispatch(request_json));active='penc'
        else:raise ValueError('未知機型，未更換執行中的機器。')
    elif active=='dmc':out=dmc.dispatch(req)
    elif active=='penc-stock':out=stock.dispatch(req)
    else:out=json.loads(penc.dispatch(request_json))
    if active=='penc' and 'clock' in out:
        out['family']='penc';out['family_name']='PenC 超代彩'
        out['capabilities']={'new_game':True,'link':True,'motion':True,'audio':True,'away':True}
    return json.dumps(out,separators=(',',':'))
