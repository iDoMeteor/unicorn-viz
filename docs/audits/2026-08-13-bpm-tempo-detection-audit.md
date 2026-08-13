# BPM / Tempo Detection Audit (2026-08-13)

Owner: unicorn-viz
Status: complete — findings awaiting owner review; no code changed by this audit
Last updated: 2026-08-13

Companion piece to the 2026-08-11 music-theory audit
(`2026-08-11-auto-vj-music-theory-audit.md`), same treatment, scoped to
tempo: the live engines in `drop-ins/auto-vj-01/beat_grid.py`
(`BeatGridTracker` v1, `BeatTracker` v2, `BeatTrackerV3` — v3 is the
configured engine per `config.toml`), the onset path feeding them
(`unicornviz/audio/analyzer.py`), the profile tempo priors
(`unicornviz/audio/profiles.py`), the BPM bus / priming path, and the
confidence machinery the director's Schmidt trigger consumes. The offline
estimator (`dj-mixer-01/bpm.py`) was covered in the 2026-08-11 audit's
bonus section (B1/B2) and is cross-referenced, not repeated. Versions
audited: detector `1.0.0-rc.8`, auto-vj-01 `1.0.0-rc.44`.

Prior art in-repo: `2026-08-04-bpm-detector-audit.md` (the "consistently
20 hot" root cause — profile hints acting as hard clamps, P0-A/P0-B).
Those fixes are verified still in place (`set_profile()` never narrows
the search range; the bus prime path exists and works). This audit does
not re-litigate them; it goes after what's *left*.

Per the owner's request, this document keeps two things strictly apart:

- **Part I** is external — what the research literature and public
  libraries actually do, with sources. Nothing in Part I is my claim.
- **Part II** is internal — my own analysis of this repository's code and
  math. Every number in it was computed directly against the constants in
  the code; no external source asserts any of it.
- **Part III** is my synthesis: recommendations that combine the two,
  attributed accordingly.

---

# Part I — External: the state of the art (sourced)

## I.1 How the field frames the problem

The literature treats **tempo estimation** (a global/period value),
**beat tracking** (event times), and **downbeat/meter tracking** (bar
phase) as related but distinct tasks, usually solved jointly in modern
systems. Evaluation conventions matter here because they encode a truth
this codebase already lives with: the metrical level is genuinely
ambiguous. The MIREX-era standard reports **Accuracy1** (estimate within
±4% of annotated tempo) and **Accuracy2** (same, but 1/3×, 1/2×, 2×, 3×
also count) — Acc2 exists precisely because "octave errors" are common
enough, and human-disagreement-prone enough, to deserve their own bucket.
Listeners themselves disagree on tapping level (the McKinney/Moelants
perception studies behind the ~120 BPM resonance peak the detector's
prior already uses).

## I.2 The classical lineage (what this codebase's design descends from)

- **Scheirer (1998)** — bank of resonant comb filters over band-wise
  onset envelopes; the ancestor of every comb/harmonic-summing tempo
  scorer, including the aubio-style comb in `beat_grid.py`.
- **Klapuri et al. (2006)** — comb-filter periodicity analysis at three
  metrical levels (tatum/tactus/measure) with a probabilistic prior tying
  them together; still the reference for principled metrical-level
  disambiguation.
- **Ellis (2007), "Beat Tracking by Dynamic Programming"** — onset
  envelope → autocorrelation tempo → DP over onset strength with an
  inter-beat-interval regularity cost. This is `librosa.beat.beat_track`
  to this day: cheap, transparent, near-competitive offline.
- **Percival & Tzanetakis (2014), "Streamlined Tempo Estimation"** —
  deliberately minimal pipeline (onset strength → generalized
  autocorrelation → cross-correlation with pulse trains for lag
  verification) that matched far more complex systems; implemented in
  Essentia/Marsyas. Its pulse-train *verification* step (score a
  candidate lag by how well an actual pulse train at that lag lines up
  with the envelope) is the standout technique not yet present in this
  codebase.

## I.3 Modern learned systems (current accuracy ceiling)

- **madmom (Böck et al.)** — the long-standing open-source reference:
  an RNN (LSTM) or TCN produces a per-frame beat activation, decoded by a
  **Dynamic Bayesian Network** (approximated as an HMM) in which tempo is
  a latent state with explicit transition costs. This is the key
  architectural idea: *stability-vs-agility is a single principled
  transition prior*, not a stack of ad-hoc gates. madmom ships an online
  (causal) DBN mode.
- **TempoCNN (Schreiber & Müller 2018)** — single-pass CNN mapping
  mel-spectrogram directly to a tempo class distribution; cheap offline
  labeling; available in Essentia.
- **Beat This! (Foscarin et al., 2024)** — transformer beat tracker that
  is the current offline F1 state of the art, notable for needing **no
  DBN post-processing**.
- **Online/real-time neural systems** — **BeatNet** (ISMIR 2021):
  causal CRNN activation + sequential Monte Carlo **particle filtering**,
  jointly tracking beat, downbeat, and meter in real time without being
  primed with a time signature; **BeatNet+** (TISMIR) extends it to
  diverse audio; **BEAST** (2023) is a streaming-transformer variant with
  low reported latency. These are the literature's direct answers to this
  project's live problem — including the bar-phase half (audit finding
  F5) that the in-house tracker doesn't attempt.
