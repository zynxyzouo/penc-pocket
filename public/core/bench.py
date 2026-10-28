# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Local BIN/native-function driver. No sockets, HTTP client, or BIN writer."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import struct
import uuid

from cpu import CPU
import hd_host

HERE = Path(__file__).resolve().parent
CONTEXT = tuple(range(0x826,0x838))+tuple(range(0xcf4,0xd07))


def address(value):
    if isinstance(value, int): return value
    return int(value.removeprefix('0x'), 16)


def default_paths(config_path=HERE/'default.json'):
    """Resolve only the local bundle configuration; no file is uploaded."""
    config_path = Path(config_path).resolve()
    settings = json.loads(config_path.read_text(encoding='utf-8-sig'))
    firmware = (config_path.parent/settings['firmware']).resolve()
    manifest = (config_path.parent/settings['manifest']).resolve() if settings.get('manifest') else None
    return firmware, manifest


def resolve_manifest(path, explicit=None, config_path=HERE/'default.json'):
    """Match exact bytes, never infer native addresses from a BIN filename."""
    path = Path(path).resolve()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    candidates = [Path(explicit).resolve()] if explicit else []
    if not explicit:
        candidates += [path.with_suffix('.emulator.json')]
        candidates += sorted(path.parent.glob('*.emulator.json'))
        config_path = Path(config_path).resolve()
        if config_path.exists():
            settings = json.loads(config_path.read_text(encoding='utf-8-sig'))
            if settings.get('manifest'):
                configured = (config_path.parent/settings['manifest']).resolve()
                candidates += [configured]
                candidates += sorted(configured.parent.glob('*.emulator.json'))
    seen = set()
    no_input = False
    for candidate in candidates:
        if candidate in seen or not candidate.is_file(): continue
        seen.add(candidate)
        try:
            data = json.loads(candidate.read_text(encoding='utf-8-sig'))
        except (ValueError,OSError):
            continue
        if data.get('sha256',data.get('firmware_sha256')) != digest: continue
        if 'input_home' not in data.get('entries',{}):
            no_input = True
            continue
        return candidate.resolve()
    if no_input:
        raise ValueError('此 BIN 的清單沒有按鍵入口，無法進行互動測試。請載入完整包內的 R8 BIN。')
    raise ValueError('未找到與此 BIN 內容相符的本機測試清單（SHA256）。\n請選完整包 release 資料夾中的 R8 BIN；其他版本尚不支援。\nBIN 與測試清單都留在本機，改檔名不影響比對。')


