# Auto VJ Director — Scene Detection Audit

Owner: Drop-in Maintainers (auto-vj-01)
Status: active
Last updated: 2026-08-09

This audits the director's scene/mode detection system in `drop-ins/auto-vj-01/auto_vj.py`
(`_update_director()` and the state-entry/exit methods it calls) plus the one
detector-side input it depends on (`drop_score`, computed in `beat_grid.py`).
Companion to the same-day recommender audit — see `docs/adr/vj-system.md`
§§ "Top-3-Weights Rewire", "Per-Profile `zcr_sigma`/`onset_density_sigma`",
and the pre-existing `weights-and-thresholds.md` Director section, which
this audit supersedes as the deeper reference for scene detection
specifically (that doc stays the canonical *constant value* reference;
this one explains the *mechanism* and adds judgment calls this project's
audits are meant to carry: recommendations, oddities, confidence).

---

## 1. The two-layer model

The director actually runs two distinct state concepts that are easy to
conflate because they share vocabulary:

| Layer | Vocabulary | What it represents | Where it lives |
| --- | --- | --- | --- |
| **VJ mode** | `CRUISE`, `BUILD`, `BREAKDOWN`, `DROP`, `IMPACT`, `CLIMAX` | What the visualizer is *doing right now* — which effect-swap/postfx behavior is active. This is what `_update_director()`'s state machine transitions between. | `self._mode`, driven by live audio (`drop_score`, `energy_slope`, `kick_regularity`) |
| **Phrase role** | `HOLD`, `RISE`, `PEAK`, `FALL`, `CLOSE` | Where the track is in its *musical structure* — a coarser, slower-moving classification used only to bias how easily a VJ-mode transition happens, never to drive one directly. | `_phrase_bias(role)`, informed by bar-counting plus the mixer's external section hint |

**Why two layers, not one:** `HOLD`/`RISE`/`PEAK`/`FALL`/`CLOSE` map roughly
to `CRUISE`/`BUILD`/`DROP`+`IMPACT`+`CLIMAX`/`BREAKDOWN`/(end of track) but
not 1:1 — a track can sit in a long musical `RISE` while the VJ mode
oscillates between `CRUISE` and a false-start `BUILD` that fizzles back to
`CRUISE` without ever reaching `DROP`. Collapsing them into one state would
force every audio-driven micro-transition to also mean "the song entered a
new structural phrase," which isn't true. Keeping them separate lets phrase
role be a *bias* (soft, additive, capped at `±phrase_bias_max`) on the VJ
mode's own audio-driven thresholds, never a hard override — a strong
enough audio signal always wins regardless of what phrase role thinks is
happening.

---

## 2. VJ mode state machine

```
                    ┌─────────────────────────────────────────┐
                    │                 CRUISE                   │◄──────────────┐
                    └───────┬───────────────────────┬──────────┘                │
                sustained   │                        │ sustained                │
                rise        ▼                        ▼ fall                     │
                    ┌───────────────┐        ┌───────────────┐                  │
                    │     BUILD      │        │   BREAKDOWN    │                 │
                    └───────┬────────┘        └───────┬────────┘                 │
           score+dconf ok   │                  energy recovers │                 │
           (fastlane/normal)│                          └───────────► BUILD       │
           /timeout escape  ▼                                                    │
                    ┌───────────────┐   drop_fizzled                            │
                    │      DROP      ├───────────────────────────────────────────┘
                    └───────┬────────┘
              major tier +  │  minor tier, or
              climax-worthy │  flourish settles
                    ▼       │
            ┌───────────────┐│
            │    IMPACT      ││
            └───────┬────────┘│
        climax-worthy│        │ not climax-worthy
                     ▼        ▼
            ┌───────────────┐  (back to DROP)
            │    CLIMAX      │
            └───────┬────────┘
             hold elapsed +
             not still_hot
                     ▼
                  CRUISE
```

