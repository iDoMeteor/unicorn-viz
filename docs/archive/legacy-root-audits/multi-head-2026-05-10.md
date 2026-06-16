# Multi-Monitor (Multi-Head) Audit — 2026-05-10

Scope:
1. Correctness review of the new multi-monitor support added in commit `83fae14`.
2. Side-effect / interaction review against existing recording, fullscreen, and resize behavior.
3. Optimization opportunities.

The audit also covers the related Audio Spectrum / EQ frequency-bar mapping per the same review request. Findings for that effect are at the end of this document.

---

## Summary

| Area | Status |
|------|--------|
| `display_mode = single` | OK, behavior preserved |
| `display_mode = span_all` | Functional; minor cleanup applied |
| `display_mode = mirror_all` | Functional; vertical-flip and double-readback issues identified and fixed |
| Fullscreen toggle | Functional; dead code removed |
| Recording integration | Now shares one screen readback per frame with mirror path |
| Wayland behavior | Not guaranteed for span/mirror modes; documented limitation |
| EQ bar↔frequency mapping | Was wrong (only 0–3 kHz, linear); corrected to log-spaced 30 Hz – 16 kHz |

Items prefixed with `[fixed]` were corrected as part of this audit. Items prefixed with `[noted]` are documented but left for follow-up because they require larger work or are out of scope for v1.

---

## Multi-Monitor Findings

### 1. `[fixed]` Mirror windows showed vertically flipped output

Cause:
1. `moderngl.Context.screen.read()` returns rows bottom-to-top (OpenGL convention).
2. SDL streaming textures expect rows top-to-bottom.
3. The previous `_present_mirror_outputs` uploaded the buffer as-is and used `SDL_RenderCopy`.

Fix:
1. Replaced `SDL_RenderCopy` with `SDL_RenderCopyEx` using `SDL_FLIP_VERTICAL` so the GPU compositor performs the flip during presentation rather than CPU-flipping the buffer.

Effect:
1. Mirror outputs now match the main display orientation.

### 2. `[fixed]` Two synchronous `screen.read()` calls per frame when recording + mirroring

Cause:
1. `_capture_recording_frame()` did its own readback.
2. `_present_mirror_outputs()` did a second readback for the mirror path.
3. Synchronous readbacks are GPU pipeline stalls; doing two per frame doubles the cost.

Fix:
1. The main loop now performs a single `screen.read()` per frame when either recording or mirroring is active.
2. The shared frame buffer is passed to both `_write_recording_frame()` and `_present_mirror_outputs()`.

Effect:
1. Eliminates the duplicate stall in the combined path.
2. Recording-only and mirror-only paths still do exactly one readback each.

### 3. `[fixed]` Dead/unreachable code in span_all branch of `toggle_fullscreen`

Cause:
1. The original implementation built `flags = SDL_WINDOW_BORDERLESS if … else 0` and then deliberately discarded it via `_ = flags`.
2. The original implementation also performed `SDL_SetWindowPosition` + `SDL_SetWindowSize` inside both fullscreen on/off branches with duplicated logic.

Fix:
1. The branch was simplified to compute the target position and size once, then call `SDL_SetWindowBordered` / `SDL_SetWindowPosition` / `SDL_SetWindowSize` exactly once.
2. The unused `flags` / `_ = flags` lines were removed.

Effect:
1. Same behavior, less surface area for accidental drift.

### 4. `[noted]` Mirror renderer GL context risk

Cause:
1. `_create_mirror_outputs` requests `SDL_RENDERER_ACCELERATED`, which on most platforms creates an extra OpenGL/Direct3D/Metal context bound to the mirror window.
2. The main app already owns a moderngl OpenGL context bound to the primary window.
3. When mirror renderers issue draws, SDL temporarily binds their backing context. If a moderngl call were issued from another thread mid-frame this would race; in our single-threaded render loop it is sequential but still binds/unbinds GL contexts repeatedly.

