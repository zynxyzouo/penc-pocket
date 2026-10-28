// SPDX-License-Identifier: GPL-3.0-or-later
// Public hosting adaptation, 2026-10-28. See MODIFICATIONS.md.
// Desktop preview cadence, not a claim about hardware LCD refresh frequency.
export class FramePacer {
  constructor(hz=64){this.hz=hz;this.period=1000/hz;this.reset(0);}
  reset(now){this.next=now;this.dropped=0;}
  claim(now,force=false){
    const due=now+1e-6>=this.next?Math.floor((now-this.next)/this.period+1e-8)+1:0;
    if(!due){if(force){this.next+=this.period;return 1;}return 0;}
    this.next+=due*this.period;this.dropped+=Math.max(0,due-3);
    return Math.min(3,due);
  }
  delay(now){return Math.max(1,Math.min(33,Math.ceil(this.next-now)));}
}
