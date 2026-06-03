# Unicorn Viz Prioritized Action Plan (2026-06-03)

Owner: Engineering
Status: active
Last updated: 2026-06-03

## Progress Update (2026-06-03)

- Completed since plan creation:
   - Display-mode alignment hardening for primary-centered overlays/menus/splash in `span_all` and `mirror_all`.
   - Mirror logical-canvas sizing and topology-change geometry/state reapply sync.
   - Recording continuity improvement on resize/topology dimension changes (segment rotation instead of silent stop).
   - Multi-head help entry correction (`Shift+X` for span-all).
   - Hotkey/help cleanup for removed alternate binds and stale labels.
- Verification snapshot:
   - `pytest -q`: 26 passed, 1 warning.
- Still required for closure:
   - Owner runtime validation pass on Fedora 44 mixed-size layout for final Display Modes signoff.

## Purpose

Consolidate outstanding work from audit reports, debug handoffs, and planning docs
into one execution order that can be worked down without reopening every source file.

## Source documents reviewed

- plan.md
- audits/fedora-44-prep.md
- audits/2026-05-09-code-audit.md
- audits/2026-05-14-code-audit.md
- audits/multi-head-2026-05-10.md
- docs/audits/2026-06-01-system-audit.md
- docs/audits/2026-06-01-hotkey-refactor-regressions.md
- docs/audits/feature-review.md
- docs/debug/control-room-debug-handoff.md
- docs/planning/beta-1-cut-checklist-2026-05-24.md
- docs/planning/installers.md
- docs/planning/recording-implementation-plan.md
- docs/planning/drop-in-planning.md
- docs/planning/documentation-cicd-pipeline-plan.md
- docs/planning/hotkey-cross-platform-conflict-remap-plan-2026-06-03.md

## Priority model

- P0: release-blocking runtime stability and correctness
- P1: beta gate completion and platform/package readiness
- P2: structural hardening and process quality
- P3: backlog expansion and new product features

## P0 Workstream (Do first)

1. Runtime stability closure for control room and audio fallback.
   Status:
   - Completed on 2026-06-03 (owner validation passed for single/span_all/mirror_all plus audio-failure behavior)
   Why:
   - control-room handoff still flags audience starvation risk while operator window is open
   - recent live sessions reported mid-session audio fallback churn
   Scope:
   - complete owner-machine validation matrix for control room in single, span_all, and mirror_all
   - complete long-session validation for audio fallback policy under steady source playback
   - decide default policy if any residual instability remains
   Acceptance criteria:
   - no audience freeze while control room is open in repeated 10-minute runs
   - no repeated source-hopping during steady playback in repeated 30-minute runs
   - explicit documented fallback behavior when no viable source remains

2. Close any remaining hotkey crash-path risk and sync stale P0 audit docs.
   Status:
   - Completed on 2026-06-03 (2026-06-01 hotkey/system audit docs truth-synced to current runtime state)
   Why:
   - old P0 hotkey/regression docs are now partially stale relative to landed fixes
   Scope:
   - verify all items in the hotkey regression checklist against current HEAD
   - update both 2026-06-01 audit docs to show what is closed vs still open
   - define a non-conflicting replacement key group for ANSI quick-jump shortcuts
     (A-family ANSI binds are temporarily disabled to prioritize operator audio selector access)
   Acceptance criteria:
   - no known keypath can crash the app from a drop-in exception
   - audit docs show current truth and are no longer action-ambiguous

3. Fedora/open-platform blocker cleanup still marked open in prep audit.
   Status:
   - Completed on 2026-06-03 (F44-03/F44-04/F44-06 explicitly reclassified/deferred with beta policy)
   Why:
   - fedora prep still tracks open items including multi-head compositor limits and doc drift
   Scope:
   - close or reclassify F44-03, F44-04, and F44-06 with explicit policy
   Acceptance criteria:
   - each open F44 item has either a landed fix or an explicit non-blocking beta policy

## P1 Workstream (Beta readiness)