- **Failure-mode honesty** — a 2026 analysis of SOTA trackers on the SMC
  dataset shows even the best systems degrade sharply on weak-pulse,
  expressive material, and that tempo accuracy is strongly BPM-range
  dependent. SOTA does not mean solved; it means solved for
  steady-pulse material — which is, usefully, exactly this project's
  operating domain.

## I.4 Evaluation practice and public data this project can use directly

- **GiantSteps Tempo / GiantSteps Key (Knees et al., ISMIR 2015)** —
  public benchmark datasets built specifically from **electronic dance
  music** (Beatport excerpts) for tempo and key. The closest public
  ground truth to this project's material; both are standard in the
  literature.
- **Hörschläger et al. (SMC 2015)** — specifically on fixing tempo
  **octave errors in electronic music**; directly relevant prior art for
  Part II's T5 (the DnB octave policy problem).
- **tempo_eval (Schreiber)** — open evaluation framework with published
  per-dataset reports; the ready-made harness shape for scoring a tempo
  estimator the way the field does (Acc1/Acc2, per-genre breakdowns).

## I.5 Public libraries roster

Framing note (internal constraint, stated here for context): the live
tracker's no-heavy-deps design is deliberate and documented
(`beat_grid.py` docstring: "No librosa, no aubio", 16.67 ms frame
budget), and Windows is a first-class install target. So the practical
uses for these libraries are (a) porting *techniques*, (b) **offline**
ground-truth labeling inside training-kit tooling, where dj-mixer-01
already sets the precedent of shelling out to a heavyweight tool
(Demucs), and (c) benchmarking the in-house detector against them.

Library | Method | Real-time | Notes
--- | --- | --- | ---
librosa | Ellis 2007 DP (+ time-varying variant) | No | ISC license; easy offline labeler
aubio | comb/phase-based, C core | Yes | GPL-3.0 — license matters for bundling; already the named inspiration for the comb
madmom | RNN/TCN + DBN(HMM), online mode | Yes (online mode) | Code permissive, **trained-model licenses need checking** (non-commercial clauses reported); best-in-class open labeler
Essentia | RhythmExtractor2013 (multifeature/degara), Percival, TempoCNN | Mostly offline | AGPL-3.0 — fine as a dev-side labeler, not for bundling
BeatNet / BeatNet+ | CRNN + particle filter, joint beat/downbeat/meter | **Yes, by design** | Research license — verify before any use beyond evaluation
Beat This! | Transformer, no DBN | No | Current offline SOTA; labeler candidate

For the labeling/benchmarking role (dev-side only, nothing bundled),
madmom's online DBN and TempoCNN are the standard choices; GiantSteps is
the standard public EDM test set to run alongside the owner's own
mixer-analyzed library.

---

# Part II — Internal: my own analysis of this codebase (no external source)

