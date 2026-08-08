# Performance Remediation Plan — webcam + mirror, and the cliff behind it

Owner: owner + agents
Status: Proposed — measured, not yet actioned
Last updated: 2026-08-08

Built from a **live DEBUG capture** (947 frames, `logs/unicornviz_20260808_134245.log`)
taken while the owner reproduced the fault: `mirror_included` across three
1920×1080 displays (3840×2160 canvas) with the webcam overlay active.

The owner's own diagnosis was right and is the key to the whole thing:
**webcam *or* mirror alone is fine; both together falls over.** The
measurements explain why, and show it is not one bug but a stack of four
that only compound past a threshold.

---

## 1. What the capture actually says

Per-stage frame time, milliseconds:

| stage | mean | median | p95 | max |
|---|---:|---:|---:|---:|
| **total** | **55.84** | **38.54** | **107.72** | **552.32** |
| draw | 19.26 | 15.68 | 41.02 | 217.80 |
| effects | 16.28 | 0.07 | 48.05 | 129.19 |
| subsys_upd | 15.26 | 11.68 | 44.00 | 106.35 |
| subsys_present | 1.61 | 0.03 | 7.45 | 32.33 |
| swap | 1.18 | 0.18 | 6.52 | 45.85 |
| events | 0.94 | 0.13 | 1.64 | 523.97 |
| auto_vj | 0.87 | 0.50 | 2.08 | 108.11 |

**Median frame 38.5 ms ≈ 26 fps.** And:

> **922 of 947 frames (97%) exceed 25 ms.**

That 25 ms number is not arbitrary — see §3.

Reading the shape rather than just the means:

- **`effects` is bimodal**: median 0.07 ms, mean 16.28 ms, max 129 ms. The
  effect is nearly free on a typical frame and occasionally catastrophic —
  the signature of ProjectM preset loads / shader compiles, not steady cost.
- **`subsys_upd` is steady and large** (median 11.68 ms). Steady cost means
  a per-frame workload, and §2 identifies it.
- **`draw` at 15.7 ms median** is the 4K mirror composite. Expected to be
  heavy; made heavier by §4.
- **`events` max 523 ms** is a single outlier worth its own look later, not
  part of this fault.

---

## 2. Root cause A — the webcam re-uploads an unchanged frame, every frame

`webcam-01`'s `_get_camera_texture()` runs on **every rendered frame** with
no check whether the camera actually produced anything new:

```python
frame = self._worker.latest()        # -> self._latest.copy()   (2.7 MB memcpy, under lock)
...
self._cam_tex.write(frame.tobytes()) # -> another 2.7 MB copy, then a GPU upload
```

Three full-frame passes over 1280×720×3 per rendered frame. The camera runs
at **30 fps**; the display attempts **60**. So **at least half of that work
re-uploads a byte-identical frame**, and at the target rate it is roughly
**490 MB/s of memory traffic to display a picture that did not change.**

This is not a new bug — it is verbatim the 2026-08-03 audit's webcam-01 P2
finding, never actioned. It stayed invisible because on its own it fits in
the budget. Add the 4K mirror composite and it does not.

There is a second, smaller offender in the same function: the
brightness/contrast path allocates a **float32 copy of the whole frame**
(4× the bytes) every frame whenever either value is non-default.

**Fix:** a frame sequence counter on the worker; skip the copy, the
`tobytes()` and the upload entirely when the sequence has not advanced.
Move brightness/contrast into the shader (it already has a fragment stage)
instead of a per-frame numpy round-trip. Expected: `subsys_upd` median from
~11.7 ms to near zero, and the memory bus freed for the mirror blits.

---

## 3. Root cause B — the mixer starvation cliff (an amplifier, not a cause)

`_present_subsystems()` skips presenting the mixer / control-room window
whenever the **previous** frame exceeded `_SUBSYS_PRESENT_SKIP_MS`, up to
`_SUBSYS_PRESENT_MAX_SKIPS = 3` in a row:

```python
_SUBSYS_PRESENT_SKIP_MS = FRAME_TIME * 1000.0 * 1.5   # = 25.0 ms, from a hardcoded 60 Hz
```

| main loop | mixer window presents |
|---|---|
| 60 fps (16.7 ms) | every frame |
| 45 fps (22.2 ms) | every frame |
| **30 fps (33.3 ms)** | **1 in 4 → ~7.5 fps** |
| 24 fps (41.7 ms) | 1 in 4 → ~6 fps |

There is no middle: the moment the loop crosses 25 ms the mixer drops
**straight to a quarter rate**. With 97% of frames over the line, the mixer
is starved essentially always — which is why *the mixer* felt far worse than
the underlying 26 fps warrants, and why it seemed like a mixer problem.

Two further faults in that constant:

1. **It assumes 60 Hz.** `FRAME_TIME` is hardcoded; a 30 Hz projector or a
   mixed-refresh mirror rig is *always* above the threshold, so the guard
   fires permanently by construction. It should derive from the actual
   display refresh.
2. **Skipping is all-or-nothing.** Halving the present rate would shed most
   of the cost while keeping the window feeling live.

This is the 2026-08-03 audit's P3 #9, also never actioned.

---

## 4. Root cause C — mirror mode forces X11, and pays XWayland's tax

`app.py` deliberately tears down SDL and restarts under X11 whenever
`display_mode != 'single'`:

```python
# Multi-head modes rely on explicit window placement; Wayland may ignore
# this by design, so try X11 automatically if available.
```

