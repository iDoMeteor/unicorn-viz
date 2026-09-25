# Unicorn Viz — Configuration Reference

Owner: Studio Documentation
Status: active
Last updated: 2026-09-04

All settings live in `config.toml` next to the app (the *app root*). Where that
is depends on how Unicorn Viz was installed:

| Install method | `config.toml` location | Notes |
|---|---|---|
| Source checkout / `run.sh` | repository root | the developer setup |
| `install.sh` (one-liner / hand-off bundle) | `~/.local/share/unicorn-viz/config.toml` (or `--prefix`) | created from `config.dist.toml` on first install; never overwritten on upgrade |
| `.rpm` / `.deb` | `/opt/unicorn-viz/config.toml` | a package config file: upgrades keep your edits (`rpmnew` / dpkg prompt) |
| Flatpak | `/app/share/unicorn-viz/config.toml` (read-only defaults) | pass `--config ~/.config/unicorn-viz/config.toml` for your own |
| Windows portable / installer | `config.toml` in the install folder | |

Any install can point elsewhere with `unicorn-viz --config <path>`. `config.dist.toml`
is the bare-bones starter that ships with packages; `config.full.example.toml`
documents every key.

Validation behavior:
- Startup performs fail-fast config validation in `unicornviz.__main__` before
    app initialization.
- Type errors and invalid enum/range values in built-in sections are reported as
    a single aggregated error list.
- Optional drop-ins may provide `drop-ins/<name>/config_validator.py` with a
    `validate_config(config_data)` function. Those validator errors are included
    in the same output and namespaced as `dropin:<name>`.

---

## `[window]`

| Key          | Type    | Default        | Description                                |
|--------------|---------|----------------|--------------------------------------------|
| `width`      | int     | `1920`         | Initial window width in pixels             |
| `height`     | int     | `1080`         | Initial window height in pixels            |
| `fullscreen` | bool    | `false`        | Start in fullscreen mode                   |
| `show_cursor`| bool    | `false`        | Keep mouse pointer visible by default      |
| `title`      | str     | `"Unicorn Viz"`| Window title bar text                      |
| `display_index` | int  | `0`            | SDL display / monitor index to target at startup and when entering fullscreen. |
| `display_mode` | str   | `"single"`   | Display layout mode: `"single"`, `"span_included"`, `"span_all"`, `"mirror_included"`, or `"mirror_all"`. |

Notes:
- `single`: render to one targeted display only.
- `span_included`: create one large window stretched across non-excluded displays.
- `span_all`: create one large window stretched across all detected displays.
- `mirror_included`: render one logical canvas and mirror it across non-excluded displays.
- `mirror_all`: render one logical canvas and mirror it across all detected displays.
- `exclude_display_indices` applies only to `span_included` and `mirror_included`.
- span/mirror modes are most reliable on X11. On Wayland compositors,
  explicit window positioning may be ignored by design.
- When `show_cursor = false`, holding Ctrl temporarily reveals the cursor.
- when `display_mode` is not `single`, Unicorn Viz attempts an automatic X11
    fallback at startup for more reliable placement; if fallback fails it
    continues on Wayland with limitations.

### Compositor Compatibility Matrix

Verified on Fedora 44 (2026-06-01):

| display_mode | GNOME Wayland | MATE (X11) | Notes |
|--------------|:-------------:|:----------:|-------|
| `single`     | ✅            | untested   | |
| `span_all`   | ✅            | untested   | |
| `mirror_all` | ✅            | untested   | |

MATE/X11 testing pending.

---

## `[demo]`

| Key                  | Type   | Default        | Description                                         |
|----------------------|--------|----------------|-----------------------------------------------------|
| `mode`               | str    | `"sequential"` | Playlist mode: `"sequential"` or `"random"`         |
| `effect_duration`    | int    | `20`           | Seconds before auto-advancing to the next effect    |
| `transition`         | str    | `"crossfade"`  | Transition type: `"crossfade"`, `"smoothfade"`, `"scanwipe"`, `"scanwipe_x"`, `"scanwipe_y"`, `"dissolve"`, `"zoomblend"`, `"shuffle"`, or `"random"` |
| `transition_duration`| float  | `1.0`          | Transition length in seconds                        |