Everything below is my analysis of the code as it stands at detector
`1.0.0-rc.8`; the numbers are computed from the constants in the code
(envelope rate 100 Hz, `_V2_PHASE_TOL` 0.14, candidate-spread limit 4.0,
`max_bpm_step` 3.0, tempo hold 10 s, blend 0.5/0.5, Schmidt 0.55/0.28).

## T1 — Integer-lag quantization in the live ACF, and a candidate-spread deadlock above ~155 BPM

The v2/v3 ACF searches integer lags of a 100 Hz envelope and takes
`argmax` with no peak interpolation. BPM candidates are therefore
quantized to `6000/lag`, and the error of the nearest representable
candidate is tempo-dependent:

True BPM | Nearest candidate | Error | Adjacent-lag gap
--- | --- | --- | ---
122 | 122.45 | 0.37% | 2.45 BPM
124 | 125.00 | 0.81% | 2.55 BPM
128 | 127.66 | 0.27% | 2.78 BPM
138 | 139.53 | 1.11% | 3.17 BPM
145 | 146.34 | 0.93% | 3.48 BPM
150 | 150.00 | 0.00% | 3.75 BPM
155 | 153.85 | 0.74% | **4.05 BPM**
160 | 157.89 | 1.32% | **4.27 BPM**
174 | 176.47 | 1.42% | **5.04 BPM**
180 | 181.82 | 1.01% | **5.35 BPM**

Two consequences:

1. **Steady-state bias.** The EMA/candidate-median machinery smooths
   between *identical quantized values*, so the error never averages out:
   a 174.0 DnB track reads 176.5 or 171.4 persistently (±1.4%). The
   phase oscillator hides this — a ~1.5%/beat phase slip corrected at
   `_V2_PHASE_NUDGE = 0.25` per on-window onset equilibrates around ~6%
   phase error, inside the 14% tolerance — so coherence stays high while
   the reported BPM is simply wrong by more than the MIREX ±4%/... no,
   within ±4%, but well outside the 0.06-BPM integer-tempo convention the
   mixer side documents, and enough to matter for the HUD, the corpus,
   and profile `tempo_fit` scoring.
2. **The deadlock.** The candidate-persistence gate requires the last 3
   ACF picks to sit within an **absolute** 4.0 BPM spread. Above ~155 BPM
   the two lags adjacent to the true tempo differ by *more than 4 BPM*
   (table above), and when the true lag falls near the midpoint (174 →
   lag 34.48), noise alternates the argmax between lag 34 and 35 —
   spread 5.04 → `return`. The tracker can be **structurally unable to
   accept updates** at exactly the DnB/hardstyle tempos whose profiles
   (`bpm_prior_mu` 174, 150, 148) this project ships. v1
   (`BeatGridTracker`) does not share this failure (its IOI median is
   continuous-valued), which may explain any lingering sense that v1 was
   "dialed in" on fast genres.

Same root cause as offline finding B1 (`dj-mixer-01/bpm.py`), same fix,
different constants: **parabolic interpolation of the ACF peak** (and of
the comb-score peak), plus making the spread limit **relative** (e.g.,
2.5% of the median candidate) instead of absolute 4.0 BPM.

## T2 — Phase-coherence confidence has a 28% chance floor; the Schmidt release sits exactly on it

`phase_confidence` is the hit rate of onsets landing within
`±_V2_PHASE_TOL = 0.14` of predicted beat phase. A completely unrelated
onset stream (random phase) lands in that window `2 × 0.14 = 28%` of the
time — the metric's zero point is 0.28, not 0.0. Three things follow:

1. **`_BPM_LOCK_RELEASE_CONFIDENCE = 0.28` is exactly chance level.**
   With the 0.5/0.5 blend, a dead phase lock (chance-level 0.28) plus an
   ACF confidence of just 0.28 keeps the blend at 0.28 — the Schmidt
   trigger's release boundary — meaning the "release" threshold as
   configured can be satisfied by *no phase information at all* whenever
   the ACF half alone reaches ~0.28. The hysteresis band is real, but its
   floor measures less than it appears to.
