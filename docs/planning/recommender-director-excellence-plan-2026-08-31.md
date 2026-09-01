# Recommender & Director Excellence Plan

Owner: JJ · Status: Draft for owner review (written at the 2026-08-31
tuning-experiment wrap) · Last updated: 2026-08-31

Goal: bring the **recommender** and **director** to best-in-class shape,
sequenced to land alongside **detector v3**. This plan converts the
2026-08-31 experiment's findings (`logs/replay/EXPERIMENT-2026-08-31.md`)
into a phased roadmap. Constants and claims below cite that ledger.

---

## Why this order: the dependency chain

```
labels (ground truth) -> recommender recalibration -> detector v3 -> director
```

- The recommender's scoring terms feed the genre tempo hints
  (`set_genre_tempo_evidence`) that detector v3 will lean on harder —
  the dose sweep proved hint strength is an amplifier of hint QUALITY
  (+10 Acc1 when right, −16 when wrong). Recalibration is therefore a
  **prerequisite** for v3's stronger evidence integration, not a
  parallel track.
- The director consumes detector lock state + recommender profile.
  Tuning it against today's inputs bakes in their errors; it goes last,
  after its inputs are trustworthy.
- Measurement comes before all tuning: two of our three quality metrics
  were found broken or missing this experiment (wall-clock churn bug,
  0% section-hint coverage in replay).

---

## Phase 0 — Ground truth (blocked on owner; everything else queues behind it)

1. **Owner arbitration pass** over the 26+32 disputed rows in
   `genre_labels-2026-08-31-queue.md`. This is the single gating item.
2. Expand the labeled corpus: favorites playlist (3.5 h, skipped in the
   experiment) + remaining media playlists through the Stage-0 labeler.
3. **Use high-gain dose probes as a calibration instrument**: a boost-1.0
   replay run exposes latent contested-evidence tracks (the Blackout
   Riddim class — wrong-side evidence that never wins at 0.1 and is
   invisible to the miss lists). Run one high-gain sweep per playlist,
   diff per-track, and add every exposed track to the arbitration queue.
   The experiment accidentally invented this technique; formalize it.
4. Commit the arbitrated label set as a versioned baseline in
   training-kit (`genre_labels-<date>.json` + queue resolution notes).

### Phase 0 addendum (2026-09-01, owner direction): ID3-driven feature calibration

Verified against the live library: 2,812 audio files, 2,810 (99.9%)
carry genre tags, only 35 distinct values in clean DJ-pool vocabulary
(House 461, Tech House 397, Hip-Hop 398, Techno 163, Trance 102, Deep
House 82, DnB 68, Dubstep 53, ...). Caveat: 'Dance' (638, 23%) is an
umbrella tag — exclude it from per-genre fitting or arbitrate it via
Essentia agreement.

New tool (training-kit): **library feature scan** — batch-decode every
track and compute the EXACT features the recommender scores (spectral
centroid, zcr, onset density, kick regularity, ...) through the same
`unicornviz.audio.analyzer` code path the live app uses (identical
scaling, or the fitted mu's won't transfer). Group per normalized ID3
genre -> per-profile empirical distributions (median/IQR -> mu/sigma).
This replaces guess-based profile constants with fits from ~2,800
producer-tagged tracks (vs the 204-track Essentia set).

Bonus: a three-way agreement report (ID3 x Essentia x current
recommender behavior) auto-arbitrates most of the label queue — only
three-way disagreements need the owner's eyes, shrinking Phase 0's
manual gate.

## Phase 1 — Recommender recalibration (Stage-1)

Target: average-track genre-acc (cluster granularity) **59% → 80%+**,
flicker archetypes resolved. All changes follow the standing rules:
flag+confirm before recommender-weight changes; weights-doc /
`_RECOMMENDER_VERSION` / ADR sync in the same commit; engagement
counters for any new tunable.

1. **μ-recalibration against arbitrated labels**: refit each profile's
   `spectral_centroid_mu`, `bpm_prior_mu/sigma` (profiles.py) so the
   named archetypes stop misreading. Regression cases, pinned as tests:
   trance edge-rider trio (Fiesta Loca / Dancing Queen / Feel The
   Light), dubstep tie-break at ~130 (MFN, Blackout Riddim), the
   rap_rnb-on-mid cluster (Memories / Pink Pony Club / Velvet After
   Dark), Love Spirit → ambient.
2. **Split the shared margin** (`profile_reco_bpm_prefilter_margin` →
   prefilter margin + matcher range_fit margin, two constants).
   Experiment-proven: one knob provably cannot serve both regimes
   (curveballs accuracy vs toughies stability). Small change, big
   headroom unlock; margin 0.10's toughies anomaly becomes recoverable.
