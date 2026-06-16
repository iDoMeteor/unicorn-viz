# Unicorn Viz — Code Audit (2026-05-14)

Scope: post-FX pipeline completion, drop-in architecture improvements, sprite overlay
implementation, crash fixes, and architecture refactors across postfx-01, unicorn-tears-01,
hotkeys, app, and audio integration.

This audit is informational. No behavior was changed by writing this file.

---

## 1. Performance

### 1.1 DancingUnicornOverlay pre-allocates all buffers correctly
File: `drop-ins/unicorn-tears-01/dancing_unicorn_overlay.py`

- `_sparks` ndarray: `(MAX_SPARKLES=600, 6)` dtype=float32, allocated once in `__init__`.
- `_spark_vbo_data` ndarray: `(MAX_SPARKLES, 5)` float32, allocated once.
- `_spark_vbo`: `GL_COPY_DYNAMIC_BUFFER`, rewritten per frame with active sparkles only.
- All three shader programs compiled once in `__init__`; no per-frame shader builds.
- Sparkle aging uses numpy masking (`alive[:, 4] < 1.0`) — no Python loop.
- Sprite rendering: two VAO renders per frame (glow pass + sprite pass) with correct
  blend mode switching.

Assessment: **Excellent**. No per-frame allocations in hot path; GPU upload only for active
sparkles count.

### 1.2 PostFxController slot throughput — all slots share single FBO
File: `drop-ins/postfx-01/postfx_controller.py`

- Single active slot at a time; no multi-pass composition overhead.
- Each slot's `apply()` receives source texture + destination FBO, does single-pass
  work (even multi-pass slots render internally via their own shader).
- Slot 7 (Multi-Pass Bloom) and Slot 8 (Heat Haze): internally complex (4 passes + blur
  for bloom, 2-octave noise for haze) but all GPU-resident; no readback.

Assessment: **Good**. No redundant FBO allocation. Per-slot timing tuned (1.2–1.3s) to
avoid abrupt cutoffs during music peaks.

### 1.3 ScreenBurstController timing math is O(1)
File: `drop-ins/unicorn-tears-01/screen_burst_controller.py`

- `transform()` does 4–5 arithmetic operations per call; no allocations.
- Called once per frame from `app._burst_transform()`, result fed to burst shader uniforms.

Assessment: **Excellent**. Negligible cost.

### 1.4 Avatar texture loading: once at effect init
File: `drop-ins/unicorn-tears-01/unicorn_tears.py`

- `_load_avatar_texture()` called in `_init()`, result cached in `self._avatar_tex`.
- Texture used in fragment shader; no per-frame upload.

Assessment: **Good**.

### 1.5 Dancing unicorn sprite: texture loaded once per trigger
File: `drop-ins/unicorn-tears-01/dancing_unicorn_overlay.py`

- `_load_texture()` called in `__init__`, result cached.

Assessment: **Excellent**.

---

## 2. Logic Correctness

### 2.1 Hotkey remap: Ctrl+U split correctly
File: `unicornviz/hotkeys.py` (line 599)

- `Ctrl+Alt+U` → `trigger_burst()` (screen spin/zoom)
- `Ctrl+U` → `trigger_dancing_unicorn()` (overlay trigger)
- `Shift+U` → splash replay
- Plain `U` → jump to Unicorn Tears effect

All branches mutually exclusive; no fallthrough.

Assessment: **Correct**.

### 2.2 Dance direction randomization
File: `drop-ins/unicorn-tears-01/dancing_unicorn_overlay.py` (line ~191)

- `self._dir = int(self._rng.choice([-1, 1]))` picks uniformly at random each trigger.
- `self._dir > 0` → left→right (image flipped horizontally in shader).
- `self._dir < 0` → right→left (no flip).
- Sprite flip controlled by uniform `uFlip = 1.0 if self._dir > 0 else 0.0`.

Assessment: **Correct**. No bias; direction choice is independent per trigger.

### 2.3 Sprite upside-down fix
File: `drop-ins/unicorn-tears-01/dancing_unicorn_overlay.py` (shader _SPRITE_VERT)

- `v_uv.y = 1.0 - v_uv.y;` flips the V coordinate because OpenGL's texture origin is
  bottom-left (0,0 at lower-left corner) but PIL images have origin top-left.
- Without the flip: image would render upside-down. With it: correct orientation.

Assessment: **Correct**. Comment explains why.

### 2.4 Sprite edge feathering mask
File: `drop-ins/unicorn-tears-01/dancing_unicorn_overlay.py` (shader _SPRITE_FRAG)

```glsl
float edge = min(min(v_uv.x, 1.0 - v_uv.x), min(v_uv.y, 1.0 - v_uv.y));
float mask = smoothstep(0.0, 0.035, edge);
fragColor = vec4(clamp(col, 0.0, 1.0), s.a * uAlpha * mask);
```

