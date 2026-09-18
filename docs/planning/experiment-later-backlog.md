# Ideas to Experiment With Later

Owner: (see individual entries)
Status: living backlog
Last updated: 2026-09-18

Technically-plausible ideas surfaced in conversation, verified enough to be
worth doing someday, but not queued as active work. Not a roadmap — nothing
here is committed or scheduled. Newest entries at the top; pull one into its
own planning doc (or straight into an implementation task) when it's
actually time to build it.

## media-01: replace VLC/mpv/ffplay with PyAV + sounddevice (2026-09-18)

**What:** Drop media-01's VLC/mpv/ffplay playback-backend chain and switch
to the same PyAV-decode + `sounddevice.OutputStream` approach dj-mixer-01
and videos-01 already use. Crossfading would move from VLC's two-
`MediaPlayer` volume-ramp hack to the mixer's own real DSP crossfade —
`equal_power_gains()` (a pure cosine/sine curve, `mixer_engine.py`) mixing
two fully-decoded numpy buffers directly.

**Why it's attractive:**
- `av`, `sounddevice`, and `soundfile` are already in the venv — two other
  drop-ins depend on them, so this is zero new installs, not a new
  dependency decision.
- media-01 already has half the decode path: the `soundfile` → PyAV
  fallback written for auto-level's loudness measurement (0.27.0) is the
  exact same pattern `dj-mixer-01/deck.py`'s `_decode()` uses.
- Removes a dependency chain with real prior pain — the VLC/PipeWire
  `pw_thread_loop_lock` segfault fixed in media-01 0.15.1 (forced
  `--aout=pulse`) exists only because VLC is in the picture at all.
- A side benefit: auto-level's `measure_gain()` already fully decodes the
  file just to compute a loudness scalar, then throws that buffer away and
  lets VLC decode the same file again to actually play it. A PyAV-backed
  player could reuse that one decode for both.

**The real trade-off:** decode-ahead-of-time instead of streaming — a
track needs a moment to finish decoding in the background before it can
start (media-01 already prescans its whole library the same way, so this
isn't a foreign pattern here) and lives in memory as float32 for its
runtime — roughly 110MB for a 5-minute stereo track. It's a full backend
swap, not a small patch: replaces `_VlcBackend`/`_SubprocessBackend`
entirely and touches load/play/seek/volume/pause end to end.

**Status:** proposed via the owner (relaying another team's suggestion),
technically verified 2026-09-18 against `dj-mixer-01/deck.py` and
`mixer_engine.py` (imports, `_decode()`, `equal_power_gains()`, the
`OutputStream` writer loop). Parked here rather than actioned immediately.
