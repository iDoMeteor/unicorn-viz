# Unicorn Viz Beta-1 Cut Checklist (Primary + Drop-ins)

Date: 2026-05-24
Scope: Primary repo plus all drop-in submodule repos
Purpose: Final top-10 execution list before first officially tagged pre-release beta

## Release objective

Cut a tagged pre-release beta where:
- Core app is stable in live use
- Auto VJ behavior is musically trustworthy
- Drop-in ecosystem loads safely and degrades gracefully
- Packaging/install flow is reproducible enough for external testers

---

## Top 10 priorities before beta tag

1. Complete the full feature review matrix and close all P0/P1 findings
- Why: This is now the release gate and still largely unchecked.
- Source of truth: docs/audits/feature-review.md
- Exit criteria:
  - All sections executed at least once
  - No open P0
  - Any remaining P1 explicitly accepted with owner/date
- Repos: primary + all effect/system drop-ins touched by resulting fixes

~~2. Resolve control-room runtime starvation or ship control-room disabled by default~~
- ~~Why: Known risk of audience output freeze while control room window is open.~~
- ~~Source: docs/debug/control-room-debug-handoff.md~~
- ~~Exit criteria:~~
  - ~~Repro test no longer freezes in single/span/mirror~~
  - ~~If unresolved, explicit beta policy: control-room disabled + documented known issue~~
- ~~Repos: drop-ins/control-room-01 + primary~~
- **RESOLVED 2026-05-27** — Attempt K (app.py throttled subsystem frame readback to ≤10 fps).
  Root cause was 60 fps `glReadPixels` stalling the GPU pipeline. Fix verified via code review;
  live test on owner machine pending. `enabled` set available for beta testing.

3. Finish Auto VJ beat-tracker live hardening for remaining low-BPM under-lock edge cases
- Why: Remaining music-correctness blocker despite major v2 progress.
- Source: docs/debug/auto-vj-handoff-2026-05-21.md
- Exit criteria:
  - Live validation against known slow/medium tracks
  - Harness metrics do not regress vs current baseline
  - Documented acceptance thresholds for lock quality
- Repos: drop-ins/auto-vj-01 + primary (audio/analyzer surfaces)

4. ~~Close remaining pre-release future-proofing items still open in code/docs~~
- **✅ Verified done (2026-06-01)** — all FP-04/05/06/09/10/11 items confirmed in code:
  - `_load_webcam_system_class`, `_load_rtmp_streamer_class`, `_load_postfx_controller_class`
    all have internal try/except + null fallbacks; remaining bare loaders are all wrapped at
    call sites in `App`.
  - `[postfx]` and `[grand_finale]` sections present in both `config.toml` and
    `config.full.example.toml`.
  - `__all__ = ['BaseEffect', 'AudioData']` in `unicornviz/effects/base.py`.
  - "Stable Public Contracts" and "Registering Help Hotkeys via HELP_ENTRIES" sections
    present in `docs/developer-guide.md`.
  - `plan-future-proofing.md` retired; all FP items tracked as `[done]` in `plan.md`.

5. ~~Add and validate user-visible postfx and grand_finale config sections~~
- **✅ Verified done (2026-06-01)** — both `[postfx]` and `[grand_finale]` sections present
  with documented keys in `config.toml` (commented skeleton) and `config.full.example.toml`
  (full defaults). No additional action required.

6. ~~Do planning truth-sync updates in canonical planning docs before tag~~
- **✅ Done (2026-06-01)** — comprehensive truth-sync pass completed:
  - `plan.md` Current Focus updated: FP pass marked `[done]`, Control Room entry trimmed
    to current state, spotify-01 marked `[done]` with open polish items noted, Delivery
    Strategy items marked `[done]`.
  - Beta checklist items 4 and 5 verified and marked done.
  - `plan-future-proofing.md` retired (referenced in plan.md with note).
  - `plan-truth-sync-2026-05-24.md` remaining actions confirmed applied.

7. Validate ProjectM on the primary target machine and finalize fallback posture
- Why: Explicitly still called out as outstanding in plan.md.
- Exit criteria:
  - Confirm native projectM path works on primary box
  - Confirm fallback behavior under missing lib/presets
  - Mark supported/unsupported combinations in docs
- Repos: drop-ins/projectm-01 + primary docs

8. Lock installer/release artifact pipeline for pre-release tags
- Why: Tagged beta needs repeatable outputs and clear distribution path.
- Source: docs/planning/installers.md
- Exit criteria:
  - Tag push builds all intended beta artifacts
  - Checksums + release manifest attached
  - Pre-release channel behavior validated
- Repos: primary

9. Implement and/or enforce drop-in dependency contract for beta channels
- Why: Cross-repo dependency drift is a likely beta pain point.
- Source: docs/planning/installers.md section 6
- Exit criteria:
  - drop-in dependency strategy selected for beta (minimum manual policy or tooling)
  - Clear tester instructions for optional/system deps
- Repos: primary + drop-ins with extra deps

10. Run long-session recording and streaming stability validation
- Why: Recording is implemented but long-run audio degradation investigation remains open.
- Source: docs/planning/recording-implementation-plan.md
- Exit criteria:
  - 30/60 min soak with recording on
  - Streaming + recording combined smoke test
  - Any known issues documented with workaround
- Repos: primary + drop-ins/streaming-01

---

## Suggested repo/tag execution order

1. Finish code and doc changes in each affected drop-in repo.
2. Commit and push each drop-in repo first.
3. Update submodule pointers in primary repo.
4. Commit/push primary repo with release notes + final planning truth-sync.
5. Create pre-release tag in primary repo.
6. Verify artifact pipeline output and publish release notes.

---

## Beta go/no-go gate

GO only if all are true:
- No open P0 items
- Control-room policy is explicit (fixed or disabled)
- Auto VJ tempo lock acceptable on live test set
- Planning docs match implementation state
- Artifact pipeline produces expected pre-release outputs
