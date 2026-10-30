// SPDX-License-Identifier: GPL-3.0-or-later
import {Gpce4Machine,PREVIOUS_CORES} from './gpce4-engine.js';
let machine,serial=Promise.resolve();
self.onmessage=({data})=>{serial=serial.then(async()=>{
 try{
  const started=performance.now();let result;
  if(data.op==='boot'){
   const configResponse=await fetch('./machine-config.json',{cache:'no-cache'});
   if(!configResponse.ok)throw Error('無法下載整機設定。');
   const config=await configResponse.json(),response=await fetch('./core/'+config.file,{cache:'no-cache'});
   if(!response.ok)throw Error('無法下載整機核心。');
   const bytes=Uint8Array.from(atob((await response.text()).trim()),c=>c.charCodeAt(0));
   machine=await Gpce4Machine.create(bytes,config);result={core_sha256:machine.core,compatible_cores:PREVIOUS_CORES};
  }else{
   if(!machine)throw Error('整機核心尚未就緒。');
   switch(data.op){
    case 'load':result=await machine.load(new Uint8Array(data.bin),new Uint8Array(data.irom));break;
    case 'run':result=machine.run(data.instructions,data.keys,!!data.motion);break;
    case 'keys':machine.keys(data.keys);if(!data.keys)machine.motion?.clear();result={};break;
    case 'native-link-info':result={native_link:machine.link.metadata()};break;
    case 'native-link-connect':result=machine.connect(data.session,data.slot);break;
    case 'native-link-receive':result=machine.receive(data.session,data.packets,data.accepted);break;
    case 'native-link-disconnect':result=machine.disconnect();break;
    case 'custody':result=await machine.catchUp(data.seconds);break;
    case 'present':result=machine.present();break;
    case 'snapshot':result=await machine.snapshot();break;
    case 'restore':result=await machine.restore(data.snapshot);break;
    case 'flash':result={bin:machine.flash()};break;
    default:throw Error('未知的整機操作。');
   }
  }
  if(result.family)result.worker_ms=performance.now()-started;
  postMessage({id:data.id,ok:true,result},result.bin?[result.bin]:[]);
 }catch(error){postMessage({id:data.id,ok:false,error:String(error.message||error)});}
});};
