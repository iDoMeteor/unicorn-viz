# Drop-in performance options audit — candidates for the config editor

Owner: overlays / core manager seat
Status: Core, Tier A (incl. auto-vj-01 rc.148 by the VJ seat) and Tier B wired 2026-09-16; mixer items stay with the mixer team
Last updated: 2026-09-16

The core config editor shipped its Performance tab in beta.144 with core
knobs only. This audit walks every drop-in (43, in four batches) for cost
knobs that belong on that tab, and says how each should get there.

## How a drop-in reaches the Performance tab

The existing contributor convention (`CONFIG_EDITOR_CATEGORY` +
`config_editor_settings()` + `set_config_setting()`) puts a controller's
rows on exactly one tab and only reads `name/value/min/max/step`. Two
small core changes make it fit the 2.0 editor, and are the first step:

1. **Per-row tab and presentation.** Rows may carry `tab` (defaults to the
   controller's category), `kind` (`slider` / `toggle` / `choice`),
   `choices`, `display`, `hint`, `badge` and `section`. A controller then
   contributes its look rows to Visuals and its cost rows to Performance
   without a second class.
2. **Discovery through the subsystem registry** instead of the fixed
   `_CONFIG_CONTRIBUTOR_ATTRS` list in `app.py`, so a drop-in never needs a
   core edit to appear.

Tiers below: **A** = wire it (clear cost, live or restart setter exists or
is trivial); **B** = worth it but needs a small change in the drop-in first,
or belongs to that team's own surface; **C** = nothing to do.

## Batch 1 — audio-out-01 … dj-mixer-01

| Drop-in | Knob | Cost it trades | Tier | Notes |
|---|---|---|---|---|
| audio-out-01 | `max_voices` (16) | one-shot mixing per block | A | live; already a contributor (Audio) |
| audio-out-01 | `blocksize` (1024), `samplerate` | output stream wakeups / underruns | A | RESTART badge |
| auto-vj-01 | `shadow_engine` (v3 shadow detector) | a second full beat tracker per block | A → done (rc.148) | RESTART row: the tracker is built in `__init__` only and it is the v3 soak instrument, so no live toggle (VJ seat's decision) |
| auto-vj-01 | `genre_matcher_enabled`, `genre_candidate_scoring_enabled` | recommender scoring per eval | A → done (rc.148) | live toggles |
| auto-vj-01 | `live_training_enabled`, `sequence_training_enabled` | JSONL logging per beat / heartbeat | A → done (rc.148) | live toggles driving the corpus writers' `set_enabled()` (same path as the hotkeys); the hint names the JSONL-gap trade-off |
| auto-vj-01 | `profile_auto_reco_eval_interval_s`, `detector_log_interval_s`, `wide_bpm_sample_interval_s` | eval cadence | A → done (rc.148) | all three as live sliders |
| banner-01 | `drip_enabled` | re-rasterizes the banner every frame while animating (0.13.0 caches the static case) | B | already Alt+D in its modal; a Performance row would mirror it |
| beat-flash-01 | `max_hz`, `max_brightness` | none (look) | C | |
| candy-frame-01 | `pattern_interval_s` | none (look) | C | |
| chat-01 | glyph capacity 4096 (hardcoded) | VBO size | C | not worth a row |
| color-grade-01 | enabled | one fullscreen pass | C | already a hotkey and a Visuals contributor |
| control-room-01 | `render_interval`, `preview_fps_cap` (0/10/20/30/60), `show_preview`, `preview_scale`, `ui_scale` | second-window raster + GPU readback | A | my lane; the reference implementation for step 1 |
| cta-01 | sparkle density, drip | PIL raster per frame while animating | B | expose its two effect toggles as rows |
| dj-mixer-01 | own PERFORMANCE tab (stem split engine, pad face cache) plus config-only `ui_scale`, `blocksize`, `prebuffer_blocks`, `stems_cpu_fraction`, `render_interval`, `audio_diag_interval_s`, `ui_diag_interval_s` | mixer raster, audio block, demucs threads | C (core) / B (mixer) | stays on the mixer's tab; suggest they add `render_interval`, the diag intervals and `stems_cpu_fraction` there |

## Batch 2 — the thirteen `effects-*` drop-ins

Effects already expose `self.parameters` on the Effects tab, so per-effect
tunables need no new plumbing. What the sweep found is **hardcoded
budgets** that never reach `parameters`:

| Drop-in | Constant | Tier | Notes |
|---|---|---|---|
| effects-particles | `_NUM_PARTICLES = 150_000` | B | promote to a `particles` parameter (transform feedback buffers are sized once, so a restart-on-change or a re-`_init`) |
| effects-tech | raymarch `MAX_STEPS 64` | B | a `steps` uniform + parameter |
| effects-rollercoast | track/segment counts | B | same pattern |
| others (cosmic, feature, flying, games, holiday, immersive, psychedelic, retro, ukiyo-e, vector) | no fixed budgets found; cost scales with resolution | C | core `render_scale` covers them |

Recommendation for the effects team: any effect over the CLAUDE.md 8 ms
budget declares its budget knob in `self.parameters` (or a
`resolution_divisor`, as the guide already asks), which lands it on the
Effects tab for free. No Performance-tab rows for effects.

## Batch 3 — effects-tech … osc-bridge-01

| Drop-in | Knob | Cost | Tier | Notes |
|---|---|---|---|---|
| grand-finale-01 | none | | C | |
| images-01 | `_MAX_IMAGE_EDGE` decode cap | decode + VRAM | B → done | `[images] max_image_edge` (0.9.0), next launch; config-only, since the showcase is an effect with no controller to carry a row. video-clips-01 has no decode cap at all (reclassified C). |
| lyrics-01 | `poll_interval_s` (0.5) | now-playing polling | A | slider 0.25–5 s; already a contributor |
| media-01 | `render_interval`, `_TAG_WORKERS = 8` (scan threads), `auto_level` (per-track loudness pass, cached) | window raster, scan CPU | A | `render_interval` live; workers RESTART |
| midi-controllers-01 | `_UPDATE_INTERVAL_S = 0.05` LED refresh (20 Hz) | USB writes | B | a 5–30 Hz slider; MIDI lane, needs their OK |
| multi-head-01 | none (spans are core display modes) | | C | |
| osc-bridge-01 | none | | C | |

## Batch 4 — postfx-01 … webcam-01

| Drop-in | Knob | Cost | Tier | Notes |
|---|---|---|---|---|
| postfx-01 | `enabled` (chain) | fullscreen passes | C | hotkey already |
| video-postfx-01 | `max_layers` (4) | stacked video passes | A | choice 1/2/4/8 |
| projectm-01 | `fps_hint`, `preset_warmup_frames`, `preset_duration` | none live | C | Corrected while wiring: `fps_hint` only seeds `configure()`; at runtime projectM's fps follows the measured frame time. Warm-up frames are a one-off cost at each preset switch, not a running one. `preset_duration` is already an effect parameter. Nothing to expose. |
| sims-01 | `fps` hardcoded 30 (USD sim playback) | none | C | Corrected while wiring: frames are baked at load and `fps` is the playback rate (the `speed` parameter already scales it); nothing is stepped per frame. |
| spotify-01 | `poll_interval_s`, `poll_fallback_s`, `http_timeout_s` | network polling | A | sliders; low risk |
| streaming-01 | `fps`, `preset`, `audio_bitrate`, `max_queued_frames` | encoder CPU + readback | A | same row kinds as Recording; RESTART while streaming |
| textures-01 | warm-cache at boot | boot time only | C | |
| training-kit-01 | tooling, not runtime | | C | |
| unicorn-tears-01 | sprite count (hardcoded) | fill rate | B | parameter |
| video-out-01 | `fps_cap` (30, 0 = every frame) | v4l2 readback | A | choice 0/15/30/60 |
| videos-01 | cache window / long edge | decode ring | C | core `[video_decks]` rows already on the tab |
| webcam-01 | `selfie_seg` mode + `grow/feather/blur px`, `selfie_seg_temporal` | segmentation is the heaviest per-frame CPU in the app when on | A | mode as a choice row under Performance; already a Visuals contributor |
| webcam-01 | capture `fps`, `width`, `height`, `cycle_interval`, `pip_scale` | capture + upload | A | fps/size RESTART; cycle live |

## Landed 2026-09-16 (Tier B, same day)

banner-01 0.14.0 (drip + beat color toggles), cta-01 0.10.0 (editor FX,
drip, sparkles, density; pushed live into an open editor),
midi-controllers-01 0.11.0 (LED refresh 5/10/20/30 Hz), effects-particles
0.10.0 (`particles`, live buffer rebuild), effects-tech 0.11.0
(`march_steps` uniform), effects-rollercoast 0.5.0 (`march_steps` per ride,
next activation), images-01 0.9.0 (`max_image_edge`, config-only),
unicorn-tears-01 rc.3 (`max_sparkles`, next launch). Left alone: the
dj-mixer-01 items (mixer team's own tab), auto-vj-01 (handoff:
`docs/planning/auto-vj-config-editor-performance-rows-2026-09-16.md`).

## Landed 2026-09-16

Core beta.146 (convention 2.0) and the Tier A rows: control-room-01 0.18.0,
audio-out-01 0.6.0, lyrics-01 0.5.0, spotify-01 rc.8, video-out-01 0.6.0,
video-postfx-01 0.3.0, streaming-01 0.7.0, media-01 0.30.0, webcam-01 1.6.0.
auto-vj-01 rows landed the same day by the VJ seat (rc.148, master 4770791;
shadow engine as a RESTART row, everything else live). projectm-01 was
reclassified (see its row).

## Proposed order (as written before wiring)

1. Core: per-row `tab` + presentation passthrough, registry discovery
   (one small commit, tests on the convention).
2. control-room-01 as the reference contributor (render interval, preview
   fps cap, show preview).
3. Tickets to the owning seats for the Tier A rows above: audio-out,
   lyrics, media, projectm, spotify, streaming, video-out, video-postfx,
   webcam. auto-vj-01 rows wait for the VJ seat's word.
4. Tier B items as each team touches its drop-in next.
