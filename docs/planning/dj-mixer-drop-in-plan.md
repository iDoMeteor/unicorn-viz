---
Owner: Planning
Status: REV1 fully wired (M-1..M-4, scratch, cues, manual+auto loops incl. the
corner LOOP IN/OUT/1/2X/2X buttons, FX, BPM/SYNC, lighting, browser). All 8 pad
modes (mouse + hardware). Mouse M-mouse 1/3/4 done; transport bar (BACK/PLAY/
CUE/LOOP/IN/OUT/CLR), session recall (state.py), **hash-keyed track store**
(track_store.py: BPM/cues/loops/grid remembered forever), beat-grid v1
(beat_offset + zoom grid lines + right-click set-downbeat), library manager
(BPM column, sort, analyze all/filtered, context menu, keyboard nav), platter
indicator all landed (0.21.0). Planning: bigger platter viz (collapsed decks),
accordion crate browser, streaming sources. Pending: hardware bring-up, mouse
M-mouse 2 remainder, feature backlog.
Last updated: 2026-07-15
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

## Open Items (truth-synced 2026-07-18)

Since the 2026-07-17 truth-sync, a large run landed: ~~key detection +
harmonic mixing~~ (0.42, wheel-coloured KEY column + green/magenta name
signals + KEY sync), ~~slip mode~~ (0.44), ~~sync phase-lock~~ (0.44),
~~bar-level phrase alignment~~ (0.46), FX depth (0.47, six tunable slots +
SETTINGS panel), ~~100% REV1 MIDI coverage~~ (0.51, PDF-verified: paddle
lever, LEVEL/DEPTH macro, shift layer, vinyl-off jog), Beat Grid Editor v1
(0.54), **persistent sync/key LOCKs** (0.53) and a **legend/help overlay**
(0.55). With LOCKs + auto-play XFADE + KEY-auto + auto-gain the mixer can
run a beatmatched, harmonically-mixed, level-matched set on its own — the
AI-DJ substrate already exists.

The live short list, in the owner's chosen order:

1. **AI v Human mode** — the epic. Phase 1 not started, but the pieces are
   now in place (auto-play director, sync/key locks, key+tempo compatibility
   scoring already drives the green/magenta browser signals). This is the
   next big feature.
2. **Deck depth (deferred v2)** — full slip refinements + true DVS are out of
   scope; basic slip shipped 0.44.
3. **Stems round 2 — DEFERRED (owner call 2026-07-17)** — ~~REV1 stem pad
   bank~~ (done 0.39.0). Deferred: per-stem gains (not just mutes), stem FX.
   The unicorn-horn integration discussion stays pending.
4. **Control-pane polish — DONE (0.56.0, 2026-07-18)** — 2-deck inset pod
   moved to the inner (console) edge: dials on top (EQ + TRIM/FLT/D-W/FXM),
   HOLD centred above each bank, centred PITCH/TEMPO sliders, a six-effect
   selector at the foot (single click select/unlock, double-click lock on).
5. **Hardware bring-up checklist** — the 1.0.0 gate. Every REV1 control is
   coded (0.51); this is now a live-hardware validation pass, not
   engineering.

## Stems (landed 0.34.0 — follows unicorn-horn's decisions)

Serato/djay-style per-deck stem toggles, built on unicorn-horn's ADRs rather
than realtime separation:

- **Offline, deterministic extraction** (ADR-0002): Demucs CLI subprocess
  (`python -m demucs`), exactly unicorn-horn's `DemucsCliStemAdapter` shape;
  model set = ADR-0007 (`htdemucs` default, MDX variants allowed).
- **Capability-aware UI** (ADR-0003): the V/M/B/D chips & STEMS+ button stay
  visible but disabled/grey when unavailable, tooltips say why.
- **Manifest-backed cache**: `runtime/stems/<hash16>-<slug>/` with the four
  wavs + `manifest.json` (source, audio_hash, model, runner, elapsed).
- **Metadata home**: buckets are keyed by the deck's *audio hash* and recorded
  in the track store next to cues/loops/BPM — stems survive retag/rename/move.
- **Runtime reuse**: interpreter resolution prefers a local unicorn-horn venv
  so one demucs install serves both products.