2. **Uncalibrated scale.** The meaningful range of `phase_confidence` is
   [0.28, 1.0] compressed into a reported [0, 1]; the overnight session's
   "genuinely weak" mean of 0.347 (2026-08-11 ADR addendum) is, chance-
   corrected, `(0.347 − 0.28)/(1 − 0.28) ≈ 0.09` — not weak, *near-zero*.
   Every consumer (blend, Schmidt, HUD, corpus, LLM scorecards) reads
   this uncalibrated number. Rescaling to
   `max(0, (hit_rate − 2·tol)/(1 − 2·tol))` makes it a true 0-to-1
   quantity *and* makes the tolerance's value stop silently shifting the
   confidence scale each time it's retuned (0.18 → 0.12 → 0.14 each moved
   the chance floor: 0.36 → 0.24 → 0.28 — some of what those experiments
   "measured" was the floor moving, not lock quality).
3. **Genre-dependent ceiling.** Coherence counts *every* onset —
   snares, syncopation, vocal transients. Four-on-the-floor genres can
   approach 1.0; heavily syncopated material (rap_rnb) structurally
   cannot, independent of lock quality. Weighting the coherence buffer by
   onset strength (already carried on `OnsetEvent`) would reduce the
   genre skew; per-profile expectations would be the fuller fix.

## T3 — The incumbent-bias stack: seven independent guards, and a convergence path that can plateau

Guards protecting the current estimate, each individually justified,
enumerated in one place for the first time: tempo hold (10 s, refreshed
on every accepted update), candidate persistence (3 picks, spread ≤ 4),
jump limit (±16%/min 10 BPM below `acf_conf` 0.72), low→fast guard
(0.80), `max_bpm_step` (3 BPM per accepted update), the analyzer
refractory feedback (T4), and v3's prior freeze. Stability is a feature —
but the *composition* has two emergent behaviors nobody chose:

1. **Confident lane changes crawl.** A genuine 120 → 150 change that
   clears every gate still moves at ≤3 BPM per accepted ACF update, and
   each partial update **refreshes the 10 s tempo hold**; if the blend
   confidence recovers above 0.45 mid-crawl (phase coherence partially
   adapting), the hold gate freezes the estimate part-way for up to 10 s.
   A plateau at a stale intermediate BPM is the same *signature* as the
   2026-08-04 "20 hot" bug, produced by a completely different mechanism
   — worth knowing before anyone chases a future report of it.
2. **The no-silence transition is the weak case.** `_reset_tempo_lock`
   needs 15 s of *zero onsets*; a beatmatched DJ blend never provides it.
   Small tempo moves ride the lock band fine; a hard playlist cut to a
   >16%-different tempo with `acf_conf` hovering under 0.72 has no reset
   path and waits on the crawl. (The mixer-bus prime covers mixer
   sessions; Spotify/media sessions have no such rescue.)

## T4 — The refractory feedback loop is a self-confirmation channel

`set_expected_bpm(bpm, conf ≥ 0.5)` sets the analyzer's onset refractory
to 70% of the *estimated* beat period (clamped 0.18–0.50 s). Lock half
tempo (60 instead of 120) and the refractory becomes 0.5 s — exactly the
true beat period — so alternating true beats get suppressed *at the
source*, and the onset stream itself starts agreeing with the wrong
estimate. This is the same shape as the P0-A self-confirming loop the
2026-08-04 audit removed (profile → search clamp → detection → profile),
one layer down: estimate → refractory → onset evidence → estimate. The
clamp bounds the damage and the intent (starving sub-beat IOI pollution)
is legitimate; but the loop deserves the same treatment P0-A got —
weaken the feedback when the estimate is contested (e.g., suspend the
BPM-derived refractory while the candidate history disagrees with the
lock, falling back to the strength-scaled cooldown).

## T5 — There is no explicit octave policy; the correct octave for fast genres is profile-mediated, which is circular

