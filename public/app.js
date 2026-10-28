// SPDX-License-Identifier: GPL-3.0-or-later
// Public hosting adaptation, 2026-10-28. See MODIFICATIONS.md.
import {read, writeMany, erase} from './storage.js';
import {PixelView} from './view.js?v=stock-family-14';
import {DisplayOrientation} from './orientation.js?v=1';
import {DeviceUI} from './ui-modes.js?v=2';
import {builtinProfile,validateProfile,firmwareHash} from './firmware.js?v=stock-family-14';
import {FramePacer} from './pacing.js';
import {PhoneMotion} from './motion.js?v=default-on-11';
import {SoundPlayer,SoundTimeline} from './sound.js?v=native-settings-12';
import {LinkRoom} from './native-link.js?v=qr-2';
import {relayAvailable,relayUnavailable} from './hosting.js';
import {upgradeSnapshotProfile} from './profile-compat.js';
const $=id=>document.getElementById(id);
const pixelView=new PixelView($('screen')), buttons=[...document.querySelectorAll('.game-key')];
const deviceUI=new DeviceUI();
function updateViewButtons(){for(const mode of ['focus','standard'])$('view-'+mode).setAttribute('aria-pressed',String(pixelView.mode===mode));}
for(const mode of ['focus','standard'])$('view-'+mode).onclick=()=>{pixelView.setMode(mode);updateViewButtons();};
updateViewButtons();
let worker,booting,id=0,pending=new Map(),loaded=false,running=false,fatal=false,playGeneration=0;
let hash='',fileName='',binBuffer,profileText,timer,lastClock=0,fraction=0,inFrame=false;
let held=new Set(),keyboard=new Set(),pointers=new Map(),events=[],longTimer,keyGeneration=0;
let lastSave=0,savePromise=null,persistence=Promise.resolve(),generation=0,saveBlocked=false;
let profileName='',motionReady=false,motionPending=false,linkRoom;
let machineFamily='penc',machineCapabilities={};
let catching=false,awayAutoRetry=true,autoLoading=false;
new DisplayOrientation({root:document.body,icon:$('orientation-toggle'),menu:$('orientation-menu'),label:$('orientation-status'),onChange:g=>pixelView.setLandscape(g.landscape),onToggle:()=>{clearKeys();if(loaded&&worker)rpc('release').catch(fail);}});
const pacer=new FramePacer(64);
const soundTimeline=new SoundTimeline();
const phoneMotion=new PhoneMotion($('motion-enable'),$('motion-status'),()=>loaded&&running&&!fatal&&!document.hidden&&motionReady,()=>{motionPending=true;});
const sound=new SoundPlayer($('sound-enable'),$('sound-status'),null,{preview:$('sound-preview')});
linkRoom=new LinkRoom({rpc,resume:start,display,onError:fail,prepare:async()=>{if(!loaded||fatal)throw new Error('請先載入相容的 BIN。');if(machineCapabilities.link===false)throw new Error('這個機型的連線介面尚未接上。');await pause();await saveNow(false);}});
$('relay-status').textContent=relayAvailable?'已設定配對服務；兩邊使用同一網站，掃描對方 QR 後回遊戲選 BATTLE 或 JOGRES。':relayUnavailable;
window.addEventListener('hashchange',()=>{if(loaded&&!fatal&&machineCapabilities.link!==false)void linkRoom.followInvite();});
function status(text,error=false){$('status').textContent=text;$('status').parentElement.classList.toggle('error',error);document.body.classList.toggle('has-error',error);$('menu-open').title=error?text:'開啟 Menu';}
function controls(){
  if(autoLoading)$('bin-file').disabled=true;
  for(const e of [...buttons,$('step')])e.disabled=autoLoading||!loaded||fatal||catching;
  $('play').disabled=autoLoading||!loaded||fatal;
  for(const e of [$('save'),$('export'),$('import'),$('reset'),$('restore-game')])e.disabled=autoLoading||!loaded;
  $('remember').disabled=autoLoading||loaded&&saveBlocked;
  $('link-open').disabled=autoLoading||!relayAvailable||!loaded||fatal||machineCapabilities.link===false;
  $('reset').disabled=autoLoading||!loaded||machineCapabilities.new_game===false;
  $('sound-enable').disabled=machineCapabilities.audio===false;
  $('motion-enable').disabled=machineCapabilities.motion===false;
  if(machineCapabilities.audio===false)$('sound-preview').disabled=true;
  $('play').textContent=catching?'Ⅱ 暫停結算':running?'Ⅱ 待機':'▶ 開始';
  $('live-state').textContent=fatal?'流程已停止':loaded?(catching?'補算離開時間':running?'執行中':'待機中'):'等待載入';
  $('clock-status').textContent=loaded?(running?'GAME TIME':'PAUSED'):'GAME TIME';
  deviceUI.setRunning(loaded,running,fatal);
  $('screen-action').hidden=running;
  $('screen-action').disabled=autoLoading;
  $('screen-action').textContent=autoLoading?'正在載入上次的 BIN…':fatal?'開啟 Menu 查看狀態':catching?'正在補算…點一下待機':loaded?'▶ 繼續':'＋ 載入 BIN';
}
function openMenu(){if(!$('menu-dialog').open){pause();if(loaded&&!fatal)status(machineCapabilities.away===false?'已待機，此機型目前在關閉期間暫停養成。':'已待機。回來按繼續，會補算離開時間。');$('menu-dialog').showModal();}}
$('menu-open').onclick=openMenu;
$('menu-close').onclick=()=>$('menu-dialog').close();
$('screen-action').onclick=()=>catching?pause():loaded&&!fatal?start({fromGesture:true}):openMenu();
function rpc(op,fields={}){if(['load','restore','reset','new-game'].includes(op))sound.clearPreview();return new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});worker.postMessage({id:n,op,...fields});});}
async function ensureCore(){
  if(booting)return booting;
  worker=new Worker('./worker.js?v=stock-family-14',{type:'module'});
  worker.onmessage=({data})=>{if(data.kind==='progress')return status(data.text);const p=pending.get(data.id);if(!p)return;pending.delete(data.id);data.ok?p.resolve(data.result):p.reject(new Error(data.error));};
  worker.onerror=e=>{for(const p of pending.values())p.reject(new Error(e.message||'瀏覽器核心中斷。'));pending.clear();running=false;clearTimeout(timer);fatal=true;controls();status('瀏覽器核心中斷，請重新整理後再試。',true);};
  booting=rpc('boot').catch(e=>{worker.terminate();booting=null;worker=null;throw e;});
  return booting;
}
function display(r,activeFrame=false){
  if(r.family){machineFamily=r.family;machineCapabilities=r.capabilities||{};controls();$('family-status').textContent=r.family==='dmc'?'DMC 彩機・線條小狗 v4.1。已接上原生畫面、ABC 與本機快照；聲音、連線、離開補算仍待移植。':r.family==='penc-stock'?'原版超代彩 TEST4・原生開機、畫面、ABC、音效、晃動與本機快照；網路連線及離開補算尚未接上。':'PenC 超代彩・原生畫面、ABC、聲音、晃動、連線與離開補算。';}
  linkRoom?.update(r.native_link);
  sound.setNativeSettings(r.native_settings);
  const setting=r.native_settings;
  const light=setting?.supported&&setting.brightness_valid?[.45,.6,.75,.9,1][setting.brightness_level-1]:1;
  $('screen').style.filter=`brightness(${light})`;$('clock-screen').style.filter=`brightness(${light})`;
  if(setting)$('native-settings-status').textContent=setting.supported===false?'此機型的網頁音量／亮度輸出尚未接上。':`遊戲音量：${setting.volume_valid?['靜音','小','大'][setting.volume_level]:'尚未設定'} · 亮度：${setting.brightness_valid?setting.brightness_level+' / 5':'尚未設定'}${setting.brightness_preview?'（預覽）':''}`;
  if(r.continuity){$('away-status').textContent=r.continuity.supported===false?'此機型目前在網頁開啟時走時；待機與關閉期間暫停養成。':r.continuity.clock_rollback?'裝置時間往回變動，保留原時間基準。':r.continuity.pending_seconds>1?`尚待補算 ${formatDuration(r.continuity.pending_seconds)}。回主畫面後繼續結算。`:r.continuity.started?'離開後持續計時，回來時補算養成。':'完成設定與孵化後，開始記錄離開時間。';}
  if(activeFrame&&running)sound.play(r.sound_events);
  pixelView.update(r);
  motionReady=!!r.motion_ready;phoneMotion.setSupported(r.motion_supported);
  $('clock-status').textContent=running&&motionReady?(phoneMotion.enabled?'晃動 '+r.motion_count+' 次':'晃動未啟用'):(running?'GAME TIME':'PAUSED');
  if(running&&r.native_link?.waiting)$('clock-status').textContent='等待對方連線';
  if(r.display_sleeping)$('clock-status').textContent='螢幕休眠 · 按 ABC 喚醒';
  deviceUI.record(r,{name:fileName,hash,bytes:binBuffer?.byteLength||0},activeFrame);
  $('empty-screen').hidden=true;$('clock').textContent=r.clock;$('speed').textContent=r.time_rate+'× TIME';
  if(r.family!=='penc'){$('clock-screen').hidden=true;$('clock').classList.remove('visually-hidden');}
  if(r.clock_rgba){
    $('clock-screen').getContext('2d').putImageData(pixelView.decode(r.clock_rgba,96,48),0,0);
    $('clock-screen').hidden=false;$('clock').classList.add('visually-hidden');
  }
  $('clock-screen').setAttribute('aria-label','遊戲時間 '+r.clock);
  if(r.frame_ms!==undefined)$('perf').textContent=Math.round(r.frame_ms)+' ms / '+(r.completed_frames||1)+' 次更新';
  $('technical').textContent=`SHA256 ${hash} · 累計 ${r.steps.toLocaleString()} 條原生指令 · state ${r.state}/${r.substate} · 主機畫面解碼，非實機截圖。`;
}
function clearKeys(){held.clear();keyboard.clear();pointers.clear();events=[];clearTimeout(longTimer);keyGeneration++;buttons.forEach(b=>b.classList.remove('pressed'));deviceUI.setKeys([]);}
function pause(save=true){
  if(autoLoading)save=false; // Do not persist a partly restored startup frame.
  running=false;catching=false;playGeneration++;sound.stop();clearTimeout(timer);fraction=0;lastClock=0;motionPending=false;phoneMotion.reset();clearKeys();controls();
  if(loaded&&worker){const g=generation;return rpc('release').then(s=>{if(save&&g===generation)return persist(s);}).catch(storageError);}
  return Promise.resolve();
}
function fail(e){pause(false);fatal=true;controls();status('遇到尚未支援的流程，已停止。可匯出快照或重設測試。 '+String(e.message).trim().split('\n').at(-1).slice(0,190),true);}
function activateInputsFromGesture(){if(machineCapabilities.audio!==false)void sound.activateFromGesture();if(machineCapabilities.motion!==false)void phoneMotion.activateFromGesture();}
function formatDuration(seconds){return seconds<60?seconds+' 秒':seconds<3600?Math.floor(seconds/60)+' 分 '+seconds%60+' 秒':Math.floor(seconds/3600)+' 小時 '+Math.floor(seconds%3600/60)+' 分';}
async function start({fromGesture=false}={}){
  if(autoLoading||!loaded||fatal||document.hidden)return;
  if(fromGesture)activateInputsFromGesture();else sound.resume();
  if(catching||running)return;
  $('menu-dialog').close();catching=true;const token=++playGeneration,g=generation;controls();
  let blocked='';
  try{
    for(;;){
      const r=await rpc('catch-up');
      if(token!==playGeneration||g!==generation||document.hidden)return;
      display(r);const remaining=r.continuity?.pending_seconds||0;
      blocked=r.catch_up?.blocked_reason||'';
      if(blocked||remaining===0)break;
      const text='正在補算離開時間，尚餘 '+formatDuration(remaining)+'；點螢幕可先待機。';
      status(text);$('screen-action').textContent='補算中 · 尚餘 '+formatDuration(remaining)+' · 點此待機';
      if(Date.now()-lastSave>5000)await saveNow(false);
      await new Promise(resolve=>setTimeout(resolve,0));
      if(token!==playGeneration||g!==generation||document.hidden)return;
    }
    if(token!==playGeneration||g!==generation)return;
    catching=false;running=true;awayAutoRetry=!blocked;lastClock=performance.now();soundTimeline.reset(lastClock);pacer.reset(lastClock);fraction=0;motionPending=false;phoneMotion.reset();controls();
    status(blocked?'離開時間已保留，這個流程暫時無法補算；完成操作回主畫面後可再試。':machineFamily==='dmc'?'彩機執行中。A 選擇、B 確認、C 返回；開機選 CONTINUE 保留 BIN 原有進度。':'執行中。A 選擇、B 確認、C 返回；主畫面長按 C 開啟遊戲設定。');
    await saveNow(false);if(token===playGeneration&&g===generation&&running)schedule(0);
  }catch(e){if(token===playGeneration&&g===generation){catching=false;fail(e);}}
}
function schedule(ms=16){clearTimeout(timer);timer=setTimeout(pump,ms);}
async function pump(){
  if(inFrame||catching||!loaded||fatal||(!running&&!events.length))return;
  const started=performance.now(),frames=running?pacer.claim(started,events.length>0):1;
  if(!frames){schedule(pacer.delay(started));return;}
  inFrame=true;const g=generation,playToken=playGeneration,event=events.shift();let seconds=0;
  if(running){const elapsed=(started-lastClock)/1000;lastClock=started;if(elapsed<0||(elapsed>5&&machineCapabilities.away!==false)){inFrame=false;const resumedToken=playGeneration+1;await pause();if(resumedToken===playGeneration&&g===generation&&!document.hidden)void start();return;}fraction+=elapsed;seconds=Math.min(5,Math.floor(fraction));fraction-=seconds;}
  const audioElapsed=soundTimeline.claim(started,running);
  try{
    const keys=event?.keys||[...held],motion=motionPending&&phoneMotion.enabled&&running;
    motionPending=false;deviceUI.setKeys(keys);
    const r=await rpc('frame',{keys,seconds,long:!!event?.long,frames,motion,audio_elapsed_ms:audioElapsed,audio_speed:sound.playbackRate});
    if(g!==generation)return;
    const activeFrame=running&&playToken===playGeneration;
    if(activeFrame)soundTimeline.acknowledge(r.sound_clock_started,performance.now());
    display(r,activeFrame);
    if(r.native_link_notice){
      await pause();
      if(g!==generation)return;
      if(!$('menu-dialog').open)$('menu-dialog').showModal();
      status(r.native_link_notice);
      return;
    }
    if(machineFamily==='penc'&&r.state===0x26){pause();status('原機進入休眠；此試作尚未模擬喚醒，可重設測試。');}
    if(activeFrame&&awayAutoRetry&&r.continuity?.safe&&r.continuity.pending_seconds>5&&!r.native_link?.connected&&!held.size){const resumedToken=playGeneration+1;await pause();if(resumedToken===playGeneration&&g===generation&&!document.hidden)void start();return;}
    if(Date.now()-lastSave>5000)saveNow(false).catch(storageError);
  }
  catch(e){if(g===generation)fail(e);}
  finally{inFrame=false;if(g===generation&&!fatal&&(running||events.length))schedule(events.length?0:pacer.delay(performance.now()));}
}
function keyEvent(){
  if(autoLoading||!loaded||fatal||catching)return;awayAutoRetry=true;held=new Set([...keyboard,...pointers.values()]);buttons.forEach(b=>b.classList.toggle('pressed',held.has(b.dataset.key)));
  deviceUI.setKeys(held);
  events.push({keys:[...held]});if(events.length>32){pause();status('輸入過於密集，已放開按鍵並暫停。');return;}
  const token=++keyGeneration,keys=[...held];clearTimeout(longTimer);
  if(keys.length)longTimer=setTimeout(()=>{if(token!==keyGeneration||fatal||document.hidden)return;events.push({keys,long:true});schedule(0);},1000);
  schedule(0);
}
function storageError(e){$('save-state').textContent='未能保存';status('瀏覽器保存未完成，請使用「匯出備份」。 '+e.message,true);}
function persist(snapshot){
  if(saveBlocked)return Promise.reject(new Error('保留未能讀取的原快照，請先匯出舊備份或明確重設測試。'));
  const h=hash,name=fileName;
  persistence=persistence.catch(()=>{}).then(async()=>{const previous=await read('save:'+h),now=new Date().toISOString(),s={...snapshot,saved_at:now,filename:name};
    const entries=[['save:'+h,s],['last',{hash:h,name,saved_at:now}]];if(previous)entries.push(['previous:'+h,previous]);await writeMany(entries);
    if(hash===h){lastSave=Date.now();$('save-state').textContent='已存 '+new Date(now).toLocaleTimeString('zh-TW',{hour12:false});}return s;});
  return persistence;
}
async function saveNow(announce=true){
  if(!loaded)return;if(savePromise)return savePromise;
  const g=generation;savePromise=rpc('snapshot').then(s=>g===generation?persist(s):null).then(s=>{if(announce)status('已保存到這台裝置的瀏覽器，建議另匯出一份備份。');return s;}).finally(()=>savePromise=null);return savePromise;
}
async function rememberSession(){
  const records=[['profile:'+hash,{text:profileText,name:profileName}],['last',{hash,name:fileName}]];
  if($('remember').checked)records.push(['bin:'+hash,{buffer:binBuffer,name:fileName,profileText,profileName}]);
  await writeMany(records);
}
function confirmAction(title,text){const d=$('confirm-dialog');$('confirm-title').textContent=title;$('confirm-text').textContent=text;d.returnValue='cancel';return new Promise(resolve=>{d.addEventListener('close',()=>resolve(d.returnValue==='ok'),{once:true});d.showModal();});}
async function loadFile(buffer,name,suppliedProfile=null){
  const newHash=await firmwareHash(buffer);
  const [stored,remembered,snapshot]=await Promise.all([read('profile:'+newHash),read('bin:'+newHash),read('save:'+newHash)]);
  const candidates=[stored,remembered?.profileText?{text:remembered.profileText,name:remembered.profileName}:null,suppliedProfile].filter(Boolean);
  let matching=null;
  if(snapshot?.profile_sha256){
    for(const candidate of candidates){
      const bytes=new TextEncoder().encode(candidate.text),digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
      if(digest===snapshot.profile_sha256){matching=candidate;break;}
    }
  }else matching=candidates[0]||null;
  matching||=await builtinProfile(newHash);
  if(!matching)throw new Error('尚未收錄這份 BIN 的架構設定，原進度不變。需更新網站的版本識別表，不必另外選 JSON。');
  validateProfile(matching.text,newHash);
  await linkRoom.end();await pause(!saveBlocked);if(loaded&&!saveBlocked)await saveNow(false);
  const saved=await read('save:'+newHash);
  generation++;loaded=false;fatal=false;controls();
  $('file-label').classList.add('busy');$('bin-file').disabled=true;
  try{
    await ensureCore();status('正在核對 BIN、設定與執行第一幀…');
    const r=await rpc('load',{bin:buffer,profile:matching.text});hash=newHash;fileName=name;binBuffer=buffer;profileText=matching.text;profileName=matching.name;loaded=true;fatal=false;display(r);
    let restored=false,restoreError='';
    if(saved){try{display(await rpc('restore',{snapshot:await upgradeSnapshotProfile(saved,profileText)}));restored=true;}catch(e){restoreError='舊快照未能讀取，未覆寫。 '+String(e.message).trim().split('\n').at(-1);}}
    else if(r.capabilities?.new_game!==false)display(await rpc('new-game'));
    $('file-info').textContent=fileName+' · 8 MiB · 設定已核對：'+profileName;$('identity').textContent='SHA256 '+hash.slice(0,12)+'…';$('resume').hidden=true;
    // A failed restore must retain both the old snapshot and its exact profile.
    if(!restoreError)await rememberSession().catch(storageError);
    saveBlocked=!!restoreError;controls();if(restoreError){fatal=true;controls();status(restoreError,true);}else{status(restored?(machineCapabilities.away===false?'已恢復這份 BIN 的快照，按「開始」繼續。':'已恢復上次進度，按「開始」補算離開時間並繼續。舊版快照從這次開始記錄。'):machineFamily==='dmc'?'已讀取 BIN 內原有進度。按開始，於原生開機選單選 CONTINUE 繼續養成。':'已進入原生開機畫面。按 B 開始；時間設定用 A 調時、B 調分、C 確認，再選蛋孵化。');await saveNow(false).catch(storageError);}
    navigator.storage?.persist?.().then(granted=>{if(granted)$('storage-note').textContent='已取得持續儲存；仍請定期匯出。手動清除網站資料會刪除快照。快照不能直接寫回實體機。';}).catch(()=>{});
  }finally{$('file-label').classList.remove('busy');$('bin-file').disabled=false;controls();}
  if(!fatal&&machineCapabilities.link!==false)await linkRoom.followInvite();
}
$('bin-file').onchange=async e=>{const f=e.target.files[0];if(!f)return;try{
  if(f.size!==8388608)throw new Error('目前支援已驗證的 8 MiB PenC／DMC BIN。');await loadFile(await f.arrayBuffer(),f.name);
}catch(err){status(err.message,true);}finally{e.target.value='';}};
$('play').onclick=()=>running||catching?(pause(),status(machineCapabilities.away===false?'已待機；此機型待機與關閉期間暫停養成。':'已待機。離開時間會保留，回來時補算。')):start({fromGesture:true});
$('step').onclick=async()=>{if(running)await pause();events.push({keys:[]});schedule(0);};
buttons.forEach(b=>{
  b.addEventListener('pointerdown',e=>{if(b.disabled)return;e.preventDefault();b.setPointerCapture(e.pointerId);pointers.set(e.pointerId,b.dataset.key);keyEvent();});
  const release=e=>{if(!pointers.has(e.pointerId))return;if(e.type==='pointerup')activateInputsFromGesture();e.preventDefault();pointers.delete(e.pointerId);keyEvent();};
  for(const type of ['pointerup','pointercancel','lostpointercapture'])b.addEventListener(type,release);
  b.addEventListener('contextmenu',e=>e.preventDefault());
  b.addEventListener('click',e=>{if(e.detail===0&&!b.disabled){activateInputsFromGesture();events.push({keys:[b.dataset.key]},{keys:[]});schedule(0);}});
});
window.addEventListener('keydown',e=>{if(autoLoading||e.repeat||e.ctrlKey||e.metaKey||e.altKey||['INPUT','TEXTAREA'].includes(e.target.tagName)||$('confirm-dialog').open||$('menu-dialog').open||$('link-dialog').open)return;const k=e.key.toUpperCase();if(!['A','B','C'].includes(k)||!loaded||fatal)return;activateInputsFromGesture();e.preventDefault();keyboard.add(k);keyEvent();});
window.addEventListener('keyup',e=>{if(keyboard.delete(e.key.toUpperCase())){e.preventDefault();keyEvent();}});
$('save').onclick=()=>saveNow().catch(storageError);
$('export').onclick=async()=>{try{
  const s=saveBlocked?await read('save:'+hash):await rpc('snapshot'),now=new Date().toISOString(),data={...s,saved_at:now,filename:fileName};
  const url=URL.createObjectURL(new Blob([JSON.stringify(data)],{type:'application/json'})),a=document.createElement('a');
  a.href=url;a.download='PenC_'+hash.slice(0,8)+'_'+now.replace(/[:.]/g,'-')+'.penc-save.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
  status('已提出下載備份，請在 Safari 下載項目或「檔案」確認已保存。');
}catch(e){status('匯出失敗：'+e.message,true);}};
$('import').onclick=()=>$('save-file').click();
$('save-file').onchange=async e=>{const f=e.target.files[0];if(!f)return;await pause();try{
  if(f.size>2000000)throw new Error('快照過大，請選取本網頁匯出的 JSON。');const s=JSON.parse(await f.text());
  if(s.firmware_sha256!==hash)throw new Error('快照與目前 BIN 不相符，未更動目前測試。');
  if(!await confirmAction('載入這份快照？','驗證成功後才套用快照，目前進度會先保存在本機。'))return;
  await linkRoom.end();await writeMany([['before-import:'+hash,await rpc('snapshot')]]);display(await rpc('restore',{snapshot:await upgradeSnapshotProfile(s,profileText)}));fatal=false;saveBlocked=false;controls();await rememberSession();await saveNow(false);status('快照已載入，按「開始」繼續。');
}catch(err){status('快照未載入：'+String(err.message).trim().split('\n').at(-1),true);}finally{e.target.value='';}};
$('reset').onclick=async()=>{await pause();if(!await confirmAction('從蛋開始新的遊戲？','將進入原生開機、設定時間與選蛋。現在的進度會先備份，可用「還原新遊戲前進度」取回；建議另匯出保存。'))return;try{
  await linkRoom.end();await writeMany([['before-new-game:'+hash,saveBlocked?await read('save:'+hash):await rpc('snapshot')]]);display(await rpc('new-game'));fatal=false;saveBlocked=false;controls();await rememberSession();await saveNow(false);status('新遊戲已準備。按 B 開始；設定時間用 A 調時、B 調分、C 確認，再選蛋。');
}catch(e){fail(e);}};
$('restore-game').onclick=async()=>{await pause();try{const backup=await read('before-new-game:'+hash);if(!backup)throw new Error('沒有新遊戲前的備份。');if(!await confirmAction('還原新遊戲前的進度？','目前進度也會保存在匯入前備份。'))return;await linkRoom.end();await writeMany([['before-import:'+hash,await rpc('snapshot')]]);display(await rpc('restore',{snapshot:backup}));fatal=false;saveBlocked=false;controls();await saveNow(false);status('已還原新遊戲前進度，按開始繼續。');}catch(e){status(e.message,true);}};
$('remember').onchange=async()=>{if(!loaded)return;try{if($('remember').checked)await writeMany([['bin:'+hash,{buffer:binBuffer,name:fileName,profileText,profileName}]]);else await erase(['bin:'+hash]);status($('remember').checked?'已在這台裝置記住 BIN 與設定。':'已移除瀏覽器保存的 BIN；設定與快照仍保留，下次需重新選取相同 BIN。');}catch(e){storageError(e);}};
$('resume').onclick=async()=>{$('resume').disabled=true;try{const last=await read('last'),record=last&&await read('bin:'+last.hash);if(!record)throw new Error('請重新選取相同的 BIN，原有快照會自動讀取。');await loadFile(record.buffer,record.name,record.profileText?{text:record.profileText,name:record.profileName||'已保存設定'}:null);}catch(e){status(e.message,true);}finally{$('resume').disabled=false;}};
document.addEventListener('visibilitychange',()=>{if(document.hidden&&loaded){pause();status(machineCapabilities.away===false?'進度已保存；關閉期間暫停養成。':'已保存待機；回來按「開始」，補算離開時間。');}});
window.addEventListener('pagehide',()=>pause());
window.addEventListener('blur',()=>{if(held.size){clearKeys();if(loaded)rpc('release').catch(()=>{});}});
window.addEventListener('pageshow',()=>{if(loaded){running=false;controls();status('已暫停，按「開始」繼續。');}});
// Reuse the normal validated restore path; the first tap still starts gameplay
// and requests audio/motion access. Never fetch or distribute a firmware file.
autoLoading=true;controls();$('bin-file').disabled=true;$('resume').disabled=true;
read('last').then(async last=>{
  if(!last)return;
  const record=await read('bin:'+last.hash);
  if(!record){$('file-info').textContent='找到本機快照，重新選取相同 BIN 即可恢復。';return;}
  $('resume').hidden=false;$('resume').textContent='重試載入 '+record.name+' →';
  status('正在從這台裝置載入上次的 BIN 與存檔…');
  await loadFile(record.buffer,record.name,record.profileText?{text:record.profileText,name:record.profileName||'已保存設定'}:null);
  if(fatal&&!$('menu-dialog').open)$('menu-dialog').showModal();
}).catch(e=>{
  status('自動載入未完成，請重試或重新選取相同 BIN。 '+String(e.message).trim().split('\n').at(-1),true);
  if(!$('menu-dialog').open)$('menu-dialog').showModal();
}).finally(()=>{autoLoading=false;$('bin-file').disabled=false;$('resume').disabled=false;controls();});
