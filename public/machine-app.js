// SPDX-License-Identifier: GPL-3.0-or-later
// Optional reset-boot experiment. All ROMs and snapshots remain in the browser.
import {read,writeMany,erase} from './storage.js';
import {PixelView} from './view.js';
import {DisplayOrientation} from './orientation.js';
import {compatibleCore} from './gpce4-engine.js';
import {SoundPlayer} from './sound.js';
import {PhoneMotion} from './motion.js';
import {LinkRoom} from './native-link.js';
import {relayEndpoint,relayUnavailable} from './hosting.js';

const BATCH=187500,INTERVAL=1000/64,SCHEMA='penc-pocket-gpce4-v1';
const KEY_BITS={A:8,B:16,C:32};
export function validateRememberedCore(boot,identity){
  if(!boot?.core_sha256||!compatibleCore(boot.core_sha256,identity?.core_sha256))throw Error('整機核心版本已變更，舊快照保留且未重新開機。請保留原備份，再選擇要使用的核心版本。');
}
export function machineKey(identity){
  const values=['firmware_sha256','irom_sha256','core_sha256'].map(key=>identity?.[key]);
  if(!values.every(value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value)))throw Error('機器識別資料不完整。');
  return 'gpce4:'+values.join(':');
}
function checkBackup(backup,identity){
  if(backup?.schema!==SCHEMA||!backup.snapshot||typeof backup.snapshot!=='object')throw Error('請選取整機實驗匯出的快照。');
  machineKey(backup.identity);machineKey(identity);
  if(['firmware_sha256','irom_sha256'].some(k=>backup.identity[k]!==identity[k])||!compatibleCore(identity.core_sha256,backup.identity.core_sha256))throw Error('快照的 BIN、內部 ROM 或核心版本不相符；目前進度未更動。');
  return backup.snapshot;
}
export class MachineKeys{
  constructor(){this.sources=new Map();this.taps=new Map();}
  press(source,key){if(!KEY_BITS[key]||this.sources.has(source))return;this.sources.set(source,key);this.taps.set(key,{remaining:.05});}
  release(source){this.sources.delete(source);}
  mask(){let mask=0;for(const key of [...this.sources.values(),...this.taps.keys()])mask|=KEY_BITS[key];return mask;}
  capture(){return new Map(this.taps);}
  advance(seconds,sent,claimed=this.taps){for(const [key,tap] of this.taps)if((sent&KEY_BITS[key])&&claimed.get(key)===tap){tap.remaining-=seconds;if(tap.remaining<=0)this.taps.delete(key);}}
  clear(){this.sources.clear();this.taps.clear();}
}