| Transition | Trigger | Key thresholds |
| --- | --- | --- |
| `CRUISE → BUILD` | Energy slope stays above `build_energy_threshold` for `build_sustain_s` (shortened if kick-confirmed, phrase-biased by `HOLD`'s bias) | `build_energy_threshold=0.45`, `build_sustain_s=3.0`, kick-confirmed multiplier `0.65` |
| `CRUISE → BREAKDOWN` | Energy slope at/below `breakdown_slope_threshold` and energy at/below `breakdown_energy_threshold` for `breakdown_sustain_s` | `breakdown_slope_threshold=-0.10`, `breakdown_energy_threshold=0.90`, `breakdown_sustain_s=3.0` |
| `BREAKDOWN → BUILD` | Slope recovers above `0.75×build_energy_threshold` and energy at/above `breakdown_recover_energy` (phrase-biased by `FALL`) | `breakdown_recover_energy=0.96` |
| `BREAKDOWN → CRUISE` | Timeout — `breakdown_max_s` elapsed, **gated by `allow_timeout_forced_transitions`** (see §6) | `breakdown_max_s=14.0` |
| `BUILD → DROP` (scheduled) | `drop_score`/`downbeat_confidence` clear a fastlane or normal threshold after `build_min_hold_s`-ish elapsed (phrase-biased by `RISE`), **or** a `build_max_s` timeout with a relaxed score floor | `drop_threshold=0.78`, `drop_fastlane_score=0.975` (`0.78×1.25`), `drop_min_downbeat_confidence` = `mode_entry_min_confidence` (defaults to `_BPM_LOCK_CONFIDENCE`), `build_max_s=20.0`, `drop_timeout_score_floor=0.78` |
| `BUILD → BREAKDOWN` | Slope/energy fall through the same breakdown gate as `CRUISE`, mid-build | same as above |
| `DROP → IMPACT` or stays `DROP` | Decided **once**, at fire time, by `_infer_peak_tier()` — `major` tier enters `IMPACT`; `minor` skips straight to holding in `DROP` | see §5 |
| `DROP → CRUISE` (fizzle) | `drop_fizzle_grace_s` elapsed and both the peak-so-far score and current score are below `drop_fizzle_score` | `drop_fizzle_grace_s=0.95s`, `drop_fizzle_score=0.78` (= `drop_threshold`) |
| `DROP → CRUISE` (cooldown) | `drop_cooldown_s` elapsed, **gated by `allow_timeout_forced_transitions`** (see §6) | `drop_cooldown_s=30.0` |
| `IMPACT → CLIMAX` | After `impact_hold_s`, tier is `major` and `downbeat_confidence`/`drop_score`/song-progress clear the climax-worthy check | `impact_hold_s=1.2s`, `climax_entry_score=0.86` (`drop_threshold+0.08`), `climax_early_override_score=0.94`, `climax_min_song_progress=0.50` |
| `IMPACT → DROP` (settle) | Same timeout, climax-worthy check fails — flourish just settles into the normal drop groove | — |
| `CLIMAX → CRUISE` | `climax_hold_s` elapsed **and** (`not still_hot` or `climax_hold_max` elapsed) — **not gated by `allow_timeout_forced_transitions`**, see §6 | `climax_hold_s=6.0s`, `climax_extend_max_factor=2.0` (max `12.0s`) |

**`still_hot`** (gates whether `CLIMAX` can extend past its base hold):
`(slope >= hold_cool_slope OR spectral_flux > 0.12) AND NOT kick_dropout_hot`,
where `kick_dropout_hot` is `kick_regularity < 0.30` and the *previous*
tick's kick regularity was `>= 0.60` — a kick dropout is treated as a
faster, more direct "the groove actually ended" signal than waiting for
the slower ~4s energy-slope average to catch up, and it always wins over
a transient spectral-flux spike.

---

## 3. `drop_score` — the detector-side composite that drives everything

`drop_score` is computed in `beat_grid.py` (not `auto_vj.py`) and is the
single most load-bearing number in the whole director — it's the audio
signal `BUILD→DROP` and the fizzle/cooldown/climax-worthy checks are all
built around. It is its own small weighted-sum composite, structurally
identical in spirit to the recommender's (a set of `[0,1]`-ish normalized
signals × fixed weights, summed and clamped), computed fresh every frame:

```python
# 2026-08-09: was energy_norm*0.22 + slope_norm*0.36 + treble_n*0.12 +
# band_blend*0.16 + flux_norm*0.14 -- treble_n double-counted (also
# inside band_blend, see the finding below), fixed the same day this
# audit shipped. Remaining four terms renormalized proportionally.
drop_score = clamp01(
    energy_norm  * 0.25
  + slope_norm   * 0.409
  + band_blend   * 0.182
  + flux_norm    * 0.159
)
```

