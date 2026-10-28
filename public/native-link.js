// SPDX-License-Identifier: GPL-3.0-or-later
// Public hosting adaptation, 2026-10-28. See MODIFICATIONS.md.
import {drawPairQR,parsePairCode,pairUrl,QrScanner} from './link-qr.js';
import {relayEndpoint,relayUnavailable} from './hosting.js';
import {RelayTransport} from './relay-transport.js';
const $=id=>document.getElementById(id);
const token=()=>[...crypto.getRandomValues(new Uint8Array(32))].map(x=>x.toString(16).padStart(2,'0')).join('');
export class LinkRoom {
 constructor({rpc,prepare,resume,display,onError=e=>this.message(e.message),renderQR=drawPairQR,scanner,endpoint=relayEndpoint,transport}){
  Object.assign(this,{rpc,prepare,resume,display,onError,renderQR,endpoint});
  this.transport=transport||(endpoint?new RelayTransport({endpoint}):null);
  this.session=null;this.engine=false;this.generation=0;this.busy=false;this.autoResume=false;
  this.scanner=scanner||new QrScanner({video:$('link-video'),canvas:$('link-scan-canvas'),onCode:value=>{this.stopScanner();void this.pair(value);},onStatus:(text,active)=>{this.scanning=active;this.scanUI();$('link-scan-status').textContent=text;}});
  $('link-open').onclick=()=>this.open();$('link-create').onclick=()=>this.enter();$('link-join').onclick=()=>this.pair($('link-code-input').value);
  $('link-close').onclick=()=>this.close();$('link-dialog').addEventListener('cancel',e=>{e.preventDefault();this.close();});
  $('link-return').onclick=()=>this.returnToGame();$('link-disconnect').onclick=$('link-indicator').onclick=()=>this.end().catch(()=>{});
  $('link-scan').onclick=()=>this.scanning?this.stopScanner():this.scanner.start();
  $('link-image').onchange=e=>{this.stopScanner();void this.scanner.image(e.target.files[0]);e.target.value='';};
  $('link-copy').onclick=async()=>{try{await navigator.clipboard.writeText(pairUrl(this.session.code));this.message('連線連結已複製。');}catch{this.message('請掃描 QR 碼，或手動輸入下方代碼。');}};
  document.addEventListener('visibilitychange',()=>{if(document.hidden)this.stopScanner();});
  globalThis.addEventListener?.('pagehide',()=>{this.stopScanner();if(this.session)void this.end().catch(()=>{});});
 }
 message(text){$('link-status').textContent=text;}
 stopNotice(text){this.message(text);$('menu-dialog').close();if(!$('link-dialog').open)$('link-dialog').showModal();}
 scanUI(){$('link-camera').hidden=!this.scanning;$('link-qr').hidden=!!this.scanning;$('link-scan').textContent=this.scanning?'停止掃描':'掃描對方 QR';}
 stopScanner(){this.scanner.stop();this.scanning=false;this.scanUI();}
 show(){
  const s=this.session,hasCode=!!s?.code;
  $('link-entry').hidden=hasCode;$('link-session').hidden=!hasCode;$('link-return').hidden=!this.engine;
  $('link-scan-tools').hidden=this.engine;$('link-qr-wrap').hidden=this.engine;
  $('link-indicator').hidden=!hasCode&&!this.cleanupNeeded;$('link-indicator').disabled=!!this.ending;
  $('link-indicator').textContent=this.ending?'斷線中…':this.cleanupNeeded?'重試斷線':this.engine?'● 已連線 · 中斷':'○ 等待連線 · 中斷';
  $('link-indicator').setAttribute('aria-label',this.engine?'已連線，點一下中斷連線':'等待連線，點一下中斷');
  if(hasCode){$('link-code').textContent=s.code;$('link-role').textContent=this.engine?'兩支手機已接通':'讓對方掃描，或掃描對方';if(this.drawnCode!==s.code){this.renderQR($('link-qr'),s.code);this.drawnCode=s.code;}}
 }
 async open({peer}={}){
  if(!this.endpoint){this.message(relayUnavailable);return;}
  if(peer)this.queuedPeer=peer;
  if(this.opening)return;this.opening=true;
  try{
   if(this.endPromise)await this.endPromise;if(this.cleanupNeeded)await this.end();const generation=this.generation;
   await this.prepare();if(generation!==this.generation)return;
   const r=await this.rpc('native-link-info');if(generation!==this.generation)return;this.profile=r.native_link.profile;
   if(!this.profile)throw Error('這份 BIN 的原生通訊尚未支援。');
   this.autoResume=true;$('menu-dialog').close();if(!$('link-dialog').open)$('link-dialog').showModal();
   this.show();this.message(this.engine?'已接通。回到遊戲，選擇 BATTLE 或 JOGRES。':'正在準備你的 QR 碼…');
   if(!this.session?.code)await this.enter();
   if(generation!==this.generation)return;
   while(this.queuedPeer&&!this.engine&&generation===this.generation){const next=this.queuedPeer;this.queuedPeer=null;await this.pair(next);if((this.session?.peer||this.engine)&&globalThis.location?.hash==='#link='+next)history.replaceState(null,'',location.pathname+location.search);}
  }catch(e){$('status').textContent=e.message;this.message(e.message);}finally{this.opening=false;}
 }
 async followInvite(){
  if(!this.endpoint){this.message(relayUnavailable);return;}
  if(!globalThis.location?.hash?.startsWith('#link='))return;
  let peer;try{peer=parsePairCode(location.href);}catch(e){this.message(e.message);return;}
  await this.open({peer});if(this.session?.peer||this.engine)history.replaceState(null,'',location.pathname+location.search);
 }
 close(){this.stopScanner();this.autoResume=false;$('link-dialog').close();if(!$('menu-dialog').open)$('menu-dialog').showModal();}
 returnToGame(){this.stopScanner();this.autoResume=false;$('link-dialog').close();$('menu-dialog').close();this.resume();}
 async request(action,fields={},session=this.session){
  if(!this.endpoint)throw Error(relayUnavailable);
  return this.transport.request(action,fields,session);
 }
 async enter(){if(!this.endpoint){this.message(relayUnavailable);return;}if(this.busy||this.ending||this.cleanupNeeded)return;this.session||={token:token(),code:null};await this.exchange();}
 async pair(value){
  if(!this.endpoint){this.message(relayUnavailable);return;}
  if(this.engine||this.ending||this.cleanupNeeded)return;
  let peer;try{peer=parsePairCode(value);}catch(e){this.message(e.message);return;}
  this.session||={token:token(),code:null};
  if(peer===this.session.code){this.message('這是自己的 QR 碼，請掃描另一支手機。');return;}
  this.stopScanner();this.session.peer=peer;this.message('正在接通另一支手機…');clearTimeout(this.timer);await this.exchange();
 }
 async exchange(){
  if(this.busy||!this.session||this.ending)return;this.busy=true;const generation=this.generation,session=this.session;clearTimeout(this.timer);
  const action=!session.code?'create':session.peer?'pair':'exchange';let fields={};
  try{
   if(action==='exchange'){
    const meta=this.engine?(await this.rpc('native-link-info')).native_link:{received:0,packets:[]};if(generation!==this.generation)return;
    fields={received:meta.received,packets:meta.packets.slice(0,16)};
   }else fields={profile:this.profile,...(action==='pair'?{peer:session.peer}:{})};
   const s=await this.request(action,fields,session);
   if(generation!==this.generation){if(s.code&&['create','pair'].includes(action)){try{await this.request('leave',{}, {...session,code:s.code});}catch{}}return;}
   session.code=s.code;session.slot=s.slot;
   if(s.closed){await this.end(false);this.stopNotice('對方已離線或連線已逾時，請重新配對。');return;}
   if(s.connected&&!this.engine){
    session.peer=null;this.connecting=true;let r;try{r=await this.rpc('native-link-connect',{session:session.code,slot:s.slot});}finally{this.connecting=false;}
    if(generation!==this.generation)return;this.engine=true;this.display(r);this.stopScanner();this.message('已接通，請在遊戲裡選擇 BATTLE 或 JOGRES。');
    if(this.autoResume)this.returnToGame();
   }
   if(this.engine){const r=await this.rpc('native-link-receive',{session:session.code,packets:s.packets,accepted:s.accepted});if(generation!==this.generation)return;if(r.rgba)this.display(r);}
   if(action==='create'&&!s.connected)this.message('兩邊都有 QR 碼，任一方掃描就能接通。不同 BIN 可使用相容的通訊。');
   this.failures=0;this.show();
  }catch(e){
   if(generation!==this.generation)return;
   this.failures=(this.failures||0)+1;
   if(e.terminal||e.retryable!==true||this.failures>=3){await this.end(true);this.stopNotice(e.message+' 連線已停止；需要再次連線時，請重新開啟配對。');}
   else this.message(e.message+'；正在重試連線。');
  }finally{
   if(generation===this.generation){this.busy=false;this.show();if(this.session)this.timer=setTimeout(()=>this.exchange(),Math.min(3000,350*(this.failures||1)));}
  }
 }
 update(meta){if(this.engine&&meta&&!meta.connected&&!this.ending)void this.end(true).catch(()=>{});}
 end(notify=true){
  if(this.endPromise)return this.endPromise;this.ending=true;this.queuedPeer=null;this.stopScanner();
  const session=this.session,needsDisconnect=this.engine||this.connecting||this.cleanupNeeded;this.generation++;clearTimeout(this.timer);this.engine=false;this.busy=false;this.autoResume=false;this.failures=0;this.show();
  this.transport?.close();
  this.endPromise=(async()=>{
   try{
    if(needsDisconnect){const r=await this.rpc('native-link-disconnect');this.display(r);}
    this.cleanupNeeded=false;this.session=null;this.drawnCode=null;
    if(notify&&session?.code){try{await this.request('leave',{},session);}catch{}}
    this.message('連線已中斷。重新開啟配對會產生新的 QR 碼。');
   }catch(e){this.cleanupNeeded=true;this.session=session;this.message('中止連線未完成，遊戲已暫停。請再按「中斷連線」。');this.onError(e);throw e;}
   finally{this.ending=false;this.show();}
  })().finally(()=>{this.endPromise=null;});return this.endPromise;
 }
}
