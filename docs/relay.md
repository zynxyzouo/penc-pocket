# Optional native-link relay

This release does not operate a relay. `configuredRelay = null` is intentional.
GitHub Pages cannot execute a POST endpoint or store transient sessions.
The previous host's identity headers and D1 database are not portable.

`public/native-link.js` defines the JSON client contract. POST requests contain
`action`, an unguessable 32-byte hex session `token`, optional session `code`,
and action-specific fields. Actions: create, pair, exchange, leave.
Create/pair include `profile`; pair also includes peer's 8-character code.
Exchange includes `received` and up to 16 outbound packets. Responses contain
`code`, `slot`, `connected`, `closed`, `accepted` and `packets` as applicable.
The emulator's `public/core/native_connector.py` validates sequence and payloads.

A compatible service must authenticate session ownership, validate profile and
packet shapes, ensure ordered/idempotent delivery, limit message/body/session
sizes and request rates, expire abandoned sessions, support leave/closure, and
return explicit errors (400/401/403/404/409 etc.). Never treat Origin as identity.
For cross-origin hosting, support OPTIONS and an explicit allowed website origin
with Content-Type application/json. The public client uses credentials: omit;
it never forwards browser cookies or exposes an operator secret.

The pairing code is an invitation, not a login credential. The random token is
kept only in memory and never encoded in the QR URL. QR contains only the same
site's app path and `#link=CODE`. A real deployment must be tested with two
phones, including simultaneous pairing, retries and disconnect races.
Do not enable the UI merely because an endpoint URL has been entered.
