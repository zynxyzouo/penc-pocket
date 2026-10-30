/* SPDX-License-Identifier: GPL-3.0-or-later
 * PenC Pocket compiled execution engine, 2026-10-30.
 * New C implementation of the project's selected unSP contract. The reference
 * contract includes MAME-derived semantics; existing attribution still applies.
 * No MAME library or other emulator core is linked. Not a full hardware model.
 *
 * Every instruction is transactional: local registers + at most 8 staged RAM
 * writes. Unsupported instructions/peripherals yield BEFORE any visible effect
 * so the host can execute one reference instruction, including its exact error.
 */
#include <stdint.h>
#if defined(_WIN32)
#define API __declspec(dllexport)
#else
#define API __attribute__((visibility("default")))
#endif
#define WORDS 65536u
#define ROM_SIZE 0x800000u
#define STOP 0x3fffffu
static uint8_t image[ROM_SIZE], valid[WORDS], changed[WORDS];
static uint32_t ram[WORDS], dirty[WORDS], calls[WORDS], state[14];
static uint32_t image_size, adapters_enabled;
API uint32_t *state_ptr(void) { return state; }
API uint32_t *ram_ptr(void) { return ram; }
API uint32_t *dirty_ptr(void) { return dirty; }
API uint32_t *calls_ptr(void) { return calls; }
API uint8_t *rom_ptr(void) { return image; }
API uint8_t *valid_ptr(void) { return valid; }
API void clear_dirty(void) {
    for (uint32_t i=0;i<state[11];i++) changed[dirty[i]]=0;
    state[11]=0;
    state[13]=0;
}
API void reset(uint32_t size, uint32_t adapters) {
    image_size=size<=ROM_SIZE?size:0; adapters_enabled=adapters;
    for (uint32_t i=0;i<WORDS;i++) valid[i]=changed[i]=0;
    for (uint32_t i=0;i<14;i++) state[i]=0;
}
static uint32_t pc_of(const uint32_t *r) { return ((r[6]&63)<<16)|r[7]; }
static void pc_set(uint32_t *r,uint32_t v) { r[7]=v&65535;r[6]=(r[6]&0xffc0)|((v>>16)&63); }
static uint32_t word_at(uint32_t address, int *ok) {
    if(address<0x200000 || (uint64_t)(address-0x200000)*2+1>=image_size) { *ok=0;return 0; }
    uint32_t at=(address-0x200000)*2;return image[at]|((uint32_t)image[at+1]<<8);
}
static uint32_t read_at(uint32_t address,int *ok) {
    if(address>=0x200000 && address<0x600000)return word_at(address,ok);
    /* All peripheral accesses go to the host, even if a cached word exists. */
    if(address>=0x2000 || !valid[address]) { *ok=0;return 0; }
    return ram[address];
}
static int condition(uint32_t sr,uint32_t c) {
    int n=!!(sr&0x200),z=!!(sr&0x100),s=!!(sr&0x80),carry=!!(sr&0x40);
    switch(c) {
    case 0:return !carry;case 1:return carry;case 2:return !s;case 3:return s;
    case 4:return !z;case 5:return z;case 6:return !n;case 7:return n;
    case 8:return z||!carry;case 9:return !z&&carry;case 10:return z||s;
    case 11:return !z&&!s;case 12:return n==s;case 13:return n!=s;default:return 1;
    }
}
static uint32_t logic_flags(uint32_t sr,uint32_t v) {
    return (sr&~0x300u)|((v&0x8000)?0x200:0)|((v&65535)?0:0x100);
}
static uint32_t arithmetic_flags(uint32_t sr,uint32_t v,uint32_t a,uint32_t b) {
    return logic_flags(sr&~0xc0u,v)|((v&0x10000)?0x40:0)|
        (((v>>16&1)!=((a^b)>>15&1))?0x80:0);
}
/* These host calls have observable audio, motion or cable effects. All other
 * native calls execute their BIN body; internal-ROM calls normally yield. */