The reasoning is sound: **Wayland has no protocol for a client to position
its own window.** It is a deliberate design decision upstream — the
compositor owns placement. Span/mirror needs a window at an exact origin
across a specific set of outputs, so on Wayland the request is simply
ignored, and the fallback to X11 is the only way to get reliable placement
today.

The cost is that everything then runs through **XWayland**: a 3840×2160 GL
surface is translated and re-composited rather than handed to the
compositor directly, which inflates `draw` and `swap`. That is a real part
of the 15.7 ms median draw.

**This is a genuine trade-off, not a bug** — and worth stating plainly
because it is the least fixable item here. Options, in increasing order of
work: leave it (correct today), revisit the per-output-window approach for
native Wayland (`MATE-X11-MULTIHEAD-NOTES.md` records a prior attempt that
failed on three platforms — the shared-GL-context variant remains
unexplored), or add a `force_wayland` escape hatch for users whose
compositor happens to place windows acceptably.

---

## 5. Root cause D — ProjectM preset loads stall the frame

`effects` median 0.07 ms vs max 129 ms, with two shader-compile warnings in
the same session, says preset switching blocks the render thread. It is not
what the owner is hitting continuously, but it is the source of the worst
individual spikes (and the 552 ms total outlier).

**Fix (later):** preset warm-up already exists in `projectm-01`; verify it
covers compile, and consider loading the next preset on a worker thread.
Not in scope for this plan beyond being recorded.

---

## 6. The always-on perf instrumentation (asked about directly)

`app.py:4477` gates every timing call on:

```python
perf_debug_enabled = log.isEnabledFor(logging.DEBUG)
```

The intent is "only measure when debugging". The reality is that
`_setup_logging()` sets the **root logger to DEBUG** for the DEBUG/INFO/WARN
bands and filters at the *handlers* instead — so at the default INFO level
`isEnabledFor(DEBUG)` returns **True**, and the instrumentation runs on
every frame of every session, forever.

**Measured cost: ~15 `time.perf_counter()` calls per frame, roughly 1 µs.**
The `log.debug()` itself is throttled (slow frames plus every 120th) and its
`%`-formatting is deferred until a handler accepts the record, so the string
is not built on the hot path.

So: **this is a real design smell but not a performance problem**, and it is
explicitly *not* a contributor to the fault above. It is worth fixing for
honesty rather than speed — the gate should read a real config key
(`[logging] perf_frames`) rather than a level check that cannot mean what it
appears to mean. The silver lining is that it is why we have this capture at
all without a rebuild.

---

## 7. Audio latency (owner request)

Requested: code default **low**, exposed as a **config-menu toggle**, and
removed from the owner's `config.toml`.

Current state, verified: `unicornviz/config.py` `_DEFAULTS` still says
`"latency": "high"`; `capture.py`'s function signature default was changed
to `'low'` in beta.38 but that fallback never fires because Config always
supplies a value. The live session ran at **high**. There is no `[audio]`
section in the owner's `config.toml`, so nothing needs removing there — the
change is purely to the code default.

**Fix:** set `_DEFAULTS['audio']['latency'] = 'low'`, add it to the config
editor's editable set with the three named options (low / medium / high) plus
a numeric seconds override, and document the trade-off (lower latency =
tighter beat response, more wakeups, more xrun risk on a loaded machine).

---

## 8. Plan of action

Ordered by measured value per unit of risk. Each item is independently
landable and independently revertible.

| # | Change | Where | Expected effect | Risk |
|---|---|---|---|---|
| **1** | **Skip webcam copy/upload when the frame has not changed** (worker sequence counter) | webcam-01 | removes ~490 MB/s and most of `subsys_upd`'s 11.7 ms median | Low — pure short-circuit |
| **2** | **Brightness/contrast into the shader** | webcam-01 | removes a per-frame float32 whole-frame allocation | Low |
| **3** | **Fix the present guard**: derive the threshold from real display refresh; halve rather than quarter | core | mixer stops dropping to 7.5 fps at the cliff | Low-Med — touches the July second-window work |
| **4** | **Audio latency default → low + config-menu toggle** | core | owner request | Low |
| **5** | **Gate perf instrumentation on a real config key** | core | correctness/honesty; ~1 µs/frame | Low |
| **6** | ProjectM preset-load stall | projectm-01 | kills the 129 ms spikes | Med — needs threading care |
| **7** | Native-Wayland multi-head (drop the X11 fallback) | core + multi-head-01 | removes the XWayland tax on `draw` | **High** — prior attempt failed on three platforms |

**Recommended first pass: 1 + 2 + 3.** Together they target the measured
dominant steady cost and the amplifier that made it feel catastrophic, and
none of them touch the risky multi-head path.

**Verification protocol** (same as the capture that produced this doc):
run with `--log-level DEBUG` in `mirror_included` with the webcam active,
capture ≥500 frames, and re-run the analysis. Success = median total under
25 ms, and the fraction of frames over 25 ms falling from 97% to a minority,
which is also what stops the mixer starving.

---

## 9. What this plan does *not* claim

The owner asked whether recent agent work caused the regression. Honest
answer from the measurements: **the dominant costs here are all pre-existing
and were documented in the 2026-08-03 audit** (webcam P2, present-guard P3
#9) — they were not introduced this week. But this capture was taken *after*
the recent core changes, so it cannot by itself exonerate them. The clean
test is a before/after at the same scene against `beta.44`, and it is worth
running before item 1 lands so the baseline is not muddied.
