---
Owner: Planning
Status: REV1 fully wired (M-1..M-4, scratch, cues, loops, FX, BPM/SYNC, lighting,
browser). Track metadata + mouse M-mouse 1 (draggable faders/EQ/filter/master)
done. Planning: performance pad modes (beat jump, trans, tracking=track-nav,
sampler, scratch bank) + beatgrid edit/lock. Pending: hardware bring-up, mouse
M-mouse 2-4, feature backlog.
Last updated: 2026-07-12
---

# DJ Mixer Drop-In Plan — `dj-mixer-01` (Pioneer DDJ-REV1)

A new drop-in that launches a dedicated **mixing-board window** (like the
Control Room) and turns a **Pioneer DDJ-REV1** controller into a real
**two-deck audio DJ mixer**.  The mixer plays and blends actual audio; the
existing capture/visualizer pipeline reacts to the mixer output automatically
(see §6).

This document is the authoritative scope + build order.  Update the
**Status** header and the milestone checkboxes as work lands.

---

## 0) Scope Decisions (locked with owner, 2026-07-07)

| Decision | Choice | Consequence |
|---|---|---|
| **Mix domain** | **Real audio DJ decks** | Two audio decks with their own playback engine; sound is mixed, not just visuals. |
| **MIDI direction (v1)** | **Input-first** | v1 reads the full REV1 surface. LED / VU / jog-ring feedback to the controller is **v2**. Keeps v1 off the core-MIDI-output owner-approval gate. |
| **v1 depth** | **Core DJ loop** | Load / play / cue / pause, tempo-pitch fader, channel fader + crossfader, 3-band EQ per channel, basic jog nudge. Scratch, hot-cue pads, loops, and beat-sync are **v2**. |
| **Audio engine origin** | **Dedicated**, patterned on `audio-out-01` | Not built on `media-01`/`videos-01` (subprocess players, no sample-level pitch/scratch/mix). Reuse `audio-out-01`'s real-time callback discipline + `dsp.FilterChain`. |

---

## 1) Why a New Drop-In (and what it reuses)

The winning move is to **compose two patterns already proven in this repo**,
not invent anything:

