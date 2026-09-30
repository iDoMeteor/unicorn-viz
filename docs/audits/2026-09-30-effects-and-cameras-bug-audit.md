# Effects and cameras bug audit (2026-09-30)

Owner: DJ Unicorn Tears
Status: complete — all findings open; nothing fixed in this pass
Last updated: 2026-09-30

Fifth report of the 2026-09-30 series, after
[2026-09-30-bug-audit.md](2026-09-30-bug-audit.md),
[2026-09-30-auto-vj-director-recommender-audit.md](2026-09-30-auto-vj-director-recommender-audit.md),
[2026-09-30-windows-bug-audit.md](2026-09-30-windows-bug-audit.md) and
[2026-09-30-ui-files-bug-audit.md](2026-09-30-ui-files-bug-audit.md).

**Scope.** Every visual effect and its shaders, plus the camera overlay. Bugs
only; performance is deferred.

Effects covered (83 registered):
- core `unicornviz/effects/` — eight audio visualizers;
- all 13 `effects-*` packs;
- `sims-01`, `textures-01`, `unicorn-tears-01`.

The camera overlay is `drop-ins/webcam-01/webcam_overlay.py`.

Versions: master `226521c`, submodules:

| Drop-in | Commit |
|---|---|
| cosmic | `ba2eefd` |
| feature | `33aebf1` |
| flying | `e3978c4` |
| games | `c0e2688` |
| holiday | `d8a0834` |
| immersive | `225d3f8` |
| particles | `381b108` |
| psychedelic | `19f1c4d` |
| retro | `eb0e223` |
| rollercoast | `c27eaf0` |
| tech | `f3cbee2` |
| ukiyo-e | `62af223` |
| vector | `5dc9037` |
| sims | `f0ce04e` |
| textures | `80ea214` |
| unicorn-tears | `08df5d2` |
| webcam | `eee52af` |

The media players (images-01, videos-01, video-clips-01, projectm-01) went
through the harness only, not a full read.

**Method.**
1. **Offscreen harness over all 83 effects** (`fx_harness.py`). Each effect
   ran:
   - two instances;
   - 30 frames of silence, then 60 loud frames with bass above 1 and beats;
   - dt spikes of 2.5 s and 0;
   - resizes to 1280×720, 333×777 portrait, 1×1 and back;
   - destroy.

   Recorded: exceptions, GL errors, NaN/Inf pixels (float32 target),
   black/frozen output, frame-0 sameness, and GL objects still alive after
   `destroy()`.
2. **Mechanism tests** for each suspected class:
   - hash precision on this GPU;
   - frame-step jumps across speed changes;
   - audio wobble;
   - phase wraps;
   - crossfade GL state.
3. **Read every effect and webcam-01** for logic bugs.
4. **Game sims run headless** for minutes of simulated time (Frogger,
   Q*bert, Mario Kart).

GPU: Mesa Intel Iris Xe (EGL, GL 4.6). The scripts live in
`/var/tmp/uv-bug-audit/`.

Marked **VERIFIED** where reproduced.

**Harness result:** 0 exceptions, 0 GL errors, 0 NaN/Inf frames across all
83 effects, every resize and dt spike, and no GL objects leaked by
`destroy()`. The bugs below are logic and precision, not crashes.

## Summary

