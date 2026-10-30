/* SPDX-License-Identifier: GPL-3.0-or-later
 * Port of gpce4_machine/soc.py. Register map and IRQ wiring follow MAME
 * 0.289 generalplus_gpce4_soc.cpp / generalplus_gpce4.cpp (BSD-3-Clause,
 * David Haywood). Instruction speed, 48 MHz timer clock and ADC are guesses.
 * No firmware functions are replaced with host implementations.
 */
#include "gpce4.h"
#include <stddef.h>
#if defined(_WIN32)
#define API __declspec(dllexport)
#else
#define API __attribute__((visibility("default")))
#endif
#define FLASH_SIZE 0x800000u
#define FIFO_SIZE 65536u
#define LCD_SIDE 162u
#define SNAP_MAGIC 0x34435047u
#define SNAP_VERSION 1u
#define TIME_LIMIT UINT64_C(0x7ffffffff0000000)

/* Freestanding Wasm does not import a libc or an allocator. */
void *memset(void *out, int value, size_t length) {
    volatile uint8_t *p = (volatile uint8_t *)out;
    for (size_t i = 0; i < length; ++i) p[i] = (uint8_t)value;
    return out;
}
void *memcpy(void *out, const void *in, size_t length) {
    volatile uint8_t *p = (volatile uint8_t *)out;
    const volatile uint8_t *q = (const volatile uint8_t *)in;
    for (size_t i = 0; i < length; ++i) p[i] = q[i];
    return out;
}

typedef struct {
    uint16_t ram[0x3000], io[0x1000], lcd[LCD_SIDE * LCD_SIDE];
    uint8_t rx[FIFO_SIZE], dirty[2048], unknown[0x1000], ram_high[48];
    uint8_t lcd_commands[4000];
    uint32_t ips, ioa_in, iob_in, int_status, int_ctrl, int2_ctrl;
    uint32_t spi_bank, rx_head, rx_count, unknown_count, dirty_count;
    uint32_t selected, wel, deep_sleep;
    int32_t spi_cmd;
    uint32_t spi_args, spi_addr;
    int32_t lcd_cmd, pending_byte;
    uint32_t lcd_param_count, lcd_params[4], command_count;
    uint32_t x0, x1, y0, y1, x, y, madctl, colmod, lcd_on;
    uint32_t timer_active[3];
    uint64_t instr, next_event, timebase_next[6], timer_next[3], pixels_written;
} GpSoc;
typedef struct {
    uint32_t magic, version, size, crc;
    GpCpu cpu;
    GpSoc soc;
} GpSnapshot;
_Static_assert(sizeof(GpCpu) == 96, "CPU ABI must remain stable");
_Static_assert(offsetof(GpSnapshot, cpu) == 16, "Snapshot header ABI");

static uint8_t irom[0x18000], flash[FLASH_SIZE], rgba[96 * 96 * 4];
static GpSoc soc;
static GpSnapshot staging;
static uint32_t metrics[24];
static const uint32_t timebase_bits[6] = {0, 1, 2, 8, 9, 10};
static const uint32_t timebase_hz[6] = {2, 16, 64, 512, 2048, 4096};

