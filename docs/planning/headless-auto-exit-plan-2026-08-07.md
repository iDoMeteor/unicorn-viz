# Auto-Exit on Set End — dj-mixer-01 + media-01

Owner: DJ Mixer team (dj-mixer-01), media-01 team, auto-vj-01/core (the watcher, §4)
Status: **implemented, 2026-08-07** — all four sections below have shipped.
Requested by: repo owner, 2026-08-07
Last updated: 2026-08-07

---

## Status

All four requested changes are done:

- **§1 (dj-mixer-01: `AutoPlay.loop` defaults `False`)** — shipped, dj-mixer-01
  0.162.0. Went further than asked: `AutoPlay.LOOP_DEFAULT = False`
  (`autoplay.py:229`) is now the single source of truth so the fresh-boot
  default and the session-restore default (§1's open question) can't drift
  from each other independently.
- **§2 (media-01: real `loop` concept, default `False`)** — shipped, media-01
  0.20.0, as `repeat` (`all`/`one`/`off`, default `off` — `off` already meant
  "stop at the end," it just needed §3's announcement wired to it).
- **§3 (signal "session over")** — shipped on both sides.
  `AutoPlay.on_night_over` (`autoplay.py:193`) → `DjMixerController.
  _on_night_over()` → `_publish_session()` (`dj_mixer_controller.py:1083-
  1223`) publishes `phase: 'over'`, `source: 'list_exhausted'`. media-01's
  `_note_set_over()` (`media_controller.py:1045-1069`) publishes the
  identical shape. Both deliberately match the *existing* timer-driven
  `phase: 'over'` shape byte-for-byte, confirmed against `session.py:134` —
  no format negotiation needed between the three publishers.
- **§4 (wire "over" → grand finale → app exit)** — shipped, auto-vj-01
  1.0.0-rc.25 / core (this session's own part; see README changelogs for
  the exact core version). Turned out to
  need **no change** to the "over" → finale trigger half: `_check_timed_
  finale()` (shipped 2026-08-06) already reacts to `seconds_left: 0.0`
  (which both night-over payloads publish) exactly like a timer running
  out — the lead-time gate (`remaining > self._finale_lead_s`) is
  immediately false at `0.0`, so it fires right away. The exact version
  numbers are in the drop-ins' own changelogs; the only new code is
  the second half: new `VjApi.grand_finale_active` (`vj_api.py`) exposes
  `GrandFinale.is_active`'s True→False completion edge, and new
  `AutoVJController._maybe_exit_after_finale()` watches it — once seen
  active then inactive, calls `vj_api.request_exit(force=True)`. A 20 s
  grace window covers the case where the finale never becomes active at
  all (drop-in missing, trigger failed) so an unattended run still ends
  rather than hanging forever. New `[auto_vj] auto_exit_after_finale`
  config key, **default off** — a normal live performance must never
  auto-quit after a finale, and the watcher only ever arms behind the
  *timed* trigger (`_timed_finale_fired`), never a manual `Ctrl+Alt+F`.

`tools/training_daemon.py` needed zero changes for any of this, as
predicted — it already just waits for the process to exit and packages
immediately after, regardless of why.

**To actually use it end to end:** just `unicornviz --dj-mixer-source` /
`--media-source` (or `training_daemon.py --source dj-mixer`/`media`) — as
of the same day, `_build_overrides()` (`__main__.py`) sets `[auto_vj]
auto_exit_after_finale = true` automatically whenever either headless
source flag is passed. No separate flag, no `config.toml` edit: a
headless source *is* a headless run, so the set ending implies the
process should too. (`auto_exit_after_finale` remains a real config key
for anyone driving `unicornviz` directly without either source flag —
e.g. a Spotify session with a configured `show_duration_min` — it's just
no longer something the two headless CLI paths need to remember to set.)

---

## Goal

Closes the last gap in unattended headless operation: today, packaging is
already automatic (`tools/training_daemon.py` runs the packager the moment
`unicorn-viz` exits, for every audio source — see `docs/adr/vj-system.md`
§ "Headless Training: dj-mixer-01/media-01 as Audio Sources") — but nothing
makes `unicorn-viz` exit on its own. The target workflow: throw a
pre-arranged set at it from the command line with `--record` on, walk away,
and come back to a fully packaged, uploadable recording. No manual `Q` /
`Ctrl+C` needed.

---

## Current state (verified 2026-08-07, code citations below)

**1. The exit mechanism already exists.** `App.request_exit(force: bool =
False)` (`unicornviz/app.py:6370-6375`), exposed as `VjApi.request_exit()`
(`unicornviz/vj_api.py:302`). With the default `force=False` it blocks on a
modal SDL confirmation dialog (`_confirm_exit_dialog()`). **Any automated
caller must pass `force=True`** — under Xvfb/headless there is no one to
click the dialog, and the process will hang forever waiting on it.

**2. Two independent "the set is over" signals exist, and neither is wired
to exit today:**

- **dj-mixer-01 AutoPlay "night over."** `_pick_index()`
  (`autoplay.py:997-1000`) returns `None` once `self.loop` is `False` and
  the bound list (shuffled or not) is exhausted — the comment there already
  calls it by name: *"end of the list, loop off — night over."*
  `_arm_next()` (`autoplay.py:1122-1163`) just does a silent `return` when
  the pick comes back `None`. No event fires, nothing logs it — the decks
  eventually go quiet and the app just sits there.
- **`[dj_mixer] session_minutes` timer.** `SessionClock` (`session.py`)
  sets `phase: 'over'` once its countdown reaches zero (`session.py:134`),
  published via the `publish_session()`/`get_session()` bus (shipped
  2026-08-06) that already reliably drives the grand-finale hand-off
  (auto-vj-01's `_check_timed_finale()`, shipped 2026-08-07). Nothing
  currently reacts to the finale sequence it triggers *finishing*.

**3. grand-finale-01 already exposes the completion signal, just unused for
this.** `GrandFinale.is_active` (`grand_finale.py:263-270`) is `True`
during PEAK/DROP/OUTRO/BLACKOUT and `False` once the sequence returns to
idle after the BLACKOUT tail — a clean True→False edge to watch for "the
finale has fully finished." No new state needed to detect it.

**4. Two defaults independently work against this goal, before the exit
question even comes up:**

- `AutoPlay.loop` defaults `True` (`autoplay.py:213`). Even a shuffle that
  correctly deals a real, ending permutation (0.156.0: "Shuffle is a
  permutation, and it ends") gets reshuffled and restarted forever by
  default, because `loop` is a second, independent flag that overrides
  "ends."
- **media-01 has no loop concept at all.** `_advance()`
  (`media_controller.py:1039-1046`) unconditionally wraps
  `% len(view)` — there is currently no way to make a media-01 session end
  on its own, shuffled or not.

**5. `tools/training_daemon.py` needs no changes for any of this.** It
already just does `uviz_proc.wait()` unconditionally and doesn't care *why*
`unicorn-viz` exited (`Q`, `Ctrl+C`, crash, or — once this lands — a
self-triggered exit); packaging runs immediately after, regardless. Once
the pieces below land, the daemon "just works" with no coordination needed.

---

## Requested changes

### 1. dj-mixer-01: `AutoPlay.loop` defaults to `False`

`autoplay.py:213`: `self.loop = True` → `self.loop = False`.

Open question for you: `_restore_state()` reads
`state.get('autoplay_loop', True)` (`dj_mixer_controller.py:457-458`) as a
*separate* default used only for session-restore — should that flip too,
or does it stay `True` since it's resuming a real DJ's saved session rather
than a fresh boot? The two defaults are currently independent; flagging
rather than assuming.

### 2. media-01: add a real `loop` concept, default `False`

- New `[media] loop` config key (bool, default `False`), alongside the
  existing `shuffle`.
- `_advance()`/`next_track()` need a "loop off, list exhausted" path
  mirroring dj-mixer-01's: when the (shuffled or sequential) list is
  exhausted and `loop` is off, stop advancing — pause, don't wrap — instead
  of today's unconditional `% len(view)`.
- dj-mixer-01 already solved the harder half of this problem (0.156.0:
  dealing a real, non-repeating shuffle permutation —
  `_shuffle_order`/`_shuffle_pos`/`_reshuffle`, `autoplay.py:970-1001`).
  media-01's fix may be able to borrow that shape directly rather than
  reinventing it — same underlying bug (shuffle-with-replacement that never
  ends, vs. a dealt permutation that does).

### 3. Signal "session over" instead of going silently idle

Both current sources of "the set is done" currently just stop, quietly.
Both need to actually signal it:

- **AutoPlay night-over** (`_arm_next()` returning early on `idx is
  None`): needs to surface this — e.g. a new callback, or simplest, reuse
  the existing `publish_session()` bus with `phase: 'over'` (the same
  phase the timer path already publishes), so a downstream consumer
  doesn't need to know or care which of the two reasons fired it.
- **media-01's new loop-off-exhausted state**: same treatment.

### 4. Wire "over" → grand finale → app exit

Once `phase: 'over'` is published (from *either* the timer or a genuine
"list exhausted, loop off"), and the grand-finale sequence it already
triggers (auto-vj-01, unchanged by this plan) finishes:

- Watch `GrandFinale.is_active` for the True→False edge, once it has
  actually fired at least once.
- Call `app.vj_api.request_exit(force=True)` — **`force=True` is not
  optional** for this path; see point 1.
- Needs a decision on **where this watcher lives** — it crosses
  grand-finale-01 (which already owns `is_active`), dj-mixer-01/media-01
  (which own "session over"), and core (`app.py`, which owns the exit
  call). Whichever of you takes it, it should almost certainly be gated
  behind an explicit opt-in — e.g. only auto-exit when the session was
  started via a flag/config meant for unattended runs — so a normal live
  performance doesn't unexpectedly quit `unicorn-viz` mid-show right after
  a finale.

---

## Why now

Closes the loop with today's other 2026-08-06/07 work: the headless
training daemon (`docs/adr/vj-system.md` § "Headless Training:
dj-mixer-01/media-01 as Audio Sources"), the set-clock bus (§ "Set-Clock
Hint Bus: `publish_session()`/`get_session()`"), and the finale trigger
that already consumes it (§ "Grand-Finale Trigger Consumes the Set-Clock
Hint"). Once this lands: `--record` + a pre-arranged set/playlist +
`--source dj-mixer`/`--source media`, walk away, and `unicorn-viz` exits
itself the moment the finale completes — packaging (already automatic)
picks it up from there with zero further wiring.
