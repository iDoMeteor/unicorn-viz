# Auto VJ: Genre Intelligence + BPM/Genre Candidate Matching — Plan (2026-08-20)

Owner: unicorn-viz
Status: Stage 1 STARTED (2026-08-20 — the genre-pure composite shipped:
recommender rc.18, tempo_fit/top_cand_fit zeroed, weights rebalanced
best-guess; see § 6). Matcher (Stage 2) not built. Captures the owner's
proposal ("this would not be a genre 'weight' in the bpm detector as we
used to have, it would be like a whole new algorithm that isn't really
weight based but more candidate matching").
Last updated: 2026-08-20

---

## 1. The theory (owner's framing, agreed)

Build genre analysis to be **as accurate as possible in its own right**,
isolated from the detector — then use the two systems' *candidate lists*
against each other instead of blending scores:

- **Detector confidence LOW:** take the detector's top-2 BPM candidates
  (with their scores) and the genre system's top-3 candidates (with
  their confidences), and select the best-matching (bpm, genre) pair —
  the genre's plausible tempo range disambiguates which BPM hypothesis
  is real. This is fold disambiguation: 87 vs 174 is R&B-vs-DnB, and
  genre knows which one it's hearing even when the ACF can't decide.
- **Detector confidence HIGH:** flip the direction — the confident BPM
  *filters* which genres are eligible, and the highest-confidence genre
  whose range contains the locked tempo wins. Tempo constrains genre;
  genre never touches tempo.

Not a weight in the detector (that coupling was cut 2026-08-14 and stays
cut), not a term in a composite — **hypothesis selection between two
independently-confident systems.**

### Why this is the right shape (audit lineage)

Both halves already exist in embryo, separately owner-approved, never
unified:

- The HIGH half is the "BPM as a Hard Recommender Pre-Filter" ADR
  (2026-08-13, approved, deferred to RC2 — born from the chillstep-at-
  130-BPM incident).
- The LOW half is round three's genre-evidence gate ("consult genre only
  while acf_confidence is low"), which already feeds tempo-independent
  terms only — but applies them as a Gaussian *boost inside the
  detector's candidate scoring*, i.e. weight-shaped. This plan's matcher
  supersedes that mechanism with explicit external selection.

It also directly answers the 2026-08-13 tempo audit's **T5** (octave
policy is profile-mediated, which is circular): an isolated genre scorer
breaks the circle, and the matcher IS the explicit octave policy T5
said doesn't exist.

**The measurable objective:** the 439-track replay baseline reads
Acc1 86.6% / Acc2 95.7% — the 9-point gap is fold-family error
(3:2 ×14, 4:3 ×8, 5:4 ×5, 3:4 ×3), exactly what genre-conditional tempo
ranges disambiguate. Success = **closing Acc1 toward Acc2 on replay,
with zero regression on the tracks that are already right.**

### A structural gift worth designing around

