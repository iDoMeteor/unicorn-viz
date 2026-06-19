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