Aliases:
- `scanwipe` -> `scanwipe_y`
- `cut` -> `smoothfade` (intentionally soft; avoids harsh hard cuts)

---

## `[audio]`

| Key              | Type   | Default | Description                                                  |
|------------------|--------|---------|--------------------------------------------------------------|
| `device`         | str    | `""`    | Device name substring (empty = auto-detect PipeWire monitor) |
| `fft_bands`      | int    | `512`   | Number of FFT frequency bins                                 |
| `buffer_seconds` | float  | `10.0`  | Audio ring buffer length in seconds                          |
| `profile`     | str     | `"house"`| Audio frequency-response profile for genre/style, e.g. `house`, `deep_house`, `tech_house`, `trance`, `psytrance`, `hard_techno`, `drum_and_bass`, `dubstep`, `chillstep`, `ambient`, `rap_rnb`. See `unicornviz/audio/profiles.py` `PROFILES` for the full current list. Sets BPM prior and (for some profiles) caps the ACF search range via `bpm_hint_min`/`bpm_hint_max`. |
| `latency`        | str    | `"low"` | Audio stream latency: `"low"`, `"medium"`, `"high"`      |
| `prefer_default_input` | bool | `true` | When true, startup prioritizes the current OS default input among candidates; when false, ranked monitor/app sources are preferred first. |
| `require_startup` | bool | `false` | If true, Unicorn Viz exits when audio startup fails after retries. If false, startup continues without active audio and the visualizer runs in degraded mode. |
| `start_timeout_s` | float | `4.0` | Per-attempt timeout for audio startup during app launch. |
| `process` | bool | `true` | Run capture and analysis in the **audio process**, a helper next to the visualizer (1.0.0-beta.162). The visualizer's process owns GL and stays on one GIL; in the helper, capture and the analyzer never wait on a frame, a console raster or a gen-2 collection, and a hanging device open stalls the helper instead of the picture. dj-mixer-01 loads its engine into the same process. The main process reads each analysis frame the helper publishes every 10 ms; onsets arrive as a stream. If the helper cannot start, audio stays in-process; if it dies, the next frame restarts capture in-process. `false` keeps everything in-process. See `unicornviz/audio/process.py`. Also on the config editor's **System** tab as *Audio process* (applies on restart). |
| `process_python` | str | `""` | Interpreter for the audio process (empty = the app's own). The hook for a free-threaded Python: the helper never imports moderngl and logs whether the GIL is really off. Also on the **Performance** tab as *Audio process Python* (applies on restart): APP PYTHON, FREE-THREADED when `~/.local/share/unicorn-viz/venv-ft/bin/python` exists (under `$XDG_DATA_HOME` if set), and CUSTOM for a path set here by hand. Never chosen by default; soak before live use. |
| `start_retries` | int | `2` | Number of additional launch-time audio startup retries after the initial attempt. |
| `start_retry_backoff_s` | float | `0.5` | Delay between launch-time audio startup retries. |
| `auto_fallback_enabled` | bool | `true` | Enable/disable mid-session automatic source fallback when capture appears silent. |
| `fallback_rms_threshold` | float | `0.0015` | Capture RMS level considered silent for source-fallback decisions. |
| `fallback_silence_seconds` | float | `6.0` | Continuous silence duration required before switching to a fallback source. |
| `fallback_cooldown_seconds` | float | `8.0` | Minimum delay between automatic fallback attempts. |
| `silence_rms_floor` | float | `0.0060` | RMS floor below which input is treated as silent (raise if b/m/t moves with no music) |
| `silence_rms_span`  | float | `0.045`  | RMS range above the floor over which the spectrum scales 0→1 |

Notes:
- **`audio.profile` is the BPM detector profile — not to be confused with the
    Auto VJ _mood_ (chill/normie/raver).** Audio profiles control the beat
    tracker's BPM prior and search range; VJ moods control the director's
    visual intensity and transition style. They are independent. Change the
    audio profile with `Alt+A` / `Alt+Shift+A` in-app, or set it in
    `config.toml` before a training session.
- `audio.latency` accepts `"low"` / `"medium"` / `"high"` labels or a numeric
    value in seconds. `"medium"` is normalized internally to a stable numeric
    midpoint for PortAudio compatibility.
- `audio.start_retries` must be `>= 0`; timing and threshold values under
    `[audio]` must be non-negative.
- With default settings (`require_startup = false`), startup does not crash if
    audio cannot be initialized; it logs the failure and continues.
- Set `require_startup = true` only for environments where audio availability is
    mandatory and startup should abort on capture failure.

### PipeWire quantum / low-latency operator setup

On Fedora/Arch with PipeWire, the default quantum (hardware period size) is
usually 1024 samples. Unicorn Viz uses `blocksize = 1024` (default) which
matches this quantum exactly. **If you see audio xruns or static on loud transients,
check the following before changing config:**

1. **Verify the PipeWire quantum matches `blocksize`:**
   ```
   pw-metadata -n settings 0 clock.force-quantum
   ```
   If the quantum differs from `blocksize`, set them to match. For 48 kHz with
   1024-sample blocks you get ~21 ms latency (the `"high"` latency preset).

2. **Recommended settings for rock-solid operation (default):**
   ```toml
   [audio]
   latency  = "high"    # maps to PortAudio 'high' → ~50 ms buffer
   blocksize = 1024     # matches PipeWire default quantum
   ```

3. **Low-latency DJ/performance setup (more xrun-prone on budget hardware):**
   ```toml
   [audio]
   latency  = "low"
   blocksize = 512      # requires PipeWire quantum = 512
   ```
   Force the PipeWire quantum:
   ```bash
   pw-metadata -n settings 0 clock.force-quantum 512
   ```
   Reset after the session:
   ```bash
   pw-metadata -n settings 0 clock.force-quantum 0
   ```

4. **Diagnosing xruns at runtime:**
   - Watch `pw-top` for capture-node xruns while Unicorn Viz runs.
   - In INFO logs look for `Audio callback status: input overflow` — each line
     is one xrun that could cause audible static.
   - If xruns appear only on beat drops, increase `blocksize` to `2048` to give
     PortAudio more buffering headroom.

---

## `[midi]`

| Key      | Type | Default | Description                                            |
|----------|------|---------|--------------------------------------------------------|
| `device` | str  | `""`    | MIDI port name substring (empty = MIDI disabled)      |

---

## Headless / training runs

Unattended runs are started with a **headless source** flag —
`--dj-mixer-source` (play a mixer set) or `--media-source` (play a media
folder). Each of these:

- forces the relevant drop-in on and arms its auto-play;
- sets `[auto_vj] auto_exit_after_finale` so the run ends by itself;
- **records Auto VJ training data**: the decision log plus the live and
  sequence corpora.

Training capture is on by default here because a headless source *is* a
training run — that is what the flag group is for. It used to need a
separate opt-in, and the failure was silent: the session looked healthy,
recorded video and audio correctly, and produced no training data at all,
which is only discoverable after the set is over and no longer repeatable.

Pass `--no-training` to suppress it (for example when using the mixer purely
as an audio source), or `--training` to capture on an ordinary interactive
run. The three streams are enabled together and cannot be selected
individually: a decision log without the corpora cannot be scored, and a
corpus without the decisions that produced it cannot be explained.

A fully specified unattended capture:

```sh
unicorn-viz --dj-mixer-source --dj-mixer-autoplay-mode smart \
            --dj-mixer-set "training - house 01" \
            --record --record-audio --record-codec auto \
            --fps-limit 30 --log-level INFO
```

---

## `[render]`

| Key | Type | Default | Description |
|---|---|---|---|
| `internal_scale` | float | `1.0` | Internal effect render scale before upscaling to screen. Use `0.5`-`1.0` for extra headroom on heavy scenes. |
| `fps_limit` | int | `0` | Render frame cap. `0` (default since 2026-09-18) follows the display's own vsync; a positive value locks to the nearest whole division of the refresh rate (30 on a 60 Hz display = every second vblank) — on Windows a non-zero cap is clamped to interval 1 regardless, since interval ≥2 stalls for seconds under desktop composition on at least one Intel driver. Also on the config editor's Performance tab. |

**Why the default is 30, not 60.** A loop that cannot finish inside one
vblank misses it and lands on the next one regardless, so the effective rate
is already halved — but unevenly, because some frames make it and some do
not, and that unevenness is what reads as judder. Asking for every second
vblank up front trades a nominally lower number for a *steady* one, and it
leaves GPU headroom for a capture tool sharing the same adapter. Raise it to
`60`, or set `0` to follow the display, if your scene comfortably fits the
budget.

---

## `[recording]`

| Key              | Type   | Default      | Description |
|------------------|--------|--------------|-------------|
| `enabled`        | bool   | `true`       | Master gate for in-app recording and the recording hotkey. |
| `auto_record`    | bool   | `false`      | Automatically start recording after startup completes. |
| `directory`      | str    | `"recordings"` | Output directory for saved recordings. |
| `ffmpeg_path`    | str    | `"ffmpeg"`  | Path to the ffmpeg executable used for recording. |
| `container`      | str    | `"mp4"`     | Output container extension for saved recordings. |
| `fps`            | int    | `60`         | Constant frame rate the recording is muxed at. Frames are paced to this rate on wallclock, so a slow render loop yields a real-time-length file rather than a sped-up one; the app also caps its readback here. |
| `codec`          | str    | `"auto"`   | Video codec. `"auto"` probes for a working hardware encoder (NVENC → VA-API → QSV) and falls back to `libx264`; the probe encodes a real frame, since a built-in encoder may still be unusable. Any explicit name is used as given. |
| `preset`         | str    | `"veryfast"`| ffmpeg encoder preset for performance/quality tradeoff. |
| `crf`            | int    | `18`         | H.264 quality target; lower is higher quality. |
| `pixel_format`   | str    | `"yuv420p"` | Output pixel format used by ffmpeg. |
| `capture_audio`  | bool   | `true`       | Capture audio alongside video when supported by the configured ffmpeg input backend. |
| `audio_input_format` | str | `"pulse"`  | ffmpeg input backend used for audio capture. Linux/PipeWire setups should use `pulse`. |
| `audio_input_device` | str | `""`       | Audio source for recording. Empty auto-resolves (see *Choosing the audio source* below); set it to pin one output permanently. |
| `audio_codec`    | str    | `"aac"`     | Audio codec used when audio recording is enabled. |
| `audio_bitrate`  | str    | `"192k"`    | Audio bitrate passed to ffmpeg. |
| `filename_prefix`| str    | `"unicornviz"` | Prefix used for timestamped recording filenames. |
| `show_indicator` | bool   | `true`       | Show a live-only recording indicator while recording. It is shown only when the name overlay is visible and is never burned into saved recordings. |

Notes:

- Recording captures the final on-screen composed output.
- The recording indicator is drawn only after frame capture, so it is visible live but not included in recordings.
- Recording readback is capped at `fps`, so raising the frame rate raises the per-frame GPU→CPU transfer cost.

### Hardware video encoding (Linux)

Recording and streaming both encode with **libx264 on the CPU** by default.
That is the portable choice and it is fine at 1080p, but at 4K — or with OBS
encoding a second copy at the same time — it is usually the largest single
CPU cost on the machine.

Intel GPUs can encode H.264 in hardware via VA-API, **but Fedora's
`libva-intel-media-driver` package is built without the patent-encumbered
encoders**. Decode works; encode is absent, and probing reports:

```
[h264_vaapi] No usable encoding profile found.
```

The full build lives in RPM Fusion as `intel-media-driver`, which *replaces*
Fedora's package:

```sh
sudo dnf install intel-media-driver          # rpmfusion-nonfree
vainfo | grep -i h264                        # needs libva-utils
# want: VAProfileH264* ... VAEntrypointEncSlice
```

**No reboot is required** — it is a userspace driver library. Restart any
application that should pick it up (OBS, Unicorn Viz); a running process
keeps the old library mapped.

AMD uses `mesa-va-drivers` (usually already present); NVIDIA uses NVENC and
needs the proprietary driver plus `libcuda`.

### Choosing the audio source

`audio_input_device` empty means auto, resolved in this order:

1. **The source the visualizer is analyzing.** Whatever is driving the
   visuals is the show, so that is what gets recorded. This is what makes a
   recording match what you were watching.
2. **An output that is actually playing.** If the analyzer source cannot be
   matched to a known output, any output in the `RUNNING` state is used,
   preferring the system default when several qualify.
3. **The default output's monitor**, with a warning logged that nothing was
   playing when the recording started.

The earlier behaviour was step 3 alone, which is silent whenever the set
plays through anything other than the system default — a DJ controller, an
interface, a second card. If several applications are playing at once (a
browser alongside the set, say) auto-detection cannot tell which one you
mean: pin it, either with `audio_input_device` or with the **audio source**
row on the config editor's Recording tab.

To list the source names available on a Linux box:

```sh
pactl list short sinks     # the ".monitor" of any of these records its output
```

---

## `[overlays]`

| Key              | Type   | Default | Description                                              |
|------------------|--------|---------|----------------------------------------------------------|
| `flash_messages` | bool   | `true`  | Show transient effect/status popups for scene changes, pause/resume, reactivity, etc. |
| `hud_show_detector_bpm`   | bool | `false` | Show the detected "BPM: nnn (conf)" readout in the Auto VJ status bar (`H` HUD). |
| `hud_show_profile_score`  | bool | `false` | Show the recommender score number next to `BPM PROF` in the `H` HUD. |
| `hud_show_reco_profile`   | bool | `false` | Show the `REC PROF` (recommended-profile) line in the `H` HUD. |

The three `hud_show_*` keys are "detector internals" readouts, default off
(2026-09-01) so the show reads smoother without the recommender's internal
wobble narrated; opt back in per-key as above. `[auto_vj] hud_production_mode
= true` forces all three off for a live session regardless of these
settings, without changing them — flip it back to `false` (or comment it
out) to see whatever the three keys above are individually set to again.

---

## `[tooltips]`

Hover tooltips on the operator surfaces (control-room window, main-window
modal browsers/selectors, help-icon rail). Never shown on the bare
audience HUD.

| Key       | Type  | Default | Description                                                             |
|-----------|-------|---------|-------------------------------------------------------------------------|
| `enabled` | bool  | `true`  | Master switch for all hover tooltips.                                   |
| `delay_s` | float | `0.55`  | Hover time before a tooltip appears (help-icon rail is always instant). |

---

## `[spotify]`

| Key                         | Type   | Default | Description |
|-----------------------------|--------|---------|-------------|
| `now_playing_banner`        | bool   | `true`  | Show a top-pinned now-playing banner when Spotify starts a new track. |
| `now_playing_banner_hold_s` | float  | `10.0`  | How long the Spotify banner stays visible before sliding out. |

Notes:
- The banner is independent from `[overlays].flash_messages`, so Spotify can surface track-change notices even when general flash popups are disabled.

---

## `[ansi]`

| Key              | Type | Default              | Description                                                              |
|------------------|------|----------------------|--------------------------------------------------------------------------|
| `ansi_dir_auto`  | str  | `"assets/ansi"`      | Directory used by ANSI Viewer in normal playlist mode                    |
| `ansi_dir`       | str  | `"assets/ansi"`      | Legacy fallback key (kept for backward compatibility)                    |

---

## `[webcam]`

Controls the always-on webcam subsystem (`drop-ins/webcam-01`) and treatment
auto-cycle behavior.

| Key              | Type | Default | Description |
|------------------|------|---------|-------------|
| `cycle_interval` | int  | `0`     | Seconds per webcam effect. `0` = use `demo.effect_duration`. |
| `switch_hide_duration_s` | float | `1.2` | Seconds to temporarily hide webcam PiP while switching camera devices. |

Additional webcam capture and image keys (for example `device`, `width`,
`height`, `fps`, `pip_scale`, `pip_position`, `treatment`, `brightness`,
`contrast`, `flip_horizontal`, `flip_vertical`) are implemented by the
`WebcamSystem` drop-in subsystem and are read from `[webcam]`.

---

## `[video_decks]`

Music-video decks: a DJ deck (`drop-ins/dj-mixer-01`) loaded with a video
file draws its picture as a full-screen, letterboxed layer at that deck's
audibility, so it fades with the fader rather than with a timer. Frames
come from `drop-ins/videos-01`'s `DeckVideoSource`; the layer itself is
core (`unicornviz/video_deck_layer.py`) and is a no-op when either drop-in
is absent. The visualizer keeps rendering underneath at every opacity.
Design: `docs/planning/music-video-decks-plan-2026-09-13.md`.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Draw the layer at all. |
| `postfx_over_video` | bool | `true` | Draw the video *before* the post-FX chain, so bloom / grading / beat-flash apply over it. `false` draws it after, untouched, on top of the processed visualizer. |
| `cache_window_s` | float | `4.0` | Seconds of decoded frames each deck keeps in its ring, so a scratch or loop inside that window never seeks. |
| `cache_long_edge` | int | `720` | Long edge, in pixels, of the cached (and uploaded) frames. 960 is sharper at more GPU upload per frame; the `video_decks` stage in the frame profiler shows the cost. |
| `swap_hold_opacity` | float | `0.9` | Read by auto-vj via `vj_api.get_video_layer_opacity()`: above this opacity the picture is essentially the video, so scene swaps are held. |

The HUD shows `VIDEO A 82%` (per visible deck) while any video deck is
drawn.

---

## `[control_room]`

Controls the operator "Control Room" second window
(`drop-ins/control-room-01`). Per the project's config policy, only
hardware-type settings live here — display, size, and redraw cadence;
everything about panel layout, pages, and per-panel overrides lives in
the runtime store instead (see `drop-ins/control-room-01/docs/
configuration.md` and `docs/planning/control-room-panel-registry-plan-
2026-09-04.md`), seeded with defaults on first run and edited live from
the operator surface's **LAYOUT** page.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Load the drop-in and open the operator window. |
| `display_index` | int | `1` | Preferred SDL display for the operator window. |
| `fullscreen` | bool | `true` | Borderless fullscreen on the chosen display. |
| `width` / `height` | int | `1440` / `900` | Initial windowed size; ignored when `fullscreen` is true. |
| `render_interval` | float | `0.5` | PIL redraw cadence, seconds between frames — independent of the runtime store's `preview_fps_cap`. |

`preview_fps_cap`, `preview_scale`, and `theme` are read from this section
only as a one-time seed the first time the runtime store has no value for
them (back-compat for pre-existing configs); the store's value wins on
every launch after that.

---

## `[runtime_state]`

Controls the shared runtime state store used by subsystems (webcam now;
additional teams can share this in future).

| Key    | Type | Default | Description |
|--------|------|---------|-------------|
| `path` | str  | `"runtime/global_state.json"` | Runtime state JSON file path, relative to project root unless absolute. |

Notes:
- Runtime state now includes schema metadata at `_meta`:
    - `schema = "unicornviz.runtime_state"`
    - `schema_version = 1`
- Webcam persistence writes under `webcam.*` and includes per-camera image
    settings.
- The config editor (`c`) remembers its Performance tab here rather than
    rewriting this file. Live rows persist as `perf_render_scale`,
    `perf_present_guard_skips`, `perf_preview_capture`,
    `perf_preview_fps_ceiling`, `perf_preview_max_width`,
    `perf_sysmon_interval_s`, `perf_tooltips` and `perf_perf_frames` and are
    re-applied at the end of startup. RESTART rows persist as
    `render_fps_limit`, `audio_latency`, `audio_fft_bands`, `audio_blocksize`,
    `video_decks_enabled` and `video_decks_cache_long_edge` and are laid over
    the loaded config (in memory only) before the subsystem that reads them
    is built. Delete a key to fall back to `config.toml`. None of these are
    part of a configuration profile.
- **config.toml is being phased out in favor of the config menu** (2026-09-24).
    When a setting gets a menu row, the value this file sets for it is
    copied into the runtime store once, at the end of startup, and the
    menu's value wins from then on; the startup log lists what moved.
    Built-in defaults are never copied, and this file is never written.
    Coverage and gaps: `docs/audits/2026-09-24-config-menu-coverage-audit.md`.
- The config editor's **Logging** tab (level, folder, crash dump file, stall
    dump) is remembered as `logging_level`, `logging_directory`,
    `logging_faulthandler` and `logging_stall_dump_s`. Logging starts before
    the app, so `unicornviz/__main__.py` applies these itself; `--log-level`
    still wins for its run.
