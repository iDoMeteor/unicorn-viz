# Unicorn Viz — Configuration Reference

Owner: Studio Documentation
Status: active
Last updated: 2026-06-04

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
| `display_mode` | str   | `"single"`   | Display layout mode: `"single"`, `"span_all"`, or `"mirror_all"`. |

Notes:
- `single`: render to one targeted display only.
- `span_all`: create one large window stretched across the combined bounds of all displays.
- `mirror_all`: render on the targeted display and mirror the final live output to every other detected display.
- `span_all` and `mirror_all` are most reliable on X11. On Wayland compositors,
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
| `profile`     | str     | `"house"`| Audio frequency-response profile for genre/style: `house`, `trance`, `electronic`, `rap`, `hyphy`, `r&b`, `rock`, `generic`, `classical`, `ambient`, `pop`, `metal` |
| `latency`        | str    | `"high"` | Audio stream latency: `"low"`, `"medium"`, `"high"`      |
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
- `audio.latency` accepts `"low"` / `"medium"` / `"high"` labels or a numeric
    value in seconds. `"medium"` is normalized internally to a stable numeric
    midpoint for PortAudio compatibility.
- `audio.start_retries` must be `>= 0`; timing and threshold values under
    `[audio]` must be non-negative.
- With default settings (`require_startup = false`), startup does not crash if
    audio cannot be initialized; it logs the failure and continues.
- Set `require_startup = true` only for environments where audio availability is
    mandatory and startup should abort on capture failure.

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
| `fps`            | int    | `60`         | Recording frame rate passed to ffmpeg. |
| `codec`          | str    | `"libx264"` | Video codec used for recording. |
| `preset`         | str    | `"veryfast"`| ffmpeg encoder preset for performance/quality tradeoff. |
| `crf`            | int    | `18`         | H.264 quality target; lower is higher quality. |
| `pixel_format`   | str    | `"yuv420p"` | Output pixel format used by ffmpeg. |
| `capture_audio`  | bool   | `false`      | Capture audio alongside video when supported by the configured ffmpeg input backend. |
| `audio_input_format` | str | `"pulse"`  | ffmpeg input backend used for audio capture. Linux/PipeWire setups should use `pulse`. |
| `audio_input_device` | str | `""`       | Audio input source name for recording. Empty auto-resolves to the default sink monitor on Linux/PipeWire. |
| `audio_codec`    | str    | `"aac"`     | Audio codec used when audio recording is enabled. |
| `audio_bitrate`  | str    | `"192k"`    | Audio bitrate passed to ffmpeg. |
| `filename_prefix`| str    | `"unicornviz"` | Prefix used for timestamped recording filenames. |
| `show_indicator` | bool   | `true`       | Show a live-only recording indicator while recording. It is shown only when the name overlay is visible and is never burned into saved recordings. |

Notes:
- Linux/PipeWire/Pulse setups can record audio by enabling `capture_audio = true`.
- If `audio_input_device` is empty, Unicorn Viz resolves the default sink monitor via `pactl` so recordings capture desktop playback instead of the default microphone source.
- Recording captures the final on-screen composed output.
- The recording indicator is drawn only after frame capture, so it is visible live but not included in recordings.
- Recording may reduce runtime performance because frame capture currently uses synchronous screen readback.

---

## `[overlays]`

| Key              | Type   | Default | Description                                              |
|------------------|--------|---------|----------------------------------------------------------|
| `flash_messages` | bool   | `true`  | Show transient effect/status popups for scene changes, pause/resume, reactivity, etc. |

---

## `[ansi]`

| Key              | Type | Default              | Description                                                              |
|------------------|------|----------------------|--------------------------------------------------------------------------|
| `ansi_dir_auto`  | str  | `"assets/ansi"`      | Directory used by ANSI Viewer in normal playlist mode                    |
| `ansi_dir`       | str  | `"assets/ansi"`      | Legacy fallback key (kept for backward compatibility)                    |

---

## `[webcam]`

Controls webcam **auto-cycle** behaviour — how long to show each webcam-type
effect before the playlist auto-cycles to the next one when `KP Enter` is
active.

| Key              | Type | Default | Description |
|------------------|------|---------|-------------|
| `cycle_interval` | int  | `0`     | Seconds per webcam effect. `0` = use `demo.effect_duration`. |

> Camera capture settings (device, resolution, fps, PiP position) live under
> `[effects.WebcamOverlay]` — see [effect-settings.md](effect-settings.md).
> Camera support is provided entirely by the `drop-ins/webcam-01` drop-in.
> There is no system-level camera overlay.

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

## `[logging]`

| Key        | Type | Default  | Description                              |
|------------|------|----------|------------------------------------------|
| `level`    | str  | `"INFO"` | Log verbosity                            |
| `directory`| str  | `"logs"` | Directory for timestamped run log files  |
