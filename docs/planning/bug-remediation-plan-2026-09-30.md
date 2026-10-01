# Bug remediation plan (2026-09-30)

Owner: DJ Unicorn Tears
Status: active — owner decisions recorded 2026-09-30 (bottom); W1 teams up
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
- [x] **G1** `--effect-duration` always rejected: default `60` → `60.0`. Landed core beta.181 (UV Core; `tests/test_cli_effect_duration.py`).
  [core]
- [x] **G3** Ctrl+C crashes shutdown: guard `_audio_manager.stop()`, and
  make the helper processes ignore SIGINT (decision 4). [core] Landed core
  beta.182 (UV Core; G1 was 50b69fa). Live repro: group SIGINT, main exited
  in 1 s, mixer state saved, helper stopped code 0, no CRITICAL.
- [ ] **AV-2** Auto VJ toggled off during a pending mode snap blocks mode
  changes for the session. [auto-vj]

## Found during remediation

- [ ] **R1 (P1)** The audio helper SIGSEGVs on track loads: a use-after-unmap
  on a shared-memory segment (`remote_objects._ShmExporter`). `retire_unused()`
  unmaps a retired deck array after a 2 s grace period while a helper thread
  can still read it (numpy fancy-index read racing `munmap`). [core: UV Core]
  - Found by UV Core in the 2026-10-01 loaded-scene A/B: 2 of 4 runs, both
    interpreters.
  - Hit the owner's live sessions on 2026-09-26 13:07 and 2026-09-27 21:05.
    Both times the engine fell back in-process for the rest of the session.

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

- [ ] **W1** Bundled 3.11 breaks all mixer track loads. Decided: bundle
  **Python 3.14 free-threaded** (decision 1), which also removes the 3.13+
  `SharedMemory` break. Teams and order:
  1. [ ] **UV Threads — critical path.** *Status: Linux wheels built, verified
     and in `~/projects/_software-dist/wheelhouse/cp314t/` (see
     [free-threaded-wheels-2026-09-30.md](free-threaded-wheels-2026-09-30.md));
     Windows wheels await an owner decision on how to build them.* No moderngl or glcontext wheels
     exist for 3.14 at all, and python-rtmidi has no `cp314t` wheel.
     - Build and bundle our own `cp314t` wheels for all three, Linux and
       Windows.
     - Add a startup check that logs when an unmarked extension turns the
       GIL back on (§6 of
       [free-threaded-python-2026-09-24.md](free-threaded-python-2026-09-24.md)).
     - The main process runs with the GIL on until moderngl is ported.
       That's expected, not a regression.
  2. [ ] **UV Install.** *Status (core beta.185): Linux done; Windows waits
     on the GitHub Actions wheel job. Details, the per-dependency table and
     the next steps are in the 2026-09-30 entry of
     [installers.md](installers.md).*
     - [x] `fetch_runtime.sh --flavor ft`: PBS 20260929 / CPython 3.14.7
       free-threaded, digests pinned, a missing checksum is now fatal.
     - [x] Install the UV Threads wheels (Linux): `stage_payload.sh` stages a
       verified `wheelhouse/`, every installer uses it; ft is chosen when a
       wheelhouse exists.
     - [x] **W2** drop-in dependencies installed by every installer (tolerant
       per-file/per-line, mediapipe `--no-deps`). PowerShell side untested.
     - [ ] Windows: GH Actions job for the cp314t wheels, then flip
       `build_windows_portable.sh` to `ft`. Fallback: 3.13 GIL interim.
     - [ ] Linux clean-install check: app launch + mixer track load.
  3. [ ] **UV Core.**
     - [x] Audio process on 3.14t: runs with the GIL off; core and mixer
       helper tests pass on it; the whole app runs on 3.14t with the UV
       Threads wheels (core beta.183; notes in
       [free-threaded-python-2026-09-24.md](free-threaded-python-2026-09-24.md) §8).
     - [x] GIL-status line in both processes (core beta.183).
     - [x] cv2 optional in core (beta.184): `--self-test` warns instead of
       failing. Drop-in follow-ups, in their own repos: webcam-01 logs the
       missing cv2 at ERROR (should be one WARNING); video-clips-01 warns per
       clip on every activation.
     - [ ] Dev `.venv` (plain 3.14.6 today) to 3.14t: parallel venv built at
       `~/Repos/unicorn-viz.venv-ft`, switch-over plan accepted (build in
       place, symlink flip, rollback by repointing), **not swapped.**
       Readiness gates: (1) 3.14t suite done, 2790 pass / 2 explained;
       (3) symlink and hook chain done in a scratch copy; **(2) the A/B is
       outstanding** and needs an idle machine
       (`tools/profiling/ft_ab/drive.sh`). Details in
       [free-threaded-python-2026-09-24.md](free-threaded-python-2026-09-24.md) §8.
     - Confirm `remote_objects` and the audio process under it. This is
       where free-threading pays off first: numpy, scipy, cffi and PyAV are
       all ready.
  4. [ ] **Drop-in owners, later — smoke test on the bundled build:**
     - mixer (PyAV, mutagen, demucs path);
     - media and videos (python-vlc, PyAV);
     - webcam (lazy mediapipe and cv2 imports; mediapipe unverified on 3.14t);
     - sims (usd-core has no `t` build, so the USD scene needs a fallback).