static void fault(uint32_t code, uint32_t address) {
    if (!cpu.fault) {
        cpu.fault = code;
        cpu.fault_pc = gp_cpu_pc();
        cpu.fault_address = address;
    }
}
static void note(uint32_t address, uint8_t kind) {
    uint32_t index = address - 0x3000;
    if (index < 0x1000 && !(soc.unknown[index] & kind)) {
        soc.unknown[index] |= kind;
        ++soc.unknown_count;
    }
}
static void mark_dirty(uint32_t at) {
    uint32_t page = at >> 12;
    if (page < 2048 && !soc.dirty[page]) {
        soc.dirty[page] = 1;
        ++soc.dirty_count;
    }
}
static void update_irqs(void) {
    static const uint16_t masks1[8] = {0x8000,0x4000,0x2000,0x0BC0,0x0030,0x0003,0,0};
    static const uint16_t masks2[8] = {0,0,0,0,0,0,0x1F00,0x0037};
    uint32_t s1 = (soc.int_status >> 16) & soc.int_ctrl;
    uint32_t s2 = (soc.int_status & 0xFFFF) & soc.int2_ctrl;
    for (uint32_t n = 0; n < 8; ++n)
        gp_cpu_irq(n + 1, !!((s1 & masks1[n]) | (s2 & masks2[n])));
}
static uint64_t timer_period(uint32_t count) {
    uint64_t period = (UINT64_C(0x10000) - count) * soc.ips / 48000000u;
    return period ? period : 1;
}
static void reset_timebase(void) {
    for (uint32_t n = 0; n < 6; ++n)
        soc.timebase_next[n] = soc.instr + soc.ips / timebase_hz[n];
}
static void start_timer(uint32_t n) {
    soc.timer_active[n] = !!((soc.io[0x16] >> (n * 4)) & 15);
    if (soc.timer_active[n])
        soc.timer_next[n] = soc.instr + timer_period(soc.io[0x11 + n * 2]);
    else soc.timer_next[n] = 0;
}
static uint64_t tick_timers(void) {
    uint64_t next = UINT64_MAX;
    for (uint32_t n = 0; n < 6; ++n) {
        if (soc.instr >= soc.timebase_next[n]) {
            soc.timebase_next[n] += soc.ips / timebase_hz[n];
            soc.int_status |= 1u << timebase_bits[n];
        }
        if (soc.timebase_next[n] < next) next = soc.timebase_next[n];
    }
    for (uint32_t n = 0; n < 3; ++n) {
        if (!soc.timer_active[n]) continue;
        if (soc.instr >= soc.timer_next[n]) {
            soc.timer_next[n] += timer_period(soc.io[0x10 + n * 2]);
            soc.int_status |= 1u << (31 - n);
        }
        if (soc.timer_next[n] < next) next = soc.timer_next[n];
    }
    update_irqs();
    return next;
}
static void spi_select(void) {
    soc.selected = 1;
    soc.spi_cmd = -2;
    soc.spi_args = 0;
}
static void spi_deselect(void) {
    if (soc.selected && soc.spi_cmd == 0x20 && soc.spi_args >= 3 && soc.wel) {
        uint32_t at = soc.spi_addr & ~0xFFFu;
        if (at > FLASH_SIZE - 4096) fault(2, soc.spi_addr);
        else { memset(flash + at, 0xFF, 4096); mark_dirty(at); }
    }
    int32_t c = soc.spi_cmd;
    if ((c == 2 || c == 0x20 || c == 0xD8 || c == 0x52 || c == 0x60 || c == 0xC7 || c == 1)
        && (soc.spi_args >= 1 || c == 0x60 || c == 0xC7)) soc.wel = 0;
    soc.selected = 0;
    soc.spi_cmd = -2;
}
static uint8_t spi_transfer(uint8_t byte) {
    static const uint8_t jedec[3] = {0xC2,0x20,0x17};
    if (!soc.selected) return 0xFF;
    if (soc.spi_cmd == -2) {
        soc.spi_cmd = byte;
        soc.spi_args = 0;
        if (soc.deep_sleep && byte != 0xAB) { soc.spi_cmd = -1; return 0xFF; }
        if (byte == 6) soc.wel = 1;
        else if (byte == 4) soc.wel = 0;
        else if (byte == 0xB9) soc.deep_sleep = 1;
        return 0xFF;
    }
    if (soc.spi_args != UINT32_MAX) ++soc.spi_args;
    uint32_t n = soc.spi_args;
    int32_t c = soc.spi_cmd;
    if (c == 5) return soc.wel ? 2 : 0;
    if (c == 0x9F) return n >= 1 && n <= 3 ? jedec[n - 1] : 0xFF;
    if (c == 0xAB) { soc.deep_sleep = 0; return n >= 4 ? 0x16 : 0xFF; }
    if (c == 3 || c == 0x0B || c == 2 || c == 0x20 || c == 0xD8 || c == 0x52 || c == 0x90) {
        if (n <= 3) {
            soc.spi_addr = n > 1 ? ((soc.spi_addr << 8) | byte) & 0xFFFFFF : byte;
            return 0xFF;
        }
        if (c == 0x0B && n == 4) return 0xFF;
        if (c == 3 || c == 0x0B) {
            uint8_t v = flash[soc.spi_addr % FLASH_SIZE];
            soc.spi_addr = (soc.spi_addr + 1) % FLASH_SIZE;
            return v;
        }
        if (c == 2 && soc.wel) {
            uint32_t at = soc.spi_addr;
            if (at >= FLASH_SIZE) { fault(2, at); return 0xFF; }
            flash[at] &= byte;
            mark_dirty(at);
            soc.spi_addr = (at & ~0xFFu) | ((at + 1) & 0xFF);
        }
    }
    return 0xFF;
}
static void lcd_command(uint8_t byte) {
    soc.lcd_cmd = byte;
    soc.lcd_param_count = 0;
    memset(soc.lcd_params, 0, sizeof soc.lcd_params);
    soc.pending_byte = -1;
    if (soc.command_count < 4000) soc.lcd_commands[soc.command_count++] = byte;
    if (byte == 0x2C) { soc.x = soc.x0; soc.y = soc.y0; }
    else if (byte == 0x29) soc.lcd_on = 1;
    else if (byte == 0x28) soc.lcd_on = 0;
}
static void lcd_data(uint8_t byte) {
    if (soc.lcd_cmd == 0x2C) {
        if (soc.pending_byte < 0) { soc.pending_byte = byte; return; }
        uint16_t pixel = (uint16_t)((soc.pending_byte << 8) | byte);
        if (soc.x < LCD_SIDE && soc.y < LCD_SIDE) soc.lcd[soc.y * LCD_SIDE + soc.x] = pixel;
        ++soc.pixels_written;
        soc.pending_byte = -1;
        ++soc.x;
        if (soc.x > soc.x1) {
            soc.x = soc.x0;
            ++soc.y;
            if (soc.y > soc.y1) soc.y = soc.y0;
        }
        return;
    }
    if (soc.lcd_param_count < 4) soc.lcd_params[soc.lcd_param_count] = byte;
    if (soc.lcd_param_count < 5) ++soc.lcd_param_count;
    uint32_t *p = soc.lcd_params;
    if (soc.lcd_cmd == 0x2A && soc.lcd_param_count == 4) {
        soc.x0 = (p[0] << 8) | p[1]; soc.x1 = (p[2] << 8) | p[3];
    } else if (soc.lcd_cmd == 0x2B && soc.lcd_param_count == 4) {
        soc.y0 = (p[0] << 8) | p[1]; soc.y1 = (p[2] << 8) | p[3];
    } else if (soc.lcd_cmd == 0x36 && soc.lcd_param_count == 1) soc.madctl = byte;
    else if (soc.lcd_cmd == 0x3A && soc.lcd_param_count == 1) soc.colmod = byte;
}
static uint32_t io_read(uint32_t a) {
    uint32_t i = a - 0x3000;
    switch (a) {
    case 0x3000: return (soc.io[1] & soc.io[2]) | (soc.ioa_in & ~soc.io[2] & 0xFFFF);
    case 0x3001: return soc.io[1];
    case 0x3004: return (soc.io[5] & soc.io[6]) | (soc.iob_in & ~soc.io[6] & 0xFFFF);
    case 0x3008: return soc.io[9];
    case 0x3039: return soc.io[i] & ~2u;
    case 0x3050: return soc.int_ctrl;
    case 0x3053: return soc.int2_ctrl;
    case 0x3051: return soc.int_status >> 16;
    case 0x3054: return soc.int_status & 0xFFFF;
    case 0x30E9: return soc.spi_bank | (soc.io[i] & ~15u);
    case 0x30E3: return 0x8000 | (soc.rx_count < 8 ? soc.rx_count : 8);
    case 0x30E4:
        if (!soc.rx_count) { note(a, 4); return 0; }
        { uint32_t v = soc.rx[soc.rx_head]; soc.rx[soc.rx_head] = 0;
          soc.rx_head = (soc.rx_head + 1) % FIFO_SIZE; --soc.rx_count; return v; }
    case 0x30E5: return (soc.rx_count ? 4 : 0) | 3;
    case 0x3071: return 0xE000;
    case 0x3091: case 0x3093: case 0x3094: return 0;
    case 0x3095: return 3;
    case 0x3002: case 0x3003: case 0x3005: case 0x3006: case 0x3007:
    case 0x3009: case 0x300A: case 0x300B: case 0x300F: case 0x3016:
    case 0x3020: case 0x3021: case 0x3022: case 0x3023: case 0x3030:
    case 0x30E0: case 0x30E7: case 0x3090: case 0x3072: case 0x3070:
        return soc.io[i];
    default: note(a, 1); return soc.io[i];
    }
}
static void io_write(uint32_t a, uint32_t v) {
    uint32_t i = a - 0x3000, old = soc.io[i];
    soc.io[i] = (uint16_t)v;
    switch (a) {
    case 0x3000: case 0x3001:
        soc.io[1] = (uint16_t)v;
        if (((old ^ v) & 0x1000) || a == 0x3000) {
            if (!(v & 0x1000) && !soc.selected) spi_select();
            else if ((v & 0x1000) && soc.selected) spi_deselect();
        }
        return;
    case 0x3004: soc.io[5] = (uint16_t)v; return;
    case 0x3050: soc.int_ctrl = v; update_irqs(); return;
    case 0x3053: soc.int2_ctrl = v; update_irqs(); return;
    case 0x3051: soc.int_status &= ~(v << 16); update_irqs(); return;
    case 0x3054: soc.int_status &= ~v; update_irqs(); return;
    case 0x3033: reset_timebase(); soc.next_event = soc.instr; return;
    case 0x3036: cpu.sleeping = 1; return;
    case 0x30E0:
        if (v & 0x800) { memset(soc.rx, 0, sizeof soc.rx); soc.rx_head = soc.rx_count = 0; }
        return;
    case 0x30E2:
        if (soc.rx_count == FIFO_SIZE) { fault(3, a); return; }
        soc.rx[(soc.rx_head + soc.rx_count) % FIFO_SIZE] = spi_transfer((uint8_t)v);
        ++soc.rx_count;
        return;
    case 0x30E9: soc.spi_bank = v & 15; return;
    case 0x3092:
        if (soc.io[5] & 0x400) lcd_data((uint8_t)v); else lcd_command((uint8_t)v);
        return;
    default: break;
    }
    if (a >= 0x3010 && a <= 0x3016) {
        for (uint32_t n = 0; n < 3; ++n) {
            uint32_t data = 0x3010 + n * 2;
            if (a == data + 1 || a == 0x3016 || (a == data && !soc.timer_active[n])) start_timer(n);
        }
        soc.next_event = soc.instr;
        return;
    }
    switch (a) {
    case 0x3002: case 0x3003: case 0x3005: case 0x3006: case 0x3007:
    case 0x3008: case 0x3009: case 0x300A: case 0x300B: case 0x300C:
    case 0x300D: case 0x300E: case 0x300F: case 0x3020: case 0x3021:
    case 0x3022: case 0x3023: case 0x3030: case 0x3032: case 0x3034:
    case 0x3035: case 0x3039: case 0x3040: case 0x3041: case 0x3042:
    case 0x3043: case 0x3052: case 0x3055: case 0x3070: case 0x3071:
    case 0x3072: case 0x3073: case 0x3090: case 0x3091: case 0x3093:
    case 0x3095: case 0x30E1: case 0x30E3: case 0x30E5: case 0x30E6:
    case 0x30E7: return;
    default: note(a, 2); return;
    }
}
uint32_t gp_read(uint32_t a) {
    if (cpu.fault) return 0;
    if (a < 0x3000) {
        if (a >= 0x1000) soc.ram_high[a >> 8] = 1;
        return soc.ram[a];
    }
    if (a < 0x4000) return io_read(a);
    if (a < 0x10000) {
        uint32_t at = (a - 0x4000) * 2;
        return irom[at] | (uint32_t)irom[at + 1] << 8;
    }
    if (a >= 0x200000 && a < 0x400000) {
        uint32_t at = soc.spi_bank * 0x400000u + 2 * (a - 0x200000);
        if (at >= FLASH_SIZE - 1) { fault(2, a); return 0; }
        return flash[at] | (uint32_t)flash[at + 1] << 8;
    }
    fault(2, a);
    return 0;
}
void gp_write(uint32_t a, uint32_t value) {
    if (cpu.fault) return;
    uint32_t v = value & 0xFFFF;
    if (a < 0x3000) {
        if (a >= 0x1000) soc.ram_high[a >> 8] = 1;
        soc.ram[a] = (uint16_t)v; return;
    }
    if (a < 0x4000) { io_write(a, v); return; }
    fault(2, a);
}

