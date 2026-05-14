# Post FX Drop-In: Developer Notes

Lessons learned from implementing the first four quick-hit post-process effects.

## Architecture & Design

### One-Shot Quick-Hit Model

All post FX in this drop-in are **one-shot bursts**, not latched toggles:
- Trigger via hotkey (e.g., `Ctrl+Alt+1`)
- Run for a configurable duration (default 0.9–1.15s)
- Strength envelope: 1.0 at trigger, fades to 0.0 at expiration
- Controller calls `effect.apply(... strength)` where `0 ≤ strength ≤ 1`
- Effects use `strength` to scale their intensity over the burst lifetime

**Why this works:**
- Feels responsive and intentional
- Doesn't interfere with the active effect
- Stackable (you can hit multiple post FX in quick succession)

### Per-Slot Configuration

Each slot can have its own hit duration via `config.toml`:
```toml
[postfx]
slot1_duration = 0.90
slot2_duration = 1.15
slot3_duration = 0.95
slot4_duration = 1.05
```

Longer durations for effects that take time to perceive (e.g., chromatic aberration),
shorter for punchy ones (grain, distortion).

---

## Shader & Visibility Lessons

### Amplitude Pitfall: Uniform Values Are Tiny

**Problem:** Computing 0.0865 grain in Python and passing it as a uniform looked reasonable, but when multiplied by a [-0.5, 0.5] hash value inside the shader, the result was imperceptible (~0.043 max shift per channel on [0, 1] RGB).

**Solution:** Do amplitude amplification **inside the shader**, not in the CPU math:
```glsl
float n = hash12(px + vec2(uTime, ...)) - 0.5;  // Range: [-0.5, 0.5]
c += n * uGrain * 3.5;  // Multiply by 3.5 inside shader, not outside
```

Even modest uniforms (0.0865) become perceptible (0.30 effective shift).

### Blocky Grain for Retro Feel

Fine-grained noise (per-pixel) on high-res screens is too subtle. Use **blocky grain** for impact:
```glsl
vec2 grain_px = floor(px / 6.5);  // Scale down to ~6-8 pixel blocks
float n = hash12(grain_px + vec2(uTime, ...)) - 0.5;
c += n * uGrain * 4.8;
```

Result: unmistakable, VHS-like, retro film grain.

### Contrast Boosts Visibility

Apply a mild **S-curve** contrast boost to make grain and dither pop:
```glsl
vec3 contracted = c * c * (3.0 - 2.0 * c);  // Classic S-curve
c = mix(c, contracted, 0.25);  // Blend 25% of the curve
```

This preserves blacks and whites while punching up mid-tones.

### Shader Bugs: Smoothstep Order Matters

**Lens Distortion + Vignette bug:**
```glsl
// WRONG (inverted): dark at center, bright at edges
float vig = smoothstep(1.06, 0.18, dot(uv, uv));

// CORRECT: bright at center, dark at edges
float vig = smoothstep(0.12, 0.95, dot(uv, uv));
```

Always test vignette visually; the math can be counterintuitive.

---

## Logging & Debugging

### Log at Module Level, Not Instance Level

**Bad:**
```python
def __init__(self, ...):
    import logging
    self._log = logging.getLogger(__name__)

def apply(self, ...):
    self._log.info(...)
```

**Good:**
```python
import logging
log = logging.getLogger(__name__)

class MyEffect:
    def apply(self, ...):
        log.info(...)
```

Module-level logger is cleaner and more efficient.

### Log Computed Values, Not Uniform Reads

**Bad:**
```python
self._pass.prog['uGrain'].value = computed_grain
self._log.info('grain=%.4f', self._pass.prog['uGrain'].value)  # May not work!
```

Reading back uniform values is unreliable. Instead:
```python
grain_val = computed_grain
self._pass.prog['uGrain'].value = grain_val
log.info('grain=%.4f', grain_val)  # Log before setting
```

