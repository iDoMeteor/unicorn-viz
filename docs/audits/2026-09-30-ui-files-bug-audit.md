# UI files bug audit: overlays.py and the mixer window (2026-09-30)

Owner: DJ Unicorn Tears
Status: complete — all findings open; nothing fixed in this pass
Last updated: 2026-09-30

Fourth report of the 2026-09-30 series, after
[2026-09-30-bug-audit.md](2026-09-30-bug-audit.md),
[2026-09-30-auto-vj-director-recommender-audit.md](2026-09-30-auto-vj-director-recommender-audit.md)
and [2026-09-30-windows-bug-audit.md](2026-09-30-windows-bug-audit.md).
The first report listed these two files as "not read line by line"; this
closes that gap.

**Scope.** Every line of the two biggest UI files, bugs only (performance is
deferred, as before):
- `unicornviz/overlays.py`: 7,433 lines, core `1.0.0-beta.180`, master
  `e8c3485`.
- `drop-ins/dj-mixer-01/ui.py`: 13,294 lines, dj-mixer-01 `0.222.0`
  (`87dbba9`).

Where a finding depends on a caller or callee (engine, track store, sets,
core dispatch), that code was read too and is cited.

**Method.**
- Read both files top to bottom.
- Checked each suspect path against the code it calls.
- Reproduced what could be reproduced off-hardware. The scripts live in
  `/var/tmp/uv-bug-audit/`:
  - `hosted_input.py` (U1)
  - `roll_tap.py` (U3)
  - `glyph_id_reuse.py` (U13)

Marked **VERIFIED** where reproduced. The rest cite exact lines.

## Summary

