"""Wire the audited custody engine without weakening the existing runtime."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'public/core'))
import continuity
import offline_custody
import runtime_bridge as rt
import settlement_session

NOW=1800000000000

class RuntimeCustodyTests(unittest.TestCase):
    def setUp(self):
        self.b=SimpleNamespace(ram={0xc9c:4})
        continuity.initialize(self.b,now=NOW-10000)
        self.patches=[]
        def replace(name,**kw):
            p=patch(name,**kw);self.patches.append(p);return p.start()
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patches)])
        replace('runtime_bridge.n.bench',new=self.b)
        replace('continuity.now_ms',return_value=NOW)
        replace('offline_custody.supports',return_value=True)
        self.custody=replace('offline_custody.catch_up',return_value={
            'processed_seconds':6,'remaining_seconds':4,'blocked_reason':None})
        self.native=replace('runtime_bridge.away_bridge.catch_up',return_value={
            'processed_seconds':6,'remaining_seconds':4,'blocked_reason':None})
        replace('runtime_bridge.n.render',return_value={'clock':'12:00:00'})
        replace('runtime_bridge.away_bridge.safe',return_value=True)
        replace('runtime_bridge.native_boot.metadata',return_value={})
        replace('runtime_bridge.native_settings.metadata',return_value={})
        replace('runtime_bridge.motion_metadata',return_value={})
        replace('runtime_bridge.native_connector.cable',new=Mock(connected=False))
        rt.native_connector.cable.metadata.return_value={}

    def call(self,op,**kw):
        return json.loads(rt.dispatch(json.dumps({'op':op,**kw})))

    def test_audited_old_save_defaults_to_custody(self):
        r=self.call('catch-up')
        self.custody.assert_called_once_with(self.b,10,budget_ms=35)
        self.native.assert_not_called()
        self.assertEqual(r['catch_up']['mode'],'custody')
        self.assertEqual(r['continuity']['pending_seconds'],4)
        self.assertEqual(r['offline_policy']['mode'],'custody')

    def test_explicit_native_policy_retains_existing_engine(self):
        r=self.call('offline-policy',mode='native')
        self.assertEqual(r['offline_policy']['mode'],'native')
        self.call('catch-up')
        self.native.assert_called_once();self.custody.assert_not_called()

    def test_invalid_policy_does_not_change_choice(self):
        self.b._offline_policy='native'
        with self.assertRaises(ValueError):self.call('offline-policy',mode='invalid')
        self.assertEqual(self.b._offline_policy,'native')

    def test_release_closes_target_and_snapshot_records_policy(self):
        settlement_session.begin(self.b,now=NOW-5000)
        with patch('runtime_bridge.n.dispatch',return_value=json.dumps({'format':rt.n.FORMAT})),patch('runtime_bridge.sound_state.snapshot',return_value=None):
            r=self.call('release')
        self.assertIsNone(self.b._settlement_window)
        self.assertEqual(r['continuity']['anchor_ms'],NOW-5000)
        self.assertEqual(r['offline_policy'],{'version':1,'mode':'custody'})

if __name__=='__main__':unittest.main()