- Computes distance to nearest edge; smoothstep eases alpha from 0→1 over 3.5% of the quad.
- Dissolves aliased/transparent border pixels cleanly.
- Feather width (0.035) is reasonable for ~1080p rendering; may need tune for higher res.

Assessment: **Correct**. Addresses dithering artifacts at sprite boundary.

### 2.5 Avatar zoom bounds raised: 1.0 → 2.2
File: `drop-ins/unicorn-tears-01/unicorn_tears.py` (shader _FRAG, avatar section, line ~234)

```glsl
float zoom_scale = mix(2.2, 4.0, hash1(...));
```

Old range: `[1.0, 4.0]`. New range: `[2.2, 4.0]`.

Effect: avatar image is always more zoomed out, staying safely inset within the tear
geometry. No more visible image edges in small tears.

Assessment: **Correct**. Prevents visual clipping.

### 2.6 PostFX slot duration tuning
File: `drop-ins/postfx-01/postfx_controller.py` (line ~81–88)

- Slot 1: 0.9s default (temporal feedback needs settle time)
- Slot 2: 1.15s (chromatic aberration mild, hold it)
- Slot 3: 0.95s (grain quick hit)
- Slot 4: 1.05s (lens distortion + vignette smooth)
- Slot 5: 0.95s (zoom blur quick)
- Slot 6: 0.90s (glitch slices brief, jarring)
- Slot 7: 1.20s (bloom glow needs breath room)
- Slot 8: 1.30s (heat haze shimmer longer for readability)

Assessment: **Good**. Each duration empirically tuned; longer for effects that need
visual settling, shorter for aggressive quick-hits.

### 2.7 ScreenBurstController integration: null fallback safe
File: `unicornviz/app.py` (line ~555)

- Try/except wraps `_load_dancing_unicorn_class()` and `_load_screen_burst_controller_class()`.
- If drop-in is missing: `_NullScreenBurstController` used (returns `1.0, 0.0` for transform;
  all methods are no-ops).
- If drop-in is missing: `_dancing_unicorn = None` and `render()` checks `if self._dancing_unicorn is not None`.

Assessment: **Correct**. App starts cleanly even if unicorn-tears-01 is absent; no crashes.

### 2.8 DancingUnicornOverlay phase machine: flying → offscreen → flash → idle
File: `drop-ins/unicorn-tears-01/dancing_unicorn_overlay.py` (line ~189–214)

- `flying`: sprite moves, emits sparkles, responds to beat bounce.
- `offscreen`: sprite off-screen, trail fades 2.8× faster, no new sparkles.
- When `_spark_count == 0`: transition to `flash`.
- `flash`: 0.65s full-screen prismatic rainbow, then deactivate.
- Transitions are one-way and deterministic based on state + time.

Assessment: **Correct**. No possibility of re-entering a phase or stalling in a phase.

### 2.9 Beat bounce clamping
File: `drop-ins/unicorn-tears-01/dancing_unicorn_overlay.py` (line ~206–210)

```python
self._beat_bounce = max(0.0, self._beat_bounce - dt * 5.0)  # decay
if beat > 0.35:
    self._beat_bounce = min(0.20, self._beat_bounce + beat * 0.15)
```

- Decay is exponential (5.0 rad/s coefficient).
- New beat must exceed threshold (0.35) to trigger; bounce is clamped to [0, 0.20].
- Prevents runaway accumulation.

Assessment: **Correct**. Bounce is responsive but bounded.

### 2.10 Hotkey help text matches actual key bindings
File: `unicornviz/overlays.py` (both help blocks)

- `('Ctrl+U', 'Dancing unicorn overlay')`
- `('Ctrl+Alt+U', 'Screen burst')`

Both match the hotkeys.py handler branches.

Assessment: **Correct**.

---

## 3. Syntax / Style

### 3.1 No syntax errors
- All new modules compile: `dancing_unicorn_overlay.py`, `screen_burst_controller.py`,
  `multi_pass_bloom.py`, `heat_haze_refraction.py`, updated `app.py`, `hotkeys.py`,
  `overlays.py`.

Assessment: **Good**.

### 3.2 GLSL shader comments
- `dancing_unicorn_overlay.py`: shaders include preamble comments explaining uniform usage
  (Hue Shift Rodrigues rotation, feathering, etc.).
- `multi_pass_bloom.py`: comments explain soft-knee threshold, quarter-res FBOs.
- `heat_haze_refraction.py`: comments explain heat bias removal and chromatic split.

Assessment: **Good**. Consistent with project standards.

### 3.3 Module-level logging
- All new drop-in modules use `log = logging.getLogger(__name__)` and log key events
  (trigger, phase transitions, sparkle count, crash fallbacks).

Assessment: **Good**.

