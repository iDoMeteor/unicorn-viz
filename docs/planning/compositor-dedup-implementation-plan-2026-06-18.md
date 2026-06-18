# Compositor Dedup Implementation Plan (2026-06-18)

Owner: Studio Documentation
Status: active
Last updated: 2026-06-18

## Objective

Complete audit item §7/#2 by replacing repeated compositor/present blocks in
`unicornviz/app.py` with a single behavior-preserving presentation path.

Target outcome:
- one canonical present/composite helper path;
- no visual or timing regressions;
- easier maintenance of mirror/candy/normal branches.

## Scope

In scope:
- Deduplicate repeated FBO present/composite code in the render pipeline.
- Keep the existing `_blit_fbo_b_to_fbo_a()` helper and build on top of it.
- Introduce a focused `_present_back(...)` style helper for final composition
  handoff where duplication still exists.
- Add/extend regression tests that pin call ordering and branch behavior.

Out of scope:
- Frame-budget CI guard (already deferred; requires headless GL benchmark).
- Visual redesign of transitions/effects.
- Refactors outside compositor/present flow.

## Current State (Known)

Already completed:
- `_blit_fbo_b_to_fbo_a()` extracted and used to remove 9 duplicate ping-pong
  blit blocks.
- Async PBO readback in place for streaming/recording.

Still open in this item:
- Mirror/candy/normal final present/composite branches still contain repeated
  logic and branch-local state handling.

## Risks

1. Render-order regressions
- Wrong call order can produce stale frames, black frames, or transition pops.

2. Readback timing regressions
- Recording/streaming readback must remain after the exact same rendered source
  as before.

3. Branch behavior drift
- Mirror/span/display-mode branches may look equivalent but have subtle
  differences in clear flags, viewport, and source FBO selection.

## Implementation Phases

### Phase 1: Inventory & Mapping

- Identify every present/composite block in `App.run()` and surrounding helpers.
- Build a per-branch table:
  - source FBO/texture,
  - destination FBO/screen,
  - clear behavior,
  - viewport/layout,
  - postfx/transition interactions,
  - readback point.

Deliverable:
- inline mapping comments near helper introduction (no standalone markdown).

### Phase 2: Helper Extraction (No Behavior Change)

- Add a minimal helper (name tentative):
  - `_present_back(src, dst, *, clear=True, viewport=None)`
- Keep helper small and explicit; avoid abstraction creep.
- Convert one low-risk branch first (normal path) without changing outputs.

Deliverable:
- one branch migrated, all tests green.

### Phase 3: Branch-by-Branch Migration

- Migrate mirror branch.
- Migrate candy/variant branch.
- Migrate remaining duplicated final-present call sites.
- Preserve existing state mutations and logging points.

Deliverable:
- all duplicate present/composite blocks removed or reduced to one-liners.

### Phase 4: Regression Test Coverage

- Add headless-safe tests that pin dispatch/ordering behavior:
  - branch-specific helper invocation order,
  - invariant: exactly one present path per frame branch,
  - invariant: readback hook called after final composed source selection.
- Extend existing app/overlay tests where possible instead of creating broad
  integration harnesses.

Deliverable:
- tests encode current contract and fail on compositor drift.

### Phase 5: Validation & Rollout

- Run full test suite.
- Run docs-check and linters.
- Manual runtime sanity sweep (operator checklist):
  - normal mode transitions,
  - mirror/span display modes,
  - recording/streaming enabled,
  - HUD/help overlays while switching effects.

Deliverable:
- behavior parity confirmed; merge.

## Acceptance Criteria

Required:
- No regressions in `pytest -q`.
- No duplicated final present/composite blocks left in targeted sections.
- Readback path behavior unchanged for recording/streaming.
- Audit item §7/#2 can be marked done.

Nice-to-have:
- Additional small helper cleanup where clearly safe.

## Test Strategy for This Item

Automated:
- New targeted unit/regression tests for branch->present ordering.
- Existing hotkey/audio/overlay tests remain green.

Manual:
- Quick runtime sweep of transitions + display modes + recording path.

## Sequencing With Other Work

This item should run as a focused refactor batch after currently active
external drop-in test work (Spotify/projectm) stabilizes, to avoid merge churn
in shared files.

## Proposed Next Execution Batch

1. Phase 1 inventory + mapping comments in `app.py`.
2. Extract `_present_back` helper with one-branch migration.
3. Add first regression test for ordering.
4. Re-run full suite and iterate branch migrations.
