"""Refresh byte hashes, preserving deliberately versioned snapshot ABI IDs."""
# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def digest(data):
    return hashlib.sha256(data).hexdigest()

def update(root=ROOT):
    public = root / 'public'
    path = public / 'core-config.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    groups = [('files','file_sha256'),('presentation_files','presentation_sha256'),
              ('runtime_files','runtime_sha256'),('family_files','family_sha256')]
    for names, hashes in groups:
        config[hashes] = {name:digest((public/'core'/name).read_bytes()) for name in config[names]}
    path.write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8',newline='\n')
    path = public/'profiles/catalog.json'
    catalog = json.loads(path.read_text(encoding='utf-8'))
    for firmware, entry in catalog['profiles'].items():
        raw = (path.parent/entry['file']).read_bytes()
        assert json.loads(raw)['sha256'] == firmware
        entry['profile_sha256'],entry['profile_bytes'] = digest(raw),len(raw)
    path.write_text(json.dumps(catalog,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')

if __name__ == '__main__':
    update()
    print('Core and profile byte hashes refreshed; snapshot ABI IDs retained.')
