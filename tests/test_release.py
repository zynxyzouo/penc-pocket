"""Packaging security and integrity checks without firmware fixtures."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from build import collect, source_zip

class ReleaseTests(unittest.TestCase):
    def test_profile_bytes_survive_git_add(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root=Path(folder);target=root/'public/profiles/r23.json'
            target.parent.mkdir(parents=True)
            raw=(ROOT/'public/profiles/r23.json').read_bytes();target.write_bytes(raw)
            (root/'.gitattributes').write_bytes((ROOT/'.gitattributes').read_bytes())
            subprocess.run(['git','init','-q'],cwd=root,check=True)
            subprocess.run(['git','-c','core.autocrlf=false','add','.'],cwd=root,check=True,capture_output=True)
            staged=subprocess.check_output(['git','show',':public/profiles/r23.json'],cwd=root)
            self.assertEqual(hashlib.sha256(staged).hexdigest(),hashlib.sha256(raw).hexdigest())

    def test_reject_unlisted_files_and_firmware(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root=Path(folder)
            (root/'release-files.json').write_text('["release-files.json"]')
            (root/'unexpected.txt').write_text('unreviewed')
            with self.assertRaisesRegex(ValueError,'Unlisted'):collect(root)
            (root/'unexpected.txt').unlink()
            (root/'release-files.json').write_text('["firmware.bin", "release-files.json"]')
            (root/'firmware.bin').write_bytes(b'placeholder')
            with self.assertRaisesRegex(ValueError,'Forbidden'):collect(root)

    def test_reject_private_path_and_parent_escape(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root=Path(folder)
            (root/'release-files.json').write_text('["note.txt", "release-files.json"]')
            # Construct rather than store a real user's path in release source.
            (root/'note.txt').write_text('C:'+chr(92)+'Users'+chr(92)+'example')
            with self.assertRaisesRegex(ValueError,'Private'):collect(root)
            (root/'release-files.json').write_text('["../outside.txt"]')
            with self.assertRaisesRegex(ValueError,'Unsafe'):collect(root)

    def test_reject_cloudflare_local_secrets_even_if_allowlisted(self):
        for name in ['.dev.vars','.dev.vars.production','cloudflare/.wrangler/cache.json']:
            with self.subTest(name=name), tempfile.TemporaryDirectory(dir=ROOT) as folder:
                root=Path(folder);secret=root/name
                secret.parent.mkdir(parents=True,exist_ok=True)
                secret.write_text('local-only-fixture')
                (root/'release-files.json').write_text(json.dumps(sorted([name,'release-files.json'])))
                with self.assertRaisesRegex(ValueError,'Forbidden'):collect(root)

    def test_source_zip_is_deterministic(self):
        self.assertEqual(source_zip({'b.txt':b'b','a.txt':b'a'}),source_zip({'a.txt':b'a','b.txt':b'b'}))

    def test_all_core_and_profile_bytes_are_pinned(self):
        public=ROOT/'public';config=json.loads((public/'core-config.json').read_text())
        checked=0
        for key in ['file_sha256','presentation_sha256','runtime_sha256','family_sha256']:
            for name,value in config[key].items():
                self.assertEqual(hashlib.sha256((public/'core'/name).read_bytes()).hexdigest(),value);checked+=1
        self.assertEqual(checked,25)
        catalog=json.loads((public/'profiles/catalog.json').read_text(encoding='utf-8'))
        self.assertEqual(len(catalog['profiles']),3)
        for firmware,entry in catalog['profiles'].items():
            raw=(public/'profiles'/entry['file']).read_bytes()
            self.assertEqual(len(raw),entry['profile_bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(),entry['profile_sha256'])
            self.assertEqual(json.loads(raw)['sha256'],firmware)

if __name__=='__main__':unittest.main()