| ID | Sev | Where | Bug |
|---|---|---|---|
| E1 | P2 | `hotkeys.py:1797-1822`, `app.py:9335-9350` | Speed hotkeys, random speed, G reset and MIDI CC skip the phase-continuity rescale, so 34 effects hard-cut instead of changing speed. **VERIFIED** |
| E2 | P2 | 14 effects' hash call sites | Float32 hash collapse: sparkles, stars and glyph rain freeze into lattices or never fire. The 2026-08-03 "mod before hash" fixes bound too loosely. **VERIFIED** mechanism |
| E3 | P2 | ~24 shader lines in 14 files | "Class A" is still open: `iTime × audio level` scrambles the animation every frame under music. **VERIFIED** |
| E4 | P2 | 20 effects | Wrapped phases pop: CPU phases wrapped at 100/400/1000 and shader `mod(iTime, N)` jump the picture (up to 99×) once per wrap. **VERIFIED** |
| E5 | P2 | `webcam_overlay.py:1231`, `1527` | Showing the camera, REDISC and camera enable/disable probe every video device on the render thread: 242 ms freeze measured here, seconds on Windows. **VERIFIED** |
| E6 | P2 | `frogger.py:721` | 22% of Frogger runs simulate more logs than the shader draws: the frog rides invisible logs. **VERIFIED** |
| E7 | P3 | `webcam_overlay.py:2228-2230` | Switching the camera and then hiding it within 1.2 s un-hides it and airs the gradient test card. **VERIFIED** |
| E8 | P3 | `webcam_overlay.py:664`, `2294` | Horizontal flip is inverted: the worker already mirrors every frame, so "FLIP H" on means not mirrored |
| E9 | P3 | `webcam_overlay.py:620-638`, `2287-2292` | A camera that fails to open or dies shows the test card, or freezes on its last frame, with no status |
| E10 | P3 | `webcam_overlay.py:2322-2337` | The PiP is sized from the configured capture size, not the real frame; large PiPs squash; fullscreen stretches |
| E11 | P3 | 7 effects | Fixed or missing aspect handling: stretched hexagons, elliptical balls and saucers, oval Breakout ball, unused `cover_uv`, double aspect |
| E12 | P3 | `neon_pac.py:835` | Power-pellet ghost reversal teleports ghosts up to 2 cells and walks them through walls |
| E13 | P3 | `mario_kart.py:432` | Rivals drift away with no rubber-banding: the race empties within 1–2 minutes. **VERIFIED** |
| E14 | P3 | `frogger.py:493` vs `648` | Turtle-dive prediction uses `pace`, the simulation doesn't: the frog hops onto diving turtles |
| E15 | P3 | `particle_storm.py:301-310` | The beat relocation of the emitters is overwritten on the next frame, so it's invisible |
| E16 | P3 | `fireworks.py:529-559` | Fireworks ignores the Candy Frame viewport and scissor |
| E17 | P3 | `audio_spectrum.py:419-426` | Peak caps are packed in the wrong vertex layout: wrong colours and intensity |
| E18 | P3 | `audio_chromogram.py:486-488`, `215` | Chroma strip: LINEAR + REPEAT bleeds pitch lanes into each other and wraps B→C and newest→oldest |
| E19 | P3 | `sun_ship_3000.py:186` | The `seed` parameter and the docstring's rolled formations don't exist: dead MIDI parameter |
| E20 | P3 | `ansi_viewer.py:143`, `159`/`176` | Load failure leaks a texture; shuffles with the global `random` against the RNG rule |

## P2

### E1 — Speed changes hard-cut 34 effects (VERIFIED)

**Where.**
- `vj_api.set_speed` (`vj_api.py:1970-2011`) keeps shader phase continuous.
  It rescales `effect.time` so `t = iTime * (bias + scale * iSpeed)` doesn't
  jump.
- Every other speed path writes `effect.parameters['speed']` directly and
  skips that:
  - the `=` / `-` / `Ctrl+=` / `Ctrl+-` hotkeys (`hotkeys.py:1797-1822`);
  - random speed (`App._apply_random_speed`, `app.py:9335`, used by F6,
    Alt+= and on scene change while armed);
  - G reset (`App._reset_speed`, `app.py:9344`);
  - MIDI CC parameter mapping (`hotkeys.py:463`).

**Failure.**
- `self.time` starts anywhere in 0–10,000 s and keeps growing.
- A 25% speed bump at t = 6,000 moves `iTime * iSpeed` by 1,500 s in one
  frame.
- The effect cuts to an unrelated moment instead of speeding up.
- A MIDI knob sweeping speed scrubs chaotically.
- 34 effect files compute `iTime * iSpeed`-style time in the shader (list in
  `speed_mult.txt`).

**Repro.** `speed_jump.py`, Plasma at t = 6,000:

| Case | Frame step |
|---|---|
| Steady | 1.24 |
| After the `=` hotkey | 73.5 (a hard cut) |
| Same change through `set_speed` | 1.58 |

