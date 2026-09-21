# Multi-head Control Room surface — audit & monitor-assignment proposal

Owner: overlays / core manager seat
Status: Findings; awaiting consensus before implementation
Last updated: 2026-09-21

Two asks: (A) the Displays page's include/exclude toggle "seems a little
buggy" — diagnose it; (B) let the operator assign which monitor the mixer
and Control Room windows themselves open on, from inside the app. No code
changed for this doc — read-only investigation, reported for a plan.

## A) The include/exclude toggle

Read all of `drop-ins/multi-head-01/multihead.py` (605 lines, the whole
thing) plus its dispatch path through `control-room-01/control_room.py`
(`_panel_canvas` → `_draw_page` → `_dispatch_page_action`). Checked
coordinate spaces, hit-region math, and the toggle/reset/save state
machine line by line.

**What's actually correct.** The toggle mechanics themselves have no
logic bug: `toggle_pending_exclude()`'s set membership and its return
value are internally consistent with the button label and the
EXCLUDED/INCLUDED tags; the map markers and list rows draw and register
their hotspots with the same rect in the same coordinate space (I
specifically checked the list rows' `rounded_rectangle` corners against
their registered hotspot width/height — they match); `page_action:`
dispatch correctly unwraps payload only when it's the wrapped-button dict
shape, and multihead's own `_draw_button` never sends that shape, so
nothing is silently dropped there.

**One real bug found: RESET ignores the runtime-store source.**

```python
def reset_pending_excludes(self) -> None:
    """Discard staged edits, reverting to config.toml's exclude list."""
    self._pending_excluded_display_indices = self._parse_excluded_display_indices(
        self._cfg.get('window', 'exclude_display_indices', default=[])
    )
```

