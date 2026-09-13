# Music Video Decks — Plan (2026-09-13)

Owner: Auto VJ strategist seat (design), dj-mixer-01 / videos-01 / core /
auto-vj-01 seats (implementation)
Status: consensus reached with the owner 2026-09-13; tickets issued; nothing
implemented yet
Last updated: 2026-09-13

## What the owner asked for

Music videos live in the DJ crates like any other track. When the DJ drops
one on a deck (or auto-play loads it), the deck treats it as a track:
waveforms, analysis (BPM, key, structure), stems. When that deck is faded
in, the visualizer fades to the video itself; when the DJ fades to another
deck, the video fades back out. The video follows the DJ: scratching,
looping, cueing and pitch all scrub or jump the picture. All three drop-ins
(dj-mixer-01, auto-vj-01, videos-01) must be present for the feature; any
one absent degrades gracefully to today's behavior.

Owner decisions (2026-09-13):

1. **Videos are recognized anywhere in the crates by extension.** No
   special folder rule.
2. **Postfx applies over the video by default**, with a toggle.
3. **The visualizer keeps rendering under an opaque video**; optimize only
   if the cost shows.

## The design in one sentence

**The deck is the clock.** The video never plays itself: every frame, the
video source is asked for the frame nearest the deck's own playhead, which
already accounts for pitch, scratch, cue jumps, loops, backspins and pause.
The mixer keeps playing the audio exactly as for any track. Scrubbing,
looping and cueing fall out for free because they are already what the
playhead does.

## Why not switch effects

The core's effect transitions are fixed-duration blends, not fader-driven;
auto VJ would fight an effect swap; and two video decks mid-crossfade
cannot both be "the active effect". So the video is a **layer in the
composite chain** whose opacity is the deck's audibility, not an effect.
videos-01's existing `VideoPlayer` effect (own audio output, forward-only
decode) stays untouched; the feature adds a new non-effect class beside it.

## The four pieces

### 1. dj-mixer-01 (mixer seat)

- `library.py`: add video extensions (`.mp4 .mkv .mov .webm .m4v .avi`)
  to the scan set; a track record gains `has_video: bool` (derived from
  the path, not from analysis — no `ANALYSIS_VERSION` bump); the browser
  shows a small video badge.
- `deck.py`: `_decode()` already falls through to PyAV, which opens video
  containers — verify that the soundfile attempt fails cleanly and the
  audio stream is picked; a video file with no audio stream is rejected
  with a message. BPM / key / structure / waveforms operate on the decoded
  PCM and need no change.
- Stems: `stems.py` shells out to Demucs on the source file; **verify
  whether Demucs accepts a video container**. If not, extract the audio
  track to the stem cache bucket (PyAV, WAV) and run Demucs on that; the
  manifest records the source container.
- **Publish deck state on the vj_api bus at frame rate**, new method pair
  `publish_deck_state(source, payload)` / `get_deck_state()` (core adds the
  bus methods; the mixer calls them). Payload per deck: `deck`, `path`,
  `has_video`, `position_s` (`Deck.position()`), `rate` (1 + pitch, signed
  during scratch/backspin), `playing`, `audibility` (the mixer's existing
  channel-fader × crossfader × master figure, normalized so a fully-open
  deck at master 1.0 reads 1.0; hamster handled inside as today), plus
  `crossfader`. Cheap: read-only attributes, no snapshot dicts.
- Version bump, README changelog, docs/adr entry in the mixer's own docs.

### 2. videos-01 (video seat)

- New module-level class `DeckVideoSource(path)` in `video_player.py` (or
  a sibling module): PyAV decoder, **no audio, no GL, no thread affinity
  assumptions** beyond "frames are produced on a worker thread and
  consumed on the caller's thread".
- API: `set_target(t_seconds, rate, playing)` called every frame;
  `frame_for(t) -> (pts, rgb24 ndarray) | None` returns the cached frame
  nearest `t` without blocking; `close()`.
