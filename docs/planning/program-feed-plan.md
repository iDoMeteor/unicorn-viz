# Program Feed — telling the VJ what is coming

Owner: Core / DJ Mixer / Auto VJ
Status: draft — awaiting audit review
Last updated: 2026-07-18

A **core-level, source-agnostic** feed carrying what the runtime knows about
the audio it is about to play: the beat grid, the song's structural timeline,
and upcoming events.

This corrects a scoping error in
[ai-dj-plan.md](../../drop-ins/dj-mixer-01/docs/ai-dj-plan.md) §7, which
designed timeline publishing as an AI DJ capability. It is not. **Every audio
source should feed the VJ, in every mode, all of the time** — whether the
operator is running the AI DJ, mixing by hand, or playing a file from the media
player. Auto VJ is the flagship; it should never be starved because of *how*
audio happens to be playing.

---

## 1. There is already a hub — extend it, do not add one

`unicornviz/now_playing.py` is already exactly the right shape:

- **Source-agnostic registry.** Any subsystem registers a named snapshot
  callable.
- **Already has three producers**: `dj-mixer-01` (priority 30), `media-01`
  (20), `spotify-01` (10).
- **Already resolves "who is live"** — the highest-priority playing source wins,
  with an ambient fallback when nothing plays.
- **Already degrades gracefully** — every key optional, no-ops on older cores.

The mistake would be building a parallel bus for structure data. The hub
already answers the hard question (*which source is the room hearing?*), and a
second mechanism would have to answer it again, differently.

**Decision: extend the existing snapshot contract with optional program
fields.** No new registry, no new transport, no protocol. Contracts and hooks,
as the owner put it.

---

## 2. Contract extension

All fields optional; every consumer must work when they are absent. Producers
publish what they genuinely know and omit the rest — **an omitted field is very
different from a guessed one.**

| field | meaning | who can fill it |
|---|---|---|
| `beat_grid` | BPM, downbeat phase, bar position — *authoritative* when present | dj-mixer (hand-corrected grid); media-01 (if detected) |
| `timeline` | ordered sections (`intro`/`build`/`drop`/`breakdown`/`verse`/`outro`) with start/end, confidence, energy | any source with offline analysis of a local file |
| `clock` | track position, playback rate and wall-time, for room-time conversion (§3, §8) | any local-file source |
| `upcoming` | near-future events: next section boundary, scheduled transition, announced performance action | dj-mixer; media-01 (boundaries only) |
| `confidence` | per-field confidence, so consumers can require more for expensive decisions | all |

### Producers

- **dj-mixer-01** — the richest source, and **in every mode**: manual mixing,
  classic XFADE/CUT, Smart Fader, or AI DJ. Publishing must live in the mixer's
  own runtime, *not* behind an AI DJ flag.
- **media-01** — must gain analysis + publishing. Playing a file from the media
  player should feed the VJ just as well as playing it on a deck.
- **library preview** — same treatment where a preview is audible.
- **spotify-01** — cannot contribute structure (remote playback, no local
  samples). It publishes what it has and omits the rest, which the contract
  already handles.

### Consumers

- **auto-vj-01** — the reason this exists.
- Others (overlays, control-room, lyrics) may read the same feed later. Nothing
  in the design is VJ-specific.

---

## 3. Room time, not track time

The single most important rule.

A consumer cares *when the drop happens in the room*, not where it sits in the
file. Those differ: varispeed moves everything, and at +4% the drop arrives
sooner in wall-clock terms.

The **producer** owns that translation, because the producer owns the playhead
and the rate. A consumer must never have to know that a pitch fader exists, and
the VJ must never do arithmetic on someone else's transport.

Room-time therefore drifts whenever the rate changes. Rather than re-sending
the future to chase that drift, the producer publishes the timeline once (it is
static in *track* time) plus a small, frequent clock, and consumers convert
through a core-provided helper. See §8.

---

## 4. Why this matters most for the beat grid

`auto-vj-01` runs a full BeatTracker — coherence windows, phase tolerance,
Schmidt trigger gain/release, warmup handling — all of it to **recover** a beat
grid from audio it is hearing for the first time.

When a local source is playing, that grid is already known exactly, and in the
mixer's case has been hand-corrected in the Beat Grid Editor.

**Rule: prefer an authoritative published grid when one is present.** This does
not remove the BeatTracker, which remains essential for live input, Spotify,
and any source that cannot publish. It removes the *guessing* for sources that
can.

---

## 5. Talking back

One verb, deliberately. A consumer may post a **hold request** — *"mid-climax,
give me 8 bars if you can"* — carrying a deadline. The producer honours it when
its own constraints allow and declines otherwise.

**Producers never block on consumers.** A slow, silent or absent VJ changes
nothing about playback. Requests are advisory, and an unanswered request is a
normal outcome, not an error.

---

## 6. Independence

Standard drop-in rules apply in both directions:

- The VJ stays fully functional with no mixer and no media player loaded,
  falling back to its current reactive detection.
- The mixer and media player stay fully functional with no VJ loaded; publishing
  into a hub nobody reads is a no-op.
- Every call site guarded, per the existing `register_now_playing` pattern.

---

## 7. Phases

1. **PF-1 — Contract extension.** Optional fields on the now-playing snapshot;
   consumer-side accessors; no producer changes. Nothing breaks, nothing is
   fed yet.
2. **PF-2 — Mixer publishes grid + position.** All modes. Immediate VJ win with
   no structure analysis required.
3. **PF-3 — VJ prefers the published grid.** With fallback intact.
4. **PF-4 — Timeline.** Gated on AID-0 structure analysis
   ([ai-dj-plan.md](../../drop-ins/dj-mixer-01/docs/ai-dj-plan.md) §3) being
   validated first.
5. **PF-5 — media-01 analysis + publishing.**
6. **PF-6 — `upcoming` events + hold requests.**

PF-2 and PF-3 deliver most of the value and need **no** structure analysis, no
AI DJ, and no model. They should not wait on any of it.

---

## 8. Resolved

**Republish rate — static timeline, cheap clock, shared helper.** Publishing a
whole timeline often, only to chase varispeed drift, would be wasteful for
data that is *static in track time*. Instead, three rates:

| what | when | cost |
|---|---|---|
| `timeline` | once per track load | rare, arbitrarily rich |
| `clock` — track position, rate, wall-time | a few Hz | three floats |
| events (transition scheduled, manual/unexpected action) | **immediately** | rare |

Consumers convert track time to room time through a **core-provided helper**,
so the "no consumer does pitch math" rule holds without the producer having to
re-send the future every frame. Since the future is known, the only thing that
needs to be timely is *change* — hence events push at once.

**Priority vs. blend — the mixer publishes one merged view.** It owns the
crossfader position and both decks, so it resolves the blend itself rather than
teaching the hub about blends. Both decks' timelines are included, the live one
flagged, along with where the mix is heading.

## 9. Open questions

- None outstanding. Producers and phases are specified; PF-1 can start.
