# Modifications — 2026-10-28

- PenC Pocket contains a Python adaptation of selected MAME 0.289 unSP
  instruction behavior, explicit peripheral/host adapters and a browser UI.
  This is not an official MAME release or a full hardware implementation.
- This public release adds GPL notices to the core. No executable Python AST
  changed. Per-file download hashes are refreshed; snapshot ABI identifiers
  remain compatible with the prior implementation.
- The original browser integration used a private authenticated relay.
  Static hosting defaults to no relay, with a visible unavailable state and
  no background pairing attempts. QR links preserve the hosting subpath.
- Profiles r19h3/r20h4 omit only `r16h.art` and `r16h.base_path`, unused local
  build metadata. `public/profile-migrations.js` records the exact admitted
  hash transition. Only that transition is allowed before normal restore
  validation; firmware/core identities and saved state are not rewritten.
- jsQR 1.4.0 is wrapped as an ES module. QR decoding logic is unchanged.
  The dated packaging notice is in its browser file and regeneration tool.
- The source package is explicitly inventoried, carries no earlier Git
  history, and accompanies every deployment. Vendor sources retain original
  licenses. Unused React/Vinext/Sites framework code is not in this release.
