/* SPDX-License-Identifier: GPL-3.0-or-later
 * C port of gpce4_machine/unsp.py. Instruction semantics follow MAME 0.289
 * src/devices/cpu/unsp (GPL-2.0-or-later; Segher Boessenkool, Ryan Holtz,
 * David Haywood) and the audited PenC CPU. Internal ROM executes normally;
 * there are no host firmware entry points or synthesized ROM results.
 */
#include "gpce4.h"

enum { N=0x200, Z=0x100, S=0x80, C=0x40,
       INE=0x10, IRQ_EN=0x20, FIQ_EN=0x40, RETI=0x9A98 };
GpCpu cpu;

uint32_t gp_cpu_pc(void) { return ((cpu.r[6]&63u)<<16)|cpu.r[7]; }
static void setpc(uint32_t value) {
 cpu.r[7]=value&65535u;
 cpu.r[6]=(cpu.r[6]&0xFFC0u)|((value>>16)&63u);
}
static uint32_t sb(void) { return (cpu.fr>>7)&15u; }
static void set_sb(uint32_t value) { cpu.fr=(cpu.fr&~0x780u)|((value&15u)<<7); }
static void unsupported(void) { if(!cpu.fault) cpu.fault=1; }
static uint32_t fetch(void) {
 uint32_t address=gp_cpu_pc();
 setpc(address+1u);
 return gp_read(address);
}
static int push(uint32_t value,uint32_t reg) {
 if(reg>=8){unsupported();return 0;}
 gp_write(cpu.r[reg],value&65535u);
 if(cpu.fault) return 0;
 cpu.r[reg]=(cpu.r[reg]-1u)&65535u;
 return 1;
}
static int pop(uint32_t reg,uint32_t *value) {
 if(reg>=8){unsupported();return 0;}
 cpu.r[reg]=(cpu.r[reg]+1u)&65535u;
 *value=gp_read(cpu.r[reg]);
 return !cpu.fault;
}
static void call(uint32_t target) {
 if(!push(cpu.r[7],0)||!push(cpu.r[6],0))return;
 setpc(target);
}
static uint32_t flags_nz(uint32_t sr,uint32_t value) {
 return (sr&~(N|Z))|((value&0x8000u)?N:0)|((value&65535u)?0:Z);
}
static uint32_t flags_nzsc(uint32_t sr,uint32_t value,uint32_t left,uint32_t right) {
 return (sr&~(N|Z|S|C))|
        ((((value>>16)&1u)!=(((left^right)>>15)&1u))?S:0)|
        ((value&0x8000u)?N:0)|((value&65535u)?0:Z)|((value&0x10000u)?C:0);
}
static void set_bank(uint32_t on) {
 if(!!(cpu.fr&0x2000u)!=!!on){
  for(unsigned i=0;i<4;i++){
   uint32_t t=cpu.r[i+1];cpu.r[i+1]=cpu.secbank[i];cpu.secbank[i]=t;
  }
  cpu.fr^=0x2000u;
 }
}
static void set_fr(uint32_t value) { set_bank(value&0x2000u);cpu.fr=value&0x7FFFu; }

