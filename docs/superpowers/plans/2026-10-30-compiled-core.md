# Compiled Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Replace the Python instruction hot loop with a locally authored compiled engine, preserving native gameplay.

**Architecture:** C runs checked RAM, ROM and instruction semantics; the host retains audited adapters and transactional saves. Wasm in browsers and the same C as a native library support differential verification.

**Tech Stack:** C11, Wasm, JavaScript, Python reference; portable pinned Zig/Clang compiler.

**Spec:** ../specs/2026-10-30-compiled-core.md

## Global Constraints
- Do not import another emulator distribution or publish firmware.
- Keep existing notices; do not claim clean-room authorship.
- Preserve native state, input, sound, motion, QR and snapshots.
- No deployment before paired browser correctness/performance gate.

## Review Focus
- Missing RAM, ROM bounds and unsupported opcodes must not silently succeed.
- Side-effect callbacks must see current registers/RAM and resume correctly.
- Instruction budgets and errors must retain transaction rollback.
- Unknown families and custom hooks must keep reference behavior.
- Native desktop gains must not be labelled Android measurements.

### Task 1: Compiled engine and tests
**Files:** src/pocket_cpu.c, tools/build-core.py, tests/test_compiled_cpu.py, public/core/pocket_cpu.wasm.
**Interfaces:** state buffers plus run(budget); yield before host-managed instructions; checked RAM/ROM.
- [x] Add failing synthetic tests for arithmetic, flags, memory, stack, branches, budgets, error bounds and host yield.
- [x] Build the minimal freestanding engine and compare all opcode words and mixed programs against the reference.
- [x] Verify the same source compiles to browser Wasm.

### Task 2: Host integration and real BIN verification
**Files:** public/core/compiled_cpu.py, public/compiled-engine.js, public/worker.js; local QA tools.
**Interfaces:** optional compiled backend installation for the exact supported MotionCPU, reference fallback for custom hooks.
- [x] Add failing tests for host callback state, rollback, and R23 fixed input sequence.
- [x] Integrate at native run boundaries; maintain diagnostics through reference mode.
- [x] Compare clock enter/leave, cry, motion and existing gameplay tests; retain cross-family fallback.

### Task 3: Paired browser evidence and integration decision
**Files:** local benchmark fixture, benchmark receipt; release files only if gate passes.
- [x] Measure reference/new engine in paired alternating browser trials, identical outputs.
- [x] Run full Python and Node suites, obtain fresh review.
- [x] If gates pass, integrate tested files with release provenance; otherwise keep the runnable experiment and record exact blocker without changing production.