export class MachineSession{
  constructor({rpc,read,writeMany,erase,onFrame=()=>{},onState=()=>{},onError=()=>{},now=()=>performance.now(),wallNow=()=>Date.now(),setTimer=(fn,ms)=>setTimeout(fn,ms),clearTimer=id=>clearTimeout(id)}){
    Object.assign(this,{rpc,read,writeMany,erase,onFrame,onState,onError,now,wallNow,setTimer,clearTimer});
    this.keys=new MachineKeys();this.loaded=false;this.running=false;this.busy=false;this.saveBlocked=false;this.fault=false;
    this.generation=0;this.playGeneration=0;this.persisting=Promise.resolve();this.inFlight=null;this.remembered=true;this.ratio=0;
    this.awaySince=null;this.custodyEnabled=true;this.motionPending=false;
  }
  envelope(snapshot){return {schema:SCHEMA,identity:this.identity,saved_at:new Date(this.wallNow()).toISOString(),custody_at:new Date(this.awaySince??this.wallNow()).toISOString(),snapshot};}
  show(frame){this.frame=frame;this.onFrame(frame);if(frame.fault){this.fault=true;this.saveBlocked=true;this.running=false;this.keys.clear();this.onError(Error(String(frame.fault)));}this.onState();}
  start(){
    if(!this.loaded||this.busy||this.pausing||this.saveBlocked||this.fault||this.running)return;
    this.running=true;this.playGeneration++;this.startedAt=this.now();this.startedVirtual=this.frame.virtual_seconds;this.onState();void this.pump();
  }
  async pump(){
    if(!this.running||this.busy||this.inFlight)return;
    const generation=this.generation,play=this.playGeneration,start=this.now(),sent=this.keys.mask(),claimed=this.keys.capture(),before=this.frame.virtual_seconds;
    const motion=this.motionPending;this.motionPending=false;
    const operation=this.rpc('run',{instructions:BATCH,keys:sent,motion});this.inFlight=operation;
    try{
      const frame=await operation;if(generation!==this.generation)return;
      this.keys.advance(Math.max(0,frame.virtual_seconds-before),sent,claimed);
      if(play===this.playGeneration){const wall=(this.now()-this.startedAt)/1000;this.ratio=wall>0?Math.min(1,(frame.virtual_seconds-this.startedVirtual)/wall):0;}
      this.show(frame);
    }catch(error){if(generation===this.generation){this.running=false;this.fault=true;this.saveBlocked=true;this.keys.clear();this.onState();this.onError(error);}}
    finally{
      if(this.inFlight===operation)this.inFlight=null;
      if(generation===this.generation&&play===this.playGeneration&&this.running)this.timer=this.setTimer(()=>void this.pump(),Math.max(0,INTERVAL-(this.now()-start)));
    }
  }
  async pause(save=true){
    this.awaySince??=this.wallNow();this.motionPending=false;
    this.running=false;const play=++this.playGeneration;this.pausing=this.loaded;this.clearTimer(this.timer);this.keys.clear();this.onState();
    if(!this.loaded)return;
    const generation=this.generation,finishing=this.inFlight,released=this.rpc('keys',{keys:0});
    try{
      const results=await Promise.allSettled([finishing,released]);
      // The run path reports execution faults. Releasing keys and exporting its
      // diagnostic state must remain possible after that batch rejects.
      if(results[1].status==='rejected')throw results[1].reason;
      if(save&&generation===this.generation)await this.save();
    }
    finally{if(play===this.playGeneration){this.pausing=false;this.onState();}}
  }
  save({allowBusy=false}={}){
    const generation=this.generation,key=this.identity&&machineKey(this.identity);
    if(!this.loaded||this.saveBlocked||this.fault||this.frame?.native_link?.connected||this.busy&&!allowBusy)return Promise.resolve();
    const task=this.persisting.catch(()=>{}).then(async()=>{
      if(generation!==this.generation||this.saveBlocked)return;
      const snapshot=await this.rpc('snapshot');
      if(generation!==this.generation||this.saveBlocked)return;
      await this.writeMany([[key+':save',this.envelope(snapshot)]]);this.savedAt=new Date();this.onState();
    });
    this.persisting=task;return task;
  }
  async remember(enabled){
    this.remembered=!!enabled;
    if(!this.loaded){await this.writeMany([['gpce4:remember',this.remembered]]);return;}
    const key=machineKey(this.identity),entries=[['gpce4:remember',this.remembered],['gpce4:last',{key,identity:this.identity}]];
    if(this.remembered)entries.push([key+':inputs',this.inputs]);
    await this.writeMany(entries);if(!this.remembered)await this.erase([key+':inputs']);
  }
  async load(inputs){
    if(this.busy)throw Error('正在處理上一個檔案，請稍候。');
    if(!(inputs.bin instanceof ArrayBuffer)||inputs.bin.byteLength!==8388608)throw Error('PenC 韌體必須是 8 MiB（8,388,608 bytes）。');
    if(!(inputs.irom instanceof ArrayBuffer)||inputs.irom.byteLength!==98304)throw Error('PenC 內部 ROM 必須是 96 KiB（98,304 bytes）。');
    this.busy=true;this.onState();
    try{
      await this.pause(false);await this.save({allowBusy:true});await this.persisting;
      this.generation++;const frame=await this.rpc('load',{bin:inputs.bin,irom:inputs.irom});
      const key=machineKey(frame.identity);this.identity=frame.identity;this.inputs=inputs;this.loaded=true;this.saveBlocked=true;this.fault=false;
      this.show(frame);
      let saved=await this.read(key+':save'),migrating=false;
      if(!saved){
        const last=await this.read('gpce4:last');
        if(last?.key!==key&&last?.identity&&['firmware_sha256','irom_sha256'].every(k=>last.identity[k]===this.identity[k])&&compatibleCore(this.identity.core_sha256,last.identity.core_sha256)){
          if(last.key!==machineKey(last.identity))throw Error('舊快照索引不正確，原進度保留。');
          saved=await this.read(last.key+':save');migrating=!!saved;
        }
      }
      if(saved)this.show(await this.rpc('restore',{snapshot:checkBackup(saved,this.identity)}));
      if(this.fault)throw Error('核心已停止，保留既有快照。');
      const date=saved&&Date.parse(saved.custody_at||saved.saved_at);
      this.awaySince=Number.isFinite(date)?Math.min(date,this.wallNow()):this.wallNow();
      if(migrating)await this.writeMany([[key+':before-migration',saved],[key+':save',this.envelope(await this.rpc('snapshot'))]]);
      this.saveBlocked=false;await this.remember(this.remembered);this.recoveryBackup=null;
    }finally{this.busy=false;this.onState();}
  }
  async importBackup(backup){
    if(!this.loaded||this.busy)throw Error('請先載入對應的 BIN 與內部 ROM。');
    const snapshot=checkBackup(backup,this.identity),key=machineKey(this.identity);
    this.busy=true;this.generation++;this.onState();
    try{
      await this.pause(false);await this.persisting.catch(()=>{});
      const previous=this.envelope(await this.rpc('snapshot'));
      const old={fault:this.fault,saveBlocked:this.saveBlocked,frame:this.frame,awaySince:this.awaySince};let replaced=false;
      try{
        const frame=await this.rpc('restore',{snapshot});replaced=true;
        if(frame.fault)throw Error('快照核心已停止，既有存檔保留。');
        this.awaySince=this.wallNow();
        await this.writeMany([[key+':before-import',previous],[key+':save',this.envelope(await this.rpc('snapshot'))]]);
        this.fault=false;this.saveBlocked=false;this.show(frame);this.savedAt=new Date();this.recoveryBackup=null;
        this.awaySince=this.wallNow();
      }catch(error){
        if(replaced){
          try{await this.rpc('restore',{snapshot:previous.snapshot});}
          catch{this.fault=true;this.saveBlocked=true;this.recoveryBackup=previous;throw Error('匯入失敗且核心無法回復；原進度仍可用「匯出備份」保存。');}
        }
        this.fault=old.fault;this.saveBlocked=old.saveBlocked;this.frame=old.frame;this.awaySince=old.awaySince;this.onFrame(old.frame);throw error;
      }
    }finally{this.busy=false;this.onState();}
  }
  async exportBackup(){if(this.recoveryBackup)return this.recoveryBackup;await this.pause(false);if(!this.loaded)throw Error('請先載入機器。');return this.envelope(await this.rpc('snapshot'));}
  async disconnect(){
    await this.pause(false);const frame=await this.rpc('native-link-disconnect');
    this.show(frame);await this.save();return frame;
  }
  async resumeWithCustody(){
    if(this.busy||!this.loaded||this.fault||this.saveBlocked||this.running)return;
    const generation=this.generation,play=this.playGeneration;
    this.busy=true;this.settling=true;this.onState();
    try{
      let remaining=this.custodyEnabled&&!this.frame?.native_link?.connected?Math.min(31536000,Math.max(0,Math.floor((this.wallNow()-(this.awaySince??this.wallNow()))/1000))):0;
      while(remaining){
        if(generation!==this.generation||play!==this.playGeneration)return;
        const frame=await this.rpc('custody',{seconds:remaining}),result=frame.custody;
        if(generation!==this.generation)return;
        if(!result||!Number.isInteger(result.remaining_seconds)||result.remaining_seconds<0||result.remaining_seconds>remaining)throw Error('離線結算回應不正確；已暫停以保留進度。');
        this.custodyResult=result;this.show(frame);
        if(result.blocked_reason){remaining=0;break;}
        if(result.remaining_seconds===remaining)throw Error('離線結算尚未推進；請重新整理後再試。');
        remaining=result.remaining_seconds;this.awaySince=this.wallNow()-remaining*1000;
        await this.save({allowBusy:true});
        if(play!==this.playGeneration)return;
        if(remaining)await new Promise(resolve=>this.setTimer(resolve,0));
      }
      this.awaySince=null;
      await this.save({allowBusy:true});
    }finally{this.busy=false;this.settling=false;this.onState();}
    if(generation===this.generation&&play===this.playGeneration)this.start();
  }
}

