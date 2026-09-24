# Streaming (OBS) and audio-runtime recommendations

Owner: perf seat
Status: **for owner review**
Last updated: 2026-09-24

Written for the owner to review: OBS settings for a high-quality visualizer
stream, what the machine's displays cost, and how to switch the audio
process onto the free-threaded Python that is now installed.  Everything
here is a recommendation; nothing in OBS or `config.toml` was changed.

## 1. OBS

Measured from the OBS log of the 15:30 session (10 minutes streamed,
QuickSync):

* Stream encoder in effect: `obs_qsv11_v2`, CBR **5,000 kbps**, TU3, High
  profile, 3 B-frames, lookahead 60, 2 s keyframes, 1080p30, AAC 128 kbps.
* **206 frames (1.1%) dropped for insufficient bandwidth / connection
  stalls.**  The upload is already the ceiling at 5 Mbps.
* The recording encoder's config file is empty, so a recording runs on
  OBS's defaults (no recording ran in that session to confirm them).

| Setting | Now | Recommend | Why |
|---|---|---|---|
| Settings → Advanced → Network → **Dynamically change bitrate** | off | **on** | Under congestion OBS lowers the bitrate briefly instead of dropping frames; dropped frames look far worse on a visualizer than a moment of softness. |
| Stream bitrate | 5,000 kbps | keep 5,000 until an upload test; then **6,000-8,000** if upload sustains ~1.5x the target | Visualizer content (dense detail, gradients, fast motion) rewards bits, but not bits the connection cannot carry. Check the platform's ingest maximum too. |
| Keep as is | TU3 · High · 3 B-frames · lookahead · 2 s keyint · CBR | — | Already right for QuickSync streaming. |
| Video → **Color range** | Full | **Partial** (keep Rec. 709) | Players and platforms expect limited range; full range can crush blacks and wash out saturated color. |
| Audio bitrate (track 1) | 128 kbps | **256 kbps** stream (320 for recordings) | It is a DJ set: the audio is the product. Costs ~130 kbps of upload. |
| Recording encoder | defaults | **ICQ, quality ~20** (lower is better), **TU1**, 3 B-frames, lookahead on — or CBR 30-50 Mbps | Recordings have no upload or latency limit; spend the quality there. Keep MKV and remux afterwards. HEVC (`obs_qsv11_hevc`) is an option for archives. |
| 60 fps (optional) | 30 | only with upload headroom | Much smoother motion for a visualizer, at ~1.5-2x the bitrate. |

Apply these in OBS with OBS closed-then-reopened as needed (its JSON files
are overwritten by a running OBS).

## 2. Displays

* Native outputs: two DisplayPort (1080p) and two HDMI — one of them
  **4K (3840x2160)**.  Fullscreen visuals on the 4K head render four times
  the pixels of a 1080p head on the Iris Xe.
* Two DisplayLink USB displays (the driver pre-creates four `evdi` devices;
  two are in use).  `DisplayLinkManager` compresses them in software: it
  used **~38% of a core** during the live profile.  Anything that can move
  to a native output costs nothing there.

## 3. Free-threaded Python for the audio process

**Installed:** `python3.14-freethreading` (3.14.7, Fedora package) and a
dedicated environment at `~/.local/share/unicorn-viz/venv-ft` with
free-threaded (`cp314t`) wheels of numpy 2.4.4, scipy 1.17.1, PyAV 18.0.0,
sounddevice 0.5.5, soundfile 0.14.0, cffi and charset-normalizer — the
same versions as the main environment where pinned.

**Verified:**

* The audio helper's full import set (core capture/analysis + dj-mixer-01's
  engine) loads under it with **the GIL still off**.
* End to end: the real helper started on this interpreter reported
  `free-threaded, GIL disabled`; analysis frames and onsets reached the
  app's normal (GIL) main process; the mixer engine loaded into the same
  helper and played.

**How to switch** (both lines, so capture and the mixer share it):

```toml
[audio]
process_python = "/home/jj/.local/share/unicorn-viz/venv-ft/bin/python"

[dj_mixer]
audio_process_python = "/home/jj/.local/share/unicorn-viz/venv-ft/bin/python"
```

The startup log then says `Audio process running (pid …, free-threaded,
GIL disabled)`.  Remove the lines to go back.

**Before a live set, soak it.**  Without a GIL the engine's own threads
(audio writer, command thread, loads) truly run at once.  Python objects
stay memory-safe, but logic that assumed one bytecode at a time — "check
this flag, then act" across threads — can now interleave.  Recommended: a
practice session of an hour or more with loads, stems, loops and
transitions, watching the mixer's `audio … block(s)` lines for
over-budget blocks or underflows, before using it on a stream.  What it
buys: the analyzer, the engine's render, decoding and the command thread
stop taking turns and use separate cores.
