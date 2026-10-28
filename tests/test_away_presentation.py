"""Catch-up presentation must not change committed time or care execution."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'public/core'))
import runtime_bridge as rt


class AwayPresentationTests(unittest.TestCase):
    def setUp(self):
        self.patches = []
        def replace(target, **kw):
            p = patch(target, **kw); self.patches.append(p); return p.start()
        replace('runtime_bridge.n.bench', new=object())
        self.render = replace('runtime_bridge.n.render', return_value={'clock':'12:00:00','rgba':'pixels'})
        self.metadata = replace('runtime_bridge.continuity.metadata', return_value={'pending_seconds':10})
        self.consume = replace('runtime_bridge.continuity.consume')
        self.catch = replace('runtime_bridge.away_bridge.catch_up', return_value={
            'processed_seconds':2, 'remaining_seconds':8, 'blocked_reason':None})
        replace('runtime_bridge.away_bridge.safe', return_value=True)
        replace('runtime_bridge.native_boot.metadata', return_value={})
        replace('runtime_bridge.native_settings.metadata', return_value={})
        replace('runtime_bridge.motion_metadata', return_value={})
        replace('runtime_bridge.native_connector.cable', new=Mock(connected=False))
        rt.native_connector.cable.metadata.return_value = {}
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def call(self, op='catch-up', **fields):
        return json.loads(rt.dispatch(json.dumps({'op':op, **fields})))

    def test_progress_only_retains_committed_seconds_without_render(self):
        out = self.call(present=False)
        self.render.assert_not_called()
        self.catch.assert_called_once_with(rt.n.bench, 10, budget_ms=35)
        self.consume.assert_called_once_with(rt.n.bench, 2)
        self.assertEqual(out['catch_up']['processed_seconds'], 2)
        self.assertEqual(out['continuity']['pending_seconds'], 10)
        self.assertNotIn('clock', out)

    def test_default_clients_keep_full_presentation(self):
        self.assertEqual(self.call()['rgba'], 'pixels')
        self.render.assert_called_once()

    def test_finished_and_blocked_always_present(self):
        for progress in ({'processed_seconds':10,'remaining_seconds':0,'blocked_reason':None},
                         {'processed_seconds':0,'remaining_seconds':10,'blocked_reason':'native-action'}):
            with self.subTest(progress=progress):
                self.render.reset_mock(); self.catch.return_value=progress
                self.assertEqual(self.call(present=False)['rgba'], 'pixels')
                self.render.assert_called_once()

    def test_cancel_refresh_does_not_advance_or_consume_time(self):
        self.assertEqual(self.call('present')['rgba'], 'pixels')
        self.render.assert_called_once_with(force=True)
        self.catch.assert_not_called(); self.consume.assert_not_called()

    def test_invalid_presentation_flag_fails_before_mutation(self):
        with self.assertRaises(ValueError): self.call(present='false')
        self.catch.assert_not_called(); self.consume.assert_not_called()


if __name__ == '__main__': unittest.main()
