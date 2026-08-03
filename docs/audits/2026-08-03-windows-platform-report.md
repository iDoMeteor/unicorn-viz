# Unicorn Viz — Windows Platform Report (2026-08-03)

Owner: owner + Claude (master coordinator)
Status: Complete — findings for the pre-RC1 Windows push
Last updated: 2026-08-03

Context: development happens on Fedora 44 (Wayland/PipeWire), but **Windows is
the primary target platform for the public release** and gets little testing.
An owner test on 2026-08-02 showed (a) small font/icon rendering issues and
(b) multi-head "acting a little goofy." This report explains both from the
code, sweeps the whole tree for other Windows breakage, and ends with a test
protocol. Companion docs:
[2026-08-03-full-system-audit.md](2026-08-03-full-system-audit.md) and
[docs/packaging/windows-native-deps-2026-07-11.md](../packaging/windows-native-deps-2026-07-11.md)
(the dependency-build field notes).

Severity here is Windows-specific: P1 = broken/crash on Windows, P2 =
degraded/wrong behavior, P3 = cosmetic/edge.

---

## 1) The two observed symptoms — ranked explanations

### 1.1 "Small font issues" — POSIX-only font paths → PIL's tiny bitmap fallback (confidence: HIGH)

Every PIL-based text surface except the core HUD searches **only
`/usr/share/fonts/...`** and falls back to `ImageFont.load_default()` — PIL's
~10 px fixed bitmap font — when nothing matches. On Windows nothing ever
matches, so all of these render with tiny, non-scalable text:

| Surface | Candidate list |
|---|---|
| dj-mixer-01 window UI | `drop-ins/dj-mixer-01/ui.py:137-143` |
| control-room-01 window UI | `drop-ins/control-room-01/control_room.py:59` |
| media-01 HUD | `drop-ins/media-01/ui.py:68-72` |
| banner-01 text | `drop-ins/banner-01/banner_controller.py:55-57` |
| Now-spinning card | `unicornviz/now_spinning.py:55-63` |
| CTA / tour big-text + emoji | `unicornviz/cta_overlay.py:274` (Symbola), `unicornviz/overlays.py:6246-6262` |

The core HUD is **immune** because `overlays.py:252` tries the bundled
`assets/fonts/ui-font.ttf` first — which is exactly the fix pattern:

- **Fix (P1, low effort):** prepend `resolve_path('assets/fonts/ui-font.ttf')`
  to every candidate list above (ideally via one shared helper in core), and
  add `C:\Windows\Fonts` candidates (`consola.ttf`, `lucon.ttf`,
  `arial.ttf`, and `seguiemj.ttf` for the emoji/eyebrow glyph path) after the
  bundled font. The Symbola-based emoji path currently has no Windows
  candidate at all, so tour/CTA decorative glyphs render as boxes.

### 1.2 "Icon issues" — no DPI awareness anywhere (confidence: HIGH for blur; MEDIUM for wrong-size)

There is **no `SDL_WINDOW_ALLOW_HIGHDPI` flag and no
`SDL_HINT_WINDOWS_DPI_AWARENESS` hint anywhere in the tree** (window flags:
`app.py:1433-1441`). On any Windows display scaled above 100% the process is
DPI-unaware, so Windows renders it at logical size and **bitmap-stretches the
whole window** — blurry text, blurry icons, and slightly-wrong perceived
sizes. Two knock-on effects:

- The help-icon bucket selector picks 152 px icons only when window width
  ≥ 3840 (`overlays.py:858`). A 4K monitor at 150% reports a logical width of
  2560, so the **76 px set is chosen and then OS-stretched** — small/blurry
  icons on exactly the hardware most Windows users run.
- All mouse/layout math operates in virtualized coordinates, which feeds the
  multi-head issue below.

**Fix (P1, low-medium):** set `SDL_HINT_WINDOWS_DPI_AWARENESS =
"permonitorv2"` before `SDL_Init`, add `SDL_WINDOW_ALLOW_HIGHDPI` to window
flags, and audit drawable-size vs window-size usage (`SDL_GL_GetDrawableSize`
where pixel sizes are needed). Re-test the 3840 bucket threshold afterward.

### 1.3 Multi-head "acting goofy" — stale display state + DPI virtualization (confidence: MEDIUM-HIGH)

Three compounding causes, in likelihood order:

1. **Display/origin state is never re-derived after startup.** The event loop
   handles only `RESIZED`/`FOCUS_LOST`/`FOCUS_GAINED`
   (`app.py:3981-3989`), and FOCUS_GAINED only toggles the cursor — the
   July audit's item 5 (re-derive on focus) was never implemented. There is
   no `SDL_WINDOWEVENT_MOVED` or `SDL_WINDOWEVENT_DISPLAY_CHANGED` handling,
   and multi-head layouts refresh only on monitor hotplug
   (`multihead.py` rebuild path). On Windows — where users routinely drag
   windows between monitors and the OS moves windows on wake/dock — overlay
   placement, the icon bucket, and mirror tiling all go stale.
2. **Per-monitor DPI virtualization skews the union/tile math.** The
   mirror/span union math itself is correct for negative origins
   (`multihead.py:140-151`, `:247-252` — Windows virtual-desktop coordinates
   left/above primary are handled), but `SDL_GetDisplayBounds` on a
   DPI-unaware process returns *virtualized* per-monitor rects. With mixed
   scale factors (e.g. 100% + 150%), the spanning borderless window and the
   per-display tile rects disagree with physical pixels → tiles land
   offset/scaled — "goofy."
