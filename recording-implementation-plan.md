# In-App Recording Implementation Plan

This plan covers immediate implementation of built-in recording for Unicorn Viz.

Goals:
1. Record what the user actually sees in-app.
2. Support automatic recording on startup.
3. Make recording output location configurable.
4. Keep defaults safe and non-invasive.
5. Land a useful v1 quickly, then leave room for later optimization.

## Recommendation

Implement recording in two steps:

1. V1 now:
- final-frame capture from the composed screen output
- pipe raw RGB frames into `ffmpeg`
- hotkey start/stop
- optional auto-start on launch
- configurable output directory and encoding settings

2. V2 later if needed:
- async readback / PBO optimization
- optional audio muxing
- recording status overlay details

Reason:
1. V1 is enough to ship a usable feature fast.
2. V1 reuses the existing render pipeline and records the exact on-screen output.
3. The main risk is performance due to synchronous readback, which is acceptable for first implementation if clearly documented and configurable.

---

## Proposed Config Schema

Defaults in `unicornviz/config.py`:

```toml
[recording]
enabled = true
auto_record = false
directory = "recordings"
ffmpeg_path = "ffmpeg"
container = "mp4"
fps = 60
codec = "libx264"
preset = "veryfast"
crf = 18
pixel_format = "yuv420p"
capture_audio = false
filename_prefix = "unicornviz"
show_indicator = true
```

Notes:
1. `enabled`
- master gate for the feature and hotkey wiring

2. `auto_record`
- default: `false`
- user config: set to `true`

3. `directory`
- default: `./recordings`

4. `ffmpeg_path`
- allows custom path or wrapper script

5. `fps`
- defaults to 60 to match target runtime

6. `codec`, `preset`, `crf`, `pixel_format`
- enough control for quality/perf tradeoffs without overcomplicating the first version

7. `capture_audio`
- default `false` in V1
- leave room for later mux support without changing schema later

8. `filename_prefix`
- prefix for timestamped output names

9. `show_indicator`
- lets user hide the recording indicator if desired

### Planned local config change

When implementing, your local `config.toml` should get:

```toml
[recording]
auto_record = true
directory = "recordings"
```

---

## Runtime Behavior

### What gets recorded

Record the final composed frame:
1. effect output
2. transitions
3. invert pass
4. overlays that are visible at capture time

Capture point:
1. after `self._render(dt)`
2. after `overlays.render(dt)`
3. before `SDL_GL_SwapWindow(self._window)`

This ensures the recording matches what the user sees.

### Output naming

Format:

```text
recordings/unicornviz_YYYYMMDD_HHMMSS.mp4
```

### Auto-record

If `recording.auto_record = true`:
1. recorder starts automatically after startup is fully initialized
2. recorder starts after splash completes, so the main show is captured cleanly

Optional variant:
1. add a future flag if splash recording is wanted later

---

## Implementation Surfaces

### 1. New module

Create:
1. `unicornviz/recording.py`

Responsibilities:
1. own the `ffmpeg` subprocess
2. accept raw frame bytes
3. manage start/stop lifecycle
4. expose current recording status

Suggested API:

```python
class Recorder:
    def __init__(self, cfg: Config, width: int, height: int) -> None: ...
    def start(self) -> bool: ...
    def stop(self) -> None: ...
    def write_frame(self, rgb_bytes: bytes) -> None: ...
    @property
    def is_recording(self) -> bool: ...
```

### 2. App integration

Modify:
1. `unicornviz/app.py`

Add:
1. `self._recorder`
2. `self._recording_enabled`
3. `self._recording_indicator_text` or a small overlay hook

Flow:
1. initialize recorder after GL context exists
2. if `auto_record`, start it after splash and subsystem init
3. on each frame, if recording is active:
   - read `ctx.screen.read(components=3)`
   - vertically flip if needed before writing to ffmpeg
4. stop recorder cleanly on exit

### 3. Hotkey

Modify:
1. `unicornviz/hotkeys.py`
2. `unicornviz/overlays.py`
3. `docs/user-guide.md`

Suggested hotkey:
1. `V` to toggle recording on/off

Behavior:
1. if recording disabled in config, hotkey is ignored
2. if recording starts, show `REC ON` flash or indicator
3. if recording stops, show saved output path

### 4. Config docs

Modify:
1. `unicornviz/config.py`
2. `docs/configuration.md`
3. maybe `docs/user-guide.md`

### 5. CLI overrides

Modify:
1. `unicornviz/__main__.py`

Recommended CLI additions:
1. `--record`
2. `--no-record`
3. `--record-dir`
4. `--record-fps`
5. `--record-crf`

