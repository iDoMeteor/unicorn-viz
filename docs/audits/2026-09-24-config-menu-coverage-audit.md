# Config menu coverage audit — config.toml keys vs. menu rows

Owner: overlays / core manager seat (config menu)
Status: In-scope coverage complete (§6); auto_vj / effects gaps listed for their seats (§3)
Last updated: 2026-09-24

**Direction (relayed by the perf seat, 2026-09-24):** every setting the app
depends on should have a config menu row, and should be set there rather
than in `config.toml`, which is to be phased out.

**Input:** the 157 keys set (uncommented) in the owner's `config.toml` on
2026-09-24, 22 sections, names only (the perf seat's inventory at
`/var/tmp/perf-seat/config_toml_active_keys.txt`). No values were read.

**Method:** each key traced to the code that reads it, and each config menu
row traced to what it writes and how it persists. Code is at core
1.0.0-beta.168.

## Legend

| Status | Meaning |
|---|---|
| **ROW** | Has a config menu row, and the choice survives a restart |
| **ROW (profile)** | Has a row, but the change survives a restart only if saved into, then loaded from, a named profile |
| **APP** | Settable in the app outside the menu (hotkey, Control Room page) and remembered; no menu row |
| **LIVE** | Settable in the app but forgotten at restart; `config.toml` is still its only lasting home |
| **NONE** | `config.toml` only |

## 1. Structural findings (these matter more than any single row)

1. **Many rows don't persist on their own.** Performance-tab rows (core and
   drop-in), Recording rows, RESTART rows and a few others are remembered
   in the runtime store and restored at startup. But **the Visuals tab's
   core rows (Effect duration, Transition length, HUD auto-hide, HUD
   timeout, Flash messages) and every Effects-tab parameter edit only
   survive a restart through a saved profile.** Change one in the menu,
   restart without saving a profile, and `config.toml` wins again. For "set
   it in the menu, not the file" to hold, these need to be remembered
   automatically, like the Performance rows. That is a behavior decision,
   see §5.
2. **No text or path row type.** The menu has sliders, toggles and choices
   only. Directories, device names, usernames, URLs and lists (13 of the 53
   in-scope keys) can't be expressed today. The overlay already has a
   text-entry mode (profile names), which a `text` row kind could reuse.