4. Execute and complete the full feature-review matrix.
   Status:
   - In progress on 2026-06-03 (Help/Basics/Playback/Tweakables/Audio+Visual/Camera covered; Display Modes engineering fixes landed, owner runtime signoff pending)
   Why:
   - feature review checklist is still largely unchecked and is the practical release gate
   Scope:
   - run sections in order from help usage through performance/stability sweep
   - capture P0/P1/P2 findings in that file only
   Acceptance criteria:
   - all checklist sections have PASS/FAIL completion marks and notes
   - no open P0 findings remain

5. Beta checklist closeout for remaining non-runtime gates.
   Why:
   - beta cut checklist still carries open release-critical items
   Scope:
   - finalize ProjectM primary-machine validation status
   - run combined recording and streaming soak validation
   - finalize drop-in dependency contract for beta channel messaging
   Acceptance criteria:
   - all top-10 checklist items are either done or explicitly deferred with owner/date

6. Installer and distribution ownership actions from installers plan.
   Why:
   - release channel execution remains blocked on account/registry ownership tasks
   Scope:
   - claim snap and flathub identifiers
   - finalize macOS minimum supported version decision
   - finish domain and org-level release prerequisites
   Acceptance criteria:
   - open owner action items section in installers plan is fully resolved or dated/deferred

## P2 Workstream (Hardening and maintainability)

7. Drop-in loader and startup hardening from system audit.
   Why:
   - system audit still tracks startup inefficiency and module identity risk
   Scope:
   - implement drop-in module cache and deterministic module naming
   - verify no duplicate module execution during startup discovery passes
   Acceptance criteria:
   - one file path maps to one module load per process
   - startup log and timing confirm reduced duplicate loading

8. Repository hygiene and stale artifact cleanup.
   Why:
   - stale build outputs and historical drift increase audit noise and editing risk
   Scope:
   - remove tracked build artifacts if still present
   - enforce ignore patterns and verify clean working-tree behavior
   Acceptance criteria:
   - no tracked build shadow copies remain

9. Documentation quality pipeline rollout.
   Why:
   - docs CI/CD plan remains draft while planning/audit drift keeps recurring
   Scope:
   - implement Stage 1 PR validation in warning mode
   - baseline metadata and link integrity
   Acceptance criteria:
   - docs pipeline runs on PRs and nightly checks
   - index coverage and broken-link reports are visible in CI

## P3 Workstream (Backlog and expansion)

10. Product-expansion planning items after beta gates clear.
    Scope examples:
    - drop-in ecosystem expansions from drop-in planning and plan.md
    - cross-platform hotkey remap rollout after stabilization cycle
    - larger architecture initiatives from older audits and enhancement backlog
    Rule:
    - do not start this work until all P0 and P1 items are closed or explicitly deferred.

## Execution order

1. P0.1 runtime stability closure (completed 2026-06-03)
2. P0.2 hotkey crash-path + audit truth-sync (completed 2026-06-03)
3. P0.3 Fedora open-item closure/reclassification (completed 2026-06-03)
4. P1.4 full feature-review execution
5. P1.5 beta checklist closeout
6. P1.6 installer ownership closure
7. P2.7 drop-in loader hardening
8. P2.8 repo hygiene cleanup
9. P2.9 docs pipeline stage-1 rollout
10. P3 backlog execution

## Next Items (Current)

1. P1.4: continue feature-review execution, with owner runtime signoff for Display Modes as the first interactive checkpoint.
2. P1.5: beta checklist closeout (ProjectM primary-machine status, recording/streaming soak, dependency contract messaging).
3. P1.6: installer/distribution ownership closure.

## Suggested operating cadence

- Run work in 1-week slices with end-of-slice truth-sync updates to:
  - docs/audits/2026-06-01-system-audit.md
  - docs/audits/2026-06-01-hotkey-refactor-regressions.md
  - docs/planning/beta-1-cut-checklist-2026-05-24.md
  - plan.md
- Keep each slice tied to one dominant risk class.
- Require explicit acceptance-criteria evidence before marking any item done.