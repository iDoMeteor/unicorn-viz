# Deferred Work Register (2026-06-18)

Owner: Studio Documentation
Status: active
Last updated: 2026-07-18

This document tracks intentionally deferred engineering work that is
acknowledged and scheduled for a later dedicated batch.

## Deferred Items

### DW-001 — Frame-Budget CI Guard

Source:

- [Full system audit (2026-06-17)](../audits/2026-06-17-full-system-audit.md)

Status:

- Deferred by owner direction on 2026-06-18.

What is deferred:

- A CI-enforced frame-budget benchmark that fails when median frame time
  exceeds 16.67 ms on the reference scene.

Why deferred:

- Reliable implementation requires a stable headless GL benchmark harness,
  not a normal unit-test runtime.

Re-entry trigger:

- Resume when benchmark environment is defined and reproducible across CI
  runners (GPU/driver variability bounded).

Owner note:

- Keep this deferred status explicit in audit updates so it is never mistaken
  for untracked or dropped work.

### DW-002 — Dedicated Offscreen Audience FBO

Source:

- Recording quality/stop-path investigation and follow-up planning (2026-06-18)
- Detailed deferred plan: [offscreen-audience-fbo-deferred-plan-2026-06-18.md](offscreen-audience-fbo-deferred-plan-2026-06-18.md)

Status:

- Deferred by owner direction on 2026-06-18.

What is deferred:

- Introduce a dedicated audience-composition offscreen FBO as the canonical
  capture source for recording/screenshots, with present-path consumption
  downstream.

Why deferred:

- Current screenshot-based recording path is stable enough for now.
- This refactor touches core compositor/capture ordering and should be staged
  with dedicated parity validation.

Re-entry trigger:

- Resume when recording/screenshot parity defects recur or when compositor
  dedup refactor milestones make insertion low-risk.

### DW-003 — Raver Mood Preset Split (raver / unicorn raver / mosh monster)

Status: deferred 2026-06-28

What is deferred:

- Split the current `raver` mood preset (BPM ≥ 126) into three named presets:
  - `raver` — progressive house, tech house, peak-time techno (126–142 BPM, shorter breakdowns)
  - `unicorn raver` — trance, uplifting trance, melodic techno (136–142 BPM, long epic arcs)
  - `mosh monster` — psytrance, hardstyle, DnB, metal, industrial (144+ BPM, aggressive short breaks)
- Auto-selection must be audio-profile-aware, not BPM-only, because trance (138 BPM)
  and peak-time techno (135 BPM) overlap in BPM range but need different visual presets.
  Routing: `recommended_profile_key → mood_preset` lookup table driven by the recommender.
- HUD display, hotkey cycling (Ctrl+J), config.toml keys, and ADR all need updating.

Why deferred:

- The timing fixes applied 2026-06-28 (breakdown_max_s 10→80, build_max_s 20→55) already
  address the correctness gap for trance. Remaining benefit is aesthetic differentiation
  (sparkly melodic vs brutal relentless).
- Auto-selection routing requires coupling the recommender output to mood-preset selection —
  moderate architectural lift best done in a dedicated session.
- Benefit is real but polish-tier, not broken-behavior repair.

Re-entry trigger:

- Resume after a few sessions with the 2026-06-28 timing tuning in place so the
  remaining aesthetic gap can be felt concretely before values are locked in.
  Estimated effort: 1.5–2 sessions.

---

### DW-004 — Live Effect Builder Mode (v2.0 Feature)

Status: deferred 2026-07-07

What is deferred:

- In Effect Builder mode the APC's 8×8 pad grid becomes a **layer compositor**: each row
  (or column) maps to a named visual effect running on its own framebuffer, and pads toggle
  layers on/off. The visible output is a real-time blend of all active layers.

Required core work before this can be implemented:

1. A `FramebufferStack` abstraction in `unicornviz/app.py` (core change — currently renders
   exactly one effect to the primary framebuffer per frame)
2. Each layer effect renders to its own `moderngl.Framebuffer`
3. A blend compositor (additive / screen / multiply / alpha-over) renders composited output
4. `BaseEffect` gains an optional `render_layer(fb, dt, audio)` entry point

Minimum viable design (v2.0 milestone):

- `LayerCompositor` subsystem owned by a `layer-compositor-01` drop-in
- `VJApi` gains `enable_layer_mode()` / `disable_layer_mode()` and
  `set_layer_effect(index, effect_cls)` / `toggle_layer(index)` surface
- `midi-controllers-01` enters **layer mode** when `layer_mode_toggle` fires:
  pads remap to `layer_0` … `layer_63` (toggle per pad)
