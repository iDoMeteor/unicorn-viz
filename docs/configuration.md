# Unicorn Viz — Configuration Reference

Owner: Studio Documentation
Status: active
Last updated: 2026-08-07

All settings live in `config.toml` in the project root.

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

## `[render]`

| Key              | Type   | Default | Description                                              |
|------------------|--------|---------|----------------------------------------------------------|
| `internal_scale` | float  | `1.0`   | Internal effect render scale before upscaling to screen. Use `0.5`–`1.0` for extra headroom on heavy scenes. |

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
| `codec`          | str    | `"libx264"` | Video codec used for recording. |
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