API uint32_t gp_bus_read(uint32_t a) { return gp_read(a); }
API void gp_bus_write(uint32_t a, uint32_t v) { gp_write(a, v); }
API uint8_t *gp_irom_ptr(void) { return irom; }
API uint8_t *gp_flash_ptr(void) { return flash; }
API uint32_t gp_flash_size(void) { return FLASH_SIZE; }
API GpCpu *gp_cpu_ptr(void) { return &cpu; }
API uint16_t *gp_ram_ptr(void) { return soc.ram; }
API uint16_t *gp_io_ptr(void) { return soc.io; }
API uint8_t *gp_dirty_ptr(void) { return soc.dirty; }
API int gp_reset(uint32_t ips) {
    if (!ips) ips = 12000000;
    if (ips < 4096 || ips > 100000000) return 0;
    memset(&soc, 0, sizeof soc);
    soc.ips = ips;
    soc.ioa_in = 0xFFFF;
    soc.spi_cmd = -2;
    soc.lcd_cmd = soc.pending_byte = -1;
    soc.x1 = soc.y1 = LCD_SIDE - 1;
    soc.colmod = 6;
    gp_cpu_reset();
    reset_timebase();
    return !cpu.fault;
}
API uint32_t gp_run(uint32_t instructions) {
    if (cpu.fault || soc.instr > TIME_LIMIT - instructions) return 0;
    uint64_t start = soc.instr, end = start + instructions;
    soc.next_event = soc.instr;
    while (soc.instr < end && !cpu.fault) {
        if (soc.instr >= soc.next_event) soc.next_event = tick_timers();
        if (cpu.sleeping && !cpu.sirq) {
            uint64_t target = soc.next_event < end ? soc.next_event : end;
            soc.instr = target > soc.instr ? target : soc.instr + 1;
            continue;
        }
        gp_cpu_step();
        if (!cpu.fault) ++soc.instr;
    }
    return (uint32_t)(soc.instr - start);
}
API void gp_keys(uint32_t mask) { soc.ioa_in = 0xFFFF & ~(mask & 0x38); }
API uint8_t *gp_rgba_ptr(void) {
    for (uint32_t y = 0; y < 96; ++y) for (uint32_t x = 0; x < 96; ++x) {
        uint32_t v = soc.lcd[(y + 18) * LCD_SIDE + x], at = (y * 96 + x) * 4;
        rgba[at] = (uint8_t)(((v >> 11) & 31) * 255 / 31);
        rgba[at + 1] = (uint8_t)(((v >> 5) & 63) * 255 / 63);
        rgba[at + 2] = (uint8_t)((v & 31) * 255 / 31);
        rgba[at + 3] = 255;
    }
    return rgba;
}
/* Stable uint32[24] ABI. The low/high pairs are little-endian uint64 values.
 * 0 ABI version; 1 fault; 2 fault PC; 3 opcode; 4 fault address;
 * 5,6 virtual instructions; 7,8 CPU steps; 9 PC; 10,11 LCD pixels written;
 * 12 IRQ status; 13 CPU sirq; 14 sleeping; 15 distinct unknown IO accesses;
 * 16 RX bytes; 17 dirty Flash pages; 18 guessed IPS; 19 LCD on; 20 bank;
 * 21 snapshot size; 22 RX capacity; 23 reserved.
 */
