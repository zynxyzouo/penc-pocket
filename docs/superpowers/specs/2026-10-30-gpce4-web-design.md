# GPCE4 reset-boot web integration

User intent: connect the new local `gpce4_machine` full-machine core to the existing phone website, preserving its real internal-ROM boot, LCD and keys. The user has already authorized C/Wasm conversion and website integration; implementation mechanics proceed without another approval loop.

Approaches: embedding Python directly is 10-30x below real time; replacing the default core would remove working sound/link/custody; a selectable full-machine C/Wasm experiment is the chosen implementation decision. Existing mode remains the default. Add a Menu entry opening `machine.html` on the same site, reusing the handheld layout and orientation support.

Port the supplied CPU and SoC semantics, including IRQ/timers/SPI/LCD. Do not introduce HLE firmware entry points. Keep guessed 12M instructions/s, 48MHz timer clock and ADC values explicitly experimental. User supplies an 8MiB firmware and 96KiB PenC internal ROM locally; no ROMs or artwork enter release artifacts or network requests. DMC is not supported by the available PenC internal ROM.

Provide start/pause, held ABC, landscape, local remembering, isolated exact-machine snapshots, export/import, and modified Flash export. Existing saves remain separate and are not silently migrated. Full-machine sound, motion, cable/QR and offline custody are unavailable and clearly indicated; machine pauses while away. Do not falsely advertise them as integrated.

Acceptance: C/native CPU comparisons including IRQ/RETI; Python-vs-Wasm reset-boot, RAM/LCD/Flash equivalence at fixed virtual instruction times; valid snapshot deterministic resume and mismatched/corrupt rejection; browser upload/boot/key/save/reload smoke; measured browser speed without claiming phone real-time until measured. Publish only code + compiled artifact with existing GPL and MAME BSD notices, after review. Keep the old default untouched.
