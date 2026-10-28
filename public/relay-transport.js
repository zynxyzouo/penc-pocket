// SPDX-License-Identifier: GPL-3.0-or-later
// Free native packet relay, 2026-10-28. See MODIFICATIONS.md.
const HEX=/^[0-9a-f]{64}$/, CODE=/^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{8}$/;
const MAX_BODY=8192, MAX_PACKETS=512;
const integer=(n,min,max)=>Number.isSafeInteger(n)&&n>=min&&n<=max;
const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const matches=(pattern,value)=>typeof value==='string'&&pattern.test(value);
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
const fault=(message,status=409)=>Object.assign(new Error(message),{status,terminal:true});
const protocol=()=>fault('配對服務回傳的通訊資料不一致，連線已停止。');
const network=message=>Object.assign(new Error(message),{retryable:true,terminal:false});
function profile(value){
 if(!object(value)||!matches(HEX,value.firmware)||!matches(HEX,value.transport)||Object.keys(value).length!==2)throw protocol();
 return {firmware:value.firmware,transport:value.transport};
}
function packets(value){
 if(!Array.isArray(value)||value.length>16)throw protocol();
 return value.map(p=>{
  if(!object(p)||Object.keys(p).length!==2||!integer(p.seq,1,MAX_PACKETS)||!Array.isArray(p.words)||p.words.length!==8||p.words.some(w=>!integer(w,0,65535)))throw protocol();
  return {seq:p.seq,words:p.words.slice()};
 });
}

