---
Owner: Effects / Media
Status: Planning — approved direction, not yet started
Last updated: 2026-07-06
---

# Video Drop-Ins — Video Clips (rename + spruce) + Video Player (new)

Two video drop-ins going forward:

| Drop-in | NAME | Class | What it is |
| --- | --- | --- | --- |
| `video-clips-01` (rename of `videos-01`) | **Video Clips** | `VideoClips` | Today's audio-*reactive* clip montage (cv2 frames, no clip audio) + a directory-aware spruce. |
| `videos-01` (new) | **Video Player** | `VideoPlayer` | Plays **whole videos with their own audio** (ffpyplayer), letterboxed, with an audio crossfade in/out. |

The current `videos-01` (`VideoShowcase`) is a cv2 frame-streamer: sequences
clips with a crossfade + 10 rotating "styles", cover-fit + Ken-Burns drift,
reacts to *system* audio (bass/mid/treble → zoom/palette/vignette). It decodes
**video frames only — no audio**. That is exactly "Video Clips".

---

## Part A — Video Clips (rename `videos-01` → `video-clips-01` + spruce)

### A1. Migration (Drop-In Source Policy)

1. New private repo `unicorn-viz-dropin-video-clips-01`; seed it with the current
   `videos-01` contents.
2. Rename inside it: `video_showcase.py` → `video_clips.py`; class
   `VideoShowcase` → `VideoClips`; `NAME 'Video Showcase'` → `'Video Clips'`;
   keep `TAGS = ['media', 'videos', 'slideshow']` (category-first invariant OK).
3. Swap submodules: deinit `videos-01`, add `video-clips-01` at
   `drop-ins/video-clips-01`. (The freed `videos-01` slot is reused by the new
   Video Player — see Part B.)
4. Update refs: `config.full.example.toml` (`[effects.VideoShowcase]` →
   `[effects.VideoClips]`), `docs/drop-ins.md`, `docs/effect-settings.md`,
   README catalog, `tests/test_effects_consolidation.py` (`ISOLATED_NAMES`),
   `docs/planning/vj-mood-tag-rollout.md`, and any `PING_PONG_FRIENDS` that name
   'Video Showcase'. `config.toml` is the owner's — add a commented section only.

### A2. Spruce — directory-aware, per-activation playback

On **each activation** (`_init`), using `self.rng` (per-instance, so runs differ):

1. Scan the videos dir (default `drop-ins/video-clips-01/videos/`, or
   `[effects.VideoClips].video_dir` override).
2. Build **groups**:
   - every immediate **subdirectory** that contains ≥1 video → one group (its
     videos);
   - every **loose video** sitting directly in `videos/` → its own single-item
     group (so loose files aren't excluded from the draw).
3. **Randomly pick one group** for this run; only that group's videos play.
4. **Shuffle that group** with `self.rng`; play through without repeats, then
   reshuffle when exhausted.
5. **Shuffle the transition styles** with `self.rng` too (currently
   `random.shuffle`; switch to `self.rng` for per-instance distinctness per the
   Effect Randomization rules).

**Refactor note:** today `_VIDEO_PACK_CACHE` caches fully-built `_VideoClip`
objects (incl. GL textures) shared across instances. Split it: cache immutable
**probe metadata** (path/fps/size) globally; keep **group selection + shuffle +
playback state (cap/texture)** per instance so each activation is independent.

---

## Part B — Video Player (new `videos-01`)

### B1. Dependency — ffpyplayer (drop-in-local)

Add `ffpyplayer` to the drop-in's own `install.sh` + drop-in docs (NOT core
`requirements.txt` unless we later want it global). Import guarded with
`try/except`; if absent, the effect degrades gracefully (disabled, logged), per
Drop-In Independence rules. ffpyplayer handles A/V **sync + audio output**
internally and hands us video frames — least sync pain for v1.

### B2. Architecture

- `BaseEffect` `VideoPlayer`. A **decode thread** owns an
  `ffpyplayer.player.MediaPlayer` for the current video, pulls frames
  (`get_frame()` → `(frame, pts)`), and hands the latest frame to the main
  thread (single-slot, lock-guarded — never block render). Main thread uploads
  to a GL texture in `render()`.
- **Letterbox/contain** fit (config `fit = contain|cover`, default `contain` so
  whole videos aren't cropped).
- **`reached_bottom`** duck-typed property = "video finished" → the existing
  app auto-advance gate (used by the ANSI viewer) plays the **whole video before
  advancing** for free. Config `loop` to repeat instead.
- **Postfx / scroll-wheel work for free**: it's a normal effect drawing a
  fullscreen (letterboxed) quad into `fbo_a`, so the global post chain
  (postfx-01 / color-grade / beat-flash) and scroll-wheel hue/rotation apply on
  top automatically. (Requirement #6.)
- **Directory logic**: reuse the same group-shuffle as Video Clips (extract to a
  tiny shared helper or mirror it) so the Player also honours subdir selection.

### B3. Audio crossfade (Requirement: fade active-source → video audio over the
transition)

- Over the **effect transition duration**: ramp the video's volume **0→1 on
  enter** and **1→0 on exit** via `player.set_volume()`.
- **Duck the inverse** on whatever audio we actually control — i.e. the
  **audio-out-01** music bus if that drop-in is present (route/duck via its
  public surface). Sources we do **not** control (e.g. Spotify playing directly)
  can't be ducked from here; they play under until paused. Call this limit out
  in the drop-in docs.
- **audio-out-01 abstraction (Requirement #7):** optional. ffpyplayer's built-in
  audio is simplest for v1; if we want unified mixing/ducking we abstract the
  Player's audio through audio-out-01 later. **Validate early:** ffpyplayer uses
  SDL audio internally — confirm it coexists with the app's SDL2 without
  contention before committing.

### B4. Deferred to a follow-up update (per your call)

- **Beat-reactive effects + postfx *on the video itself*** (default on, with an
  option to disable each). This is what I meant by "video takes over
  reactivity": once the video's audio is crossfaded in and playing, the app's
  capture picks it up → drives the beat grid → a reactive pass warps/pulses the
  video to its own soundtrack. Cleaner as a v2 once base playback is solid.
- Transport controls (play/pause/seek/next) — "maybe later".

### B5. Risks to burn down first

1. **ffpyplayer + SDL audio** coexistence with the app's SDL2 — validate before
   building out.
2. **A/V sync under postfx load** — decode thread must never block the render
   path; drop frames rather than stall.
3. **`destroy()` hygiene** — stop audio + join the decode thread cleanly; no
   zombie audio when the effect switches away.

---

## Execution order

1. **Video Clips** migration + directory spruce (lower risk; frees the
   `videos-01` slot for the Player).
2. **Video Player v1**: playback + letterbox + audio crossfade + `reached_bottom`
   + postfx-over-top.
3. **Later:** beat-reactive video postfx; audio-out-01 routing; transport.

## Decisions to confirm before building

- **Loose-file grouping:** each loose video in `videos/` = its own single-item
  group (so a run may legitimately be one clip on loop). Correct?
- **ffpyplayer as a drop-in-local dep** (not core `requirements.txt`)?
- **Crossfade scope:** OK that we can only duck app-controlled audio
  (audio-out-01), not external sources like Spotify?