The genres that are spectrally *confusable* (house / deep house / tech
house / peak-time) mostly *share* tempo ranges, so confusing them is
harmless to the matcher. The genres the matcher needs distinguished
(DnB vs R&B, dubstep's halftime vs trance, hip-hop vs hardstyle) are
spectrally far apart. So the genre scorer's accuracy bar is **the
tempo-family partition, not the 20-profile partition** — a much easier
target, and the evaluation metric should be defined at that granularity
(group profiles into tempo families; score family-accuracy).

---

## 2. Isolation, defined (owner's answer, 2026-08-20)

> "sort of. i do not think one can accurately call a genre w/o some of
> the tempo related things like kick regularity, onset density, etc..
> *but* we shouldn't use actual detector bpm values.. just the distinct
> genre-determining metrics"

So the rule is **tempo-blind, rhythm-aware**:

| Signal | In the genre scorer? | Why |
| --- | --- | --- |
| `tempo_fit` (BPM vs profile prior) | **OUT** | Consumes the detector's BPM — the circularity being removed. |
| `top_cand_fit` (ACF candidates vs prior) | **OUT** | Same — it IS the detector's candidate list; that comparison moves into the matcher, where it belongs. |
| `onset_fit` (onset density) | **IN** | Rhythmic event *rate* measured from the onset stream directly — tempo-correlated by nature but not a detector output. |
| `kick_regularity_fit` | **IN** | Four-on-the-floor character; measured from kick-band energies at onsets, no BPM consumed. |
| `centroid_fit`, `zcr_fit`, `spectral_shape_fit`, `vocal_hnr/fmr_fit` | **IN** | The timbre/texture core. |

Caveat carried into the design: onset density still *correlates* with
tempo, so the genre scorer will never be fully tempo-orthogonal — that's
accepted (the owner's call), and it's another reason the matcher only
ever *selects among detector-proposed candidates* rather than generating
tempo evidence of its own.

---

## 3. Where the genre score comes from today: `_profile_score()` anatomy

For reference while redesigning (full detail in
`weights-and-thresholds.md`'s recommender section). Nine per-candidate
terms, each a raw fit value × a weight, summed — an arbitrary-scale
weighted sum of Gaussian log-densities (clipped at 6σ), NOT a
probability; ranking + softmax margin over candidates is what's
consumed:

| Term | Weight (today) | Measurement |
| --- | --- | --- |
| `tempo_fit` | 2.2 | Gaussian log-density of window BPM readings vs the profile's log2 tempo prior (μ, σ floored at 0.02). |
| `spectral_shape_fit` | 1.4 | Cosine similarity of the 64-band window mean vs the profile's `expected_bands` fingerprint, rescaled (sim−0.5)×2. |
| `onset_fit` | 1.0 | Gaussian fit of onsets/s vs per-profile `onset_density_mu/σ`. |
| `kick_regularity_fit` | 1.0 | (kick_regularity−0.5) × (expected kick-band energy−0.5) × 4 — rewards regular kicks only for profiles that expect them. |
| `zcr_fit` | 0.6 | Gaussian fit of zero-crossing rate vs per-profile μ/σ. |
| `centroid_fit` | 0.5 | Gaussian fit of spectral centroid vs per-profile μ/σ. **Known-broken μ basis** (linear-FFT live measurement vs log-band-derived μ — bug open since 2026-08-10, weight repeatedly cut because of it: 1.5→1.3→1.0→0.8→0.5→0.3→0.7→0.5). |
| `top_cand_fit` | 0.4 | Best Gaussian fit among ACF top-3 candidates vs the profile prior (was silently dead until 2026-08-09). |
| `vocal_fmr_fit` | 0.4 | Gaussian fit of vocal modulation rate; first-pass targets, never validated. |
| `vocal_hnr_fit` | 0.3 | Gaussian fit of vocal harmonicity; same caveat. |

Plus machinery around it: `detector_trust` (lock rate / confidence /
downbeat conf) scales the *confirmation margin* rather than the score;
softmax margin for cross-session comparability; a ridge-regression
offline weight-fitting path (`promote_weights.py`) that can override the
hand-tuned defaults (never auto-applied).

**Why "once upon a time it worked great" and then didn't:** three
structural reasons visible in the history. (1) `centroid_fit`'s μ
formula mismatch has been an open wound since 2026-08-10 — it supplied
+0.84 of a +0.99 wrong-answer margin in the ambient incident; every
weight change since has partly been compensation for it. (2) Weight
churn: nearly every weight has moved 3-6 times, largely LLM-suggested
one-session-at-a-time nudges — the composite is a moving target tuned
against whichever session was scored last (the standing
"agent-authored weights need validation" concern, live). (3) The tempo
terms (2.2 + 0.4 = 2.6 combined, the largest block) mean today's
"genre" score is substantially a tempo-agreement score — fine when the
detector is right, circular when it isn't, and useless as an
independent second opinion. The redesign removes (3) by construction,
fixes or retires (1) inside the isolated scorer where it can be
calibrated against ground truth, and answers (2) by validating against
labeled tracks in replay instead of per-session vibes.

---

## 4. Ground truth: Essentia-first (owner's call)

> "we should probably trust essentia a lot more than my library lol"

- **Primary:** Essentia, run offline/dev-side in training-kit (already a
  dev dependency — `RhythmExtractor2013`, `Danceability`, `KeyExtractor`
  are in `training_lib.py` today). For genre specifically, Essentia
  ships pretrained TensorFlow classifier models (Discogs-EffNet /
  MTG-Jamendo families) — heavier than the descriptor algorithms, but
  offline-only, so the no-heavy-deps runtime constraint is untouched.
  **Role clarified (owner, 2026-08-20):** Essentia is a library+models,
  not a harvestable dataset — so it is a *reference signal, not gospel*:
  log its per-track genre call side-by-side with ours (the same pattern
  `essentia_bpm`/`essentia_key` already follow in the training rows),
  review the disagreements, and tune toward **our own interpretation of
  correctness** case by case. Where we consistently agree, the label is
  settled for free; where we disagree, a human (the owner) arbitrates —
  that arbitration IS the ground truth this plan accumulates.
  **License note:** Essentia is AGPL-3.0 — fine for offline dev-side
  label generation (nothing links into the shipped runtime), consistent
  with how the 2026-08-13 tempo audit scoped madmom/TempoCNN
  ("offline, dev-side only, check model licenses"); the model weights
  carry their own (CC BY-NC-SA for some) — verify before adopting a
  specific model, per the 2026-08-08 licensing-audit discipline.
- **Secondary:** library tags — under repair, tiebreaker-grade only.
- **Tertiary:** hand-label the fold-problem set (~30 tracks the
  baseline classifies as non-1:1) — an afternoon, and these are the
  tracks the whole matcher exists for.
- Labels land in a manifest next to the replay baseline (numbers/labels
  only, no audio), at **tempo-family granularity** (§ 1) with the fine
  genre kept as an informational column.

---

## 5. The matcher (v0 sketch — deliberately tiny)

Keep it small enough that it cannot become weights with extra steps:

```
inputs:  detector top-2 candidates [(bpm_i, score_i)]   (already exposed)
         genre top-3 candidates    [(genre_j, conf_j)]  (isolated scorer)
         detector confidence + lock state               (Schmidt-style regime
                                                         switch WITH hysteresis)

HIGH regime (locked, confident):
    eligible = genres whose [bpm_hint_min, bpm_hint_max] (± soft margin,
               ~15% per the prefilter ADR) contain the locked BPM
    pick argmax conf_j over eligible; if none eligible, no recommendation
    (surface "genre/tempo disagreement" telemetry instead of forcing one)

LOW regime (unlocked / ambiguous):
    for each (bpm_i, genre_j) pair:
        match_ij = score_i * conf_j * range_fit(bpm_i, genre_j)
    range_fit = 1.0 in range, soft-decaying outside (one margin constant)
    pick argmax; the winning pair's bpm becomes the *matcher's endorsement*
    of that detector candidate — consumed the way genre evidence is today
    (candidate selection support), never as a generated tempo
```

Tunables: the range margin, the two regime thresholds (gain/release),
and possibly a floor on `conf_j`. That's it — four constants, all
replay-sweepable, all with engagement counters from day one (the
standing same-commit rule).

Containment (the chillstep lesson): the matcher can only ever endorse a
candidate the ACF itself proposed; regime switching is hysteretic so it
can't flap; every endorsement is corpus-logged with both candidate
lists so wrong picks are diagnosable after the fact.

Supersedes when it lands: the genre-evidence Gaussian boost
(`set_genre_tempo_evidence` consumers) in the LOW regime, and implements
the deferred BPM-prefilter ADR in the HIGH regime. Mood-prime and
tap-prime (manual evidence) are untouched — they are architecturally
distinct external evidence and stay so.

---

## 6. Staged plan

- **Stage 0 — ground truth.** Pick the Essentia genre model (license
  check first), label the 439-baseline tracks + the fold-problem set,
  commit the manifest. Decide the tempo-family partition (draft: slow
  {rap/rnb/chill ~70-95}, mid {house family ~110-130}, fast {trance/
  psytrance/hard ~135-155}, double {dnb ~165-180}, bimodal {dubstep} —
  needs owner eyes).
- **Stage 1 — the genre-pure scorer, in place (STARTED 2026-08-20).**
  Owner call: do NOT fork/redo `_profile_score()` — it is purpose-built
  and keeps its machinery (softmax margins, detector_trust gating,
  decider, telemetry, promoted-weights path). Instead the existing
  composite went genre-pure surgically: `tempo_fit` and `top_cand_fit`
  zeroed (kept as telemetry — the matcher needs their data), remaining
  weights rebalanced best-guess for the first runs (shape 2.2,
  onset/kick 1.5, zcr 0.9, centroid held 0.5 pending its formula bug,
  vocals 0.4/0.5) — recommender rc.18, weights doc v63, full rationale
  in docs/adr/vj-system.md. Still Stage 1: recalibrate μ/σ against the
  side-by-side Essentia comparison (§ 4) and fix-or-retire centroid on
  evidence, iterating the best-guess weights toward measured accuracy.
- **Stage 2 — the matcher.** Build § 5 behind a flag, replay-validated:
  Acc1 uplift on the baseline, zero regression, endorsement counters.
- **Stage 3 — rollout.** Owner-reviewed live sessions; retire the
  genre-evidence boost once the matcher demonstrably covers it; then
  this becomes the recommender's spine and the HMM thread (v3 Thread 1)
  can inherit the (bpm × genre) agreement structure as its prior.

Decisions for the owner before Stage 0 starts: which Essentia genre
model (license + quality tradeoff — needs a short comparison writeup);
the tempo-family partition; whether Stage 1's recalibration also
retires the vocal terms if they don't earn their keep against labels.