export class RelayTransport {
 constructor({endpoint,fetchImpl=globalThis.fetch,now=Date.now}){
  Object.assign(this,{endpoint,fetchImpl,now});this.generation=0;this.pending=new Set();this.closed=false;this.state=null;
 }
 close(){
  this.closed=true;this.generation++;
  for(const controller of this.pending)controller.abort(fault('連線已中斷。'));
  this.pending.clear();
 }
 async request(action,fields={},session){
  const leaving=action==='leave';let generation=this.generation;
  try{
   if(!this.endpoint)throw fault('此版本尚未設定配對服務。',503);
   if(!object(session)||!matches(HEX,session.token)||!['create','pair','exchange','leave'].includes(action))throw protocol();
   if(action==='create'){
    if(session.code!==null)throw protocol();
    const p=profile(fields.profile);
    if(!this.state||this.closed&&session.token!==this.state.token){
     this.generation++;generation=this.generation;this.closed=false;
     this.state={token:session.token,profile:p,code:null,slot:null,expires:null,connected:false,peerProfile:null,sent:new Map(),incoming:new Map(),received:0,accepted:0};
    }else if(this.state.token!==session.token||!same(this.state.profile,p))throw protocol();
   }else if(!matches(CODE,session.code))throw protocol();
   if(!leaving&&(this.closed||session.token!==this.state?.token))throw fault('連線已中斷，請重新開啟配對。');
   const state=this.state;
   if(!leaving&&action!=='create'&&session.code!==state.code)throw protocol();
   const body={action,token:session.token,code:session.code};
   if(action==='create'||action==='pair'){
    body.profile=profile(fields.profile);
    if(!same(body.profile,state.profile))throw protocol();
    if(action==='pair'){
     if(!matches(CODE,fields.peer)||fields.peer===session.code)throw protocol();
     body.peer=fields.peer;
    }
   }
   if(action==='exchange'){
    body.received=fields.received??0;body.packets=packets(fields.packets??[]);
    if(!integer(body.received,state.received,state.incoming.size)||!state.connected&&(body.received||body.packets.length))throw protocol();
    const sent=new Map(state.sent);
    for(let i=0;i<body.packets.length;i++){
     const p=body.packets[i],previous=sent.get(p.seq);
     if(i&&p.seq!==body.packets[i-1].seq+1||previous&&!same(previous,p)||!previous&&p.seq!==sent.size+1)throw protocol();
     sent.set(p.seq,p);
    }
    // The server may receive a request whose HTTP reply is lost. Retain its
    // exact packet values and cursor so a retry cannot rewrite that history.
    state.sent=sent;state.received=body.received;
   }
   const value=await this.post(body,leaving);
   if(!leaving&&(generation!==this.generation||this.closed))throw fault('連線已中斷。');
   const result=this.validate(value,body,leaving?null:state);
   if(!leaving){
    Object.assign(state,{code:result.code,slot:result.slot,expires:result.expires,connected:result.connected,peerProfile:result.peerProfile?{...result.peerProfile}:null,accepted:result.accepted});
    for(const p of result.packets)state.incoming.set(p.seq,{seq:p.seq,words:p.words.slice()});
    if(result.closed)this.closed=true;
   }
   return result;
  }catch(e){
   if(!leaving&&e.terminal&&generation===this.generation)this.close();
   throw e;
  }
 }
 validate(value,body,state){
  if(!object(value)||!matches(CODE,value.code)||!integer(value.slot,0,1)||!integer(value.expires,1,Number.MAX_SAFE_INTEGER)||typeof value.connected!=='boolean'||typeof value.closed!=='boolean'||!integer(value.accepted,0,MAX_PACKETS))throw protocol();
  const incoming=packets(value.packets),peer=value.peerProfile===null?null:profile(value.peerProfile);
  if(value.closed&&(value.connected||incoming.length)||value.connected&&!peer||!value.connected&&!value.closed&&(peer||value.slot!==0||incoming.length||value.accepted))throw protocol();
  if(state){
   // The server enforces TTL. Phone wall clocks may differ or change while
   // playing; only the server's expiry identity/stability is authoritative.
   if(state.expires!==null&&value.expires>state.expires)throw protocol();
   if(peer&&(peer.transport!==state.profile.transport||state.peerProfile&&!same(peer,state.peerProfile)))throw protocol();
   if(state.connected){
    if(value.code!==state.code||value.slot!==state.slot||value.expires!==state.expires||!value.connected&&!value.closed)throw protocol();
   }else if(state.code){
    if(value.connected){
     if(value.code>state.code||value.slot!==(value.code===state.code?0:1))throw protocol();
     if(body.action==='pair'&&value.code!==[state.code,body.peer].sort()[0])throw protocol();
    }else if(value.code!==state.code||value.slot!==state.slot)throw protocol();
   }
   if(value.accepted<state.accepted||value.accepted>state.sent.size)throw protocol();
   for(let i=0;i<incoming.length;i++){
    const p=incoming[i],previous=state.incoming.get(p.seq);
    if(p.seq!==(body.received??0)+i+1||previous&&!same(previous,p))throw protocol();
   }
  }else if(!value.closed)throw protocol();
  return {code:value.code,slot:value.slot,expires:value.expires,connected:value.connected,closed:value.closed,peerProfile:peer,accepted:value.accepted,packets:incoming};
 }
 async post(body,leaving){
  const controller=new AbortController();this.pending.add(controller);
  let reader,timer,onAbort;
  const aborted=new Promise((resolve,reject)=>{
   onAbort=()=>{if(reader)void reader.cancel().catch(()=>{});reject(controller.signal.reason||fault('連線已中斷。'));};
   controller.signal.addEventListener('abort',onAbort,{once:true});
  });
  timer=setTimeout(()=>controller.abort(network('配對服務回應逾時。')),8000);
  try{
   const text=JSON.stringify(body);
   if(new TextEncoder().encode(text).length>MAX_BODY)throw protocol();
   const work=(async()=>{
    const response=await this.fetchImpl.call(globalThis,this.endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:text,credentials:'omit',cache:'no-store',signal:controller.signal,...(leaving?{keepalive:true}:{})});
    if(controller.signal.aborted)throw controller.signal.reason;
    if(Number(response.headers.get('content-length'))>MAX_BODY)throw protocol();
    if(!response.body)throw protocol();
    reader=response.body.getReader();let size=0,content='';const decoder=new TextDecoder('utf-8',{fatal:true});
    for(;;){
     const {done,value}=await reader.read();if(done)break;
     size+=value.byteLength;if(size>MAX_BODY){void reader.cancel().catch(()=>{});throw protocol();}
     try{content+=decoder.decode(value,{stream:true});}catch{throw protocol();}
    }
    try{content+=decoder.decode();}catch{throw protocol();}
    if(!response.ok){
     const quota=response.status===429||response.status===503||/\b1027\b/.test(content);
     if(quota)throw fault('免費連線服務額度已用盡或暫停，連線已停止。'+(/\b1027\b/.test(content)?' (1027)':''),response.status);
     let detail;try{detail=JSON.parse(content).error;}catch{}
     throw fault(typeof detail==='string'&&detail.length<=256?detail:'配對服務拒絕連線，請重新開啟配對。',response.status);
    }
    try{return JSON.parse(content);}catch{throw protocol();}
   })();
   return await Promise.race([work,aborted]);
  }catch(e){
   if(e.terminal||e.retryable)throw e;
   throw network('網路暫時無法連到配對服務。');
  }finally{
   clearTimeout(timer);controller.signal.removeEventListener('abort',onAbort);this.pending.delete(controller);
  }
 }
}