`self._excludes_source` already tracks whether the *live, active* exclude
set came from `config.toml` or from a prior SAVE (persisted under
`multihead.monitor_editor.exclude_display_indices` in the runtime store —
see `__init__`'s `runtime_excludes` parameter). RESET always discards
back to `config.toml` regardless, so on a machine where the operator has
already saved excludes once, pressing RESET on the Displays page silently
reverts to a value that may have nothing to do with what's actually
running. Should instead revert to `self._excluded_display_indices` (the
current live/active set) — that's what "discard my edits" should mean.
Small, contained fix (one method body), not blocked on the item below.

**Lower-severity smell: two independent live queries instead of one
snapshot.** `_draw_displays_page` and `_displays_page_action`'s
`toggle_exclude` branch each call `self.all_detected_displays()`
separately — a fresh SDL query each time rather than sharing one
snapshot. In practice SDL's enumeration order is stable within a session,
so this only has a window to bite around a hot-plug/unplug landing
between a draw and the next click. Worth threading one shared snapshot
through if this page gets touched anyway; not urgent on its own.

**The likely source of "seems a little buggy": the feature is staged +
restart-required, and nothing on screen says so at the point of action.**
Toggling EXCLUDE updates `_pending_excluded_display_indices` and the
map/list badge *immediately* — it looks like it took effect. SAVE
persists that to the runtime store. But nothing about the *actual*
span/mirror geometry (`_excluded_display_indices`,
`_refresh_active_layouts()`, the real window bounds) changes until the
whole app restarts — the only warning is one line of dim text at the
bottom of the panel ("Saved excludes apply on next launch."), easy to
miss under the buttons an operator just used. Worse: if you then press a
*mode* hotkey (Shift+X etc.), that change **is** live — `set_display_mode()`
repositions/resizes the window immediately — so in the same session an
operator can toggle an exclude (feels immediate), save it (still nothing
visibly changes), then switch modes (visibly changes, using the *old*
exclude set) — three actions with three different immediacy models, on
one page. That inconsistency, not a code defect, is my best read of "a
little buggy."

**This turns out to be fixable, not just documentable.** I checked
`App.set_display_mode()` (`unicornviz/app.py:7734`): mode changes already
call `_log_video_displays()` to refresh layout, then reposition/resize
the live SDL window — the exact machinery a live exclude-apply would also
need. Nothing here needs inventing. A live-apply redesign would mean: on
SAVE (or even on each toggle), write straight into
`self._excluded_display_indices` instead of only the staged copy, call
`_refresh_active_layouts()`, and re-invoke `set_display_mode(self._display_mode)`
to re-lay-out the window immediately if currently in a `*_included` mode.
The "restart required" design predates this and looks like caution rather
than a hard constraint — worth deciding deliberately rather than by
inertia.

## B) Assign a monitor to the mixer and Control Room windows

**Current state, confirmed by reading both drop-ins' window lifecycle
(`control-room-01/control_room.py` and `dj-mixer-01/ui.py` — near-identical
patterns):**

- Both read `display_index` from `config.toml` exactly once, in
  `__init__`, into a plain mutable instance attribute
  (`self._display_index = int(self._cfg.get('display_index', 1) or 1)`).
  There is no in-app control for either today — config.toml only.
- Both destroy and recreate their SDL window on every open/close toggle
  (`_destroy_window()` / `_create_window()` — confirmed by reading the
  toggle/shutdown/close_now methods in both files). `_create_window()`
  reads `self._display_index` fresh each time it runs.
- Control room additionally has `_resolve_target_display_index()`: if in
  single-display mode and the requested display would collide with the
  audience output, it silently falls back to `(requested + 1) % count`.
  The mixer has no equivalent — it always opens exactly on
  `self._display_index`, no collision avoidance.
- `[window] display_index` (the audience output) defaults to `0`;
  `[control_room]` and `[dj_mixer] display_index` both default to `1` —
  the two operator windows are already meant to land off the audience
  monitor by default, just not adjustable without an editor.

**The useful consequence of that lifecycle:** because `self._display_index`
is a plain attribute re-read at every window (re)creation, and the window
is already destroyed/recreated on every toggle, **reassigning a monitor
does not need a full app restart** — only a close + reopen of that one
window, which is the normal way an operator already interacts with these.
Persisting the choice so it survives an actual app restart is the same
runtime-store-override-over-config-default shape control-room-01 already
uses for `ui_scale` and `theme` (`_initial_ui_scale()` /
`_initial_theme_name()`, reading `control_room.<key>` from the runtime
store, falling back to `config.toml`) — `display_index` would be one more
key in that same shape, for both drop-ins.

**Two ways to surface the control; recommend the first, listing both for
consensus:**

1. **Extend the Displays page.** It already draws a live map + list of
   every detected monitor with click-to-select — the natural home for
   "put the mixer/Control Room here" too, next to the existing
   include/exclude controls. Add two more action buttons ("MOVE MIXER
   HERE" / "MOVE CONTROL ROOM HERE") that set the target window's live
   `display_index` and persist it, reusing the map/list/selection code
   that's already built. Ties directly into the item above: one page
   becomes the single "which monitor shows what" surface instead of
   three scattered ones. Reaching the mixer/control-room controller from
   `multi-head-01` needs a small new surface — today `MultiHeadController`
   only reads display topology, it doesn't hold references to the other
   two windows; `vj_api` would need a couple of narrow setters
   (`set_control_room_display(index)` / `set_mixer_display(index)`) for
   the Displays page to call through, matching the "prefer `vj_api`
   first" rule.
2. **A row on each drop-in's own config-editor Performance/Visuals tab**
   (the contributor convention this session's audit already wired
   through nine other drop-ins) — a choice row listing detected
   displays, `restart`-badged or not depending on which live-apply
   decision comes out of item A. Keeps "which monitor" as each
   window-owning drop-in's own concern rather than multi-head's, at the
   cost of the operator having to visit two different tabs instead of
   one map.

Nothing here is mutually exclusive with fixing (A) first — the
live-apply plumbing (A) and the live-reassignment plumbing (B) are the
same shape (mutate live state, call the existing reposition/relayout
path, persist to the runtime store), so doing them in the same pass would
avoid touching this window-lifecycle code twice.

## Open questions for consensus

1. **(A) Live-apply or keep restart-required for excludes**, and if kept,
   should the "applies on next launch" warning be louder / closer to the
   SAVE button so it can't be missed mid-action?
2. **(A) Fix RESET's source bug** regardless of the live-apply decision —
   assume yes unless told otherwise, it's small and unambiguous.
3. **(B) Displays-page buttons vs. per-drop-in config-editor rows** — or
   both, sequenced.
4. **(B) Mixer needs `_resolve_target_display_index()`-style collision
   avoidance too?** Right now only Control Room avoids landing on the
   audience display; worth the same treatment, or leave it operator-error
   since the Displays page would make the collision visible on the map.
5. **(B) What happens if two operator windows are assigned the same
   display** — first-come-first-served with a flash warning, or should
   assigning one to a monitor another already occupies auto-bump the
   other, mirroring the existing audience-collision fallback?
