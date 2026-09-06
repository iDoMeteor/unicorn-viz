# System audit — bugs and unexpected side effects (2026-09-05)

Owner: DJ Unicorn Tears
Status: complete — findings F1–F3 fixed and shipped; O1–O12 open, ranked
Last updated: 2026-09-05

Scope: the core package and every drop-in, taken as the shipped tree on
2026-09-05 evening.  Method: run every test suite (core + 24 drop-ins) with
the owner's `runtime/` and `logs/` directories snapshotted before and after;
bandit at medium+ and ruff over the whole tree; targeted sweeps for the
defect classes that have actually bitten this codebase this month — thread
races, silently swallowed exceptions, hand-written field copies,
`__file__`-relative persistent paths, tests reaching real state, GL objects
without a release; and a read of the shutdown order.

**Baseline.**  Core 2,355 passed; all 24 drop-in suites green (dj-mixer-01
1,105, media-01 170, spotify-01 144, control-room-01 107, webcam-01 88,
projectm-01 37, video-out-01 34, video-postfx-01 28, cta-01 28, candy-frame-01
25, audio-out-01 23, multi-head-01 21, beat-flash-01 18, color-grade-01 17,
lyrics-01 16, osc-bridge-01 15, streaming-01 14, chat-01 8, midi-controllers-01
7, postfx-01 7, sims-01 7, unicorn-tears-01 6, videos-01 5, grand-finale-01 4).
bandit: no medium-or-higher findings.  ruff: 39 style-level items in drop-ins
(31 unused imports), none in core.

---

## F. Fixed in this audit

### F1. Test suites were overwriting the owner's live state — severity: high

The single most damaging class found, and it explains several "mysteries"
from the last two weeks.  Every case is the same shape: code computes a
persistent path from its own `__file__`, a test constructs the object
without overriding that path, and the test's write replaces the owner's
file.  The hooks run these suites on every commit, so it recurred daily.

| Victim | Effect | Evidence |
|---|---|---|
| `runtime/media_library_cache.json` (10,843 tracks) | Replaced by four `/tmp/pytest…` entries.  Next launch re-read every tag: **7–14 s of main-thread stall at nine of the last ten launches** (311 ms the one time the cache survived). | file held 4 entries at 11:44; `scan … 0 cached, 10843 read` in nine session logs |
| `runtime/dj_mixer_state.json` | **The owner's session — four loaded decks — replaced by four empty decks** at 20:26:52 by `dj-mixer-01/tests/test_controller.py` (controllers built without `state_path`; their shutdown save wins). | mtime + content; last real decks in the 05:42 log |
| `logs/autovj-*.jsonl` | Three one-second synthetic decision logs per core test run, plus one per headless replay, in the directory `package_training_set.py` sweeps **wholesale into live-session training buckets**. | 14,574-byte files at 01:12, 05:47, 20:22, 20:23 … |
| `logs/faulthandler_*.log` | One empty file per faulthandler test run. | — |

**Fixed:**
- media-01 0.29.1: one cache file **per media root** plus `UNICORNVIZ_MEDIA_CACHE_DIR`; playlists path honors `UNICORNVIZ_APP_ROOT`.
- dj-mixer-01: every default path (track store, sets, stems, session state, recordings) goes through `_runtime_dir()`, which honors core's `UNICORNVIZ_APP_ROOT`.
- auto-vj-01 rc.128: `[auto_vj] log_dir` / `UNICORNVIZ_AUTOVJ_LOG_DIR`; training-kit-01 0.42.1: replays pass `log_dir=out_dir` (closing the gap the code's own comment described).
- `tests/conftest.py` in core, dj-mixer-01 and media-01: an autouse fixture redirects every path above to a temp root, and a **session-scoped guard fails the run if any test leaves a new file in `runtime/` or `logs/`**, naming the files.  This is the part that makes the class stay fixed.
- The owner's decks A and B were written back from the last session log (Roberto Pedoto @ 0.5 s, Fogsick @ 10.5 s); the test-written file is kept beside it as `dj_mixer_state.json.test-clobbered-20260905.bak`.  **Other tuned values in that file (dial defaults, toggles) may have been reset to defaults — the owner should glance at the mixer settings once.**

### F2. Track store: shared nested dicts mutated while the writer serializes — severity: medium

`save()` hands a *shallow* copy of the tracks dict to the writer; `remember()`
updated the nested marks dict **in place**, so a cue edit during a write
could raise "dictionary changed size during iteration" inside `json.dump` on
the writer thread and drop that save.  Pre-existing (analysis worker vs. main
thread), made likelier by the new async UI saves.  `remember()` now replaces
the entry with a fresh dict; a test pins it.

### F3. Earlier today, for the record

Media crossfade `SIGSEGV` (libvlc volume on a player with no aout); secondary
window overread (`glTexSubImage2D` past a short buffer); `_width` poisoned by
a drop-in layout tuple; APC USB writes stalling the render thread (534 ×
500 ms in one session); the mixer search freeze (10k `mutagen` opens per
keystroke); the 16 MB store save, library walk, coverage recount, per-row
stat storm, ProjectM catalog stub, `pactl` spawns, ffmpeg probe and playerctl
polls all moved off the main thread; the stall watchdog and faulthandler
cleanup.  All committed with their own regression tests.

---

## O. Open findings, ranked

### O1. `logs/replay/` holds 567 directories, 548 of them under 64 KB — severity: medium (data hygiene)

225 MB.  The tiny ones are consistent with one-clip harness or test runs
rather than real replays.  Because packaging sweeps `logs/`, anything here
can reach a training bucket.  **Owner decision: prune** (destructive, so not
done here); going forward the redirect in F1 stops the test share of it.

### O2. Exceptions swallowed silently inside per-frame paths — severity: medium

350 `except: pass/continue` sites in total; 71 are in `vj_api.py`, where a
drop-in's failure must not take the app down and that is by design.  The ones
worth attention are in **per-frame** code with no log call at all, where a
bug is invisible forever:

- `dj_mixer_controller.update()` — engine ticks (`follow_active_deck`,
  `_exchange_bpm`, `_publish_section`, `_tick_session`) share one bare
  `except: pass`.
- `auto_vj.update()` — `publish_bpm` and `set_expected_bpm`.
- `dj-mixer-01/ui.py on_sdl_event` — three handlers.

Recommendation: keep the guard, add a once-per-N-seconds `log.debug` with
the exception, so the debug run the owner is about to do can see them.

### O3. ProjectM destroys its shared GL bridge on a worker thread at `atexit` — severity: low–medium

`_shutdown_shared_bridge()` runs `bridge.destroy()` on a daemon thread with a
1 s join, i.e. GL calls off the context's thread.  Deliberate (isolates a
hang), but undefined behaviour on the driver side; the exit-time aborts
seen earlier this month came from the same neighbourhood.  Verify with the
stall/exit logs from the next debug run; if clean, leave it.

