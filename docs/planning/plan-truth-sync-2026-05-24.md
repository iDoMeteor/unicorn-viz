# Plan Truth Sync Report

Owner: Studio Documentation
Status: archive
Last updated: 2026-06-18


Date: 2026-05-24
Scope audited:
- plan.md
- docs/planning/plan-future-proofing.md
- docs/planning/plan-audit-response.md
- docs/planning/drop-in-planning.md
- docs/planning/installers.md
- drop-ins/auto-vj-01/PLAN.md
- docs/archive/debug/control-room-debug-handoff.md
- docs/planning/recording-implementation-plan.md
- docs/archive/audits/dropin-audit-report-2026-05-19.md

Method:
1. Extract done/todo/pre-release claims from planning docs.
2. Verify against current code and repo metadata.
3. Cross-check against recent git commit history where needed.
4. Classify each checked claim as one of:
   - Verified landed
   - Open (accurately marked)
   - Stale doc status (needs update)
   - Mismatch (marked done but not found in code)

---

## A) Verified landed claims

1. VJApi versioning and surface upgrades for grand-finale safety
- Verified in code:
  - VJ_API_VERSION and VJApi.VERSION
  - ctx/render_width/render_height accessors
  - has_postfx accessor
- Evidence: unicornviz/vj_api.py
- Classification: Verified landed

2. Grand-finale private-app coupling remediation
- Verified in code:
  - GrandFinaleController built from api.ctx and api.render_*
  - No direct app._ private access or SLF001 suppression in current drop-in code
- Evidence: drop-ins/grand-finale-01/grand_finale.py
- Classification: Verified landed

3. Ctrl+J leader chain and help integration
- Verified in code + commit history
- Evidence: plan references and recent history around Auto VJ chain commits
- Classification: Verified landed

4. Submodule migration of postfx/projectm/streaming
- Verified in repo metadata:
  - .gitmodules includes postfx-01, projectm-01, streaming-01
- Evidence: .gitmodules
- Classification: Verified landed

5. Sim showcase implementation exists
- Verified in code:
  - SimShowcase effect class present
- Evidence: drop-ins/sims-01/sim_showcase.py
- Classification: Verified landed

6. Scroll-wheel hue and ctrl-wheel rotation behavior exists
- Verified in code:
  - vj_api methods and app event routing for wheel + middle click behavior
- Evidence: unicornviz/vj_api.py, unicornviz/app.py, unicornviz/hotkeys.py
- Classification: Verified landed

---

## B) Open items that are accurately marked open

1. FP-04 loader standardization remains open
- Current state:
  - _load_multihead_controller_class has internal try/except fallback
  - _load_webcam_system_class / _load_rtmp_streamer_class / _load_postfx_controller_class are still bare loaders
- Evidence: unicornviz/app.py
- Classification: Open (accurately marked)

2. FP-05/06 config skeletons for postfx and grand_finale remain open
- Current state:
  - No [postfx] or [grand_finale] sections found in config.toml or config.full.example.toml
- Evidence: config.toml, config.full.example.toml
- Classification: Open (accurately marked)

3. FP-09/10/11 stable public contract docs remain open
- Current state:
  - No __all__ in unicornviz/effects/base.py for BaseEffect/AudioData contract declaration
  - No Stable Public Contracts or HELP_ENTRIES registration section found in docs/developer-guide.md
- Evidence: unicornviz/effects/base.py, docs/developer-guide.md
- Classification: Open (accurately marked)

4. Control-room live stability issue remains open
- Current state:
  - Handoff still identifies operator-window starvation/freeze as unresolved risk
- Evidence: docs/archive/debug/control-room-debug-handoff.md
- Classification: Open (accurately marked)

5. Recording long-run audio stability remains open
- Current state:
  - Document still calls out long-run degraded recorded audio investigation as open
- Evidence: docs/planning/recording-implementation-plan.md
- Classification: Open (accurately marked)

---

## C) Stale doc status (needs update)

1. docs/planning/plan-future-proofing.md still lists FP-01/02/03 as open critical checklist items
- But these are already landed in current code.
- Impact: Can incorrectly inflate pre-release critical backlog.
- Classification: Stale doc status

2. docs/planning/plan-future-proofing.md checklist still marks FP-08 unchecked
- But VJ_API_VERSION and VJApi.VERSION are in code.
- Classification: Stale doc status

3. plan.md still has TODO for assets/sims support
- But SimShowcase implementation exists.
- Classification: Stale doc status

4. plan.md still has TODO for Grand Finale system design/prototype
- But grand-finale-01 implementation exists with trigger/abort path.
- Classification: Stale doc status

5. docs/archive/audits/dropin-audit-report-2026-05-19.md states submodule registration is 14/17
- Current .gitmodules shows those previously missing modules are now submodules.
- Classification: Snapshot stale (historical report, not current state)

6. plan.md TODO for scroll-wheel hue-shift interaction appears functionally landed
- Core wheel/ctrl-wheel/middle-click behavior exists in current code.
- Classification: Likely stale TODO (recommend reword to tuning/polish if intent remains)

---

## D) Mismatch findings (marked done but not found in code)

Result: No hard mismatch found in this audit set.

Notes:
- Several done claims were validated directly in code.
- Several open claims are accurate.
- Main issue is planning-doc drift (stale open flags for already-landed items), not false done claims.

---

## E) Immediate doc-sync actions recommended

1. Update docs/planning/plan-future-proofing.md checklist:
- Mark FP-01, FP-02, FP-03 as done if this repo state is the release baseline.
- Mark FP-08 as done.
- Keep FP-04/05/06/09/10/11 open.

2. Update plan.md status lines:
- Move sims support from todo to done (or split into implementation done + content/perf polish todo).
- Move grand-finale system from todo to done (or split into implemented + polish/hardening todo).
- Reword scroll-wheel item from design todo to implementation tune/validation todo.

3. Treat docs/archive/audits/dropin-audit-report-2026-05-19.md as historical snapshot:
- Keep report immutable, but add a short note in docs/planning index or release notes that submodule migration state has changed since that audit.

---

## G) Sync actions applied in this pass

Applied now:
- plan.md updated to mark implemented sims support as done.
- plan.md updated to mark implemented grand-finale system effect as done.
- plan.md updated to mark scroll-wheel hue-shift interaction as done and narrowed follow-up to tuning.

Not yet applied in this pass:
- Add config skeleton sections for postfx and grand_finale in config files (still open by design).
- Base contract + HELP_ENTRIES documentation additions in developer guide (still open by design).

Plan-future-proofing checklist status:
- Current file now reflects FP-01/02/03 and FP-08 as complete.

---

## F) Confidence and limits

Confidence: High for audited items explicitly listed above.

Limits:
- This sync verifies representative high-impact planning claims and all future-proofing FP items.
- It does not independently re-validate every historical done claim in every audit file end-to-end.