**Fix.** Route every speed write through one helper with the continuity
rescale (`VJApi.set_speed`, or a shared `App` method).

### E2 — Float32 hash collapse (VERIFIED mechanism)

**Mechanism** (`hash_collapse.py`, `hash_threshold*.py`). These count
distinct hash values over a 256×256 cell grid at growing input magnitudes:

| Hash form | 0 | 200 | 400 | 800 | 3,000 | 20,000 | 80,000 |
|---|---|---|---|---|---|---|---|
| `fract(sin(dot(p, (127.1, 311.7))) * 43758.5)` | 4,115 | 937 | 66 | 56 | 26 | 4 | 2 |
| `fract(p * (127.1, 311.7))` family, no `mod` | 1,510 | 346 | 282 | 251 | 100 | 7 | 1 |
| `hash21` (123.34, 456.21), no `mod` | 10,168 | 5,508 | 3,633 | 1,515 | 230 | 4 | 1 |
| `hash21` with `p = mod(p, 512.0)` first | 10,168 | 5,508 | 10,181 | 5,415 | 10,651 | 8,575 | 6,054 |

A "sparkle if hash > 0.996" gate passes 0.35% of cells at input 0 and **0%**
at 80,000.

The flying, games, ukiyo-e and rollercoaster packs already put
`mod(p, 512.0)` inside `hash21`. That's the proven fix.

The exact degradation is driver-dependent, but these inputs are beyond
float32's reliable range everywhere.

**Dead** (time-fed, unbounded or huge; the feature never fires or is
frozen):
- `audio_spectrogram.py:96` — sparks, `floor(iTime*8)`;
- `audio_spectrum.py:51` — bar sparks, `floor(iTime*4)`;
- `audio_spectrum.py:242` — DNA-rain glyph pick, `floor(iTime*1.6..5.6)`,
  so the glyphs stop changing;
- `audio_tracks.py:101` — `floor(iTime*10)`;
- `audio_waveforms.py:103` — `floor(iTime*8)`;
- `hacker_terminal.py:85` — `hash(uv + t*…)`;
- `wavey_gravy.py:70` — fbm terrain fed `t*0.5`, so the terrain goes
  blocky;
- `dali.py:90` — background noise fed `t*0.12`.

**Degraded** (the 2026-08-03 "mod before the hash" fixes wrap time to
128–2048 s, then multiply by 2–170):
- `cosmos.py:86` — stars ×120, about 15k; the fbm nebula at `mod(t, 1024)`
  times its octaves;
- `van_gogh.py:122-123` — stars/streaks ×120/×170;
- `america_250.py:138`, `153` — about 6–9k;
- `reactor_breach.py:147` — about 4.5k;
- `threat_matrix.py:100` — glyph seed, about 7k;
- `hacker_terminal_v2.py:131`, `161` — about 4k into the weak hash;
- `hexy_stars.py:104` — a star grid of about 300 cells into the sin-hash,
  even with no time term.

**Fix.** Put `p = mod(p, 512.0)` as the first line of every hash (and
`mod(n, 512.0)` for 1-D hashes), and drop the per-call-site time wraps.

### E3 — Class A (`iTime × audio level`) is still open (VERIFIED)

**What it is.** The 2026-08-03 audit's systemic item. When a shader computes
`t * (k + iBass)` with t in the thousands, a 0.01 change in the audio level
moves the phase by tens of seconds, so the animation re-randomizes every
frame.

bass_hammer, vector_hallway, sun_ship and tunnel were fixed with
CPU-integrated phases. These sites were not:
- `audio_spectrum.py:139` (nebula);
- `audio_sine.py:58`, `72`;
- `audio_waveforms.py:53`, `102`;
- `audio_tracks.py:105`;
- `audio_spectrogram.py:85`;
- `metaballs.py:68`, `72`;
- `rainbow_trance.py:119`, `152`, `153`. Line 119 multiplies all of the
  effect's time by smoothed energy, so it is scrambled constantly;
