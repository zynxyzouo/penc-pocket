# Foreground responsiveness implementation plan

> For agentic workers: use superpowers:subagent-driven-development for the two independent implementation tasks; root integrates and verifies deployment.

**Goal:** Reduce CPU work and input waiting behind native frames, improving clock transitions, call cadence and controls on slower devices.

**Architecture:** Optimize the existing additive CPU accelerator while retaining strict CPU semantics and native frame timing. Bound urgent input batches and preserve scheduling debt correctly. Compare current and candidate builds with the same local R23 BIN and browser runtime before publishing.

**Tech stack:** Python/Pyodide worker, JavaScript UI, static GitHub Pages.

**Spec:** User request on 2026-10-29: improve Android transitions, call intervals and button latency together, then update website if tests pass. Prior controlled R23 reproduction: clock transitions require 24 native frames; call repeats every 43 frames; RTC tracks elapsed wall time independently.

## Global constraints

- No BIN edits, uploads or firmware extracts in the public repository.
- Preserve immutable snapshot identity files: bench.py, cpu.py, hd_host.py, host_clock.py, web_adapter.py.
- Preserve RAM, registers, flags, peripheral/call hooks, traces, instruction budgets, exception states and transaction rollback against the reference CPU.
- Preserve sound pitch +48 and melody rate 2; do not fake call cadence or advance gameplay timers without native updates.
- Keep existing saves, offline custody, native QR Battle/Jogres, motion and supported machine families compatible.
- Desktop/browser measurements are not TITAN1 hardware evidence.

## Review focus

- Aliased stack/SR/PC registers and failures halfway through instructions retain exact partial states.
- Custom CPU overrides and unknown instructions retain strict fallback.
- Press/release ordering and long presses survive queued input during a slow frame.
- Native batching does not silently discard uncompleted frame claims or grow unbounded catch-up.
- Both current and candidate use identical firmware, state and runtime for performance comparison.

### Task 1: CPU interpreter work

Files: public/core/cpu_accelerator.py, tests/test_cpu_accelerator.py; private profiling under penc-pocket-deploy-tools/foreground-20261029.

- [ ] Profile repeated native clock transition work and identify interpreter overhead.
- [ ] Add failing deterministic work-reduction tests plus differential state coverage.
- [ ] Optimize decoded execution while preserving every Global Constraint.
- [ ] Run synthetic differential tests and actual R23 differential paths; report performance and self-review.
- [ ] Independent task review and corrections.

### Task 2: Input and frame scheduling

Files: public/pacing.js, public/app.js, tests/pacing.test.mjs; runtime_bridge.py only if required and coordinated.

- [ ] Reproduce urgent input delayed by batching and discarded partial claims using deterministic tests.
- [ ] Minimize waiting for queued input without bypassing native semantics or dropping edges.
- [ ] Test press/release, forced updates, partial batches, pause/resume and bounded debt.
- [ ] Independent task review and corrections.

### Task 3: Integration and deployment

- [ ] Run full Python suite with private R23 and Node suite.
- [ ] Browser baseline/candidate checks: home, entering/leaving clock, cry sequence, input turnaround, slow-worker workload; compare state checksums.
- [ ] Run fresh broad code review, fix material issues, update notices and release allowlist/integrity, build public bundle.
- [ ] Publish source-only PR, merge after checks, verify GitHub Pages deployed bytes and real browser startup.
- [ ] Record receipt and report results with device limitation.