API uint32_t *gp_metrics_ptr(void) {
    metrics[0] = 1; metrics[1] = cpu.fault; metrics[2] = cpu.fault_pc;
    metrics[3] = cpu.fault_op; metrics[4] = cpu.fault_address;
    metrics[5] = (uint32_t)soc.instr; metrics[6] = (uint32_t)(soc.instr >> 32);
    metrics[7] = (uint32_t)cpu.steps; metrics[8] = (uint32_t)(cpu.steps >> 32);
    metrics[9] = gp_cpu_pc(); metrics[10] = (uint32_t)soc.pixels_written;
    metrics[11] = (uint32_t)(soc.pixels_written >> 32);
    metrics[12] = soc.int_status; metrics[13] = cpu.sirq; metrics[14] = cpu.sleeping;
    metrics[15] = soc.unknown_count; metrics[16] = soc.rx_count;
    metrics[17] = soc.dirty_count; metrics[18] = soc.ips; metrics[19] = soc.lcd_on;
    metrics[20] = soc.spi_bank; metrics[21] = sizeof staging;
    metrics[22] = FIFO_SIZE; metrics[23] = 0;
    return metrics;
}
static uint32_t snapshot_crc(void) {
    const uint8_t *p = (const uint8_t *)&staging + 16;
    uint32_t crc = 0xFFFFFFFF;
    for (size_t n = 16; n < sizeof staging; ++n) {
        crc ^= *p++;
        for (uint32_t bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1)));
    }
    return ~crc;
}
API uint32_t gp_state_size(void) { return sizeof staging; }
/* Refreshes an isolated staging area. Import must copy exactly gp_state_size()
 * bytes to this pointer then call gp_restore WITHOUT calling gp_state_ptr again.
 * Raw state is a versioned little-endian ABI, excluding ROM/Flash. The caller
 * must validate file sizes, firmware/ROM identities and pair the matching Flash.
 */
