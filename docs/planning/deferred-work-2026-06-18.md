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
