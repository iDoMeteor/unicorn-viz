# Audit Response Plan

This file turns the findings in:
- `audits/2026-05-09-code-audit.md`
- `audits/2026-05-09-feature-enhancements.md`

into an execution strategy.

## Recommendation

Do **not** knock the entire audit list out in one shot.

Reason:
1. The findings span different risk classes:
   - correctness/documentation cleanup
   - low-risk runtime hot-path cleanup
   - moderate refactors in the audio pipeline
   - optional architecture changes (threaded analyzer, dynamic render scale)
2. A one-pass refactor would make it much harder to isolate regressions in:
   - audio responsiveness
   - transition feel/timing
   - effect-specific rendering behavior
   - live hotkey / control flow behavior
3. Several issues are independent enough to fix quickly and validate narrowly.
4. A few findings are now already resolved or partly stale, so the list should be normalized before work starts.

Recommended approach:
- work in **4 waves**
- validate each wave before moving on
- keep one commit per wave or per tightly-coupled item

---

## Normalization First

Before implementation, treat these audit items as already resolved or stale:

### Already resolved

1. Repo hygiene (`.venv`, `__pycache__`, `.pyc` tracked in git)
- Status: resolved
- Verification: `git ls-files` audit check returned `0`
- Action: update `plan.md` note and remove this from the cleanup queue

2. Per-effect reactivity doc semantics
- Status: corrected after the audit
- Notes: audit called out old multiplier wording; runtime/docs were later updated to absolute-override semantics
- Action: do not schedule this again unless another doc drift is found

### Still valid but should be rephrased

1. “Per-effect reactivity allocation”
- Still valid, but the implementation has changed since the audit.
- Current issue is specifically:
  - `_audio_for_effect()` allocates a fresh `AudioData` and copies arrays when an override is active.
- Action: keep this item, but work against current code, not the older wording.

---

## Wave 1 — Correctness and low-risk cleanup

Goal:
- remove obvious logic drift and hot-path correctness issues with minimal behavioral change

Items:

1. Use real `dt` for transition timing
- File: `unicornviz/app.py`
- Why first:
  - correctness bug
  - user-facing feel issue
  - very localized change
- Validation:
  - transition duration should match config at different frame rates
  - no transition timing regressions in normal 60fps run

2. Lift `ANSIViewer` imports out of app loop
- File: `unicornviz/app.py`
- Why first:
  - zero-risk cleanup
  - removes needless per-frame import path
- Validation:
  - ANSI auto-advance logic still works
  - `goto_ansi()` still works

3. Remove dead `_splash_config` write
- File: `unicornviz/app.py`
- Why first:
  - dead code
  - logic simplification
- Validation:
  - splash replay via `Shift+U`
  - startup splash still works

4. Hoist inline imports from hot paths
- Files:
  - `unicornviz/audio/manager.py`
  - `unicornviz/effects/fire.py`
  - `unicornviz/effects/particle_storm.py`
- Why first:
  - trivial cleanup
  - no intended behavior change
- Validation:
  - syntax check
  - narrow smoke tests for touched effects

5. Lift transition `mode_map` to module constant
- File: `unicornviz/app.py`
- Why first:
  - low-risk micro-optimization
- Validation:
  - all transition modes still map correctly

6. Fix cursor visibility desync on window focus changes
- File: `unicornviz/app.py`
- Why first:
  - real UX correctness issue
  - easy to validate manually
- Validation:
  - Ctrl cursor behavior after alt-tab / focus loss

Success criteria for Wave 1:
- no visible effect rendering regressions
- transition timing is frame-rate independent
- startup + splash + ANSI flows still behave correctly

---

## Wave 2 — Runtime allocation cleanup

Goal:
- reduce avoidable per-frame Python and numpy allocations without changing visuals

Items:

1. Add scratch `AudioData` buffers for `_audio_for_effect()`
- File: `unicornviz/app.py`
- Strategy:
  - maintain one scratch object per active effect slot (`current`, `next`)
  - mutate fields in place instead of allocating per frame
- Validation:
  - effects with and without per-effect reactivity produce expected response
  - transitions with different overrides still behave correctly

2. Cache analyzer window(s)
- File: `unicornviz/audio/analyzer.py`
- Strategy:
  - cache hanning window keyed by block length
- Validation:
  - analyzer outputs remain numerically sane
  - no silence/beat regressions

3. Replace spectral-flux list churn
- File: `unicornviz/audio/analyzer.py`
- Strategy:
  - replace list + `pop(0)` + per-frame `np.array()` with a bounded structure
- Validation:
  - beat triggering still feels similar

4. Tighten effect-local allocation hotspots
- Files:
  - `unicornviz/effects/unicorn_tears.py`
  - `unicornviz/effects/metaballs.py`
  - `unicornviz/effects/audio_spectrum.py`