- `starfield.py:177`, `181`;
- `breakout.py:101`, `102`, `117`;
- `laser_tunnel.py:132`, `142`;
- `missile_command.py:105`;
- `cyber_war.py:102-105`;
- `hacker_terminal.py:80`;
- `webcam_overlay.py:346` (posterize edge hue);
- CPU-side: `vector.py`'s racer position,
  `(time * (… + bass*0.40)) % 1`.

**Repro.** `classA_jitter.py` at t = 6,000 with audio wobbling ±0.1 (normal
music): Audio Spectrum and Cyber War change 2.3× more per frame than with
steady audio.

**Fix.** Integrate each audio-modulated rate on the CPU (the bass_hammer
pattern) and pass the phase in.

### E4 — Wrapped phases pop (VERIFIED)

**What happens.** To keep float32 happy, CPU phases are wrapped with `% 100`,
`% 400` or `% 1000`, and shaders wrap time with `mod(iTime, N)`. But the
shaders then use those values non-periodically: hashed cells at
`iTravel * 2.6`, noise offsets at `iDrift * 0.35`, `mod(depth, 3.2)`, and
time-driven motion. So the frame where the value wraps jumps.

**Measured** as the frame step across the wrap ÷ an ordinary step, using
`wrap_pop.py`, `wrap_pop_b.py` and `time_wrap_pop.py`:

| Effect | Phase | Pop | Wraps about every (speed 1, mid bass) |
|---|---|---|---|
| Space Dance | `_depth % 1000` | 99× | 77 min |
| Nebula Drift | `_drift % 100` | 77× | 2 min |
| Nebula Drift | `mod(iTime, 600)` | 39× | 10 min |
| Warp Drive | `_warp % 100` / `mod(iTime, 600)` | 13× / 3.5× | 70 s / 10 min |
| Wingsuit Dive | `mod(iTime, 600)` / `_travel % 100` | 10× / 1.7× | 10 min / 31 s |
| Bass Hammer | `_flight % 1000` | 9.3× | 18 min |
| Floating World | `_wind % 100` | 8.5× | ~100 s |
| Raijin's Drums, First Drop | `mod(iTime, 600 / 300)` | 4.4× | 10 / 5 min |
| Disco Ball | `_spin % 1000` / `_cam % 1000` | 3.7× / 2.7× | — |
| Onden Watermill | `_current % 100` | 3.6× | ~74 s |
| Canyon Run, Asteroid Run | `_travel % 100` | 3.4× / 3.0× | ~40 s |
| Corkscrew, Log Flume, Audio Bass Machine, Coaster Cam | `mod(iTime, 300 / 120)` | 2.1–3.1× | 5 min / 2 min |
| Cloud Surfer | `_run % 400` | 2.8× | ~62 s |
| Night Parade, Night Coaster, Mine Train, Portal Flight | various | 1.8–1.9× | — |

These wrap cleanly and are fine: Space Tunnel and Vector Hallway (integer
periods), the coaster track position (periodic circuit), and Night Parade's
`iMarch`.

**Fix.** Wrap each *derived* value at its consumer's period on the CPU, for
example `mod(travel * 2.6, 512)` per use. Or choose wrap values that every
coefficient maps to a whole hash/noise period. Or pass the phase as a
(whole, fraction) pair.

### E5 — Camera probe freezes the show (VERIFIED)

**Where.** `_ensure_worker` (`webcam_overlay.py:1231`) → `rediscover_cameras`
→ `_enumerate_cameras` (`1465-1487`). It runs synchronously from:
- `set_layout` (Ctrl+KP 1–9 / 0 when first showing the camera);
- the Control Room REDISC button (`2071`);
- `start()`.

**Failure.**
- The probe opens every `/dev/video*` node through OpenCV. On Windows it
  opens indices 0–7 through MSMF.
- Measured here: **242 ms** for 7 nodes / 3 cameras, a quarter-second freeze
  on the audience output.
- MSMF failed opens typically cost 0.3–1 s each, so Windows can freeze for
  seconds.
- OpenCV also prints a WARN line to stderr for every non-capture node.

**Fix.** Probe on a worker thread. Better: list capture nodes from
sysfs/udev (`_scan_camera_identities` already reads them) instead of opening
devices.

### E6 — Frogger rides invisible logs (VERIFIED)

