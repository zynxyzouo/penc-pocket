// SPDX-License-Identifier: GPL-3.0-or-later
// A host shake supplies one bounded native sensor latch. The admitted firmware
// consumer owns counters and results; physical accelerometer/IRQ timing is not
// emulated. Live pending input is excluded from the machine snapshot.
const FLASH_SIZE=8388608;
const SENSOR_SIGNATURES=[
 [0x201bcc,0x201c42,'60601d930236234396d672a6423a5552cbe2f93c3b752ebfb8e0652fed23b172'],
 [0x201cda,0x201d1e,'d0875163bdc59798c9ca51e0d09999a0a9ae2374784b5989404078363ad3c22d'],
 [0x201d1e,0x201d49,'5f71630944839ed811e61b2df0c9bda18108e3ad4f2ee8204cb4d6c992de565d'],
];
const sha256=async bytes=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');

export class Gpce4Motion{
 static async create(bin,getExports){
  if(typeof getExports!=='function')throw Error('Motion requires the current machine exports');
  const regions=bin instanceof Uint8Array&&bin.length===FLASH_SIZE
   ?SENSOR_SIGNATURES.map(([start,end,digest])=>({offset:2*(start-0x200000),bytes:bin.slice(2*(start-0x200000),2*(end-0x200000)),digest})):[];
  const matches=await Promise.all(regions.map(async region=>await sha256(region.bytes)===region.digest));
  return new Gpce4Motion(matches.length===3&&matches.every(Boolean)?regions:[],getExports);
 }
 constructor(regions,getExports){this.regions=regions;this.getExports=getExports;this.supported=regions.length===3;this.enabled=false;}
 admitted(e){
  if(!this.supported)return false;
  const bytes=new Uint8Array(e.memory.buffer,e.gp_flash_ptr(),FLASH_SIZE);
  return this.regions.every(region=>region.bytes.every((value,i)=>bytes[region.offset+i]===value));
 }
 enable(){
  const e=this.getExports();this.enabled=this.admitted(e);
  // Also clears pending input after load/restore; never carry an old gesture
  // into another machine instance or replay the snapshot's sensor RAM.
  e.gp_motion_enable(this.enabled?1:0);return this.enabled;
 }
 metadata(){
  const e=this.getExports(),supported=this.enabled&&this.admitted(e);
  if(!supported)return {motion_supported:false,motion_ready:false,motion_count:0};
  const ram=new Uint16Array(e.memory.buffer,e.gp_ram_ptr(),0x3000);
  return {motion_supported:true,motion_ready:ram[0xca0]===2,motion_count:ram[0xd41]};
 }
 pulse(requested){
  if(typeof requested!=='boolean')throw Error('Motion input must be a single boolean pulse');
  if(!requested||!this.metadata().motion_ready)return false;
  this.getExports().gp_motion_pulse();return true;
 }
 clear(){this.getExports().gp_motion_clear();}
}
