# R23 Offline Custody Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Independent native research may run in parallel.

**Goal:** Continue R23 growth during offline custody without new care mistakes or per-second replay.
**Architecture:** An additive, exact-ROM-gated custody adapter calls native minute/lifecycle boundaries. A settlement session keeps a fixed offline target and excludes processing overhead; existing save validation and native execution remain authoritative.
**Tech Stack:** Python/Pyodide worker, browser JavaScript, unittest and Node tests.
**Spec:** ../specs/2026-10-29-offline-custody.md

## Global Constraints
- No BIN publication or mutation; no edits to the five snapshot-identity core files.
- Preserve prior care mistakes and achievements; verify both native context banks.
- No irreversible migration of user saves, no silent heuristic support for unknown BINs.
- Errors stop at a recoverable boundary; never discard unsimulated time to fake fast completion.

## Review Focus
- Existing illness, pending evolution/death or a non-HOME saved screen.
- Hidden pet care and context selection restoration.
- Duplicate/resumed work after saving, cancellation and tab closure.
- Clock rollback, huge time gaps and changing mode during partial settlement.
- Processing overhead accidentally becoming more offline debt.

### Task 1: Audited custody event engine
Files: public/core/offline_custody.py, tests/test_offline_custody.py.
Interface: supports(bench), catch_up(bench, seconds, budget_ms=35) with processed_seconds, remaining_seconds, blocked_reason and event counts.
- [x] Prove native boundaries/care fields against actual R23; record private fixtures and evidence.
- [x] Write failing contract and real R23 tests for CM preservation, growth, two pets and lifecycle.
- [x] Implement guarded native event/minute settlement with whole-step rollback.
- [x] Measure 48h in CPython then browser Pyodide; refine only if a measured failure requires it.

### Task 2: Settlement session, persistence and UI
Files: public/core/settlement_session.py, public/core/runtime_bridge.py, public/app.js, public/index.html; tests/test_settlement_session.py and lifecycle JS tests.
- [x] Test fixed target, processing-time exclusion, cancellation/reload, old snapshots, unsupported BIN and invalid policy.
- [x] Default audited R23 to custody; expose native mode in Menu with clear tradeoff and resumable progress.
- [x] Commit only actual processed time, preserving old snapshot/core identities and policy provenance.

### Task 3: Release
Files: core-config.json, release-files.json, README.md, MODIFICATIONS.md.
- [x] Independent review; fix meaningful findings and rerun affected/full checks.
- [ ] Build explicit source package, publish reviewed branch/PR, verify Pages source bytes and live restore.
- [ ] Report real measured improvement and unsupported/physical-device limits.