- The config editor's **System** tab (display, MIDI, audio engine, folders,
    Spotify client ID), **Streaming** tab (RTMP, video out, chat username)
    and **Auto VJ** tab (all Auto VJ rows, while Auto VJ is loaded) follow
    the machine like Performance: none of them is part of a profile.
- The config editor's **Drop-ins** tab holds load/start switches (RESTART),
    remembered as `config_overrides.<section>.<key>`; a nested key such as
    `[spotify.web_api] enabled` overrides only that leaf.
- The config editor's **active profile** is remembered as
    `config_profile_active`. Audio/Visuals rows and per-effect parameter
    edits write through to it in `runtime/config_profiles.json` as they
    change, and it is loaded at the end of startup (first run saves the
    current settings as "default"). Save writes to it; a new name creates
    and activates a profile; Load switches to the selected one.
- Drop-in rows on the Performance tab persist the same way:
    `perf_dropin.<KEY>.<name>` for live rows (replayed through the drop-in's
    `set_config_setting` at startup) and `config_overrides.<section>.<key>`
    for RESTART rows (laid over the loaded config before the drop-in is
    built). See the developer guide, "Contributing Settings to the Config
    Editor".

---

## `[effects]`

Per-effect parameter overrides.  Keyed by **Python class name**.

Per-effect reactivity override:
- Optional key: `reactivity`
- If set, this is the absolute reactivity used by that effect
- If omitted, the effect uses global `audio.reactivity`

