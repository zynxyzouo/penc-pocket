"""Optional real-firmware integration: set PENC_R23_BIN; firmware is not bundled."""
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'public/core'))
import family_router as router
import runtime_bridge as rt
import web_adapter as host
import native_boot
import native_settings
import away_bridge
import sound_state

SHA='0c7953432d89c924221ee8b30054a25fd7c954ec35565b32bd499a5ac2daf882'

@unittest.skipUnless(os.environ.get('PENC_R23_BIN'), 'External R23 BIN not provided')
class R23Tests(unittest.TestCase):
    def test_native_startup_and_persistence(self):
        path=Path(os.environ['PENC_R23_BIN'])
        code=path.read_bytes()
        self.assertEqual(hashlib.sha256(code).hexdigest(),SHA)
        # Check the adapter gate first: this was the second failure after lookup.
        self.assertTrue(native_boot.supports(code), 'R23 native startup must be admitted')
        for module in (native_settings,away_bridge):self.assertTrue(module.supports(code))
        self.assertTrue(sound_state._supported(code))
        config=json.loads((ROOT/'public/core-config.json').read_text(encoding='utf-8'))
        def call(op,**kw):return json.loads(router.dispatch(json.dumps({'op':op,**kw})))
        call('load',bin_path=str(path),profile_path=str(ROOT/'public/profiles/r23.json'),core_sha256=config['core_sha256'])
        call('new-game')
        b=host.bench
        def frame(keys=()):return rt.advance(list(keys),frames=1,audio_elapsed_ms=1000/64)
        def tap(key):frame((key,));frame()
        frame()
        self.assertEqual(native_boot.metadata(b)['phase'],'title')
        tap('B')
        self.assertEqual(native_boot.metadata(b)['phase'],'clock-setting')
        for _ in range(12):tap('A')
        for _ in range(34):tap('B')
        tap('C')
        for _ in range(40):
            frame()
            if b.ram[0xc9c]==b.ram[0xc9d]==3:break
        self.assertEqual(native_boot.metadata(b)['phase'],'egg-select')
        self.assertEqual((b.ram[0xcc4],b.ram[0xcc3],b.ram[0xcc2]),(12,34,0))
        tap('A');tap('B')
        for _ in range(1800):
            frame()
            if b.ram[0xc9c]==4 and b.ram[0x827]==0:break
        self.assertEqual((b.ram[0xc9c],b.ram[0x827]),(4,0))
        frame()
        settings=native_settings.metadata(b)
        self.assertTrue(settings['volume_valid'])
        self.assertTrue(settings['brightness_valid'])
        def menu(item):
            self.assertEqual(b.ram[0xc9c],4)
            if b.ram[0xcf3]:tap('C')
            for _ in range(100):
                frame(('C',))
                if b.ram[0xc9c]==23:break
            frame()
            self.assertEqual(b.ram[0xc9c],23)
            for _ in range(item):tap('A')
            tap('B')
        menu(2)
        volume=native_settings.metadata(b)['volume_level']
        tap('A')
        self.assertEqual(native_settings.metadata(b)['volume_level'],(volume+1)%3)
        tap('B')
        self.assertEqual(b.ram[0xc9c],4)
        menu(1)
        brightness=native_settings.metadata(b)['brightness_level']
        tap('A')
        self.assertEqual(native_settings.metadata(b)['brightness_level'],brightness%5+1)
        tap('B')
        self.assertEqual(b.ram[0x825],brightness%5+1)
        self.assertNotIn(0x3022,b.ram)
        saved=call('snapshot')
        call('restore',snapshot=saved)
        self.assertEqual(call('snapshot'),saved)
        self.assertTrue(away_bridge.safe(host.bench))
        before=host.bench.ram[0xcc2]
        remaining=2
        for _ in range(2):
            result=away_bridge.catch_up(host.bench,remaining,budget_ms=1000)
            self.assertIsNone(result['blocked_reason'])
            remaining=result['remaining_seconds']
            if not remaining:break
        self.assertEqual(remaining,0,result)
        self.assertEqual(host.bench.ram[0xcc2],(before+2)%60)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),SHA)
        bad=bytearray(code);bad[0]^=1
        self.assertFalse(native_boot.supports(bytes(bad)))

if __name__=='__main__':unittest.main()
