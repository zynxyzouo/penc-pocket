// SPDX-License-Identifier: GPL-3.0-or-later
// Public hosting adaptation, 2026-10-28. See MODIFICATIONS.md.
const ENABLED_KEY='penc-motion-enabled-v1';
const vector=v=>v&&[v.x,v.y,v.z].every(x=>typeof x==='number'&&Number.isFinite(x))?[v.x,v.y,v.z]:null;
// Accept a strong stroke after rest OR a reversal. Sampling may miss the zero
// crossing, and elliptical motion need not reach zero total acceleration.
export class ShakeDetector {
  constructor(){this.reset();}
  reset(){this.gravity=null;this.lastTime=null;this.lastPulse=-Infinity;this.armed=true;this.lastDirection=null;}
  sample(event,now){
    let a=vector(event.acceleration);const raw=vector(event.accelerationIncludingGravity);
    if(!Number.isFinite(now)||(!a&&!raw))return {valid:false,pulse:false};
    const gap=this.lastTime===null?null:now-this.lastTime;this.lastTime=now;
    if(gap!==null&&(gap<0||gap>500)){this.gravity=null;this.armed=true;this.lastDirection=null;}
    if(!a){
      if(!this.gravity){this.gravity=raw;return {valid:true,pulse:false};}
      const alpha=Math.exp(-Math.max(1,gap||16)/250);
      this.gravity=this.gravity.map((v,i)=>alpha*v+(1-alpha)*raw[i]);
      a=raw.map((v,i)=>v-this.gravity[i]);
    }
    const magnitude=Math.hypot(...a);
    if(magnitude<2.5)this.armed=true;
    const reversed=this.lastDirection&&magnitude>=7&&a.reduce((dot,v,i)=>dot+v*this.lastDirection[i],0)/magnitude<=-.5;
    const pulse=!!((this.armed||reversed)&&magnitude>=7&&now-this.lastPulse>=150);
    if(pulse){this.armed=false;this.lastPulse=now;this.lastDirection=a.map(v=>v/magnitude);}
    return {valid:true,pulse};
  }
}
export class PhoneMotion {
  constructor(button,label,canSend,onPulse){
    this.button=button;this.label=label;this.canSend=canSend;this.onPulse=onPulse;
    this.detector=new ShakeDetector();this.enabled=false;this.received=false;this.supported=false;
    this.wanted=true;this.error='';this.activating=null;this.activation=0;this.attempted=false;
    try{this.wanted=localStorage.getItem(ENABLED_KEY)!=='false';}catch{}
    this.handle=event=>{
      if(!this.enabled)return;
      const sample=this.detector.sample(event,performance.now());
      if(sample.valid&&!this.received){this.received=true;this.update();}
      if(sample.pulse&&this.canSend())this.onPulse();
    };
    button.onclick=()=>this.wanted?this.disable():this.enable();
    this.update();
  }
  update(){
    this.button.textContent=this.wanted?'停用手機晃動':'啟用手機晃動';
    this.button.setAttribute('aria-pressed',String(this.wanted));
    this.label.textContent=this.error||(this.enabled?(this.received?(this.supported?'感測器已連接；訓練與連線的晃動階段可使用。':'感測器已連接；目前 BIN 的晃動介面尚未支援。'):'已開啟，等待手機感測資料；沒有資料時請檢查瀏覽器權限。'):this.wanted?'預設開啟；按「開始／繼續」時，若出現動作權限請選允許。':'手機晃動已關閉，會記住你的選擇。');
  }
  setSupported(value){if(this.supported!==!!value){this.supported=!!value;this.update();}}
  reset(){this.detector.reset();}
  remember(){try{localStorage.setItem(ENABLED_KEY,String(this.wanted));}catch{}}
  enable(){this.wanted=true;this.attempted=false;this.error='';this.remember();return this.activateFromGesture();}
  activateFromGesture(){
    if(!this.wanted)return Promise.resolve(false);
    if(this.enabled)return Promise.resolve(true);
    if(this.activating)return this.activating;
    if(this.attempted)return Promise.resolve(false);
    this.attempted=true;const generation=this.activation;let request;
    try{
      if(!window.isSecureContext)throw new Error('手機晃動需要 HTTPS 網頁。');
      const api=window.DeviceMotionEvent;
      if(!api)throw new Error('此瀏覽器沒有提供動作感測器。請使用 iPhone Safari 開啟。');
      // Called synchronously from the same gesture as audio resume, never after awaiting it.
      request=typeof api.requestPermission==='function'?api.requestPermission():'granted';
    }catch(e){this.error=e.message;this.update();return Promise.resolve(false);}
    this.activating=Promise.resolve(request).then(permission=>{
      if(generation!==this.activation||!this.wanted)return false;
      if(permission!=='granted')throw new Error('未取得動作權限。允許權限後，可關閉再啟用手機晃動。');
      this.enabled=true;this.received=false;this.reset();
      window.addEventListener('devicemotion',this.handle);this.error='';this.update();return true;
    }).catch(e=>{if(generation===this.activation){this.error=e.message||'無法取得感測器權限，請關閉後重新啟用。';this.update();}return false;})
      .finally(()=>{if(generation===this.activation)this.activating=null;});
    return this.activating;
  }
  disable(){this.wanted=false;this.enabled=false;this.activation++;this.activating=null;this.attempted=false;this.error='';this.remember();window.removeEventListener('devicemotion',this.handle);this.reset();this.update();}
}
