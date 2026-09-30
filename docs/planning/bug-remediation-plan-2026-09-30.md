# Bug remediation plan (2026-09-30)

Owner: DJ Unicorn Tears
Status: proposed — awaiting owner read-through; four decisions open (bottom)
Last updated: 2026-09-30

This is the working checklist for the 134 findings (14 P1) in the six
2026-09-30 audits. Tick an item in the same commit that lands its fix, and
add the short hash.

| Tag | Audit |
|---|---|
| `B` | [bug audit](../audits/2026-09-30-bug-audit.md) (P1-*, P2-*, P3-*) |
| `AV` | [Auto VJ director + recommender](../audits/2026-09-30-auto-vj-director-recommender-audit.md) |
| `W` | [Windows](../audits/2026-09-30-windows-bug-audit.md) |
| `U` | [UI files](../audits/2026-09-30-ui-files-bug-audit.md) |
| `E` | [effects + cameras](../audits/2026-09-30-effects-and-cameras-bug-audit.md) |
| `H` / `G` | [hardware + GPU run](../audits/2026-09-30-hardware-and-gpu-run-bug-audit.md) |

## Ground rules

1. **Test first.** The suites were green through every one of these bugs.
   - Each fix starts by turning its repro into a regression test that fails
     before the fix and passes after.
   - The repros are in `/var/tmp/uv-bug-audit/`. That's outside the repo, so
     copy what you need.
2. **The owning seat fixes it.** In the lists below, owners are in brackets:
   core, mixer (dj-mixer-01), auto-vj, midi (midi-controllers-01), effects,
   media (media / videos / streaming / spotify / lyrics / webcam drop-ins),
   installer.
   - Core changes that touch MIDI need owner approval first.
   - Installer work belongs to the installer team.
3. **Fix by root cause.** Where one fix covers several IDs, they are listed
   together. Close them together.
4. **Normal landing discipline.** Version bump and changelog line per
   component. Update the ADR or weights doc where CLAUDE.md requires it.

## Wave 1 — one-liner and near-one-liner P1/P2s

- [ ] **H13** REV1 LEDs dead since 09-24: move `on_scratch_mode` out of the
  LED `try` and poll scratch mode on the main side. [mixer]
- [ ] **G1** `--effect-duration` always rejected: default `60` → `60.0`.
  [core]
- [ ] **G3** Ctrl+C crashes shutdown: guard `_audio_manager.stop()`.
  Helpers ignoring SIGINT waits on decision 4. [core]
- [ ] **AV-2** Auto VJ toggled off during a pending mode snap blocks mode
  changes for the session. [auto-vj]

## Wave 2 — show-breakers

- [ ] **U1** Mixer-only boot profile takes no input. [mixer + core]
- [ ] **B P1-1** Ping-pong pinning leaks effect instances. [core + auto-vj]
- [ ] **B P1-2, B P1-3** Recording/streaming stop blocks, or hangs, the
  render thread. Move `stop()` and faststart off the main thread, and bound
  `stdin.close()`. [core + media]
- [ ] **E5** Camera probe (242 ms+) on the render thread. [media]
- [ ] **H1 + H2 + H14** Controller reconnect after a USB blip:
  - keep the device hint on failure;
  - retry aux devices;
  - libusb reader exits on error and reopens;
  - clean libusb release (device reset) so the APC keeps its kernel
    driver.
  [core + midi + mixer]

## Wave 3 — data safety

- [ ] **B P1-6** An unreadable `global_state.json` / `config_profiles.json`
  is replaced with an empty store. Quarantine the bad file and keep going
  read-only. [core]
- [ ] **U6** Backup restore undone by the next store save. [mixer]
- [ ] **B P2-1** `set_override()` mutates `_DEFAULTS` and the parsed config.
  [core]
- [ ] **G3 (rest)** Every teardown step guarded, so the runtime-state save
  always runs. [core]

