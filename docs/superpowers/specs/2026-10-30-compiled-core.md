# Compiled execution core

User approved replacing the slow interpreter with a locally authored core. Keep native BIN gameplay, UI, snapshots, QR battle/jogress and sound/motion integration. Do not import another emulator distribution. Existing reference semantics have MAME provenance; new implementation is not a clean-room licensing claim and existing notices remain.

Write a small freestanding C instruction engine compiled to Wasm. Dense checked RAM and immutable ROM live in the compiled engine. It runs whole instruction stretches; audited peripheral/call boundaries yield to the existing host adapters. Ordinary memory operations never cross into Python. Unknown instructions and invalid memory fail or fall back explicitly, without inventing behavior.

First acceptance: identical architectural state/steps, committed RAM/flash and sound events in R23 clock enter/exit and cry fixtures, and at least 20% browser transition improvement on paired runs. Keep the deployed reference intact until this gate passes. Native desktop results are not Android timing proof. Other families retain their reference backend until validated. No firmware is published.

No per-opcode trace is required in normal execution; reference mode remains available for full diagnostics. Preserve transaction failure behavior and snapshot ABI. A new compiler is a development tool, not an emulator dependency.
