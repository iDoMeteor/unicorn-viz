---
Owner: Planning
Status: draft — M-0 scaffold shipped 2026-07-07
Last updated: 2026-07-07
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
  channel gain, VU) + centre master + crossfader. `Shift+D` toggles; `Esc`
  closes; left-click toggles a deck. 32 tests green; frame verified headlessly.
- [x] **M-4 — Integration + docs (done 2026-07-07, main `a6e3a5a`).**
  `_load_dj_mixer_controller_class()` + guarded load site in `app.py` registers
  the `dj_mixer` subsystem and `Shift+D` handler; defaults = loaded-but-idle
  (REV1 wired, window + audio stream closed until opened). `[dj_mixer]` skeleton
  added to `config.full.example.toml` (config.toml left to the owner); drop-in
  registered in `docs/drop-ins.md`; `HELP_ENTRIES` present. Remaining M-4
  polish: HUD `snapshot()` for now-playing, monitor-source guidance in docs.
- [ ] **v2 backlog (not scheduled):** absolute jog scratch, hot-cue/loop pads,
  FX paddles, beat-sync via `auto-vj-01`.

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
  is realised on the pads. Exact pad **colour** is set by the hardware's active
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