Per-effect randomization overrides:
- Optional keys: `random_speed_min` / `random_speed_max`,
    `random_zoom_min` / `random_zoom_max`,
    `random_reactivity_min` / `random_reactivity_max`
- If set under `[effects.<ClassName>]`, these values override the global
    `[hotkeys]` ranges only while that effect is active
- If omitted, the app falls back to the global randomization bounds
- The same keys work for drop-in effects loaded from `drop-ins/`

For a complete list of every effect's tweakable settings and defaults, see:

- [Effect Settings Reference](effect-settings.md)

```toml
[effects.Plasma]
speed = 2.0

[effects.Kaleidoscope]
speed = 1.0
zoom = 0.62
# random_speed_min = 0.7
# random_speed_max = 1.4
# random_zoom_min = 0.45
# random_zoom_max = 0.90

[effects.ANSIViewer]
slide_time = 30.0
glow       = 0.8
crt        = 0.5

[effects.FractalZoom]
max_iter = 120

[effects.ParticleStorm]
speed = 1.5
```

Available parameters per effect:

| Effect            | Parameter   | Range      | Meaning                         |
|-------------------|-------------|------------|---------------------------------|
| All               | `speed`     | 0.05–10.0  | Animation rate multiplier       |
| All               | `reactivity`| 0.1–5.0    | Absolute per-effect audio reactivity override |
| All               | `random_speed_min/max` | hotkey defaults | Optional per-effect bounds for random speed |
| All               | `random_zoom_min/max` | hotkey defaults | Optional per-effect bounds for random zoom |
| All               | `random_reactivity_min/max` | hotkey defaults | Optional per-effect bounds for random reactivity |
| ANSIViewer        | `glow`      | 0.0–1.0    | Phosphor glow intensity         |
| ANSIViewer        | `crt`       | 0.0–1.0    | CRT barrel distortion strength  |
| ANSIViewer        | `slide_time`| 5.0–300.0  | Seconds per art piece           |
| AudioSpectrum     | `mode`      | 0, 1, 2    | 0=bars, 1=waveform, 2=both      |
| AudioSpectrum     | `glow`      | 0.0–1.0    | Bar glow                        |
| FractalZoom       | `max_iter`  | 32–512     | Iteration depth                 |
| UnicornTears      | `speed`     | 0.05–10.0  | Fall speed multiplier           |

