# SPDX-License-Identifier: GPL-3.0-or-later
# PenC Pocket integration; release/license notice updated 2026-10-28.
"""Hash-admitted packet peripheral for the native CONNECT state machines.

The immutable BIN builds/validates all eight words, selects results, animates,
and saves. This replaces GPIO/ROM receive timing with peer packet delivery;
it is not physical wire/IRQ emulation. CCC=6 means an actual complete peer
packet was delivered, never a forced handshake or game-success return value.
"""
import copy
import hashlib

SIGNATURES = (
    (0x2084e9,0x208571,'25c92b9a8e6a27673c3e77a6a4579204efe02aa696398134d708838b32a630fb'),
    (0x208571,0x208595,'938cb122f598d585552454d20b099095adfd7690145d1c5d72312da284336406'),
    (0x208595,0x2085bf,'d1320b01c4b9be3008c4983ad37857379013039a73dc201af96fff6ce8918d70'),
    (0x2085bf,0x208763,'1bf6e237470a822813856bd0329d46badf89e1ea50c03c2bd152b0253beab76f'),
    (0x208763,0x208926,'8855ca1f7b7d91aa1d288b54d2167c69c496be18b8f7540d0577f9103ff5945f'),
    (0x208926,0x208a82,'b3459df2929ad8ad9d53871039c5acb16b4ecf2324c016c84ba810040dd54497'),
    (0x21f3d0,0x21f562,'18c241eb6134710b3320678e8f8e005d5ae126c64c99241cc4ca771f2c106f3b'),
)
TRANSPORT_ID = hashlib.sha256(''.join(s[2] for s in SIGNATURES).encode()).hexdigest()
PHYSICAL_MAINS = (0x0f,0x10,0x13)
MAX_PACKETS = 512


def supports(code):
    return all(hashlib.sha256(code[2*(a-0x200000):2*(z-0x200000)]).hexdigest()==h
               for a,z,h in SIGNATURES)


def _words(value):
    if (not isinstance(value,list) or len(value)!=8
            or any(type(w) is not int or not 0<=w<=65535 for w in value)):
        raise ValueError('Native packets require exactly eight uint16 words')
    return tuple(value)


def _waiting_stage(bench):
    m=bench.ram
    return ((m.get(0xc9c),m.get(0xc9e)) in ((0x0f,3),(0x10,1),(0x13,1)))


