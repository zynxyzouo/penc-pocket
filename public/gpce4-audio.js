// SPDX-License-Identifier: GPL-3.0-or-later
// Observe accepted native calls only. Internal-ROM playback/busy completion is
// untouched. Browser pitch, duration, rest interpretation and gain approximate
// the existing SoundPlayer calibration; this is not decoded hardware audio.
const FLASH_SIZE=8388608,FRONT_START=0xa0,FRONT_END=0x212,TABLE=0x40000,SOUND_COUNT=24;
const FRONT_SHA256='7dc6f900aef5b3c220f15acb6514f22b5d455304040032214beb6a5e7d44ad85';
const NOTES=new Set([29,31,34,36,38,40,41,43,45,46,47,48,49,50,51,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,72,73,74]);

// Pure bounded data decoder. Calling this alone does not admit a firmware;
// the observer below checks the native request front end before playback.
export function decodeGpce4Sequence(bytes,id){
 if(!(bytes instanceof Uint8Array)||bytes.length<TABLE+SOUND_COUNT*4||!Number.isInteger(id)||id<0||id>=SOUND_COUNT)return null;
 const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength),word=at=>view.getUint16(at,true);
 const start=word(TABLE+id*4)*2;
 if(word(TABLE+id*4+2)!==0x20||start<=0||start>=TABLE-4)return null;
 let limit=Math.min(start+4*129,TABLE,bytes.length),following=null;
 if(id+1<SOUND_COUNT){
  following=word(TABLE+(id+1)*4)*2;
  if(word(TABLE+(id+1)*4+2)!==0x20||following<start+4||following>TABLE)return null;
  limit=Math.min(limit,following);
 }
 if(word(start)!==1)return null;
 const notes=[];let total=0;
 for(let at=start+2;at+2<=limit;at+=4){
  const note=word(at);
  if(note===65535)return notes.length&&(following===null||at+2===following)?{id,notes,approximate:true}:null;
  if(notes.length>=128||at+4>limit||!NOTES.has(note))return null;
  const duration=word(at+2);total+=duration;
  if(duration<1||duration>4096||total>32768)return null;
  notes.push([note,duration]);
 }
 return null;
}

export class Gpce4AudioObserver{
 static async create(bytes){
  const front=bytes instanceof Uint8Array&&bytes.length===FLASH_SIZE?bytes.slice(FRONT_START,FRONT_END):null;
  const digest=front?[...new Uint8Array(await crypto.subtle.digest('SHA-256',front))].map(x=>x.toString(16).padStart(2,'0')).join(''):null;
  return new Gpce4AudioObserver(digest===FRONT_SHA256?front:null);
 }
 constructor(front){this.front=front;this.supported=!!front;}
 admitted(bytes){return this.supported&&this.front.every((value,i)=>bytes[FRONT_START+i]===value);}
 consume(e){
  // Queue is ephemeral, excluded from snapshots, and cleared even for foreign
  // firmware. No RAM polling, completion timer, or writes to firmware state.
  try{
   const count=e.gp_audio_event_count();
   if(!this.supported||!Number.isInteger(count)||count<1||count>8)return [];
   const bytes=new Uint8Array(e.memory.buffer,e.gp_flash_ptr(),FLASH_SIZE);
   if(!this.admitted(bytes))return [];
   const raw=new Uint32Array(e.memory.buffer,e.gp_audio_events_ptr(),count*4),events=[];
   for(let i=0;i<count;i++){
    if(raw[i*4+1]!==0)continue;
    const event=decodeGpce4Sequence(bytes,raw[i*4]);
    if(event)events.push(event);
   }
   return events;
  }catch{return [];}
  finally{e.gp_audio_clear?.();}
 }
}
