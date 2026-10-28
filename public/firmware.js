// SPDX-License-Identifier: GPL-3.0-or-later
// Public hosting adaptation, 2026-10-28. See MODIFICATIONS.md.
// Profiles are data. Keep their original UTF-8 text: snapshots pin those bytes.
export function decodeProfile(bytes){
  if(bytes.byteLength>262144)throw new Error('設定檔過大，請選取隨 BIN 附上的 .emulator.json。');
  return new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes);
}
function address(value){
  if(typeof value==='string'&&/^(0x)?[0-9a-f]+$/i.test(value))return parseInt(value.replace(/^0x/i,''),16);
  return Number.isSafeInteger(value)?value:NaN;
}
export function validateProfile(text,expectedHash){
  if(typeof text!=='string'||new TextEncoder().encode(text).length>262144)throw new Error('設定檔格式或大小不正確。');
  let p;try{p=JSON.parse(text.replace(/^\uFEFF/,''));}catch{throw new Error('設定檔不是有效的 JSON。');}
  const hash=p?.sha256??p?.firmware_sha256;
  if(!/^[0-9a-f]{64}$/.test(hash||''))throw new Error('請選取 .emulator.json 模擬設定，不能使用存檔或其他 JSON。');
  if(expectedHash&&hash!==expectedHash)throw new Error('BIN 與設定檔的 SHA256 不相符，請選同一版本附帶的 .emulator.json。');
  if(!p.entries||Array.isArray(p.entries)||typeof p.entries!=='object')throw new Error('設定檔缺少原生入口。');
  for(const item of Object.values(p.entries)){
    const at=address(typeof item==='object'&&item!==null?item.address:item);
    if(!Number.isSafeInteger(at)||at<0x200000||at>=0x600000)throw new Error('設定檔包含不支援的原生入口。');
  }
  if(p.family==='dmc'){
    if(p.adapter!=='dmc-linedog-v41'||hash!=='3457140c5f07211abdd756462693c67c824c4c45c26a7ca91e4323df476701dc'||address(p.entries.input_home)!==0x2005f3||address(p.entries.input_scan)!==0x200c1a||address(p.entries.timers)!==0x20923c)throw new Error('這份彩機設定尚未受支援。');
  }else if(p.family==='penc-stock'){
    if(p.adapter!=='penc-stock-test4'||hash!=='a21e573ba40741603b8b4068817c789c625196ab5e53ddb188b1f57c63c612a1'||address(p.entries.input_home)!==0x200545||address(p.entries.input_scan)!==0x200d48||address(p.entries.timers)!==0x210918)throw new Error('這份原版超代彩設定尚未受支援。');
  }else if((p.family&&p.family!=='penc')||address(p.entries.input_home?.address??p.entries.input_home)!==0x2005e9||!p.r8_time)throw new Error('此設定的架構尚未受網頁核心支援。');
  if(p.initial_ram!==undefined){
    if(!p.initial_ram||typeof p.initial_ram!=='object'||Array.isArray(p.initial_ram))throw new Error('初始記憶體設定無效。');
    for(const [key,value] of Object.entries(p.initial_ram)){
      const at=address(key),word=address(value);
      if(!Number.isSafeInteger(at)||!(at>=0&&at<0x2000||at===0x3000||at===0x30e9)||!Number.isSafeInteger(word)||word<0||word>65535)throw new Error('初始記憶體超出支援範圍。');
    }
  }
  return hash;
}
export async function firmwareHash(buffer){
  if(buffer.byteLength!==8388608)throw new Error('目前支援已驗證的 8 MiB PenC／DMC BIN，檔案未載入。');
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256',buffer))].map(x=>x.toString(16).padStart(2,'0')).join('');
}

let builtinCatalog;
async function catalog(){
  if(!builtinCatalog)builtinCatalog=(async()=>{
    const response=await fetch('./profiles/catalog.json',{cache:'no-cache'});
    if(!response.ok)throw new Error('無法讀取內建版本目錄，請稍後重試。');
    const value=await response.json();
    if(value?.version!==1||!value.profiles||typeof value.profiles!=='object'||Array.isArray(value.profiles))throw new Error('內建版本目錄格式不正確。');
    return value.profiles;
  })().catch(error=>{builtinCatalog=null;throw error;});
  return builtinCatalog;
}

export async function builtinProfile(hash){
  if(!/^[0-9a-f]{64}$/.test(hash||''))return null;
  const profiles=await catalog();
  if(!Object.hasOwn(profiles,hash))return null;
  const entry=profiles[hash];
  if(!entry||typeof entry!=='object'||
     !/^[a-z0-9][a-z0-9_-]*\.json$/.test(entry.file||'')||
     !/^[0-9a-f]{64}$/.test(entry.profile_sha256||'')||
     !Number.isSafeInteger(entry.profile_bytes)||entry.profile_bytes<1||entry.profile_bytes>262144||
     typeof entry.name!=='string'||!entry.name||entry.name.length>160)throw new Error('內建版本目錄資料不正確。');
  const response=await fetch('./profiles/'+entry.file,{cache:'no-cache'});
  if(!response.ok)throw new Error('無法取得這份 BIN 的內建設定，請稍後重試。');
  const bytes=await response.arrayBuffer();
  if(bytes.byteLength!==entry.profile_bytes)throw new Error('內建設定長度不符，請重新整理後再試。');
  const actual=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
  if(actual!==entry.profile_sha256)throw new Error('內建設定 SHA256 不符，請重新整理後再試。');
  const text=decodeProfile(bytes);
  validateProfile(text,hash);
  // Return the exact original UTF-8 text, never JSON.stringify(parsedProfile).
  return {text,name:entry.name};
}