- **Seeking model**: compressed video seeks land on a keyframe and decode
  forward, far too slow at 60 Hz while scratching. Keep a **rolling ring of
  decoded frames** covering the last `cache_window_s` (default 4 s, config)
  at reduced resolution (default long edge 960, config) so back-and-forth
  within a scratch or a loop is a cache hit; only a target outside the
  ring triggers a keyframe seek + decode-forward. Forward play decodes
  ahead by ~1 s at the current rate. Reverse play and pause are cache
  reads. Nearest-PTS is sufficient; no frame interpolation.
- Tests with a synthetic video written by PyAV (no fixtures): nearest-frame
  correctness, cache hit on reverse scrub, seek on a far jump, no blocking
  on `frame_for`, clean close with a parked decoder.
- Version bump, README changelog.

### 3. Core (core seat)

- `vj_api`: `publish_deck_state` / `get_deck_state` (same shape as the
  other publish/get pairs), plus `get_video_layer_opacity()` for auto VJ.
- `app.py`: `_load_deck_video_source_class()` via `load_dropin_symbol`,
  guarded, `None` when videos-01 is absent (drop-in independence rule; the
  three existing load sites stay as the pattern).
- **`VideoDeckLayer`** in the composite chain: reads deck state each frame;
  holds up to two `DeckVideoSource`s keyed by deck path (open on load,
  close on unload); calls `set_target` with the deck's position/rate/
  playing; uploads the frame it gets back to a texture; draws a
  letterboxed fullscreen quad with opacity = that deck's audibility. Two
  video decks: two quads, each at its own audibility, drawn in deck order.
  Drawn **before the postfx chain** by default (decision 2), with
  `[video_decks] postfx_over_video = true|false`; when false the layer is
  drawn after postfx. The visualizer keeps rendering underneath at all
  opacities (decision 3).
- Config: `[video_decks] enabled = true` (new features default on),
  `cache_window_s`, `cache_long_edge`, `postfx_over_video`. Commented
  section added to `config.toml`.
- HUD: a status pill while a video layer is visible (`VIDEO A 82%`).
- Independence check after landing: all four load sites guarded, no bare
  drop-in imports.
- Core version bump, changelog, `docs/configuration.md`, ADR entry in
  `docs/adr/vj-system.md` (a new runtime surface and a new bus channel).

### 4. auto-vj-01 (auto VJ seat)

- Read `get_video_layer_opacity()`; while it is ≥ `video_swap_hold_opacity`
  (default 0.9) suppress effect swaps and ping-pong pinning (nobody can see
  them) but keep the director, drop/impact postfx and scroll effects
  running. Counter `video_layer_swap_suppressed_count` on corpus rows;
  packager key; director rc bump; weights doc + changelog + ADR note.

## Sequencing

1. **Mixer and videos-01 in parallel** (independent). The mixer half is a
   milestone on its own: a video dropped on a deck plays, analyzes and
   shows waveforms before any pixels move.
2. **Core layer** once both exist (needs the bus payload and the source
   class).
3. **Auto VJ gate** last (needs the layer opacity).

## Risks named up front

- Scratch fidelity is the hard part (keyframe seeking); the frame ring is
  the mitigation and its window/resolution are config, not constants.
- Demucs on video containers is unverified; the audio-extract fallback is
  specified.
- A/V offset: the deck playhead is the PortAudio output cursor at block
  granularity (~10–20 ms), acceptable; measure once with a clapper video.
- GPU: two 960-wide texture uploads per frame plus the visualizer; measure
  with the existing frame profiler before deciding decision 3 needs
  revisiting.

## Acceptance

Drop a music video on deck A while deck B plays audio: waveform and BPM
appear; crossfade A→B and back: the video fades in and out with the fader,
never with a fixed timer; scratch, cue-jump and loop on A: the picture
follows within a frame or two; remove any one of the three drop-ins: the
app starts and the deck plays the video's audio as a normal track.
