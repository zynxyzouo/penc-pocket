# Native link relay

GitHub Pages is static. The optional backend is a Cloudflare Workers Free and
SQLite Durable Object service, with /api/link create,pair,exchange,leave.
Current authoritative wire protocol: [cloudflare-contract.md](cloudflare-contract.md).
Deployment steps and Free-plan boundary: [cloudflare-setup.md](cloudflare-setup.md).

The old private platform relay and unpublished WebRTC/TURN prototype are not
runtime dependencies. Browser RelayTransport preserves native connector packet
semantics. Pairing closes the QR overlay, then players choose BATTLE or JOGRES
in their own game. Different BIN hashes are allowed when transport hashes match.

No backend-calculated battle or fusion preview. No firmware/save uploads. Public
QR invitation is not the private device authentication token. Quota exhaustion
ends the connection with no paid fallback. Real-phone gameplay testing remains
necessary even after desktop transport tests pass.
