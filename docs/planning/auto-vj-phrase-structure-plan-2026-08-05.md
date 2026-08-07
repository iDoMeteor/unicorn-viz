# Auto VJ — Phrase-Aware Song Structure Plan

Owner: unicorn-viz maintainers (auto-vj-01) + dj-mixer-01 team (§6 review)
Status: Phase 1 implemented (2026-08-05, auto-vj-01 1.0.0-rc.8). Phase 2's
  bus channel + auto-vj-01 consumer side implemented (2026-08-05, core +
  auto-vj-01 1.0.0-rc.11) — see [docs/adr/vj-system.md § "Phrase-Aware
  Director: Bar-Relative Bias + IMPACT Fold-In"](../adr/vj-system.md#phrase-aware-director-bar-relative-bias--impact-fold-in-2026-08-05)
  for both records and `tests/test_auto_vj_phrase_structure.py` /
  `tests/test_section_bus.py` for regression coverage. The **mixer
  publisher side is now implemented too** (2026-08-05, dj-mixer-01
  0.145.0): `structure.wire_for()` returns `next_role`/`next_tier`/
  `next_label`/`bars_to_next` per §6.b, and the controller publishes for
  the live deck every frame via `vj_api.publish_section()`. **The
  director's own "arm a transition ahead of the next role" behaviour is
  now implemented too** (2026-08-06, auto-vj-01 1.0.0-rc.20) -- `_phrase_
  bias()` reads `next_role`/`bars_to_next`, so §6.b's payload is fully
  consumed end to end. Since 2026-08-06 the mixer's sections are also
  **hand-editable** and corrections republish mid-track (§6.e) -- no wire
  change, and the consumer was verified clear of the one staleness hazard
  it raised, so nothing is outstanding on that amendment either. A
  **second, separate bus channel** landed the same day (§6.3): `publish_
  session()`/`get_session()` for set-level clock/grand-finale timing,
  mirroring the section bus exactly. Mixer side (dj-mixer-01 0.152.0)
  was already written and guarded; the core channel now exists too.
  **The auto-vj-01 consumer side of §6.3 is now implemented too**
  (2026-08-06, auto-vj-01 1.0.0-rc.21) -- `_check_timed_finale()` reads
  `get_session()` via `_get_session_hint()` and prefers `final_peak_in_s`
  (fires 43s ahead, matching grand-finale-01's own buildup length) over
  `seconds_left` over the original wall-clock estimate. §6.3 is fully
  consumed end to end; nothing outstanding on this plan.
Last updated: 2026-08-06

## 1. Objective

Give the Auto VJ director *expectations* about typical song/phrase structure
(intro, build, chorus/drop, breakdown, outro; typical phrase lengths) instead
of reacting to audio energy frame-to-frame with no sense of where in a song
it plausibly is. Not a rigid script — a set of soft priors that make expected
transitions easier to fire and unexpected ones require stronger evidence,
while still degrading gracefully to today's audio-only behavior when no
track position is knowable at all (live stream, no metadata).

## 2. Problem statement

The director (`drop-ins/auto-vj-01/auto_vj.py`) currently has no structural
model of a song. Every transition (`CRUISE -> BUILD -> DROP -> IMPACT ->
CLIMAX -> CRUISE`, with `BREAKDOWN` as a side branch) is driven purely by
audio energy slope, `drop_score`, downbeat confidence, and wall-clock/BPM-
scaled timers (`_timing_scale_from_bpm()`). The one exception --
`_current_song_progress()` gating `CLIMAX` entry behind 50% of a known
track's duration -- is coarse (a single floor, one checkpoint) and was
itself silently inert for non-Spotify sources until the `_spotify_snapshot()`
fix landed earlier this session (2026-08-04, now source-agnostic via
`vj_api.active_now_playing()`).

This surfaced from a concrete incident (director entered `CLIMAX` ~1/4 into
a track) but the owner's actual concern is broader: the director "jumps
around trying to guess scenes so often and guessing incorrectly" because it
has no expectation of what phase of a song it's probably in or what usually
happens next -- not just a missing climax-timing floor.

## 3. Prior art

`docs/planning/auto-vj-breakdown-impact-climax-plan.md` (status: archive,
2026-06-18) is the design that introduced `BREAKDOWN`/`IMPACT`/`CLIMAX` as
explicit states. It explicitly favored "deterministic state transitions over
opaque ML-style guessing" -- a principle this plan keeps (see §4.2: bias, not
inference). What it didn't have: any notion of phrase length or song
position: the `DROP -> IMPACT` transition was justified purely by
`drop_score` crossing a threshold after a short delay, with no sense of
whether that delay/threshold made sense for *where in the track* the drop
was happening. A 2026-06-28 follow-up (comment-only, no doc, see
`auto_vj.py:122-125` / `:242-246` / `:365-369`) pushed `IMPACT` later ("not
the drop hit, a gateway to CLIMAX") but kept the same structural gap: no
song-position awareness, just a longer delay before the same threshold
check.

This plan is *not* an amendment to that doc -- it changes the fundamental
model (bar-relative phrase clock + soft bias instead of pure wall-clock
thresholds) and removes a state (`IMPACT`) that plan introduced.

## 4. Design

### 4.1 Phrase clock (bar-relative counters)

Three new counters on `AutoVJController`, all driven purely by the beat
tracker's own `is_downbeat` firing (`beat_grid.py`) -- no new detection
needed, and no dependency on track metadata:

- `_bars_since_track_start` -- increments every downbeat; resets on a
  now-playing track-identity change (via the source-agnostic
  `_spotify_snapshot()` / `active_now_playing()` path). For an identity-less
  live source it never resets -- it becomes a running "how long has this set
  been going" counter, which is still meaningful for phrase-length
  reasoning even without track boundaries.
- `_bars_since_phase_entry` -- increments every downbeat; resets on every
  director state transition. Bar-denominated replacement for today's
  `elapsed_build` / `elapsed` wall-clock locals.
- `_drop_cycle_count` -- increments each time `DROP` is entered; resets with
  `_bars_since_track_start`. "Which drop is this" -- the signal that lets a
  second/later drop be treated as more climax-eligible than a first one,
  independent of whether track duration is known.

### 4.2 Phrase-bias mechanism: soft, not a gate

Every existing transition already compares a score against a threshold
(`drop_score >= drop_energy_threshold`, `score >= climax_entry_score`,
etc.). A new `_phrase_bias(target_role) -> float`, roughly bounded to
`[-phrase_bias_max, +phrase_bias_max]` (default `phrase_bias_max = 0.15`),
is computed each tick from three additive terms and applied as
`effective_threshold = base_threshold - phrase_bias`:

- **Phase-duration term** -- `_bars_since_phase_entry` vs. that phrase
  role's expected bar range (new per-profile config, §5). Below the expected
  minimum -> negative bias (discourage an early transition, replacing hard
  min-hold cliffs). At/past the expected maximum -> growing positive bias,
  replacing today's hard timeout cliff with something continuous.
- **Phrase-boundary term** -- small bonus when `_bars_since_phase_entry`
  lands near a musically natural boundary (`phrase_boundary_bar_unit`,
  default 4 or 8), extending today's "wait for the next downbeat" precision
  to "prefer the next 4/8-bar boundary" for the big transitions (entering
  `DROP`, entering `BREAKDOWN`).
- **Position/cycle term** -- from `_drop_cycle_count` (cycle 1 = neutral on
  the flourish/major-peak; cycle 2+ = positive bias toward it) and, only
  when track duration is known, `song_progress` (early track = negative bias
  on peaks / positive on rise; late track, past `phrase_outro_song_progress`
  = negative bias on everything except returning to `HOLD`/`CLOSE`).

This is deliberately an extension of a pattern already in the codebase
(`_timing_scale_from_bpm()` modulates *durations* by tempo; `_phrase_bias`
modulates *thresholds* by song position) rather than a new paradigm. A track
that doesn't follow the expected shape still gets through on strong evidence
-- it just needs more of it than a track doing the expected thing at the
expected time. This is what keeps the model "not super rigid" per the
owner's own framing.

### 4.3 State machine changes

**`IMPACT` is removed as a state.** Its one legitimate idea -- a later drop
should hit harder than the first -- is folded directly into `DROP` as an
entry-time flourish flag, computed once when `DROP` is entered:

```
peak_tier = (
    external_tier                                          # from the mixer
    if external_tier is not None else
    'major' if (
        _drop_cycle_count >= phrase_peak_flourish_min_cycle   # default 2
        and preceding BREAKDOWN/BUILD lasted a real number of bars
            (guards against a fizzle-retry counting as "real setup")
    ) else 'minor'
)
flourish = (peak_tier == 'major')
```

When `flourish` is true, `DROP`'s first ~2 bars get what `IMPACT` used to do
(max reactivity, biggest post-fx slot, `impact_effect_tags`/burst stack),
then it settles into normal `DROP` behavior for the rest of the phrase. This
directly reflects the owner's revised theory (agreed 2026-08-05): the impact
*is* the arrival of a later drop, not something earned mid-groove.

**`CLIMAX` is demoted, not removed.** Its role changes from "the thing every
`DROP` tries to escalate into" to something rarer: reserved for the
genuinely final/biggest moment of a set (last drop cycle before an expected
`CLOSE`, or overwhelming evidence regardless of position -- generalizing
today's `climax_early_override_score` escape hatch). `climax_min_song_progress`
/ `climax_early_override_score` need to be re-examined under this new
meaning as part of implementation, not just left as-is with new keys layered
on top.

Net state count: `CRUISE / BUILD / DROP / CLIMAX / BREAKDOWN` -- five states,
each corresponding to a real structural role, instead of six with one
(`IMPACT`) that was a scripted visual flourish wearing a state's clothing.

### 4.4 Genre-neutral phrase vocabulary

Internal director state names stay EDM-flavored (existing code, existing
tuning history). A separate, genre-neutral vocabulary is used wherever a
phrase *role* needs to be communicated externally (the mixer hint bus, §6)
or reasoned about independent of genre convention:

| Internal state | Neutral role | EDM-style label | Pop-style label |
|---|---|---|---|
| `CRUISE` (no prior peak / between peaks) | `HOLD` | intro | intro / verse |
| `BUILD` | `RISE` | build | pre-chorus |
| `DROP` (any cycle) | `PEAK` | drop | chorus |
| `BREAKDOWN` | `FALL` | breakdown | bridge |
| `CRUISE` (after the final peak) | `CLOSE` | outro | outro |

`PEAK` carries an optional `minor`/`major` tier (decided 2026-08-05, §8) --
`major` drives the entry flourish (§4.3). Locally inferred from
`_drop_cycle_count` by default; an external detector that has pre-analyzed
the full track (the future mixer integration, §6) may supply the tier
directly, overriding the local inference for that occurrence.

This table reads as one-to-one; the mixer's side of it is **many-to-one**.
Its display vocabulary is a superset that collapses onto these five roles --
notably an *intro* and a mid-track *groove* or *verse* are both `HOLD`. See
§6.d for the full mapping and why the distinction is worth drawing on screen
but not on the wire.

### 4.5 Degradation without metadata

This is the property that matters most for a live stream / no-metadata
source, and it falls out of the design rather than needing special-casing:

- Bar counting, `_drop_cycle_count`, the phase-duration and phrase-boundary
  bias terms all need only a locked beat tracker -- available identically
  for Spotify, mixer, media, or a raw mic feed.
- Only the `song_progress`-derived term (early-track caution, `CLOSE`
  suppression) requires known duration. When unavailable, that term is
  simply omitted from `_phrase_bias` -- behavior falls back to "reasonable
  expectations about phrase length and drop sequencing" with no notion of
  "how far through the whole track," which is the honest thing to do since
  that's genuinely unknowable there.

## 5. New config surface

Mirrors the existing per-profile dict shape (`chill`/`normie`/`raver`,
`auto_vj.py:90-400`) -- bar-denominated instead of second-denominated:

| Key | Meaning | Starting default (normie) |
|---|---|---|
| `phrase_hold_expected_min_bars` / `_max_bars` | `HOLD` phrase length | 8 / 24 |
| `phrase_rise_expected_min_bars` / `_max_bars` | `RISE` phrase length | 8 / 16 |
| `phrase_peak_expected_min_bars` / `_max_bars` | `PEAK` phrase length | 16 / 32 |
| `phrase_fall_expected_min_bars` / `_max_bars` | `FALL` phrase length | 8 / 16 |
| `phrase_boundary_bar_unit` | preferred transition-alignment granularity | 8 |
| `phrase_bias_max` | cap on `_phrase_bias` magnitude | 0.15 |
| `phrase_peak_flourish_min_cycle` | first `_drop_cycle_count` to get the flourish | 2 |
| `phrase_outro_song_progress` | `song_progress` beyond which `CLOSE` suppression applies | 0.85 |

**These starting values are placeholders from general dance-music structure
convention, not derived from real session data** -- same caveat as every
other threshold in this file's tuning history. The `~7-8 bar` figures in the
old `IMPACT`-era comments (`auto_vj.py:122-125` etc., e.g. "DROP runs for ~8
bars at 90 BPM") were reasoning about "before any escalation," not "the
whole chorus," so `phrase_peak_expected_max_bars` is deliberately wider here
(16-32) to match how long a real chorus/drop section actually runs.

## 6. Mixer integration (Phase 2 -- reviewed, contract agreed)

**Review status: complete (dj-mixer-01 team, 2026-08-05).** The detector
exists -- `drop-ins/dj-mixer-01/structure.py`, shipped as groundwork with 18
tests -- and segments real library tracks into labelled sections in 0.4-1.0 s
per track during analysis. The §4.4 vocabulary survived contact with it
unchanged. Four amendments were requested against the draft contract below
and **all four were accepted by the owner (2026-08-05)**; they are folded in.

dj-mixer-01's detector is more authoritative than anything derivable from
live audio alone because it is pre-analyzed against the complete file rather
than inferred incrementally. Concretely, it knows three things the director
structurally cannot: which peak is the *biggest* (so which is `major`), that
a given peak was the *last* one (so `CLOSE` is knowable at all), and how many
bars the current section has *left*.

1. **New hint-bus channel, symmetric to the existing BPM bus.** Mirrors
   `vj_api.publish_bpm()`/`get_bpm()` (5s TTL, `app.py:_bpm_hints`): a new
   `publish_section(source, ...)` / `get_section(exclude=...)`.
2. **Canonical neutral vocabulary is the wire contract.** The mixer detects
   and *displays* genre-appropriate labels but publishes only the
   `HOLD`/`RISE`/`PEAK`/`FALL`/`CLOSE` vocabulary from §4.4.

### 6.e Sections are hand-editable, so hints can change mid-track (2026-08-06)

Landed after the consumer side was written, so it is called out here rather
than assumed: as of **dj-mixer-01 0.149.0** the DJ can correct the detected
structure directly on the waveform strip -- drag a boundary, retype a block,
merge, split, or reset the track to the detector's version. Corrections are
persisted and **republished immediately**, so the director sees the new shape
without waiting for a track change.

**What this is worth to the director.** The hints get *better*, and a
correction is a person's answer rather than a threshold's: an edited section
publishes `confidence: 1.0`, which under §6.c means the external bias term
applies at full strength. Hand-fixed structure should move the director harder
than detected structure, and it now does, with no change needed on the
consumer side.

**The one thing to check -- checked, and clear (auto-vj-01 team +
dj-mixer-01, 2026-08-06).** `role`/`tier`/`bars_in` for a given playhead
position are no longer guaranteed stable across a track: a boundary dragged at
02:30 changes what the hint says about 02:45, so anything cached per-track
rather than per-hint could go stale mid-track. The mixer's own publisher
needed exactly that fix (it cached the rehydrated rows and had to be told to
drop them). **The consumer does not have the equivalent problem:**
`_get_section_hint()` calls `vj_api.get_section()` on every read and holds
nothing between ticks, and all three of its call sites go through it. No
change was required on either side.

**Not a wire change.** The payload shape from §6.a/§6.b is unchanged; only how
often the values can move. `manual` is deliberately *not* on the wire: whether
a person placed a boundary is provenance the mixer needs for re-analysis and
the director does not need at all -- it already gets the part that matters, as
full confidence.

### 6.a Payload carries extent, not just a role (amendment 1)

The draft had the mixer publish which role we are in and the director keep
counting bars itself. That discards the reason for asking the mixer at all:
having analyzed the whole file we can say how far *into* the section the
playhead is and how many bars remain, which a live listener can never know.
The payload (`structure.to_wire()`) is:

```python
{'role': 'PEAK', 'tier': 'major', 'label': 'drop',
 'bars_in': 12.0, 'bars_left': 20.0, 'confidence': 0.72}
```

`label` is advisory -- for logs and operator-facing display. The director
must key only off `role`/`tier`, so a new display label can never change
director behaviour.

### 6.b Publish the *next* role too (amendment 2)

The mixer also publishes what comes after the current section and how far
away it is. This is the amendment with the most reach: it lets the director
**arm** a transition rather than react to one, which goes at the root of the
§2 complaint that the director "jumps around trying to guess scenes." For
mixer-sourced audio it does not have to guess -- an 8-bar build into a known
`PEAK` can be prepared on bar 1 instead of recognised on bar 6.

Shipped as `next_role`, `next_tier`, `next_label` and `bars_to_next`
(dj-mixer-01 0.145.0).  They are **omitted entirely on the final section**
rather than sent as nulls, so a consumer can read "absent" as "nothing known
about what follows" without distinguishing that from "explicitly nothing
follows".  `bars_to_next` equals the current section's `bars_left` -- stated
separately because a consumer arming a transition reasons about "how long
until the next thing", not "how long is this thing".

### 6.c Confidence is on the wire and scales the bias (amendment 3)

The draft had the director treat a fresh mixer hint as ground truth, by
analogy with P0-B's treatment of mixer BPM. That is right for a confident
hint and wrong for a shrug: per-section confidence runs roughly 0.50-0.99 on
real tracks, and a 0.53 section should not move the director as hard as a
0.95 one. `_phrase_bias` scales its external term by the published
confidence rather than switching on presence alone.

### 6.d The vocabulary mapping is many-to-one (amendment 4)

§4.4's table reads as 1:1. The mixer's display set is deliberately a
**superset** that collapses onto those five roles:

| Display label | Wire role | Note |
|---|---|---|
| intro | `HOLD` | the *first* hold only |
| groove / verse | `HOLD` | every later hold |
| build / pre-chorus | `RISE` | |
| drop / chorus | `PEAK` | carries `minor`/`major` |
| breakdown / bridge | `FALL` | |
| outro | `CLOSE` | |

Intro and groove are the same role to a lighting decision and emphatically
not the same thing to a DJ, since only one of them is where you mix in. A
strip that wrote "intro" across the middle of a track would be lying about
the thing it is most used for. This closes the §8 open question about the
`HOLD`/verse distinction from the mixer side: the five roles are right, and
display carries the distinction instead of the wire.

A test in dj-mixer-01 (`test_every_display_label_maps_to_a_wire_role`) fails
if any display label lacks a mapping, so a label added later cannot become a
section the director silently drops. It caught exactly that during
development.

### 6.1 Known edge case: hard deck cuts

Raised by the owner 2026-08-05: DJ is in deck A's `FALL`, expecting deck A's
big second `PEAK`; hard-cuts to deck B, already mid-drop, on another deck.

**What breaks:** `track_id`/`change_counter` (dj-mixer-01, added in the
2026-08-04 corpus-capture fix) flip the instant deck B becomes loudest,
correctly triggering today's track-change reset -- but that reset zeroes
`_drop_cycle_count`/`_bars_since_track_start`, which is *wrong* here: deck B
isn't starting from bar zero, it may already be in its own biggest drop. The
phrase-bias model would, for a moment, work against reality -- treating a
real second-drop moment as unearned.

**What self-corrects:** because bias is additive, not gating (§4.2), a real
drop happening right now produces strong raw evidence (`drop_score`/energy/
kick regularity) regardless of stale counters -- the `DROP` transition
itself should still fire, just without the flourish/major-peak treatment it
deserves for a few bars.

**Mitigations, staged:**

- **Phase 1 (auto-vj-01 alone, no mixer dependency):** detect a hard
  deck-switch (dj-mixer-01 already tracks per-deck level for "loudest
  deck") and, for a few bars after one, hold `_phrase_bias` near-neutral
  instead of applying the (stale, likely wrong) historical bias -- withhold
  judgment rather than actively penalize.
- **Phase 2 (needs the mixer detector, §6):** since the mixer can
  pre-analyze a file offline, it can supply the *correct* phrase role and
  tier for deck B's current playhead position instantly on the cut --
  something the director can only ever reconstruct incrementally, live.
  This is one of the strongest concrete cases for why §6 matters beyond
  "nicer than guessing."

**Resolved by amendment 6.a (dj-mixer-01 review, 2026-08-05).** With
`bars_in` on the wire this stops being a mitigation and becomes a fix: on
the cut the mixer publishes deck B's real role, tier *and* position, so the
director sets its phrase clock from the hint instead of counting up from a
zero that was never true. The Phase 1 near-neutral hold stays as the
fallback for a source with no mixer hint -- a bare stream, or the mixer
absent entirely -- rather than as the answer.

### 6.2 Which deck publishes during a blend (open)

Two decks playing means two different sections, and the bus carries one
value. The mixer already had to answer this for its browser row colours,
where it settled on auto-play's live deck while that is driving and
otherwise the loudest with a 1.4x hysteresis margin -- the same definition
publishes here so "live" means one thing across the app.  **Settled in code
(2026-08-05):** that answer moved out of the UI onto `MixerEngine.
live_deck_key(exclude=, prefer=)`, a public surface both callers share.  It
carries hysteresis state that cannot be recomputed independently without the
two drifting apart, which is exactly the failure the browser colours already
had once.

What is genuinely undecided is whether that is the *right* answer for
visuals during a long blend. For thirty seconds of crossfade the room is
hearing both, and the lights arguably want to follow where the mix is
*going* rather than where it has been -- which would argue for publishing
the incoming deck once the crossfader passes some point, or for publishing
both and letting the director weigh them. Deferred until the bus exists and
we can watch it against a real transition.

## 6.3 Set clock and the grand finale (dj-mixer-01 -> director, 2026-08-06)

**Bus channel shipped (2026-08-06, core).** `publish_session()`/
`get_session()` now exist on `App`/`VjApi`, mirroring `publish_section()`
exactly (same 5 s TTL, same deep-copy on both sides, same
degrade-to-no-op on an older core). The mixer side was already written
and guarded -- it calls `publish_session` only when the attribute exists
(dj-mixer-01 0.152.0) -- so it lit up with no further coordination
needed. See `docs/adr/vj-system.md` § "Set-Clock Hint Bus:
`publish_session()`/`get_session()`".

**Consumer side shipped too (2026-08-06, auto-vj-01 1.0.0-rc.21).**
`_check_timed_finale()` reads `get_session()` via a new
`_get_session_hint()` helper and prefers, in order: `final_peak_in_s`
(fires `_finale_peak_lead_s` = 43s ahead of the analysed drop, matching
grand-finale-01's own documented buildup length so the finale sequence's
own climax lands with the music's), then `seconds_left` (the mixer's
set-end estimate, same `_finale_lead_s` = 45s lead as before), then the
original `state.session_remaining_s` wall-clock estimate when no mixer
hint exists at all. See `docs/adr/vj-system.md` § "Grand-Finale Trigger
Consumes the Set-Clock Hint" and `tests/test_auto_vj_timed_finale.py`.
§6.3 is now fully consumed end to end.

**Original ask, for reference:** a `publish_session()` /
`get_session()` pair on `vj_api`, mirroring `publish_section()` exactly (same
5 s TTL, same deep-copy on both sides, same degrade-to-no-op on an older core).
The mixer side is already written and guarded -- it calls `publish_session` only
when the attribute exists, so shipping the channel lights it up with no further
change here (dj-mixer-01 0.152.0).

### Why the director wants this

Song sections say where you are in a *track*.  This says where you are in the
*night*, which is the other half of the same question and the one the finale
depends on.  Coordinating a grand finale by shouting across a room is how it
usually goes wrong; the mixer knows when the set ends and the director does
not.

### Payload

```python
{
  'phase': 'running' | 'closing' | 'final' | 'over',
  'source': 'clock' | 'last_track',
  'seconds_left': 240.0,          # best estimate until the set ends
  'minutes_left': 4.0,
  # present when a set length is configured:
  'elapsed_s': 5400.0, 'total_s': 7200.0, 'progress': 0.75, 'remaining_s': 1800.0,
  # present when phase == 'final':
  'track_total_s': 420.0,         # how long the last song is
  'track_remaining_s': 240.0,     # ...and how much of it is left
  'final_peak_s': 300.0,          # where its biggest drop starts, if analysed
  'final_peak_in_s': 120.0,       # ...counting from now
  # context, when a list is playing:
  'track_index': 9, 'track_total': 10, 'list_name': 'Friday Peak',
  'endless': False,
}
```

### The two signals, and why both

* **`source: 'last_track'`** -- the last track of the playing list has started.
  Exact, and the strongest finale cue available.  **Unavailable under shuffle
  or loop**, where the list genuinely has no last track; claiming a finale
  followed by four more tunes is worse than claiming none, so those cases fall
  back to the clock.  Note that **loop defaults ON** in dj-mixer-01, so in a
  default setup this signal never fires -- the DJ turns ∞ off for a set with a
  planned ending.
* **`source: 'clock'`** -- a configured set length, counted from the first
  audio (not from when the mixer opened).  Works regardless of shuffle or loop,
  but only if the operator set one.

`last_track` wins when both apply: the list knowing its own end beats an
estimate, including a clock that still thinks there is an hour to go.

### `final_peak_s` is the interesting one

A director told only *"three minutes left"* still has to guess when to fire,
and the guess is usually wrong because the tune's own biggest drop is not in
the middle of what remains.  We already analysed the file, so we can say
exactly when it lands -- the `major`-tier peak from §6's structure data, or the
last peak of any tier if no major one is ahead of the playhead.  Firing the
finale *on* that drop rather than on a timer is the whole point of the field.
Absent when the last track has never been analysed, so treat it as a bonus and
not a precondition.

### Suggested consumer behaviour (not prescriptive)

`closing` is the cue to stop opening new material and start converging;
`final` with `final_peak_in_s` is the cue to schedule the biggest moment of
the night at that offset.  `over` means the target passed and the set is
running long -- probably a reason to hold, not to escalate again.

## 7. Validation plan

Sequence-corpus rows already record `bpm`/`beat_index`/`mode` per row
(`_build_live_training_row()`, training-kit-01). Once bar-counting lands,
`_bars_since_phase_entry`/`_drop_cycle_count` can be reconstructed
retrospectively from existing corpus data to check whether the §5 starting
bar-length defaults actually match real sessions, before spending a live
tuning pass on them -- same validation path used for every other threshold
in this file's history (see `docs/adr/vj-system.md`).

## 8. Decided / open questions

**Decided (owner, 2026-08-05):**

- **`PEAK` tiering: adopted.** `PEAK` carries an optional tier (`minor` /
  `major`) alongside the neutral role. Locally, `_drop_cycle_count >=
  phrase_peak_flourish_min_cycle` infers `major` (this is what drives the
  flourish, §4.3); an external source (the future mixer detector, §6) may
  supply the tier directly, which then overrides the local inference for
  that `PEAK`. Wire format: `(role='PEAK', tier='major'|'minor'|None)` --
  `None` means "use local inference," not "definitely minor."
- **`HOLD`/verse distinction: not pursuing.** No dedicated mechanism to
  distinguish a true intro from a mid-song verse beyond what the
  position/cycle bias terms already do implicitly. Left as a listed
  possibility below only in case the mixer's detector ends up drawing that
  line anyway and it turns out to matter for visual treatment -- not
  something to build toward now.

- **Mixer integration amendments: all four adopted (owner, 2026-08-05).**
  The payload carries extent rather than a bare role (§6.a); the mixer also
  publishes the *next* role and its distance (§6.b); confidence rides the
  wire and scales the director's external bias term rather than gating on
  presence (§6.c); and the label->role mapping is many-to-one, with display
  carrying distinctions the wire does not (§6.d).
- **Neutral vocabulary (§4.4): fixed as drafted -- closed.** It did not need
  to wait for the mixer's label set. The detector was built against these
  five roles and they held; the mixer emits genre-specific labels for
  display and publishes neutral roles on the bus, which was option three of
  the three the owner was weighing.

**Still open:**

- Which deck publishes during a long blend (§6.2). The live-deck definition
  is settled; whether visuals should follow the *incoming* deck mid-crossfade
  is not.
- (Not pursuing, see above) Does `HOLD` need to distinguish a true intro
  from a mid-song verse for anything beyond the position/cycle bias term?
- The old archived plan's "Optionally add a `RECOVERY` micro-state if
  `CLIMAX -> CRUISE` feels abrupt" (§ Near-Term Next Steps) was never
  picked up. Worth revisiting once `CLIMAX` is demoted to a rarer event --
  an abrupt drop back to `CRUISE`/`HOLD` after a true set-defining peak may
  read worse than it did when `CLIMAX` fired every cycle.

## 9. Staging

- **Phase 1 — done (2026-08-05, auto-vj-01 1.0.0-rc.8):** phrase clock
  (§4.1), phrase-bias mechanism (§4.2), `IMPACT` fold-in + `CLIMAX` demotion
  (§4.3), hard-cut neutral-bias mitigation (§6.1 Phase 1), config surface
  (§5). Not yet done: corpus-based validation of the starting bar-length
  defaults (§7) -- shipped as-is, pending a real-session tuning pass the
  way every other threshold in this file has gone through.
- **Phase 2 — bus channel + consumer side done (2026-08-05, core + auto-vj-01
  1.0.0-rc.11):** `App.publish_section()`/`get_section()` (mirrors the BPM
  bus exactly, 5s TTL, `_SECTION_ROLES` validates against the canonical
  five) and the matching `VjApi` wrappers; `_infer_peak_tier()` accepts a
  confident external tier override (`phrase_external_tier_min_confidence`,
  default 0.6); `_phrase_bias()` gains a confidence-scaled external term
  per §6.c; `_maybe_sync_phrase_clock_from_section_hint()` resolves the
  hard-cut edge case per §6.1's "Resolved by amendment 6.a" -- during the
  post-track-change neutral window, a fresh hint sets `bars_in`/tier from
  real data instead of waiting the window out blind.
- **Phase 2 — mixer publisher done (2026-08-05, dj-mixer-01 0.145.0):**
  `structure.wire_for()` builds the payload including §6.b's next-role
  fields, and `DjMixerController._publish_section()` publishes it each
  frame for the live deck. "Live" is now `MixerEngine.live_deck_key()`, a
  public surface the browser's mix colours and the hint share, so §6.2's
  answer cannot drift between the two. Verified end to end against the
  real `App.publish_section()`/`get_section()`: every role the detector
  emits survives the core's canonical-role validation.
  **Remaining (closed 2026-08-06, see below):** §6.b's *consumer* half --
  the director arming a transition on `next_role`/`bars_to_next` rather
  than only reacting. The fields were on the wire and json-safe from the
  start; nothing read them until now.
- **Phase 2 — external-hint bias proximity fix (2026-08-06, auto-vj-01
  1.0.0-rc.15):** live use turned up a real bug in the §6.c bias term --
  it used `role`+`confidence` only, so a confident match right at the
  *start* of a phase (e.g. BUILD) escalated the DROP threshold just as
  hard as one right before the actual drop. Now gated by `bars_left`
  proximity (new `phrase_external_proximity_bars`). This uses `bars_left`
  (already consumed since §6.a), not (at the time) the still-unread
  `next_role`/`bars_to_next` from §6.b above. See
  `docs/adr/vj-system.md` § "External Section-Hint Bias Gated by
  `bars_left` Proximity".
- **Phase 2 — §6.b consumer half done (2026-08-06, auto-vj-01
  1.0.0-rc.20):** `_phrase_bias()` now reads `next_role`/`bars_to_next`
  too, arming a transition ahead of time instead of only reacting once
  the role has arrived -- the piece that most directly answers this
  plan's original §2 complaint. Owner had assumed this already shipped;
  it hadn't. See `docs/adr/vj-system.md` § "Director Arms Ahead of
  `next_role`; Detector's Primed-Confidence Floor".