void gp_cpu_reset(void) {
 cpu=(GpCpu){0};
 cpu.fr=0x0808;
 cpu.r[7]=gp_read(0x4017);
 if(cpu.fault)cpu.fault_pc=0x4017;
}
void gp_cpu_irq(uint32_t line,uint32_t level) {
 /* Peripheral lines are 0..8. Guard the public API before the C shift. */
 if(line>=32)return;
 if(level)cpu.sirq|=1u<<line;else cpu.sirq&=~(1u<<line);
}
static int check_irqs(void) {
 if(!cpu.sirq)return 0;
 uint32_t line=0;
 while(!(cpu.sirq&(1u<<line)))line++;
 if(line==0){
  if(!(cpu.fr&FIQ_EN)||cpu.fiq_active)return 0;
  cpu.fiq_active=1;
  if(!push(cpu.r[7],0)||!push(cpu.r[6],0))return -1;
  uint32_t vector=gp_read(0x4016);
  if(cpu.fault)return -1;
  cpu.r[7]=vector;cpu.r[6]=0;
 }else{
  uint32_t irq=line-1,ine=cpu.fr&INE;
  if((!ine&&cpu.irq_active)||(cpu.fr&15u)<=irq||!(cpu.fr&IRQ_EN))return 0;
  cpu.irq_active=1;
  if(!push(cpu.r[7],0)||!push(cpu.r[6],0))return -1;
  if(ine){
   if(!push(cpu.fr,0))return -1;
   cpu.fr=(cpu.fr&~15u)|irq;
  }
  uint32_t vector=gp_read(0x4018+irq);
  if(cpu.fault)return -1;
  cpu.r[7]=vector;cpu.r[6]=0;
 }
 cpu.sleeping=0;
 return 1;
}
static void reti(void) {
 uint32_t value;
 /* Deliberately mirrors the supplied reference: FR is restored directly,
  * without set_fr's mask or bank swap; INE controls the FR pop even for FIQ. */
 if(cpu.fr&INE){if(!pop(0,&value))return;cpu.fr=value;}
 if(!pop(0,&value))return;
 cpu.r[6]=value;
 if(!pop(0,&value))return;
 cpu.r[7]=value;
 if(cpu.fiq_active)cpu.fiq_active=0;
 else if(cpu.irq_active)cpu.irq_active=0;
}
static int branch(unsigned condition,uint32_t s) {
 switch(condition){
 case 0:return !(s&C);case 1:return !!(s&C);
 case 2:return !(s&S);case 3:return !!(s&S);
 case 4:return !(s&Z);case 5:return !!(s&Z);
 case 6:return !(s&N);case 7:return !!(s&N);
 case 8:return (s&Z)||!(s&C);case 9:return !(s&Z)&&(s&C);
 case 10:return (s&Z)||(s&S);case 11:return !(s&Z)&&!(s&S);
 case 12:return !!(s&N)==!!(s&S);case 13:return !!(s&N)!=!!(s&S);
 default:return 1;
 }
}
static uint32_t bitop(unsigned kind,uint32_t value,unsigned bit) {
 uint32_t mask=1u<<bit;
 cpu.r[6]=(cpu.r[6]&~Z)|((value&mask)?0:Z);
 switch(kind){case 1:return value|mask;case 2:return value&~mask;case 3:return value^mask;default:return value;}
}
/* Arithmetic shift with unsigned operands; defined for every n in 0..31. */
static uint32_t asr32(uint32_t value,unsigned n) {
 if(!n)return value;
 return (value>>n)|((value&0x80000000u)?(0xFFFFFFFFu<<(32u-n)):0);
}
static void op_exxx(uint32_t op,unsigned dst,unsigned src) {
 uint32_t *r=cpu.r,kind=(op>>4)&3u;
 if((op&0xF1C8u)==0xE000u||(op&0xF1C0u)==0xE040u){
  unsigned bit=(op&0xF1C8u)==0xE000u?r[src]&15u:op&15u;
  uint32_t value=bitop(kind,r[dst],bit);r[dst]=value&65535u;return;
 }
 /* The reference also compares (op & F188) to E140, which is impossible.
  * E140 forms are already matched by the E100 comparison (bit 6 is ignored). */
 if((op&0xF180u)==0xE180u||(op&0xF188u)==0xE100u){
  unsigned ds_form=(op&0xF1C0u)==0xE1C0u||(op&0xF1C0u)==0xE140u;
  unsigned bit=(op&0xF180u)==0xE180u?op&15u:r[src]&15u;
  uint32_t address=(ds_form?(r[6]>>10)<<16:0)|r[dst];
  uint32_t orig=gp_read(address);if(cpu.fault)return;
  uint32_t value=bitop(kind,orig,bit);
  if(kind)gp_write(address,value&65535u);
  return;
 }
 if((op&0xF1F8u)==0xE008u){
  uint32_t value=r[dst]*r[src];r[3]=value&65535u;r[4]=value>>16;return;
 }
 if((op&0xF188u)==0xE108u){
  unsigned shift_kind=(op>>4)&7u,n=r[src]&31u;
  uint32_t v=r[dst],value;
  switch(shift_kind){
  case 0:r[dst]=asr32(v|((v&0x8000u)?0xFFFF0000u:0),n)&65535u;break;
  case 1:value=asr32(v<<16,n);r[3]|=value&65535u;r[4]=(value>>16)&65535u;break;
  case 2:r[dst]=(v<<n)&65535u;break;
  case 3:value=v<<n;r[3]=value&65535u;r[4]|=(value>>16)&65535u;break;
  case 4:r[dst]=v>>n;break;
  case 5:value=(v<<16)>>n;r[3]|=value&65535u;r[4]=(value>>16)&65535u;break;
  default:unsupported();break;
  }
  return;
 }
 unsupported();
}
static void op_fxxx(uint32_t op,unsigned dst,unsigned group,unsigned src) {
 uint32_t *r=cpu.r;
 if(group==0){
  if((op&0xFFC0u)==0xFE00u)r[6]=(r[6]&0x3FFu)|((op&63u)<<10);
  else if((op&0xF1F8u)==0xF020u)r[src]=r[6]>>10;
  else if((op&0xF1F8u)==0xF028u)r[6]=(r[6]&0x3FFu)|((r[src]&63u)<<10);
  else if((op&0xF1F8u)==0xF030u)r[src]=cpu.fr;
  else if((op&0xF1F8u)==0xF038u)set_fr(r[src]);
  else if((op&0xF1F8u)==0xF008u){
   uint32_t value=r[dst]*r[src];
   if(r[src]&0x8000u)value-=r[dst]<<16;
   r[3]=value&65535u;r[4]=value>>16;
  }else unsupported();
  return;
 }
 if(group==1){
  if((op&0xF3C0u)==0xF040u){
   uint32_t low=fetch();if(cpu.fault)return;
   call(((op&63u)<<16)|low);
  }else if((op&0xF3C0u)==0xF240u){
   uint32_t address=fetch();if(cpu.fault)return;
   address|=(op&0x0400u)?(r[6]>>10)<<16:0;
   unsigned kind=(op>>4)&3u;
   uint32_t orig=gp_read(address);if(cpu.fault)return;
   uint32_t value=bitop(kind,orig,op&15u);
   if(kind)gp_write(address,value&65535u);
  }else unsupported();
  return;
 }
 if(group==2&&(op&0xFFC0u)==0xFE80u){
  uint32_t low=fetch();if(!cpu.fault)setpc(((op&63u)<<16)|low);return;
 }
 if(group==3&&(op&0xFFC0u)==0xFEC0u){setpc(((r[4]&63u)<<16)|r[3]);return;}
 if(group==4&&(op&0xF1F8u)==0xF108u){
  /* Both factors are in [-32768,32767], so their product fits int32_t. */
  int32_t a=(int32_t)r[dst]-((r[dst]&0x8000u)?65536:0);
  int32_t b=(int32_t)r[src]-((r[src]&0x8000u)?65536:0);
  uint32_t value=(uint32_t)(a*b);r[3]=value&65535u;r[4]=value>>16;return;
 }
 if(group==5){
  uint32_t low=op&63u;
  if(low<=3)cpu.fr=(cpu.fr&~(IRQ_EN|FIQ_EN))|((low&1u)?IRQ_EN:0)|((low&2u)?FIQ_EN:0);
  else if(low==8||low==9)cpu.fr=(cpu.fr&~IRQ_EN)|((low&1u)?IRQ_EN:0);
  else if(low==12||low==14)cpu.fr=(cpu.fr&~FIQ_EN)|((low&2u)?FIQ_EN:0);
  else if(low==4||low==5)cpu.fr=(cpu.fr&~0x800u)|((low==4)?0x800u:0);
  else if(low==6||low==7)cpu.fr=(cpu.fr&~0x1000u)|((low==7)?0x1000u:0);
  else if(low==13||low==15)cpu.fr=(cpu.fr&~INE)|((low==15)?INE:0);
  else if(low==10||low==11)set_bank(low==11);
  else if((low&0x27u)==0x25u){ /* NOP family. */ }
  else if((low&0x27u)==0x21u)call(((r[4]&63u)<<16)|r[3]);
  else if((low&0x27u)==0x24u){
   uint32_t value=r[4];unsigned bits=0;
   if(value&0x8000u)value=(~value)&65535u;
   while(value){bits++;value>>=1;}
   r[2]=15u-bits;
  }else unsupported();
  return;
 }
 unsupported();
}
static void adjust(unsigned src,uint32_t delta,unsigned ds_mode) {
 cpu.r[src]=(cpu.r[src]+delta)&65535u;
 if(ds_mode&&cpu.r[src]==(delta==1u?0u:65535u))
  cpu.r[6]=(cpu.r[6]+(delta==1u?0x400u:0xFFFFFC00u))&65535u;
}
static void execute(uint32_t op) {
 unsigned top=op>>12,dst=(op>>9)&7u,group=(op>>6)&7u,mode=(op>>3)&7u,src=op&7u;
 uint32_t *r=cpu.r;
 if(top<15&&dst==7&&group<2){
  if(branch(top,r[6]))setpc(group==0?gp_cpu_pc()+(op&63u):gp_cpu_pc()-(op&63u));
  return;
 }
 if(top==15){op_fxxx(op,dst,group,src);return;}
 if(top==14){op_exxx(op,dst,src);return;}
 if(group==2&&top==13){
  /* Reject invalid decoded ranges before any bus write. Python's negative
   * list indices accidentally alias registers for these malformed opcodes. */
  if(mode>dst+1u){unsupported();return;}
  for(unsigned i=0;i<mode;i++)if(!push(r[dst-i],src))return;
  return;
 }
 if(group==2&&top==9){
  if(op==RETI){reti();return;}
  if(dst+mode>7u){unsupported();return;}
  for(unsigned i=1;i<=mode;i++){
   uint32_t value;if(!pop(src,&value))return;r[dst+i]=value;
  }
  return;
 }
 uint32_t left=r[dst],address=0,right=0,result=0;
 int has_address=0;
 switch(group){
 case 0:address=(r[5]+(op&63u))&65535u;has_address=1;break;
 case 1:right=op&63u;break;
 case 3:{
  unsigned ds_mode=mode&4u;
  if((mode&3u)==3u)adjust(src,1u,ds_mode);
  address=(ds_mode?(r[6]>>10)<<16:0)|r[src];has_address=1;
  if(top!=13){right=gp_read(address);if(cpu.fault)return;}
  if((mode&3u)==1u||(mode&3u)==2u)adjust(src,(mode&3u)==1u?0xFFFFFFFFu:1u,ds_mode);
  break;
 }
 case 4:
  if(mode==0)right=r[src];
  else if(mode==1){left=r[src];right=fetch();if(cpu.fault)return;}
  else if(mode==2||mode==3){
   address=fetch();if(cpu.fault)return;has_address=1;
   if(mode==3)right=left;
   left=r[src];
  }else{
   uint32_t v=(r[src]<<4)|sb();
   if(v&0x80000u)v|=0xF00000u;
   v>>=mode-3u;set_sb(v&15u);right=(v>>4)&65535u;
  }
  break;
 case 5:
  if(mode&4u){uint32_t v=((r[src]<<4)|sb())>>(mode-3u);set_sb(v&15u);right=(v>>4)&65535u;}
  else{uint32_t v=((sb()<<16)|r[src])<<(mode+1u);set_sb((v>>16)&15u);right=v&65535u;}
  break;
 case 6:{
  uint32_t v=(((sb()<<16)|r[src])<<4)|sb();
  if(mode&4u){v>>=mode-3u;set_sb(v&15u);}
  else{v<<=mode+1u;set_sb((v>>20)&15u);}
  right=(v>>4)&65535u;break;
 }
 case 7:address=op&63u;has_address=1;break;
 default:unsupported();return;
 }
 if(has_address&&top!=13&&group!=3&&!(group==4&&mode==3)){
  right=gp_read(address);if(cpu.fault)return;
 }
 if(top==13){if(!has_address)unsupported();else gp_write(address,left);return;}
 if(top<=4){
  uint32_t operand=top<=1?right:(~right)&65535u;
  uint32_t carry=(top==1||top==3)?!!(r[6]&C):(top==2||top==4);
  result=left+operand+carry;
  if(dst!=7)r[6]=flags_nzsc(r[6],result,left,operand);
  if(top==4)return;
 }else if(top==6||top==8||top==9||top==10||top==11||top==12){
  if(top==6)result=0u-right;
  else if(top==8)result=left^right;
  else if(top==9)result=right;
  else if(top==10)result=left|right;
  else result=left&right;
  if(dst!=7)r[6]=flags_nz(r[6],result);
  if(top==12)return;
 }else{unsupported();return;}
 if(group==4&&mode==3)gp_write(address,result&65535u);
 else r[dst]=result&65535u;
}
int gp_cpu_step(void) {
 if(cpu.fault)return -1;
 uint32_t pc=gp_cpu_pc(),op=0;
 if(cpu.sleeping){
  int taken=check_irqs();
  if(taken<0)goto fault;
  if(!taken)return 0;
 }
 pc=gp_cpu_pc();op=fetch();
 if(cpu.fault)goto fault;
 cpu.steps++;
 execute(op);
 if(cpu.fault)goto fault;
 if(op!=RETI&&cpu.sirq&&check_irqs()<0)goto fault;
 return 1;
fault:
 cpu.fault_pc=pc;cpu.fault_op=op;return -1;
}
