# Feature Review Remediation Plan (2026-06-10)

Owner: Engineering + Operator
Status: active
Last updated: 2026-06-10

## Goal

Turn the first full effect-review pass into an execution plan that closes all open issues and stages enhancements in a controlled order.

Scope source:
- docs/audits/feature-review.md
- docs/archive/legacy-root-audits/2026-05-09-feature-enhancements.md
- docs/planning/effect-tweakables-backlog-2026-06-04.md

Assumption:
- Legacy effect deletions are already complete and are excluded from this plan.

## Prioritization Model

- P0: Release blocker or core-show quality blocker
- P1: High-value pre-release fix
- P2: Polish and consistency
- P3: Nice-to-have refinement

## Workstream A - Review Truth-Sync and Closure Gates (Immediate)

Objective: ensure the tracker reflects what is truly implemented vs. only claimed complete.

Tasks:
1. Re-open every 2026-06-04 "implemented" item as "implementation landed, visual signoff pending" until operator confirms in-session behavior.
2. Normalize summary counts in docs/audits/feature-review.md section 16 with current tested totals.
3. Add explicit PASS/FAIL and severity entries for every effect reviewed in the 2026-06-04 batch.
4. Convert freeform notes into actionable issue lines with owner and target date.

Acceptance criteria:
- No ambiguous "done" items without operator signoff evidence.
- Section 16 counts are accurate and non-placeholder.
- Every open item has a priority and owner.

## Workstream B - Open Issue Remediation From Effect Review (Now)

### B1. P0 Remaining

1. Audio Spectrum modernization pass
   - Add stronger life and movement profile while preserving readability.
   - Re-tune reactivity cap behavior (requested cap around 1.2).
   - Add explicit acceptance captures for single/span/mirror.

2. Any unresolved System Monitor split/hotkey UX deltas
   - Verify special-tool access path is stable and discoverable.
   - Confirm it is removed from normal visual rotation where intended.

Acceptance criteria:
- Operator re-score improves and P0 is cleared.
- No regressions in help text or hotkey behavior.

### B2. P1 Remaining

1. Alien Invasion polish round
   - UFO/highlight motion path no longer sticks to one side.
   - Stronger scene-wide reactivity and speed responsiveness.
   - Increase controlled color variance and sparkle accents.
   - Default zoom/framing adjusted to show full composition.

2. Startup-variance regressions still marked FAIL
   - Re-verify Fractal Zoom and Hacker Terminal startup variance after recent changes.

Acceptance criteria:
- Startup variance PASS for targeted effects.
- Operator confirms responsiveness and framing improvements.

### B3. P2/P3 Remaining

1. 3D Cube parameter-control sanity follow-up (reactivity/zoom feel).
2. Remaining visual polish asks not yet operator-closed.
3. Backlog-only P3 refinements stay deferred unless they unblock higher priorities.

Acceptance criteria:
- No open P2 tied to broken controls.
- P3 stays intentionally deferred unless bundled with nearby work.

## Workstream C - Incomplete Matrix Areas (Required for Release Confidence)

Objective: finish all unclosed review sections so release risk is known.

Tasks:
1. Section 8 drop-in runtime validation completion
   - Spotify auth and controls
   - Control Room focus/toggle behavior
   - Streaming provider switching and endpoint behavior
   - Asset-dependent Sims/Images/Videos validation once assets are available

2. Section 14 config edge-case pass
   - Missing config, malformed TOML, invalid audio/MIDI/stream/display settings

3. Section 15 stability pass
   - Rapid key sequence stress
   - Alt+Tab/focus transitions
   - 30-minute and 60-minute soak runs with recording/streaming combinations

Acceptance criteria:
- Sections 8, 14, and 15 fully marked with PASS/FAIL evidence.
- Any new P0/P1 findings immediately routed to Workstream B.

## Workstream D - Enhancement Delivery Waves (After B and C Core Risk)

Enhancements are grouped by value and implementation risk.

### Wave D1 (High-impact, low/medium risk)

1. Tap-tempo hotkey and BPM lock
2. Beat-locked transitions
3. Favorites/scene banks
4. Snapshot/restore show state
5. Photosensitive-safe mode
6. Reduced-motion mode

Exit criteria:
- Each feature behind clear hotkeys/config toggles.
- Help/docs updated in same change set.

### Wave D2 (Operator control and interoperability)

1. Web UI remote control
2. OSC input support
3. Hotkey/MIDI learn mode
4. MPRIS metadata pickup in HUD/transitions

Exit criteria:
- No startup dependency hard-fail when subsystem unavailable.
- Security posture documented for local control surface.

### Wave D3 (Heavier rendering/output investments)

1. Built-in MP4 pipeline hardening and clip-export tooling
2. Dynamic resolution scaling loop
3. Benchmark/profile mode with automated effect budget report
4. Effect chain/layering architecture experiments

Exit criteria:
- Performance budget impact measured and documented.
- Feature flags available for safe live rollback.

## Delivery Sequence and Cadence

Recommended sequence:
1. Workstream A (1-2 days)
2. Workstream B P0/P1 (first sprint)
3. Workstream C matrices and soak (parallel with B where possible)
4. Workstream B P2 closeout
5. Workstream D wave rollout (D1 then D2 then D3)

Cadence:
- Twice-weekly tracker sync in docs/audits/feature-review.md.
- End-of-sprint demo with operator score updates.

## Definition of Done

This plan is complete when:
1. feature-review.md has no open P0/P1 items.
2. Sections 8, 14, 15, and 16 are fully resolved with evidence.
3. Enhancement wave D1 is either shipped or explicitly deferred with owner/date.
4. plan.md and docs/README.md remain truth-synced to this plan.