- Audio: all-stems-on plays the untouched master (bit-exact); muting switches
  the deck read path to a per-block weighted stem sum (playback, loops,
  transform gate, and scratching all follow).
- Deferred: per-stem gains (not just mutes), REV1 pad bank for stems, stem FX.

## Frequency-Coloured Waveforms (landed 0.34.0)

FULL/ZOOM/collapsed waves blend low=red, mid=green, high=blue from a per-track
(2048, 3) Butterworth band-energy grid computed once at load on a ~24 kHz
decimated mono mix; highs are display-boosted (energy ratio 1/1.6/3.2) so hats
read. Amplitude stays the RMS peak envelope; unplayed material dims to 42%.

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
- [x] **M-mouse 2 — buttons (done, truth-sync 2026-07-17).** Click PLAY/CUE, SYNC, FX engage (press-hold with
  the mouse), and a clickable hot-cue / loop pad grid per deck.
- [x] **M-mouse 3 — browser (done 2026-07-13, 0.18.0).** Double-click a row →
  loads the opposite deck (fresh setup → deck 1 + play); **scroll-wheel browses**
  the list; the visible window now **fills the pane height** (not a fixed 12) and
  reports the true total, with a **scrollbar indicator** on the right edge. Still
  open: per-deck **▶A / ▶B** load buttons, click-to-select-without-load, draggable
  scrollbar thumb.
- [x] **M-mouse 4 — waveform (done 2026-07-13, 0.18.0).** Press-drag on either
  wave **scrubs/scratches** through the deck's platter (`scratch_touch` +
  `scratch_move`); a click-and-release **seeks** — FULL = absolute needle-drop,
  ZOOM = relative to the playhead. Click-vs-drag split by a travel threshold
  (`_WAVE_CLICK_SLOP`). Fixed a HiDPI bug where mouse points weren't mapped to the
  drawable-pixel space the regions use, so clicks fell through to play/pause.
- [x] **Polish (done, truth-sync 2026-07-17).** Hover highlights, tooltips with the value, keyboard fallbacks.

Phasing: Foundation → M-mouse 1 (the faders/EQ are the 80% win) → 2 → 3 → 4.

## Performance Pad Modes Plan (v-next)

> **UI + mouse actions in (dj-mixer-01 0.14.0):** each deck shows an 8-pad grid +
> two rows of mode buttons in REV1 order (cue/loop/track/sample ·
> jump/roll/trans/scratch). **Mouse-wired + engine-backed**: hot cue, auto loop,
> roll (momentary), **track-nav** (`deck.seek_fraction`), **beat jump**
> (`deck.beat_jump`), **transform** (beat-synced gate, `deck.trans_rate`), and
> **sampler** (shared 8-slot one-shot player, `sampler.py`, `[dj_mixer].sampler_dir`).
> **DONE (0.16.0):** all eight pad modes are wired for **mouse and hardware** —
> hardware note bases came from the official MIDI list (`docs/midi/`, saved PDF):
> hot cue 0, auto loop 16, tracking 32, sampler 48, beat jump 64, roll 80,
> trans 96, scratch bank 112 (each base..base+7). `rev1_map.pad_mode_of()`
> resolves them. Scratch bank loads a sampler slot onto the deck as a scratch
> source (full platter-scratch integration lands with the platter work).

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

- [x] **Beat Jump (done — JUMP pad bank, truth-sync 2026-07-17)** *(S — playhead math, reuses the loop/beat engine)*. Eight
  pads = jump sizes/directions (e.g. 1/4 pads jump back, others forward, or a
  size grid ±1/2/4/8 beats) staying in time. No DSP, no assets.
- [x] **Trans / Transform (done — TRANS pad bank, truth-sync 2026-07-17)** *(S — small DSP)*. Rhythmic channel gate synced to
  the deck BPM/phase; pads = gate rates (1/16 … 1 beat). A gain gate in the mix
  path; reuses the existing `bpm`/phase already driving the beat flasher.
  **Keep it (decided 2026-07-13).** DJs use Transform to rapidly cut a channel
  on/off in time (from the "transformer" crossfader scratch) for stutter/gating
  over build-ups, drops, and breakdowns. Beatgrid editing lives on the window
  (above), so it needs **no** pad slot — there's no reason to drop Transform for
  it. Transform overlaps with loop roll + the planned gate FX, so *if* future
  hardware pad-mode pressure ever forces a cut it's a defensible one, but that's
  a later trade, not now.
