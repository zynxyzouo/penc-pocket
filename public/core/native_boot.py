# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Native new-game flow from the admitted BIN's own save template.

This is a selected native startup prefix, not a GPCE hardware reset emulator.
RAM/power/key defaults are host inputs. Native 2060C5 loads the BIN template,
2D2800 initializes and preserves the title, and native UI owns time setting,
egg selection, species creation and hatching. Existing sessions are preserved
by the caller, which must run new_game on an isolated candidate first.
"""
import hashlib

FIRMWARE_SHA256=frozenset((
    '78a066bf272712aee1bf1868522dbcccbca0ee6586963940bdc61ca111c4809d',
    '16e635693650ee76dbae80b8d831a1b0557d5aafa04f0858e673f7e272cf6981',
    '3cf1d684b408da7e6917eb198798eb1f25ef2e4cfed347074f988995591c7191',
    '188d650f63b8bf694b1b8f7904a23089f6308f9f9774c2f608c9fdf463d7d772',
    'aa7227c3f5cc5bfd459352ffc936269e1f61b8ab62d6e19f6564cf39f933d204',
    '0c7953432d89c924221ee8b30054a25fd7c954ec35565b32bd499a5ac2daf882',  # R23; native adapter regions verified unchanged.
))
SIGNATURES=(
    (0x20067f,0x200697,'c76e6b8c91fa92475bce5208a8ab135ae0460b98e41027af9d1fc802343bdda0'),
    (0x2060c5,0x2060c7,'d18347b26a0805b3c19273343524e0bce78de6a7fa9cb8c70be711c2e1440df6'),
    (0x2c09c4,0x2c0b00,'b389b92778020f02439db088d02cfa7d4ec5ec9b2308906a7de85df3847be8f7'),
    (0x2d2800,0x2d2816,'3e67dde69ce89923c719cd66831b1148c673a326dbcfa07d617987936967051b'),
    (0x2fd780,0x2fd800,'00cc21a792e69743080c6f4cd96f3489a639672c748a9aa305dd99826126c2b7'),
    (0x207e1b,0x207e67,'c6a4ea8577e3991c8b226f47a035d396ebe19c6ff19c7a6871c57242242bcfa5'),
    (0x2303a0,0x23049a,'e581ea1a6c3eb6afb7122871e178d9c09db7e2f59a2e89530e8004ace42725a3'),
    (0x200976,0x200a7f,'55ecba85fba3c61e90aac75ae0be080aa99e8fb940c3e8362742fc804f7dbb09'),
)
_last_code=None
_last_supported=False


def supports(code):
    """Only byte-exact audited releases; immutable bytes permit caching."""
    global _last_code,_last_supported
    if type(code) is not bytes:return False
    if code is _last_code:return _last_supported
    admitted=(len(code)==0x800000 and hashlib.sha256(code).hexdigest() in FIRMWARE_SHA256
        and all(hashlib.sha256(code[2*(a-0x200000):2*(z-0x200000)]).hexdigest()==sha
                for a,z,sha in SIGNATURES))
    _last_code,_last_supported=code,admitted
    return admitted


def handles_read(cpu,address):
    """Exact timer-config read in native207E1B; no general MMIO access."""
    if (address!=0x3053 or cpu.pc!=0x207e52 or not cpu.allow_adapters
            or not supports(cpu.code)):
        return False,None
    # Native2300A1..A7 programs 0205 on hardware before the main loop.
    # This host prefix omits that hardware setup. Only the register value is
    # supplied; the interrupt controller, clock rate and IRQ are not emulated.
    return True,getattr(cpu,'_boot_mmio',{}).get(address,0x0205)


def handles_write(cpu,address,value):
    """Allow only the audited caller/address/value triples from clock commit."""
    expected={(0x207e4d,0x3054):1,(0x207e58,0x3053):0x0205,
              (0x207e5f,0x3033):0x5555}
    if (expected.get((cpu.pc,address))!=value or not cpu.allow_adapters
            or not supports(cpu.code)):
        return False
    # Keep peripheral latches outside RAM. The unchanged web snapshot format
    # intentionally admits only RAM plus existing key/bank host registers.
    if not hasattr(cpu,'_boot_mmio'):cpu._boot_mmio={}
    cpu._boot_mmio[address]=value
    cpu.adapters.append({'target':f'{address:06X}',
        'kind':'exact native clock-commit timer/watchdog register fixture; no IRQ timing'})
    return True


def new_game(bench):
    """Initialize an isolated candidate from its own native template, no demo."""
    if not supports(bench.code):
        raise ValueError('This BIN has no admitted native new-game startup flow')
    if bench.entries.get('input_home')!=0x2005e9 or bench.r8_time is None:
        raise ValueError('Native new game requires the matching interactive profile')
    bench.ram=dict.fromkeys(range(0x2000),0)
    bench.ram.update({0x3000:0xffff,0x30e9:0,0x81b:0xffff,0xcae:3})
    bench.virtual_flash=bytes(bench.code[0x7fd000:0x7ff000])
    bench.virtual_album=bytes(bench.code[0x5f000:0x5f040])
    bench.previous_keys=set()
    bench.total_steps=0
    bench.last_trace=[];bench.last_adapters=[];bench.last_calls=[]
    bench.adapters_seen=set();bench.stop_reason=''
    # Native state reset establishes title invalidation sentinels. Native
    # loader, not host writes, supplies egg/species/care fields from the BIN.
    for entry in (0x20067f,0x2060c5,0x2d2800):bench.execute(entry)
    if (bench.ram[0xc9c]!=0 or bench.ram[0x823]!=0 or bench.ram[0x827]&1!=1
            or bench.ram[0xdab]&0x40):
        raise RuntimeError('Native template did not reach the admitted new-game title state')


def metadata(bench):
    if bench is None:return {'supported':False,'phase':'unloaded','hardware_boot':False}
    admitted=supports(bench.code)
    m=bench.ram;main=m.get(0xc9c)
    phase=('title' if main==0 else 'clock-setting' if main==2 else
           ('hatching' if m.get(0x86c)==1 else 'egg-select') if main==3 else
           'play' if main==4 else 'display-suspended' if main==0x26 else 'native-ui')
    return {'supported':admitted,'phase':phase,'hardware_boot':False,
            'startup':'native-template-prefix' if admitted else 'unsupported',
            'wake_supported':False}