- [x] **W2** Installers skip drop-in dependencies. [installer] Landed core beta.185 (Linux verified; PowerShell untested; demucs still blocked on sphn for 3.14t).
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
  - H3: "MIDI disabled" still drives the APC. Fix: no libusb claim and no
    injected pad actions unless the configured device is the APC (decision
    3). Choosing the APC mid-session must claim libusb before opening its
    MIDI ports.
  - H4: dead APC faders. Route through the app-wide `vj_api` setters,
    alphabetically: 48 hue, 49 reactivity, 50 rotation, 51 speed, 52 zoom.
    Leave 53–56 unbound until the owner's mapping session with the APC team
    (decision 2). Going through `set_speed` also fixes E1 on the MIDI path.
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

## Owner decisions (recorded 2026-09-30)

1. **W1:** bundle **Python 3.14 free-threaded**. Teams: UV Install, UV
   Threads, UV Core; the drop-in owners come up later (see W1 above).
   - **Windows** (recorded later the same day): build the cp314t Windows
     wheels on **GitHub Actions** (a windows-2022 job, owned by UV Install;
     build scripts by UV Threads). This approval covers this build only. If
     it fails, fall back to a Windows **3.13 (GIL)** interim. Every
     dependency has a cp313 Windows wheel except python-rtmidi.
   - **Wheels for CI-built artifacts** (2026-10-01): publish the cp314t
     wheels as a **GitHub release asset** under a dedicated non-version tag.
     The installer-building workflows fetch them and verify them against a
     SHA256SUMS committed in the repo. UV Install owns it. The approval
     covers that release and the fetch step only. Until it lands,
     CI-built tarball/rpm/deb artifacts still install the 3.11 runtime.
   - **Stems on 3.14t:** the only gap is **sphn** (no cp314t wheel; torch and
     torchaudio have them). UV Threads builds it.
2. **H4:** APC faders drive the app-wide tweakables in alphabetical order,
   as long as they work. The final default mapping will be redone from
   scratch in a session with the APC team.
3. **H3:** "MIDI disabled" fully releases the APC.
4. **G3:** the helper processes ignore SIGINT, and the main app stops them
   in order after saving state. This was the agent's recommendation, recorded at
   the owner's request. The helpers already exit on their own when the
   parent's pipe closes (`remote_objects.py:518-519`), so there's no orphan
   risk.

Waves 1–3 carry most of the live-set risk. Waves 5 and 6 are the bulk of the
effort.
