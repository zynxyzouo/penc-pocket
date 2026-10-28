"""Wrap a locally rebuilt jsQR UMD file as an ES module; no network access."""
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
NOTICE = ('// jsQR 1.4.0 — Apache-2.0; upstream notices retained.\n'
          '// Modified 2026-10-28: ES-module packaging for PenC Pocket; decoding logic unchanged.\n'
          '// Preferred TypeScript source: third_party/jsqr-1.4.0/ in the source download.\n')

if __name__=='__main__':
    source=ROOT/'third_party/jsqr-1.4.0/dist/jsQR.js'
    if not source.is_file():
        raise SystemExit('Build third_party/jsqr-1.4.0 first; see third_party/README.md.')
    text=source.read_text(encoding='utf-8')
    out=NOTICE+'const module={exports:{}}; const exports=module.exports;\n'+text+'\nexport default module.exports;\n'
    (ROOT/'public/vendor/jsqr-1.4.0.mjs').write_text(out,encoding='utf-8',newline='\n')
    print('jsQR ESM wrapper refreshed. Run tests and tools/build.py next.')