class Bench:
    def __init__(self, path=None, manifest=None):
        if path is None:
            path, configured_manifest = default_paths()
            if manifest is None:
                manifest = configured_manifest
        self.path = Path(path).resolve()
        self.code = self.path.read_bytes()
        if len(self.code) != 0x800000: raise ValueError('Requires an 8 MiB BIN')
        self.sha256 = hashlib.sha256(self.code).hexdigest()
        self.manifest = {}
        if manifest:
            self.manifest = json.loads(Path(manifest).read_text(encoding='utf-8-sig'))
            pin = self.manifest.get('sha256', self.manifest.get('firmware_sha256'))
            if pin != self.sha256: raise ValueError('Manifest SHA256 does not match loaded BIN')
        self.r8_local_play=self.manifest.get('r8_local_play')
        if self.r8_local_play is not None:
            cfg=self.r8_local_play
            if (not isinstance(cfg,dict) or type(cfg.get('version')) is not int or cfg['version']!=1
                or cfg.get('firmware_sha256')!=self.sha256
                or cfg.get('source_sha256')!='eb3be1f0048582ac6e1501a7da1df787c754a781f28d5eb34442036877db9e0f'):
                raise ValueError('R8 local-play manifest must match exact product and source')
        # Extra RGB565 assets are admitted only by the matching local manifest,
        # with an independently checked byte-region digest. Do not treat all
        # executable flash as valid artwork when decoding a bad descriptor.
        self.r8_ui=self.manifest.get('r8_ui')
        ui_region=None
        if self.r8_ui is not None:
            cfg=self.r8_ui
            if (not isinstance(cfg,dict) or type(cfg.get('version')) is not int or cfg['version']!=1
                or cfg.get('firmware_sha256')!=self.sha256
                or cfg.get('source_sha256')!='aa8924ddee43fe04f7cf17e4da78a399b8eecc6fc03754d731891308e724fd82'
                or cfg.get('asset_regions') not in ([[0x1f3800,0x1f9000],[0x1bd000,0x1c0000],[0x1ef000,0x1f0000]],
                                                    [[0x1f3800,0x1f9000],[0x1bd000,0x1c0000],[0x1ef000,0x1f0000],
                                                     [0x1f0200,0x1f2000]])):
                raise ValueError('R8 UI manifest must match exact product and source')
            ui_region=[tuple(r) for r in cfg['asset_regions']]
        self.extra_sprite_regions=[]
        for region in self.manifest.get('extra_sprite_regions',[]):
            start,end=region['start'],region['end_exclusive']
            if not (type(start) is int and type(end) is int and start%2==0 and end%2==0 and
                    (0x1c8000<=start<end<=0x1e0000 or
                     (self.r8_local_play is not None and 0x1a9000<=start<end<=0x1b0000) or
                     (ui_region is not None and any(a<=start<end<=z for a,z in ui_region)))):
                raise ValueError('Invalid Book sprite region')
            if hashlib.sha256(self.code[start:end]).hexdigest()!=region.get('sha256'):
                raise ValueError('Book sprite region digest mismatch')
            self.extra_sprite_regions.append((start,end))
        self.device_rules()
        self.entries = {k:address(v['address'] if isinstance(v,dict) else v)
                        for k,v in self.manifest.get('entries',{}).items()}
        self.r8_time = self.manifest.get('r8_time')
        if self.r8_time is not None:
            cfg = self.r8_time
            if not isinstance(cfg, dict) or cfg.get('firmware_sha256') != self.sha256:
                raise ValueError('R8 time SHA256 must match the loaded BIN')
            expected = {'version':1,'tick_entry':0x2da400,'frame_entry':0x2dae00,
                        'default_mode':0,'long_press_host_seconds':1}
            if any(type(cfg.get(k)) is not int or cfg[k] != value for k,value in expected.items()):
                raise ValueError('Unsupported R8 native time configuration')
            if self.entries.get('input_home') != 0x2005e9:
                raise ValueError('R8 time requires actual native UI entry 2005E9')
        self.total_steps = 0
        self.last_trace, self.last_adapters = [], []
        self.last_calls, self.stop_reason, self.last_result = [], '', 0
        self.previous_keys = set()
        self.adapters_seen=set()
        self.virtual_flash=bytes(self.code[0x7fd000:0x7ff000])
        self.virtual_album=bytes(self.code[0x5f000:0x5f040])
        self.reset()

    def stat(self, species, field):
        if not 0 <= species < 312 or not 0 <= field < 18: raise ValueError('species/field out of range')
        return struct.unpack_from('<H', self.code, 0x2b000+2*(species*18+field))[0]

    def seed_pet(self, species):
        result = dict.fromkeys(CONTEXT, 0)
        result.update({0x826:species, 0x828:5, 0x829:self.stat(species,3),
                       0x82a:self.stat(species,15), 0x833:10,
                       0x836:100, 0x837:100, 0xcf5:4, 0xcf6:4,
                       0xcfa:100, 0xcfb:100, 0xcfc:100})
        result.update({a:65535 for a in range(0xcfd,0xd04)})
        return result

    def reset(self):
        # All zero RAM, stack position, clock and test pet values are HOST
        # inputs. This is not a claim that firmware boot initialized them.
        self.ram = dict.fromkeys(range(0x2000),0)
        self.ram.update(self.seed_pet(5))
        # Boot normally queries internal-ROM power status into CAE at200195.
        # This partial bench bypasses boot, so explicitly supply normal power
        # (3). Zero means native low battery, not "unknown". Explicit manifest
        # fixtures may still select charging5/full6; no per-frame override.
        self.ram.update({0xc9c:4,0xc9d:4,0xcae:3,0xcc2:17,0xcc3:21,0xcc4:12,
                         0xcc7:1,0x3000:0xffff,0x81b:65535,0x820:0})
        if self.r8_local_play is not None:self.ram[0x30e9]=0
        for i in range(8): self.ram[0x600+i] = (i+1)*123
        for obj in range(36): self.ram[0x608+obj*12] = 65535
        for key,value in self.manifest.get('initial_ram',{}).items(): self.ram[address(key)] = address(value) if isinstance(value,str) else value
        if self.r8_time is not None:
            # A new host demo session starts at1x, inactive. Assigning a saved
            # RAM snapshot after construction is not reset here or per frame.
            self.ram[0xdab] &= ~0x600
            self.ram[0xda3] = self.ram[0xda4] = 0
        self.previous_keys = set(); self.stop_reason = ''
        self.last_trace, self.last_adapters, self.last_calls = [], [], []

    def execute(self, entry, args=(), register1=None, adapters=True, direct=False, clock_seconds=None):
        cpu = CPU(self.code, self.ram, adapters=adapters,flash=self.virtual_flash,clock_seconds=clock_seconds,
                  album_flash=self.virtual_album,local_play=self.r8_local_play is not None)
        try:
            budget = 3000000 if self.r8_time is not None and entry == self.r8_time['tick_entry'] else 500000
            cpu.run(entry,args,register1=register1,direct=direct,budget=budget)
        except Exception as exc:
            self.stop_reason = f'{exc}; stopped PC {cpu.pc:06X}; RAM transaction discarded'
            raise RuntimeError(self.stop_reason) from exc
        else:
            self.ram = cpu.mem
            self.virtual_flash=bytes(cpu.virtual_flash)
            self.virtual_album=bytes(cpu.virtual_album)
            self.last_result = cpu.r[1]
            self.stop_reason = ''
            return cpu.r[1]
        finally:
            self.last_trace = list(cpu.trace)
            self.last_adapters, self.last_calls = cpu.adapters, cpu.calls
            self.adapters_seen.update(a['target'] for a in cpu.adapters)
            self.total_steps += cpu.steps

    def run_named(self, name, args=(), register1=None):
        if name not in self.entries: raise RuntimeError(f'Manifest has no native {name} entry')
        return self.execute(self.entries[name],args,register1)

    def sample_keys(self, held, long=False):
        """Host sampled edge/held/raw fields only; no native scanner or UI."""
        bits = {'A':8,'B':16,'C':32}
        held = set(held)
        value = sum(bits[k] for k in held)
        fresh = value if held-self.previous_keys else 0
        self.ram.update({0x81b:fresh if fresh else 65535,0x81c:value,
                         0x820:(0x8000|value) if long and value else 0,
                         0x3000:65535^value})
        return held

    def keys(self, held, long=False, seconds=0):
        if 'input_home' not in self.entries:
            raise RuntimeError('No hash-bound input_home entry: this BIN supports selected-function tests only')
        if self.r8_time is not None:
            from host_clock import native_frame
            return native_frame(self, held, seconds=seconds, long=long)
        if seconds:
            raise ValueError('Legacy keys cannot inject time; use host_clock.native_frame')
        # Supply a sampled combined event when another key joins a chord.
        # This host scan adapter makes keyboard A then B produce native 0x18.
        pending = dict(self.ram)
        held = self.sample_keys(held,long)
        try: result = self.run_named('input_home')
        except Exception:
            self.ram = pending
            raise
        self.previous_keys = held
        return result

    def device_rules(self):
        """Two device behaviours the host decoder used to ignore (2026-10-19 device report).

        1. The per-frame redraw only walks slots 0..[07B8]-1. A BIN carrying the
           R8.3 COUNT call at gateway 21ECC0 raises the count to the highest
           visible slot first; older BINs do not.
        2. Private sprites (field7 flag 0x2000) are not readable through the
           author's renderer on hardware. A BIN carrying the bank1 MAP redirect
           (and the manifest's bank1_remap with byte-identical copies) reads
           them from the upper-half copies; otherwise they are shown as noise.
        """
        c = self.code
        at = lambda pc: 2*(pc-0x200000)
        self.count_fix = c[at(0x21ecc0):at(0x21ecc0)+4] == bytes.fromhex('6ff000fd')
        self.bank1_remap = []
        remap = (self.r8_ui or {}).get('bank1_remap') or []
        redirected = (c[at(0x3fc3ba):at(0x3fc3ba)+4] == bytes.fromhex('bffe04c6') and
                      c[0x3f8000:0x3fa000] == c[0x7f8000:0x7fa000])
        if redirected:
            for r in remap:
                s0, e0, d0 = r['source_start'], r['source_end'], r['dest_start']
                if (0x200000+(d0-0x400000)//2) - (0x200000+s0//2) != r['delta']:
                    raise ValueError('bank1 remap delta inconsistent')
                for a, z in self.extra_sprite_regions:
                    if s0 <= a < z <= e0 and c[a:z] != c[d0+a-s0:d0+z-s0]:
                        raise ValueError('bank1 copy does not match its private sprite source')
                self.bank1_remap.append((r['hi'], r['delta']))
        self.device_warnings = set()
        self.hd = hd_host.present(c)

    def drawn_slots(self):
        """Slots the device redraw actually walks (see device_rules)."""
        d = self.descriptors()
        count = self.ram.get(0x7b8, 0)
        if self.count_fix:
            top = max((s+1 for s, x in enumerate(d) if x[8] == 1 and x[0] != 0xffff), default=0)
            count = max(count, top)
        return [s for s in range(min(count, 36)) if d[s][0] != 0xffff and d[s][8]]

    def descriptors(self):
        return [[self.ram.get(0x608+slot*12+i,0) for i in range(12)] for slot in range(36)]

    def sprite_offset(self, descriptor):
        """R15h Height48 frames are drawn relative to the 48x48 box (0 for every other sprite)."""
        hd = hd_host.image(self.code, descriptor) if self.hd else None
        return 0 if hd is None else (hd[4] if descriptor[11] else hd[3])

    def sprite(self, descriptor):
        width, height = descriptor[4:6]
        hd = hd_host.image(self.code, descriptor) if self.hd else None
        if hd is not None:
            return hd[:3]
        if descriptor[0] == 0xfffe:
            # Native 20CDE2 solid rectangle: field1 is the RGB565 colour and
            # there is no bitmap pointer. Used by the CHANGE chooser and R8 UI.
            if not (1 <= width <= 96 and 1 <= height <= 96):
                raise RuntimeError(f'Invalid native fill descriptor: {descriptor}')
            v = descriptor[1]
            colour = '#%02x%02x%02x'%(((v >> 11)&31)*255//31,((v >> 5)&63)*255//63,(v&31)*255//31)
            return width, height, [colour]*(width*height)
        # Author renderer flag 0x4000 expands stored pixels 3x in each axis.
        # Role assets are 16x16 RGB565; executed object dimensions are 48x48.
        # Native external LCD reader 3FC3B4 selects bank0 with flag0x2000,
        # otherwise bank1. Both use CPU window200000..3FFFFF. Flag0x4000
        # independently requests the author's 3x RGB565 expansion.
        pointer = descriptor[6] | ((descriptor[7] & ~0x6000) << 16)
        bank0 = bool(descriptor[7] & 0x2000)
        if bank0 and descriptor[0] != 65535:
            # Admission is always judged on the private (bank0) address first.
            s0 = 3 if descriptor[7] & 0x4000 else 1
            at0 = (pointer-0x200000)*2
            end0 = at0 + (width//s0)*(height//s0)*2
            if (1 <= width <= 96 and 1 <= height <= 96 and width % s0 == 0 and height % s0 == 0
                    and any(start<=at0 and end0<=stop for start,stop in self.extra_sprite_regions)):
                delta = dict(self.bank1_remap).get(pointer >> 16)
                if delta is None:
                    # Device: unsynchronised bank0 switch; the toy shows stripes/garbage.
                    self.device_warnings.add(f'private sprite {pointer:06X} unreadable on device')
                    return width, height, ['#000000' if (x//2) % 2 else '#ff00ff' for y in range(height) for x in range(width)]
                pointer, bank0 = (pointer + delta) & 0x3fffff, False
        at = (pointer-0x200000)*2+(0 if bank0 else 0x400000)
        if descriptor[0] == 65535: return 0,0,[]
        scale = 3 if descriptor[7] & 0x4000 else 1
        raw_width, raw_height = width//scale, height//scale
        end=at+raw_width*raw_height*2
        admitted=(not bank0 and 0x400000<=at and end<=len(self.code)) or (
            bank0 and any(start<=at and end<=stop for start,stop in self.extra_sprite_regions))
        if not (1 <= width <= 96 and 1 <= height <= 96 and width % scale == 0 and height % scale == 0
                and 0x200000<=pointer<0x400000 and admitted):
            raise RuntimeError(f'Invalid executed native sprite descriptor: {descriptor}')
        raw = struct.unpack_from('<'+'H'*(raw_width*raw_height),self.code,at)
        colors = [None if v == 0x7e0 else '#%02x%02x%02x'%(
            ((v >> 11)&31)*255//31,((v >> 5)&63)*255//63,(v&31)*255//31) for v in raw]
        if scale == 3:
            # Device 3x reader 3FC420..47B: linear offset o = y*width + x, then a
            # fixed subtraction chain that is a correct divide only for 48-px
            # (16-column) sprites; o >= 0x900 reads the unexpanded word at o.
            def index(o):
                if o >= 0x900: return o
                n = 0
                for t, add in ((0x480,0x80),(0x240,0x40),(0x120,0x20),(0x90,0x10),(0x60,0),(0x30,0),
                               (0x18,8),(0xc,4),(6,2),(3,1)):
                    if o >= t: o -= t; n += add
                return n
            if width != 48:
                self.device_warnings.add(f'3x sprite {pointer:06X} width {width} != 48 garbles on device')
            pixels = []
            for y in range(height):
                for x in range(width):
                    i = index(y*width + x)
                    if i < len(colors): pixels.append(colors[i])
                    else:
                        v = struct.unpack_from('<H', self.code, at+2*i)[0] if at+2*i+1 < len(self.code) else 0
                        pixels.append(None if v == 0x7e0 else '#%02x%02x%02x'%(((v>>11)&31)*255//31,((v>>5)&63)*255//63,(v&31)*255//31))
            return width,height,pixels
        pixels = [colors[(y//scale)*raw_width+x//scale] for y in range(height) for x in range(width)]
        return width,height,pixels

    def save_copy(self, folder=HERE/'sessions'):
        folder = Path(folder).resolve()
        if not folder.is_relative_to(HERE): raise ValueError('Snapshots must stay in the isolated emulator folder')
        folder.mkdir(parents=True,exist_ok=True)
        path = folder/f'bench_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.json'
        payload = {'format':'PENC_NATIVE_BENCH_HOST_SNAPSHOT_V1', 'firmware_path':str(self.path),
                   'firmware_sha256':self.sha256, 'not_device_save':True,
                   'ram':{f'{a:04X}':v for a,v in self.ram.items()},
                   'virtual_flash_mirrors_hex':self.virtual_flash.hex(),
                   'virtual_flash_note':'Host NOR mirror fixture; original BIN unchanged; not verified hardware geometry',
                   'virtual_album_hex':self.virtual_album.hex(),
                   'virtual_album_note':'64-byte host album fixture; not a complete device save or verified physical Flash layout',
                   'executed_instructions':self.total_steps,
                   'last_trace':[[f'{pc:06X}',f'{op:04X}'] for pc,op in self.last_trace],
                   'last_adapters':self.last_adapters,'stop_reason':self.stop_reason}
        with path.open('x',encoding='utf-8') as out: json.dump(payload,out,ensure_ascii=False,indent=2)
        return path
