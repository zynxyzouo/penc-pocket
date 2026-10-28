# PenC Pocket Public Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** Deliver a clean licensed source release and matching GitHub Pages artifact.
**Architecture:** Fresh allowlisted source tree, buildless browser code, Python-standard-library packaging, local source zip per deployment.
**Tech Stack:** HTML/CSS/JS, Python 3.12, Pyodide 0.27.7, GitHub Actions.
**Spec:** `docs/release-design.md`

## Global Constraints
- No BIN, decoded assets, disassembly, user saves, credentials, Sites identity or old Git history.
- Preserve emulator behavior and snapshot ABI identities.
- GPL-3.0-or-later for first-party integration; preserve vendor licenses.
- No pairing requests when relay endpoint is absent.
- Every deployable artifact includes its exact modifiable source.

## Review Focus
- Project subpath URLs must not fall back to domain root or accept another app's invite.
- Metadata sanitation must not invalidate exported legacy saves without an explicit safe migration.
- Missing relay must not trigger network requests or alter running game state.
- Packaging must reject symlinks, unlisted files and private paths.
- License and source downloads must be present in the final deployed artifact.

### Task 1: Curate source and notices
- [ ] Copy explicit browser/core/profile files into the fresh tree.
- [ ] Add GPL3 text, upstream notices and modification headers; sanitize unused profile paths.
- [ ] Retain pinned vendor preferred sources/build metadata and document CDN runtime.

### Task 2: Static hosting compatibility
- [ ] Test QR project paths, disabled relay and bounded profile migration (expect failures first).
- [ ] Implement `public/hosting.js`, project-path QR handling, `public/profile-compat.js` and client integration.
- [ ] Run Node tests; verify core ASTs unchanged and hash pins correct.

### Task 3: Reproducible public artifacts
- [ ] Implement `tools/build.py` with explicit inventory, integrity metadata and matching source zip.
- [ ] Add README, GitHub Pages workflow, notices/source Menu links and release verification.
- [ ] Build twice and compare outputs; inspect archives and source download.
- [ ] Preview the built artifact under a project subpath; obtain independent review.

### Task 4: Publication
- [ ] Confirm GitHub connection, create a fresh public repository and publish only verified content.
- [ ] Enable Pages and verify deployment, or report precise account-access blocker with local artifacts.
