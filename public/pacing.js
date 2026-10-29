// SPDX-License-Identifier: GPL-3.0-or-later
// Public hosting adaptation, 2026-10-28. See MODIFICATIONS.md.
// Desktop preview cadence, not a claim about hardware LCD refresh frequency.
export class FramePacer {
  constructor(hz=64){this.hz=hz;this.period=1000/hz;this.reset(0);}
  reset(now){this.next=now;this.dropped=0;this.reserved=0;}
  claim(now,force=false){
    const due=now+1e-6>=this.next?Math.floor((now-this.next)/this.period+1e-8)+1:0;
    this.reserved=0;
    if(!due)return force?1:0;
    // Keep at most three owed updates; an overloaded foreground must not
    // accumulate an unbounded replay queue. Urgent input gets its own draw.
    const stale=Math.max(0,due-3);
    this.next+=stale*this.period;this.dropped+=stale;
    this.reserved=force?1:Math.min(3,due);
    this.next+=this.reserved*this.period;
    return this.reserved;
  }
  complete(frames){
    this.next-=Math.max(0,this.reserved-Math.max(0,frames))*this.period;
    this.reserved=0;
  }
  delay(now){return Math.max(0,Math.min(33,Math.ceil(this.next-now)));}
}
