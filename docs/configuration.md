# Unicorn Viz — Configuration Reference

All settings live in `config.toml` in the project root.

---

## `[window]`

| Key          | Type    | Default        | Description                                |
|--------------|---------|----------------|--------------------------------------------|
| `width`      | int     | `1920`         | Initial window width in pixels             |
| `height`     | int     | `1080`         | Initial window height in pixels            |
| `fullscreen` | bool    | `false`        | Start in fullscreen mode                   |
| `title`      | str     | `"Unicorn Viz"`| Window title bar text                      |
| `display_index` | int  | `0`            | SDL display / monitor index to target at startup and when entering fullscreen. |

---

## `[demo]`

| Key                  | Type   | Default        | Description                                         |
|----------------------|--------|----------------|-----------------------------------------------------|
| `mode`               | str    | `"sequential"` | Playlist mode: `"sequential"` or `"random"`         |
| `effect_duration`    | int    | `20`           | Seconds before auto-advancing to the next effect    |
| `transition`         | str    | `"crossfade"`  | Transition type: `"crossfade"`, `"smoothfade"`, `"scanwipe_x"`, `"scanwipe_y"`, `"dissolve"`, `"zoomblend"`, `"radialwipe"`, `"lumawipe"`, `"stripewipe"`, `"anglesweep"`, `"glitchsoft"`, `"prismsplit"`, `"shuffle"` |
| `transition_duration`| float  | `1.0`          | Transition length in seconds                        |

Aliases:
- `scanwipe` -> `scanwipe_y`
- `radial` -> `radialwipe`
- `cut` -> `smoothfade` (intentionally soft; avoids harsh hard cuts)

---

## `[audio]`

| Key              | Type   | Default | Description                                                  |
|------------------|--------|---------|--------------------------------------------------------------|
| `device`         | str    | `""`    | Device name substring (empty = auto-detect PipeWire monitor) |
| `fft_bands`      | int    | `512`   | Number of FFT frequency bins                                 |
| `buffer_seconds` | float  | `10.0`  | Audio ring buffer length in seconds                          |
| `reactivity`     | float  | `1.5`   | Master visual response multiplier                            |
| `latency`        | str    | `"high"` | Audio stream latency: `"low"`, `"medium"`, `"high"`      |
| `try_alsa_loopback` | bool | `false` | Try ALSA loopback devices before app/default sources        |

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
| `ansi_own_dir`   | str  | `"assets/ansi"`      | Own hand-crafted art — launched with `,`                                 |
| `ansi_acid_dir`  | str  | `"assets/ansi/acid"` | ACiD Productions art — launched with `.`                                 |
| `ansi_dir`       | str  | `"assets/ansi"`      | Legacy fallback key (kept for backward compatibility)                    |

---

## `[effects]`

Per-effect parameter overrides.  Keyed by **Python class name**.

Per-effect reactivity override:
- Optional key: `reactivity`
- If set, this is the absolute reactivity used by that effect
- If omitted, the effect uses global `audio.reactivity`

For a complete list of every effect's tweakable settings and defaults, see:

- [Effect Settings Reference](effect-settings.md)

```toml
[effects.Plasma]
speed = 2.0

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
| ANSIViewer        | `glow`      | 0.0–1.0    | Phosphor glow intensity         |
| ANSIViewer        | `crt`       | 0.0–1.0    | CRT barrel distortion strength  |
| ANSIViewer        | `slide_time`| 5.0–300.0  | Seconds per art piece           |
| AudioSpectrum     | `mode`      | 0, 1, 2    | 0=bars, 1=waveform, 2=both      |
| AudioSpectrum     | `glow`      | 0.0–1.0    | Bar glow                        |
| FractalZoom       | `max_iter`  | 32–512     | Iteration depth                 |
| UnicornTears      | `speed`     | 0.05–10.0  | Fall speed multiplier           |
| Raymarcher        | `speed`     | 0.05–10.0  | Scene animation speed           |

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