### Use `--log-level NONE` for Clean Testing

When testing visual effects, set `--log-level NONE` to silence all output.
Configure in `config.toml`:
```toml
[logging]
level = "NONE"
```

---

## Effect Lifecycle

### Reset on Slot Selection

Every effect should implement an optional `reset()` method:
```python
def reset(self) -> None:
    """Reset effect state when triggered."""
    self._history_valid = False
    self._phase = 0.0
```

The controller calls `effect.reset()` when a slot is triggered, ensuring clean state.

**Example: Temporal Feedback Trail**
- On trigger, mark history invalid
- On first apply frame, prime history from current input (no stale frames)
- On subsequent frames, blend normally

This prevents one-frame flashes of old content.

### Required Methods

Every effect must implement:
- `apply(src_tex, dst_fbo, dt, bass, mid, treble, beat, strength) -> None`
- `resize(width, height) -> None`
- `destroy() -> None`

Optional but recommended:
- `reset() -> None` (for quick-hit effects especially)

---

## Performance Considerations

### Quick-Hit Overhead

Quick-hit effects are **not** always active, so overhead is minimal:
- No per-frame cost when slot is not triggered
- Only runs during the burst window (0.9–1.15s typical)
- Can safely chain multiple effects (each gets its own render pass)

### Framebuffer Management

Each effect manages its own scratch framebuffers (e.g., Temporal Feedback's history FBO):
```python
self._feedback_fbo = self._ctx.framebuffer(color_attachments=[tex])
```

Always release in `destroy()`:
```python
def destroy(self) -> None:
    if self._feedback_fbo is not None:
        self._feedback_fbo.release()
```

---

## Adding New Effects (Slots 5–8)

1. **Create the effect class** in `effects/new_effect.py`:
   - Inherit from nothing (no base class; use protocol duck-typing)
   - Implement `NAME`, `apply()`, `resize()`, `destroy()`, optionally `reset()`

2. **Wire into controller** in `postfx_controller.py`:
   - Import the class at top
   - Add to `SLOT_MAP` with (slot_number, name, True)
   - Instantiate in `__init__`: `self._effects[n] = NewEffect(ctx, width, height)`
   - Add duration config: `self._slot_hit_duration[n] = ...`
   - Add help entry: `('Post FX', 'Ctrl+Alt+N', 'Effect Name (quick hit)')`

3. **Update README**:
   - Check off the effect in the 8-slot roadmap
   - Document any special config or behavior

4. **Test**:
   - Compile check: `.venv/bin/python -m py_compile`
   - Load check: `load_dropin_symbol('postfx-01/postfx_controller.py', 'PostFxController')`
   - Runtime: hit hotkey, verify logs and visuals

---

## Common Pitfalls

| Pitfall | Solution |
|---------|----------|
| Effect too subtle | Multiply noise/displacement by 3–5x inside shader, not in Python |
| Fine grain on high-res screen | Use blocky grain (scale down coordinates by ~6) |
| Stale previous-frame flash | Implement `reset()` and prime state on first apply |
| Vignette/falloff backward | Test visually; smoothstep order matters |
| Logs don't show right values | Log before setting uniforms, not after |
| Slot not triggering | Verify effect is in `self._effects` dict and controller imports it |

---

## Testing Checklist

- [ ] Effect fires on hotkey press (check logs with `--log-level INFO`)
- [ ] Effect fades in/out smoothly (strength envelope working)
- [ ] Effect visible on 2–3 different effects (not effect-specific bug)
- [ ] Resize/fullscreen doesn't crash (resize() called correctly)
- [ ] Clean shutdown (destroy() releases all GL resources)
- [ ] Silent mode works (no errors with `--log-level NONE`)

---

## Future Improvements

- Per-slot configurable intensity scalar in config.toml
- Chaining/combining multiple effects in one burst
- Effect parameter randomization per trigger
- Custom control curves instead of simple linear fade
