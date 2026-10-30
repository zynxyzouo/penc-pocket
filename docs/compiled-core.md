# Compiled instruction backend

The locally written `src/pocket_cpu.c` executes selected unSP instructions directly
as WebAssembly. It links no MAME or third-party emulator core. Its compatibility
contract was developed against the existing Python reference, whose instruction
semantics include MAME provenance. This is **not** a clean-room rewrite or a
removal of GPL/third-party obligations. All existing notices remain.

This release uses a hybrid backend: short native entries use the decoded Python
path; entries whose previous invocation exceeded 4096 instructions use the C
engine. Work estimates reset when the ROM identity changes. It changes execution
cost, not game time, BIN bytes, instruction budgets or native gameplay rules.
Stock TEST4 and DMC retain their existing family backends.

The C loop uses checked dense memory and transactional instruction commits.
Unknown instructions, peripheral operations and stateful internal-ROM calls
yield before mutation to one reference instruction. Audited pure 32-bit arithmetic
adapters stay in C. Audio, motion and native cable hooks remain in the host.
The five snapshot identity files and ABI IDs are unchanged.

Import `compiled_cpu` only during pristine, hash-checked Worker bootstrap, before
installing instrumentation. Its method/descriptor guard detects later changes;
it is not a security boundary against pre-bootstrap code replacement. Custom CPU
subclasses, unsupported host arguments and reentrant calls keep the reference path.
Normal compiled mode retains call history but records only host-boundary instruction
traces. Open the website with `?core=reference` for full instruction diagnostics.

## Rebuild and verify

Install Zig **0.15.2** from https://ziglang.org/download/ and place `zig` on PATH,
or set `POCKET_ZIG` to its executable. The build uses Zig's Clang C frontend;
the compiler is a development tool and is not shipped in the website.

```
python tools/build-core.py --native
python tools/update_integrity.py
node --test tests/compiled-engine.test.mjs
python -B -m unittest discover -s tests -p 'test_compiled*.py'
python tools/build.py
```

The native library is optional and lives in ignored `build/`. Set
`POCKET_NATIVE_CORE` to test a library built elsewhere. Set `PENC_R23_BIN` to a
local lawful R23 file to run firmware integration tests; it is never included in
the package. Without a native library those optional Python tests report skips;
Node always executes the actual distributed Wasm bytes.

The Wasm is stored as ASCII base64 (`public/core/pocket_cpu.wasm.b64`) so the
existing text-only publication/source inventory can carry it. The Worker decodes
it and checks SHA-256 of the binary before instantiation. The full C source and
build recipe are included in the matching source archive.

Desktop browser measurements are not Android or physical-device timing proof.
