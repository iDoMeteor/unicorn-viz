# Auto VJ — Phrase-Aware Song Structure Plan

Owner: unicorn-viz maintainers (auto-vj-01) + dj-mixer-01 team (§6 review)
Status: draft — design agreed with owner; §6 (Mixer Integration) pending
  dj-mixer-01 team review before implementation starts
Last updated: 2026-08-05

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
flourish = (
    _drop_cycle_count >= phrase_peak_flourish_min_cycle   # default 2
    and preceding BREAKDOWN/BUILD lasted a real number of bars
        (guards against a fizzle-retry counting as "real setup")
)
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

Open question (owner still deciding, §8): should `PEAK` carry an optional
tier/rank ("is this the major peak") supplied by an external detector that
has pre-analyzed the full track, rather than always inferring it from our
own live `_drop_cycle_count`? Defaults to the inferred value when a source
doesn't supply one either way -- this is additive, not a blocking decision.

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

## 6. Mixer integration (Phase 2 -- for dj-mixer-01 team review)

dj-mixer-01 will gain its own phrase/section detector, more authoritative
than anything derivable from live audio alone (pre-analyzed against the
full file, not inferred incrementally). Two integration decisions, agreed
with the owner 2026-08-05:

1. **New hint-bus channel, symmetric to the existing BPM bus.** Mirrors
   `vj_api.publish_bpm()`/`get_bpm()` (5s TTL, `app.py:_bpm_hints`): a new
   `publish_section(source, role, ...)` / `get_section(exclude=...)`. When a
   fresh mixer hint exists, the director treats it as ground truth for
   *which phrase role we're in*, the same way P0-B (BPM audit fixes,
   2026-08-04) treats a fresh mixer BPM as ground truth for tempo. The
   director keeps counting bars itself for *how long we've been in that
   role* -- the label disambiguates the phrase clock, it doesn't replace it.
2. **Canonical neutral vocabulary is the wire contract.** The mixer may
   detect and *display* genre-appropriate labels (EDM intro/build/drop/
   breakdown/outro, or pop intro/verse/chorus/bridge/outro, or both selected
   by genre) but must publish into the `HOLD`/`RISE`/`PEAK`/`FALL`/`CLOSE`
   vocabulary from §4.4 on the bus. This is the artifact for the mixer team
   to review -- the mapping table needs to hold for whatever genre-specific
   detection they build, not just the EDM case this plan was designed
   against.

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

## 7. Validation plan

Sequence-corpus rows already record `bpm`/`beat_index`/`mode` per row
(`_build_live_training_row()`, training-kit-01). Once bar-counting lands,
`_bars_since_phase_entry`/`_drop_cycle_count` can be reconstructed
retrospectively from existing corpus data to check whether the §5 starting
bar-length defaults actually match real sessions, before spending a live
tuning pass on them -- same validation path used for every other threshold
in this file's history (see `docs/adr/vj-system.md`).

## 8. Open questions

- Should the neutral vocabulary (§4.4) wait for the mixer team's actual
  label set rather than being fixed here first? Owner is still deciding
  whether the mixer will emit genre-specific labels only, dual-mode, or
  send/receive neutral directly.
- Should `PEAK` carry an optional major/minor tier from an external source
  (§4.4), or stay purely locally inferred from `_drop_cycle_count`?
- Does `HOLD` need to distinguish a true intro (never had a peak yet) from a
  mid-song verse (between peaks) for anything beyond the position/cycle bias
  term already handling that implicitly? No known need yet -- flagging in
  case the mixer's detector ends up distinguishing them and it turns out to
  matter for visual treatment.
- The old archived plan's "Optionally add a `RECOVERY` micro-state if
  `CLIMAX -> CRUISE` feels abrupt" (§ Near-Term Next Steps) was never
  picked up. Worth revisiting once `CLIMAX` is demoted to a rarer event --
  an abrupt drop back to `CRUISE`/`HOLD` after a true set-defining peak may
  read worse than it did when `CLIMAX` fired every cycle.

## 9. Staging

- **Phase 1** (deliverable now, self-contained in auto-vj-01): phrase clock
  (§4.1), phrase-bias mechanism (§4.2), `IMPACT` fold-in + `CLIMAX` demotion
  (§4.3), hard-cut neutral-bias mitigation (§6.1 Phase 1), config surface
  (§5), corpus-based validation (§7).
- **Phase 2** (blocked on dj-mixer-01's section detector): hint-bus channel
  + canonical vocabulary contract (§6), hard-cut authoritative resolution
  (§6.1 Phase 2).