- [x] **Tracking = track navigation (done — TRK pad bank, truth-sync 2026-07-17)** *(S — playhead math)*. **Owner decision
  2026-07-12: the tracking pads do section-jump navigation, not beatgrid
  editing.** Eight pads jump the playhead to eight equal points across the
  loaded track — pad *i* → `position = duration × i/8` (0%, 12.5%, … 87.5%) — a
  fast scrub/section grid for long tracks. (Beatgrid editing is split out as its
  own feature below.)
- [x] **Sampler (done — SMPL bank + sampler.py, truth-sync 2026-07-17)** *(L — new subsystem)*. Load short one-shots/stingers to the
  eight pads and mix their voices over the master. Needs a sample loader, a
  small polyphonic voice mixer in the engine, committed sample assets, and
  config (bank path, gain). Pairs with the backlog `audio-out-01` clip idea.
- [x] **Scratch Bank (done — SCR bank + engine scratch_bank, truth-sync 2026-07-17)** *(M — reuses the sampler loader + existing platter
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

- [ ] **"Give me a tour" — mixer walkthrough (owner-requested 2026-07-18).** A
  guided tour entry in the mixer's `?` help overlay that walks a first-time DJ
  through: deck anatomy (2×2 vs 2-deck, full+zoom waves, playhead-tracking
  platter) → the browser's colour language (white on-deck / green mixes clean /
  magenta one wheel step / gold has stems) → load + transport → the pod (dials,
  PITCH/TEMPO, HOLDs, FX selector single-click-select vs double-click-lock) →
  SYNC/KEY/🔒 locks incl. pre-sync-on-load → stems (`G:` faders, right-click
  mute, `S:` solos) → auto-play + the scratch transition → headphone cue.
  Non-blocking, skippable, resumable; never touches audio state. Canonical
  cross-surface plan: [guided-tour-plan.md](guided-tour-plan.md).

- [x] **BPM beat flasher (done 2026-07-12).** The **PLAY button** pulses on its
  own deck's beat while playing (phase from `position × bpm/60`, buffer-latency
  compensated), on for the first half of each beat. ~2 MIDI-out messages per beat
  vs the VU's continuous stream — the **real fix** for the USB-MIDI congestion
  flake. The pad VU is **retired**; pads now show set hot cues only. Config
  `beat_flash` (default true). Owner chose the play button over the pads.
- [x] **Mix recording (done 2026-07-16, 0.29.0).** REC button by the
  crossfader; post-master tap -> WAV via a flusher thread.
- [x] **Cue / headphone monitor (done 2026-07-16, 0.30.0).** PFL cue bus, CUE
  buttons under each fader + master, second output stream
  (headphone_device), REV1 M7/M8 wired.
- [x] **Track metadata (done 2026-07-12).** The browser reads ID3/Vorbis tags
  (`mutagen`, optional) and shows `Artist - Title`, falling back to the filename
  stem when untagged or the package is absent. Tags are read lazily per visible
  row and cached; the display name is captured at load time and propagates to
  the deck's `snapshot()['track']` label. Follow-up idea: a dedicated
  now-playing HUD line for the active deck.
- [x] **Waveform niceties (done 0.34.0–0.35.x).** Frequency-colored waveform, beat-grid markers,
  on-waveform BPM/time; colored playhead.
- [ ] **Key detection + harmonic mixing.** Estimate musical key on load; show
  Camelot-style compatible-key hints for the other deck.
- [x] **Auto-gain / loudness normalization (done 0.38.0, 2026-07-17)** — RMS-of-loud-body gain on load, `auto_gain` config, clamped ±8 dB.
- [x] **Sampler pads (done — duplicate of Sampler above, truth-sync 2026-07-17).** One-shot samples/stingers on a pad bank (pairs with
  `audio-out-01` clip playback). → now scoped under **Performance Pad Modes
  Plan** (Sampler mode).