class Cable:
    def __init__(self):
        self.clear()

    def clear(self):
        self.bench=None
        self.session=None
        self.slot=None
        self.connected=False
        self.finishing=False
        self.rx={}
        self.rx_history={}
        self.received=0
        self.tx=[]
        self.next_seq=1
        self.accepted=0
        self.active=False
        self.checkpoint=None
        self.staged=[]
        self.consuming=None

    def handles(self,bench):
        return self.bench is bench and (self.connected or self.finishing)

    def connect(self,bench,session,slot):
        if not supports(bench.code):raise ValueError('This BIN has no verified native packet boundary')
        if not isinstance(session,str) or not 1<=len(session)<=128:raise ValueError('Invalid cable session')
        if slot not in (0,1,'a','b','A','B'):raise ValueError('Invalid cable slot')
        if self.connected:
            if self.bench is bench and self.session==session and self.slot==slot:return self.metadata(bench)
            raise ValueError('Disconnect the current cable before pairing again')
        self.clear()
        self.bench=bench;self.session=session;self.slot=slot;self.connected=True
        return self.metadata(bench)

    def receive(self,bench,session,packets,accepted=None):
        if self.bench is not bench or not self.connected or session!=self.session:
            raise ValueError('Stale or disconnected native cable session')
        if self.active:raise ValueError('Cannot deliver packets inside a native frame')
        if not isinstance(packets,list) or len(packets)>MAX_PACKETS:raise ValueError('Invalid native packet batch')
        trial=dict(self.rx)
        maximum=self.received+len(trial)
        for packet in packets:
            if not isinstance(packet,dict) or set(packet)!={'seq','words'}:raise ValueError('Invalid native packet envelope')
            seq=packet['seq'];words=_words(packet['words'])
            if type(seq) is not int or not 1<=seq<=MAX_PACKETS:raise ValueError('Invalid native packet sequence')
            old=self.rx_history.get(seq,trial.get(seq))
            if old is not None:
                if old!=words:raise ValueError('Native packet retry changed its bytes')
                continue
            if seq!=maximum+1:raise ValueError('Native packets must arrive in order')
            trial[seq]=words;maximum=seq
        if accepted is not None:
            if type(accepted) is not int or not 0<=accepted<self.next_seq:
                raise ValueError('Relay acknowledged an unsent native packet')
        self.rx=trial
        if accepted is not None and accepted>self.accepted:
            self.accepted=accepted
            self.tx=[p for p in self.tx if p['seq']>accepted]
        return self.metadata(bench)

    def waiting(self,bench):
        if not self.handles(bench) or not _waiting_stage(bench):return False
        m=bench.ram
        if m.get(0xca0)!=1 or m.get(0xccc)!=1 or self.rx:return False
        # Initial listening accepts A/B to emit the first native command. Once
        # sent, suspend whole frames while network time passes. Never adjust
        # the native 33-frame reply deadline or choose its timeout branch.
        address,initial=(0x86a,0) if m[0xc9c]==0x10 else (0x86b,0x10 if m[0xc9c]==0x0f else 0x14)
        return m.get(address)!=initial

    def begin(self,bench):
        if self.active:raise ValueError('Native cable frame already active')
        if not self.handles(bench):return True
        if self.waiting(bench):return False
        self.active=True
        self.checkpoint=(dict(bench.ram),bench.virtual_flash,bench.virtual_album,set(bench.previous_keys))
        self.staged=[];self.consuming=None
        if self.connected and self.rx and bench.ram.get(0xca0)==1 and bench.ram.get(0xccc)==1:
            seq=self.received+1
            words=self.rx[seq]
            for i,w in enumerate(words):bench.ram[0xcce+i]=w
            bench.ram[0xccc]=6
            self.consuming=seq
        return True

    def call(self,cpu,target,ret):
        if (not self.active or self.bench is None or cpu.code is not self.bench.code
                or not cpu.allow_adapters or target not in (0x2084e9,0x208571,0x208595,0x208926)):
            return False
        cpu.calls.append(target)
        if target==0x2084e9:
            if not self.connected:raise ValueError('Native cable was disconnected before receive setup')
            for address,value in {0xccc:1,0xccd:0,0xcd6:0,0xca0:1,**{a:0 for a in range(0xcce,0xcd6)}}.items():
                cpu.write(address,value)
        elif target in (0x208571,0x208595):
            cpu.write(0xccc,0);cpu.write(0xca0,0)
        else:
            if not self.connected:raise ValueError('Native cable was disconnected before send')
            if self.next_seq+len(self.staged)>MAX_PACKETS:raise ValueError('Native cable session packet limit reached')
            self.staged.append([cpu.read(a) for a in range(0xce0,0xce8)])
        cpu.adapters.append({'target':f'{target:06X}','kind':'peer packet peripheral; native builder/validator/gameplay unchanged'})
        cpu.setpc(ret)
        return True

    def commit(self,bench):
        if not self.active:return
        if self.bench is not bench:raise ValueError('Wrong native cable frame owner')
        if self.consuming is not None:
            seq=self.consuming;self.rx_history[seq]=self.rx.pop(seq);self.received=seq
        for words in self.staged:
            self.tx.append({'seq':self.next_seq,'words':words});self.next_seq+=1
        self.active=False;self.checkpoint=None;self.staged=[];self.consuming=None
        if self.finishing and bench.ram.get(0xc9c) not in PHYSICAL_MAINS:self.finishing=False

    def rollback(self,bench):
        if self.active and self.bench is bench:
            bench.ram,bench.virtual_flash,bench.virtual_album,bench.previous_keys=self.checkpoint
        self.active=False;self.checkpoint=None;self.staged=[];self.consuming=None

    def disconnect(self,bench,cancel=True):
        if self.active:raise ValueError('Cannot disconnect inside a native frame')
        is_physical=bench.ram.get(0xc9c) in PHYSICAL_MAINS
        # A settled native animation may finish after the transport closes.
        # It no longer needs incoming packets, and its result must not be reset.
        animation_start={0x0f:5,0x10:3,0x13:3}
        finishing=(is_physical and bench.ram.get(0xc9e,0)>=animation_start[bench.ram[0xc9c]])
        if cancel and is_physical and not finishing:
            if not supports(bench.code):raise ValueError('Cannot cancel an unknown native transport')
            original=copy.deepcopy(bench.__dict__)
            previous=dict(self.__dict__)
            try:
                self.bench=bench;self.active=True
                if bench.ram.get(0xca0)==1:bench.execute(0x208595)
                import native_link_guard
                native_link_guard.recover(bench)
            except Exception:
                bench.__dict__.clear();bench.__dict__.update(original)
                self.__dict__.clear();self.__dict__.update(previous)
                raise
        self.clear()
        if finishing:self.bench=bench;self.finishing=True
        return self.metadata(bench)

    def metadata(self,bench):
        admitted=supports(bench.code)
        owned=self.bench is bench
        return {'supported':admitted,'connected':bool(owned and self.connected),
                'finishing':bool(owned and self.finishing),'session':self.session if owned else None,
                'slot':self.slot if owned else None,'received':self.received if owned else 0,
                'packets':copy.deepcopy(self.tx) if owned else [],
                'waiting':self.waiting(bench),
                'profile':{'firmware':bench.sha256,'transport':TRANSPORT_ID} if admitted else None}


cable=Cable()