3. **Some values shouldn't be shown in a menu at all.** `[streaming]
   endpoint` usually carries the stream key. `[spotify] web_api.client_id`
   is an app credential. These need a masked or write-only field, or should
   stay out of the menu.
4. **`[logging] level` is read before the app, and the runtime store, exist**
   (`unicornviz/__main__.py`). A menu row needs `__main__` to consult the
   runtime store first, or the level change must apply on the next launch.
5. **Dead config:** the three `[effects] VideoShowcase.*` keys point at a
   class renamed to `VideoClips` in July
   (`docs/planning/video-drop-ins-2026-07-06.md`). They currently do
   nothing.
6. **Precedence already favors the menu.** RESTART and remembered values are
   laid over `config.toml` at startup (`App._apply_runtime_config_overrides`,
   `_restore_performance_settings`), so a menu choice wins over the file
   once made. Carrying the file's current values into the runtime store is
   the remaining step toward retiring the file. Awaiting the owner's
   go-ahead, see §5.

## 2. In-scope sections (overlays / core / Control Room seat): 53 keys

| Key | Status | Notes |
|---|---|---|
| `[logging] level` | NONE | Read in `__main__` before the runtime store (finding 4) |
| `[logging] perf_frames` | ROW | Performance › Per-frame perf logging |
| `[window] display_mode` | LIVE | Hotkeys / Displays page switch it live; not remembered |
| `[window] display_index` | NONE | Audience display |
| `[window] exclude_display_indices` | APP | Displays page SAVE (runtime store, wins over config) |
| `[ansi] ansi_dir_auto` | NONE | Path |
| `[midi] device` | LIVE | MIDI selector modal picks live; not remembered |
| `[midi] preset` | NONE | |
| `[recording] directory` | NONE | Path |
| `[recording] fps` | ROW | Recording › Frame rate |
| `[overlays] flash_messages` | ROW (profile) | Visuals › Flash messages (finding 1) |
| `[overlays] hud_auto_hide` | ROW (profile) | Visuals › HUD auto-hide (finding 1) |
| `[overlays] hud_show_detector_bpm` | NONE | |
| `[overlays] hud_show_profile_score` | NONE | |
| `[overlays] hud_show_reco_profile` | NONE | |
| `[hotkeys] random_speed_min` / `_max` | NONE | Random-look ranges (2 keys) |
| `[hotkeys] random_reactivity_min` / `_max` | NONE | (2 keys) |
| `[hotkeys] random_zoom_min` / `_max` | NONE | (2 keys) |
| `[streaming] enabled` | NONE | |
| `[streaming] endpoint` | NONE | Carries the stream key (finding 3) |
| `[spotify] enabled` | NONE | |
| `[spotify] poll_interval_s` | ROW | Performance › Local poll |
| `[spotify] web_api.enabled` | NONE | |
| `[spotify] web_api.client_id` | NONE | Credential (finding 3) |
| `[spotify] web_api.scopes` | NONE | Developer-level; recommend leaving out of the menu |
| `[spotify] web_api.poll_interval_s` | ROW | Performance › Web API poll |
| `[spotify] web_api.http_timeout_s` | ROW | Performance › HTTP timeout |
| `[media] enabled` | NONE | |
| `[media] media_dir` | NONE | Path |
| `[chat] enabled` | NONE | |
| `[chat] username` | NONE | Text |
| `[chat] position` | NONE | |
| `[candy_frame] enabled` | NONE | |
| `[lyrics] enabled` | NONE | |
| `[color_grade] start_enabled` | NONE | (Visuals › intensity row exists, profile-only) |
| `[video_postfx] enabled` | NONE | |
| `[control_room] enabled` | NONE | Shift+M opens/closes live |
| `[control_room] fullscreen` | LIVE | F in the window toggles live; not remembered |
| `[control_room] display_index` | APP | Displays page "MOVE CONTROL ROOM HERE" (runtime store) |
| `[control_room] render_interval` | ROW | Performance › Window refresh (10–60 fps). **Range gap:** config's `0.5` s is 2 fps, below the row's lowest choice, so the row reads as 10 until touched. With the GPU UI (2.3 ms/frame) raising it is cheap |
| `[keystrokes] enabled` | NONE | |
| `[webcam] pip_position` | APP | Ctrl+numpad layout keys (runtime `webcam` state) |
| `[webcam] pip_scale` | APP | Alt+[ / ] (runtime `webcam` state) |
| `[webcam] border_thickness` | NONE | (Border style / intensity / hue rows exist; thickness doesn't) |
| `[webcam] cycle_interval` | ROW | Performance › Treatment cycle |
| `[video_out] enabled` | NONE | |
| `[video_out] start_enabled` | NONE | |
| `[video_out] v4l2.enabled` | NONE | |
| `[video_out] v4l2.device` | NONE | Path |
| `[video_out] v4l2.fps_cap` | ROW | Performance › Output fps cap |

**Tally (53):** ROW 9 · ROW (profile) 2 · APP 4 · LIVE 3 · NONE 35.

## 3. Owned elsewhere — listed for routing

### `[auto_vj]` — 25 keys (auto-vj seat, not running)

ROW (2): `live_training_enabled`, `sequence_training_enabled` (Performance).

NONE (23): `enabled`, `beat_tracker_engine`, `env_source`,
`drop_trigger_threshold`, `drop_trigger_fastlane`, `drop_sustain_entry`,
`drop_sustain_fizzle_floor`, `postfx_cruise_slots`, `log_decisions`,
`live_training_corpus_path`, `sequence_training_corpus_path`,
`published_bpm_smoothing_enabled`, `published_bpm_smoothing_s`,
`mode_snap_unit_build`, `mode_source_min_confidence_build`,
`mode_source_min_confidence_build_rel`, `mode_snap_unit_breakdown`,
`mode_phrase_within_bars_breakdown`, `mode_snap_unit_climax`,
`mode_phrase_unit_climax`, `mode_phrase_within_bars_climax`,
`drop_cruise_min_confidence`, `hud_production_mode`.

Several of these are detector/director tunables under the doc-sync and
subsystem-version rules in CLAUDE.md, so rows for them belong with that
seat.

### `[effects]` — 70 keys (effects seat, not running)

Sorted by a static scan (whether the effect declares the key as a numeric
entry in its `parameters`), so treat it as approximate:

- **ROW (profile), 46:** numeric parameters the Effects tab already edits:
  `speed` / `zoom` / `reactivity` / `glitter` on FirstDrop, Corkscrew,
  NightCoaster, MineTrain, CoasterCam, LogFlume, FloatingWorld and
  OndenWatermill; their per-effect extras (`drop_force`, `roll_force`,
  `neon_gain`, `torch_gain`, `cam_offset`, `splash_gain`, `layer_churn`,
  `flow_gain`); `ImageShowcase.mix_time`; `ProjectMEffect.speed`,
  `preset_duration`, `beat_sensitivity`. These persist only through a
  saved profile (finding 1).
- **NONE, 21:** construction-time settings, not live parameters:
  `ImageShowcase.preload_images`, `scale_when_framed`;
  `SimShowcase.mix_time`, `camera_energy`; `random_zoom_min` on six
  rollercoaster effects; and ProjectMEffect's `smooth_transition`,
  `lock_preset`, `start_clean`, `fps_hint`, `projectm_library`,
  `preset_dirs`, `texture_dirs`, `start_preset`,
  `solid_color_skip_enabled`, `solid_color_duration`,
  `preset_warmup_frames`.
- **Dead, 3:** `VideoShowcase.preload_videos`, `mix_time`,
  `scale_when_framed` (finding 5).

### `[dj_mixer]` — 9 keys (UV Mixer Team)

`enabled`, `start_enabled`, `rev1_device`, `music_dir`, `display_index`,
`fullscreen`, `prebuffer_blocks`, `output_device`, `headphone_device`. The
mixer has its own settings tabs; not audited here. The perf seat is
routing these.

## 4. Plan for the in-scope gaps

1. **Toggles, sliders and choices, each remembered on its own** (the bulk,
   no new machinery):
   - `[overlays] hud_show_*` ×3
   - `[hotkeys] random_*` ×6 (as min/max sliders)
   - `[webcam] border_thickness`
   - `[control_room] fullscreen`, plus a 2 fps / 5 fps floor on Window refresh
   - `[window] display_mode`, `display_index` (choices over detected displays)
   - `[chat] position`
   - `[midi] device` (choice over connected devices), `preset`
   - A **Drop-ins** section of RESTART `enabled` toggles: streaming, spotify
     (+ `web_api.enabled`), media, chat, candy_frame, lyrics, video_postfx,
     control_room, keystrokes, video_out (+ `start_enabled`,
     `v4l2.enabled`), color_grade `start_enabled`
2. **A `text` row kind** reusing the overlay's text entry, for the paths
   and names: `recording.directory`, `media.media_dir`, `ansi_dir_auto`,
   `video_out.v4l2.device`, `chat.username`. Masked or write-only for
   `streaming.endpoint` and `spotify.web_api.client_id`.
3. **`[logging] level`**: a choice row that applies on the next launch, with
   `__main__` reading the runtime store first.
4. **Value migration**, after §5 decision A.

## 5. Decisions for the owner

- **A. Carry `config.toml`'s current values into the runtime store?** This is
  the step that actually retires the file for these keys: after it, the
  menu (runtime store) is the source of truth and edits to `config.toml` no
  longer take effect. Reversible (clear the runtime keys), but a real
  behavior change. Needs the owner's direct go-ahead; the direction reached
  this seat secondhand.
- **B. Remember Visuals rows and effect-parameter edits automatically?**
  Today they persist only through saved profiles, by design (profiles
  describe "the look of a show"). Recommendation: remember the last-used
  value automatically, and keep profiles as named snapshots layered on top.
- **C. Sensitive values** (`streaming.endpoint`, `spotify.web_api.client_id`):
  masked write-only fields, or keep them file-only?

## 6. Progress

Owner answers (2026-09-24, direct): **A** migrate each key as its row lands
(never writing config.toml); **B** always save automatically, into the
*active profile* itself: there is always one, it loads at boot, it shows
orange, Save writes to it, and a picked-but-unloaded profile shows purple
with its border and LOAD pulsing cyan; **C** sensitive values masked, with
a toggle to show.

| Batch | Shipped | What |
|---|---|---|
| 1 | core 1.0.0-beta.169 | Profiles write through and load at boot: Visuals rows and effect-parameter edits now persist (finding 1 resolved) |
| 2 | core 1.0.0-beta.170, control-room-01 0.24.0 | Migration: `Config.file_value()`; file-set values copied into the menu once at startup (core restart and live rows, drop-in rows declaring `config`, profile rows via the active profile). Window refresh gains 2/5 fps (`render_interval = 0.5` is now a menu value); Control Room Fullscreen row |
| 3 | core 1.0.0-beta.171, webcam-01 1.9.0 | **Drop-ins** tab: RESTART load/start switches for candy_frame, chat, color_grade (+ start), control_room, keystrokes, lyrics, media, spotify (+ web_api), streaming, video_out (+ start, v4l2). Visuals: HUD detail ×3, Random look ranges ×6. Webcam border thickness. Nested keys (`web_api.enabled`) override just their leaf |

| 4 | core 1.0.0-beta.172-173, spotify-01 rc.9-10, streaming-01 0.8.0, auto-vj-01 rc.152 | **Logging** tab (owner request, 2026-09-24): log level, log folder, per-frame perf logging, crash dump file, stall dump; Auto VJ decision log / log folder / training logs and corpus files / detector log; Spotify corpus file. New **text** and **secret** row kinds (decision C): Spotify client ID and streaming endpoint masked with SHOW |

| 5 | core 1.0.0-beta.176, media-01 0.31.0, video-out-01 0.7.0, chat-01 0.7.0 | Recording save folder, ANSI art folder, display mode and display (live; applied before multi-head is built), MIDI device and preset; media folder, V4L2 device, chat position and username |

**All 53 in-scope keys now have menu rows**, except `[spotify] web_api.scopes` (left out by recommendation: developer-level) and `[dj_mixer] enabled` (owner: config.toml / boot-level only). Rows added after the file value was set migrate it on the next start.

In-scope status after batch 3: of the 35 NONE keys, **24 now have rows**.
`[dj_mixer] enabled` stays out of the menu by the owner's decision (config.toml / boot-level only; beta.174 added it, beta.175 removed it); the mixer's other keys live in its own ⚙ SETTINGS. After batch 4, `[logging] level`, `[streaming] endpoint` and
`[spotify] web_api.client_id` are covered too. Still open: text rows
for `[recording] directory`, `[media] media_dir`, `[ansi] ansi_dir_auto`,
`[video_out] v4l2.device`, `[chat] username` (the row kind now exists);
choice rows for `[window] display_mode` / `display_index`, `[midi]
device` / `preset`, `[chat] position`. `web_api.scopes` recommended to
stay out.