| ID | Sev | Where | Bug |
|---|---|---|---|
| U1 | P1 | `ui.py:1802` | Mixer-only boot profile: the console ignores every mouse and key event. **VERIFIED** |
| U2 | P2 | `overlays.py:1190` | Any non-ASCII character draws as the wrong glyph (`·` shows as `7`, `—` and `→` are blank, `é` shows as `i`), including track titles on the audience output |
| U3 | P2 | `ui.py:4344`, `rev1_input.py:494` | A quick tap on a quantized ROLL or TRANS pad leaves the roll looping, or the gate on, after release. **VERIFIED** |
| U4 | P2 | `ui.py:9140` | THROW OUT ignores hamster (which SCRATCH MODE turns on): it fades *to* the thrown deck, then ejects it, leaving dead air |
| U5 | P2 | `ui.py:9747` | Re-building a Smart List in the same minute (or at the same HH:MM another day) appends to the old set |
| U6 | P2 | `ui.py:4517` | LIBRARY → BACKUPS → RESTORE is undone by the next store save |
| U7 | P2 | `ui.py:772` | The mixer window can never open on display 0 (`or 1` turns 0 into 1) |
| U8 | P2 | `overlays.py:4018`, `4139` | Audio and MIDI selector panels grow without limit and run off-screen when there are many devices |
| U9 | P3 | `overlays.py:4279` | Webcam editor draws only 12 cameras; a selection past 12 is invisible |
| U10 | P3 | `overlays.py:5828` | Help cards that don't fit are silently dropped, but focus and Enter can still land on them |
| U11 | P3 | `overlays.py:5268` | SYSTEM MONITOR's "FRAME MS" row shows `33 − frame_ms` |
| U12 | P3 | `overlays.py:6399` | Drop-in help section colours change on every launch (salted `hash()`) |
| U13 | P3 | `ui.py:640` | Pillow path: after closing and reopening the mixer, labels can draw at the wrong size (glyph cache keyed by a reused `id(font)`). **VERIFIED** mechanism |
| U14 | P3 | `ui.py:666` | `_ScaledDraw` doesn't scale `polygon`/`arc`, so those glyphs land in the wrong place at `ui_scale` < 1 |
| U15 | P3 | `ui.py:8349` | At `ui_scale` ≠ 1, multi-line tooltips draw as one very wide single-line box with the text spilling out |
| U16 | P3 | `ui.py:5080`, `5236` | EDIT TAGS and search can't type shifted punctuation: `(`, `)`, `&`, `:`, `!` |
| U17 | P3 | `ui.py:6919`, `7162` | Platter beat ring and pad beat sparkle ignore `beat_offset`, so they flash off the grid |
| U18 | P3 | `ui.py:6111` | SPARKLE < 1 builds two fresh sprites per frame, and the GPU atlas pins every one until it resets |
| U19 | P3 | `ui.py:6967` | Pad-face tile cache is never evicted and grows with every window size |
| U20 | P3 | `ui.py:9089` | THROW OUT on deck 3 or 4: the fade does nothing (C/D aren't on the crossfader), then the deck ejects mid-tail |
| U21 | P3 | `ui.py:12650` | Context menus aren't clamped or scrolled: "Add to set »" with many sets runs off-screen, and long labels overrun the 170 px box |
| U22 | P3 | `ui.py:12410` | SETTINGS → GENERAL: the SECTIONS chip shows the old DIAL RESET tooltip, and the SECTIONS tooltip sits on empty space |
| U23 | P3 | `ui.py:13108`, `11349` | Stale advice to use `config.toml`: every empty view says "set [dj_mixer].music_dir", and the RECORDING tooltip points at a config key |
| U24 | P3 | `overlays.py:1698` + 4 sites | Centred titles and labels assume 8 px per character, not the real glyph advance, so they sit off-centre |

## P1

### U1 — Mixer-only boot profile: the console takes no input (VERIFIED)

**Where.**
- `drop-ins/dj-mixer-01/ui.py:1801-1803` (`on_sdl_event`).
- `unicornviz/app.py:5983`: the mixer boot profile sets `hosted = True`.
- `app.py:1405-1417`, `6732`: claimed-window dispatch consumes the event.

**Failure.**
1. In hosted mode the console claims the *main* window's events
   (`ui.py:1406-1423`).
2. Core hands every main-window event to `on_sdl_event` and `continue`s past
   its own handling.
3. `on_sdl_event` opens with
   `if self._pending_shutdown or self._window is None or not _SDL_OK: return`.
   Hosted mode keeps `self._window` at `None` for its whole life
   (`ui.py:1404`).
4. So every click, drag, wheel and key is thrown away.
5. Core hotkeys don't see them either: the claimed handler already consumed
   them.

In the mixer-only profile the whole application is therefore input-dead,
including Esc-Esc quit (`_hosted_quit`). Only the OS close button still works.

**Repro.** `hosted_input.py`: a hosted window with `is_open == True` gets
Esc; `_close_confirm_deadline` stays `0.0`.

**History.** The guard is from the original window (`c6acd93`). Hosted input
was added later (`b15aad6`) without updating it.

**Fix.** Guard on `not self.is_open`, the predicate the render loop already
uses, instead of `self._window is None`. Then add a hosted-mode
`on_sdl_event` test.

## P2

### U2 — Non-ASCII text draws as the wrong glyphs

**Where.** `overlays.py:1190`: `code = ord(ch) & 0x7F` over a 128-glyph ASCII
atlas.

**Failure.** Masking folds every code point above 127 onto an unrelated
ASCII cell.
- Core's own strings hit it:
  - tour eyebrow `·` renders as `7` (`overlays.py:3747`);
  - `—` becomes cell 20, which is blank:
    - `4170` "(none — disable MIDI)";
    - `4556` " — key: ";
    - `4751` "No presets yet — press S…";
    - `6028` "Page n/m — PageUp/PageDown";
  - `hotkeys.py:1586` flashes "BPM → Auto VJ", and `→` is blank too.
- Anything that passes through `draw_text` is mangled: the HUD title, the
  banner (now-playing text) and flash messages. On screen, "Beyoncé" reads
  "Beyonci" and "Ólafur" reads "Slafur", on the audience output.

**Fix.**
- Map unknown code points to `?` (or a transliteration table: `—`→`-`,
  `·`→`.`, `→`→`->`, accented letters to their base letter) instead of
  masking.
- Longer term, build a Latin-1/CP437 atlas from the bundled TTF.

### U3 — Quick tap on a quantized ROLL or TRANS pad sticks (VERIFIED)

**Where.**
- Press: `ui.py:4400-4411` schedules `set_loop(beats, roll=True)` or
  `trans_rate` through `deck.schedule_quantized` (`deck.py:2344`).
- Release, immediate: `ui.py:4344-4358` (`_release_pad`),
  `rev1_input.py:492-496` and `rev1000_input.py:498-502`.

**Failure.**
1. `quantize_for('roll', beats)` quantizes a roll to its own length, so a
   4-beat pad pressed one beat into a bar waits 3 beats (~1.5 s at 120 BPM).
2. A tap shorter than the wait releases first.
3. Release calls `exit_loop()` (nothing to exit yet) or sets
   `trans_rate = 0`.
4. The deferred action then fires, and the roll loops (or the gate chops)
   until something else clears it.

Mouse and both REV controllers share the bug.

**Repro.** `roll_tap.py`: deferred wait 3.0 beats; after the release and
4 s of render, the loop is still active with `roll=True`.

**Fix.**
- Hold a token for the pending action.
- On release, cancel it if it hasn't fired.
- Or, if released before the grid line, run the press and release as one
  quantized unit.

### U4 — THROW OUT fades the wrong way with hamster on

**Where.**
- `ui.py:9140`: `self._xf_fade_target = 1.0 if st['fx'] == 'fx1' else 0.0`.
- The engine applies `cf = 1 - crossfader` under hamster
  (`mixer_engine.py:1073`).

**Failure.**
1. With hamster on, a throw-out on FX1 (deck 1) drives the fader toward
   deck 1.
2. The incoming deck 2 fades to silence.
3. Deck 1 is then ejected: dead air.

SCRATCH MODE turns hamster on (`mixer_engine.py:1164-1180`), so this is the
normal state during a scratch set.
- The `◄◄`/`►►` auto-fade handler already corrects for hamster
  (`ui.py:4953-4955`).
- The engine has a hamster-aware helper, `xfade_pos_for()`
  (`mixer_engine.py:1220-1223`).

**Fix.** Target `eng.xfade_pos_for(other_side_deck)`. U20 is the related
deck 3/4 case.

### U5 — Smart List rebuild merges into an older set

**Where.** `ui.py:9747-9752`: `name = time.strftime('Smart %H:%M')`, then
`sets.create(name)` and `sets.add(name, paths)`.

**Failure.**
- `create()` is `setdefault` (`sets.py:92`), and `add()` appends every
  non-duplicate (`sets.py:142-149`).
- Tweak the tempo and press BUILD again within the minute, or build at the
  same HH:MM on a later night, and the new walk lands on the end of the
  earlier set.
- The result is over-long and out of order. The toast describes only the new
  build.

**Fix.** Make the name unique (date plus a suffix while taken), or clear the
set before adding.

### U6 — Library backup restore is silently undone

**Where.**
- `ui.py:4517-4534` (`lib_restore`).
- `track_store.py:83-108` (`restore_backup`).
- `track_store.py:511-560` (`save`, `_queue_payload`).

**Failure.**
1. Restore copies the backup over the store *file*.
2. The running `TrackStore` keeps its pre-restore `_tracks`/`_paths` in
   memory.
3. The next save serializes that memory over the restored file.
   Saves come from:
   - every cue, section or sample edit (`save_async(force=True)`);
   - the end of an analysis run (`browser.py:1317`);
   - a delete.

The toast says "restart the mixer to load them", but anything that saves
before or during that restart reverts the restore. The `.pre-restore` copy is
the only trace.

**Fix.** Reload the store in place after a restore (`_tracks`, `_paths`,
clear dirty), or mark it read-only until restart.

### U7 — Mixer window can't open on display 0

**Where.** `ui.py:772`: `int(self._cfg.get('display_index', 1) or 1)`.

**Failure.**
- `_apply_stored_display_index` (`dj_mixer_controller.py:1639-1640`) writes a
  stored "MOVE MIXER HERE" choice of `0` into the config.
- `0 or 1` evaluates to `1`, so on a multi-monitor rig the mixer never
  reopens on the primary display.
- `test_display_index.py` sets `_display_index` directly and never goes
  through this line.
- Same pattern: `tooltip_delay_s = 0` becomes `0.55` (`ui.py:1040`).

**Fix.** `cfg.get(...)` with an explicit `None` check.

### U8 — Audio and MIDI selectors have no row cap or scroll

**Where.** `overlays.py:4018` and `4139`:
`panel_h = 80 + n_rows * row_h + 56`, centred, no clamp.

**Failure.**
- At 38 px per row, a 1080p window overflows past about 26 sources.
- PipeWire routinely lists more once monitors are counted. On Windows it's
  worse: each device appears once per host API (W22 in the Windows audit).
- The title, the top rows and the selected row go off-screen.

**Fix.** Clamp to the window and scroll a window of rows around the
selection, as the presets modal does (`overlays.py:4747-4748`).

## P3

- **U9** `overlays.py:4279`: `entries[:12]`. With more than 12 cameras,
  keyboard selection moves past the drawn rows and disappears. Scroll the
  list around the selection.
- **U10** `overlays.py:5828-5834`: a card that fits neither column is
  skipped with `continue`, but `_help_focus_idx`, the digit keys and Enter
  still address it. The user toggles an invisible card. Page or clip the card
  instead of dropping it.
- **U11** `overlays.py:5268`: `_metric_row(1, 'FRAME MS', max(0, 33 -
  frame_ms), …)` prints that value as the number. At 30 fps the row reads
  0.00; at 120 fps it reads 24.7. Show `frame_ms`; drive only the bar from
  the headroom.
- **U12** `overlays.py:6399`: `abs(hash(section))` in the "deterministic
  fallback". `str` hashes are salted per process, so drop-in sections change
  colour every launch. Use `zlib.crc32`.
- **U13** `ui.py:640-663` (VERIFIED mechanism):
  - `_GLYPH_CACHE` is module-level, keyed `(text, id(font), fill)`, and does
    not keep the font alive. `unicornviz.fonts.load_font` is uncached.
  - A reopened `MixerWindow`'s fonts reuse freed ids of *different-size*
    fonts: 18 of 20 reopen cycles in `glyph_id_reuse.py`.
  - On the Pillow path (hosted mode, or `gpu_console = false`) labels then
    paste tiles rendered at the wrong size.
  - The GPU atlas is per-window and pins its fonts, so it is unaffected.
  - Fix: key by `(font.path, font.size)` or pin the font in the entry.
- **U14** `ui.py:666-745`: the proxy scales `rectangle`, `line`, `ellipse`,
  `pieslice`, `rounded_rectangle` and `text`. `polygon` and `arc` fall
  through `__getattr__` unscaled. At `ui_scale` 0.5 the KEEP-PLAYING speaker
  (`5447-5451`) and the padlock shackle (`6136-6138`) draw at twice their
  intended coordinates.
- **U15** `ui.py:8349-8354`, `8363-8369`: any `ui_scale` ≠ 1 uses the
  fallback tooltip. It sizes one 18 px line by `len(whole text) * 6`, so the
  many `\n` tooltips become one huge box with lines spilling below it.
- **U16** `ui.py:5080-5085` (tag editor) and `5236-5237` (search) build text
  from keysyms. Shift only upper-cases letters, so "Title (Extended Mix)" or
  "Drum & Bass" can't be typed in EDIT TAGS. The folder boxes already moved
  to `SDL_TEXTINPUT` for exactly this (`ui.py:1831-1861`); do the same here.
- **U17** `ui.py:6919-6932` (`_beat_pulse`, platter glow and beat ring) and
  `7162-7168` (pad sparkle) compute beats as `position * bpm / 60`, with no
  `beat_offset`. The flashes are phase-shifted from the grid and the kick
  whenever the downbeat isn't at 0, which is almost always. The "no
  beat-grid anchor yet" docstring is stale.
- **U18** `ui.py:6111-6115`: below SPARKLE 0.99, each frame copies two orb
  sprites. `TextureAtlas.image_entry` keys by `id()` and **pins** each image
  (`gpu2d.py:260-270`), so dead orbs fill the atlas until it resets. A reset
  drops that frame and re-rasterizes all text. Cache the faded sprite per
  quantized intensity.
- **U19** `ui.py:6965-6976`: `_pad_tiles` is keyed by exact width, height
  and scale and never cleared. Every intermediate size during a window
  resize adds a set of tiles.
- **U20** `ui.py:9089-9092`, `9140-9146`: THROW OUT picks deck 3 or 4 when
  that one is playing. The crossfader only feeds decks 1 and 2, so the 2 s
  fade changes nothing and the deck is ejected at full level, cutting the
  tail.
- **U21** `ui.py:12650-12653`: height `24 + 20·n`, clamped only to the top
  edge. With about 37 or more sets at 800 px, the tail of "Add to set »" is
  unreachable. The width is a fixed 170 px, and labels such as "Send to… —
  nothing is loaded to receive it" overrun it.
- **U22** `ui.py:12410-12427`: the SECTIONS tooltip is registered at
  `x0+140..246`, empty space on that row. The SECTIONS chip itself
  (`x0+24..130`) carries the DIAL RESET text left behind when that switch
  moved to its own tab.
- **U23** Stale `config.toml` guidance in live UI text, now that the menu
  replaces the file:
  - `ui.py:13108`: every zero-row view (an empty set or favorites, a search
    or filter with no matches) says "set [dj_mixer].music_dir". That's wrong
    advice, and LIBRARY → MUSIC FOLDER is the picker.
  - `ui.py:11349`: the RECORDING tooltip says to use the `recordings_dir`
    config key. LIBRARY → FOLDERS → RECORDINGS is live.
- **U24** Centring uses `len(text) * 8 * scale` instead of the atlas advance
  (`glyph_w * _font_scale_norm * scale`), so text sits off-centre with the TTF
  atlas. Sites:
  - `overlays.py:1698` (HUD title);
  - `5624`, `5636` (help title and date);
  - `6020`, `6069` (help tab labels);
  - `5728` (rail glyph fallback);
  - `ui.py`'s own `len(label) * 6` layout, which is tuned to its font and
    fine.

## Checked, not bugs

- The 26 render-time `float(self._hud_state.get(...))` parses in
  `overlays.py` are safe: `App._hud_audio_state_fields` always writes
  formatted numbers.
- Config-editor index requests are drained at the start of
  `_push_config_editor_model` (`app.py` ~3815), before the rows rebuild, so
  an index can't point at a rebuilt list.
- `modal_snapshot()` clamps help focus. Help paging (`move_help_page`) wraps
  both panes correctly.
- The delete fence (`ui.py:3680-3721`) compares against `library.root`,
  which is already resolved (`library.py:332`).
- Context-menu actions re-resolve their track by path (`_ctx_row_index`,
  `ui.py:3261`) before acting, so a re-sorted view can't redirect a delete.
- Multi-selection is invalidated on any view change (`_selection_view_key`).
  `sel_set_remove` resolves every row to a path before removing any.
- RST's two-press guard binds to deck *and* track path (`ui.py:2272-2302`).
- Hosted `hosted_frame()` is served from the Pillow path (`_gpu_active()` is
  false when hosted), so frames exist. Only input is broken (U1).
- `Overlays._ensure_resources` / `_build_image` (`overlays.py:7307-7433`)
  are an orphaned copy of `cta_overlay.py`. They reference attributes
  `Overlays` doesn't have and are never called: dead code to delete, not a
  live bug.
- Lint-level nits, no behaviour change:
  - `ui.py:7082` `cw = 6 if wide else 6`;
  - `ui.py:8033` `accent = accent`;
  - `ui.py:11418` unused `decks`.
- Known from the Windows audit and not repeated here:
  - `_device_choice_options` stores bare device names (W4);
  - `_free_threaded_audio_python` is POSIX-only (W17).

## Suggested order

1. **U1.** One-line guard change and a test. It makes the mixer boot profile
   usable at all.
2. **U3, U4, U6.** Live-set failures: a stuck loop, dead air, a lost
   restore.
3. **U2.** Visible on the audience output whenever a title has an accent.
4. **U5, U7, U8.**
5. The P3 list, in any order.
