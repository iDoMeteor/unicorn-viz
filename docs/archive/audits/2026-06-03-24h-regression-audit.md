# 24-Hour Committed-Work Regression Audit (2026-06-03)

Owner: Core team (primary) + Audio team + Webcam/Multi-display team
Status: open — 2 confirmed regressions, fixes recommended below
Last updated: 2026-06-03

## Scope

This audit reviews **only committed work** landed in the trailing 24h window
(2026-06-02 17:16 → 2026-06-03 17:16): 32 commits on the main repo plus
submodule pointer bumps for `auto-vj-01` (1), `multi-head-01` (1),
`projectm-01` (5), and `webcam-01` (1).

- Window baseline for diffs: `f49e970~1` (`9ffb480`); HEAD = `a8658e4`.
- Committed-only diffs were isolated with
  `git --no-pager diff f49e970~1 HEAD -- <path>` so the **uncommitted ProjectM
  preset-manager work is explicitly out of scope** (per owner direction; that
  work already churned help/overlays/hotkeys and is being handled separately).

Priorities, in order: (1) regressions, (2) features "thought to have landed but
missed," (3) bonus bugs / optimizations.

## Verified healthy (no action needed)

These were checked and are correctly wired — recording here to prevent re-audit:

- **Prior-audit P0s are fixed.** `_profile_value` restored
  (`drop-ins/auto-vj-01/auto_vj.py:812`); `VJApi.show_splash()` added
  (`unicornviz/vj_api.py:244`); `find_effect()` 2nd arg now optional
  (`vj_api.py:234`); key-dispatch loop is now exception-isolated with
  auto-unregister (`unicornviz/hotkeys.py:263-268`).
- **MIDI presets landed.** `MidiManager` receives `preset`, `cc_map`, and
  `note_map` (`unicornviz/app.py:1962-1972`).
- **Audio profile is consumed.** `audio.profile` flows through
  `unicornviz/audio/manager.py:57` (`_profile_key`).
- **Audio device probe is safe.** `_probe_device_openable`
  (`unicornviz/audio/capture.py:303`) casts the device id to `int` before
  building the subprocess argv — no shell, no injection vector.
- **Webcam multi-camera support is fully wired.** `VJApi.goto_prev_camera()`
  / `goto_next_camera()` / `postfx_slot_duration()` delegate correctly and the
  drop-in (`drop-ins/webcam-01/webcam_overlay.py:434-437`) calls them with a
  local fallback.
- **Multi-display primary-viewport centering is guarded.**
  `App._primary_display_viewport()` (`unicornviz/app.py:777`) returns `None`
  outside `mirror_all`/`span_all`, so single-display overlay/splash rendering
  falls back to full canvas — no single-display regression.
- All audio/MIDI selector methods referenced by `hotkeys.py`/`overlays.py`
  exist on both `App` and `Overlays`. No dangling references in that subsystem.

---

## REG-1 (HIGH) — Wayland keyboard-grab fix was deleted

**Impact:** On the **primary target (Fedora 44 / GNOME Wayland)** the
compositor again intercepts `Ctrl+Alt+*` and other reserved chords, so a class
of application hotkeys is swallowed by the desktop and never reaches the app.
This is a straight reversal of a shipped fix.

**Evidence:**

- The grab block was added by `1cdd0dd` and refined by `20112cc`
  (Wayland-only + `window.keyboard_grab` config gate, default `True`).
- It was **deleted** inside `App._init_sdl()` by commit `156c585`
  ("Webcam multi-camera support: VJApi shims + app delegates") — an unrelated
  change. Removed lines:

  ```
  - _grab_enabled = bool(self.cfg.get('window', 'keyboard_grab', default=True))
  - if _video_driver == 'wayland' and _grab_enabled:
  -     sdl2.SDL_SetWindowKeyboardGrab(self._window, sdl2.SDL_TRUE)
  ```

- The trail was then erased by `c1fb299`
  ("chore: update config defaults…"), which removed the `keyboard_grab` default
  from `config.py`'s `_DEFAULTS["window"]`.
