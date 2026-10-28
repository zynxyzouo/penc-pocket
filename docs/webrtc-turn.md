# WebRTC/TURN alternative — not used

A WebRTC direct/DataChannel plus Cloudflare TURN prototype was considered.
The user requires service to stop at the free allowance without overage charges.
TURN usage alerts do not provide that hard cap, so the prototype is not shipped.

Current implementation relays small native packets over HTTPS using Workers Free
and SQLite Durable Objects Free. See [cloudflare-contract.md](cloudflare-contract.md)
and [cloudflare-setup.md](cloudflare-setup.md). It has no TURN credentials or ICE
endpoint. QR still pairs two devices and gameplay stays in the BIN.

A future WebRTC option would require separate agreement on costs, NAT traversal,
credential security and real relay-route verification. It is not an automatic
fallback when the current free service reaches quota.