1. **Window + operator UI** — clone `control-room-01`'s approach exactly:
   its own `SDL_CreateWindow` + **`SDL_RENDERER_SOFTWARE`** streaming texture,
   a **throttled background render thread** drawing the UI with PIL, and
   `vj_api.claim_window_events(window_id, cb)` so mixer input never falls
   through to the main hotkey path.  Preview of the audience output is
   available via `vj_api.get_frame_bytes()` if we want it in a corner.
   Reference: [control_room.py](../../drop-ins/control-room-01/control_room.py#L282).

2. **Real-time audio engine** — clone `audio-out-01`'s thread discipline:
   a single `sounddevice.OutputStream` whose callback **only reads numpy state
   and drains a command `deque`** — never touches GL/SDL/app, never holds a
   lock across the real-time path.  Its `dsp.py` already gives us a
   `FilterChain` (HPF / LPF / 3-band EQ) and `Reverb` we can lift per channel.
   Reference: [audio_out_controller.py](../../drop-ins/audio-out-01/audio_out_controller.py#L1-L24).

The new part is the **two-deck DJ engine** (varispeed playback, per-channel
EQ/filter, crossfader mix) and the **REV1 MIDI decode**.

**Explicitly not reused for decks:** `media-01` (libvlc/mpv jukebox — single
stream, no pitch/scratch; its own crossfade TODO is unimplemented) and
`videos-01` (video, not a DJ deck).  They remain the right tools for
now-playing playback, just not for beatmixing.

---

## 2) Drop-In Layout

Per Drop-In Source Policy: its own **private GitHub repo**, wired as a
submodule at `drop-ins/dj-mixer-01`, loaded via `load_dropin_symbol()` with a
`try/except` null fallback.

```
drop-ins/dj-mixer-01/
  __init__.py
  dj_mixer_controller.py     # DjMixerController: window + subsystem coordinator
  deck.py                    # Deck: one varispeed audio deck (numpy)
  mixer_engine.py            # MixerEngine: OutputStream callback, sums decks → master
  rev1_map.py                # DDJ-REV1 MIDI decode table (data, see §5)
  rev1_input.py              # raw-MIDI listener → normalized deck/mixer commands
  ui.py                      # PIL software-rendered mixer UI (two decks + center)
  config_validator.py        # mirrors audio-out-01/color-grade-01 pattern
  install.sh
  requirements.txt           # sounddevice, soundfile (+ decode backend, see §4)
  README.md                  # overview + controls + config + troubleshooting
  docs/operations.md
  docs/configuration.md
  docs/integration.md
  docs/troubleshooting.md
  tests/
    test_deck.py             # varispeed cursor, EQ, gain math (pure numpy)
    test_mixer_engine.py     # crossfade curve, summing, clip guard
    test_rev1_map.py         # decode table: (ch, kind, num) → command
```

Structured docs are **required** (this is a complex controller drop-in) and
must be registered in [docs/drop-ins.md](../drop-ins.md).

---

## 3) Audio Engine Design (the core of v1)

### 3.1 `Deck` (deck.py)
One deck owns one loaded track as a numpy **float32 stereo** array plus a
fractional read cursor.

- **Load:** decode file → `np.ndarray[frames, 2]` at the engine samplerate
  (resample on load if the file rate differs). Decode off the audio thread.
- **Transport:** `play` / `pause` / `cue` (jump to cue point, or track start),
  `set_cue()`.
- **Varispeed / pitch:** cursor advances by `rate = base_rate * (1 + pitch)`
  where `pitch` comes from the tempo fader (±8% default range, configurable).
  Read with **linear interpolation** between samples (upgrade to a windowed
  resampler in v2 if artifacts show).
- **Jog nudge (v1):** jog rotation applies a short-lived pitch bend (temporary
  `rate` offset that decays). Absolute **scratch** (jog touch + position
  scrub) is v2.
- **Per-deck chain:** gain (channel fader) → 3-band EQ (`dsp.FilterChain`) →
  filter (HPF/LPF sweep knob) → deck output buffer.
- **Thread-safety:** the audio callback reads deck float targets (atomic under
  the GIL) and drains a per-deck command `deque`; the UI/MIDI threads only
  write targets + append commands. Same rule as `audio-out-01`.

### 3.2 `MixerEngine` (mixer_engine.py)
Owns the single `sounddevice.OutputStream`.

- Callback: pull `blocksize` frames from Deck A and Deck B, apply the
  **crossfader** curve (constant-power / equal-power by default so the mix
  doesn't dip in the middle), sum, apply **master gain**, soft-clip guard,
  write to output.
- Output device: default sink (config-overridable). On PipeWire this reaches
  speakers **and** the monitor source (OBS + the app's own capture) for free.
- Idle safety: writes silence when both decks are paused; never blocks.

### 3.3 Latency / budget
Audio runs on PortAudio's thread — **independent of the 16.67 ms render
budget**. Keep blocksize modest (256–512) for responsive jog/cue without
under-runs. The mixer UI window is throttled (~30 fps, like Control Room) so
it never starves the main GL loop.

---

## 4) Dependencies (confirm before coding — CLAUDE.md library policy)

- `sounddevice` — already in `requirements.txt`. ✅
- `soundfile` (libsndfile) — WAV/FLAC/OGG decode. Present via `audio-out-01`.
- **MP3/AAC/M4A decode is the open dependency question.** Options:
  - **PyAV** — already a dependency of `videos-01`; broad format coverage;
    consistent with the house A/V backend decision
    ([memory: video-player-av-backend]). **Recommended.**
  - `audioread` / `pydub` (+ system ffmpeg) — lighter but shells out.
- **Decision (owner, 2026-07-07): PyAV.** Decode MP3/AAC/M4A with PyAV to match
  the existing A/V backend and avoid a new dependency family. Pinned in the
  drop-in's own `requirements.txt`, not the core's.

All new deps live in `drop-ins/dj-mixer-01/requirements.txt`, not the core
`requirements.txt`, so core stays lean and independent.

---

## 5) DDJ-REV1 MIDI (input-first)

### 5.1 Getting the map — **do not guess CC/note numbers**
Pioneer publishes an official **"DDJ-REV1 MIDI Message List"** PDF. The build
starts by transcribing that table into `rev1_map.py` as data. Where the PDF is
ambiguous, confirm live using the existing **raw-listener** capture (below) as
a MIDI monitor. No fabricated control numbers go into the repo.

> **Resolved (2026-07-07):** the official Pioneer "DDJ-REV1 List of MIDI
> message" (5-page PDF) was sourced via the Wayback Machine and the v1
> core-loop subset is transcribed in **Appendix A**. Live raw-listener capture
> is still the confirmation step during M-2.

### 5.2 Wiring (uses existing public surface — no core change)
- The mixer registers a raw listener:
  `vj_api.midi_add_raw_listener('dj_mixer', self._on_midi)` — exactly how
  `midi-controllers-01` consumes MIDI ([midi_manager.py](../../drop-ins/midi-controllers-01/midi_manager.py#L871)).
- `rev1_input.py` decodes `(channel, note/cc, value)` → a normalized command
  (`deck`, `control`, `value`) and appends it to the engine command deque.
  The callback fires on the rtmidi thread → **enqueue only**, never touch the
  engine's numpy state directly.
- REV1 uses per-deck MIDI channels plus a global channel; the decode table is
  keyed on `(channel, kind, number)`.

### 5.3 v1 control surface → deck/mixer mapping (core DJ loop)
Jog wheel (nudge), Play/Cue, tempo fader, channel fader, crossfader, and the
TRIM/HI/MID/LOW EQ knobs per deck, plus browse-encoder + LOAD to load the
selected track into a deck. Performance pads, FX paddles, and scratch are
parked for v2.

### 5.4 Policy gate (coordination with `midi-controllers-01`)
- The REV1 **decode table** maps to *mixer* functions, not visualizer actions,
  so it lives **in this drop-in**, not in the visualizer preset list.
- **BUT** two things touch the MIDI-policy boundary and need owner sign-off
  before code, per [memory: MIDI Drop-in Policy]:
  1. **Confirming the core `MidiManager` opens the REV1 input port** (config
     key or auto-bind). If it doesn't already open non-preset devices, that
     port-binding rule belongs in `midi-controllers-01` = owner approval.
  2. **v2 LED/VU/jog-ring feedback** needs a MIDI **output** port capability in
     core `MidiManager` = owner approval (deferred with v2).

---

## 6) Integration with the Rest of the App

- **Visuals react to the mix (free on PipeWire):** if the mixer outputs to the
  default sink and the app's audio source is the system **monitor**, capture
  picks up the mixed output with no wiring — the same mechanism documented for
  audio injection in the 2026-06-19 audit §11. Note in `docs/integration.md`
  that the operator should select the monitor source (or a dedicated null
  sink) when they want visuals bound to the decks rather than to line-in.
- **Now-playing HUD:** optionally expose a `snapshot()` matching
  `SpotifyController`/`media-01` so the existing HUD band shows the *active
  deck's* track with zero HUD changes.
- **Auto VJ (v2):** `auto-vj-01` already locks BPM; a v2 sync feature can pull
  that for beatmatch, and the crossfader can emit a VJ "blend" signal. Out of
  v1 scope.
- **Core independence:** if core needs to know about the mixer at all, add an
  `_load_dj_mixer_controller_class()` loader in `app.py` following the existing
  `try/except` → null-fallback pattern; prefer adding any needed capability to
  `VJApi` over reaching into `app._private`.

---

## 7) Milestones

- [x] **M-0 — Prereqs / approvals (mostly done, 2026-07-07).**
  - [x] Official DDJ-REV1 MIDI Message List sourced (via Wayback; extracted
    core-loop subset in **Appendix A**).
  - [x] MP3/AAC decode dependency approved: **PyAV** (owner OK).
  - [x] Private repo `unicorn-viz-dropin-dj-mixer-01` created + pushed; wired as
    submodule `drop-ins/dj-mixer-01` (scaffold: window/engine/deck interfaces,
    equal-power crossfader curve, config validator, structured docs, 3 smoke
    tests green). No MIDI code — see §5.4 / point-3.
  - [x] Core multi-device MIDI landed (2026-07-07, commit `42a5a83`): the core
    `MidiManager` now opens concurrent **raw-only aux input devices**
    (`vj_api.midi_add_input_device(hint)`) whose events are source-tagged and
    reach named listeners only — so the REV1 coexists with a VJ-side APC. This
    was a **core `unicornviz/midi.py`** change (not a `midi-controllers-01`
    change), owner-approved. **M-2 is now unblocked.**
- [x] **M-1 — Audio engine, headless (done 2026-07-07).** `Deck` + `MixerEngine`
  with load (soundfile→PyAV) / play / cue / pitch (varispeed) / channel fader /
  crossfader (equal-power) / 3-band DJ EQ (RBJ biquads) / jog nudge / master
  soft-clip. Pure `render_block` mix path; `sounddevice` stream + safe callback.
  18 tests green (`dsp`/`deck`/`mixer_engine`). No window, no MIDI yet.
- [x] **M-2 — REV1 input (done 2026-07-07, drop-in `6cab9c5`).** `rev1_map.py`
  (Appendix A) + `rev1_input.py`: the controller calls
  `vj_api.midi_add_input_device('rev1')` and registers a raw listener that
  decodes only its own `event.source` traffic — 14-bit fader/EQ reassembly,
  bipolar tempo→pitch + EQ, channel fader→gain, crossfader/master, jog nudge,
  play/cue. 29 tests green; verified end-to-end against the real core
  `MidiManager` (REV1 drives the engine, APC is ignored). **Remaining: confirm
  polarity/scaling on real hardware.**
- [x] **M-3 — Mixer window (done 2026-07-07, drop-in `c6acd93`).** `ui.py`:
  own borderless SDL window (software renderer + streaming texture + throttled
  PIL render thread + deferred teardown, Control Room pattern). Renders both
  decks (waveform + playhead, track, time, pitch %, play/cue, 3-band EQ knobs,
  channel gain, VU) + center master + crossfader. `Shift+D` toggles; `Esc`
  closes; left-click toggles a deck. 32 tests green; frame verified headlessly.
- [x] **M-4 — Integration + docs (done 2026-07-07, main `a6e3a5a`).**
  `_load_dj_mixer_controller_class()` + guarded load site in `app.py` registers
  the `dj_mixer` subsystem and `Shift+D` handler; defaults = loaded-but-idle
  (REV1 wired, window + audio stream closed until opened). `[dj_mixer]` skeleton
  added to `config.full.example.toml` (config.toml left to the owner); drop-in
  registered in `docs/drop-ins.md`; `HELP_ENTRIES` present. Remaining M-4
  polish: HUD `snapshot()` for now-playing, monitor-source guidance in docs.
- [x] **Color filter (done 2026-07-08, drop-in `a4d46f8`).** `dsp.SweepFilter`
  bipolar one-knob LPF/HPF (center = bypass, RBJ biquads, geometric cutoff
  sweep) applied per deck after EQ; REV1 EFFECT FILTER knobs (ch7 CC 23/24,
  14-bit) decoded to `deck.filter`. 52 tests green. UI filter-bar indicator was
  written but lost to a concurrent `ui.py` edit (the GL-rebind workstream) —
  re-add once that settles; purely cosmetic, the audio path is complete.
- [x] **Jog scratch (done 2026-07-08, drop-in `ddc2295`).** Platter touch
  (Note 54) enters scratch; vinyl rotation (CC 34/35, relative) scrubs the
  playhead forward/reverse via `deck.scratch_touch`/`scratch_move`; a held
  platter is silent (stopped record); release restores play state.
  `scratch_scale` tunes samples/tick. 58 tests green.
- [x] **Hot-cue pads (done 2026-07-08, drop-in `dbd5cf7`).** 8 hot-cue slots per
  deck: press a HOT-CUE-mode pad to set (if empty) or jump+play (if set),
  SHIFT+pad deletes; cues cleared on load. Decoded on pad channels 7/8 (deck A
  normal/shift) and 9/10 (deck B). Pad LEDs show set cues (falling back to the
  VU show when none are set). 64 tests green.
- [x] **Loop / roll pads (done 2026-07-08, drop-in `ce69b5a`).** Deck `bpm` +
  loop engine (modulo-wrapped read/cursor). AUTO LOOP pads (notes 16-23) toggle
  a beat-length loop (1/16..8 beats); ROLL pads (notes 80-87) are momentary.
- [x] **FX units + paddles (done 2026-07-08, drop-in `9b7e348`).** Master
  `BeatEcho` (feedback delay) engaged by the FX1 paddle (Note 80, ch4, momentary)
  with the LEVEL/DEPTH knob (CC 2/4/6) as echo depth; `set_bpm` drives the echo
  time. 77 tests green. FX2 + more effect types are v2.
- [x] **Beat-sync Phase A — tempo-locked FX/loops (done 2026-07-08, drop-in
  `9fa40a4`).** The mixer owns its own **offline per-track BPM** (`bpm.py`,
  autocorrelation + octave/prior logic adapted from auto-vj but *not* dependent
  on it); `deck.detect_bpm()` on load drives beat-correct loop lengths and the
  master echo (`engine.follow_active_deck`). 89 tests green.
- [x] **Beat-sync Phase B — SYNC / beatmatch (done 2026-07-08, drop-in
  `9d7d7ad`).** `deck.sync_to` (octave-folded pitch match) + `engine.sync_deck`;
  the REV1 SYNC button (Note 88) beatmatches a deck to the other. The mixer owns
  its own BPM code — no dependency on auto-vj (users may install either alone).
- [x] **Smart BPM interop (done 2026-07-08).** A shared **BPM hint bus** on
  `vj_api` (`publish_bpm`/`get_bpm`, TTL'd, core `App`): the mixer publishes its
  active-deck tempo and borrows an external hint when idle; `auto-vj` publishes
  its room estimate (publish-only, no ADR impact). Neither depends on the other;
  if both are present they sharpen each other. Core bus tested in
  `tests/test_bpm_bus.py`.

### Lighting (bidirectional MIDI — REV1 LED feedback)

Turns out this needs **no** core MIDI-out change: the mixer owns its own
cross-platform `rtmidi.MidiOut` to the REV1 (the same ownership pattern
`apc_leds` uses), so it works on Windows/Linux/macOS. The Linux-only ALSA
`rawmidi` workaround for the broken kernel `snd_ump` output path is avoided
(and the owner's kernel update should resolve that anyway).

- [x] **Lighting Phase 1 — transport lights (done 2026-07-08).** `rev1_leds.py`
  `Rev1Leds`: lights each deck's PLAY / CUE button (Note 11/12 on the deck
  channel, velocity 0x7F/0x00 per the "MIDI-OUT ← Same as MIDI-IN" spec),
  diffed so the device is never flooded. Opened/closed with the mixer window
  (LEDs off on close), config-gated (`[dj_mixer].led_feedback`, default true).
  6 tests via an injected sender. **Hardware validation pending** (polarity is
  trivial; confirm the REV1 accepts the note-on LED convention).
- [x] **Lighting Phase 2 — performance-pad light show (done 2026-07-08).**
  `rev1_leds.py` drives the 8 performance pads per deck as an audio-reactive
  **VU meter** off each deck's output level (pad channels 0x97/0x99, HOT-CUE-mode
  notes 0–7, on/off velocity, fast-attack/slow-decay smoothing, diffed).
  Config-gated (`[dj_mixer].pad_lightshow`, default true). 9 LED tests total.
  **Scope note:** Pioneer's message list exposes LEDs on **buttons + pads**
  only — there are no dedicated VU-meter or jog-ring LEDs on the REV1, so "VU"
  is realized on the pads. Exact pad **color** is set by the hardware's active
  pad mode; we drive on/off (safe regardless of RGB palette). **Hardware
  validation pending** (confirm pads light without a host-mode handshake).

---

## 8) Risks & Open Questions

| Risk | Mitigation |
|---|---|
| REV1 MIDI map unknown / undocumented online | Start from official Pioneer PDF; fall back to raw-listener capture. **M-0 blocker.** |
| MP3 decode dependency creep | Prefer PyAV (already in-tree via videos-01); owner confirms before pinning. |
| Audio under-runs from too-small blocksize during jog | Tune blocksize; keep decode + resample off the audio thread. |
| Second SDL window starving GL loop (the Control Room bug class) | Copy Control Room's throttled render-thread + software-renderer fix verbatim. |
| Core doesn't open the REV1 input port | Confirm early in M-0; port-binding change routes through `midi-controllers-01` + owner approval. |
| Linux operator-window support | Control Room notes Linux operator windows are still maturing; validate the mixer window on the F44 primary early in M-3. |

---

## 9) Definition of Done (v1)

- Two audio tracks load into decks A/B and mix through the crossfader with
  per-channel 3-band EQ, tempo-pitch, and jog nudge — **driven entirely by the
  DDJ-REV1**.
- The mixer window renders the deck/mixer state and is mouse-operable.
- The audience visualizer reacts to the mixed audio via the monitor source.
- All new code lives in the `dj-mixer-01` submodule; core loads it via
  `try/except` and runs normally when it is absent.
- Structured docs present and registered; unit tests green in the drop-in repo.

---

## 10) Where the MIDI Lives — Decision (point 3)

**Question:** keep the mixer in its own drop-in and add the REV1 MIDI support
to `midi-controllers-01`?

**Recommendation: split by layer, not by device — a hybrid.**

- **`midi-controllers-01` owns the *transport* layer** (shared infrastructure):
  opening the REV1 input port, device identity / port-binding, and the raw
  event stream already exposed via `vj_api.midi_add_raw_listener`. This is the
  only part the project MIDI policy really requires to live there, and it is
  the part the **VJ MIDI team is already in** — so any REV1 port-binding rule
  should be their change, coordinated + owner-approved.
- **`dj-mixer-01` owns the *semantic* layer** (`rev1_map.py` + `rev1_input.py`):
  the REV1 → deck/mixer decode. It subscribes to the shared raw stream and
  translates `(channel, note/CC, value)` into deck commands.

**Why not put the whole REV1 mapping in `midi-controllers-01`:**

1. **Dependency direction.** That drop-in's presets map MIDI → *visualizer
   actions/params*. A DJ mapping targets *deck transport / audio mix* — a
   different domain. Housing it there would make the shared MIDI drop-in depend
   on (or hard-code knowledge of) a specific consumer (`dj-mixer-01`), which
   inverts the dependency. Keeping decode with its consumer preserves
   independence and testability.
2. **Concurrency.** The VJ team is live in `midi-controllers-01` right now.
   Keeping REV1 decode in `dj-mixer-01` lets the mixer move without merge
   contention on their WIP.
3. **Cohesion.** `rev1_map.py` is meaningless without the deck engine; it
   belongs next to it.

**The one thing that must be coordinated with the VJ team (blocking M-2):**
confirm the core `MidiManager` can open the REV1 input port **and fan out
multiple simultaneous devices** to multiple raw listeners — e.g. an APC driving
the VJ side *and* the REV1 driving the mixer, at the same time. If today's
transport only tracks a single active device, multi-device support is a
`midi-controllers-01` change (owner-approved) that both teams depend on. This
is the natural integration point between the two efforts.

> Net: **mixer stays its own drop-in; the REV1 *decode* stays with it; only the
> shared *transport* (port open + multi-device fan-out) is a `midi-controllers-01`
> change owned by the VJ team.**

---

## Appendix A — DDJ-REV1 MIDI reference (v1 core-loop subset)

Source: Pioneer DJ "DDJ-REV1 List of MIDI message" (5-page PDF), retrieved via
the Wayback Machine. Values are decimal unless noted. This is the subset the v1
core DJ loop needs; performance pads, FX slots, and per-mode pad banks are fully
documented in the source PDF and are parked for v2.

**Channel assignment** (status nibble): Deck 1 = ch 1 (`0x90`/`0xB0`), Deck 2 =
ch 2 (`0x91`/`0xB1`), Deck 3 = ch 3, Deck 4 = ch 4. Mixer master/browser section
(crossfader, master, headphones, filter, browse) = ch 7 (`0x96`/`0xB6`). FX1 =
ch 5, FX2 = ch 6. Pads = ch 8/10/12/14 (decks 1–4), +SHIFT ch 9/11/13/15.
`n` below = deck channel (1–4).

Continuous controls are **14-bit** (MSB CC + LSB CC); v1 can read the MSB alone
for coarse control and add the LSB for smoothness.

| Control | Deck/Ch | Type | Number (dec) | Notes |
|---|---|---|---|---|
| PLAY/PAUSE | n | Note | 11 | on=0x7F, off=0x00 |
| CUE | n | Note | 12 | |
| TEMPO fader | n | CC | 0 (MSB) / 32 (LSB) | −/+ end = min/max |
| CH FADER | n | CC | 19 (MSB) / 51 (LSB) | bottom→top = min→max |
| GAIN (TRIM) | n | CC | 4 (MSB) / 36 (LSB) | |
| EQ HI | n | CC | 7 (MSB) / 39 (LSB) | |
| EQ MID | n | CC | 11 (MSB) / 43 (LSB) | |
| EQ LOW | n | CC | 15 (MSB) / 47 (LSB) | |
| Headphone CUE | n | Note | 84 | |
| Jog — wheel side (nudge) | n | CC | 33 | relative: CW≈0x41+, CCW≈0x3F− |
| Jog — platter (scratch, v2) | n | CC | 34 vinyl-on / 35 vinyl-off | touch = Note 54 |
| SYNC | n | Note | 88 | |
| DECK SELECT 1/3 · 2/4 | n | Note | 60 (deck on/off) | switches which deck a side controls |
| CROSSFADER | 7 | CC | 31 (MSB) / 63 (LSB) | left→right = min→max |
| MASTER LEVEL | 7 | CC | 8 (MSB) / 40 (LSB) | |
| HEADPHONES LEVEL | 7 | CC | 13 (MSB) / 45 (LSB) | |
| MASTER CUE | 7 | Note | 99 | |
| SHIFT | 7 | Note | 63 | modifier; second layer on most controls |
| FILTER (per ch, color knob) | 7 | CC | 23=CH1, 24=CH2, 25=CH3, 26=CH4 (MSB) | +32 for LSB |
| Browse encoder | 7 | CC | 64 | relative, same CW/CCW scheme |
| Browse press / LOAD L / LOAD R | 7 | Note | 65 (press) · 70 (load L) · 71 (load R) | LOAD targets the selected deck |

All button Notes send `0x7F` on press and `0x00` on release. Jog/browse
encoders are **relative** (two's-complement-style around 0x40): clockwise counts
up from 0x41, counterclockwise down from 0x3F.

---

## Four-Deck + Waveforms + Auto-Play Plan (v-next)

Owner-directed 2026-07-13. Four sub-features; build **#1 → #2 → #3, then #4 as
its own isolated segment**. All four reshape the same window, so the layout is
locked once (below) and built against, not thrashed per-feature.

### Locked decisions

- **Sides & decks.** Two physical sides. **Left side = decks 1 & 3 (a/c)**,
  **right side = decks 2 & 4 (b/d)**. The REV1's **upper-corner DECK-SELECT
  buttons** (Appendix A: **Note 60** on the deck's channel) switch which deck a
  side controls; when a side selects deck 3/4, the hardware re-addresses that
  side's controls to channel 3/4 (0-indexed 2/3), which our channel dispatch
  already routes. All decks keep *playing* regardless of which one a side is
  *controlling*.
- **Hardware-addressed 3/4** (not software-only): decks 3 & 4 are first-class,
  driven by the REV1 exactly like 1 & 2, plus mouse on the window.
- **Crossfader = decks 1 ↔ 2 only.** Decks 3 & 4 run at full and are blended via
  their own channel faders. One crossfader, matching the REV1 hardware.
- **LOAD targets the selected deck** (Appendix A): LOAD-L → the left side's
  currently-selected deck (a or c), LOAD-R → the right side's (b or d).
- **Window layout: 2×2 decks + center console.** Decks 1&2 top, 3&4 bottom, with
  the browser / auto-play / master / crossfader as a center console band. Each
  deck shows the full-track wave **and** a zoomed ~10 s wave beneath it.
- **Control bar above the console** (moves with the console; will also host
  search / filter / etc.) carries **three intuitive state icons** for the
  auto-play mode.
- **Buttons:** every button gets a **hover state** now and carries a **tooltip
  string** so it's plug-ready for the **core team's forthcoming tooltip system**
  (we do not build that system here).

### #1 — Decks 3 & 4 (engine + hardware + UX)

- **#1a Engine/hardware foundation** *(testable, no UI)*: add `deck_c`/`deck_d`
  to `MixerEngine`; `render_block` = `xfade(a,b) + c + d`; extend
  `follow_active_deck` and `sync_deck` to 4 decks. `rev1_map`: `DECK_CHANNELS`
  += `{2:'c',3:'d'}`, `DECK_SELECT_NOTE = 60`, pads += channels 11–14 (+shift),
  `FILTER_CC14` += CH3 (25/57) & CH4 (26/58), LOAD notes resolve to the selected
  deck per side. `rev1_input`: track the selected deck per side from Note 60,
  route LOAD accordingly, apply filter c/d; deck controls for ch 2/3 already flow
  through `_deck()`. `rev1_leds`: PLAY/CUE + pads for all 4 decks (throttle +
  diff already guard MIDI-out).
- **#1b UX**: relayout `ui.py` to the 2×2 + center console; mouse controls
  (draggable faders/EQ/filter/gain) for all four decks; the console hosts the
  master, crossfader, browser and the auto-play control bar.

### #2 — Dual waveforms per deck

Each deck keeps the full-track overview wave and gains a **zoomed ~10 s wave**
beneath it (default window `wave_zoom_seconds = 10`, config), centered on the
playhead and scrolling with it — the close-up DJs beatmatch against. Reuses
`deck.waveform_peaks` with a position-windowed variant.

### #3 — Drag a track onto a deck to load

Press on a browser row → drag → release over any deck panel → load that track
into that deck (uses the existing hit-region/drag foundation; adds a browser-row
grab + deck drop-targets + a drag ghost/label).

### #4 — Auto-play (isolated segment, after #1–#3) — DONE 2026-07-13

Shipped in `autoplay.py` (`AutoPlay` sequencer) + control-bar buttons in `ui.py`
+ the `rev1_leds` warn hook, ticked from the controller each frame. Notes below
reflect what was built.

A panel above the track list with **three state buttons (active = highlighted):
`cut` | `crossfade` | `ai`** (start with cut + crossfade; **ai greyed/disabled**
for now). Clicking the **active** button turns auto-play **off** and returns full
control to the DJ. Buttons have hover states + tooltip strings.

- **Only decks 1 & 2** participate in auto-play, in every mode — so the DJ is
  free to work on the **non-playing side's alternate deck (3/4)**.
- Auto-play loads the next track into the **next non-playing** primary and, at
  the track's end, transitions to it (`cut` = hard switch on the crossfader;
  `crossfade` = timed blend). **Never auto-switch from the current playing deck
  to an already-playing one** when toggling the mode on.
- **Pre-transition warning:** **10 s** before an auto transition begins, the
  **non-playing side's 3/4 pad flashes at 1 Hz** (1 flash/second) to tell the DJ
  to stop working that alt deck — that side is about to go live (auto-play will
  switch it from the alt 3/4 back to the primary 1/2). Reuses the `rev1_leds`
  MIDI-out path.
- `ai` mode (future): beat-/structure-aware automatic transitions — the Auto-DJ
  frosting; depends on the beatgrid `beat_offset` model.

---

## Mouse-Friendly UI Plan (v-next)

Goal: the mixer window is fully usable **without** the DDJ-REV1 — every control
clickable/draggable — so it works on a laptop, and so REV1 polarity/handshake
issues never block a set. Adopt `control-room-01`'s proven **hit-region +
tweakable-drag** pattern: the render thread publishes a list of hotspot rects
with their control payloads; the main thread hit-tests mouse events against the
latest snapshot (already thread-safe there).

- [x] **Foundation — hotspot system (done 2026-07-12).** A `_Hit` list
  (`x0,y0,x1,y1,mode,lo,hi,get,set`) is built during `_render_ui` next to each
  widget and published under `_frame_lock`; `on_sdl_event` routes
  `MOUSEBUTTONDOWN/MOTION/UP` against it (`_begin_drag`/`_drag_to`/`_end_drag`).
  Draw coords are full-window pixels == SDL mouse coords, so no `ui_scale`
  conversion is needed. `get`/`set` bind the same engine/deck floats the REV1
  writes, so mouse and hardware share one value. (Plain `__slots__` class, not a
  dataclass — the module is imported by path and isn't in `sys.modules`, which
  breaks dataclass string-annotation resolution.)
- [x] **M-mouse 1 — faders & knobs (drag) (done 2026-07-12).** Crossfader,
  per-channel gain, color filter (bipolar) and master are click-and-drag and
  jump to the cursor; the 3 EQ knobs turn with a relative vertical drag (up =
  boost, no jump, `_KNOB_DRAG_SPAN` px = full sweep). A click off any control
  still toggles the deck under it. Follow-ups: tempo/pitch has no widget yet;
  double-click-to-reset and scroll-wheel not yet added.
- [ ] **M-mouse 2 — buttons.** Click PLAY/CUE, SYNC, FX engage (press-hold with
  the mouse), and a clickable hot-cue / loop pad grid per deck.
- [ ] **M-mouse 3 — browser.** Click a row to select, scroll-wheel to browse,
  per-deck **▶A / ▶B** load buttons (or double-click a row → active/last deck),
  drag the scrollbar.
- [ ] **M-mouse 4 — waveform.** Click/drag on the waveform overview to seek; hold
  to scrub (mouse "scratch"); optional needle-drop.
- [ ] **Polish.** Hover highlights, tooltips with the value, keyboard fallbacks.

Phasing: Foundation → M-mouse 1 (the faders/EQ are the 80% win) → 2 → 3 → 4.

## Performance Pad Modes Plan (v-next)

> **UI + mouse actions in (dj-mixer-01 0.13.0):** each deck now shows an 8-pad
> grid + two rows of mode buttons in REV1 order (cue/loop/track/sample ·
> jump/roll/trans/scratch). **Mouse-wired**: hot cue, auto loop, roll (momentary),
> **track-nav** (`deck.seek_fraction`), **beat jump** (`deck.beat_jump`); pads
> self-label per mode. **Still needs subsystems**: sampler, transform (gate),
> scratch bank. **Hardware note-bases** for the new modes still must come from the
> REV1 MIDI list before wiring the pads to the controller (Appendix A only covers
> hot cue / auto loop / roll).

Goal: flesh out the REV1's eight performance pads across the full set of pad
modes. On the REV1 the four pad-mode buttons make the pads emit a **different
note base** per mode on the shared pad channels (deck A = MIDI ch 8/9
normal/+shift → 0-indexed 7/8; deck B = 10/11 → 9/10); `rev1_input.py` already
dispatches by that note base. **Every new mode's note base must be transcribed
from Pioneer's official DDJ-REV1 MIDI list (Appendix A) — never guessed**
(CLAUDE.md MIDI rule).

**Already shipped** (for reference, don't rebuild):

- **Hot Cue** — notes 0–7; normal press sets/jumps, +shift deletes.
- **Auto Loop** — notes 16–23; toggles a loop of `LOOP_BEATS[pad]` beats.
- **Roll** — notes 80–87; momentary loop while held.
- **Scratch** — the jog platter (touch note 54 + relative CC 34/35), not a pad
  mode but the eighth "scratch" concept from the owner's list.

**New modes to build** (owner listed: beat jump, trans, tracking, sampler,
scratch bank). Grouped by shared machinery / risk:

- [ ] **Beat Jump** *(S — playhead math, reuses the loop/beat engine)*. Eight
  pads = jump sizes/directions (e.g. 1/4 pads jump back, others forward, or a
  size grid ±1/2/4/8 beats) staying in time. No DSP, no assets.
- [ ] **Trans / Transform** *(S — small DSP)*. Rhythmic channel gate synced to
  the deck BPM/phase; pads = gate rates (1/16 … 1 beat). A gain gate in the mix
  path; reuses the existing `bpm`/phase already driving the beat flasher.
  **Keep it (decided 2026-07-13).** DJs use Transform to rapidly cut a channel
  on/off in time (from the "transformer" crossfader scratch) for stutter/gating
  over build-ups, drops, and breakdowns. Beatgrid editing lives on the window
  (above), so it needs **no** pad slot — there's no reason to drop Transform for
  it. Transform overlaps with loop roll + the planned gate FX, so *if* future
  hardware pad-mode pressure ever forces a cut it's a defensible one, but that's
  a later trade, not now.
- [ ] **Tracking = track navigation** *(S — playhead math)*. **Owner decision
  2026-07-12: the tracking pads do section-jump navigation, not beatgrid
  editing.** Eight pads jump the playhead to eight equal points across the
  loaded track — pad *i* → `position = duration × i/8` (0%, 12.5%, … 87.5%) — a
  fast scrub/section grid for long tracks. (Beatgrid editing is split out as its
  own feature below.)
- [ ] **Sampler** *(L — new subsystem)*. Load short one-shots/stingers to the
  eight pads and mix their voices over the master. Needs a sample loader, a
  small polyphonic voice mixer in the engine, committed sample assets, and
  config (bank path, gain). Pairs with the backlog `audio-out-01` clip idea.
- [ ] **Scratch Bank** *(M — reuses the sampler loader + existing platter
  scratch)*. Temporarily swap a scratch-source sample onto a deck to scratch
  with (platter already implemented), then restore the loaded track. Depends on
  the Sampler loader infra landing first.

**Split-out feature — Beatgrid editing** *(M — not a pad mode)*. Conceptual
overview + principles: **dj-mixer-01 `README.md` → "Beat Grid Editing"**. The
owner wants grid correction handled *some other way* than the tracking pads.

- **Surface (decided 2026-07-13):** the **mixer window (mouse) + keyboard**, not
  the REV1 performance controls — gridding is a *prep* activity, so it must stay
  off the primary controller's performance path and muscle memory. Ties into
  *M-mouse 4 — waveform* (set-downbeat / drag-to-shift on the waveform). Optional
  REV1 GRID pad-mode only later, opt-in, and only if a pad slot is free.
- **Data model:** add a **beat anchor** `beat_offset` (seconds) to the deck
  alongside `bpm`; all phase becomes `(position − beat_offset) × bpm/60` (the
  beat flasher, SYNC, and future quantized pads read this one anchor). Defaults
  to `0.0` → fully backward compatible. Variable/warp grids (multiple anchors)
  are a later generalisation, out of scope for v1.
- **Phasing:** (1) model — add `beat_offset`, thread it through SYNC + the
  flasher, and have `estimate_bpm` return an initial downbeat offset (pure logic,
  no UI); (2) render beat/bar markers on the window waveform (read-only; pairs
  with *Waveform niceties*); (3) mouse/keyboard editing — set-downbeat,
  drag-to-shift, ÷2/×2, nudge ±, tap tempo (non-destructive); (4) persistence —
  a per-track sidecar cache (`{bpm, beat_offset}` keyed by path+mtime/hash) with
  reset-to-detected; (5) later — optional REV1 GRID mode, variable/warp grids.
- **Why:** directly improves SYNC + flash accuracy since BPM is auto-estimated
  per track and often a hair off the downbeat; it's also the foundation the
  future Auto-DJ needs for beat-accurate automatic transitions.

**Proposed sequencing (recommendation — confirm on return):** Beat Jump →
Trans → Tracking (track-nav) → Sampler → Scratch Bank, one mode per commit +
submodule bump, each with its own tests + docs (avoid a monolithic commit per
CLAUDE.md). Beatgrid edit/lock is scheduled independently once its surface is
chosen. **Owner is keeping this in planning; no code yet.**

## Library Analysis & Faceted Filter Plan (v-next)

The browser now has **search + a faceted filter flyout** (tags / artists / BPM
range / genre) in `library.py`, drawing facet values from each track's **tags**
(`Library.distinct(facet)`).  BPM uses fixed **overlapping** bands (90–110,
100–120, …).  That's tier 1; the facet *data source* should grow through
progressive analysis tiers, all feeding the same filter + browser.

**Analysis tiers (owner-directed 2026-07-13; progressive, layered):**

1. **Tagged-set (current default).** Read facets from file tags on demand, cached
   per entry.  Zero analysis cost; quality tracks how well the crate is tagged;
   missing facets are simply absent.
2. **At-load.** When a track loads onto a deck, run cheap DSP on it (BPM already
   via `estimate_bpm`; add key, energy, and the beatgrid `beat_offset`).  Fills
   gaps for the tracks actually in play; ties into the Beatgrid feature.
3. **Full library (optional continuous).** A background pass over the whole
   folder computing + caching facets/analysis for every track (BPM, key, energy,
   waveform preview).  *Continuous* variant watches the folder and (re)analyses
   new/changed files.
4. **All prior + stems.** Add stem separation (drums / bass / vocals / other)
   per track for stem-aware filtering + future stem FX.  Heaviest; opt-in.

**Cache/index.** Persist analysis in a **local library index** (JSON or SQLite)
keyed by path + mtime/hash — never committed (same spirit as the `config.toml`
gitignore item).  The faceted filter reads the index instantly instead of
re-reading tags every time `distinct()` is called (today's on-demand tag read is
fine for small crates but O(N files) per facet expand — the index removes that).

**Config surface (to design).** `[dj_mixer].library_analysis =
"tagged" | "at_load" | "full" | "full_continuous" | "stems"` (or layered
booleans), plus an index path.  Facets/filters stay identical across tiers; only
their completeness + new facets (key, energy, stems) grow.

**Open:** index format + schema, incremental/continuous scan scheduling (must not
touch the audio/RT path), stem backend choice, and how key/energy surface as new
filter facets.

## Feature Backlog & Ideas

Owner-requested / near-term first, then a grab-bag to prioritize.

- [x] **BPM beat flasher (done 2026-07-12).** The **PLAY button** pulses on its
  own deck's beat while playing (phase from `position × bpm/60`, buffer-latency
  compensated), on for the first half of each beat. ~2 MIDI-out messages per beat
  vs the VU's continuous stream — the **real fix** for the USB-MIDI congestion
  flake. The pad VU is **retired**; pads now show set hot cues only. Config
  `beat_flash` (default true). Owner chose the play button over the pads.
- [ ] **Mix recording.** Capture the master mix to a file (record your set) —
  tap the existing engine output.
- [ ] **Cue / headphone monitor.** Pre-listen a deck on a second output device
  (split master vs cue), the classic DJ headphone workflow.
- [x] **Track metadata (done 2026-07-12).** The browser reads ID3/Vorbis tags
  (`mutagen`, optional) and shows `Artist - Title`, falling back to the filename
  stem when untagged or the package is absent. Tags are read lazily per visible
  row and cached; the display name is captured at load time and propagates to
  the deck's `snapshot()['track']` label. Follow-up idea: a dedicated
  now-playing HUD line for the active deck.
- [ ] **Waveform niceties.** Frequency-colored waveform, beat-grid markers,
  on-waveform BPM/time; colored playhead.
- [ ] **Key detection + harmonic mixing.** Estimate musical key on load; show
  Camelot-style compatible-key hints for the other deck.
- [ ] **Auto-gain / loudness normalization** on load so decks match in level.
- [ ] **Sampler pads.** One-shot samples/stingers on a pad bank (pairs with
  `audio-out-01` clip playback). → now scoped under **Performance Pad Modes
  Plan** (Sampler mode).
- [ ] **More FX + FX2.** Reverb / flanger / gate / filter-roll and the second FX
  unit + its paddle.
- [ ] **Browser search / crates / recently-played**; **session recall**
  (save/restore deck + mixer state).
- [ ] **Generalize MIDI mapping.** A mapping-file layer so other controllers work
  (mirrors the `midi-controllers-01` preset idea) — REV1 becomes one profile.
- [ ] **Deck depth.** True shadow-playhead loop roll, slip mode. (Beat-jump pads
  moved to the **Performance Pad Modes Plan**.)
