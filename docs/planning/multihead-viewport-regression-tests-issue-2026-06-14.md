Owner: Runtime/Core
Status: proposed
Last updated: 2026-06-14

# Multi-Head Viewport Regression Tests (Issue)

## Summary

Capture and prevent regressions in multi-head viewport routing across non-grid
display topologies, mixed resolutions, and configurable primary display
selection.

## Background

Recent runtime fixes addressed two classes of issues:

- Overlay anchoring drift in span/mirror modes on non-linear monitor layouts.
- Coordinate-space mismatches between top-left display layout space and
  bottom-left OpenGL viewport space.

These fixes should be guarded with deterministic tests so behavior remains
stable when topology logic evolves.

## Scope

1. Geometry-only viewport regression tests for primary display targeting.
2. Mode matrix checks for `single`, `span_included`, `span_all`,
   `mirror_included`, and `mirror_all`.
3. Mixed-resolution and non-grid layout fixtures, including centered-lower
   primary layouts.
4. Screenshot safety tests for framebuffer-size/readback-size mismatch paths.

## Proposed Test Topologies

1. 3-screen non-grid
   - Display 0: `(1920, 0, 1920, 1080)`
   - Display 1: `(0, 0, 1920, 1080)`
   - Display 2: `(940, 1080, 1920, 1080)`
2. 5-screen mixed sizes
   - Two top displays, one larger center display, two smaller bottom displays.
3. Mixed-resolution variant
   - One primary display at 4K while others remain 1080p.

## Acceptance Criteria

1. For each topology/mode pair, computed primary viewport is deterministic and
   mapped to the configured primary display index.
2. Viewport conversion from layout space to GL viewport space is validated.
3. Screenshot pipeline handles short readback safely without process crash.

## Non-Goals

1. Visual style changes to overlays/help UI.
2. Candy Frame rendering redesign.
3. Operator workflow changes outside viewport routing.

## Notes

This issue is intentionally deferred while current milestone focus remains on
help-screen additions (About, Contact/Bug Report, and Links).