**Where.** Rows 7–11 each roll 3–4 logs (up to 20). `render()` uploads
`self._logs[:_NLOG]` with `_NLOG = 18` (`frogger.py:721`).

**Failure.** The extra logs, in the top river row, are simulated and
landable but never drawn. The frog appears to stand on water.

**Repro.** 44 of 200 activations (22%) have more than 18 logs.

**Fix.** Set `_NLOG = 20`, in the shader array too, or cap `n` per row.

## P3

- **E7 — the switch blink overrides a deliberate hide (VERIFIED,
  `webcam_switch_hide.py`).**
  - `next_camera` / `prev_camera` set `_hidden` and `_switch_hide_active`
    for 1.2 s.
  - `set_layout('hide')` inside that window stops the worker but leaves
    `_switch_hide_active` set.
  - At the deadline `render()` (`2228-2230`) sets `_hidden = False`, and
    with no worker `_get_camera_texture` returns the 256×256 gradient test
    card. It airs until someone hides again.
  - Fix: clear `_switch_hide_active` in `set_layout`.
- **E8 — flip semantics inverted.**
  - `_CameraWorker.run` mirrors every frame (`cv2.flip(frame, 1)`, `664`).
  - `_get_camera_texture` mirrors again when `_flip_horizontal` is set
    (default **True**, `2294-2297`).
  - So the default output is *not* mirrored, and the "FLIP H" chip lit
    (tooltip "Mirror the webcam image horizontally") means un-mirrored.
- **E9 — a dead camera stays on air.**
  - The worker exits for good after an initial open failure, or after 5
    failed reconnects (`620-638`).
  - `render()` keeps drawing: the gradient test card if no frame ever
    arrived, or the last frame frozen indefinitely. Neither is surfaced.
  - A camera held by another app (OBS) at show time puts the test card on
    the audience output.
- **E10 — PiP aspect** (`_rect_from_layout`, `2322-2337`).
  - Height comes from the *configured* capture size. A camera that delivers
    4:3 under a 1280×720 setting is stretched.
  - `h` is clamped to 70% of the window without shrinking `w`, so at
    pip_scale 0.8 on 16:9 the image squashes about 12%.
  - The fullscreen layout stretches the camera to the window.
- **E11 — aspect bugs in effects.**
  - Hexy Stars has no aspect term at all, so its hexagons are stretched
    1.78× on every 16:9 display (`hexy_stars.py:66`).
  - Metaballs hardcodes `vec2(1.777, 1.0)` (`metaballs.py:22`).
  - Alien Invasion has no `iResolution` and hard-codes a 1.6 aspect
    (`alien_invasion.py:129`). Saucers stretch 2× on the multi-head span
    canvases.
  - Breakout draws its ball in raw uv (`breakout.py:128`), so the ball is
    oval.
  - Texture Showcase defines `cover_uv` and never calls it
    (`texture_showcase.py:80`), so every texture is stretched to the window.
  - Unicorn Tears applies the aspect to its background twice
    (`unicorn_tears.py:163`).
- **E12 — Neon Pac ghost reversal** (`neon_pac.py:835`).
  - On a power pellet, direction is flipped while `prog` is mid-segment.
  - The drawn position `col + dcol*prog` jumps by `2*prog` cells.
  - The ghost then walks into `col - dcol` without a passability check,
    clipping through walls.
  - Fix: `col += dcol; prog = 1 - prog` before reversing.
- **E13 — Mario Kart empties (VERIFIED).**
  - Rival pace is 0.90–1.06 of the player's, with no rubber-banding, and
    rivals are drawn only within `_DRAW_ARC` ahead.
  - Rivals on screen every 15 s over 3 minutes, across four runs:
    `[6,5,3,3,3,3,3,3,3,2,0,1,1]`, `[6,6,2,2,1,1,1,1,0,0,0,0,0]` and
    similar.
  - Slower rivals return only after lapping, about 4 minutes.
- **E14 — Frogger turtle prediction.**
  - The simulation advances `dive` by `drate * dt` (`648`).
  - The safety check predicts it with `drate * pace * when` (`493`).
  - Pace runs 0.72–1.7 with the bass, so the frog's "safe to land" answer
    is wrong on turtle rows.