Computed against the shipped constants: for a 174 BPM track under the
**default** prior (μ=120, σ=0.55), the prior weight at 87 BPM (0.701)
*exceeds* the weight at 174 (0.622) — the default prior votes for
half-time. The tactus fold-down then only needs the 0.5× lag to score ≥
55% of the pick — near-always true for periodic material — so an
unprofiled DnB session folds to ~87. The 174 lock is reachable
essentially only when the dnb profile is active (μ=174 floored σ=0.45:
weight 1.0 vs 0.085) — but the profile is chosen by the recommender,
whose `tempo_fit` reads the detected BPM. The 2026-08-04 audit broke the
*hard* version of this circle (the range clamp); the *soft* version —
profile prior ↔ detected tempo ↔ recommended profile — still stands, and
for fast genres it decides the octave. Two things are missing, both
cheap: an **explicit, written octave policy** (recommendation: follow
the mixer store's convention — kick-level tactus, 174 for DnB — since
that store is already the designated ground truth), and **corpus logging
of fold decisions** (`tactus fold applied: 176→88, ratio 0.61`) — today
folds are invisible in the data, so nobody can measure how often the
fold is right. This is also where the external work (Hörschläger SMC
2015, Part I.4) is directly reusable: EDM-specific octave disambiguation
is a solved-enough problem to crib from.

## T6 — Minor findings

- **ACF overlap bias**: `acf[i] = dot(env[lag:], env[:n−lag])/norm` is
  not divided by the overlap length `(n − lag)`; longer lags (slower
  tempos) sum fewer terms, a systematic few-percent tilt toward faster
  lanes. The comb partially masks it; dividing by `(n − lag)` removes it.
- **Unbounded pulse strengths**: onset strengths (MAD z-scores, ≥ 1,
  unbounded) are written raw into the envelope; one freak transient
  dominates the zero-mean ACF for the full 8 s window. `log1p` or a
  percentile clamp on strength at pulse time would cap the leverage.
- **BPM-EMA alpha is near-floor always**: alpha derives from
  `score[peak]/score.sum()` — with ~70 lags this share is structurally
  tiny, so alpha ≈ its 0.05 floor regardless of evidence quality; the
  intended "confident → faster adaptation" behavior mostly doesn't
  engage. Harmless today (candidate-median does the real work), but the
  knob doesn't do what it looks like it does.
- **Clock-epoch fragility**: `update()` uses onset audio-time as `now`
  when onsets arrive but `time.monotonic()` otherwise; live these
  coincide (the analyzer stamps onsets with monotonic time), but any
  future audio-clock timestamp source would silently mix epochs in
  `phase_dt`. One comment and one invariant check would pin it.
- **v1 (`BeatGridTracker`)**: sound as a legacy fallback (median-IOI +
  harmonic families is a reasonable classical design, and it's immune to
  T1's lag quantization); its weaknesses (no envelope memory, IOI
  contamination sensitivity) are exactly what v2 was built to fix. v3's
  prior freeze is correctly designed and verified in place.

---

# Part III — Synthesis: recommendations (mine, drawing on Part I)

Ordered by leverage-per-effort; none require new runtime dependencies,
honoring the documented in-house constraint.

1. **Parabolic peak interpolation, live + offline (T1, B1).** Standard
   practice in every serious ACF-based estimator (Percival & Tzanetakis
   interpolate; so does Essentia). Fixes the steady-state bias, and with
   the spread limit made relative (≈2.5% of candidate) also fixes the
   ≥155 BPM deadlock. Small, self-contained, simulatable against corpus
   replays. `_DETECTOR_VERSION` minor bump + weights-doc sync when it
   lands.
2. **Calibrate phase coherence (T2).** Chance-corrected rescale, and
   revisit `_BPM_LOCK_RELEASE_CONFIDENCE` in calibrated units (as
   configured it releases at chance level). Strength-weight the
   coherence buffer. This changes the meaning of a logged field — bump
   and note in the corpus schema comments, since LLM scorecards read it.
3. **Adopt the field's metrics and data for validation (Part I.4).**
   Add Acc1/Acc2 (±4%, octave-tolerant) split to the training scorecards
   so octave errors are counted separately from lane errors; validate
   against the owner's mixer-analyzed library (already designated ground
   truth) plus **GiantSteps Tempo** for public reproducibility; use
   madmom/TempoCNN **offline, dev-side only** as reference labelers in
   training-kit tooling (Demucs precedent; check model licenses before
   even that).
