// SPDX-License-Identifier: GPL-3.0-or-later
// Public hosting adaptation, 2026-10-28. See MODIFICATIONS.md.
// The display projection does not participate in snapshots or firmware execution.
export class PixelView {
  constructor(canvas) {
    this.canvas=canvas;
    this.ctx=canvas.getContext('2d',{alpha:false});
    this.native=null;this.wide=null;
    this.mode='focus';
    try{if(localStorage.getItem('penc-view-mode')==='standard')this.mode='standard';}catch{}
    this.nativeSurface=document.createElement('canvas');this.nativeSurface.width=96;this.nativeSurface.height=96;
    this.wideSurface=document.createElement('canvas');this.wideSurface.width=144;this.wideSurface.height=96;
    this.hudSurface=document.createElement('canvas');this.hudSurface.width=432;this.hudSurface.height=36;
    this.hud=null;
    this.landscapeOverride=null;
    this.landscape=matchMedia('(orientation:landscape)');
    this.landscape.addEventListener('change',()=>this.draw());
  }
  decode(encoded,width,height=96) {
    const raw=atob(encoded),pixels=new Uint8ClampedArray(raw.length);
    if(raw.length!==width*height*4)throw new Error('顯示資料長度不正確。');
    for(let i=0;i<raw.length;i++)pixels[i]=raw.charCodeAt(i);
    return new ImageData(pixels,width,height);
  }
  update(frame) {
    // Display geometry belongs to the selected view mode, not a firmware page.
    if(!frame.rgba)return;
    this.family=frame.family||'penc';
    this.native=this.decode(frame.rgba,96);this.nativeSurface.getContext('2d').putImageData(this.native,0,0);
    this.wide=frame.wide_rgba?this.decode(frame.wide_rgba,144):null;
    if(this.wide)this.wideSurface.getContext('2d').putImageData(this.wide,0,0);
    this.hud=frame.hud_rgba?this.decode(frame.hud_rgba,432,36):null;
    if(this.hud)this.hudSurface.getContext('2d').putImageData(this.hud,0,0);
    this.draw();
  }
  setMode(mode) {
    this.mode=mode==='standard'?'standard':'focus';
    try{localStorage.setItem('penc-view-mode',this.mode);}catch{}
    this.draw();
  }
  setLandscape(value){
    const next=typeof value==='boolean'?value:null;
    if(this.landscapeOverride===next)return;
    this.landscapeOverride=next;this.draw();
  }
  draw() {
    if(!this.native)return;
    const wide=this.landscapeOverride??this.landscape.matches,focus=wide&&this.mode==='focus'&&this.family==='penc';
    const width=focus?432:wide?144:96,height=focus?288:96;
    if(this.canvas.width!==width)this.canvas.width=width;
    if(this.canvas.height!==height)this.canvas.height=height;
    this.canvas.setAttribute('aria-label',focus?'放大模擬畫面，上下圖示縮小':wide?'144 × 96 寬景模擬畫面':'96 × 96 原比例模擬畫面');
    if(focus){
      // 18+60+18 source rows become 6+84+6 display units. The scene
      // scales uniformly by 1.4; extra mirrored scenery is cropped first.
      // A 3x backing canvas keeps all 18 original icon rows legible.
      const hud=18,sceneHeight=height-hud*2,scale=sceneHeight/60;
      this.ctx.imageSmoothingEnabled=false;
      this.ctx.fillStyle='#cbdcc7';this.ctx.fillRect(0,0,width,height);
      const scene=this.wide?this.wideSurface:this.nativeSurface,sceneWidth=this.wide?144:96;
      this.ctx.drawImage(scene,0,18,sceneWidth,60,(width-sceneWidth*scale)/2,hud,sceneWidth*scale,sceneHeight);
      if(this.hud){
        this.ctx.drawImage(this.hudSurface,0,0,432,18,0,0,width,hud);
        this.ctx.drawImage(this.hudSurface,0,18,432,18,0,height-hud,width,hud);
      }else{
        // Keep colours continuous even before a projected HUD is available.
        const left=(width-96)/2;
        for(const [sourceY,destY] of [[0,0],[78,height-hud]]){
          this.ctx.drawImage(this.nativeSurface,0,sourceY,1,18,0,destY,left,18);
          this.ctx.drawImage(this.nativeSurface,95,sourceY,1,18,left+96,destY,left,18);
          this.ctx.drawImage(this.nativeSurface,0,sourceY,96,18,left,destY,96,18);
        }
      }
      return;
    }
    if(wide&&this.wide)this.ctx.putImageData(this.wide,0,0);
    else {
      this.ctx.fillStyle='#d8e5d0';this.ctx.fillRect(0,0,width,96);
      if(wide&&this.family!=='penc'){
        this.ctx.imageSmoothingEnabled=false;
        this.ctx.drawImage(this.nativeSurface,0,0,1,96,0,0,24,96);
        this.ctx.drawImage(this.nativeSurface,95,0,1,96,120,0,24,96);
      }
      this.ctx.putImageData(this.native,wide?24:0,0);
    }
  }
}
