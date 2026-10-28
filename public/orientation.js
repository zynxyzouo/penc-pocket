// SPDX-License-Identifier: GPL-3.0-or-later
// Public hosting adaptation, 2026-10-28. See MODIFICATIONS.md.
// Display-only fallback: never rewrites firmware, snapshots or system settings.
export function displayGeometry(width,height,forced){
  const rotated=!!forced&&height>width;
  return {width:rotated?height:width,height:rotated?width:height,rotated,landscape:!!forced||width>height};
}
export class DisplayOrientation {
  constructor({root,icon,menu,label,onChange,onToggle=()=>{},env=window}){
    Object.assign(this,{root,icon,menu,label,onChange,onToggle,env});
    this.forced=false;this.locked=false;this.pending=null;
    icon.onclick=menu.onclick=()=>this.toggle();
    env.addEventListener('resize',()=>this.update());
    env.visualViewport?.addEventListener('resize',()=>this.update());
    env.screen?.orientation?.addEventListener?.('change',()=>this.update());
    this.update();
  }
  update(){
    const geometry=displayGeometry(this.env.innerWidth,this.env.innerHeight,this.forced);
    this.root.dataset.rotated=String(geometry.rotated);
    this.root.dataset.landscape=String(this.forced);
    this.root.style.setProperty('--display-width',geometry.width+'px');
    this.root.style.setProperty('--display-height',geometry.height+'px');
    const title=this.forced?'回到自動方向':'一鍵橫向';
    for(const button of [this.icon,this.menu])button.setAttribute('aria-pressed',String(this.forced));
    this.icon.setAttribute('aria-label',title);this.icon.setAttribute('title',title);this.menu.textContent=title;
    this.label.textContent=this.forced?'橫向顯示已開啟，將手機橫拿即可；再按一次回到自動方向。':'自動跟隨畫面方向；也可一鍵切成橫向，不需重載遊戲。';
    this.onChange(geometry);
  }
  unlock(){
    try{this.env.screen?.orientation?.unlock?.();}catch{}
    this.locked=false;
  }
  async toggle(){
    this.onToggle();this.forced=!this.forced;
    if(!this.forced&&this.locked)this.unlock();
    this.update();
    const orientation=this.env.screen?.orientation;
    if(!this.forced||this.pending||typeof orientation?.lock!=='function')return;
    // Some mobile contexts permit locking; others require fullscreen or reject
    // it entirely. The visible CSS fallback works immediately in every case.
    const request=Promise.resolve().then(()=>orientation.lock('landscape'));
    this.pending=request;
    try{await request;if(this.forced)this.locked=true;else this.unlock();}
    catch{/* Keep the usable CSS fallback without an error/permission dialog. */}
    finally{if(this.pending===request)this.pending=null;this.update();}
  }
}
