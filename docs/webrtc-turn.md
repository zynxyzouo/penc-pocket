# Phone pairing with WebRTC and TURN — proposal, 2026-10-28

Status: researched design, not implemented or deployed. The published app still
has `configuredRelay = null`. A TURN URL cannot replace that JSON HTTP endpoint.

## Recommended deployment

Keep the website on GitHub Pages. Add one Cloudflare Worker with short-lived
pairing state (for example a Durable Object) and Cloudflare Realtime TURN.
Cloudflare is a proposed operator choice, not a requirement of the emulator.

1. Each phone creates a session and displays an invitation QR. The scanner joins
   the scanned session; the other phone receives the offer/answer through the
   signaling Worker. Handle simultaneous scanning by choosing one session
   deterministically; invalidate the unused invitation.
2. The Worker issues each session member temporary TURN credentials. Keep the
   TURN key and API token in Worker secrets. Authenticate membership, limit
   session creation/credential issuance, and restrict CORS to the website.
   Origin alone is not authentication. Return credentials with no-store.
3. Create an RTCPeerConnection using the returned iceServers and policy `all`.
   ICE can select a direct route or TURN relay as connectivity permits. Use an
   ordered, reliable DataChannel for the existing native connector packets.
4. The UI closes pairing only after the channel and protocol handshake succeed.
   Both players operate Battle / Jogres inside their own BIN. Do not require
   equal BIN hashes; negotiate connector protocol support. Preserve sequence,
   deduplication, bounded buffering and disconnect behavior. No host-computed
   battle outcome or fusion preview substitutes for native execution.
5. A visible connected control ends the channel, clears transient pairing state
   and signals native cable removal. Interrupted Jogres must never be silently
   retried after a page reload or applied twice.

Use a proposed 30-minute credential/session limit for the first version. End a
session visibly before expiry and allow re-pairing; longer sessions need tested
credential refresh and ICE restart behavior. Never embed long-lived TURN keys
in this public repository. TURN transports bytes; signaling still exchanges
offer/answer/ICE information. A Worker does not itself implement a TURN server.

## Backend contract to implement

- Create: return private owner token, public random invitation and expiry.
- Join: atomically reserve the second member, return private member token.
- Signal: authenticated, bounded offer/answer/ICE/leave mailbox scoped to member.
- Credentials: authenticated member only, fixed server-side TTL, issuance quota;
  call Cloudflare's generate-ice-servers API and return only short-lived values.
- Leave/expiry: invalidate invitations, notify peer and expire state. Enforce
  total body limits, two-member capacity, replay protection and global quotas.

The current `native-link.js` uses HTTP packet exchange. A separate WebRTC
transport and signaling service must be built and tested before switching it.
No firmware, save snapshots, gameplay images or game audio need to be uploaded.

## Cost and alternatives

Cloudflare currently lists TURN at USD 0.05 per GB of outbound traffic, with
1,000 GB free monthly shared by Realtime SFU and TURN. Protocol overhead counts;
the small native payload alone is not the billable size. Worker/storage costs
are separate. Set usage alerts and issuance limits before opening registration.

Alternatives are a self-hosted coturn server (requires a reachable host and
ongoing maintenance), or mutual QR offer/answer exchange with STUN/direct ICE.
Mutual QR can avoid a hosted signaling mailbox but generally needs a return
scan; it does not solve networks that require TURN. Keep the one-scan UX by
using the small signaling service above.

## Acceptance before enabling

- Two iPhones on one Wi-Fi, separate Wi-Fi and Wi-Fi versus cellular.
- Force `iceTransportPolicy: 'relay'` in a diagnostic session and inspect the
  selected candidate pair with getStats. A successful direct test proves no TURN.
- Verify native Battle and Jogres, mixed supported BIN versions, simultaneous
  scans, dropped connections, expired invitations and credential expiry.
- Confirm secret exclusion, invitation replay rejection, bounded traffic,
  background/foreground behavior and clear disconnect status in Safari.

## Official references

- [Credential generation and server-side secrets](https://developers.cloudflare.com/realtime/turn/generate-credentials/)
- [TURN billing and traffic accounting](https://developers.cloudflare.com/realtime/turn/faq/)
- [Monthly allowance and separate Worker charges](https://developers.cloudflare.com/realtime/sfu/platform/pricing/)
- [WebRTC specification: peer connections and data channels](https://www.w3.org/TR/webrtc/)