- Strategy:
  - preallocate flat arrays / buffers where possible
  - avoid tuple-building generators in render hot path
  - vectorize bar generation only if it remains maintainable
- Validation:
  - effect-by-effect smoke tests
  - visual parity check

Success criteria for Wave 2:
- reduced Python allocation churn in profiler or simple timing runs
- identical or near-identical visual behavior
- no effect crashes across long session sweep

---

## Wave 3 — Medium-risk performance improvements

Goal:
- improve runtime headroom without changing the product model

Items:

1. Analyzer internal allocation-free pass
- File: `unicornviz/audio/analyzer.py`
- Strategy:
  - reuse arrays where practical
  - reduce copies around FFT smoothing path
- Validation:
  - compare beat / band response before vs after with recorded test material

2. Optional global internal render scale
- Files:
  - `unicornviz/app.py`
  - docs/config
- Strategy:
  - add `[render].internal_scale`
  - render heavy scenes to scaled FBO, composite to screen
- Why Wave 3:
  - meaningful performance win
  - slightly broader rendering-surface change
- Validation:
  - screenshot comparisons
  - measure frame stability on heavy effects

3. Logging noise review
- Files:
  - `unicornviz/hotkeys.py`
  - audio startup/open logs
- Strategy:
  - keep operationally useful logs
  - lower spammy per-key INFO logs if needed
- Validation:
  - log remains useful during live troubleshooting

Success criteria for Wave 3:
- measurable performance improvement on heavy scenes
- no degradation in visual quality beyond accepted render-scale tradeoff

---

## Wave 4 — Architecture changes (optional, careful)

Goal:
- take the biggest wins only if Waves 1–3 still leave meaningful performance pressure

Items:

1. Move analyzer processing off the render thread
- Files:
  - `unicornviz/audio/*`
  - maybe app integration points
- Risk:
  - concurrency / snapshot consistency
  - harder debugging when audio + render decouple
- Only do if:
  - profiling shows render-thread analyzer cost is still material after Waves 1–3

2. Dynamic resolution scaling
- Files:
  - render pipeline, config, maybe overlays
- Risk:
  - more moving parts than fixed render scale
  - possible shimmer / aliasing / transition mismatch
- Only do if:
  - internal render scale proves worthwhile and you want automatic tuning

Success criteria for Wave 4:
- demonstrable frame stability gains on real hardware
- no live-control regressions

---

## Suggested execution order

Recommended exact order:

1. Wave 1.1 `dt`-based transition timing
2. Wave 1.2 / 1.3 / 1.4 / 1.5 / 1.6 cleanup bundle
3. Wave 2.1 scratch `AudioData`
4. Wave 2.2 / 2.3 analyzer hot-path cleanup
5. Wave 2.4 effect-local allocation cleanup
6. Wave 3.1 analyzer reuse refinements
7. Wave 3.2 fixed internal render scale
8. Wave 4 items only if still needed

---

## What should *not* be bundled together

Avoid these one-shot combinations:

1. Analyzer threading + transition timing + render-scale
- too many simultaneous causes if responsiveness changes

2. Broad effect-hotpath cleanup across every effect in one PR
- impossible to isolate visual regressions quickly

3. Input UX fixes + logging policy + audio pipeline refactor
- unrelated concerns, hard to review

---

## Validation strategy

For each wave:

1. Syntax check touched Python files
2. Run narrow smoke tests for touched effects or runtime surfaces
3. Do one manual live pass covering:
- scene switching
- transitions
- reactivity changes
- help/hotkeys
- ANSI entry paths
4. Compare visuals for tuned effects before/after where appropriate

For audio/analyzer changes specifically:

1. Run with a known music source
2. Check bass / mid / treble feel on:
- Starfield
- Metaballs
- Water
- Audio Spectrum
- Unicorn Tears
3. Check beat onset feel on:
- transitions
- Particle Storm
- Fractal Zoom

---

## Recommendation summary

Best path:
- **Make and use this plan file**
- **Do not** attempt to close the full audit in one shot
- Start with Wave 1 + Wave 2 first
- Reassess after those land

That gives you:
1. the highest-confidence wins fastest
2. the least regression risk for a live-performance app
3. enough structure to keep audit cleanup from turning into an unfocused refactor

---

## Proposed next concrete action

If proceeding immediately, the next implementation batch should be:

1. `app.py`: fix transition timing to use `dt`
2. `app.py`: lift `ANSIViewer` import out of loop
3. `app.py`: remove dead splash config write
4. `app.py`: lift `mode_map` constant
5. `audio/manager.py`, `fire.py`, `particle_storm.py`: hoist inline imports
6. `app.py`: reset cursor visibility on focus loss

This is the cleanest first PR/batch.
