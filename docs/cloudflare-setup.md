# Cloudflare Free deployment

Status: deployed and live verified on 2026-10-28; the release config enables
https://penc-pocket-pairing.penc-pocket-deploy-tools.workers.dev/api/link.
The account dashboard showed Workers Free, US$0, current plan immediately
before deployment. Verify again before future deployments or account moves.

## Billing boundary

Use Workers Free and SQLite Durable Objects Free only. Free-limit exhaustion
causes failed requests/operations. Do not upgrade Workers to Paid. The app's own
quotas reduce usage but cannot guarantee zero bills on a Paid account. Cloudflare
Realtime TURN has no verified hard spending cap and is not used here. No TURN
key, credential API, ICE configuration or fallback is included. An existing
Realtime subscription is separate and is not cancelled by this source change.

## Deploy

Use official Wrangler4.154.0 from a separate tooling folder; no npm application
runtime dependencies. Keep logs/auth/local state/generated bundles outside this
release source tree. Build rejects .wrangler, .dev.vars and unlisted files.

1. Confirm Workers Free in the account dashboard. Never click Upgrade.
2. Authenticate Wrangler with account:read user:read workers_scripts:write
   and offline_access for the approved persistent login.
   The account owner must approve the actual new OAuth access grant. No zone,
   KV,R2 or account-administration write scopes are needed.
3. Review cloudflare/wrangler.jsonc: SQLite DO, no observability body logs,
   exact frontend origins. Production needs https://zynxyzouo.github.io only;
   localhost is for controlled QA and can be removed for public operation.
4. Deploy using the config and intended account. Use absolute dry-run outdir
   outside the release tree; archive generated .wrangler state outside it.
   No secrets or paid-service bindings are required.
5. Live verify health, CORS, membership, reciprocal pairing, native-size duplex
   packets, peer ACK, quota failure and leave. No invented game outcome.
6. Set public/hosting.js configuredRelay to the verified HTTPS /api/link URL,
   rebuild, publish source with Pages, then test two actual iPhones.

## Limits and behavior

Default app cap8000 API requests per UTC day, shared by all testers; at350ms
polling, at most about23 minutes of aggregate paired time, less with retries
and setup. Polling does not run during ordinary single-player use. Additional
limits:600requests/IP/min,10invitations/IP/hour,20/IP/day,500global/day,512packets
per member,8uint16 per packet,16packets/request,8KiB/request,30minute lifetime.
Paired peers absent over20seconds close on the next request. Quota or platform
errors stop the native link visibly; users explicitly re-pair after recovery.
UTC midnight is08:00 in Taiwan. Other Free resources on this account share
platform quotas and can make the service unavailable earlier.

Tokens remain in memory on the phone and hashed server-side; QR has only public
invitation. Server receives the native connection words and profile hashes,
not the BIN, save, sprites or audio. Transient records expire and are deleted.

## Verify locally

Live verification completed: health, strict CORS, reciprocal pairing, mixed
firmware, ownership authentication, duplex native-size packets, peer ACK,
duplicates, invalid ACK rejection and leave. Browser RelayTransport also passed
cross-origin HTTP tests. The public core ran unchanged private R19h3/R20h4 BINs
through a native battle and R20/R20 through native Jogres over this live service
(48 requests). Battle updated native DP/results; Jogres evolved the selected pet
while preserving the other. No BIN/save bytes were sent or published. Quota
exhaustion was tested in isolated local workerd, not by draining production.
These are desktop tests; two physical iPhones and complete lifecycle remain open.

Run Node/Python tests and python tools/build.py. Optional actual runtime test:
node tools/test_worker_runtime.mjs. Set PENC_MINIFLARE_MODULE to installed
Miniflare's file URL when using a separate tools directory. Wrangler4.154.0
provides convertV4MiniflareOptions. Local browser QA:
node tools/serve_relay_smoke.mjs at http://127.0.0.1:8766/. This uses workerd
SQLite with external network forbidden and a separate quota-limited instance.
It does not establish live Cloudflare, actual game or physical phone success.

## References

- [Workers Free limits](https://developers.cloudflare.com/workers/platform/limits/)
- [Durable Objects pricing and Free exhaustion](https://developers.cloudflare.com/durable-objects/platform/pricing/)
- [Budget alerts do not cap spend](https://developers.cloudflare.com/billing/manage/budget-alerts/)
