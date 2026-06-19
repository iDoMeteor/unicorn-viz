# Deferred Plan: Offscreen Audience FBO (2026-06-18)

Owner: Runtime Architecture
Status: deferred
Last updated: 2026-06-18

## Summary

This deferred plan proposes introducing a dedicated offscreen "audience" frame
buffer object (FBO) in the main app render path. The audience FBO would become
the canonical source for recording and screenshot capture, and then feed present
paths (single, span, mirror) as a downstream consumer.

Current behavior already records from the screenshot frame and is stable enough
for now. This work is deferred to avoid unnecessary churn in active show code.

## Problem Statement

The current pipeline captures recording frames from a post-overlay screenshot
path that is reliable, but still tied to a readback-oriented surface rather
than an explicit "audience composition" render target.

The deferred architecture goal is:

- one canonical composed frame
- deterministic ordering of overlays/CTA/HUD relative to capture
- cleaner decoupling from presentation routing (single/span/mirror)
- simpler future testing of recording vs present parity

## Intended End State

Add a dedicated offscreen audience FBO in `unicornviz/app.py` and use it as the
single source for:

- recorder input frames
- screenshots (unless an explicit alternate capture mode is selected)
- present-path blits to final display outputs

Control-room routes remain independent and optional.

## Proposed Integration Points

1. Allocate audience render target(s) alongside existing compositor resources.
2. Render the full audience composition into audience FBO each frame.
3. Move capture hooks to read from audience FBO (or its texture) instead of
   ad-hoc screenshot/readback surfaces.
4. Keep span/mirror compositing as presentation-only consumers of audience FBO.
5. Keep control-room and drop-in routing out of core capture plumbing.

## Migration Strategy

1. Add audience FBO behind a config/runtime feature flag (default off).
2. Implement parity mode where both old and new capture paths can be compared.
3. Validate screenshot and recording parity in single/span/mirror.
4. Flip default to audience FBO after parity tests are stable.
5. Remove legacy capture branch only after soak testing.

## Risks and Side Effects

- Additional VRAM footprint for extra color target(s).
- Potential frame-time increase if extra blits/copies are introduced.
- Resolution/resize edge cases if FBO resize lifecycle is incomplete.
- Ordering regressions if overlay draw order changes during migration.

## Validation Plan

- Unit tests for capture-source selection and ordering invariants.
- Regression tests covering recording source independence from multi-head mode.
- Manual validation in:
  - single display
  - span_all
  - mirror_all
- Visual parity checks for HUD/help/CTA and screenshot output.

## Re-entry Trigger

Resume this work when either:

- recording/screenshot parity issues recur, or
- compositor dedup refactor reaches a stable integration point that makes
  audience-FBO insertion low-risk.

## Related Documents

- `docs/planning/deferred-work-2026-06-18.md`
- `docs/planning/compositor-dedup-implementation-plan-2026-06-18.md`
- `plan.md`
