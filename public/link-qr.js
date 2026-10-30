// SPDX-License-Identifier: GPL-3.0-or-later
// Public hosting adaptation, 2026-10-28. See MODIFICATIONS.md.
import qrcode from './vendor/qrcode-generator-2.0.4.mjs';
const CODE=/^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{8}$/;
const appBase=()=>new URL('./',import.meta.url).href;
export function pairUrl(code,base=appBase()){if(!CODE.test(code))throw Error('配對代碼格式錯誤。');return new URL((new URL(base).pathname.endsWith('/machine.html')?'':'./')+'#link='+code,base).href;}
export function parsePairCode(value,base=appBase()){
 const raw=String(value).trim(),code=raw.toUpperCase().replace(/[\s-]/g,'');if(CODE.test(code))return code;
 let u;try{u=new URL(raw);}catch{throw Error('請掃描 PenC Pocket 的連線 QR 碼。');}
 const app=new URL('./',base);
 if(u.origin!==app.origin||![app.pathname,new URL('./machine.html',app).pathname].includes(u.pathname)||u.search||u.username||u.password||!/^#link=[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{8}$/.test(u.hash))throw Error('這不是此網站的連線 QR 碼。');
 return u.hash.slice(6);
}
export function qrMatrix(text){const qr=qrcode(0,'M');qr.addData(text);qr.make();return Array.from({length:qr.getModuleCount()},(_,r)=>Array.from({length:qr.getModuleCount()},(_,c)=>qr.isDark(r,c)));}
export function drawPairQR(canvas,code,base=appBase()){
 const matrix=qrMatrix(pairUrl(code,base)),scale=6,quiet=4,size=(matrix.length+quiet*2)*scale;canvas.width=canvas.height=size;
 const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,size,size);ctx.fillStyle='#102820';
 matrix.forEach((row,y)=>row.forEach((dark,x)=>{if(dark)ctx.fillRect((x+quiet)*scale,(y+quiet)*scale,scale,scale);}));
}
let decoder;
async function getDecoder(){return decoder??=(await import('./vendor/jsqr-1.4.0.mjs')).default;}
export class QrScanner {
 constructor({video,canvas,onCode,onStatus,media=globalThis.navigator?.mediaDevices,requestFrame=globalThis.requestAnimationFrame?.bind(globalThis),cancelFrame=globalThis.cancelAnimationFrame?.bind(globalThis)}){Object.assign(this,{video,canvas,onCode,onStatus,media,requestFrame,cancelFrame});this.generation=0;this.stream=null;this.frame=null;}
 stop(){this.generation++;if(this.frame!==null)this.cancelFrame?.(this.frame);this.frame=null;this.stream?.getTracks().forEach(t=>t.stop());this.stream=null;this.video.pause();this.video.srcObject=null;}
 async start(){
  this.stop();const generation=this.generation;this.onStatus('將鏡頭對準另一支手機的 QR 碼。',true);
  try{
   if(!this.media?.getUserMedia)throw Error('這個瀏覽器無法開啟相機，可改選 QR 圖片或輸入代碼。');
   const stream=await this.media.getUserMedia({audio:false,video:{facingMode:{ideal:'environment'},width:{ideal:960},height:{ideal:720}}});
   if(generation!==this.generation){stream.getTracks().forEach(t=>t.stop());return;}
   this.stream=stream;this.video.srcObject=stream;await this.video.play();const decode=await getDecoder();if(generation!==this.generation)return;
   let last=0;const tick=time=>{
    if(generation!==this.generation)return;
    if(this.video.readyState>=2&&time-last>=160){last=time;try{const data=this.frameData(this.video,this.video.videoWidth,this.video.videoHeight);const result=decode(data.data,data.width,data.height,{inversionAttempts:'dontInvert'});if(result){this.stop();this.onCode(result.data);return;}}catch{this.stop();this.onStatus('無法讀取相機畫面，可改選 QR 圖片或輸入代碼。',false);return;}}
    this.frame=this.requestFrame(tick);
   };this.frame=this.requestFrame(tick);
  }catch(e){if(generation!==this.generation)return;this.stop();this.onStatus(e.name==='NotAllowedError'?'相機未獲允許，可改選 QR 圖片或輸入代碼。':e.message,false);}
 }
 frameData(source,width,height){const ratio=Math.min(1,720/Math.max(width,height));this.canvas.width=Math.max(1,Math.round(width*ratio));this.canvas.height=Math.max(1,Math.round(height*ratio));const ctx=this.canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(source,0,0,this.canvas.width,this.canvas.height);return ctx.getImageData(0,0,this.canvas.width,this.canvas.height);}
 async image(file){
  this.stop();if(!file)return;const generation=this.generation;
  if(file.size>15*1024*1024){this.onStatus('圖片過大，請選擇 QR 碼截圖。',false);return;}
  const url=URL.createObjectURL(file);try{const image=new Image();image.src=url;await image.decode();const decode=await getDecoder();if(generation!==this.generation)return;const data=this.frameData(image,image.naturalWidth,image.naturalHeight),result=decode(data.data,data.width,data.height);if(!result)throw Error('找不到 QR 碼，請選擇清楚的截圖。');this.onCode(result.data);}catch(e){if(generation===this.generation)this.onStatus(e.message,false);}finally{URL.revokeObjectURL(url);}
 }
}