- Shift+layer pad → opens a mini picker showing available effects for that slot

Intermediate workaround available today:

- The 8 APC scene-launch pads (row 8) can be bound to `scene_slot_1..8`, replaying scenes
  that call `vj_api.goto_effect(...)`. This gives a fast preset-switch grid without layer
  blending — useful for many live VJ workflows.

Why deferred:

- Requires a significant core render pipeline change (`FramebufferStack`) that must be
  designed and approved by the core team before any drop-in work begins.
- The scenes-01 intermediate workaround covers the primary live use case for v1.x.

Re-entry trigger:

- Resume after scenes-01 ships and the core team has approved the `FramebufferStack`
  architecture. Estimated effort: 3–5 sessions (core + compositor drop-in + MIDI wiring).

---

### DW-005 — ONNX Vocal-Activity-Detection Model

Status: deferred 2026-07-08

What is deferred:

- Replace/augment the hand-rolled `vocal_hnr` / `vocal_fmr` heuristics in
  `unicornviz/audio/analyzer.py` (added 2026-07-08 — see
  `docs/adr/vj-system.md`) with a small pretrained vocal-activity-detection
  model (ONNX runtime), run on the audio thread.

Why deferred:

- The heuristic pair (harmonic-to-noise-ratio proxy + formant modulation
  rate) is real signal — synthetic tests show clean noise-vs-tonal
  separation on HNR and a genuine (if noisier) preference for true 3-8 Hz
  syllabic-rate modulation on FMR — but neither is a true vocal detector;
  both can false-positive on any harmonically pitched, syllabically-
  modulated non-vocal source (a synth lead with vibrato, for example).
- A real VAD model would need a new runtime dependency (`onnxruntime` is not
  in `requirements.txt`), a model file to source/vet, and inference wired
  onto the audio thread without violating the "no blocking I/O in
  render()"/16.67ms frame budget constraints — a bigger lift than the
  heuristic pair, which reuses FFT data the analyzer already computes.
- The heuristic pair should be observed against real session data first
  (mirroring how the spectral fingerprints and BPM-detector thresholds were
  validated this session) before deciding whether the accuracy gap actually
  justifies the added dependency and complexity.

Re-entry trigger:

- Resume if live sessions show `vocal_hnr`/`vocal_fmr` still misclassifying
  non-vocal genres into rap/hyphy/r&b (or vice versa) often enough that the
  heuristic pair isn't closing the gap it was added for. Estimated effort:
  1–2 sessions (dependency vetting, model sourcing, audio-thread inference
  wiring, parity check against the heuristic pair before removing it).


### DW-006 — Bootable Fedora "Appliance" USB Image

Source:

- Owner request, 2026-07-18.

Status:

- Deferred to a dedicated batch; no work started.

What is deferred:

- A live Fedora USB image that boots straight into Unicorn Viz as a kiosk
  appliance — no desktop session, no login, no manual setup — so the whole
  rig travels on a stick and comes up show-ready on borrowed hardware.

Why this is attractive:

- The project already pins its runtime (`requirements.txt`), targets Fedora
  as the primary platform, and expects PipeWire + a Wayland compositor —
  which is exactly the environment an image can guarantee instead of hope
  for.  It also removes the single largest source of "works on my machine"
  variance from live use: the host's audio stack and GPU drivers.
- Persistence would let the library, `config.toml`, track store, stems cache
  and saved sets ride along with the stick.

What it would involve (sketch, not a plan):

- Kickstart + `livemedia-creator` (or Image Builder) to define the compose;
  a systemd unit launching the app in place of a desktop session; a writable
  overlay or a separate persistent partition for user data.
- Decisions needed before it becomes a plan: which GPU driver sets to ship
  (Mesa-only vs. bundling NVIDIA), whether MIDI/DDJ-REV1 udev rules ship
  preinstalled, how drop-in submodules are baked in given they are private
  repos, and how the image gets updated without a full re-flash.

Why deferred:

- It is a packaging/distribution workstream, not a runtime one, and it wants
  the runtime to be closer to stable first — an appliance image freezes
  whatever it ships, so it is best built once the mixer and Auto VJ have
  settled their config surfaces.
- Needs hardware to validate against (at minimum: a non-development machine
  to boot on) and a real test loop, or it becomes a large untested artifact.

Re-entry trigger:

- Revisit once the mixer reaches a stable config surface and the drop-in
  submodule distribution question is answered.  Natural companion to the
  installer work already tracked in
  [installers.md](installers.md).
