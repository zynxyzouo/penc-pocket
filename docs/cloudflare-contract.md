# Free native relay contract — 2026-10-28

User selected Workers Free packet relay instead of paid TURN and asked to try.
Verify account Workers Free before deployment. No TURN keys, ice endpoint, paid
plan upgrade or external credential fetch. Keep QR and native Battle/Jogres.

POST /api/link JSON: action, token (private 64 lower hex), code (null create).
- create: profile {firmware,transport}, both sha256. Idempotent for same token.
- pair: peer code, profile. Authenticate own room, merge into lexical smaller
  code; identity-bound aliases. Reciprocal scans safe, third phone forbidden.
  Same transport required; different firmware permitted.
- exchange: received integer 0..512, packets <=16 {seq,words}. seq 1..512,
  contiguous, eight uint16 words. Exact retry safe; changed retry rejected.
  received cannot decrease or exceed peer stored sends. Store each packet row.
- leave: idempotently close both members and aliases.
Response {code,slot,expires,connected,closed,peerProfile,accepted,packets}.
accepted = OTHER member received cursor, never just server receipt. packets
up to16 peer packets after own received. Unpaired: no send; closed: no packets.

30 minute lifetime from earlier invitation; paired peer absent over20 seconds
closes on next request. Body8KiB. Error JSON {error}, statuses400/403/404/409/413/
429/503. Exact Origin CORS, POST only, preflight600s. Token hashes, no logs of
bodies, no BIN/save upload. SQLite DO serializes. Per-IP600 requests/minute,
creation10/hour20/day500 global/day. Global requests8000/day, server enforced.
Free-plan platform quota is billing boundary, not these app limits on Paid.

RelayTransport({endpoint,fetchImpl=fetch,now=Date.now}) implements request(action,
fields={},session), synchronous close(). Validate bounded responses, identity,
slot, peer transport, seq/ACK continuity. Fetch.call(globalThis) for Safari,
8s timeout, generation/abort prevents old response revival. Best-effort leave
works after close. Quota429,503/1027, auth/expiry/protocol errors terminal; show
reason and disconnect native engine. Network retries bounded; no re-pair or
replay. LinkRoom polls350ms only during linking; engine pauses native link wait.

Builder choice: HTTPS polling reuses connector; WebSocket optimization deferred.
8000 requests is at most23 minutes total paired time/day, less setup/retries.
This conservative trial has limited free capacity. No claim of real iPhone
validation from desktop tests. Actual game determines battle/fusion outcomes.