3. **Span/mirror never requests real fullscreen** (`FULLSCREEN_DESKTOP` is
   single-display-only, `app.py:1441`), so the taskbar stays above the
   borderless window on Windows exactly like the GNOME panel did on Linux
   (July audit §4 — same design constraint, now on the primary platform).

**Fix (P2, medium):** implement the deferred display-state re-derivation
(on FOCUS_GAINED + add MOVED/DISPLAY_CHANGED handlers), then re-test spanning
with mixed DPI after the §1.2 DPI-awareness fix lands (which removes cause 2
entirely). Taskbar suppression needs the same design conversation as the
GNOME panel did.

---

## 2) Other Windows-specific breakage found

### P1 — broken on Windows

1. **Recording and streaming audio capture cannot work:** both default to
   ffmpeg `-f pulse` (`recording.py:44/126`, config default
   `audio_input_format = "pulse"`) and probe devices with `pactl`
   (`recording.py:110`, `rtmp_streamer.py:145`) — neither exists on Windows.
   Result: any recording/streaming with `capture_audio` enabled fails at
   ffmpeg spawn. Needs a platform-aware default (`dshow` with a device
   enumeration, and docs for enabling loopback capture).
2. **Recording/streaming stop paths raise on Windows:**
   `proc.send_signal(signal.SIGINT)` (`recording.py:315`,
   `rtmp_streamer.py:296`) is unsupported on Windows Popen (ValueError). In
   recording the exception is swallowed by the outer handler and the ffmpeg
   process is **orphaned with the MP4 unfinalized** (no moov atom → file
   unplayable); streaming similarly loses its only graceful-stop rung. Use
   `CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT` on Windows, or ffmpeg's
   `-nostdin`-compatible `q`/stdin-close path, then `terminate()`.
3. **ffmpeg itself is assumed on PATH** (`ffmpeg_path = "ffmpeg"`): no
   bundling yet (installer plan ★3 milestone bundles it). On a fresh Windows
   box, recording/streaming are dead on arrival even before items 1-2.

### P2 — degraded

4. **WASAPI loopback capture is unverified:** the device ranking prefers
   name-matched "loopback"/"stereo mix" input devices
   (`capture.py:160-170`) — correct intent, but PortAudio does not expose
   WASAPI loopback as an input device on all systems, and "Stereo Mix" is
   disabled by default on most modern drivers. Visualizing *system audio*
   (the core use case) may silently land on the microphone. Needs a live
   Windows test + a documented setup path (enable Stereo Mix / VB-Cable) or
   a WASAPI-loopback-specific capture path.
5. **APC mini LED path:** the libusb bypass loads only `.so` names
   (`apc_leds.py:126`), so on Windows it falls through the chain to plain
   rtmidi — *probably fine* (the snd_ump bug it bypasses is Linux-only), but
   the fallback has never been exercised on Windows hardware; and if raw USB
   access were ever needed there it requires a WinUSB driver (Zadig).
6. **python-vlc/media-01 requires an installed VLC**, and the July field
   notes show `python-rtmidi`/`moderngl` still need a hand-patched MinGW
   source build on Python 3.14 — the whole dependency story on Windows is
   developer-grade, not user-grade, until the installer reaches ★3 (bundled
   runtime + prebuilt wheels). See the field notes and installers.md P3.

### P3 / verified-clean list

- `SDL_VIDEODRIVER` forcing is correctly win32-guarded (`app.py:21`); the
  Wayland→X11 multi-head fallback cannot misfire on Windows.
- dj-mixer rtkit realtime setup is guarded `sys.platform != 'linux'`
  (`mixer_engine.py:463`) with the `resource` import inside the guard.
- spotify-01 explicitly disables the playerctl/MPRIS local backend on win32
  and falls back to Web-API polling (`spotify_controller.py:114-121`) — by
  design.
- webcam-01 handles Windows camera indexing (`sys.platform` checks
  throughout).
- Config/state writers use `Path.replace` (atomic on Windows) and pass
  `encoding='utf-8'` — no cp1252 or rename-over-existing hazards found.
- No `fcntl`/`termios`/`os.fork` anywhere outside the guarded rtkit path.
- URL opens use `webbrowser` (cross-platform), not `xdg-open`.

---

## 3) Recommended Windows test protocol (after the P1 fixes)

Run on a machine with two monitors at **different** scale factors (e.g.
1080p@100% + 4K@150%):

1. **Fonts:** open dj-mixer window, control room, banner config, now-spinning
   card, and the tour — confirm all text renders at design size (no tiny
   bitmap text, no box glyphs on the tour/CTA decorations).
2. **DPI:** confirm the window is crisp (not stretched) at 150%; open the
   help overlay on the 4K display and confirm the 152 px icon set is chosen
   (log line / visual sharpness).
3. **Multi-head:** enable mirror and span modes across both monitors;
   confirm tile alignment at both scale factors; drag the window between
   monitors and confirm overlays/HUD stay on the visible output; check
   whether the taskbar overlaps (expected until the fullscreen design
   conversation happens — document it).
4. **Recording:** record 30 s with audio; confirm the file finalizes
   playable, audio present, and stop is clean (no orphaned ffmpeg in Task
   Manager). Kill the RTMP endpoint mid-stream and confirm the app survives
   and stop works.
5. **Audio capture:** play system audio with no mic; confirm the visualizer
   reacts to the music (loopback), not room noise.
6. **MIDI:** APC mini mk2 pads light correctly over plain rtmidi; DDJ-REV1
   loads in dj-mixer.
7. **Cold start:** delete `runtime/`, rename `config.toml` away, first-boot
   with defaults — confirm no mixer/REV1/4-display assumptions break startup
   (see config-default findings in the main audit §9.5).
