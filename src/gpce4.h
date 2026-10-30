/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef GPCE4_H
#define GPCE4_H
#include <stdint.h>
typedef struct {
 uint32_t r[8], fr, secbank[4], sirq, irq_active, fiq_active, sleeping;
 uint64_t steps;
 uint32_t fault, fault_pc, fault_op, fault_address;
} GpCpu;
extern GpCpu cpu;
uint32_t gp_read(uint32_t address);
void gp_write(uint32_t address, uint32_t value);
void gp_cpu_reset(void);
int gp_cpu_step(void);
uint32_t gp_cpu_pc(void);
void gp_cpu_irq(uint32_t line, uint32_t level);
#endif
