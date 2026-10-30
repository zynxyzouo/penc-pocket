"""Build the same freestanding C engine for Wasm and local differential tests."""
from pathlib import Path
import os, subprocess, sys, shutil, tempfile, base64
root=Path(__file__).resolve().parents[1]
compiler=os.environ.get('POCKET_ZIG') or shutil.which('zig')
if not compiler:raise SystemExit('Set POCKET_ZIG to the Zig 0.15.2 executable (see docs/compiled-core.md)')
source=root/'src/pocket_cpu.c'
if not source.exists():
    raise SystemExit('Missing compiled instruction engine src/pocket_cpu.c')
out=root/'public/core/pocket_cpu.wasm.b64'
common=[str(compiler),'cc','-std=c11','-O3','-Wall','-Wextra','-Werror','-fno-strict-aliasing',str(source)]
build=root/'build';build.mkdir(exist_ok=True)
env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(build/'zig-cache'),ZIG_LOCAL_CACHE_DIR=str(build/'zig-local-cache'))
exports=['state_ptr','ram_ptr','valid_ptr','dirty_ptr','calls_ptr','rom_ptr','reset','run','clear_dirty']
with tempfile.TemporaryDirectory(dir=build) as temporary:
    raw=Path(temporary)/'pocket_cpu.wasm'
    subprocess.run(common+['-target','wasm32-freestanding','-nostdlib','-Wl,--no-entry','-Wl,--export-memory',
        '-Wl,-z,stack-size=65536','-Wl,--initial-memory=10485760','-Wl,--max-memory=10485760',
        *['-Wl,--export='+n for n in exports],'-o',str(raw)],check=True,env=env)
    data=raw.read_bytes()
    out.write_text(base64.b64encode(data).decode('ascii')+'\n',encoding='ascii',newline='\n')
if '--native' in sys.argv:
    native=build/('pocket_cpu.dll' if sys.platform=='win32' else 'pocket_cpu.so')
    subprocess.run(common+['-shared','-fPIC','-o',str(native)],check=True,env=env)
print('Built Wasm bytes:',len(data))