| Term | Weight | What it measures | Normalization |
| --- | --- | --- | --- |
| `slope_norm` | **0.409** (largest) | Positive energy slope over the last ~2s (rising energy), saturating. | `slope_pos / (slope_pos + 0.12)` |
| `energy_norm` | 0.25 | Absolute smoothed energy level. | `energy / (energy + 1.0)` |
| `band_blend` | 0.182 | Weighted blend of normalized bass/mid/treble (`0.45/0.30/0.25`) — the *only* place treble now contributes, at its intended `0.25` share of this term. | Each band z-score-normalized against its own running mean/variance, squashed to `[0,1]` |
| `flux_norm` | 0.159 | EMA-smoothed spectral flux (transient/onset energy), saturating. | `flux_smooth / (flux_smooth + 0.10)` |

**Theoretical read, same methodology as the recommender audit:**

- **`slope_norm` (0.409, importance High, accuracy High).** The single
  strongest, most theoretically sound signal — a build's whole identity
  *is* rising energy, and the saturating normalization (`x/(x+0.12)`)
  means it can't be dominated by one loud transient the way a raw linear
  slope could. Correctly the largest weight.
- **`energy_norm` (0.25, importance Medium, accuracy Medium).** Absolute
  level matters (a drop is loud), but it's the term most vulnerable to
  mastering/loudness differences between tracks — the same failure mode
  `centroid_fit` had before its per-profile-sigma fix, except `drop_score`
  has no per-profile calibration mechanism at all (see §6, "no per-genre
  scaling").
- **`treble_n` used to be counted twice (0.12 standalone + inside
  `band_blend`'s 0.16×0.25 ≈ 0.04 contribution, total ≈0.16 effective
  weight on treble alone) — fixed 2026-08-09, same day this audit
  shipped** (owner: "don't double count treble! that explains that lol").
  The standalone term is gone; treble now only contributes its intended
  `0.25` share inside `band_blend` (≈0.046 effective, well below bass's
  `0.45` share ≈0.082), which is what the weight authors' own numbers
  said should happen all along.
- **`flux_norm` (0.159, importance Medium-High, accuracy Medium).** A real,
  distinct signal (broad-spectrum transient energy, "qualitatively
  different from energy slope" per the code's own comment) — sound
  reasoning for keeping it additive rather than folded into slope. Its
  `0.10` saturation constant is a hand-picked value with no stated
  derivation, unlike `slope_norm`'s (which at least shares its `0.12`
  constant with the CRUISE build/breakdown gates elsewhere, suggesting it
  was tuned once and reused).
- **`band_blend` (0.182, importance Medium, accuracy Medium).** Reasonable
  as a coarse texture signal, but the same coarse-3-bucket limitation the
  recommender's `band_fit` has — no spectral-shape (64-band) equivalent
  exists on the detector side.

**No per-genre scaling anywhere in `drop_score`.** Every one of these four
terms uses one fixed normalization constant for every track, every genre,
every session — there is no equivalent of the recommender's
`bpm_prior_sigma`/`spectral_centroid_sigma`/`zcr_sigma`/`onset_density_sigma`
per-profile mechanism here. A quiet, low-transient genre (ambient,
chillstep) and a loud, transient-dense one (hardstyle, drum & bass)
compete for `DROP`/`BUILD` against the *same* `0.78`/`0.45` thresholds.
This is a real, unaddressed gap — see Recommendations.

---

## 4. Threshold constants — full reference

All are `config.toml`-overridable via `_profile_value()` (VJ mood profile →
explicit user config.toml override → hardcoded fallback shown here).

| Constant | Default | Role |
| --- | --- | --- |
| `build_energy_threshold` | `0.45` | `CRUISE→BUILD` slope gate |
| `build_reset_slope` | `0.66×build_energy_threshold` | Below this, the build-onset timer resets (evidence stopped accumulating) |
| `build_sustain_s` | `3.0` | How long the slope must stay above threshold before firing (halved to `0.65×` if kick-confirmed) |
| `build_min_hold_s` | `1.4` | Minimum time in `BUILD` before a drop can be scheduled (phrase-biased by `RISE`) |
| `build_max_s` | `20.0` | Timeout ceiling — forces a drop attempt via the relaxed floor below |
| `drop_energy_threshold` | `0.78` | Normal-path `drop_score` gate |
| `drop_fastlane_score` | `1.25×drop_energy_threshold` (`0.975`) | A much higher bar that needs only `~35%` of `build_min_hold_s` elapsed — lets an unambiguously huge score skip most of the hold |
| `drop_confirm_score` | `0.90×drop_energy_threshold` (`0.702`) | Re-validation floor at the scheduled downbeat (see `_fire_drop()`, §5) |
| `drop_timeout_score_floor` | `= drop_energy_threshold` | Relaxed-but-not-zero floor for the `build_max_s` timeout path |
| `drop_cooldown_s` | `30.0` | Minimum time `DROP` holds before the timeout exit is even considered |
| `drop_fizzle_score` | `= drop_energy_threshold` | Both peak-so-far and current score must fall below this to fizzle |
| `drop_fizzle_grace_s` | `0.95` | Minimum time in `DROP` before a fizzle can be declared |
| `breakdown_energy_threshold` | `0.90` | `CRUISE/BUILD→BREAKDOWN` energy gate |
| `breakdown_slope_threshold` | `-0.10` | `CRUISE/BUILD→BREAKDOWN` slope gate |
| `breakdown_reset_slope` | `0.3×breakdown_slope_threshold` | Breakdown-onset timer reset point |
| `breakdown_reset_energy` | `1.08×breakdown_energy_threshold` | Alternate breakdown-onset timer reset point |
| `breakdown_sustain_s` | `3.0` | How long the breakdown gate must hold before firing |
| `breakdown_max_s` | `14.0` | Timeout ceiling back to `CRUISE` |
| `breakdown_recover_energy` | `0.96` | Energy floor to recover from `BREAKDOWN` into `BUILD` |
| `impact_hold_s` | `1.2` | Fixed-duration entry flourish before the climax-worthy check runs |
| `climax_hold_s` | `6.0` | Base `CLIMAX` hold |
| `climax_extend_max_factor` | `2.0` | Max hold multiplier while `still_hot` (ceiling `12.0s`) |
| `climax_entry_score` | `drop_threshold+0.08` (`0.86`) | Score floor for climax-worthy, combined with song-progress gate |
| `climax_early_override_score` | `climax_entry_score+0.08` (`0.94`) | Score floor high enough to skip the song-progress gate entirely |
| `climax_min_song_progress` | `0.50` | Song must be at least halfway through, unless the early-override score clears |
| `climax_song_progress_min_duration_s` | `75.0` | Tracks shorter than this never report song progress (too short for the ratio to mean anything) |
| `climax_min_downbeat_confidence` | `= drop_min_downbeat_confidence` | Downbeat-phase confidence floor for climax-worthy |
| `drop_min_downbeat_confidence` | `= mode_entry_min_confidence` | Downbeat-phase confidence floor to schedule a drop |
| `mode_entry_min_confidence` | `= _BPM_LOCK_CONFIDENCE` (`0.55`) | BPM-lock confidence floor to enter `BUILD`/`BREAKDOWN` at all |
| `hold_cool_slope` | `-0.05` | Slope floor for `still_hot` during `CLIMAX` |
| `cycle_refractory_s` | `3.0` | Dead time after returning to `CRUISE` before another dramatic transition can fire |
| `require_bpm_lock_for_modes` | `True` | Whether `mode_entry_min_confidence` is even checked |
| `allow_timeout_forced_transitions` | **`False`** (fallback) / `True` (all 3 shipped mood profiles) | See §6 |

---

## 5. Phrase bias — mechanism and external influences (with weights)

`_phrase_bias(role)` returns a value in `[-phrase_bias_max, +phrase_bias_max]`
(default `±0.15`) that callers subtract from a threshold
(`effective_threshold = base_threshold - _phrase_bias(role)`) — positive
bias makes a transition easier, negative makes it harder. **Never a hard
gate**: a strong enough audio signal always overrides it.

### Internal terms (bar-counting, no external input)

| Term | Multiplier of `phrase_bias_max` | Fires when |
| --- | --- | --- |
| Under-hold | `0.6 × frac` | Fewer bars elapsed than the role's `expected_min_bars` — scales from full penalty at bar 0 to none at the boundary |
| Over-hold | `0.6 × min(1, over)` | More bars elapsed than `expected_max_bars` — scales up as it overshoots, capped at full bonus |
| Phrase-boundary bonus | `0.25 × (1 - dist)` | Current bar count is within 1 bar of a `phrase_boundary_bar_unit` (default `8`) boundary |
| Peak-cycle flourish | `+0.3` (flat) | Role is `PEAK` and `drop_cycle_count >= phrase_peak_flourish_min_cycle` (default `2`) |
| Early-track suppression | `-0.4` (flat) | Song progress `< 0.15` and role is `RISE`/`PEAK` |
| Late-track (outro) suppression | `-0.5` (flat) | Song progress `>= phrase_outro_song_progress` (default `0.85`) and role isn't `HOLD` |

### External influences — the mixer's section-hint bus (dj-mixer-01)

These are the only terms fed by an outside system rather than the
director's own bar-counting. All three read from `_get_section_hint()`
(`vj_api.get_section(exclude='auto_vj')`), which degrades to `None` (all
external terms inert) on an older core, a missing mixer, or any lookup
error.

| Term | Weight (multiplier of `phrase_bias_max`) | Fires when | Notes |
| --- | --- | --- | --- |
| **External hint match** | `2.0 × confidence × proximity` *(raised from `1.0`, 2026-08-09)* | The mixer's published `role` equals the role being biased | `proximity` ramps `0 → 1` as the mixer's own `bars_left` goes from `phrase_external_proximity_bars` (default `8.0`) down to `1` — confirming "yes we're in BUILD" at the very *start* of a long build contributes ~nothing; only escalates as that role is actually ending |
| **External hint mismatch** | `-0.5 × confidence` | The mixer publishes a *different*, confident role | Not proximity-gated — a mismatch is evidence regardless of where in the phase we are, so it isn't softened the way a match is |
| **Arm ahead of `next_role`** | `2.0 × confidence × proximity` *(raised from `1.0`, 2026-08-09)* | The mixer's `next_role` equals the role being biased | `proximity` ramps over `phrase_arm_proximity_bars` (default `16.0`, twice the match term's window) keyed on `bars_to_next` — "prepare early" intentionally starts further out than "confirmed, about to end" |