This keeps runtime control consistent with the rest of the app.

---

## ffmpeg Strategy

Command shape:

```bash
ffmpeg \
  -y \
  -f rawvideo \
  -pix_fmt rgb24 \
  -s WIDTHxHEIGHT \
  -r FPS \
  -i - \
  -an \
  -c:v libx264 \
  -preset veryfast \
  -crf 18 \
  -pix_fmt yuv420p \
  output.mp4
```

Why this baseline:
1. reliable
2. widely available
3. good quality-to-speed ratio

V1 constraints:
1. no audio mux yet
2. synchronous frame writes

---

## Known Concerns

### 1. Performance cost

Synchronous `ctx.screen.read()` is expensive and may reduce frame rate while recording.

Mitigation:
1. document this clearly
2. keep recording optional
3. let user combine with `render.internal_scale`
4. use `veryfast` preset by default

### 2. Backpressure if ffmpeg cannot keep up

Mitigation:
1. write to stdin carefully
2. trap broken pipe / subprocess failure
3. stop recording cleanly and show/log the failure

### 3. Color and orientation correctness

Mitigation:
1. validate frame orientation against screenshot logic
2. do a short recorded sample test before shipping as complete

### 4. Audio capture complexity

Do not solve in V1.

Reason:
1. current audio path is monitor/input driven and not packaged for easy muxing
2. video-only recording is enough for first delivery

---

## Phase 2 — Audio Mux Feasibility

Status:
1. implemented for Linux-first Pulse/PipeWire capture
2. still needs broader runtime validation and cross-platform follow-up

### Recommended approach

Use ffmpeg to mux a second audio input directly, rather than trying to reuse the in-process `sounddevice` stream.

Why:
1. the current app audio path is designed for analysis/reactivity, not for writing muxable encoded output
2. ffmpeg already handles A/V muxing, resampling, and sync much better than a first-pass custom solution would
3. it keeps the recording code simpler and isolates audio capture failures from the reactivity path

### Linux-first strategy

Current path:
1. configurable ffmpeg audio input source
2. PulseAudio/PipeWire input via ffmpeg device flags
3. empty device string auto-resolves to the default sink monitor via `pactl`

Implemented config:

```toml
[recording]
capture_audio = true
audio_input_format = "pulse"
audio_input_device = ""
audio_codec = "aac"
audio_bitrate = "192k"
```

Current ffmpeg shape:

```bash
ffmpeg \
  -y \
  -f rawvideo -pix_fmt rgb24 -video_size WIDTHxHEIGHT -framerate FPS -i - \
  -f pulse -i <default-sink>.monitor \
  -c:v libx264 -preset veryfast -crf 18 \
  -c:a aac -b:a 192k \
  -pix_fmt yuv420p \
  output.mp4
```

### Remaining concerns

1. Device naming varies across PipeWire/Pulse setups.
2. The current app may react to one source while ffmpeg records another unless recording audio input is explicitly configured to match.
3. Auto-fallback monitor selection in the app does not automatically translate to a good ffmpeg input string.
4. Startup ordering matters: we need the video recorder and audio input to come up without hanging the app.

### Remaining follow-up scope

Include:
1. optional audio capture with explicit config
2. Linux-first Pulse/PipeWire support
3. graceful fallback to video-only if audio input fails

Do not include initially:
1. perfect automatic audio-device mirroring from the app reactivity input
2. per-platform audio mux support beyond Linux
3. live waveform/level monitoring in the recorder UI

---

## Validation Plan

### Automated / headless

1. syntax check new/changed files
2. recorder start/stop unit-like subprocess smoke test
3. create a short 2–3 second recording in a test run
4. verify file exists in configured directory

### Manual

1. start app with `auto_record = true`
2. confirm file appears in `./recordings`
3. toggle recording with hotkey while app runs
4. verify output plays correctly in VLC/mpv
5. confirm overlays and transitions appear in the recording
6. test with `internal_scale = 0.85`

---

## Immediate Implementation Order

1. Add config defaults and docs
2. Add `Recorder` module with ffmpeg subprocess lifecycle
3. Integrate recorder into `app.py`
4. Add hotkey toggle and overlay messaging
5. Add CLI overrides
6. Set local `config.toml` to `auto_record = true`
7. Run short real recording validation

---

## Recommended scope boundary for the first commit

Include:
1. video-only mp4 recording
2. auto-record option
3. configurable output directory
4. hotkey toggle
5. docs + CLI support

Do not include yet:
1. audio muxing
2. gif/webm export
3. async readback optimization
4. advanced recording HUD

That keeps the first implementation shippable and reviewable.