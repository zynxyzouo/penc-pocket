# Modifications — 2026-10-28

- Homepage startup now loads the last locally remembered BIN through the existing
  profile/hash and snapshot validation path. Gameplay remains paused until a tap;
  loading locks input and exposes recoverable errors without replacing bad saves.
  No firmware distribution or download was added.
- PenC Pocket contains a Python adaptation of selected MAME 0.289 unSP
  instruction behavior, explicit peripheral/host adapters and a browser UI.
  This is not an official MAME release or a full hardware implementation.
- The initial public release added GPL notices without executable Python AST
  changes. The subsequent R23 update admits one additional exact BIN hash in
  boot, native settings, away catch-up and sound snapshot guards, after checking
  their unchanged native regions. CPU instructions and snapshot schemas remain
  unchanged; per-file download hashes are refreshed.
- R23 replaces the bundled r18/r19/r20/r19h3/r20h4 profiles. TEST4 and DMC remain.
  Older adapter admissions and stored-profile migration records are retained for
  existing local saves; no user BIN or saved state is deleted or converted to R23.
- The original browser integration used a private authenticated relay.
  Static hosting retains a null-endpoint unavailable state, with no background
  pairing attempts. QR links preserve the hosting subpath.
- Cloudflare Free deployment adds authenticated QR pairing and native packet
  mailboxes in a SQLite Durable Object. Peer acknowledgements, bounded retries,
  quotas, expiry and disconnect are explicit. Different firmware may pair with
  matching native transport hashes. The unpublished TURN prototype is omitted;
  there is no credential issuance or paid fallback. The verified Free endpoint
  is enabled after live packet, browser and native gameplay tests on 2026-10-28.
  No game core behavior changed. Physical iPhone-to-iPhone testing remains open.
- Previously bundled profiles r19h3/r20h4 omitted only `r16h.art` and `r16h.base_path`, unused local
  build metadata. `public/profile-migrations.js` records the exact admitted
  hash transition. Only that transition is allowed before normal restore
  validation; firmware/core identities and saved state are not rewritten.
- jsQR 1.4.0 is wrapped as an ES module. QR decoding logic is unchanged.
  The dated packaging notice is in its browser file and regeneration tool.
- The source package is explicitly inventoried, carries no earlier Git
  history, and accompanies every deployment. Vendor sources retain original
  licenses. Unused React/Vinext/Sites framework code is not in this release.
