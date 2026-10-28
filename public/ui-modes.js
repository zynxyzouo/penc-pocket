// SPDX-License-Identifier: GPL-3.0-or-later
// Public hosting adaptation, 2026-10-28. See MODIFICATIONS.md.
// View preferences and measurements only. No firmware or save-state writes.
const $=id=>document.getElementById(id);
const modes=['simple','original','developer'];
const descriptions={
  simple:'簡潔模式：保留最大遊戲畫面、時鐘與 ABC 按鍵。',
  original:'原機模式：Pendulum Color 銀藍外殼與按鍵風格，沿用目前的顯示比例。',
  developer:'開發模式：顯示實際畫面更新 FPS、遊戲 RTC、按鍵與 ROM 資訊。'
};
export class DeviceUI {
  constructor(){
    this.running=false;this.loaded=false;this.last=null;this.samples=[];this.fps=0;
    let mode='simple';try{mode=localStorage.getItem('penc-ui-mode')||mode;}catch{}
    for(const name of modes)$('mode-'+name).onclick=()=>this.setMode(name);
    this.setMode(mode);this.setKeys([]);
  }
  setMode(mode){
    this.mode=modes.includes(mode)?mode:'simple';
    document.body.dataset.uiMode=this.mode;
    $('developer-panel').hidden=this.mode!=='developer';
    for(const name of modes)$('mode-'+name).setAttribute('aria-pressed',String(name===this.mode));
    $('mode-description').textContent=descriptions[this.mode];
    try{localStorage.setItem('penc-ui-mode',this.mode);}catch{}
  }
  setRunning(loaded,running,fatal=false){
    this.loaded=loaded;this.running=running;
    this.samples=[];this.fps=0;
    $('dev-fps').textContent=loaded?'0.0':'—';$('dev-sim').textContent=loaded?'0.0 / 64':'—';
    $('dev-status').textContent=fatal?'STOPPED':!loaded?'NO ROM':running?'RUNNING':'PAUSED';
    $('developer-panel').dataset.running=String(running);
  }
  setKeys(keys){
    const pressed=new Set(keys);
    for(const name of ['A','B','C']){
      const el=$('dev-key-'+name);el.dataset.pressed=String(pressed.has(name));
      el.setAttribute('aria-label',name+(pressed.has(name)?' 按下':' 放開'));
    }
  }
  record(frame,{name,hash,bytes},activeFrame=false){
    this.last=frame;
    $('dev-rtc').textContent=frame.clock;
    $('dev-rate').textContent=frame.time_rate+'×';
    $('dev-cost').textContent=frame.worker_ms===undefined?'—':Math.round(frame.worker_ms)+' ms';
    $('dev-cost').title=`原生 ${frame.native_ms??'—'} ms；原生＋繪圖 ${frame.frame_ms??'—'} ms；完整 Worker ${Math.round(frame.worker_ms||0)} ms`;
    $('dev-state').textContent=frame.state+'/'+frame.substate;
    $('dev-rom').textContent=name||'尚未載入';
    $('dev-rom').title=name;
    $('dev-hash').textContent=hash?hash.slice(0,12)+'… · '+(bytes/1048576).toFixed(0)+' MiB':'—';
    $('dev-hash').title=hash?'SHA256 '+hash:'';
    if(activeFrame&&this.running){
      const now=performance.now();this.samples.push({now,frames:frame.completed_frames||1});
      while(this.samples.length>2&&this.samples[1].now<now-1500)this.samples.shift();
      if(this.samples.length>=2){
        const elapsed=now-this.samples[0].now;
        this.fps=(this.samples.length-1)*1000/elapsed;
        $('dev-fps').textContent=this.fps.toFixed(1);
        $('dev-sim').textContent=(this.samples.slice(1).reduce((sum,s)=>sum+s.frames,0)*1000/elapsed).toFixed(1)+' / 64';
      }
    }
  }
}