API uint8_t *gp_state_ptr(void) {
    memset(&staging, 0, sizeof staging);
    staging.magic = SNAP_MAGIC; staging.version = SNAP_VERSION;
    staging.size = sizeof staging;
    memcpy(&staging.cpu, &cpu, sizeof cpu);
    memcpy(&staging.soc, &soc, sizeof soc);
    staging.crc = snapshot_crc();
    return (uint8_t *)&staging;
}
API int gp_restore(void) {
    if (staging.magic != SNAP_MAGIC || staging.version != SNAP_VERSION ||
        staging.size != sizeof staging || staging.crc != snapshot_crc()) return 0;
    const GpCpu *c = &staging.cpu;
    const GpSoc *s = &staging.soc;
    for (uint32_t n = 0; n < 8; ++n) if (c->r[n] > 0xFFFF) return 0;
    for (uint32_t n = 0; n < 4; ++n) if (c->secbank[n] > 0xFFFF) return 0;
    if (c->fr > 0xFFFF || c->sirq > 0x1FF || c->irq_active > 1 || c->fiq_active > 1 ||
        c->sleeping > 1 || c->fault > 3 || c->fault_pc > 0x3FFFFF || c->fault_op > 0xFFFF) return 0;
    if (s->ips < 4096 || s->ips > 100000000 || s->instr > TIME_LIMIT ||
        s->next_event > TIME_LIMIT || s->ioa_in > 0xFFFF || s->iob_in > 0xFFFF ||
        s->int_ctrl > 0xFFFF || s->int2_ctrl > 0xFFFF || s->spi_bank > 15 ||
        s->rx_head >= FIFO_SIZE || s->rx_count > FIFO_SIZE || s->selected > 1 ||
        s->wel > 1 || s->deep_sleep > 1 || s->spi_cmd < -2 || s->spi_cmd > 255 ||
        s->spi_addr > 0xFFFFFF || s->lcd_cmd < -1 || s->lcd_cmd > 255 ||
        s->pending_byte < -1 || s->pending_byte > 255 || s->lcd_param_count > 5 ||
        s->command_count > 4000 || s->x0 > 65535 || s->x1 > 65535 ||
        s->y0 > 65535 || s->y1 > 65535 || s->x > 65535 || s->y > 65535 ||
        s->madctl > 255 || s->colmod > 255 || s->lcd_on > 1) return 0;
    for (uint32_t n = 0; n < 4; ++n) if (s->lcd_params[n] > 255) return 0;
    for (uint32_t n = 0; n < 6; ++n)
        if (s->timebase_next[n] > TIME_LIMIT || !s->timebase_next[n]) return 0;
    for (uint32_t n = 0; n < 3; ++n)
        if (s->timer_active[n] > 1 || s->timer_next[n] > TIME_LIMIT ||
            (s->timer_active[n] && !s->timer_next[n])) return 0;
    uint32_t dirty = 0, unknown = 0;
    for (uint32_t n = 0; n < 2048; ++n) { if (s->dirty[n] > 1) return 0; dirty += s->dirty[n]; }
    for (uint32_t n = 0; n < 0x1000; ++n) {
        uint32_t v = s->unknown[n]; if (v > 7) return 0;
        unknown += (v & 1) + ((v >> 1) & 1) + ((v >> 2) & 1);
    }
    for (uint32_t n = 0; n < 48; ++n) if (s->ram_high[n] > 1) return 0;
    if (dirty != s->dirty_count || unknown != s->unknown_count) return 0;
    memcpy(&cpu, c, sizeof cpu);
    memcpy(&soc, s, sizeof soc);
    return 1;
}