Why not changed now:
1. Behavior is correct for the current single-threaded render loop because `SDL_GL_MakeCurrent` is implicitly re-applied on the next moderngl call within the loop.
2. Forcing `SDL_RENDERER_SOFTWARE` would avoid the extra GL context entirely but would push pixel pushing onto the CPU, which under `mirror_all` plus 1080p+ resolutions could be worse than the current cost.

Recommendation:
1. Keep accelerated for now.
2. If we ever introduce multi-threaded rendering, switch the mirror path to either explicit `SDL_GL_MakeCurrent` calls or use `SDL_RENDERER_SOFTWARE`.

### 5. `[noted]` Mirror windows do not handle their own SDL events

Cause:
1. Only `SDL_KEYDOWN`/`SDL_KEYUP`/`SDL_QUIT`/`SDL_WINDOWEVENT` for the main window are wired in the loop.
2. Closing or resizing a mirror window from the OS today does not propagate cleanly.

Mitigations:
1. Mirror windows are created `SDL_WINDOW_BORDERLESS`, so the OS does not surface a close button.
2. They are positioned at the originating display bounds and not user-resizable.

Why not changed now:
1. Adding event routing per mirror window adds complexity beyond the v1 use case (live performance / mirroring on a fixed multi-monitor rig).

Recommendation:
1. If a future hotkey toggles `mirror_all` at runtime, also handle `SDL_WINDOWEVENT_CLOSE` / `SDL_WINDOWEVENT_RESIZED` for mirror windows.

### 6. `[noted]` Wayland positioning is not guaranteed

Cause:
1. Wayland intentionally does not allow clients to position their own windows.
2. `SDL_SetWindowPosition` is a no-op on most Wayland compositors.
3. As a result, both `span_all` and `mirror_all` may not appear on the intended displays under Wayland.

Mitigations:
1. The app already falls back to X11 if Wayland init fails.
2. Under X11, both modes work as designed.

Recommendation:
1. Document that `span_all` and `mirror_all` are X11-tested.
2. Consider auto-falling-back to X11 specifically when `display_mode != "single"` is requested on Wayland.

### 7. `[noted]` Mirror windows stretch the source frame to fit each display

Cause:
1. `SDL_RenderCopyEx` is called with `dst = NULL`, which scales the entire texture to fill the destination renderer.
2. If the mirror display has a different aspect ratio than the main display, the mirrored output is distorted.

Why not changed now:
1. For typical "all displays are 16:9" rigs this never triggers.
2. Letterboxing requires per-display rect computation which is straightforward but is a polish task.

Recommendation:
1. When at least two displays differ in aspect ratio, switch to letterboxed `dst` rect.

### 8. `[noted]` Display layout is captured once at startup

Cause:
1. `_log_video_displays()` populates `self._display_layouts` once during init.
2. If a monitor is hot-plugged, unplugged, or rearranged, mirrors and span dimensions remain stale.

Why not changed now:
1. Live display hot-plug handling requires `SDL_DISPLAYEVENT` integration and recreation of the moderngl context in the worst case.
2. Out of scope for the v1 multi-monitor slice.

Recommendation:
1. Add `SDL_DISPLAYEVENT_CONNECTED` / `SDL_DISPLAYEVENT_DISCONNECTED` handling that regenerates `_display_layouts` and triggers a soft re-init of mirror outputs.

### 9. `[noted]` `display_index` warning remains in span_all mode

Cause:
1. `_resolve_display_index()` is still called in `span_all`; it logs a warning if the index is out of range.
2. In `span_all` mode the index has reduced meaning (used only for the un-fullscreen restore position).

Recommendation:
1. Demote the out-of-range warning to debug when mode is `span_all`.

### 10. `[noted]` Mirror cost is the dominant performance variable

Cause:
1. `mirror_all` requires:
   - one synchronous `screen.read()` per frame
   - one `SDL_UpdateTexture` per mirror per frame (full-frame upload)
   - one render+present per mirror per frame
2. At 1920×1080 RGB24, each readback is ~6 MB, each `SDL_UpdateTexture` is another ~6 MB GPU upload.

