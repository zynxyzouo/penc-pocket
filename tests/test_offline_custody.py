"""External R23 integration; native minute/event code is the reference."""
import copy
import importlib.util
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'public/core'))


class Availability(unittest.TestCase):
    def test_custody_adapter_exists(self):
        self.assertIsNotNone(importlib.util.find_spec('offline_custody'))


@unittest.skipUnless(os.environ.get('PENC_R23_BIN'), 'External R23 BIN not provided')
class CustodyTests(unittest.TestCase):
    def setUp(self):
        import runtime_bridge
        import offline_custody as custody
        import audio_completion
        import native_connector
        from bench import Bench
        self.custody = custody
        audio_completion.clock.clear()
        native_connector.cable.clear()
        self.b = Bench(os.environ['PENC_R23_BIN'], ROOT / 'public/profiles/r23.json')
        self.b.ram[0xcc7] = 0

    def pets(self, b=None):
        from bench import CONTEXT
        b = b or self.b
        owner = b.ram[0xdab] & 1
        result = []
        for slot in (0, 1):
            self.assertEqual(b.execute(0x2d1700, register1=slot), 1)
            result.append({a: b.ram[a] for a in CONTEXT})
        self.assertEqual(b.execute(0x2d1700, register1=owner), 1)
        return result

    def run_away(self, seconds, b=None):
        b = b or self.b
        rows = []
        while seconds:
            row = self.custody.catch_up(b, seconds, budget_ms=5000)
            self.assertIsNone(row['blocked_reason'], row)
            self.assertGreater(row['processed_seconds'], 0, row)
            rows.append(row)
            seconds = row['remaining_seconds']
        return rows

    def test_pin_gate_and_arguments(self):
        self.assertTrue(self.custody.supports(self.b))
        self.assertFalse(self.custody.supports(None))
        self.assertFalse(self.custody.supports(object()))
        for seconds in (-1, True, 2**31, 1.5):
            with self.assertRaises(ValueError): self.custody.catch_up(self.b, seconds)
        for budget in (0, float('nan'), float('inf'), True):
            with self.assertRaises(ValueError): self.custody.catch_up(self.b, 1, budget)

    def test_care_history_is_not_erased_and_clock_age_continue(self):
        for slot in (0, 1):
            self.b.execute(0x2d1700, register1=slot)
            self.b.ram.update({0x82e:2+slot, 0x82b:100+slot, 0x832:6+slot,
                               0xcfd:1, 0xcfe:1, 0xcff:1, 0xcf5:0, 0xcf6:0,
                               0x836:5000, 0xcfa:5, 0xcfb:5, 0xcfc:5})
        before = self.pets()
        self.run_away(3600)
        after = self.pets()
        for old, new in zip(before, after):
            self.assertEqual([new[a] for a in (0x82e,0x82b,0x832)], [old[a] for a in (0x82e,0x82b,0x832)])
            self.assertEqual(new[0x837], old[0x837]+60)
            self.assertEqual(new[0x836], old[0x836]-60)
        self.assertEqual([self.b.ram[a] for a in (0xcc4,0xcc3,0xcc2)], [13,21,17])

    def test_hidden_preexisting_illness_blocks_without_any_mutation(self):
        self.b.execute(0x2d1700, register1=1)
        self.b.ram.update({0xcf4:2,0xd01:1})
        self.b.execute(0x2d1700, register1=0)
        before = copy.deepcopy(self.b.__dict__)
        row = self.custody.catch_up(self.b, 3600)
        self.assertEqual((row['processed_seconds'], row['remaining_seconds']), (0,3600))
        self.assertIn('illness', row['blocked_reason'])
        self.assertEqual(self.b.__dict__, before)

    def test_pending_evolution_finishes_both_native_commits(self):
        for slot in (0,1):
            self.b.execute(0x2d1700, register1=slot)
            self.b.ram[0x827] |= 2
        self.b.execute(0x2d1700, register1=0)
        rows = self.run_away(60)
        self.assertEqual([p[0x826] for p in self.pets()], [12,45])
        self.assertTrue(all(not p[0x827]&2 for p in self.pets()))
        self.assertLess(sum(r['completed_frames'] for r in rows), 100)

    def test_cross_bedtime_and_wakeup_keep_native_sleep(self):
        self.b.ram.update({0xcc4:20,0xcc3:59,0xcc2:59})
        for slot in (0,1):
            self.b.execute(0x2d1700, register1=slot)
            self.b.ram[0x836]=5000
        self.run_away(1)
        self.assertTrue(all(p[0xd04]==2 and p[0xd06]==0 for p in self.pets()))
        self.run_away(10*3600)
        self.assertTrue(all(p[0xd04]==0 and p[0xd06]==1 for p in self.pets()))

    def test_failed_native_step_restores_sound_ram_album_and_flash(self):
        import audio_completion as sound
        original = self.b.execute
        def fail(entry, *args, **kwargs):
            value = original(entry, *args, **kwargs)
            if entry == 0x2da800:
                self.b.ram[0x826]=311
                self.b.virtual_album=b'x'*64
                self.b.virtual_flash=b'x'*8192
                sound.clock.remaining=123
                raise RuntimeError('injected native failure')
            return value
        self.b.execute=fail
        self.b.ram[0xcc2]=59
        before=copy.deepcopy(self.b.ram), self.b.virtual_album, self.b.virtual_flash, copy.copy(sound.clock.__dict__)
        row=self.custody.catch_up(self.b,1)
        self.assertEqual(row['processed_seconds'],0)
        self.assertIn('injected native failure',row['blocked_reason'])
        self.assertEqual((self.b.ram,self.b.virtual_album,self.b.virtual_flash,sound.clock.__dict__),before)

    def test_two_days_use_event_boundaries_and_preserve_elapsed_growth(self):
        for slot in (0,1):
            self.b.execute(0x2d1700,register1=slot)
            self.b.ram[0x836]=5000
        before=self.pets()
        rows=self.run_away(48*3600)
        after=self.pets()
        for old,new in zip(before,after):
            self.assertEqual(new[0x836],2120)
            self.assertEqual(new[0x828],old[0x828]+2)
            self.assertEqual(new[0x837],old[0x837])
            self.assertEqual(new[0x82e],old[0x82e])
        self.assertLess(sum(r['native_minutes'] for r in rows),200)
        self.assertGreater(sum(r['batched_minutes'] for r in rows),2680)

    def test_preexisting_sound_finishes_during_offline_time(self):
        import audio_completion as sound
        self.b.ram[0xcc0]=0  # Native sound enabled; the raw demo fixture is muted.
        self.b.execute(0x200050,args=(20,))
        self.assertEqual(self.b.ram[0xca1],1)
        self.assertIsNone(sound.clock.remaining)  # Restored native request, no live clock yet.
        self.run_away(3600)
        self.assertEqual(self.b.ram[0xca1],0)
        self.assertIsNone(sound.clock.remaining)

    def test_restored_unknown_sound_is_not_force_cleared(self):
        self.b.ram.update({0xca1:1,0xcaa:1})
        self.run_away(3600)
        self.assertEqual(self.b.ram[0xca1],1)

    def test_short_away_time_preserves_unfinished_sound(self):
        import audio_completion as sound
        self.b.ram[0xcc0]=0
        self.b.execute(0x200050,args=(20,))
        sound.clock.begin(self.b.code,elapsed_ms=0,speed=2)
        sound.clock.commit(self.b)
        sound.clock.remaining=2000  # Explicit saved completion-clock fixture.
        self.run_away(1)
        self.assertEqual(self.b.ram[0xca1],1)
        self.assertEqual(sound.clock.remaining,1000)

if __name__ == '__main__': unittest.main()