**2026-08-09 update:** match/arm-ahead raised `1.0 → 2.0`. At `1.0`, either
term needed `confidence × proximity == 1.0` (never actually reachable) to
saturate `phrase_bias_max` on its own, so a confident external
confirmation was routinely outweighed by the internal bar-counting terms
it was supposed to reinforce — owner: the external terms "seem weak, like
not doing crap." At `2.0`, saturation needs only ~50% `confidence ×
proximity`. Mismatch intentionally left at `0.5` — confirmation and
disagreement were never meant to be symmetric (see below), and the
owner's question was specifically about "the 1.0s." See
`docs/adr/vj-system.md` § "Live-Session Follow-Up."

**Relative ranking of external influence:** hint-match and arm-ahead each
carry the *same* maximum weight as each other and are both stronger than
a mismatch — the system trusts a confident confirmation more than a
confident disagreement. This is a deliberate, documented asymmetry (per
the code's own comment: "it disagrees with this specific role outright,
it doesn't confirm some other one is nearly over") rather than an
oversight.

### External influence — peak-tier override (separate from bias)

`_infer_peak_tier()` doesn't go through `_phrase_bias()` at all — it's a
**hard override**, not a soft bias, gated on a confidence floor rather than
scaled continuously:

| Signal | Threshold | Effect |
| --- | --- | --- |
| Mixer's `role == 'PEAK'` and `tier in ('major','minor')` | `confidence >= phrase_external_tier_min_confidence` (default `0.6`) | Returns the mixer's tier directly, skipping local inference (`drop_cycle_count`/`bars_since_phase_entry` heuristics) entirely |

This is the *only* place in the whole director where an external signal
can fully override local judgment rather than just nudge a threshold — a
deliberate design choice, since (per the code's comment) "the mixer has
pre-analyzed the whole file and knows which peak is genuinely the biggest,
which the director can only ever guess at live from cycle count."

### External influence — set-clock hint (session-level, not phrase-level)

`_get_session_hint()` (`vj_api.get_session()`) is a *different* bus from
the section hint above — set-level (`phase`/`seconds_left`), not
track-level (`role`/`bars_left`). It does not feed `_phrase_bias()` at
all; it feeds `_check_timed_finale()` (grand-finale triggering, already
audited earlier this session — see `docs/adr/vj-system.md` § "Set-Clock
Hint Bus"). Included here only to be explicit that it is **not** one of
the phrase-bias external influences, despite superficially similar naming.

---

## 6. Oddities / potential bugs

### 6.1 — `allow_timeout_forced_transitions`'s hardcoded fallback is the *dangerous* value — **RESOLVED 2026-08-09**

The code-level fallback (used only when no mood profile and no
`config.toml` override supplies this key) is **`False`**. All three
shipped VJ mood profiles (`chill`, `normie`, `raver`) explicitly override
it to **`True`**, so in every real session today this is a non-issue. But
the fallback governs three separate exits: `BREAKDOWN→CRUISE` timeout,
`BUILD`'s `build_max_s` forced-drop timeout, and `DROP→CRUISE` cooldown
timeout. If a future 4th mood profile forgot this key, or a session ran
with no mood profile selected, the consequence isn't graceful degradation
— it's `DROP` (and potentially `BREAKDOWN`) **holding indefinitely** as
long as `drop_score` stays above `drop_fizzle_score`, since the *only*
other exit (fizzle) requires the score to actually drop. This is backwards
from normal defensive-default practice: the safe value should be the
one that survives an unconfigured `_profile_value()` lookup, with profiles
opting *out* of it if they want, not the other way around.

**Fixed same day:** hardcoded fallback flipped to `True`. Owner separately
noted this was plausibly contributing to real friction: "wasn't doing well
on long breakdowns/drops in the more wandering genres w/longer songs."
Per-audio-genre-profile overrides for this specific constant were
explicitly **not** added — see §6.4's note below, folded into the same
"thorough per-genre director tweaks" follow-up rather than a one-off
exception. See `docs/adr/vj-system.md` § "Live-Session Follow-Up."

### 6.2 — `CLIMAX`'s exit is not gated by `allow_timeout_forced_transitions`, inconsistently with `BUILD`/`BREAKDOWN`/`DROP`

The other three timeout-driven exits all check
`self._allow_timeout_forced_transitions` before firing. `CLIMAX`'s hold-
elapsed exit (`elapsed >= climax_hold and (not still_hot or elapsed >=
climax_hold_max)`) does not. Given §6.1's fallback risk, this actually
makes `CLIMAX` the *safest* mode against getting permanently stuck — but
the inconsistency itself looks unintentional rather than a deliberate
design choice; no comment explains why `CLIMAX` was left out of the gate
that every sibling mode respects.

**Recommendation:** either explain the asymmetry in a comment (if
intentional — e.g. "CLIMAX must always be time-bounded since it's the
most visually intense state") or bring it in line with the other three for
consistency.

### 6.3 — Treble is double-counted in `drop_score` with no documented rationale — **RESOLVED 2026-08-09**

Covered in §3 — `treble_n` appears both standalone (`0.12`) and inside
`band_blend` (contributing another `~0.04`), giving treble roughly `0.16`
effective weight versus bass/mid's `~0.10`/`~0.07` (their `band_blend`
share alone, no standalone term). Plausible musically (drops/risers are
often treble-forward), but nothing in the code says this was a deliberate
choice versus an accumulated accident from `band_blend` being added after
`treble_n` already existed.

**Fixed same day** (owner: "don't double count treble! that explains that
lol") — the standalone term removed in both `beat_grid.py` engines
(`BeatGridTracker`/v1, `BeatTracker`/v2); the remaining terms'
weights renormalized proportionally so they still sum to `1.0`. See
`docs/adr/vj-system.md` § "Live-Session Follow-Up" for the exact new
weight values.

### 6.4 — No per-genre-profile scaling anywhere in `drop_score` or the mode thresholds — **still open, explicitly deferred**

Covered in §3. Every threshold in §4 is one fixed number for every audio
profile — an ambient track and a hardstyle track compete for `BUILD`/
`DROP` against identical `0.45`/`0.78` gates, despite the recommender
subsystem (same day, same file) having just gone through two rounds of
adding exactly this kind of per-profile calibration (`bpm_prior_sigma`,
`spectral_centroid_sigma`, `zcr_sigma`, `onset_density_sigma`). This isn't
a bug — the director predates that pattern and nothing is provably broken
— but it's the most significant asymmetry between the two subsystems
audited today, and a plausible next target if `DROP`/`BUILD` timing turns
out to feel wrong on quiet-genre sessions specifically.

**2026-08-09 update:** the owner independently converged on this same
finding from a different angle — real friction on long/wandering-genre
songs (§6.1) plus a direct question, "should we have per-genre tweaks on
director, thoroughly? that is really the whole intent of guessing the
genre... to better read/predict/respond to drops & breakdowns and energy
levels." Deliberately not implemented yet: this needs a genre-profile-
override lookup layer in `_profile_value()` (currently mood-profile-only)
plus new `AudioProfile` fields plus the same kind of research pass
`zcr_sigma`/`onset_density_sigma` got — bigger than a single-session fix.
The owner is running a multi-genre, multi-session training marathon
specifically to build a stable base first, which will also produce exactly
the broad, tagged data this calibration should be researched against.

---

## 7. Positive findings (worth preserving, not just critiquing)

- **`_fire_drop()`'s downbeat-scheduled re-confirmation** (§2, `BUILD→DROP`
  row) is genuinely good design: `_schedule_drop()` doesn't fire
  immediately — it waits for the next real downbeat
  (`schedule_for_next_downbeat`), then re-checks `drop_score`/
  `downbeat_confidence` against fresh (if slightly relaxed —
  `drop_confirm_score = 0.90×drop_threshold`) floors before actually
  transitioning, emitting a `drop_cancelled` event if the re-check fails.
  This closes a real class of bug (scheduling on a score spike that's
  already decayed by the time the downbeat arrives) that a naive
  "check once, fire immediately" design would miss.
- **The track-change neutral window** (`_reset_phrase_clock_for_track_
  change()`) is an honest response to genuine ambiguity: a hard deck-cut
  and a fresh track look identical from a bare track-ID change, so phrase
  bias is withheld entirely for `phrase_track_change_neutral_bars` bars
  rather than guessing either way. Good instinct for a case with no
  principled way to disambiguate locally.
- **The external-hint proximity ramps** (§5) are a well-reasoned fix for a
  real, owner-observed live bug (a confident hint at the *start* of a
  build nearly pushed the director toward `DROP` immediately) — scaling by
  how close the hinted phase actually is to ending, rather than firing at
  full strength the instant it's confirmed, is the right shape for that
  problem.
- **Deadline-locking on entry** (`_enter_breakdown()`'s
  `self._breakdown_deadline_t = now + ...`) deliberately prevents a
  mid-breakdown profile switch from retroactively extending the timeout —
  a small but easy-to-miss correctness detail (many similar systems would
  recompute the deadline every tick and accidentally let a switch reset
  the clock).

---

## 8. Recommendations summary

| # | Recommendation | Priority | Effort | Status |
| --- | --- | --- | --- | --- |
| 1 | Flip `allow_timeout_forced_transitions`'s hardcoded fallback to `True` (§6.1) | High — current safety depends entirely on every mood profile remembering to override it | Trivial (one-line default change) | **Done 2026-08-09** |
| 2 | Resolve the `CLIMAX` timeout-gate inconsistency (§6.2) — comment or align | Medium | Trivial | Open |
| 3 | Confirm or fix the treble double-count in `drop_score` (§6.3) | Low — plausible either way, just undocumented | Trivial (comment) to Small (rebalance) | **Done 2026-08-09** |
| 4 | Consider per-audio-profile scaling for `drop_score`'s normalization constants and/or the `BUILD`/`DROP` thresholds (§6.4), mirroring the recommender's per-profile sigma pattern | Low-Medium — no known live bug, but a real asymmetry with the subsystem it sits next to | Medium — needs the same kind of research pass `zcr_sigma`/`onset_density_sigma` got, plus new `AudioProfile` fields | Deferred — owner converged on the same finding independently; explicitly waiting on marathon data (see §6.4) |

Items 1 and 3 were implemented the same day this audit shipped, after the
top-3-weights rewire's first live session surfaced both as active
contributors to a real symptom (composite scores blowing past the old
`±9.99` HUD clamp) rather than latent risk — see `docs/adr/vj-system.md`
§ "Live-Session Follow-Up" for the full account. Item 2 remains flagged
for owner review, unchanged. Item 4 is explicitly deferred pending the
owner's training marathon.
