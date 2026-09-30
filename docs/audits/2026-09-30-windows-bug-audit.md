# Windows bug audit (2026-09-30)

Owner: DJ Unicorn Tears
Status: complete — all findings open; nothing fixed in this pass
Last updated: 2026-09-30

Third report of the 2026-09-30 series, after
[2026-09-30-bug-audit.md](2026-09-30-bug-audit.md) and
[2026-09-30-auto-vj-director-recommender-audit.md](2026-09-30-auto-vj-director-recommender-audit.md).

**Scope.**
- Windows-specific bugs in core and every drop-in, at master `ee8834c`.
- Weighted toward what landed since the
  [2026-08-03 Windows platform report](2026-08-03-windows-platform-report.md):
  the audio process, DJ mixer, media-01, video decks, config menu, Control
  Room and video-out.
- It follows the product as it would actually run on Windows:
  - the installer bundles **CPython 3.11** (`tools/packaging/fetch_runtime.sh:38`
    pins `3.11.10`; `docs/planning/installers.md:625`, `746`);
  - installer shortcuts launch **`pythonw.exe`** (no console,
    `installers.md:1746`);
  - the interim bootstrap `tools/install/windows_deps.ps1` accepts any
    Python 3.11+.

**Method.**
- No Windows machine was available.
- Mechanical sweeps over core and drop-ins:
  - POSIX-only APIs;
  - Linux-only binaries and paths;
  - text I/O and subprocess output decoded with the locale codec;
  - string path handling;
  - `ctypes` library names;
  - stdlib APIs newer than 3.11;
  - glob case sensitivity;
  - rename-over-existing.
- Byte-compiled the tree under Python 3.11 and 3.12 (clean).
- Built a scratch **3.11 venv from the pinned `requirements.txt`** and ran
  the core suite and the dj-mixer suite in it.
- Where Windows behaviour could be reproduced off-Windows it was:
  - the real `sounddevice` 0.5.5 name resolver against a Windows-shaped
    device list;
  - `faulthandler` with `sys.stderr = None` (what `pythonw` gives you);
  - `tomllib` on a Windows path;
  - the capture claim logic with Windows device names;
  - libvlc's `--aout` fallback.

Marked **VERIFIED** where reproduced; the rest cite exact lines.

**Python 3.11 run** (`/var/tmp/uv-bug-audit/venv311`):
- Core: 2,767 passed, 4 failed.
  - 3 are `test_remote_objects.py` shared-memory tests: W1, reproduced by
    the existing suite.
  - 1 is `test_self_test.py`, which spawns `python -m unicornviz` in an
    unpackaged venv, an artifact of the scratch environment.
- dj-mixer-01: 1,469 passed, 4 failed.
  - `test_audio_process.py::test_load_play_render_and_read_back` fails on
    W1: the mixer's own end-to-end proof that tracks can't load in the
    audio process.
  - 3 `test_tags.py` failures come from `mutagen` not being installed: W2.
- The suites pass on the dev box only because it runs 3.14 with extra
  packages installed by hand.

---

## Summary

| ID | Sev | One line |
|---|---|---|
| W1 | P1 | The audio process uses a Python-3.13-only `SharedMemory` parameter, so on the bundled 3.11 runtime **no mixer track, stem or sampler pad can load** — **VERIFIED** (all installed builds, Linux too) |
| W2 | P1 | The installers install only the root `requirements.txt`: PyAV, mutagen, python-vlc (and mediapipe, usd-core, ably, demucs) are missing — **VERIFIED** on a clean install |
| W3 | P1 | Core capture has no WASAPI loopback path, so a stock Windows machine visualizes **the microphone** |
| W4 | P1 | Mixer output devices picked in its own menu fail to open: bare names are ambiguous across Windows host APIs — **VERIFIED** |
| W5 | P2 | Before Python 3.13, `time.monotonic()` on Windows ticks every 15.6 ms, and it timestamps every onset and the beat grid |
| W6 | P2 | Under `pythonw`, the documented `faulthandler = false` / `level = "NONE"` settings crash startup silently — **VERIFIED** |
| W7 | P2 | Under `pythonw`, every ffmpeg / PowerShell / demucs spawn opens its own console window (one for the whole recording) |
| W8 | P2 | A normal Windows path in `config.toml` (`"C:\Users\…"`) stops the app from starting, or silently becomes a different path — **VERIFIED** |
| W9 | P2 | Recording/streaming audio device lookup is English-only and decodes ffmpeg output with the wrong codec |
| W10 | P2 | With the mixer on the built-in Realtek output, capture refuses Realtek **Stereo Mix** (the stock loopback) as "claimed" — **VERIFIED** |
| W11 | P2 | Help-rail links use `xdg-open`, so they silently do nothing on Windows |
| W12 | P2 | lyrics-01 ignores the now-playing hub, so there are no lyrics for mixer or media playback on Windows |
| W13…W24 | P3 | See the P3 table |