---

## `[playlist]`

| Key        | Type           | Default | Description                                               |
|------------|----------------|---------|-----------------------------------------------------------|
| `sequence` | list of str    | `[]`    | Ordered list of effect class names; empty = all effects   |

Example — only rotate through three effects:

```toml
[playlist]
sequence = ["Plasma", "Fire", "Starfield"]
```

---

## `[splash]`

| Key       | Type | Default | Description                                        |
|-----------|------|---------|----------------------------------------------------|
| `enabled` | bool | `true`  | Show the startup splash animation. The mixer-only boot profile forces this off. |
| `image`   | str  | `"images/unicorn-viz-01.png"` | Splash image path.           |

---

## `[dj_mixer]` (boot profile keys)

The mixer's own settings are documented in the dj-mixer-01 drop-in; these
core-read keys select the **mixer-only boot profile** (see
`drop-ins/dj-mixer-01/docs/mixer-only-mode-plan.md`).

| Key           | Type | Default | Description                                    |
|---------------|------|---------|------------------------------------------------|
| `mixer_only`  | bool | `false` | Boot straight into the DJ mixer console: no splash, no audio capture, no effects, no visual drop-ins. The mixer window opens automatically. Also available as the `--mixer` CLI flag or the `unicorn-mix` entrypoint (both override `false` here). |
| `mixer_allow` | list | `[]`    | Extra drop-ins to load in mixer-only mode, by config-section name (e.g. `["media", "osc"]`). The mixer itself is always loaded. |