- [x] **More FX + FX2 (done 2026-07-16, 0.31.0).** FX1 + FX2 units with
  echo/reverb/flanger slots, SLOT SELECT buttons, paddles and per-unit depth.
  Still open: gate/filter-roll effects, FX UI readout.
- [x] **Browser search / crates / recently-played (done — RECENT tab landed 0.38.0, 2026-07-17)** (crates → see **Accordion
  Crate Browser Plan** below).
- [x] **Session recall (done 2026-07-13, 0.18.0).** `state.py` persists the board
  to `runtime/dj_mixer_state.json` (atomic JSON): master + crossfader, every
  deck's gain/TRIM/EQ/filter/pitch, pad modes, auto-play mode, collapsed decks,
  and each loaded deck's track path + playhead position. Restored on startup
  (controls instantly; tracks decoded off-thread, always **paused** at their saved
  position); saved on close/shutdown + a 30 s autosave. Config `persist_state`
  (default true), `state_path` override.
- [x] **Generalize MIDI mapping (done 0.38.0, 2026-07-17).** `midi_map.py` TOML mapping files (`mappings/example-generic.toml`), `[dj_mixer] midi_map` config; Rev1Input parametrized over its control map so other controllers work
  (mirrors the `midi-controllers-01` preset idea) — REV1 becomes one profile.
- [ ] **Deck depth.** True shadow-playhead loop roll, slip mode. (Beat-jump pads
  moved to the **Performance Pad Modes Plan**.)

## AI v Human Mode (THE EPIC — owner-requested 2026-07-16)

**The dream:** alternating full-system control, song by song — a human runs
the whole rig (mixer + VJ visuals) for one track, then the AI takes the booth
(auto-mix + auto-VJ), then back — a live human-vs-machine battle format.