- **E15 — Particle Storm beat relocation** (`particle_storm.py:301-310`).
  - The beat randomizes the three emitters.
  - The very next frame (`audio.beat <= 0.5`) reassigns them to the drift
    path.
  - The relocation lasts ~16 ms.
- **E16 — Fireworks vs Candy Frame** (`fireworks.py:529-559`).
  - It saves `ctx.fbo` but not the viewport, then forces
    `viewport = (0, 0, w, h)` on the caller's FBO.
  - Inside Candy Frame it draws full-target.
  - The app's scissor (`app.py:8189-8211`) also clips its private
    accumulation passes, so trails outside the rect never clear.
- **E17 — Audio Spectrum peak caps** (`audio_spectrum.py:419-426`). The caps
  are packed `(x, y, r, g, b, 0.6)` into a `2f 1f 3f` (pos, mag, col)
  buffer, so `mag = 1 - r` and colour = `(1 - g, 1 - b, 0.6)`.
- **E18 — Audio Chromogram strip** (`audio_chromogram.py:486-488`).
  - The 12-row texture uses LINEAR filtering and default REPEAT.
  - Each pitch lane's energy and octave (G) blend with its neighbours', so
    blobs sit at a blended octave near lane edges.
  - The newest column blends with the oldest at the edges.
  - The drip lookup (`215`) wraps B's lane to C's row.
- **E19 — Sun Ship 3000.**
  - The docstring promises `iSeed`-rolled formations and wave patterns. The
    shader has neither.
  - The `seed` parameter (`186`) is never uploaded: it's a dead MIDI
    parameter.
- **E20 — ANSI Viewer.**
  - A failed load replaces `_ansi_tex` with a fallback without releasing it
    (`159`, `176`).
  - It shuffles with the global `random` (`143`, against the RNG rule).
  - The optional file cycling parses files inside `update()` (blocking-I/O
    rule; off by default).

## Checked, not bugs

- **Harness:** every effect survives silence, loud audio, dt 0 / 2.5 s, 1×1
  and portrait resizes, and destroy, with no GL errors, NaNs or leaked
  objects.
- **Crossfade GL state:** A and B render back to back with no
  `_normalize_gl_render_state()` between them (`app.py:8418-8434`). Audio
  Sine, Spectrum, Waveforms and Particle Storm leave BLEND on. But no effect
  renders differently when handed that state (`dirty_state.py`), because
  every shader writes opaque alpha or sets its own state.
- The app caps dt at 0.1 s (`app.py:6719`), so the game sims only tunnel on
  hitches.
- Q*bert never gets stuck: 35–40 courses per 10 simulated minutes, worst
  58 s.
- Galaga, Donkey Kong, Super Mario, Marble Madness, Joust, Tetris and Missile
  Command sims were read. They're sound apart from the items above.
- The Image Showcase "leak" is its deliberate module-level texture cache. It
  does bend effect rule 7 ("never hold GL objects outside the instance").
- Sim Showcase rendered black only in the depth-less harness target. The
  app's scene FBOs have depth (`app.py:3254`).
- The effects-browser thumbnail FBO has no depth. Only 3D Cube differs, by
  0.77, which is negligible.
- Plasma's frame-to-frame flicker under wobbling audio is spatial-frequency
  reactivity by design, not a phase bug.
- The randomization rule holds. The only frame-0 look-alikes are audio
  visualizers in silence, plus effects that start empty (Fireworks).

## Suggested order

1. **E1.** One helper and five call sites; fixes every speed change on 34
   effects.
2. **E5.** Moving the probe off the render thread removes the show freeze
   on camera show/REDISC.
3. **E2.** Mechanical: one line per hash function. It restores the sparkle,
   star and glyph layers in 14 effects.
4. **E4.** Pick periods per consumer; the Nebula Drift, Space Dance, Warp
   Drive and Wingsuit Dive pops are the worst.
5. **E3.** The CPU-integrated phase pattern, applied to the remaining Class A
   sites.
6. **E6–E7**, then the rest.