4. **Snap, don't crawl, on confident lane changes (T3).** When
   `acf_conf ≥ _large_jump_confidence` *and* candidate persistence holds,
   bypass `max_bpm_step` and adopt the candidate median outright; refresh
   the tempo hold only when the estimate and candidate agree within the
   lock band. This is a two-condition change that removes the plateau
   mode without touching the guards' protective roles.
5. **Write the octave policy down and log fold decisions (T5).** Policy
   doc line + one corpus mark. Then measure fold correctness against the
   mixer store before touching `tactus_preference_ratio`.
6. **Soften the refractory feedback under disagreement (T4).** Suspend
   the BPM-derived refractory while candidate history and lock disagree;
   fall back to the strength-scaled cooldown. Closes the last
   self-confirmation channel the 2026-08-04 audit's fixes left open.
7. **The bigger step, if it's ever wanted (Part I.3):** the guard stack
   is a hand-rolled approximation of what madmom's DBN does with one
   explicit transition prior. A small pure-numpy HMM over quantized tempo
   states (transition cost = the current guards, observation = comb
   score) would replace seven interacting gates with one tunable matrix —
   the principled version of the incumbent bias, and the direction the
   entire field went. Not urgent; the guards work. Noted so the option
   has a name. Similarly, BeatNet's particle-filter bar-phase inference
   is the literature's answer to the missing-downbeat finding (F5) if the
   cheap accent-voting version proves insufficient.

Per the standing rules: audit only, no code changed, no version bumps
due. The standing owner feedback applies to items 1-6: they are grounded
in code math and corpus-replayable, but anything touching detector
constants gets flagged + confirmed and simulated against real sessions
before shipping, per the established process.

---

## Sources (Part I)

- [Ellis 2007 — Beat Tracking by Dynamic Programming (PDF)](https://www.ee.columbia.edu/~dpwe/pubs/Ellis07-beattrack.pdf)
- [librosa.beat.beat_track (Ellis DP implementation)](https://librosa.org/doc/latest/generated/librosa.beat.beat_track.html)
- [Percival & Tzanetakis 2014 — Streamlined Tempo Estimation (PDF)](https://webhome.csc.uvic.ca/~gtzan/output/taslp2014-tempo-gtzan.pdf)
- [madmom tempo module (DBN histogram)](https://madmom.readthedocs.io/en/v0.16.1/modules/features/tempo.html)
- [madmom beats module (RNN + DBN/HMM decoding)](https://madmom.readthedocs.io/en/v0.16.1/modules/features/beats.html)
- [Schreiber & Müller 2018 — TempoCNN single-step tempo CNN (PDF)](https://www.tagtraum.com/download/2018_schreiber_tempo_cnn.pdf)
- [Beat This! — Accurate beat tracking without DBN postprocessing (arXiv)](https://arxiv.org/pdf/2407.21658)
- [BEAST — Online joint beat/downbeat tracking, streaming transformer (arXiv)](https://arxiv.org/pdf/2312.17156)
- [BeatNet — CRNN + particle filtering, online joint tracking (arXiv)](https://arxiv.org/abs/2108.03576)
- [BeatNet GitHub](https://github.com/mjhydri/BeatNet)
- [BeatNet+ — Real-time rhythm analysis for diverse music audio (TISMIR)](https://transactions.ismir.net/articles/10.5334/tismir.198)
- [The SMC Blind Spot — failure-mode analysis of SOTA beat tracking (arXiv)](https://arxiv.org/html/2605.12287v1)
- [AI and Tempo Estimation: A Review (arXiv)](https://arxiv.org/pdf/2401.00209)
- [GiantSteps tempo/key EDM datasets (ISMIR 2015 paper)](https://archives.ismir.net/ismir2015/paper/000246.pdf)
- [Hörschläger et al. SMC 2015 — Addressing tempo octave errors in electronic music (PDF)](https://www.ifs.tuwien.ac.at/~knees/publications/hoerschlaeger_etal_smc_2015.pdf)
- [tempo_eval published reports](https://tempoeval.github.io/tempo_eval_report/hjdb.html)
- [tagtraum — tempo estimation notes (Acc1/Acc2 conventions)](https://www.tagtraum.com/tempo_estimation.html)