- **Building blocks that already exist:** auto-play (cut/crossfade + the
  armed-deck/override-return logic), SYNC/beatmatch, per-track BPM + beat grid,
  the disabled **AI mode button** in the mixer console (reserved for exactly
  this), auto-vj-01 (beat-locked visual direction), and the now-playing hub
  (who's "on deck" is already announced).
- **Missing pieces to design:** a *turn arbiter* (who owns the controls this
  song; handoff at track boundaries via the auto-play transition points), a
  **control-ownership flag** surfaced across mixer + VJ (inputs from the
  "benched" side ignored or blended out), an on-screen **VS scoreboard/banner**
  (round number, who's live, maybe crowd-reaction scoring via audio energy),
  and an AI mixing brain one notch above auto-play: pick the next track
  (harmonic/BPM-aware once key detection lands), beatmatch, and choose
  cut/crossfade per transition.
- **Phasing sketch:** (1) turn arbiter + handoff at track end (mixer only:
  AI song / human song alternation using existing auto-play); (2) VJ side
  joins (auto-vj on for AI turns, manual for human turns); (3) the show layer
  — VS banner, round intros, scoring; (4) smarter AI selection (key/energy
  aware) as library analysis tiers land.

## Platter Integration Plan (v-next)

The hardware jog already scratches (touch note 54, rotation CC 34/35, side jog
CC 33 → `deck.scratch_touch`/`scratch_move`). This plan is about the **UI**: a
mouse path to the same scratch, plus a visual platter. Agent proposed three
ideas (2026-07-13); **owner picked #1 + #2 to execute nextish**, #3 deferred.

- [x] **Platter indicator (idea #2, done 2026-07-13, 0.18.0).** A compact spinning
  disc in each deck header: angle derives from the playhead position, so it spins
  while playing, freezes when paused, and **jogs back/forth under a scrub/scratch**;
  the ring turns **red while scratching** (`deck.is_scratching()`). Cheap to draw,
  doubles as a transport + motion read-out. Placement chosen by the agent (header,
  all decks). See `_draw_platter` in `ui.py`.
- [x] **Waveform scrub/scratch (idea #1, done 2026-07-13, 0.18.0).** Press-drag on
  a waveform scratches through the deck platter; click seeks. (Details under
  *M-mouse 4* above.) This is the mouse-parity half of platter integration.
- [x] **Bigger platter viz when decks 3 & 4 are collapsed (done 2026-07-15,
  0.24.0).** In 2-deck mode the waves cap at ~25% of the pane each and each
  primary draws a **big neon platter**: glow rims breathing on the beat, vinyl
  grooves, strobe spokes, a downbeat-flash beat ring, orbiting sparkles while
  playing, red rim while scratching, BPM on the label — and the disc is
  **grab-and-spin scratchable** (angular drag). The compact header disc stays
  on always.
- [x] **Full jog-wheel widget (done — the 2-deck-mode big scratchable platter, truth-sync 2026-07-17).** A large round platter with an
  outer nudge ring + inner scratch zone. Most skeuomorphic but real-estate hungry
  in the 2×2 grid and largely duplicates waveform-scrub; revisit only if the
  collapsed-decks viz proves it earns the space.

**Skeuomorphism (owner asked what it means):** designing a digital control to
*look and behave like its real-world physical counterpart* — e.g. a round vinyl
platter that visibly spins, a fader that looks like a channel strip, a knob with a
pointer and detent. The opposite is an **abstract/flat** control (a plain slider,
a number). Skeuomorphic = more familiar/tactile and better motion feedback, but
costs screen space and can add visual noise; flat = compact and clean but less
immediately "readable" as a physical action. Idea #3 (a real jog wheel) is the
most skeuomorphic; the current header disc is a light, semi-skeuomorphic middle
ground. **Owner has ideas here — discuss after this batch.**

## Accordion Crate Browser Plan (owner-requested 2026-07-13 — DONE: phases 1–2 + persistence 0.26.0; sample-bucket routing 0.27.0 — drag-drop pad banks, split sampler/scratch banks, ≤8-track auto-fill from samples//scratch/ crates, bank persistence)

Goal: organise the browser into **buckets** the owner named — *crates, loops,
foley, samples, scratch, vocals* — instead of one flat track list. Owner's
chosen starting approach: **a folder per bucket**, shown as an **accordion** —
click a bucket to expand it and **auto-contract the others**, matching the core
app's mouse-menu accordion behaviour (one section open at a time).

- **Data model.** Each bucket = a configured directory (default: subfolders of
  `[dj_mixer].music_dir`, e.g. `crates/`, `loops/`, `foley/`, `samples/`,
  `scratch/`, `vocals/`). `Library` scans per-bucket so each keeps its own track
  list + facet cache; the flat scan becomes the "all / crates" default bucket.
- **UI.** Replace the single list header with a stack of bucket headers
  (name + count). The **expanded** bucket shows its windowed, scrollable track
  list (reuse the height-fill + wheel scroll + scrollbar just added); collapsed
  buckets show only their header. Exactly one expands at a time (accordion);
  clicking another collapses the current — mirror the core mouse-menu component's
  open/close semantics rather than inventing new ones.
- **Interaction.** Wheel scrolls within the open bucket; double-click / drag to a
  deck works as today; buckets remember their last selection. Sample-type buckets
  (foley/samples/scratch/vocals) should also be loadable into the **sampler** /
  **scratch bank**, not just decks — natural tie-in with the Performance Pad Modes.
- **Config.** `[dj_mixer].crates = { crates = "…", loops = "…", … }` (or auto from
  subfolders) + which bucket opens on start. Ties into the **Library Analysis &
  Faceted Filter Plan** above: facets/filters apply *within* the open bucket.
- **Phasing.** (1) per-bucket scan in `Library` (logic only); (2) accordion UI
  reusing the new browser windowing; (3) route sample buckets to sampler/scratch;
  (4) filters-within-bucket + persisted last-open bucket in `state.py`.

## External Streaming Sources Plan — Spotify / Beatport / Apple·Google (v-next, owner-requested 2026-07-13)

Goal: **Spotify playlists (and later Beatport, Apple/Google Music) as top-level
accordion buckets in the browser.** Builds on the *Accordion Crate Browser Plan*
above — each service is another top-level bucket whose children are
playlists → tracks.

### ⚠️ The hard constraint (decide this first)

**You cannot pull raw Spotify/Apple/Google audio into a deck.** Their Web APIs
expose *metadata only*; feeding their streamed audio into a custom mixer for
scratch/cue/loop is not offered and is against their terms. So a "Spotify
bucket" can browse playlists but the tracks are **not directly deck-loadable**.
Three ways to make it useful (owner picks — this drives everything else):

- **A) Local-file matching (recommended).** Browse the streaming playlist; for
  each track, match it to a **local file** in the crates (by ISRC, else
  artist+title+duration) and load *that* file into the deck. Fully legal + fully
  mixable (scratch/cue/loop). Unmatched tracks show greyed with a "no local
  file" tag (a buy/download to-do list). Turns your Spotify playlists into a
  shopping/prep list mapped onto what you can actually spin.
- **B) `spotifyd` Connect capture.** The project already runs `spotifyd`
  (`_SPOTIFYD_WARMUP_S` in `beat_grid.py`); capture its PipeWire output as a
  **live line-in deck source**. Plays anything in Spotify but it's a *live,
  non-seekable* stream — no scratch/cue/loop, no waveform overview. A "broadcast
  deck," not a performance deck. Could pair with A.
- **C) Browse-only reference.** Show playlists/queue as read-only context (what's
  playing, up-next) with no deck load. Lowest effort; ties to the existing
  now-playing HUD.

**Recommendation:** ship **A** (real DJ value, legal, mixable), optionally add
**B** later as a "Spotify live deck." **Beatport is the exception** — see below.

### What already exists (reuse, don't rebuild)

`drop-ins/spotify-01` (**v1.0.0-rc.1**, active) already implements the whole
Spotify auth + Web API spine, per CLAUDE.md's Spotify rules:

- **PKCE auth** (Authorization Code + PKCE) over a **loopback `127.0.0.1`**
  redirect, minimal scopes (`playlist-read-private`,
  `playlist-read-collaborative`, user-read-playback/currently-playing), tokens
  in an **ignored runtime file** (`runtime/spotify-token.json`) with refresh.
- Web API polling for **playback context, queue, and the current playlist**;
  local MPRIS metadata via `playerctl`.
- `snapshot()`, `begin_auth_async()`, logout hotkey.

**Gap to fill in `spotify-01`:** it resolves the *current* playlist context, not
a **browse-all** surface. Add (in the spotify-01 repo, its own commit + submodule
bump — Drop-In Source Policy): `list_playlists()` → `GET /me/playlists`
(paginated) and `playlist_tracks(id)` → `GET /playlists/{id}/tracks` (paginated,
request only needed fields incl. `external_ids.isrc` for matching). Honour 429 +
`Retry-After`, cache per-playlist, never store the client secret (Client ID +
PKCE only).

### Integration boundary (independence rules)

`dj-mixer-01` must **not hard-import** `spotify-01`. Consume it via
`vj_api` (preferred — add a small capability like
`vj_api.get_spotify_playlists()` / `get_spotify_playlist_tracks(id)`) or, if a
direct handle is unavoidable, `load_dropin_symbol()` wrapped in `try/except`
with a graceful "Spotify bucket hidden" fallback when spotify-01 is absent or
unauthenticated. The Spotify bucket simply doesn't appear if the drop-in isn't
installed/authed — never an error.

### Beatport / Apple / Google (later tiers)

- **Beatport** — the best "real DJ" fit: it's a **purchase/download** store, so
  tracks you own become **local files → fully deck-loadable** (no matching hack).
  Beatport also has LINK (streaming) + an OAuth catalog API for playlists/charts.
  Plan: OAuth (owner Beatport dev account), browse charts/playlists/purchases,
  load owned downloads directly; treat LINK-only tracks like option A/C.
- **Apple Music** — MusicKit (developer token + user token); metadata + playlist
  browse only, playback via Apple's SDK → same no-raw-audio constraint as
  Spotify → option A/C tier.
- **Google / YouTube Music** — no first-class DJ-friendly API; metadata/matching
  tier at best; lowest priority.

### Owner decisions needed before coding

1. **Audio strategy** (A local-match / B spotifyd capture / C browse-only) — A
   recommended.
2. **Spotify Developer app + Client ID** — owner registers the app, adds the
   `http://127.0.0.1:<port>/callback` loopback redirect, hands over the Client ID
   (goes in config, not the secret). Without this the Web API can't authenticate.
3. **Extend `spotify-01`** with `list_playlists()` / `playlist_tracks(id)` (its
   own repo/commit) — confirm before touching the shared drop-in.
4. Service priority order (recommend **Spotify → Beatport → Apple → Google**).

### Phasing (after the Accordion Crate Browser lands)

1. `spotify-01`: add `list_playlists()` + `playlist_tracks(id)` + a `vj_api`
   capability (spotify-01 repo).
2. `dj-mixer-01`: a **Spotify accordion bucket** (browse-only, option C) reading
   that capability via `try/except` — proves the boundary end to end.
3. **Option A local-file matching** (ISRC → artist/title/duration) so playlist
   tracks load their local file into a deck; greyed "no local file" otherwise.
4. Optional **spotifyd live deck** (option B).
5. **Beatport** bucket (owned downloads = local files) → then Apple → Google.

## Mixer Open-Window Performance Plan (owner-requested 2026-07-18)

**Symptom.** The first `Shift+D` open of the mixer is noticeably slower than
later opens. By design the mixer is *idle* until opened — the window, the
REV1 MIDI port, and the audio output stream are all deferred to open-time so
nothing claims USB/audio hardware while sitting unused (the snd_ump/UMP USB
fragility). So the first-open cost is exactly those deferred claims.

**What is NOT the cost (already handled).** Deck audio decode is *not* a
first-open cost: `_restore_state()` at controller construction (app startup)
decodes restored deck tracks **off-thread** (`dj_mixer_controller.py`, the
`# decode tracks off-thread` restore). The engine, decoder, track store and
browser are all built at startup too.

**First-open cost candidates** (in `open_window()`):

| Step | Nature | Notes |
|---|---|---|
| `_load_sibling('ui.py', 'MixerWindow')` | re-executes the ~1600-line `ui.py` module body **on every open** (its numpy/PIL deps are already in `sys.modules`, but `_load_sibling` does `spec_from_file_location` + `exec_module`, which does not consult `sys.modules`) | repeatable per-open cost, not just first |
| `MixerWindow(...)` | SDL window + GL context + shader compile + render-thread start | same class of cost as control-room's open |
| `_open_rev1()` | REV1 USB-MIDI claim (hardware) | **deferred by design**; ties into the separate MIDI-startup item — do not pre-claim at idle |
| `self._engine.start(...)` | PortAudio `OutputStream` open + `query_devices` + 4-channel probe | PortAudio host-API is already warm (the app's input capture inits `sounddevice` at startup), so this is stream-open cost, not cold init; still a device open + a channel-count probe |

**Instrumentation (landed 2026-07-18).** `open_window()` now logs
always-on `dj-mixer-01: open timing: <step> +N.Nms` deltas for `ui.py import`,
`window + thread`, `rev1 open`, and `engine.start` — the mixer-scoped analog
of the core `_StartupProfiler`. Measure the real split (cold first open vs.
warm reopen) before optimizing, rather than guessing which claim dominates.

### Measured results (2026-07-18) — all three candidates dropped

Two real opens, captured by the instrumentation above:

```
open #1:  ui.py import 3.2ms | window+thread  69.8ms | rev1 2.1ms | engine.start 22.3ms  ->  97ms
open #2:  ui.py import 3.1ms | window+thread 150.4ms | rev1 3.0ms | engine.start 42.4ms  -> 199ms
```

**`open_window()` is already fast (~100–200ms end to end), and every
pre-measurement hypothesis was wrong.** Recording this so nobody re-derives
the same guesses:

| Candidate | Predicted | Measured | Verdict |
|---|---|---|---|
| Pre-import `ui.py` at `__init__` | "cheap, safe win" | **3ms** per open | **Dropped** — the module re-exec is negligible; not worth the caching complexity |
| Background `engine.start()` | possibly dominant (PortAudio open) | **22–42ms** | **Dropped** — PortAudio host-API really is already warm from the app's input capture |
| REV1 claim cost | possibly slow (USB-MIDI) | **2–3ms** | **Dropped** — the claim is effectively free; MIDI has no bearing on open latency |
| `window + thread` | inherent | **70–150ms** (dominant) | Inherent: SDL window + GL context + shader compile |

Also note **there was no first-open penalty in these samples** — the *second*
open was slower than the first (150ms vs 70ms on `window + thread`, likely
compositor/GPU scheduling noise), so the cost is not a one-time warm-up.

### Where to look next (if "first open feels slow" persists)

The reported symptom ("not cheap the first time") does **not** match a
~100ms `open_window()`. If it still feels slow with these timings, the cost
is **downstream of `open_window()`**, not inside it. Most likely, in order:

1. **The render thread's first full frame.** `open_window()` returns as soon
   as the thread is *started*; the first 4-deck frame (waveform bars, browser,
   pads) is drawn afterwards and the window shows nothing until
   `SecondaryGLWindow.present()` uploads it. Instrument
   `MixerWindow._loop`'s first `_render_ui()` — the existing
   `render thread produced its first frame` / `first frame presented` log
   lines already bracket this; add a delta between them and `open_window()`
   returning.
2. **Deck audio decode**, when a session starts with decks *not* already
   restored — `deck.load()` decodes on the caller's thread and is explicitly
   "slow". Restored decks decode off-thread at app startup, so this only
   bites when loading fresh tracks at open time.
3. **Waveform/beat-grid analysis** for freshly loaded tracks.

Measure before optimizing — the same discipline that invalidated all three
candidates above.

**Non-goal (unchanged).** Moving the hardware claims (audio out, REV1) to app
startup — that reintroduces the idle-hardware-claim fragility the
deferred-open design exists to avoid. The measurements make this moot anyway:
those claims cost 2–42ms combined.

## Mixer Runtime Present-Coupling (owner-observed 2026-07-17)

**Symptom.** When the main visualizer is **paused or its window is
occluded/minimized**, the mixer window's refresh drops to a crawl — even
though the mixer's own render thread keeps producing frames fine.

**Root cause (diagnosed).** The mixer *produces* frames on its own throttled
render thread (`ui.py`, `render_interval` ≈ 30 fps), but it *presents* them
(GL upload + `SDL_RenderPresent` on its second SDL window) only when the core
main loop calls `controller.present()` — from `App._present_subsystems()`,
right after the main window's vsync `SDL_GL_SwapWindow`. So the mixer's
on-screen rate is **gated by the main-loop iteration rate**. Two things slow
that loop and starve the mixer present:

1. The main window's vsync swap is throttled by the compositor when that
   window is hidden/occluded (hidden windows get low-rate vsync callbacks).
2. `_present_subsystems()` has a **budget guard** that *skips* the subsystem
   present when the previous main frame overran 1.5× budget
   (`_SUBSYS_PRESENT_SKIP_MS`, up to `_SUBSYS_PRESENT_MAX_SKIPS`).

The present is deliberately main-thread-only because a second SDL window's
`SDL_RenderPresent` silently switches the GL context on Wayland and never
switches back — `_present_subsystems()` rebinds the main context afterward
(see its docstring). That constraint is why this isn't a trivial fix.

**Why it's parked (not a quick win).** Decoupling the mixer present from the
main loop means presenting the mixer window from something other than the
main thread's post-swap call — which reopens the exact cross-thread /
Wayland GL-context hazard the current design routes around. That's an
architectural change with real risk, not a one-liner.

**Candidate approaches (design-only, measurement-first).**

1. **Own paced present, still on the main thread.** Give the mixer present its
   own wall-clock cadence (e.g. a floor rate) so a slow/occluded main loop
   doesn't drop it below ~20–30 fps — decoupling the *rate* without moving the
   *thread*. Needs the main loop to keep iterating (not block) when occluded.
2. **Fully independent present** on the mixer's own thread with its own GL
   context made-current there, never touching the main context (so no rebind
   needed). Cleanest in theory; highest Wayland-context risk; prototype behind
   a flag.
3. **Accept + document** as an OS/compositor behavior for hidden windows
   (lowest effort) — the mixer is usually foreground when in use.

**Priority:** low (owner: "not a big deal"). Revisit if a two-screen setup
(visualizer on the audience display, mixer on the booth display) makes the
occluded-main-window case common.
