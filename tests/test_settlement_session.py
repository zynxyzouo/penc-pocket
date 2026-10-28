"""Waiting for offline settlement is not an additional unattended interval."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'public/core'))
import continuity

NOW=1800000000000

class SettlementSessionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('settlement_session'))
        import settlement_session
        self.session=settlement_session
        self.bench=SimpleNamespace(ram={0xc9c:4})
        continuity.initialize(self.bench,now=NOW-172800000)

    def test_fixed_target_does_not_grow_during_work(self):
        self.session.begin(self.bench,now=NOW)
        continuity.consume(self.bench,3600,now=NOW+2000)
        self.assertEqual(self.session.metadata(self.bench,now=NOW+15000)['pending_seconds'],169200)
        self.session.begin(self.bench,now=NOW+20000)
        self.assertEqual(self.session.metadata(self.bench,now=NOW+20000)['pending_seconds'],169200)

    def test_snapshot_resume_preserves_only_unprocessed_time(self):
        self.session.begin(self.bench,now=NOW)
        continuity.consume(self.bench,3600,now=NOW)
        snapshot=self.session.snapshot(self.bench,now=NOW+15000)
        other=SimpleNamespace(ram={0xc9c:4})
        continuity.restore(other,snapshot,now=NOW+25000)
        self.assertEqual(self.session.metadata(other,now=NOW+25000)['pending_seconds'],169210)
        self.assertEqual(self.bench._continuity['anchor_ms'],NOW-169200000)

    def test_cancel_excludes_wait_once_but_preserves_later_absence(self):
        self.session.begin(self.bench,now=NOW)
        continuity.consume(self.bench,100,now=NOW)
        self.session.end(self.bench,now=NOW+5000)
        anchor=self.bench._continuity['anchor_ms']
        self.session.end(self.bench,now=NOW+15000)
        self.assertEqual(self.bench._continuity['anchor_ms'],anchor)
        self.assertEqual(self.session.metadata(self.bench,now=NOW+15000)['pending_seconds'],172710)

    def test_complete_has_no_processing_debt(self):
        self.session.begin(self.bench,now=NOW)
        continuity.consume(self.bench,172800,now=NOW)
        self.session.end(self.bench,now=NOW+8000)
        self.assertEqual(self.session.metadata(self.bench,now=NOW+8000)['pending_seconds'],0)

    def test_clock_rollback_never_subtracts_committed_time(self):
        self.session.begin(self.bench,now=NOW)
        before=self.bench._continuity['anchor_ms']
        self.session.end(self.bench,now=NOW-5000)
        self.assertEqual(self.bench._continuity['anchor_ms'],before)

    def test_old_snapshots_default_to_custody_only_when_supported(self):
        self.assertTrue(hasattr(self.session,'policy'))
        self.assertEqual(self.session.policy(self.bench,available=True),'custody')
        self.assertEqual(self.session.policy(self.bench,available=False),'native')

    def test_invalid_or_unsupported_policy_keeps_existing_choice(self):
        self.assertTrue(hasattr(self.session,'restore_policy'))
        self.bench._offline_policy='native'
        for payload,available in [({'version':1,'mode':'custody'},False),
                                  ({'version':True,'mode':'custody'},True),
                                  ({'version':1,'mode':'unknown'},True),
                                  ({'version':1,'mode':'custody','extra':1},True)]:
            with self.assertRaises(ValueError):
                self.session.restore_policy(self.bench,payload,available=available)
            self.assertEqual(self.bench._offline_policy,'native')

    def test_policy_roundtrip_and_legacy_restore(self):
        self.assertTrue(hasattr(self.session,'restore_policy'))
        self.session.restore_policy(self.bench,{'version':1,'mode':'custody'},available=True)
        self.assertEqual(self.session.policy(self.bench,available=True),'custody')
        self.session.restore_policy(self.bench,None,available=True)
        self.assertEqual(self.session.policy(self.bench,available=True),'custody')

if __name__=='__main__':unittest.main()