static int host_target(uint32_t target) {
    switch(target) {
    case 0x2000a9:case 0x201bcc:case 0x201cda:case 0x201d1e:
    case 0x2084e9:case 0x208571:case 0x208595:case 0x208926:return 1;
    default:return 0;
    }
}
static int instruction(void) {
    uint32_t r[8],fr=state[8],wa[8],wv[8],nw=0;
    for(uint32_t i=0;i<8;i++)r[i]=state[i];
    int ok=1;
    uint32_t pc=pc_of(r),op=word_at(pc,&ok);
    if(!ok)return 0;
    pc_set(r,pc+1);
    uint32_t top=op>>12,dst=(op>>9)&7,group=(op>>6)&7,mode=(op>>3)&7,src=op&7;
    uint32_t target=0,ret=0,left=0,right=0,address=0,result=0;
    int has_address=0,did_call=0;
#define READ(a) read_at((a),&ok)
#define WRITE(a,v) do { uint32_t addr_=(a); if(addr_>=0x2000 || nw==8) return 0; wa[nw]=addr_;wv[nw++]=(v)&65535; } while(0)
#define PUSH(reg,v) do { uint32_t value_=(v); WRITE(r[reg],value_); r[reg]=(r[reg]-1)&65535; } while(0)
    if(op==0xf165)goto commit;
    if((op&0xf1f8)==0xf108) {
        int32_t a=(int16_t)r[dst],b=(int16_t)r[src];
        uint32_t product=(uint32_t)(a*b);r[3]=product&65535;r[4]=product>>16;goto commit;
    }
    if((op&0xf1e7)==0xf161) { target=r[3]|((r[4]&63)<<16);ret=pc+1;goto call; }
    uint32_t irq=op&0xf1ff;
    if(irq>=0xf140 && irq<=0xf143) { fr=(fr&~0x60u)|((op&3)<<5);goto commit; }
    if(irq==0xf148 || irq==0xf149) { fr=(fr&~0x20u)|((op&1)<<5);goto commit; }
    if(irq==0xf14c || irq==0xf14e) { fr=(fr&~0x40u)|((op&2)<<5);goto commit; }
    if((op&0xf1f8)==0xf030) { r[src]=fr;goto commit; }
    if((op&0xf1f8)==0xf038) { if((fr^r[src])&0x2000)return 0;fr=r[src];goto commit; }
    if((op&0xf188)==0xe108) {
        uint32_t shift=(op>>4)&7,n=r[src]&31,v=r[dst];
        if(shift==2)r[dst]=(v<<n)&65535;
        else if(shift==3) { uint64_t w=(uint64_t)v<<n;r[3]=(uint32_t)w&65535;r[4]|=(uint32_t)(w>>16)&65535; }
        else if(shift==4)r[dst]=v>>n;else return 0;
        goto commit;
    }
    if(top<15 && dst==7 && group<2) { if(condition(r[6],top))pc_set(r,pc_of(r)+(group==0?(op&63):0u-(op&63)));goto commit; }
    if((op&0xf3c0)==0xf040) { target=((op&63)<<16)|word_at(pc+1,&ok);ret=pc+2;goto call; }
    if((op&0xffc0)==0xfe80) { target=((op&63)<<16)|word_at(pc+1,&ok);pc_set(r,target);goto commit; }
    if((op&0xffc0)==0xfe00 || (op&0xf1f8)==0xf028) {
        uint32_t v=(op&0xffc0)==0xfe00?op&63:r[src]&63;r[6]=(r[6]&0x3ff)|(v<<10);goto commit;
    }
    if(group==2 && top==13) {
        if(mode>dst+1)return 0;
        for(uint32_t i=0;i<mode;i++)PUSH(src,r[dst-i]);
        goto commit;
    }
    if(group==2 && top==9) {
        if(op==0x9a98 || dst+mode>7)return 0;
        for(uint32_t i=1;i<=mode;i++) { r[src]=(r[src]+1)&65535;r[dst+i]=READ(r[src]);if(!ok)return 0; }
        goto commit;
    }
    left=r[dst];
    if(group==0) { address=(r[5]+(op&63))&65535;has_address=1; }
    else if(group==1)right=op&63;
    else if(group==3) {
        if((mode&3)==3) { r[src]=(r[src]+1)&65535;if((mode&4)&&r[src]==0)r[6]=(r[6]+0x400)&65535; }
        address=((mode&4)?((r[6]>>10&63)<<16):0)|r[src];has_address=1;
        right=top==13?0:READ(address);if(!ok)return 0;
        if((mode&3)==1 || (mode&3)==2) {
            int minus=(mode&3)==1;r[src]=(r[src]+(minus?65535:1))&65535;
            if((mode&4)&&r[src]==(minus?65535u:0u))r[6]=(r[6]+(minus?0xfc00:0x400))&65535;
        }
    }
    else if(group==4 && mode==0)right=r[src];
    else if(group==4 && mode==1) { left=r[src];right=word_at(pc_of(r),&ok);pc_set(r,pc_of(r)+1); }
    else if(group==4 && (mode==2 || mode==3)) {
        address=word_at(pc_of(r),&ok);pc_set(r,pc_of(r)+1);has_address=1;
        if(mode==3)right=left;left=r[src];
    }
    else if(group==5 || group==6) {
        uint64_t shifted;uint32_t sb=(fr>>7)&15;
        if(group==5) {
            if(mode&4) { shifted=(((uint64_t)r[src]<<4)|sb)>>(mode-3);sb=(uint32_t)shifted&15;right=(uint32_t)(shifted>>4)&65535; }
            else { shifted=(((uint64_t)sb<<16)|r[src])<<(mode+1);sb=(uint32_t)(shifted>>16)&15;right=(uint32_t)shifted&65535; }
        } else {
            shifted=(((((uint64_t)sb<<16)|r[src])<<4)|sb);
            if(mode&4) { shifted>>=mode-3;sb=(uint32_t)shifted&15; }
            else { shifted<<=mode+1;sb=(uint32_t)(shifted>>20)&15; }
            right=(uint32_t)(shifted>>4)&65535;
        }
        fr=(fr&~0x780u)|(sb<<7);
    } else return 0;
    if(!ok)return 0;
    if(has_address && top!=13 && group!=3 && !(group==4 && mode==3))right=READ(address);
    if(!ok)return 0;
    if(top==13) { if(!has_address)return 0;WRITE(address,left);goto commit; }
    if(top<=4) {
        uint32_t operand=top<=1?right:(~right)&65535;
        uint32_t carry=(top==1||top==3)?!!(r[6]&0x40):(top==2||top==4);
        result=left+operand+carry;
        if(dst!=7)r[6]=arithmetic_flags(r[6],result,left,operand);
        if(top==4)goto commit;
    } else {
        switch(top) {
        case 6:result=0u-right;break;case 8:result=left^right;break;case 9:result=right;break;
        case 10:result=left|right;break;case 11:case 12:result=left&right;break;default:return 0;
        }
        if(dst!=7)r[6]=logic_flags(r[6],result);
        if(top==12)goto commit;
    }
    if(group==4 && mode==3)WRITE(address,result);else r[dst]=result&65535;
    goto commit;
call:
    if(!ok || host_target(target))return 0;
    if(state[13]>=WORDS)return 0;
    did_call=1;
    if(target<0x200000) {
        /* Only the audited pure unsigned 32-bit arithmetic adapters. All stateful
         * ROM routines, SPI, clocks and errors return to the host. */
        if(!adapters_enabled || (target!=0x63cf && target!=0x603c && target!=0x60b3))return 0;
        uint32_t a=READ(r[0]+1);a|=READ(r[0]+2)<<16;
        uint32_t b=READ(r[0]+3);b|=READ(r[0]+4)<<16;
        if(!ok || (target!=0x63cf && b==0))return 0;
        uint32_t v=target==0x63cf?a*b:target==0x603c?a/b:a%b;
        r[1]=v&65535;r[2]=v>>16;pc_set(r,ret);
        /* Bitset is diagnostic only; commit it after all validation. */
        state[12]|=target==0x63cf?1:target==0x603c?2:4;
    } else { pc_set(r,ret);PUSH(0,r[7]);PUSH(0,r[6]);pc_set(r,target); }
commit:
    if(!ok)return 0;
    for(uint32_t i=0;i<nw;i++) {
        uint32_t a=wa[i];ram[a]=wv[i];valid[a]=1;
        if(!changed[a]) { changed[a]=1;dirty[state[11]++]=a; }
    }
    for(uint32_t i=0;i<8;i++)state[i]=r[i];
    if(did_call)calls[state[13]++]=target;
    state[8]=fr;state[9]++;return 1;
#undef READ
#undef WRITE
#undef PUSH
}
/* 0: native return sentinel, 1: execute one host/reference instruction,
 * 2: budget exhausted. No trap or unchecked guest address is exposed. */
API uint32_t run(uint32_t budget) {
    while(pc_of(state)!=STOP) {
        if(state[9]>=budget)return state[10]=2;
        if(!instruction())return state[10]=1;
    }
    return state[10]=0;
}
