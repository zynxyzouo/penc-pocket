# Free native relay implementation plan

> Use superpowers:executing-plans task by task.

Goal: QR native Battle/Jogres with Free quota shutdown.
Architecture: GitHub Pages + bounded HTTPS mailbox in SQLite Durable Object.
Spec: ../../cloudflare-contract.md. Tech: browser JS, Workers, SQLite, Node.

Global constraints: no ROM/save/private files published; verify Workers Free;
no TURN credential paths or paid upgrade. Preserve isolated public release.
Review focus: reciprocal scans/aliases/third peer; ACK/duplicates/cursors;
quota/timeout/stale async; native outcomes preserved; no billing-cap overclaim.

## Task1 Backend
Files cloudflare/{state,worker}.mjs,wrangler.jsonc,tests/cloudflare.test.mjs.
- [x] Failing tests: native packet mailbox, ACK, timeout, quota, reject ice.
- [x] Implement contract actions with atomic bounds and per-packet records.
- [x] node --test tests/cloudflare.test.mjs passes.

## Task2 Browser
Files public/relay-transport.js, native-link.js and associated tests.
- [x] Failing tests: validation, quota stop, generation/abort and disconnect.
- [x] Implement facade and LinkRoom terminal failures without QR/game changes.
- [x] Focused Node tests pass.

## Task3 Integration/deployment
- [x] Actual workerd SQLite tests and real browser HTTP duplex packet smoke.
- [x] Full Node/Python tests, source allowlist/build/license audit.
- [x] Independent review; resolve material findings.
- [x] Workers Free verified in dashboard; minimal deployment OAuth granted by owner.
- [x] Deploy/live test before enabling hosting endpoint for the Pages release.

Pre-flight: Task1 /api/link consumed by Task2, Task3 verifies both. Contract
response shape binding; code ownership disjoint. No local git in public tree.

Verification:79/79 Node tests,7/7 Python tests with local R23 fixture; real
workerd SQLite packet/auth/ACK/quota tests and browser HTTP smoke pass. Private
native gameplay harness using public core completed mixed R19h3/R20h4 battle
and R20 Jogres through HTTP relay,52requests; BIN files unchanged. Physical
phones not yet tested. Live Cloudflare packet/browser tests passed; native
mixed-version battle and Jogres also passed over the deployed service (48 requests).

Final review:2 Important findings fixed with RED/GREEN tests: phone wall-clock
skew now defers expiry enforcement to server; terminal failure opens a visible
notice after native disconnect. No remaining reviewer findings. Ruling: server
TTL is authoritative; client validates positive/nonincreasing stable expiry
without comparing phone clock. Bounded request failures still close transport.
