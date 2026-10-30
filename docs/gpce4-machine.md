# Optional GPCE4 full-machine mode

Open Menu -> full-machine experiment (`machine.html`). Supply a local 8 MiB
PenC firmware and the verified 96 KiB internal-ROM dump. Neither image is shipped
or uploaded. The internal-ROM hash is pinned in `public/machine-config.json`.
The known dump is for Pendulum Color; it is not Digimon Color's internal ROM.

This mode is a C/Wasm port of the supplied Python GPCE4 reset-boot model. It
executes the real ROM vector and firmware, IRQs/RETI, banked Flash, SPI, LCD and
ABC GPIO. Hash-admitted packet and motion peripheral wrappers connect host input
to native gameplay; this is not physical wire/sensor timing emulation. It does
not require Pyodide. The former hybrid mode remains the default.

The model still assumes 12,000,000 instructions per second and a 48 MHz timer
source plus an estimated battery ADC value. Instruction counts are not measured
processor cycles. Physical timing and complete hardware compatibility are not
established by successful boot.

Masked input and enabled peripheral events wake the native sleep routine even
when CPU interrupt delivery is disabled. Sound observes accepted firmware calls;
the internal ROM still completes its busy state. Browser synthesis keeps the
user's +48 semitone/2x listening calibration, not a measured speaker waveform.
Motion supplies a short-lived native sensor latch. QR pairing transports eight
native words; compatible firmware versions may differ. Native Battle/Jogres
validation, results, animation, DP and Flash writes are unchanged. Disconnect
uses native cancel or preserves already-settled animation, then saves locally.

R23 custody is enabled by default. On resume it synchronizes at the native UI
entry, wakes verified HOME sleep, and settles growth/sleep events with bounded
native calls and countdown jumps. No new care mistakes are accumulated. Existing
illness/injury, unsupported firmware and other active menus remain frozen for
that absence. The page does not execute in the background while closed. Failed
transactions restore their CPU/RAM/Flash checkpoint and clear pending inputs.
The small exterior clock shows elapsed virtual execution, not the game's RTC.
The game's own clock is displayed by the firmware on its LCD.

Snapshots include CPU, RAM, LCD, peripheral transaction and timer state plus
modified Flash sectors. They are bound to the exact firmware, internal ROM and
compiled core hashes. Only the explicitly known preceding ABI v1 core is migrated;
the original save and a migration backup are retained. Other core changes fail
closed. They use separate storage keys and do not import or replace
the default mode's snapshots. Restore is prepared in a new instance and validated
before becoming active. A native Flash export is a copy of current Flash bytes;
it is not a guarantee that flashing physical hardware is safe or that all game
data has been committed by the firmware yet.

Build with official Zig 0.15.2 via `POCKET_ZIG` or PATH:

```
python tools/build-gpce4.py --native
python tools/update_integrity.py
node --test tests/gpce4-engine.test.mjs tests/machine-ui.test.mjs
python -B tests/gpce4_soc_test.py
python -B tests/gpce4_host_test.py
python -B tests/gpce4_cpu_test.py
python tools/build.py
```

The source download contains the C port and unmodified Python reference under
`reference/gpce4/`. Tests can use that reference with no proprietary ROM. Real-ROM
boot tests are local-only evidence and are not distributed with game data.

Optional private integration tests use `PENC_R23_BIN`, `PENC_INTERNAL_ROM` and
`PENC_GPCE4_SNAPSHOT` (a healthy clock-setup snapshot); audio/motion use
`PENC_AUDIO_BIN` and `PENC_AUDIO_IROM`. Public CI explicitly skips missing private
fixtures. Local evidence covers native hatching, HOME sleep/wake, two-day custody,
R23/R20 Battle/Jogres, cold Flash reload, and animation snapshot continuation.
Physical iPhone/Android sensor, audio and performance acceptance remains separate.