### O4. Hand-written `AudioData` field copies — severity: low (now)

Three sites existed this morning; one dropped `vocal_hnr`/`vocal_fmr`, one
never wrote `bpm` (effects always saw `120.0`).  Another seat has since
consolidated the copy into `unicornviz/effects/base.py`; the analyzer still
does not set `bpm`.  Recommendation: derive the copy from `__slots__` so a
new field cannot be missed again, and either set `bpm` or remove the field.

### O5. Spotify local poll: the "player unavailable" branch writes state outside the lock — severity: low

`_poll_playerctl`'s early return sets `_available/_is_playing/_status`
without `_state_lock` (the normal path commits under it since rc.6).
Harmless tearing at worst; one `with` block fixes it.

### O6. `App._open_external_url` never reaps `xdg-open` — severity: trivial

`Popen` without `wait()`; a zombie until exit.  `start_new_session=True`
plus letting `Popen.__del__` reap is enough.

### O7. Lint-level real bugs — severity: low

- `auto_vj.py:5572` — `'genre_evidence_applied_count'` appears twice in the
  telemetry dict (same expression; harmless duplicate, confusing).
- 4 unused locals (`control_room.py` ×3, `effects-vector/vector.py`), 31
  unused imports across drop-ins.

### O8. Threads — severity: informational

50 thread-creation sites, **all daemon**.  Twelve are stopped and joined on
shutdown; the rest are fire-and-forget workers (prefetch, probes, prewarm,
playerctl, pactl refresh).  The only one whose loss at exit costs data is the
new `DjMixerStoreWriter`; the controller's per-frame `_flush_dirty_marks()`
calls the blocking `save()`, which drains it — but see O9.

### O9. Cue edits still save the 16 MB store synchronously — severity: medium (perf)

`dj_mixer_controller._flush_dirty_marks()` runs from `update()` and calls
`self._tracks.save()` (blocking) as soon as marks are dirty — the
"immediate flush" from upcoming-work item E.  0.190.1 moved the *UI
actions'* saves onto the writer thread but not this path, so a hot-cue press
still costs a whole-file write on the main thread.  Switch it to
`save_async()` and add a `flush()` in `shutdown()`.  **(Fixed in the same
commit as this document; listed here so the reasoning is findable.)**

### O10. `[logging] performance_logging` is a dead key — severity: low

Read by nothing; `perf_frames` is the real switch and is DEBUG-only.
Documented in `docs/configuration.md` today; remove the dead key from
config.toml when convenient (owner file — not touched).

### O11. Persistent paths computed from `__file__` in drop-ins — severity: low (residual)

Fixed for dj-mixer-01 and media-01 (F1).  Remaining `__file__`-relative
writers: `training-kit-01/keystroke_logger.py` (`logs/`, tests already use
temp dirs), projectm-01 (uses core `APP_ROOT`, already override-aware).
Recommendation: every drop-in that persists anything derives its root from
`UNICORNVIZ_APP_ROOT` first — one helper each, no shared import.

### O12. The shared working tree and the pre-commit stash — severity: medium (process)

Every seat commits in one checkout.  pre-commit stashes *all* unstaged
changes to lint the staged set; today that stash removed another seat's
edits from the tree twice (recovered from `~/.cache/pre-commit/patch*`), and
their uncommitted WIP made every other seat's hook fail on files they never
touched.  Nothing in the code fixes this.  Recommendation: one `git
worktree` per seat, sharing the repository; hooks then only ever see the
committer's own tree.

---

## What this audit did not do

It did not exercise hardware paths (APC, DDJ-REV1, S4 MK3), the GL pipeline
under a real driver, or network drop-ins against their services — those are
soak items, not suite items.  It did not read every effect shader.  And it
found no way to reproduce the 2026-09-05 mixer-search hang under test; the
stall watchdog exists so the next one reports itself.
