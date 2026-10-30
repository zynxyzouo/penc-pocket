"""Build GPCE4 C sources without embedding ROMs; --native also builds test DLL."""
from pathlib import Path
import base64
import os
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
bundled = root.parents[1] / 'wasm-core-20261030/toolchain/zig-x86_64-windows-0.15.2/zig.exe'
compiler = os.environ.get('POCKET_ZIG') or shutil.which('zig') or (str(bundled) if bundled.exists() else None)
if not compiler:
    raise SystemExit('Set POCKET_ZIG to official Zig 0.15.2 executable')
build = root / 'build'
build.mkdir(exist_ok=True)
out = root / 'public/core/gpce4.wasm.b64'
out.parent.mkdir(parents=True, exist_ok=True)
common = [compiler, 'cc', '-std=c11', '-O3', '-Wall', '-Wextra', '-Werror',
          '-fno-strict-aliasing', '-fno-builtin', str(root / 'src/gpce4_cpu.c'),
          str(root / 'src/gpce4_soc.c')]
env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(build / 'zig-cache'),
           ZIG_LOCAL_CACHE_DIR=str(build / 'zig-local-cache'))
exports = ['gp_irom_ptr', 'gp_flash_ptr', 'gp_flash_size', 'gp_reset', 'gp_run', 'gp_keys',
           'gp_rgba_ptr', 'gp_cpu_ptr', 'gp_ram_ptr', 'gp_io_ptr', 'gp_metrics_ptr',
           'gp_state_ptr', 'gp_state_size', 'gp_restore', 'gp_dirty_ptr',
           'gp_bus_read', 'gp_bus_write', 'gp_audio_events_ptr',
           'gp_audio_event_count', 'gp_audio_clear', 'gp_custody_call', 'gp_sync_ui',
           'gp_link_enable', 'gp_link_cancel', 'gp_link_status', 'gp_link_tx_ptr', 'gp_link_tx_take',
           'gp_link_rx_ptr', 'gp_link_receive', 'gp_motion_enable', 'gp_motion_clear', 'gp_motion_pulse']
with tempfile.TemporaryDirectory(dir=build) as directory:
    raw = Path(directory) / 'gpce4.wasm'
    subprocess.run(common + ['-target', 'wasm32-freestanding', '-nostdlib', '-Wl,--no-entry',
        '-Wl,--export-memory', '-Wl,-z,stack-size=65536',
        '-Wl,--initial-memory=33554432', '-Wl,--max-memory=33554432',
        *['-Wl,--export=' + name for name in exports], '-o', str(raw)], check=True, env=env)
    data = raw.read_bytes()
    out.write_text(base64.b64encode(data).decode('ascii') + '\n', encoding='ascii', newline='\n')
if '--native' in sys.argv:
    native = build / ('gpce4.dll' if sys.platform == 'win32' else 'gpce4.so')
    subprocess.run(common + ['-shared', '-fPIC', '-o', str(native)], check=True, env=env)
print(f'Built GPCE4 Wasm: {len(data)} bytes; fixed memory 32 MiB; no ROM data')