3. **Decider-side applied-profile hysteresis**: the Love Spirit 2:3
   flicker (82–91% wrong-profile row share) is a decider problem, not
   an evidence problem (proven: boost changes never moved it). Add
   switch-damping at the applied-profile layer.
4. **Revisit genre re-priming after lock** (parked 2026-08-14, owner
   wants it reconsidered when recommender work resumes — this is that
   moment).
5. Validation protocol per change: fixed seeds {3,11}, house +
   curveballs 01/03 as the veto set, toughies diagnostic-only (owner
   ruling 2026-08-31), one variable at a time, per-track diffs.

## Phase 2 — Evidence channel, v3-ready

1. **Lock-state-aware evidence gating** (experiment rec #2): evidence
   engages when unlocked or fold-ambiguous (where 1.0 rescued +10
   Acc1), never against an established high-confidence lock (where it
   harassed, +51% churn). Design doc first; this is the piece that
   makes a raised cap safe.
1b. **Chicken/egg resolution principle (owner + strategist, 2026-09-01)**:
   the loop (genre hints tempo, tempo gates genre) is broken by PHASE
   and CONFIDENCE, with disagreement as a diagnostic:
   - Pre-lock / low ACF confidence: genre evidence ADVISES tempo
     (current gate, kept).
   - Post-confident-lock: tempo GATES genre — the applied profile MUST
     contain the locked BPM within the (split) margin. Mandatory, per
     owner.
   - Escape valve: persistent strong out-of-range endorsement (matcher
     repeatedly backing a profile the locked BPM excludes, on
     tempo-independent character) does NOT override the mandate and is
     NOT suppressed — it raises a FOLD-SUSPECT alarm that re-opens the
     detector's fold hypotheses. We watched the un-valved loop close
     the wrong way at boost 1.0 (Feel The Light: evidence folded the
     BPM, then the profile flipped to match the folded BPM — error
     reinforcing itself, entrenched at cov 95%). Disagreement is
     information; route it to re-decision, not to either side winning.
   Feeds directly into the detector v3 design brief.
2. **Raise the boost cap post-recalibration** behind that gate: sweep
   0.1 → 0.3 → 0.5 with the recalibrated profiles; the dose data
   predicts rescues dominate once archetype evidence is net-right.
3. Wire the amplifier findings into detector v3's design brief: v3
   should treat genre evidence as a first-class fold disambiguator with
   the gate above, not a background nudge.

## Phase 3 — Director

1. **Fix measurement first** (already queued in the consensus commit):
   capture-time-based churn and director-rate in the training-kit
   scorer; then add the replacement director-quality metric
   ((transitions + drops) / audio-hour) as a standing scorecard line.
2. **Close the section-hint gap**: replay corpora show 0.0% song-
   structure hint coverage — the director is flying blind in replay,
   and drop-alignment quality is unmeasurable. Wire mixer-store
   structure hints into the replay harness so director events can be
   scored against actual musical structure (drop fired at a real drop?
   build respected?).
3. **Ground-truth the LLM director rubric**: the LLM's 2.5–3.75 ratings
   are our only director judge and they moved with boost dose (3.0
   floor at 1.0), so they detect something real — but they've never
   been validated against the owner's own judgment. One session: owner
   rates a handful of replays blind, compare to LLM scores, adjust the
   rubric until they agree.
4. **Phrase-bias validation**: with section hints in replay, validate
   `_phrase_bias()` multipliers and `_PHRASE_ROLE_BARS` against labeled
   phrase boundaries (mixer beat grids), the same isolated A/B protocol
   the detector constants got. The drop trigger/sustain split (core
   beta.99) gets its first measured validation here.
5. Directed by data, not vibes: any director constant that survives
   validation gets its ADR entry; any that doesn't gets the
   release-confidence treatment (bracket, verdict, pin).

## Sequencing with detector v3

- Phase 0 can start immediately (owner arbitration + labeler runs).
- Phase 1 does not need v3 and should land BEFORE it (v3 wants clean
  evidence).
- Phase 2's gate design should be co-designed with v3's architecture.
- Phase 3 rides after v3 stabilizes lock behavior — director tuning
  against a moving detector re-measures nothing.

## Standing constraints (memories/CLAUDE.md, restated so they ride along)

- Flag + confirm before recommender-weight or detector changes driven
  by Essentia/LLM deltas alone.
- Weights doc + subsystem versions (`_RECOMMENDER_VERSION`,
  `_DIRECTOR_VERSION`) + ADR sync in the same commit as any constant
  change; engagement counters for new tunables in the same commit.
- No architecture changes inside tuning passes; design docs first.
- This file is uncommitted until the experiment consensus commit; link
  it from `docs/README.md` planning index in that commit.