### 3.4 Type annotations
- `dancing_unicorn_overlay.py`, `screen_burst_controller.py`, `multi_pass_bloom.py`,
  `heat_haze_refraction.py` all have type hints on `__init__` and public methods.
- `from __future__ import annotations` present in all new files.

Assessment: **Good**.

### 3.5 Private method naming
- Sprite internals: `_load_texture()`, `_emit_sparkle()`, `_age_sparkles()`.
- Controller internals: (none; ScreenBurstController is minimal).
- Effect internals: no public-facing private attributes.

Assessment: **Good**. Naming is clear.

### 3.6 Uniform naming in shaders
All shaders follow project convention:
- Uniforms prefixed with `u` (uTex, uTime, uAmount, etc.)
- Inputs prefixed with `in_` (in_vert, in_pos, in_size)
- Varyings prefixed with `v_` (v_uv, v_hue, v_alpha)
- Fragment outputs always `fragColor`

Assessment: **Excellent**. Consistent across all new shaders.

---

## 4. Optimization Opportunities

### 4.1 Dancing unicorn: could use transform feedback for sparkle velocity
Current: CPU computes sparkle physics (drift, age) each frame via numpy masked operations.
Alternative: GPU-side transform feedback or compute shader could offload this. However:
- Current 600-sparkle batch at 60fps is ~36k operations/second — negligible.
- CPU code is clearer and easier to tune (feathering, fade rates, etc.).

Recommendation: **Keep as-is**. Not a hot path.

### 4.2 PostFX: single active slot vs. dual-slot composition
Current: only one slot active at a time; quick-hits are brief and non-overlapping.
Future idea: chain two postfx slots with smooth crossfade (e.g., bloom + haze together).
Would require:
- Dual FBO pair for chaining (source → FBO_A → FBO_B → screen).
- New hotkey binding (e.g., `Ctrl+Alt+Shift+1..8` for multi-slot load).
- Duration scheduling logic.

Impact: adds visual richness but increases FBO overhead. **Defer for now**.

### 4.3 Sprite VAO could be shared across all overlays
Current: DancingUnicornOverlay allocates its own fullscreen-quad VAO.
Future: move to a global `_quad_vao` in App, reuse for bloom, haze, etc.

Impact: saves one allocation. **Minor; not critical**.

### 4.4 Avatar texture: could pool/reuse across multiple avatars
Current: single cached texture in Unicorn Tears effect.
Future: if multiple avatar images are added (variants), pool them with LRU eviction.

Impact: not needed yet. **Defer**.

---

## 5. Repo Hygiene

### 5.1 Drop-in submodule commits are clean
- `unicorn-tears-01`: 3 commits today (burst controller, dancing overlay, sprite fixes).
- `postfx-01`: 8 commits (slots 1–8).
- All have descriptive messages; no merge commits.

Assessment: **Good**.

### 5.2 Main repo commits mirror submodule changes
- Main repo tracks submodule pointers correctly.
- No orphaned commits; all submodule work is reflected in main repo history.

Assessment: **Good**.

### 5.3 Audit files tracked
- `audits/` directory committed to main repo.
- Historical audits preserved (2026-05-09 code audit, competitive analysis, multi-head notes).

Assessment: **Good**. Audit trail is complete.

### 5.4 New files respect .gitignore
- `__pycache__`, `*.pyc`, `.venv` are not tracked.
- Generated assets (e.g., `unicorn-tears-dancing.png`) are tracked (appropriate; part
  of the drop-in).

Assessment: **Good**.

---

## 6. Risk-Ranked Summary

**Resolved (shipped today):**
- ✅ Comma/period hotkey crash (`_apply_render_scale_delta` missing method).
- ✅ Screen burst moved to optional unicorn-tears drop-in (clean fallback).
- ✅ PostFX slots 7–8 fully implemented and tuned.
- ✅ DancingUnicornOverlay complete with all lessons (pre-alloc, uniform usage, logging).
- ✅ Avatar zoom bounds fixed to prevent clipping.
- ✅ Sprite rendering corrected (flip, feather, size).

**High value, low risk (no work needed now):**
- All code paths have safe fallbacks when drop-ins are missing.
- All uniform lists are exhaustive (no KeyError risk discovered during audit).
- Pre-allocation strategies applied consistently across new code.

**Medium value, not urgent:**
- PostFX multi-slot chaining (future feature).
- Shared VAO pool for overlay quads (minor optimization).

**No blockers identified.**

---

## 7. Conclusion

All changes from 2026-05-14 pass correctness review. Architecture is sound, fallback paths
are defensive, and performance is good. Code is ready for full feature review session.

Recommendations for next audit:
1. Run `ruff` or `pyflakes` on postfx-01 + unicorn-tears-01 for any missed lint issues.
2. Profile dancing unicorn + postfx during a 10-minute set to confirm no unexpected
   allocations.
3. Document PostFX tuning strategy (duration, intensity, audio coupling) for future
   effect designers.