## Wave 4 — crash isolation

One rule: no drop-in call or worker thread can take down the main loop or
silently die.

- [ ] **B P1-4** Config-editor keys, MIDI dispatch, render-phase drop-in
  calls, first-effect construction. [core]
- [ ] **B P1-5** Analysis thread exception guard. [core]
- [ ] **B P2-5** Esc during the splash double-frees SDL/GL. [core]
- [ ] **B P2-10** Audio source switch on two threads without a lock. [core]
- [ ] **B P2-6** libvlc volume set from a worker thread. [media]

## Wave 5 — installed builds (Windows and everywhere)

- [ ] **W1** Bundled 3.11 breaks all mixer track loads. The approach waits
  on decision 1. [core + installer]
- [ ] **W2** Installers skip drop-in dependencies. [installer]
- [ ] **W3** No WASAPI loopback, so Windows visualizes the microphone.
  [core]
- [ ] **W4** Mixer output device names ambiguous across Windows host APIs.
  [mixer]
- [ ] **W5–W12** Windows P2s: monotonic clock resolution, `pythonw`
  crashes and console windows, backslash paths, English-only device lookup,
  Stereo Mix refusal, `xdg-open`, lyrics hub. [core / mixer / media]

## Wave 6 — effects, as bulk fixes

- [ ] **E1** Speed-change phase continuity: one helper, five call sites, 34
  effects. [core]
- [ ] **E2** Float32 hash collapse: `mod` inside each hash function, 14
  effects. [effects]
- [ ] **E4** Wrapped phases pop: pick periods per consumer, 20 effects.
  [effects]
- [ ] **E3 = B P2-8** Class A `iTime × audio`: CPU-integrated phases, ~24
  sites. [effects]
- [ ] **E6** Frogger invisible logs. [effects]

## Wave 7 — remaining P2s, grouped by owner

- [ ] **Auto VJ:** AV-1 (P1, decider never leaves a prefilter-excluded
  profile), AV-3 … AV-9. [auto-vj]
- [ ] **Hardware:**
  - H3: "MIDI disabled" still drives the APC; waits on decision 3.
  - H4: dead APC faders; waits on decision 2.
  [midi]
- [ ] **Mixer UI:** U3 (quantized ROLL/TRANS tap sticks, also REV1), U4,
  U5, U7. [mixer]
- [ ] **Overlays:** U2 (non-ASCII glyphs, audience-visible), U8. [core]
- [ ] **Core:**
  - B P2-3: blocksize truncates the FFT;
  - B P2-4: frame overlays redraw the outgoing effect during a
    transition;
  - B P2-7: rebinding leaves the old key live.
  [core]
- [ ] **Media:**
  - B P2-2: videos-01 seek past EOF spins;
  - B P2-9: spotify 401 never refreshes.
  [media]

## Wave 8 — P3 sweep, batched per file

- [ ] **Bug audit:** B P3-1 … P3-14.
- [ ] **Auto VJ:** AV-10 … AV-18.
- [ ] **Windows:** W13 … W24.
- [ ] **UI files:** U9 … U24. U17 (platter ring off-grid) shares a fix
  with H7.
- [ ] **Effects:** E7 … E20.
- [ ] **Hardware / GPU run:** H5 … H12, G2, G4.

## Owner decisions needed

1. **W1:** raise the bundled Python to 3.13+, or rewrite the audio process
   for 3.11? Separately, may the pre-push hook add a 3.11 test run? That's
   an infrastructure change.
2. **H4:** what should the dead APC faders control? Master or mixer volume,
   PostFX mix, zoom, something else.
3. **H3:** should "MIDI disabled" fully release the APC (no libusb claim,
   no pad actions)?
4. **G3:** should the helper processes ignore SIGINT and let the main app
   stop them?

Waves 1–3 carry most of the live-set risk. Waves 5 and 6 are the bulk of the
effort.
