# Deferred Work Register (2026-06-18)

Owner: Studio Documentation
Status: active
Last updated: 2026-06-18

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
