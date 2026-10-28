# PenC Pocket public release

Approved direction (2026-10-28): publish the emulator's modifiable source, its
license notices and a matching GitHub Pages build; do not publish firmware,
game assets, firmware disassembly, local data, credentials or old research history.

The existing Sites project is the reference and stays separate. This directory
is a fresh source tree with an explicit file inventory. The browser application
is ordinary HTML/CSS/JavaScript plus a Python core loaded through Pyodide.
It needs no React/Vinext build for static hosting. First-party integration is
GPL-3.0-or-later; vendor licenses retain their original scope.

GitHub Pages cannot host the existing authenticated relay. Keep native-link
client code and document the protocol, but disable pairing until an operator
configures a compatible relay. Do not silently use the private Sites endpoint.
QR URLs must preserve a project subpath. No hosted relay is promised by this release.

Source distributions accompany every static build through a same-version zip
linked from Menu. The source includes build scripts, pinned vendor sources,
notices and tests. Public profiles exclude unused private build paths. Keep
snapshot ABI identities; permit only explicitly audited metadata-only profile
migrations. BIN/profile and core validation remain in place.

Alternatives: uploading the old Git history risks exposing research files;
publishing only a compiled website omits corresponding source. A fresh,
allowlisted source tree addresses both. GitHub publication requires a connected
account; prepare and validate locally while connection is pending.