function attachUI(){
  const $=id=>document.getElementById(id),buttons=[...document.querySelectorAll('.game-key')],view=new PixelView($('screen'));
  let worker,booting,nextId=0,starting=true,selectedBin,selectedROM,readingFiles=false,phoneMotion,linkRoom;
  const sound=new SoundPlayer($('sound-enable'),$('sound-status'),null,{preview:$('sound-preview')});
  function resetSound(){sound.stop();sound.lastEvent=null;$('sound-preview').disabled=true;}
  const pending=new Map();
  const status=(message,error=false)=>{$('status').textContent=message;$('status').parentElement.classList.toggle('error',error);document.body.classList.toggle('has-error',error);$('menu-open').title=error?message:'開啟選單';};
  const report=error=>status(String(error.message||error).trim().split('\n').at(-1),true);
  function rpc(op,fields={}){return new Promise((resolve,reject)=>{const id=++nextId;pending.set(id,{resolve,reject});try{worker.postMessage({id,op,...fields});}catch(error){pending.delete(id);reject(error);}});}
  async function ensureCore(){
    if(booting)return booting;
    worker=new Worker('./machine-worker.js',{type:'module'});
    worker.onmessage=({data})=>{if(data.kind==='progress'){status(data.text);return;}const waiting=pending.get(data.id);if(!waiting)return;pending.delete(data.id);data.ok?waiting.resolve(data.result):waiting.reject(Error(data.error||'核心回應失敗。'));};
    worker.onerror=error=>{for(const waiting of pending.values())waiting.reject(Error(error.message||'核心中斷。'));pending.clear();session.running=false;session.fault=true;session.saveBlocked=true;session.clearTimer(session.timer);session.keys.clear();controls();report(Error('整機核心中斷；既有快照保留。請重新整理後再試。'));};
    booting=rpc('boot').catch(error=>{worker.terminate();worker=null;booting=null;throw error;});return booting;
  }
  const session=new MachineSession({rpc,read,writeMany,erase,onState:controls,onError:report,onFrame:frame=>{
    view.update(frame);$('empty-screen').hidden=true;$('clock').textContent=frame.clock||'--:--:--';
    $('clock').setAttribute('aria-label','虛擬機累計時間 '+frame.clock);
    $('perf').textContent=Number.isFinite(frame.worker_ms)?Math.round(frame.worker_ms)+' ms / 批':'本機執行';
    $('speed').textContent=session.running?(session.ratio.toFixed(2)+'× 實際速度'):'已暫停';
    $('technical').textContent=`PC ${Number(frame.pc).toString(16).toUpperCase()} · ${Number(frame.steps).toLocaleString()} 條指令 · ${Number(frame.virtual_seconds).toFixed(2)} 虛擬秒${frame.sleeping?' · CPU 休眠':''}`;
    sound.setNativeSettings(frame.native_settings);if(session.running)sound.play(frame.audio||[]);
    phoneMotion?.setSupported(frame.motion_supported);linkRoom?.update(frame.native_link);
    $('native-settings-status').textContent=frame.native_settings?.supported?'音量跟隨遊戲內設定。':'此 BIN 的聲音介面尚未驗證。';

  }});
  phoneMotion=new PhoneMotion($('motion-enable'),$('motion-status'),()=>session.running&&!session.busy&&!document.hidden&&session.frame?.motion_ready,()=>{session.motionPending=true;});
  linkRoom=new LinkRoom({rpc:(op,fields)=>op==='native-link-disconnect'?session.disconnect():rpc(op,fields),prepare:async()=>{if(!session.loaded)throw Error('請先載入遊戲。');await session.pause();},resume:()=>void start(),display:frame=>{if(frame.rgba)session.show(frame);else if(frame.native_link&&session.frame){session.frame.native_link=frame.native_link;controls();}},onError:report,pairBase:new URL('./machine.html',location.href).href});
  $('relay-status').textContent=relayEndpoint?'掃描任一方 QR，回到遊戲選擇 BATTLE 或 JOGRES。':relayUnavailable;
  $('custody-enabled').onchange=()=>{session.custodyEnabled=$('custody-enabled').checked;void writeMany([['gpce4:custody',session.custodyEnabled]]).catch(report);};
  function controls(){
    const busy=starting||readingFiles||session.busy||session.pausing,canPlay=session.loaded&&!session.fault&&!session.saveBlocked;
    $('play').disabled=busy||!canPlay;$('play').textContent=session.running?'Ⅱ 暫停':'▶ 開始';
    for(const button of buttons){button.disabled=busy||!canPlay||!session.running;button.classList.toggle('pressed',session.running&&!!(session.keys.mask()&KEY_BITS[button.dataset.key]));}
    for(const id of ['save','export','import','flash-export'])$(id).disabled=busy||!session.loaded;
    $('save').disabled=busy||!canPlay||!!session.frame?.native_link?.connected;$('remember').disabled=busy;
    $('load').disabled=busy||!selectedBin||!selectedROM;
    for(const id of ['bin-file','irom-file'])$(id).disabled=busy;
    $('screen-action').hidden=session.running;$('screen-action').disabled=busy;
    $('screen-action').textContent=busy?'正在準備…':canPlay?'▶ 繼續':session.loaded?'開啟選單查看狀態':'＋ 載入本機檔案';
    $('live-state').textContent=session.fault?'核心已停止':session.saveBlocked&&session.loaded?'快照待處理':session.running?'執行中':'暫停中';
    $('save-state').textContent=session.saveBlocked&&session.loaded?'原快照保留':session.savedAt?'已保存 '+session.savedAt.toLocaleTimeString():'尚未保存';
    if(session.identity)$('identity').textContent='BIN '+session.identity.firmware_sha256.slice(0,12)+' · ROM '+session.identity.irom_sha256.slice(0,12)+' · 核心 '+session.identity.core_sha256.slice(0,12);
    $('link-open').disabled=busy||!canPlay||!session.frame?.native_link?.supported;
    const result=session.custodyResult;
    $('custody-status').textContent=session.settling?'正在結算離線成長…':result?.blocked_reason?'這次離開期間保持暫停；目前畫面或角色狀態不適用託管。':result?'已完成離線成長結算。':session.frame?.custody_supported?'R23 託管可用；在寵物主畫面離開時生效。':'目前 BIN 不支援託管，離開期間保持暫停。';
    if(!session.running){sound.stop();phoneMotion?.reset();}
  }
  function clearKeys(){session.keys.clear();controls();if(session.loaded)void rpc('keys',{keys:0}).catch(report);}
  function openMenu(){void session.pause().catch(report);if(session.loaded&&!session.saveBlocked&&!session.fault)status('已暫停，按「開始」繼續。');if(!$('menu-dialog').open)$('menu-dialog').showModal();}
  async function start(){
    if(document.hidden)return;void sound.activateFromGesture();void phoneMotion.activateFromGesture();
    try{await session.resumeWithCustody();if(session.running){$('menu-dialog').close();status(session.custodyResult?.blocked_reason?'此次離線保持暫停，已繼續遊戲。':'整機實驗執行中。');}}catch(error){report(error);}
  }
  new DisplayOrientation({root:document.body,icon:$('orientation-toggle'),menu:$('orientation-menu'),label:$('orientation-status'),onChange:geometry=>view.setLandscape(geometry.landscape),onToggle:clearKeys});
  $('menu-open').onclick=openMenu;$('menu-close').onclick=()=>$('menu-dialog').close();
  $('play').onclick=()=>session.running?void session.pause().catch(report):start();
  $('screen-action').onclick=()=>session.loaded&&!session.saveBlocked&&!session.fault?start():openMenu();
  for(const [id,kind] of [['bin-file','bin'],['irom-file','irom']])$(id).onchange=event=>{
    const file=event.target.files[0];if(kind==='bin')selectedBin=file;else selectedROM=file;
    $(kind==='bin'?'bin-name':'irom-name').textContent=file?file.name+' · '+file.size.toLocaleString()+' bytes':'尚未選取';controls();
  };
  $('load').onclick=async()=>{
    readingFiles=true;controls();status('正在讀取本機檔案與啟動整機核心…');
    try{
      if(linkRoom.session||linkRoom.cleanupNeeded)await linkRoom.end();resetSound();
      if(selectedBin.size!==8388608||selectedROM.size!==98304)throw Error('請選取 8 MiB PenC 韌體與 96 KiB PenC 內部 ROM。');
      const [bin,irom]=await Promise.all([selectedBin.arrayBuffer(),selectedROM.arrayBuffer(),ensureCore()]);
      session.remembered=$('remember').checked;
      await session.load({bin,irom,binName:selectedBin.name,iromName:selectedROM.name});
      status('已載入整機，按「開始」執行並結算可託管的離開時間。');
      void linkRoom.followInvite();
    }catch(error){report(error);}finally{readingFiles=false;controls();}
  };
  $('remember').onchange=()=>session.remember($('remember').checked).then(()=>status($('remember').checked?'已記住本機檔案，下次自動載入為暫停。':'已移除這組記住的檔案；快照保留，下次請重選相同檔案。')).catch(report);
  $('save').onclick=()=>session.save().then(()=>status('已將整機進度保存在這個瀏覽器。')).catch(report);
  function download(blob,name){const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);}
  const datedName=()=>new Date().toISOString().replace(/[:.]/g,'-');
  $('export').onclick=async()=>{try{if(linkRoom.session||linkRoom.cleanupNeeded)await linkRoom.end();const backup=await session.exportBackup();download(new Blob([JSON.stringify(backup)],{type:'application/json'}),'PenC-GPCE4-'+datedName()+'.json');status('已提出快照下載；請確認檔案已保存。');}catch(error){report(error);}};
  $('flash-export').onclick=async()=>{try{await session.pause();const result=await rpc('flash');download(new Blob([result.bin],{type:'application/octet-stream'}),'PenC-GPCE4-flash-'+datedName()+'.bin');status('已提出目前 Flash BIN 下載。這是實驗核心輸出，尚未驗證實體機寫回。');}catch(error){report(error);}};
  $('import').onclick=()=>$('save-file').click();
  $('save-file').onchange=async event=>{const file=event.target.files[0];if(!file)return;try{if(linkRoom.session||linkRoom.cleanupNeeded)await linkRoom.end();resetSound();await session.pause(false);if(file.size>40000000)throw Error('快照過大，請選取整機實驗匯出的 JSON。');await session.importBackup(JSON.parse(await file.text()));status('快照已載入並保存，按「開始」繼續。匯入前進度另存於本機。');}catch(error){report(error);}finally{event.target.value='';}};
  function acceptsInput(){return session.running&&!session.busy&&!document.hidden&&!$('menu-dialog').open;}
  for(const button of buttons){
    button.onpointerdown=event=>{if(!acceptsInput())return;event.preventDefault();button.setPointerCapture?.(event.pointerId);session.keys.press('pointer:'+event.pointerId,button.dataset.key);controls();};
    const release=event=>{session.keys.release('pointer:'+event.pointerId);controls();};
    button.onpointerup=button.onpointercancel=button.onlostpointercapture=release;button.oncontextmenu=event=>event.preventDefault();
  }
  window.addEventListener('keydown',event=>{const key=event.key.toUpperCase();if(!KEY_BITS[key]||event.ctrlKey||event.metaKey||event.altKey||!acceptsInput())return;event.preventDefault();session.keys.press('keyboard:'+event.code,key);controls();});
  window.addEventListener('keyup',event=>{session.keys.release('keyboard:'+event.code);controls();});
  window.addEventListener('blur',clearKeys);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)void (async()=>{await session.pause(false);if(linkRoom.session||linkRoom.cleanupNeeded)await linkRoom.end();await session.save();})().catch(report);});
  window.addEventListener('pagehide',()=>void session.pause().catch(report));
  window.addEventListener('pageshow',()=>{if(!starting)void session.pause(false).catch(report);});
  setInterval(()=>{if(session.running)void session.save().catch(report);},15000);
  controls();
  (async()=>{
    try{
      session.custodyEnabled=(await read('gpce4:custody'))!==false;$('custody-enabled').checked=session.custodyEnabled;
      const preference=await read('gpce4:remember');session.remembered=preference!==false;$('remember').checked=session.remembered;
      const last=await read('gpce4:last');if(!last||!session.remembered)return;
      if(last.key!==machineKey(last.identity))throw Error('上次的整機記錄無法辨識；請重新選取檔案。');
      const inputs=await read(last.key+':inputs');if(!inputs){status('找到整機快照；重新選取相同 BIN 與內部 ROM 即可恢復。');return;}
      status('正在從這台裝置載入整機與快照…');const boot=await ensureCore();validateRememberedCore(boot,last.identity);await session.load(inputs);
      $('bin-name').textContent=inputs.binName;$('irom-name').textContent=inputs.iromName;
      status('已恢復上次的整機。按「繼續」開始，支援的主畫面會結算離線成長。');void linkRoom.followInvite();
    }catch(error){report(error);if(!$('menu-dialog').open)$('menu-dialog').showModal();}
    finally{starting=false;controls();}
  })();
}
if(typeof document!=='undefined'&&document.getElementById('machine-app'))attachUI();