- Current tree: **zero** references to `SetWindowKeyboardGrab` or
  `keyboard_grab` anywhere in `unicornviz/`.

**Recommended fix (Core team):**

1. Restore the Wayland-gated grab block in `App._init_sdl()`, immediately
   before `self._set_cursor_visible(...)`:
   read `window.keyboard_grab` (default `True`), check
   `SDL_GetCurrentVideoDriver() == 'wayland'`, and call
   `SDL_SetWindowKeyboardGrab(self._window, SDL_TRUE)`.
2. Restore `keyboard_grab: True` to `_DEFAULTS["window"]` in `config.py`.
3. Re-document the key under the `[window]` section in
   `config.full.example.toml` (commented is fine).
4. Add a smoke check to the merge checklist: grepping for
   `SetWindowKeyboardGrab` must return a hit.

---

## REG-2 (MEDIUM) — Runtime ANSI art-source switching is now unreachable

**Impact:** The `a` (ACiD art) and `Shift+A` (own ANSI art) hotkeys that
switched the live ANSI art directory were removed. `App.goto_ansi()` still
exists (`unicornviz/app.py:3911`) but **no key binding invokes it** anymore, so
operators can no longer flip between their own art collection and the ACiD
collection during a set. The capability is orphaned, not deleted.

**Evidence:**

- Commit `e8fcf2d` ("Enhance audio source management") repurposed the entire
  `SDLK_a` family for the audio source selector
  (`unicornviz/hotkeys.py:531-566`): plain `a`, `Shift+A`, and `Ctrl+A` all now
  open the audio selector; `Ctrl+Shift+A` is intentionally unbound; `Alt+A` /
  `Alt+Shift+A` cycle BPM profiles. The previous `goto_ansi(acid_dir)` /
  `goto_ansi(own_dir)` calls were dropped from the diff.
- `grep goto_ansi unicornviz/hotkeys.py` → no matches (dead capability).
- Help text was rewritten to the new behavior
  (`unicornviz/overlays.py:401-403`), so the loss is **silent** — nothing
  surfaces the missing ANSI switch to the user.

**Note on intent:** The audio-selector overhaul itself looks deliberate and is
healthy. The collateral loss of ANSI source switching is the regression. This
needs an owner decision rather than a blind revert.

**Recommended fix (Core + Effects):** choose one —

- **(preferred)** Rebind ANSI source switching to a currently-free chord and
  re-add the matching `HELP_TEXT` lines in `overlays.py` (single source of
  truth for keys). Candidates that are free in the current map should be
  confirmed against `overlays.py` `HELP_TEXT` before assignment.
- **or** if the removal is intentional, delete the now-dead `goto_ansi()` from
  `app.py` and any now-unused ACiD/own-art directory plumbing so the dead path
  doesn't mislead future work.

Do **not** leave it half-wired (orphaned method + no binding).

---

## Minor findings (P3 / cosmetic)

- **Duplicated comment label.** The comment `# MIDI selector navigation`
  appears on both the audio-selector and the MIDI-selector navigation blocks in
  `unicornviz/hotkeys.py` (copy/paste). Harmless; relabel the audio block to
  `# Audio selector navigation` for clarity.
- **MIDI→keyboard re-entry.** New MIDI note handling re-enters the keyboard
  dispatch path via `self.handle(SDLK_a, 0)`. `MidiManager`'s callback runs on
  the `rtmidi` thread; this path now reaches `moderngl`-touching handlers
  indirectly. Confirm the MIDI note path only enqueues/handles on the main
  thread (per the MIDI threading rule) and does not dispatch GL-affecting
  actions directly from the callback thread.

## Suggested follow-up sweep

To catch future "landed-but-missed" regressions cheaply, add a pre-merge grep
gate that flags: (a) a config key added to `_DEFAULTS` but never read via
`cfg.get(...)`, (b) a `VJApi`/`App` method referenced in a drop-in but undefined
in core, and (c) a `HELP_TEXT` key entry with no matching `SDLK_*` handler (and
vice-versa, an orphaned handler like `goto_ansi`).