---

## P1

### W1. The audio process can't load tracks on the bundled Python 3.11 — VERIFIED

**Where:** `unicornviz/remote_objects.py:279`, `291`, `371` — `shared_memory.SharedMemory(..., track=False)`.

**What happens:**
- The `track` parameter was added in Python 3.13.  On 3.11 and 3.12 it
  raises `TypeError: SharedMemory.__init__() got an unexpected keyword
  argument 'track'`.
- In the audio helper (`[audio] process` and `[dj_mixer] audio_process`,
  both default on) every large array goes through it:
  - `adopt_array()` for each deck load (`deck.py:980`), stem set
    (`deck.py:1168`) and sampler pad (`sampler.py:63`, `85`);
  - and publishing any array ≥ 1 MB.
- So loading a track fails, and the deck is left half-loaded (metadata of
  the new track, no samples).
- Every installer bundles 3.11.10, including the finished Linux one-liner,
  so **this is broken in every installed build**, not only on Windows.
- The owner's dev box runs 3.14, which is why it has never been seen.

**Evidence:**
- `adopt_array()` on a 4-minute stereo buffer, inside a helper-style
  exporter: fails on 3.11.15, works on 3.14.6.
- The existing suites prove it on 3.11: three core
  `test_remote_objects.py` tests and dj-mixer's
  `test_audio_process.py::test_load_play_render_and_read_back` all fail
  with this `TypeError`.

**Fix direction:**
- Pass `track` only when `sys.version_info >= (3, 13)`.  On older
  versions, `track=False` is Windows' default behaviour anyway; on POSIX,
  unregister from the resource tracker by hand.
- Run the suites once under the bundled interpreter before each release.
  A local check is enough; CI workflows are installer-team-only.

### W2. Installed builds lack the drop-ins' dependencies — VERIFIED

**Where:**
- `tools/install/lib.sh:258` and `tools/install/windows_deps.ps1:119`
  install only the root `requirements.txt`.
- Drop-ins declare their own dependencies in `drop-ins/*/requirements.txt`.

**What happens:** a clean install from the root `requirements.txt` has no:
- `av` — videos-01, video-postfx-01, the mixer's music-video decks;
- `mutagen` — media-01 and mixer tag reads/editing (titles and artists in
  the libraries);
- `python-vlc` — media-01 playback.  The bootstrap only checks that
  `libvlc.dll` exists;
- `mediapipe` — webcam-01;
- `usd-core` — sims-01;
- `ably` — chat-01;
- `demucs` — mixer stems.

Each drop-in degrades or disables itself, so nothing crashes, but the
installed product is missing features the dev tree has.

**Fix direction:**
- The installers should also install `drop-ins/*/requirements.txt` for
  the drop-ins they ship, or the root file should list the non-optional
  ones.
- This belongs to the installer team; it's reported here because it was
  found in this pass.

### W3. A stock Windows machine visualizes the microphone

**Where:** `unicornviz/audio/capture.py:116`, `281-284`, `485-499`.

**What happens:**
- The Windows ranking puts `'wasapi'` + `'loopback'` devices first, then
  `'stereo mix'` / `'what u hear'`.
- The pinned `sounddevice` 0.5.5 cannot open WASAPI loopback:
  `WasapiSettings` takes only `exclusive`, `auto_convert` and
  `explicit_sample_format`.  So no stock device is ever named "loopback".
- "Stereo Mix" ships disabled on most drivers.  Its name is also
  localized: "Stereomix" (German), "Mixage stéréo" (French), "Mezcla
  estéreo" (Spanish).
- With nothing classified as an output, `_default_viable_keys()` enables
  everything and the OS default input, the microphone, wins.
- The 08-03 report had this as "unverified P2"; the library check makes it
  definite.

**Fix direction:**
- A real loopback path: PyAudioWPatch, or `soundcard`'s loopback, behind
  the capture interface.
- Until then, detect "no loopback source" on Windows and tell the operator
  (enable Stereo Mix / install a virtual cable) instead of silently using
  the mic.
- Match the localized Stereo Mix names.