Recommendation, in order of impact:
1. Add async readback via PBO (would also help recording).
2. Render at the smallest resolution any mirror needs, and let mirrors upscale, to drop both readback and upload bytes.
3. Reuse a single texture across all mirrors when target display sizes match.

---

## Audio Spectrum / EQ Frequency Mapping Findings

### 11. `[fixed]` EQ only displayed 0–3 kHz and used linear bin spacing

Pipeline state at audit time:
1. `AudioCapture._BLOCK_SIZE = 1024`, default `_SAMPLE_RATE = 48000`.
2. `Analyzer` performs `np.fft.rfft(windowed, n=self._bands * 2)` with `bands = 512`, so `n_fft = 1024` and bin frequency = `i * sample_rate / n_fft ≈ i * 46.875 Hz` at 48 kHz.
3. The full FFT array therefore covers 0 Hz to ~24 kHz across 512 bins.
4. `AudioSpectrum.update` previously did `self._fft[:] = audio.fft[:_N_BARS]` with `_N_BARS = 64`.
5. That meant the EQ used FFT bins 0–63, i.e. 0 Hz – ~3 kHz only.
6. Bins were also linearly spaced, which is wrong for music.

Effect at audit time:
1. The "EQ" bars effectively rendered only the bass and low mids, repeatedly, across all 64 bars.
2. Treble/upper-mid energy never moved a bar.
3. The right side of the bar field was almost indistinguishable from the left.

Fix:
1. Added a log-spaced band-edge table covering ~30 Hz – 16 kHz across 64 bars.
2. `update()` now averages the FFT bins inside each band rather than picking a single bin per bar.
3. Added a mild pink-noise compensation per band so a flat input produces visually balanced bars.
4. The bin-frequency derivation is documented inline so future sample-rate changes are obvious.

Effect after fix:
1. EQ now actually reflects bass, mids, and treble across the bar field.
2. Reading the bars left-to-right corresponds to ascending audible frequencies.

### 12. `[noted]` `Analyzer` band split for `bass` / `mid` / `treble` is also off

Current behavior in [unicornviz/audio/analyzer.py](../unicornviz/audio/analyzer.py):
1. `lo = bands // 32 = 16`, so `bass = mean(spectrum[:16])` ≈ 0–750 Hz. That is wider than the standard "bass" band (~60–250 Hz).
2. `mid = mean(spectrum[16:256])` ≈ 750 Hz – 12 kHz. That includes most of the treble range.
3. `treble = mean(spectrum[256:])` ≈ 12 kHz – 24 kHz. That sits almost entirely above the musically useful range.

Why not changed now:
1. Many existing effects are tuned against the current `bass` / `mid` / `treble` numbers.
2. Changing those splits would silently shift every effect's reactivity.
3. This is a follow-up that should land with a re-tune sweep across all effects, not as a drive-by fix.

Recommendation:
1. Track this under a dedicated "frequency-response tuning system" task (already present as a `[decision]` item in the project plan).
2. When that lands, normalize the splits to typical music-production bands: bass 60–250 Hz, low-mid 250–500 Hz, mid 500–2 kHz, high-mid 2–4 kHz, treble 4–16 kHz.

---

## Files Touched by This Audit

1. [unicornviz/effects/audio_spectrum.py](../unicornviz/effects/audio_spectrum.py) — log-spaced EQ band mapping with pink-noise compensation.
2. [unicornviz/app.py](../unicornviz/app.py) — mirror vertical flip, single shared screen read per frame, span_all `toggle_fullscreen` cleanup.
3. [audits/multi-head-2026-05-10.md](multi-head-2026-05-10.md) — this report.

---

## Suggested Follow-ups (not done in this audit)

1. PBO async readback for both recording and mirror paths.
2. Letterboxed mirror rendering for mixed-aspect-ratio displays.
3. `SDL_DISPLAYEVENT` hot-plug support.
4. Per-mirror SDL window event routing.
5. Wayland-aware fallback for `span_all` / `mirror_all`.
6. Re-tune analyzer band splits and document each effect's expected reactivity contract.
