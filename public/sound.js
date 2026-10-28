// SPDX-License-Identifier: GPL-3.0-or-later
// Public hosting adaptation, 2026-10-28. See MODIFICATIONS.md.
// Host synthesis from BIN note pairs. Pitch/timing/waveform are approximate.
// Listening calibration confirmed by the user; not a recovered ROM table.
const PITCH_SEMITONES=48,PLAYBACK_RATE=2,ENABLED_KEY='penc-audio-enabled-v1';
const AUDIO_LEAD_MS=10;
// Native completion may advance only after the producing frame has reached
// the browser. Never count that frame's own worker/render cost as playback.
export class SoundTimeline {
  constructor(){this.anchor=0;}
  reset(now){this.anchor=now;}
  claim(now,active){const elapsed=active?Math.max(0,now-this.anchor):0;this.anchor=Math.max(now,this.anchor);return elapsed;}
  acknowledge(started,now){if(started)this.anchor=now+AUDIO_LEAD_MS;}
}
export class SoundPlayer {
  constructor(button,status,volume,{preview}={}){
    this.button=button;this.status=status;this.volume=volume;this.enabled=false;this.context=null;this.nodes=[];
    this.preview=preview;this.lastEvent=null;this.playbackGeneration=0;
    this.nativeLevel=null;this.master=null;
    this.wanted=true;this.error='';this.activating=null;this.activation=0;
    try{this.wanted=localStorage.getItem(ENABLED_KEY)!=='false';}catch{}
    if(preview)preview.onclick=async()=>{
      if(!this.enabled||!this.lastEvent)return;
      const generation=this.playbackGeneration,event=this.lastEvent;
      try{await this.context.resume();if(this.enabled&&generation===this.playbackGeneration)this.play([event]);}
      catch{this.status.textContent='無法試聽，請重新啟用聲音。';}
    };
    button.onclick=()=>this.wanted?this.disable():this.enable();
    this.update();
  }
  get transpose(){return PITCH_SEMITONES;}
  get playbackRate(){return PLAYBACK_RATE;}
  setNativeSettings(settings){
    if(!settings)return;
    this.nativeLevel=settings.supported&&[0,1,2].includes(settings.volume_level)?settings.volume_level:null;
    if(this.nativeLevel===0)this.stop();
    this.applyNativeGain();this.update();
  }
  applyNativeGain(){
    if(!this.master)return;
    // Small/loud are relative browser levels, not measured piezo amplitudes.
    this.master.gain.setValueAtTime(this.nativeLevel===0?0:this.nativeLevel===2?1:.5,this.context.currentTime);
  }
  remember(){try{localStorage.setItem(ENABLED_KEY,String(this.wanted));}catch{}}
  enable(){this.wanted=true;this.remember();this.error='';return this.activateFromGesture();}
  disable(){this.wanted=false;this.enabled=false;this.activation++;this.activating=null;this.error='';this.remember();this.stop();this.update();}
  activateFromGesture(){
    if(!this.wanted)return Promise.resolve(false);
    if(this.activating)return this.activating;
    if(this.enabled&&this.context?.state==='running')return Promise.resolve(true);
    const generation=this.activation;let request;
    try{
      const Audio=window.AudioContext||window.webkitAudioContext;
      if(!Audio)throw new Error('此瀏覽器未提供網頁音訊。');
      this.context||=new Audio();request=this.context.resume();
    }catch(e){this.enabled=false;this.error=e.message;this.update();return Promise.resolve(false);}
    this.activating=Promise.resolve(request).then(()=>{
      if(generation!==this.activation||!this.wanted)return false;
      if(this.context.state!=='running')throw new Error('聲音尚未啟動，請再按開始或關閉後重新啟用。');
      this.enabled=true;this.error='';this.update();return true;
    }).catch(e=>{if(generation===this.activation){this.enabled=false;this.error=e.message;this.update();}return false;})
      .finally(()=>{if(generation===this.activation)this.activating=null;});
    return this.activating;
  }
  update(){
    this.button.textContent=this.wanted?'停用聲音':'啟用聲音';this.button.setAttribute('aria-pressed',String(this.wanted));
    this.status.textContent=this.error||(this.enabled?'聲音已開啟。回遊戲按 A／B／C 後，可在此試聽最近音效。':this.wanted?'預設開啟；按「開始／繼續」時啟動聲音。':'聲音已關閉，會記住你的選擇。');
    if(this.enabled&&this.nativeLevel===0)this.status.textContent='遊戲內已靜音；可在遊戲設定調整。';
    if(this.preview)this.preview.disabled=!this.enabled||!this.lastEvent||this.nativeLevel===0;
  }
  resume(){if(this.enabled)this.context?.resume().catch(()=>{});}
  stop(){this.playbackGeneration++;for(const node of this.nodes){try{node.stop();}catch{}try{node.disconnect();}catch{}}this.nodes=[];}
  clearPreview(){this.stop();this.lastEvent=null;this.update();}
  play(events){
    if(!events?.length)return;
    const event=events.at(-1);if(!Array.isArray(event?.notes)||!event.approximate)return;
    if(!event.notes.length||event.notes.length>128||!event.notes.every(pair=>Array.isArray(pair)&&pair.length===2&&Number.isInteger(pair[0])&&pair[0]>=0&&pair[0]<=127&&Number.isInteger(pair[1])&&pair[1]>0&&pair[1]<=4096))return;
    if(event.notes.reduce((sum,pair)=>sum+pair[1],0)>32768)return;
    this.lastEvent={approximate:true,notes:event.notes.map(pair=>[...pair])};
    if(this.preview)this.preview.disabled=!this.enabled||this.nativeLevel===0;
    if(!this.enabled||this.context?.state!=='running'||this.nativeLevel===0)return;
    if(!this.master){this.master=this.context.createGain();this.master.connect(this.context.destination);}
    this.applyNativeGain();
    this.stop();let start=this.context.currentTime+AUDIO_LEAD_MS/1000;
    const loudness=.03;
    for(const [note,word] of event.notes){
      const duration=word/1000/this.playbackRate;
      // 74 is a candidate rest code in this admitted table, not confirmed ROM semantics.
      if(note!==74&&loudness){
        const osc=this.context.createOscillator(),gain=this.context.createGain();
        // +48 is the user's confirmed listening setting, not a decoded table.
        osc.type='square';osc.frequency.value=Math.min(this.context.sampleRate/2||22050,440*Math.pow(2,(note+this.transpose-69)/12));
        gain.gain.setValueAtTime(0,start);gain.gain.linearRampToValueAtTime(loudness,start+Math.min(.005,duration/4));
        gain.gain.setValueAtTime(loudness,start+duration-Math.min(.01,duration/4));gain.gain.linearRampToValueAtTime(0,start+duration);
        osc.connect(gain);gain.connect(this.master);osc.start(start);osc.stop(start+duration);
        osc.onended=()=>{osc.disconnect();gain.disconnect();};this.nodes.push(osc);
      }
      start+=duration;
    }
  }
}