---

## `[logging]`

| Key        | Type | Default  | Description                              |
|------------|------|----------|------------------------------------------|
| `level`    | str  | `"INFO"` | Log verbosity                            |
| `directory`| str  | `"logs"` | Directory for timestamped run log files  |
| `perf_frames` | bool | `false` | Per-frame timing breakdown (`Perf frame: ...`). Emitted at DEBUG, so it only reaches the log when `level = "debug"`; at `"info"` it is generated and discarded. Logged for every frame over 25 ms and every 120th frame otherwise. Buckets are wall-clock spans of the main loop in order: `events`, `midi`, `auto`, `audio`, `auto_vj` (five controllers, with its `osc`, `lyrics` and `vj` sub-spans reported alongside), `finale`, `subsys_upd` (every registered subsystem's `update()`), `effects`, `hud`, `draw`, `swap`, `subsys_present`. Summarize a log with `tools/profiling/perf_frames.py`. |
| `faulthandler` | bool | `true` | Write native-crash and stall dumps to a per-run `faulthandler_<stamp>.log` under `directory`. A run that writes nothing deletes its file on exit. `false` keeps the handler on stderr only (the release setting). |
| `stall_dump_s` | float | `5.0` | If the render loop stops advancing for this many seconds, dump every thread's stack into the faulthandler file (or stderr) while the process is still hung. `0` disables. |