### W4. Mixer output devices chosen in the mixer's own menu can't open — VERIFIED

**Where:**
- `drop-ins/dj-mixer-01/ui.py:11535-11557` (`_device_choice_options`).
- Opens at `mixer_engine.py:1822`, `1839`, `1864`.

**What happens:**
- The picker stores bare device names, de-duplicated by name.
- Windows lists every endpoint once per host API (MME, DirectSound,
  WASAPI, WDM-KS), usually with the identical name.
- `sounddevice`'s resolver raises `Multiple output devices found` when a
  name matches exactly under more than one host API.  Only
  `"name, Windows WASAPI"` resolves.
- So master and headphone devices picked from the menu fail to open on
  Windows.  The same happens with a hand-typed name like `"DDJ-REV1"`.

**Evidence:** the real `sounddevice` 0.5.5 `_get_device_id` against a
Windows-shaped device list:
- `'Speakers (DDJ-REV1)'` → ValueError;
- `'DDJ-REV1'` → ValueError;
- `'Speakers (DDJ-REV1), Windows WASAPI'` → device 2.

**Fix direction:**
- Store `"<name>, <host API>"` (prefer WASAPI on Windows), or store the
  index plus name and re-resolve.
- Also pass `extra_settings=sd.WasapiSettings(auto_convert=True)`.  The
  mixer is fixed at 48 kHz, and WASAPI shared mode rejects a rate that
  differs from the device's mix format (commonly 44.1 kHz).

---

## P2

### W5. 15.6 ms timestamps on onsets and the beat grid

**Where:**
- `unicornviz/audio/analyzer.py:816` stamps each processed block with
  `time.monotonic()`.
- That time becomes every onset's `t` and, via `AudioManager.get_audio_time()`,
  the beat tracker's timebase (`auto_vj.py:5412-5431`).

**What happens:**
- Before Python 3.13, `time.monotonic()` on Windows is `GetTickCount64`,
  with 15.6 ms resolution; 3.13 moved it to `QueryPerformanceCounter`.
- The shipped runtime is 3.11.
- Against ~21 ms audio blocks, onset timestamps land on a 15.6 ms grid: up
  to ±3% of a beat interval at 128 BPM, feeding the tempo and phase
  estimates.

**Fix direction:** stamp audio from the sample clock (block count ×
block size ÷ rate), which is also more correct on every platform than
processing-time stamps; or use `perf_counter()`.

### W6. `pythonw` + faulthandler settings = silent startup crash — VERIFIED

**Where:**
- `unicornviz/__main__.py:410-413`: `faulthandler.enable()` with no file.
- `stall_watchdog.py:78`: `dump_traceback_later()` with no file, re-armed
  every frame from the unguarded `app.py:6724`.

**What happens:**
- Under `pythonw`, `sys.stderr` is `None`, and both calls raise
  `RuntimeError: sys.stderr is None` (reproduced on 3.11 and 3.14).
- Defaults are safe because they open a log file.
- But `[logging] faulthandler = false`, documented as the release switch
  for rigs that don't want a logs folder, or `level = "NONE"`, makes the
  Windows app exit before its window opens, with no console to say why.
- Related: `print(..., file=sys.stderr)` for config-validation errors
  (`__main__.py:618`) and the audio-failure message are invisible under
  `pythonw`, so a bad config also just means "it doesn't start".

**Fix direction:**
- Skip or redirect `faulthandler` when `sys.stderr is None`.
- Show startup errors in an `SDL_ShowSimpleMessageBox` on Windows.

### W7. Console windows under `pythonw`

**Where:** every `subprocess` launch of a console program:
- recording ffmpeg (`recording.py:701`; only `CREATE_NEW_PROCESS_GROUP`);
- streaming ffmpeg (`rtmp_streamer.py:468`);
- hardware-encoder probes (`recording.py:166`);
- `dshow` listing (`recording.py:542`, `rtmp_streamer.py:308`);
- the mixer's PowerShell folder picker (`native_dialog.py:71`) and demucs
  (`stems.py:578`).

Nothing passes `CREATE_NO_WINDOW`.

**What happens:**
- A GUI process spawning a console program gets a new console window for
  it.
- A recording or stream shows a black ffmpeg console for its whole
  duration.  It can take focus from the show window, and closing it kills
  the recording.
