# ProjectM-Only Mode + Effects Browser — Design Examination

Owner: Effects
Status: ProjectM-only mode IMPLEMENTED (Method A); effects browser still todo-soon
Last updated: 2026-06-30

> **Implemented 2026-06-30 (Method A).** Generic effect-lock at `_switch_effect`
> (`App._effect_lock`, exposed via `vj_api.lock_effect/unlock_effect/effect_lock`).
> Toggle: **Ctrl+L** (`App.toggle_projectm_only`) — on = switch to ProjectM +
> lock; off = unlock + advance to next effect immediately (owner decision #3).
> Auto-advance is suppressed while locked. A blocked switch redirects into a
> locked-effect variation (ProjectM `next_preset`), so Auto VJ keeps running its
> normal cadence but expresses it through pM presets (owner decision #2) with no
> Auto VJ code changes. Startup lock via `[effects.ProjectMEffect] only_mode`.
> Tests in `tests/test_hotkeys_projectm_only.py`.

Two related items:

1. **ProjectM-only mode** — a toggle that keeps the system in ProjectM the whole
   time, skipping system effects and other drop-in effects. ProjectM's own
   controls (preset next/prev, the `Ctrl+M` preset manager, search) keep working
   unchanged; the only new control is the mode toggle itself.
2. **Effects browser/loader** — a ProjectM-manager-style browser for *our*
   system effects + drop-in effects. Deferred ("todo soon") — see §4.

---

## 1. How effect switching works today (the relevant facts)

- ProjectM is a **playlist effect** (`ProjectMEffect`, display name
  `ProjectM Presets`), not a subsystem. It already owns a preset-manager modal.
- **Every** effect switch funnels through one chokepoint:
  `App._switch_effect(cls)` ([app.py](../../unicornviz/app.py)). Callers:
  - auto-advance (main loop, `playlist.advance()` → `_switch_effect`);
  - hotkeys / playlist nav → `App.goto_effect(cls)` → `_switch_effect`;
  - Auto VJ → `vj_api.goto_effect(name|cls)` → `goto_effect` → `_switch_effect`.
- `_switch_effect` **already blocks switches** while the ProjectM preset manager
  modal is open (`_projectm_manager_modal_active`). That is the exact precedent
  for a lock.
- Auto-advance is separately gated in the loop:
  `if not manager_modal_active and not self._paused and self._next_effect is None
  and self._auto_advance:`.

Implication: a single guard at `_switch_effect` (plus suppressing the
auto-advance timer) covers **all** switch sources at once.

---

## 2. Methods examined

### Method A — Generic effect-lock at the switch chokepoint  ✅ recommended

Add a generic `_effect_lock: str | None` to `App` (the locked display name).

- `_switch_effect(cls)`: if a lock is set and `cls.NAME != lock`, log + return
  (mirrors the existing manager-modal guard).
- Auto-advance loop gains `and self._effect_lock is None` so the timer doesn't
  even fire while locked.
- Entering pM-only: `goto_effect('ProjectM Presets')` once, then set
  `_effect_lock = 'ProjectM Presets'`. Exiting: clear the lock (stay on pM;
  rotation resumes on the next advance/hotkey).
- Expose via VJApi: `lock_effect(name)` / `unlock_effect()` / `effect_lock`
  property, so drop-ins and the control room use the public surface.

**Pros:** ~20 lines, central, reuses a proven pattern, covers every path
(hotkeys, number-jumps, auto-advance, Auto VJ) in one place. ProjectM's own
controls are untouched (they never call `_switch_effect`). **Generic** — not
hardcoded to ProjectM, so the future effects browser reuses the same lock to
"pin" any effect.
**Cons:** Auto VJ keeps evaluating and will attempt (blocked) swaps, producing
harmless "switch blocked" log lines. Optional refinement: have Auto VJ honor
`effect_lock` and stand down (it already reads `vj_api`), or demote the block
log to debug.

### Method B — Restrict the playlist to a single entry

On enter, swap the active playlist for a one-item `[ProjectM]` list (and restore
on exit).

**Pros:** auto-advance naturally never leaves ProjectM; no per-switch guard.
**Cons:** does **not** stop hotkey next/prev/random, number-jump-by-index, or
Auto VJ's `goto_effect(specificClass)` — those bypass the playlist. So it needs
the Method-A guard anyway. Adds save/restore playlist state. More moving parts
for strictly less coverage. Rejected as a standalone.

### Method C — ProjectM as an exclusive subsystem takeover

Promote pM-only to a modal/subsystem mode (like control-room) that suspends the
playlist/effect system entirely and routes rendering straight to ProjectM.

**Pros:** strongest "it is the only thing running"; could skip instantiating
other effects entirely (memory/CPU).
**Cons:** large change — pM is a playlist effect, not a subsystem; needs a
parallel render/ownership path and careful HUD/overlay/transition handling.
Overkill for the requirement. Revisit only if we want pM to run with the whole
effect pipeline torn down.

### Method D — Auto-VJ "lock to current effect" only

Use/extend an Auto VJ lock so automation stops swapping.

**Pros:** trivial if Auto VJ already has the concept.
**Cons:** covers Auto VJ only — manual hotkeys + auto-advance still switch.
Incomplete alone; would be a complement to A, not a substitute.

---

## 3. Recommendation

**Method A (generic effect-lock)**, because the architecture already centralizes
switching and already has the manager-modal precedent. Make the lock generic
(`lock_effect(name)`) rather than pM-specific so it doubles as the "pin this
effect" primitive the effects browser will want — keeping core drop-in-agnostic.

Open decisions for the owner:

- **Toggle surface.** The toggle must work from *any* active effect (you can't
  rely on ProjectM's own `handle_key` to enter the mode from elsewhere). Options:
  (a) one global hotkey in core `hotkeys.py`; (b) a control-room button via
  `vj_api.lock_effect`; (c) a `[effects.ProjectMEffect] only_mode = true` for
  startup-locked installs. Likely (a) + (c), with (b) when the control room grows
  the button. Pick the hotkey (a free, WM-safe chord).
- **Auto VJ behavior while locked.** Honor the lock and stand down (quietest), or
  leave it attempting blocked swaps (simplest). Recommend: Auto VJ checks
  `vj_api.effect_lock` and pauses swap decisions.
- **Exit behavior.** Stay on the current ProjectM preset and resume rotation, or
  also restore the pre-lock effect. Recommend: just unlock; stay on pM.

Estimated effort for A: core guard + auto-advance gate + VJApi surface + toggle
hotkey + config + a couple of unit tests (lock blocks non-pM, allows pM,
auto-advance suppressed). ~half a focused session.

---

## 4. Effects browser / loader  — `[todo soon]`

A ProjectM-manager-style browser for **system effects + drop-in effects**:
search/filter by name/tag, preview, enable/disable, and jump-to/pin (reusing the
Method-A `lock_effect` primitive). Mirrors `drop-ins/projectm-01`'s preset
manager UX but over `registry.get_effects()` + `discover_dropin_effect_classes()`.

Deferred per owner. Captured here and in the main plan's todo list so it is not
lost. Natural follow-on once the generic effect-lock lands (the browser's
"pin/lock" action is the same primitive).
