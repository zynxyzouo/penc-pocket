/* SPDX-License-Identifier: GPL-3.0-or-later
 * Deterministic word bus for CPU-only differential tests. No ROM data. */
#include "../src/gpce4.h"
#include <stdint.h>
#ifdef _WIN32
#define API __declspec(dllexport)
#else
#define API __attribute__((visibility("default")))
#endif
static uint32_t seed, count, trace_count, fail_address;
static uint32_t addresses[128], values[128], trace[256][3];
API void gpce4_cpu_test_begin(uint32_t value) {
 seed=value; count=trace_count=0; fail_address=0xffffffffu;
}
API void gpce4_cpu_test_poke(uint32_t address,uint32_t value) {
 for(uint32_t i=0;i<count;i++) if(addresses[i]==address){values[i]=value;return;}
 if(count<128){addresses[count]=address;values[count++]=value;}
}
API void gpce4_cpu_test_fail(uint32_t address){fail_address=address;}
static void record(uint32_t kind,uint32_t address,uint32_t value){
 if(trace_count<256){trace[trace_count][0]=kind;trace[trace_count][1]=address;trace[trace_count][2]=value;trace_count++;}
}
uint32_t gp_read(uint32_t address){
 if(address==fail_address){cpu.fault=2;cpu.fault_address=address;return 0;}
 uint32_t v=((address*109u+seed)^(address>>8))&65535u;
 for(uint32_t i=0;i<count;i++) if(addresses[i]==address){v=values[i];break;}
 record(0,address,v); return v;
}
void gp_write(uint32_t address,uint32_t value){
 if(address==fail_address){cpu.fault=2;cpu.fault_address=address;return;}
 record(1,address,value&65535u); gpce4_cpu_test_poke(address,value&65535u);
}
API GpCpu *gpce4_cpu_test_state(void){return &cpu;}
API uint32_t gpce4_cpu_test_trace_count(void){return trace_count;}
API const uint32_t *gpce4_cpu_test_trace(void){return &trace[0][0];}
API void gpce4_cpu_test_reset(void){gp_cpu_reset();}
API uint32_t gpce4_cpu_test_pc(void){return gp_cpu_pc();}
API int gpce4_cpu_test_step(void){return gp_cpu_step();}
API void gpce4_cpu_test_irq(uint32_t line,uint32_t level){gp_cpu_irq(line,level);}