- Starting a recording flashes two probe consoles first.
- (`SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS` is already 0, so the show window
  won't minimize.)

**Fix direction:** one helper that adds `CREATE_NO_WINDOW` on win32, used
by every spawn.

### W8. Windows paths in `config.toml` — VERIFIED

**Where:** `Config.__init__` (`config.py:426-431`), unguarded in `main()`
(`__main__.py:614`).

**What happens:**
- In TOML, double-quoted strings treat `\` as an escape.
- `directory = "C:\Users\dj\Videos"` raises `TOMLDecodeError: Invalid hex
  value` before logging exists, so the app doesn't start (silently, under
  `pythonw`).
- `"C:\new\tracks"` parses *successfully* as a newline and a tab: a wrong
  path with no error.
- Nothing in `docs/configuration.md` or `config.dist.toml` warns about it.
- The config menu is retiring the file, but the owner and users still
  edit it.

**Fix direction:**
- Catch the parse error and name the line.
- Document single-quoted (`'C:\Users\…'`) or forward-slash paths.
- Optionally warn on control characters in path-like values.

### W9. Recording/streaming audio device lookup fails on non-English Windows

**Where:** `recording.py:534-557` and its copy at `rtmp_streamer.py:301-324`.

**What happens:**
- The lookup matches only English names (`'stereo mix'`, `'loopback'`, …),
  so German "Stereomix", French "Mixage stéréo" and Japanese
  "ステレオ ミキサー" aren't found.
- ffmpeg's listing is UTF-8 but is decoded with `text=True` (the ANSI
  code page).  Non-ASCII names come back mangled; when they don't match,
  or bytes that cp1252 can't decode make it raise (caught as "enumeration
  failed"), the device isn't found.
- Either way, recording and streaming proceed **without audio**.

**Fix direction:**
- `encoding='utf-8', errors='replace'`.
- Localized name hints, and a config override for the device name.

### W10. Capture refuses the stock loopback when the mixer uses the same brand of output — VERIFIED

**Where:**
- `capture.py:64-68` (`_DEVICE_GENERIC_TOKENS`) and `1135-1152`.
- Claims published from `mixer_engine.py:1749-1766`.

**What happens:**
- The "claimed device" guard exists for the Linux DDJ-REV1 case, where a
  second open of an exclusive ALSA device kills the process.
- It matches on distinctive name tokens, but the generic-word list has no
  Windows vocabulary ("speakers", "realtek", "microphone", "high
  definition").
- With the mixer's master set to "Speakers (Realtek(R) Audio)", the
  claimed tokens are `{speakers, realtek}`.  Capture then refuses "Stereo
  Mix (Realtek(R) Audio)" (the only stock loopback), the microphone and
  line-in.
- On Windows (shared mode) opening a different endpoint is harmless.

**Fix direction:**
- On Windows, match claims by exact device index / endpoint, not by token.
- Or extend the generic list with the common Windows words.

### W11. Help-rail links don't open on Windows

**Where:** `App._open_external_url`, `app.py:8803-8817`.

**What happens:** it launches `['xdg-open', url]` unconditionally.  On
Windows that raises `FileNotFoundError`, which is caught, and the rail
flashes "failed to open link".

**Fix direction:** `webbrowser.open()`, which is already used elsewhere,
or `os.startfile()` on win32.

### W12. lyrics-01 never sees mixer or media playback on Windows

**Where:** `drop-ins/lyrics-01/lyrics_controller.py:225-280`.

**What happens:**
- Now-playing comes from `get_subsystem('spotify')`, then
  `playerctl`/MPRIS.
- It never uses the core now-playing hub, where dj-mixer-01 and media-01
  publish.
- Windows has no MPRIS, so lyrics only work with Spotify there.  It also
  spawns a `playerctl` attempt on a new thread every poll, forever.

**Fix direction:**
- Read `vj_api.active_now_playing()` first.
- Skip `playerctl` when `shutil.which('playerctl')` is None.

---

## P3

| ID | Where | Finding |
|---|---|---|
| W13 | `drop-ins/cta-01/cta_editor.py:632-654` | The CTA editor tries only Linux font paths, then `ImageFont.load_default()` (no size): PIL's tiny bitmap font on Windows — the 08-03 "small font" symptom, fixed in core but not here.  Use `unicornviz.fonts`. |
| W14 | `drop-ins/effects-retro/ansi_viewer.py:139` | `glob("*.ans") + glob("*.ANS")`: Windows globbing is case-insensitive, so every ANSI piece is listed **twice** (the ACiD pack is uppercase). |
| W15 | `drop-ins/dj-mixer-01/native_dialog.py:56-77` | The PowerShell folder picker's output is in the OEM code page but decoded as ANSI, so a folder like `D:\Música` comes back as `D:\M£sica`.  Set `[Console]::OutputEncoding` to UTF-8 in the script and decode UTF-8.  (It also opens a console window; see W7.) |
| W16 | `unicornviz/effects/registry.py:50-60` | `_pack_of()` tests for `'/drop-ins/'` in a native path, so every effect reads as pack "core" on Windows (effects browser pack column, category of untagged effects).  Use `Path.parts`. |
| W17 | `app.py:4555-4560`; dj-mixer `ui.py:11518-11533` | The free-threaded interpreter lookup is POSIX-only (`$XDG_DATA_HOME/…/venv-ft/bin/python`), so the option can never appear on Windows (`Scripts\python.exe`, `%LOCALAPPDATA%`). |
| W18 | `drop-ins/projectm-01/projectm_effect.py:329-334` | `projectm_load_preset_file(path.encode('utf-8'))`: libprojectM opens narrow paths in the ANSI code page, so a per-user install under a non-ASCII profile (`%LocalAppData%\Programs\…` for `José`) can't load any preset.  The owner's 10,341 presets have no non-ASCII names, so only the install path matters. |
| W19 | hotkey tables | AltGr on international layouts arrives as Ctrl+Right-Alt, so the Ctrl+Alt+letter hotkeys (`Ctrl+Alt+F` grand finale, `Ctrl+Alt+J` Auto VJ, …) fire from AltGr+letter outside text fields.  Text fields themselves are safe (verified: the core search modes and the CTA editor consume all keys). |
| W20 | `recording.py:130-137` | Windows encoder candidates are NVENC and QSV only; no `h264_amf`, so AMD GPUs always record with software x264. |
| W21 | `unicornviz/midi.py:593-627` | WinMM MIDI inputs are exclusive.  `add_input_device()` de-duplicates by hint, not port, so if `[midi] device` also matches the DDJ-REV1 the mixer's aux open fails, on Windows only. |
| W22 | `capture.py:156-335` | The capture selector lists each device once per host API (MME names truncated to 31 chars), and tie-breaks by index put high-latency MME entries first. |
| W23 | runtime/profile/track stores | `os.replace` raises `PermissionError` when an antivirus scanner or indexer has the target open, so saves are lost with a warning and no retry.  Deep library paths beyond 260 characters fail without `LongPathsEnabled`. |
| W24 | `drop-ins/media-01/media_controller.py:425` | `--aout=pulse` is forced for a Linux crash.  On Windows, libvlc falls back to the platform output (tested: an unknown `--aout` falls back rather than failing), so audio works.  But the volume/aout race guarded by `_output_is_live()` is untested on Windows' `mmdevice`. |

Checked and **not** bugs:
- libvlc's forced `--aout` falls back instead of going silent (tested).
- The worker pool uses spawn with a guarded `__main__`.
- The audio helper exits when the main process dies (pipe EOF/OSError).
- projectM preset keys use `as_posix()`.
- video-out's v4l2/PipeWire, the mixer's rtkit/`resource` and `fcntl` are
  platform-guarded.
- The SDL DPI and minimize-on-focus-loss hints are set on win32.
- Mixer sample and split-recording names are sanitized.
- The MIDI profile TOML writer escapes backslashes.
- Glyph fonts in core resolve the bundled font first.
- The tree compiles under 3.11 and 3.12.

## Status of the 2026-08-03 Windows report

| 08-03 item | Status now |
|---|---|
| Small fonts (POSIX-only font paths) | Fixed in core and the mixer; **still open in the CTA editor** (W13) |
| Blurry icons (no DPI awareness) | Fixed (`SDL_WINDOWS_DPI_AWARENESS=permonitorv2`) |
| Multi-head stale display state | Fixed (`_refresh_display_state('focus gained')`) |
| ffmpeg `-f pulse` / `pactl` defaults | Fixed (`dshow`); **the new lookup is English-only and mis-decodes** (W9) |
| `send_signal(SIGINT)` on Windows | Fixed (`CTRL_BREAK_EVENT` + process group); note that CTRL_BREAK can't reach a child from a console-less `pythonw` parent, so stdin-close is the real stop path |
| ffmpeg not bundled | Installer work (★3), unchanged |
| WASAPI loopback unverified | **Now definite: not possible with the pinned library** (W3) |
| APC LEDs over plain rtmidi | Still unverified on hardware |
| python-vlc / VLC dependency | Unchanged, and now also **not pip-installed at all** by the installers (W2) |
