"""Audio profile system for frequency-response tuning by genre.

Each profile defines:
- Frequency range emphasis for bass/mid/treble
- FFT band grouping and weighting
- Reactivity sensitivity curve
- Beat detection thresholds
- A BPM prior and a set of spectral targets (centroid, ZCR, onset density,
  and a 64-band cosine-similarity fingerprint) used by the Auto VJ profile
  recommender to score how well live audio matches each genre

Provenance of the spectral targets: these aren't arbitrary numbers. Each
profile's spectral fingerprint and acoustic characteristics are synthesized
from published music-information-retrieval research — AcousticBrainz's
large-scale per-genre spectral descriptor corpus, the GTZAN genre dataset
(Tzanetakis & Cook, 2002), the FMA dataset (Defferrard et al., 2017,
106k+ tracks across 161 genres), and EDM-specific classification literature
(Sturm 2012; Bonnin & Jannach 2014; Schedl et al. 2018) characterizing
techno/trance/house/DnB by their sub-bass-to-treble energy ratios. See
``tools/gen_spectral_fingerprints.py`` for the synthesis pipeline and prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class AudioProfile:
    """Audio analysis profile for a specific genre or style."""

    name: str
    description: str
    # Frequency ranges (Hz) for bass/mid/treble detection
    bass_min: float
    bass_max: float
    mid_min: float
    mid_max: float
    treble_min: float
    treble_max: float
    # Relative emphasis (weight) for each band in mixed reactivity
    bass_weight: float = 1.0
    mid_weight: float = 1.0
    treble_weight: float = 1.0
    # Beat detection sensitivity (lower = more sensitive)
    beat_threshold: float = 1.2
    # Reactivity smoothing (0.0-1.0, higher = more smoothing)
    smoothing: float = 0.1
    # Frequency response curve name for FFT shaping
    curve: str = "flat"

    # ------------------------------------------------------------------
    # Beat-detection shaping (used by Analyzer + BeatTracker).
    # Profiles inform "what does a beat look like in this genre?" so the
    # onset detector and tempo prior have realistic expectations.
    # ------------------------------------------------------------------

    # Per-band emphasis applied to spectral flux during onset detection.
    # Kick-driven genres (house/rap/techno) should weight bass high so
    # hi-hats and percussion do not pollute the onset stream. Defaults
    # match the prior hardcoded analyzer weights for backward compat.
    onset_bass_emphasis: float = 1.8
    onset_mid_emphasis: float = 1.2
    onset_treble_emphasis: float = 1.0

    # Perceptual tempo prior centre (BPM) and width (in log2(BPM) units).
    # Used by the BeatTracker to bias the ACF score toward genre-typical
    # tempos. A wider sigma means weaker bias; a narrower sigma means the
    # detector strongly prefers the genre's canonical tempo range.
    bpm_prior_mu: float = 120.0
    bpm_prior_sigma: float = 0.55
    # Optional user-facing "sweet spot" range for HUD / diagnostics.
    bpm_hint_min: float | None = None
    bpm_hint_max: float | None = None

    # Spectral features for the profile recommender.  Set to None to skip
    # scoring on that dimension (safe for profiles without calibrated values).
    #
    # 2026-09-10 (zone-map batch, recommender rc.41): spectral_centroid_mu/
    # spectral_centroid_sigma and their scoring term (centroid_fit) removed
    # entirely -- not just the weight (retired at 0.0 since rc.19,
    # 2026-08-20). Real cause, confirmed on 57 library tracks across five
    # brightness formulations (log-band centroid, linear-FFT centroid,
    # log2-frequency centroid, >=4kHz energy fraction, rolloff-85): every one
    # showed within-family spread 2-4x the between-family separation, with
    # genre-nonsensical orderings. Scalar brightness of a mastered full mix
    # tracks production/mastering, not genre -- the real spectral evidence
    # lives in the full 64-band distribution, which spectral_shape_fit
    # already scores at full resolution. Owner: "officially retired and dead
    # forever." See docs/adr/vj-system.md.
    # zcr_mu: zero-crossing rate per sample — correlates with harshness/noise content
    # zcr_sigma: how tightly this genre's zcr clusters around zcr_mu. Mirrors
    #   spectral_centroid_sigma's role -- a genre with a very consistent,
    #   narrow percussive-vs-tonal texture (e.g. cleanly quantized electronic
    #   production) should be tight; one whose zcr varies a lot by track/
    #   subgenre/production style should be wide.
    # onset_density_mu: expected onset events per second (with kick-biased weighting)
    # onset_density_sigma: how tightly this genre's rhythmic density clusters
    #   around onset_density_mu. A mechanically regular pulse (four-on-the-
    #   floor house/techno, psytrance's rolling kick) should be tight even
    #   when its zcr/centroid/bpm sigma is wide for other reasons; a
    #   syncopated or variable-density genre (breaks, garage's swing,
    #   dubstep's sparse hits) should be wide regardless of how tight its
    #   other sigmas are -- rhythmic regularity and timbral/tempo spread are
    #   independent properties of a genre, not the same axis in disguise.
    #   2026-08-09: added as coarse tight/medium/wide tiers (zcr: 0.015/
    #   0.020/0.028, onset: 0.7/1.0/1.5) from genre-convention research plus
    #   the one genre-tagged validated training bucket available (house) --
    #   not fitted values. 0.020/1.0 (medium) are the defaults for any
    #   profile that doesn't set these explicitly, mirroring how 400 Hz was
    #   spectral_centroid_sigma's pre-per-profile fixed constant. See
    #   drop-ins/auto-vj-01/docs/weights-and-thresholds.md and docs/adr/
    #   vj-system.md for the full per-profile rationale and the plan to
    #   replace these with measured values once broader genre-tagged
    #   training data exists.
    #
    #   2026-09-04 (recommender rc.30): the "once broader genre-tagged
    #   training data exists" plan above landed for the 12 profiles with a
    #   real training-list corpus -- NOT from the raw per-frame corpus rows
    #   used for the other evidence-based fields this session (a raw
    #   per-row `zcr` field on those was, it turned out, never actually
    #   wired up -- confirmed by grep across all 827 packaged
    #   assets/training/sets/**/*.jsonl files: zero contain it), but from
    #   `mean_zcr`/`onset_density` on the `profile_recommendation` keyframe
    #   rows already logged into assets/training/accelerated/<list>/**/
    #   (thousands of rows, 11-54 tracks per profile -- real and copious,
    #   just not where the raw-per-frame check first looked). Same per-
    #   track-then-robust-stat methodology as bpm_prior_mu/sigma and
    #   vocal_hnr_mu/sigma: median per track (>=3 keyframe rows required),
    #   then robust median (-> mu) / MAD-derived sigma (-> sigma, floored
    #   at 0.03) across those per-track points, raw linear space for both
    #   fields.
    #
    #   2026-09-04 (recommender rc.32): the 0.03 floor above was WRONG for
    #   this feature -- it was copy-pasted from vocal_hnr/vocal_fmr's own
    #   floor without checking scale. Those live on [0,1]; zcr's entire
    #   genre-to-genre range is only ~0.03-0.09 (a 0.06-wide span), so a
    #   0.03 floor is over HALF that whole range -- it swallowed every
    #   profile's real MAD-derived sigma (which came in at 0.0116-0.0217,
    #   comfortably real, not noise) and flattened all 12 to the same
    #   number. Floor dropped to 0.008 (below the smallest real value
    #   measured across the roster, so it doesn't bind for any of them --
    #   still there as a safety net against a hypothetical future profile
    #   with a much tighter or thinner sample). zcr_sigma now carries its
    #   own real per-profile value again (tech_house tightest at 0.0116,
    #   dubstep widest at 0.0217).
    #
    #   Honest caveat, checked rather than assumed: even with real sigma,
    #   most ADJACENT-ranked profiles by zcr_mu are still within about
    #   1 sigma of each other (e.g. deep_house 0.0372 vs hyphy 0.0376, a
    #   0.0004 gap against ~0.02 sigmas) -- zcr_fit's real discriminating
    #   power lives mostly at the tails of the roster (chillstep/ambient/
    #   deep_house/hyphy cluster low; trance/drum_and_bass/dubstep/house
    #   cluster high), not between most individual genre pairs. Fixing the
    #   floor makes the TERM correctly calibrated (a tight-clustering
    #   profile like tech_house now scores confidently, a noisier one like
    #   dubstep doesn't get false confidence) -- it does not turn zcr into
    #   a strong pairwise discriminator, because the underlying acoustic
    #   feature genuinely doesn't separate most of this roster that
    #   cleanly. `zcr_mu` itself still spans ~2.1x roster-wide (chillstep
    #   0.0297 to trance 0.0627). Worth a flag:
    #   ambient's onset_density_mu moved from a hand-guessed 0.4 to a
    #   measured 2.66 (~6.6x) and chillstep similarly (1.5 -> 2.94) --
    #   applied as real per-track evidence (no known contamination
    #   mechanism analogous to the BPM ACF-lock issue applies to onset
    #   *counting*, which doesn't need periodicity the way tempo tracking
    #   does), but the magnitude is large enough to flag for a look rather
    #   than treat as quietly settled -- these training lists' tracks may
    #   simply carry more transient/textural onset activity than the old
    #   "ambient/chillstep = sparse" assumption expected, or may warrant a
    #   closer per-track check. `psytrance`/`hard_techno`/`hardstyle`/
    #   `synthwave`/`electronic` untouched (disabled or no corpus of their
    #   own).
    #
    #   2026-09-04 (recommender rc.33, tuning session): the rc.32 zcr_sigma
    #   values above (0.0116-0.0217) and the original onset_density_sigma
    #   values (0.1779-0.9266) are BOTH SUPERSEDED here -- found live,
    #   the same night, running six fresh accelerated-replay sessions for
    #   a tuning pass: `zcr_fit`/`onset_fit` compare against `mean_zcr`/
    #   `onset_density`, values the recommender computes freshly each
    #   evaluation CYCLE (a rolling window of live samples -- see
    #   `_update_profile_recommendation()`'s own sample accumulation),
    #   NOT the per-track-smoothed value either sigma was fit from. Both
    #   prior fits collapsed many cycles down to one MEDIAN per track
    #   first (deliberately, to stop one noisy track dominating a genre's
    #   estimate) -- correct for `mu`, but it strips out exactly the
    #   cycle-to-cycle variation the live scorer actually sees, leaving
    #   sigma far too tight for what it's compared against. Measured
    #   directly on `peak_time`'s own fresh replay session: live
    #   `onset_density` read stdev 0.77 against a stored sigma of 0.19 --
    #   4x tighter than reality -- and `peak_time` scored dead last
    #   (11/11) on the full weighted composite against its OWN list,
    #   never once recommended correctly across a full ~1h session.
    #   Zeroing `spectral_shape_fit`'s weight entirely (a live experiment,
    #   not applied) did NOT fix this -- `peak_time` stayed 11/11 --
    #   proving `onset_fit`'s over-tight sigma, not the ribbon fit, was
    #   the actual driver. Confirmed the same order-of-magnitude gap holds
    #   across all 12 real-corpus profiles for both fields (pooled raw
    #   per-cycle `mean_zcr`/`onset_density` stdev, 5460-34254 rows each,
    #   from `assets/training/accelerated/`): `zcr` cycle-to-cycle stdev
    #   runs 0.0184-0.0343 (roughly 1.5-2x the rc.32 per-track values);
    #   `onset_density` cycle-to-cycle stdev runs 0.59-1.08 (roughly
    #   3-6x the original per-track values for every profile except
    #   `techno`, whose per-track spread was already unusually wide).
    #   `mu` values are UNCHANGED -- the per-track-median center was
    #   never the problem, only the width. See docs/adr/vj-system.md
    #   "zcr_sigma / onset_density_sigma: Fit-vs-Live Scale Mismatch" for
    #   the full diagnostic (including the composite-rank table across
    #   all six fresh sessions) and weights-and-thresholds.md for the
    #   corrected per-profile table.
    zcr_mu: float | None = None
    zcr_sigma: float = 0.020
    onset_density_mu: float | None = None
    onset_density_sigma: float = 1.0

    # Vocal-presence heuristics (2026-07-08, first-pass/unvalidated starting
    # values -- not yet checked against real session data the way the
    # spectral fingerprints below were). See Analyzer._compute_vocal_hnr /
    # _compute_vocal_fmr in unicornviz/audio/analyzer.py for what these
    # measure and their known limitations (neither is a true vocal detector).
    # vocal_hnr_mu: expected 0-1 harmonic-to-noise-ratio in the vocal-formant
    #   band. Weak genre discriminator on its own (most genres have *some*
    #   harmonic bass/lead content in that band) -- mainly separates
    #   noise/percussion-dominated material from anything tonal.
    # vocal_fmr_mu: expected 0-1 fraction of formant-band modulation energy
    #   in the 3-8 Hz syllabic/vibrato rate. The stronger genre
    #   discriminator: steady 4/4 kick-driven modulation sits at the beat
    #   rate (~2 Hz at 120 BPM), well below this band, so instrumental
    #   dance genres should score meaningfully lower than sung/rapped vocal.
    # None on a profile = not calibrated, skip scoring on that dimension.
    #
    # 2026-09-04: vocal_hnr_sigma/vocal_fmr_sigma below replace the flat,
    # hand-picked 0.20/0.15 sigma _profile_score() used for EVERY profile
    # regardless of genre (drop-ins/auto-vj-01/auto_vj.py) -- a real per-
    # profile fit needs a per-profile spread, not one constant borrowed
    # across the whole roster. Computed the same way as everything else
    # this session: per-track median first (>=10 rows required for a
    # track to count, so one short/noisy clip can't dominate), then
    # robust median (-> the mu fields) and MAD-derived sigma (floored at
    # 0.03) across those per-track points, in raw linear [0,1] space
    # (these are already bounded ratios, unlike BPM which needs log2).
    # A profile with vocal_hnr_mu/vocal_fmr_mu set but the matching sigma
    # left None falls back to the legacy flat 0.20/0.15 constant in
    # _profile_score() -- additive/opt-in per profile, same pattern as
    # expected_bands_sigma above.
    vocal_hnr_mu: float | None = None
    vocal_fmr_mu: float | None = None
    vocal_hnr_sigma: float | None = None
    vocal_fmr_sigma: float | None = None
    # spectral_contrast_mu/sigma (2026-09-01): mean log peak/valley gap
    # over 6 octave bands (analyzer._CONTRAST_*) — "peakiness"
    # (harmonic-rich vs dense/noisy). DELIBERATELY unset on every
    # profile at launch: the term is dormant (weight 0.0) until the
    # library bake-off fits real per-genre values. Do NOT hand-author
    # these — the 2026-08-31 instrument audit is the standing reason.
    spectral_contrast_mu: float | None = None
    spectral_contrast_sigma: float = 0.15

    # 64-element normalized (0.0–1.0) spectral fingerprint: expected relative
    # magnitude per log-spaced band (30 Hz – 16 kHz, matching audio_spectrum.py).
    # None = not yet calibrated.
    #
    # 2026-09-04 (recommender rc.28, "ribbon" redesign): for a profile that
    # also sets expected_bands_sigma below, spectral_shape_fit is a per-band
    # Gaussian log-density (mean across bands) against this as mu and that
    # as sigma -- NOT cosine similarity. Root cause this replaced: flat
    # cosine similarity on a single point vector rewards whichever profile
    # has the tallest/smoothest low-band plateau as a generic runner-up
    # (measured: EVERY pair of this roster's data-derived fingerprints was
    # >=0.94 cosine-similar to every other, so the term barely discriminated
    # anything). Root cause of THAT: expected_bands used to be the frame-
    # level mean `bands` vector across an entire playlist session -- owner:
    # averaging hundreds of frames from many different tracks converges
    # toward "the generic shape of any decaying spectrum," erasing the
    # texture that's actually genre-specific (the CLT smooths away
    # per-track structure, it doesn't reveal a genre's real "shape"). Fixed
    # by aggregating to one point PER TRACK first (so a long-playing track
    # doesn't dominate a short one), then taking robust (median, not mean --
    # outlier tracks tossed) statistics ACROSS those per-track points:
    # median -> this field, MAD-derived spread -> expected_bands_sigma.
    # See docs/adr/vj-system.md "Spectral-Shape Ribbon Redesign" for the
    # full methodology, the frame-vs-track scoring bug caught along the
    # way, and the weight-rebalancing finding (this term went from a near-
    # constant +0.95-ish bonus under cosine to a real, wide-swinging
    # discriminator under the ribbon fit -- its old weight, 2.5, was tuned
    # for the former and overpowers the composite under the latter; owner-
    # validated new weight is 0.7, see weights-and-thresholds.md).
    #
    # A profile with expected_bands set but expected_bands_sigma left None
    # (every hand-authored profile not yet re-derived: psytrance,
    # hard_techno, hardstyle, synthwave) keeps the OLD cosine-similarity
    # path unchanged -- this redesign is additive/opt-in per profile, not a
    # wholesale behavior change for profiles with no ribbon data yet.
    #
    # 2026-09-04 (recommender rc.34, tuning session): the rc.28 per-TRACK
    # aggregation above is SUPERSEDED here for the same reason
    # zcr_sigma/onset_density_sigma got fixed earlier the same night --
    # `spectral_shape_fit` compares against `band_mean_vec`, a live
    # ~16-second ROLLING WINDOW mean (`profile_auto_reco_window_s`,
    # default 16.0s), not a whole-track mean. Averaging over an entire
    # track (3-8 minutes) smooths out section-to-section variation
    # (intro/build/drop/breakdown) that a 16s window still shows in full
    # -- so the rc.28 sigma was calibrated for a far smoother signal than
    # what it's actually compared against, the exact class of bug already
    # found and fixed for the two zcr/onset terms. Found live the same
    # tuning session: `house` scored 7th of 12 candidates against its OWN
    # list; `peak_time` scored DEAD LAST (12/12); `ambient` topped
    # `spectral_shape_fit` on every single list regardless of genre (the
    # fourth recurrence of "one profile sweeps the ribbon fit," after
    # dubstep/house/techno earlier this project). Re-fit both `mu` and
    # `sigma` together this time (unlike the zcr/onset fix, which only
    # needed sigma corrected) -- because the aggregation UNIT changed
    # (per-track -> per-16s-window), both statistics needed recomputing
    # from the same windows for consistency, not just the spread. Method:
    # for each profile's own training-list corpus, group heartbeat rows
    # by track, accumulate non-overlapping ~16s chunks (matching the live
    # window), take the per-band mean within each chunk, then robust
    # median (-> mu) / MAD-derived sigma (-> sigma, floored at 0.01)
    # across ALL those chunks (pooled across tracks, not one point per
    # track). Verified against real corpus data before landing: `house`
    # went from rank 7/12 to 1/12 on its own list, `peak_time` from
    # 12/12 to 4/12, `tech_house` (disabled) from 8/12 to 1/12,
    # `deep_house` from 10/12 to 3/12 -- `ambient` stayed 1/12 (the fix
    # didn't regress the one profile that was already working). See
    # docs/adr/vj-system.md "spectral_shape_fit: Per-Track vs. Live
    # 16s-Window Aggregation Mismatch" for the full diagnostic.
    # `electronic` mirrors `house`'s new values, same as every other
    # ribbon field, per that profile's own control-pair design.
    expected_bands: list[float] | None = None
    # Per-band spread (same units/order as expected_bands), robust MAD-
    # derived, floored at 15% of that band's own median so a tiny real
    # sample doesn't produce an unrealistically confident (near-zero)
    # sigma. None = this profile has no ribbon; expected_bands (if set)
    # scores via the legacy cosine-similarity path instead. See
    # expected_bands' own field comment above for the full story.
    expected_bands_sigma: list[float] | None = None

    # Capability-aware disable, not delete (mirrors unicorn-horn ADR-0003's
    # pattern for stem toggles): a disabled profile is excluded from
    # discovery -- list_profiles() (Alt+A cycling) and the auto-vj
    # recommender's candidate pool (enabled_profiles()) -- but get_profile()
    # still resolves it directly by name. Existing config referencing a
    # disabled profile by key, or any other explicit lookup, keeps working;
    # only random/automatic discovery skips it.
    enabled: bool = True

    def preferred_bpm_range(self) -> tuple[int, int]:
        """Return a concise user-facing BPM sweet-spot range.

        When a profile declares explicit hints, prefer those. Otherwise derive a
        compact display range from the BPM prior width rather than exposing the
        full statistical prior spread, which is too wide for HUD use.
        """
        if self.bpm_hint_min is not None and self.bpm_hint_max is not None:
            lo = int(round(float(self.bpm_hint_min)))
            hi = int(round(float(self.bpm_hint_max)))
            return max(1, lo), max(lo + 1, hi)
        span_ratio = max(0.06, min(0.14, float(self.bpm_prior_sigma) * 0.35))
        lo = max(1, int(round(float(self.bpm_prior_mu) * (1.0 - span_ratio))))
        hi = max(lo + 1, int(round(float(self.bpm_prior_mu) * (1.0 + span_ratio))))
        return lo, hi

    def hud_bpm_range_label(self) -> str:
        """Return the preferred BPM range in compact HUD form."""
        lo, hi = self.preferred_bpm_range()
        return f'{lo}-{hi}'


# Profile definitions tuned for different genres and styles
PROFILES: Dict[str, AudioProfile] = {
    "house": AudioProfile(
        name="House",
        description="Deep bass emphasis, steady mid kick, treble for hi-hats",
        bass_min=20.0,
        bass_max=250.0,
        mid_min=250.0,
        mid_max=2000.0,
        treble_min=2000.0,
        treble_max=20000.0,
        bass_weight=1.2,
        mid_weight=1.0,
        treble_weight=0.9,
        beat_threshold=1.15,
        smoothing=0.12,
        curve="bass_boost",
        # House: kick-driven 4/4 at 118-130 BPM.  Raw-spectrum flux already
        # amplifies kick transients strongly; moderate the bass weight so
        # hi-hat flux (which carries beat subdivisions) still contributes.
        onset_bass_emphasis=1.4,
        onset_mid_emphasis=1.0,
        onset_treble_emphasis=0.75,
        # 2026-08-10: house-family consolidation (owner philosophy pass --
        # "lean harder on bpm than bright/darker" -- see docs/adr/vj-system.md
        # for the full account). Bands moved from soft/overlapping to
        # deliberately adjacent: deep_house 112-118, house 118-126,
        # tech_house 127-134. mu is the band center; sigma tightened from
        # 0.35 to 0.10 -- as tight as it can usefully go, since
        # auto_vj.py's tempo_fit scoring floors sigma at 0.08 (a value
        # below that has zero additional effect on the actual composite
        # score). Note this only sharpens the RECOMMENDER's genre
        # discrimination -- beat_grid.py's own detector-search floor
        # (_MIN_PROFILE_PRIOR_SIGMA = 0.45) is intentionally untouched, so
        # this doesn't narrow what tempo the detector searches for, only
        # how confidently the recommender favors this profile once a tempo
        # is found.
        # 2026-08-14: reversed the independence above on purpose -- owner
        # spent real time hand-dialing bpm_hint_min/max as the actual
        # intended per-genre expectation, so sigma now derives FROM the
        # hint band instead of the other way around: sigma set so +-1
        # sigma (log2 space) just covers [bpm_hint_min, bpm_hint_max],
        # rounded with a small buffer. Applied identically across all 16
        # profiles in the same pass.
        # 2026-08-14 (same night): unclamped. House's true hint-band value
        # (0.0505) originally sat below the recommender's tempo_fit sigma
        # floor (0.08 at the time), so the *stored* value here was rounded
        # up to 0.08 to match what would actually bind -- discarding the
        # true, sharper number. Recommender/detector genre coupling was cut
        # entirely the same night (see docs/adr/vj-system.md), and the
        # runtime floor dropped 0.08 -> 0.02, well under every profile's
        # true value (tightest: dubstep at 0.0218) -- so every profile now
        # stores and uses its real hint-band-derived sigma, full range
        # 0.0218-0.30 across the roster, nothing clamped away.
        #
        # 2026-09-04 (recommender rc.28, evidence-based sigma pass):
        # bpm_prior_sigma 0.0505 -> 0.0297, from real per-track BPM
        # spread on training-house-01 (log2-space median/MAD across 15
        # tracks' own per-track medians -- the same "aggregate per track
        # first, robust stat across tracks" methodology already used for
        # expected_bands_sigma). mu is DELIBERATELY left at the owner-
        # dialed 122.0, not moved to the real measured median (128.1) --
        # see docs/adr/vj-system.md "House-Family BPM Cluster Finding"
        # for why: the four house-family profiles' real per-track medians
        # (house 128.1, deep_house 126.4, tech_house 129.9, peak_time
        # 129.9) cluster within ~3.5 BPM of each other, far tighter than
        # the deliberately-separated, owner-hand-dialed non-overlapping
        # bands this profile's own bpm_hint_min/max still reflect --
        # updating mu to match would collapse that intentional design,
        # a decision this pass does not make unilaterally.
        #
        # 2026-09-10 (zone-map batch, owner-provided genre BPM table):
        # bpm_hint_min 118 -> 120, narrowing the low edge against the new
        # 'dance'/electronic-family split below it. mu (122.0) still sits
        # comfortably inside the new band, left unchanged.
        bpm_prior_mu=122.0,
        bpm_prior_sigma=0.0297,
        bpm_hint_min=120.0,
        bpm_hint_max=126.0,
        zcr_mu=0.0372,
        zcr_sigma=0.0406,
        onset_density_mu=2.9223,
        onset_density_sigma=0.552,
        # 2026-09-04 (recommender rc.29, per-track median-of-medians re-fit,
        # n=15 tracks): supersedes the 2026-09-03 flat-per-row median below
        # -- mu shifted 0.4524->0.4347 / 0.3344->0.3315 and this profile now
        # also carries a real fitted sigma (was the flat 0.20/0.15 constant
        # every profile shared; see vocal_hnr_sigma/vocal_fmr_sigma's own
        # field comment above for the methodology).
        #
        # 2026-09-03 (recommender rc.27, vocal-term calibration): median
        # vocal_hnr/vocal_fmr from training-house-01's own packaged corpus
        # (both seeds, same rows as the expected_bands derivation below).
        # Replaces the generic 0.35/0.25 default every profile in this
        # roster started with. See docs/adr/vj-system.md "Data-Derived
        # expected_bands" vocal-calibration addendum for the full
        # methodology, the deep_house confound it fixed, and the caveat
        # that calibrating shifted broad cross-list dominance onto house.
        vocal_hnr_mu=0.4429,
        vocal_fmr_mu=0.3343,
        vocal_hnr_sigma=0.1797,
        vocal_fmr_sigma=0.0624,
        # 2026-09-03 (recommender rc.27, data-derived fingerprints): mean of
        # the 64-band `bands` feature over training-house-01's own packaged
        # corpus (both seeds pooled, ~7.5k heartbeats). Replaces a hand-
        # authored jagged multi-peak array -- found live (dubstep-wins-on-
        # house diagnosis) that every *measured* band-mean vector is a
        # smooth, monotonically decaying curve (an artifact of averaging
        # bands across many different tracks/onsets over time), so a
        # hand-authored jagged fingerprint could never cosine-match real
        # audio well regardless of genre -- house's own shipped fingerprint
        # scored the WORST self-similarity of the whole roster (0.671)
        # against its own list. See docs/adr/vj-system.md "Data-Derived
        # expected_bands" and weights-and-thresholds.md's profile-
        # fingerprint section for the full methodology and gate results.
        # 2026-09-10 (zone-map batch, Phase 5 fingerprint refresh): re-derived pooling ALL packaged buckets under this list's own training slug (same per-track median/MAD ribbon methodology), including the owner's pilot-run tracks from this same session.
        expected_bands=[
            0.714, 0.716, 0.722, 0.722, 0.725, 0.725, 0.725, 0.716,
            0.679, 0.634, 0.634, 0.634, 0.634, 0.525, 0.411, 0.411,
            0.413, 0.379, 0.326, 0.331, 0.322, 0.322, 0.303, 0.278,
            0.254, 0.241, 0.222, 0.210, 0.190, 0.178, 0.172, 0.172,
            0.153, 0.156, 0.123, 0.114, 0.110, 0.102, 0.092, 0.095,
            0.096, 0.081, 0.079, 0.070, 0.073, 0.060, 0.058, 0.056,
            0.057, 0.058, 0.056, 0.050, 0.050, 0.048, 0.045, 0.041,
            0.037, 0.031, 0.029, 0.024, 0.018, 0.013, 0.010, 0.007,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.107, 0.107, 0.108, 0.108, 0.109, 0.109, 0.109, 0.107,
            0.102, 0.095, 0.095, 0.095, 0.095, 0.079, 0.076, 0.080,
            0.082, 0.062, 0.066, 0.058, 0.055, 0.067, 0.088, 0.096,
            0.104, 0.084, 0.076, 0.084, 0.072, 0.071, 0.070, 0.069,
            0.070, 0.064, 0.053, 0.052, 0.052, 0.048, 0.044, 0.046,
            0.048, 0.040, 0.036, 0.044, 0.046, 0.034, 0.036, 0.035,
            0.033, 0.042, 0.036, 0.033, 0.035, 0.030, 0.025, 0.023,
            0.022, 0.018, 0.016, 0.013, 0.010, 0.008, 0.006, 0.004,
        ],
    ),
    # 2026-08-03: added alongside 'synthwave' -- 'house' and 'tech_house'
    # were the only two points on the house-family spectrum, leaving the
    # warmer/slower/chord-driven end uncovered and prone to landing on
    # 'house' with a poor spectral match.
    # 2026-09-10 (zone-map batch): this profile is the dark pole of a
    # deep/progressive dark-vs-bright split (owner: "progressive (bright)
    # & deep (dark) house, same bpm range"), with the bright counterpart a
    # new 'progressive' profile below (placeholder, borrows this
    # profile's real Tier-A fingerprint pending its own Phase 5
    # derivation) sharing this profile's own 112-116 BPM window exactly.
    "deep_house": AudioProfile(
        name="Deep House",
        description=(
            "Warm rolling sub-bass, soulful/jazzy chord stabs, and soft "
            "filtered hats at 112-118 BPM -- slower, darker, and more "
            "melodic than house, the darker pole of the deep/progressive split"
        ),
        bass_min=20.0,
        bass_max=200.0,
        mid_min=200.0,
        mid_max=2200.0,
        treble_min=2200.0,
        treble_max=20000.0,
        bass_weight=1.15,
        # Elevated vs house's 1.0: the soulful chord stab (not just the
        # kick) is a defining, identifiable element of this genre.
        mid_weight=1.15,
        treble_weight=0.75,
        beat_threshold=1.2,
        smoothing=0.13,
        curve="warm",
        onset_bass_emphasis=1.5,
        onset_mid_emphasis=1.3,
        onset_treble_emphasis=0.8,
        # 2026-08-10: house-family consolidation, see house's own field
        # comment for the full rationale. deep_house's band moved from
        # 118-124 (overlapping house's old 120-128) to 112-118, adjacent to
        # but no longer overlapping house's new 118-126.
        # 2026-08-14: sigma-matches-hint-band pass (see house's own field
        # comment) -- derived value 0.04, unclamped the same night (see house's own field comment).
        # 2026-09-04 (recommender rc.28, evidence-based sigma pass):
        # 0.04 -> 0.0445, real per-track spread on training-deep-house-01
        # (11 tracks). mu DELIBERATELY unchanged -- see house's own
        # 2026-09-04 field comment for the house-family BPM cluster
        # finding this profile is part of (deep_house's own real median,
        # 126.4, sits almost entirely inside house's owner-designed band).
        # 2026-09-10 (zone-map batch, owner-provided genre BPM table):
        # bpm_hint_max 118 -> 116, narrowing against the new 'midtempo'
        # sibling profile (112-116, the "no 4otf" variant of this same
        # tempo pocket). mu (115.0) still sits inside the new band.
        bpm_prior_mu=115.0,
        bpm_prior_sigma=0.0445,
        bpm_hint_min=112.0,
        bpm_hint_max=116.0,
        # Warmer/less bright than house (1500 Hz) -- the chord stabs and
        # rolled-off hats keep energy lower in the spectrum.
        zcr_mu=0.0254,
        zcr_sigma=0.0261,
        onset_density_mu=3.2215,
        onset_density_sigma=0.7519,
        # 2026-09-03 (recommender rc.27, vocal-term calibration, config B):
        # median vocal_hnr/vocal_fmr from training-deep-house-01's OWN
        # corpus only (both seeds, ~15.4k heartbeats) -- see expected_bands
        # below for why this profile is no longer pooled with progressive-
        # house-01. Superseded the first-landed value (0.4876/0.3070, from
        # the earlier deep-house+progressive pooled measurement) the same
        # night, before that config ever shipped. This profile previously
        # left vocal_hnr_mu/vocal_fmr_mu uncalibrated (None) entirely on
        # the theory that a fabricated target would be worse than no
        # signal -- but None is not neutral in _profile_score(): it makes
        # the vocal_hnr_fit/vocal_fmr_fit terms score exactly 0.0, a "free
        # pass" no calibrated profile gets, found to be the actual root
        # cause of deep_house dominating nearly every list regardless of
        # genre match. See docs/adr/vj-system.md "Data-Derived
        # expected_bands" vocal-calibration addendum.
        vocal_hnr_mu=0.5386,
        vocal_fmr_mu=0.3192,
        vocal_hnr_sigma=0.1624,
        vocal_fmr_sigma=0.0505,
        # 2026-09-04 (recommender rc.29, per-track median-of-medians re-fit,
        # n=11 tracks): supersedes the mu just above (0.5384->0.5672 /
        # 0.3192->0.3244) and adds a real fitted sigma in place of the flat
        # 0.20/0.15 constant every profile shared -- see
        # vocal_hnr_sigma/vocal_fmr_sigma's own field comment for method.
        # 2026-09-03 (recommender rc.27, data-derived fingerprints, config
        # B): mean `bands` over training-deep-house-01's OWN corpus ONLY
        # (both seeds, ~15.4k heartbeats) -- NOT pooled with
        # training-progressive-house-01. Supersedes the first-landed
        # config (pooled, cos(deep_house, progressive) = 0.9965 vs.
        # cos(house, deep_house) = 0.9959 tie-break) the same night, before
        # that config ever shipped: owner correction -- progressive-
        # house-01 is not pooled anywhere; progressive tracks fall to deep
        # or house at scoring time on their own merits instead of being
        # baked into either fingerprint. See docs/adr/vj-system.md.
        expected_bands=[
            0.582, 0.596, 0.620, 0.656, 0.679, 0.682, 0.629, 0.613,
            0.608, 0.585, 0.587, 0.591, 0.588, 0.521, 0.435, 0.437,
            0.442, 0.421, 0.380, 0.397, 0.378, 0.358, 0.289, 0.267,
            0.293, 0.266, 0.248, 0.210, 0.186, 0.165, 0.147, 0.149,
            0.130, 0.140, 0.114, 0.092, 0.078, 0.065, 0.057, 0.053,
            0.045, 0.042, 0.054, 0.044, 0.042, 0.037, 0.037, 0.041,
            0.038, 0.033, 0.027, 0.024, 0.023, 0.021, 0.019, 0.019,
            0.018, 0.016, 0.013, 0.009, 0.007, 0.005, 0.003, 0.002,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.087, 0.089, 0.093, 0.098, 0.102, 0.102, 0.094, 0.092,
            0.091, 0.088, 0.088, 0.089, 0.088, 0.078, 0.065, 0.066,
            0.066, 0.063, 0.057, 0.077, 0.100, 0.119, 0.135, 0.069,
            0.096, 0.040, 0.073, 0.078, 0.061, 0.060, 0.037, 0.048,
            0.057, 0.052, 0.045, 0.039, 0.027, 0.025, 0.016, 0.018,
            0.009, 0.006, 0.018, 0.022, 0.021, 0.020, 0.015, 0.007,
            0.012, 0.014, 0.012, 0.012, 0.011, 0.013, 0.011, 0.012,
            0.014, 0.012, 0.009, 0.006, 0.004, 0.003, 0.002, 0.002,
        ],
    ),
    # 2026-09-10 (zone-map batch, owner-provided genre BPM table): renamed
    # "Peak-Time" -> "Hard House" ("formerly peaktime, vocals, 4otf" in the
    # owner's table). Dict key kept as 'peak_time' for backward
    # compatibility with existing config/corpus data that references it by
    # key (same pattern as electronic/hyphy above) -- only the display
    # name, description, and BPM band changed.
    #
    # 2026-09-10 (zone-map batch, later): renamed again, "Hard House" ->
    # "Hard" -- this profile is now the dark pole of a hard/peak dark-vs-
    # bright split (owner: "hard (dark) / peak (bright)"), with the
    # bright counterpart a new 'peak' profile below (placeholder, borrows
    # this profile's fingerprint pending its own Phase 5 derivation).
    # Shortening to "Hard" also resolves a pre-existing key/display
    # mismatch (the dict key already said 'peak_time' while the display
    # name said "Hard House") by handing "Peak Time" to the new sibling
    # instead, rather than compounding it.
    "peak_time": AudioProfile(
        name="Hard",
        description="Festival-ready kick, bright tops, and no patience for low-energy lanes -- the darker pole of the hard/peak split",
        bass_min=25.0,
        bass_max=230.0,
        mid_min=230.0,
        mid_max=3800.0,
        treble_min=3800.0,
        treble_max=20000.0,
        bass_weight=1.15,
        mid_weight=1.10,
        treble_weight=1.00,
        beat_threshold=1.05,
        smoothing=0.09,
        curve="bright",
        onset_bass_emphasis=1.10,
        onset_mid_emphasis=1.35,
        onset_treble_emphasis=1.15,
        # 2026-08-14: sigma-matches-hint-band pass (see house's own field
        # comment) -- derived value 0.07, unclamped the same night (see house's own field comment).
        # 2026-09-04 (recommender rc.28, evidence-based sigma pass):
        # 0.0683 -> 0.0741, real per-track spread on training-big-room-01
        # (11 tracks). mu DELIBERATELY unchanged -- see house's own
        # 2026-09-04 field comment (this profile's real median, 129.9,
        # sits right at the edge of the house-family cluster).
        #
        # 2026-09-10 (zone-map batch, owner-provided genre BPM table):
        # bpm_hint_min 126 -> 130, closing the gap against house's new
        # 120-126 band. mu (130.0) still sits inside the new band.
        bpm_prior_mu=130.0,
        bpm_prior_sigma=0.0741,
        bpm_hint_min=130.0,
        bpm_hint_max=136.0,
        zcr_mu=0.0254,
        zcr_sigma=0.0261,
        onset_density_mu=2.933,
        onset_density_sigma=0.4915,
        # 2026-09-03 (recommender rc.27, vocal-term calibration, config B):
        # median vocal_hnr/vocal_fmr from training-big-room-01's OWN corpus
        # ONLY (both seeds, ~14.9k heartbeats) -- see expected_bands below
        # for why this profile is no longer pooled with training-techno-01.
        # Supersedes the first-landed value (0.4748/0.3133, pooled with
        # techno) the same night, before that config ever shipped.
        vocal_hnr_mu=0.4639,
        vocal_fmr_mu=0.3263,
        vocal_hnr_sigma=0.1867,
        vocal_fmr_sigma=0.0666,
        # 2026-09-04 (recommender rc.29, per-track median-of-medians re-fit,
        # n=11 tracks): mu shifted 0.4640->0.4573 / 0.3265->0.3097 and adds
        # a real fitted sigma in place of the flat 0.20/0.15 constant.
        # 2026-09-03 (recommender rc.27, data-derived fingerprints, config
        # B): mean `bands` over training-big-room-01's OWN corpus ONLY
        # (both seeds, ~14.9k heartbeats) -- NOT pooled with
        # training-techno-01. Supersedes the first-landed config (pooled,
        # cos(techno, big-room) = 0.9943 tie-break) the same night, before
        # that config ever shipped: owner correction -- techno is NOT
        # peak_time ("peak time is fast house, techno is techno");
        # training-techno-01 is left unmapped pending a possible dedicated
        # `techno` profile (see docs/adr/vj-system.md). big-room-01's own
        # festival-energy description remains the reason it maps to
        # peak_time.
        # 2026-09-10 (zone-map batch, Phase 5 fingerprint refresh): re-derived pooling ALL packaged buckets under this list's own training slug (same per-track median/MAD ribbon methodology), including the owner's pilot-run tracks from this same session.
        expected_bands=[
            0.670, 0.676, 0.690, 0.721, 0.734, 0.750, 0.716, 0.707,
            0.646, 0.598, 0.596, 0.591, 0.591, 0.523, 0.430, 0.432,
            0.413, 0.360, 0.298, 0.274, 0.234, 0.224, 0.218, 0.216,
            0.219, 0.195, 0.187, 0.167, 0.146, 0.142, 0.143, 0.139,
            0.119, 0.114, 0.117, 0.097, 0.088, 0.078, 0.088, 0.085,
            0.069, 0.058, 0.058, 0.059, 0.056, 0.050, 0.046, 0.045,
            0.043, 0.037, 0.037, 0.034, 0.031, 0.028, 0.026, 0.024,
            0.021, 0.020, 0.020, 0.018, 0.015, 0.012, 0.009, 0.006,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.100, 0.102, 0.110, 0.108, 0.110, 0.113, 0.107, 0.106,
            0.097, 0.090, 0.089, 0.089, 0.089, 0.078, 0.107, 0.089,
            0.118, 0.054, 0.084, 0.052, 0.035, 0.049, 0.066, 0.040,
            0.034, 0.031, 0.041, 0.037, 0.028, 0.022, 0.069, 0.043,
            0.044, 0.069, 0.045, 0.033, 0.033, 0.052, 0.046, 0.022,
            0.021, 0.030, 0.019, 0.022, 0.017, 0.014, 0.015, 0.014,
            0.010, 0.008, 0.008, 0.015, 0.020, 0.015, 0.018, 0.016,
            0.015, 0.011, 0.008, 0.006, 0.005, 0.005, 0.003, 0.003,
        ],
    ),
    "trance": AudioProfile(
        name="Trance",
        description="Elevated mids, strong highs for synth leads, reactive bass",
        bass_min=30.0,
        bass_max=200.0,
        mid_min=200.0,
        mid_max=4000.0,
        treble_min=4000.0,
        treble_max=20000.0,
        bass_weight=1.0,
        mid_weight=1.3,
        treble_weight=1.2,
        beat_threshold=1.1,
        smoothing=0.08,
        curve="mid_treble_boost",
        # Trance: kick + offbeat at 130-145 BPM. Mid synths can fire flux
        # so keep mid emphasis moderate.
        onset_bass_emphasis=1.8,
        onset_mid_emphasis=1.3,
        onset_treble_emphasis=0.9,
        # 2026-08-14: sigma-matches-hint-band pass (see house's own field
        # comment) -- derived value 0.04, unclamped the same night (see house's own field comment).
        # 2026-09-04 (recommender rc.28, evidence-based mu/sigma pass):
        # mu 138.0 -> 134.5, sigma 0.0446 -> 0.0593 -- real per-track
        # median/spread on training-trance-01 (11 tracks), no house-
        # family-style separation conflict here, applied directly.
        # 2026-09-10 (zone-map batch, owner-provided genre BPM table):
        # hint band 134-142 -> 132-138, tightening against hardhouse/
        # techno below and deeptrance above. mu (134.5) still sits inside.
        bpm_prior_mu=134.5,
        bpm_prior_sigma=0.0593,
        bpm_hint_min=132.0,
        bpm_hint_max=138.0,
        zcr_mu=0.0391,
        zcr_sigma=0.0406,
        onset_density_mu=3.2721,
        onset_density_sigma=0.8841,
        # 2026-09-03 (recommender rc.27, vocal-term calibration): median
        # vocal_hnr/vocal_fmr from training-trance-01's own corpus.
        # Replaces the generic 0.35/0.25 default -- see house's own field
        # comment for the full methodology pointer.
        vocal_hnr_mu=0.4003,
        vocal_fmr_mu=0.2781,
        vocal_hnr_sigma=0.1787,
        vocal_fmr_sigma=0.0613,
        # 2026-09-04 (recommender rc.29, per-track median-of-medians re-fit,
        # n=11 tracks): mu shifted 0.4007->0.3711 / 0.2776->0.2882 and adds
        # a real fitted sigma in place of the flat 0.20/0.15 constant.
        # 2026-09-03 (recommender rc.27, data-derived fingerprints): mean
        # `bands` over training-trance-01's own corpus (both seeds, ~7.5k
        # heartbeats). Generalization checked against training-normie-
        # trance (a separately-named, lower-tempo trance-adjacent list,
        # not a literal sibling): the measured fingerprint still beats
        # dubstep's own shipped fingerprint on that held-out session by
        # 0.141 (spectral_shape_fit only) -- see docs/adr/vj-system.md.
        # 2026-09-10 (zone-map batch, Phase 5 fingerprint refresh): re-derived pooling ALL packaged buckets under this list's own training slug (same per-track median/MAD ribbon methodology), including the owner's pilot-run tracks from this same session.
        expected_bands=[
            0.751, 0.751, 0.753, 0.760, 0.766, 0.771, 0.779, 0.775,
            0.733, 0.719, 0.725, 0.723, 0.716, 0.613, 0.452, 0.453,
            0.453, 0.394, 0.349, 0.327, 0.316, 0.300, 0.287, 0.246,
            0.235, 0.226, 0.212, 0.240, 0.198, 0.178, 0.188, 0.181,
            0.164, 0.152, 0.149, 0.129, 0.138, 0.112, 0.106, 0.094,
            0.100, 0.082, 0.073, 0.071, 0.062, 0.067, 0.058, 0.060,
            0.057, 0.055, 0.050, 0.044, 0.041, 0.037, 0.033, 0.031,
            0.033, 0.029, 0.026, 0.023, 0.018, 0.013, 0.009, 0.006,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.113, 0.113, 0.113, 0.114, 0.115, 0.116, 0.117, 0.116,
            0.110, 0.145, 0.137, 0.125, 0.129, 0.096, 0.101, 0.105,
            0.100, 0.059, 0.068, 0.080, 0.072, 0.052, 0.070, 0.037,
            0.054, 0.071, 0.063, 0.083, 0.069, 0.049, 0.058, 0.042,
            0.037, 0.047, 0.033, 0.027, 0.032, 0.029, 0.035, 0.032,
            0.039, 0.032, 0.018, 0.024, 0.020, 0.024, 0.021, 0.021,
            0.014, 0.015, 0.016, 0.011, 0.010, 0.017, 0.019, 0.023,
            0.016, 0.014, 0.011, 0.010, 0.011, 0.008, 0.006, 0.004,
        ],
    ),
    "psytrance": AudioProfile(
        name="Psytrance",
        description="Relentless rolling kick, psychedelic mids, and hyper-detailed tops",
        # 2026-09-04 (recommender rc.29, evidence audit): was disabled --
        # zero training-list corpus of any kind, every scoring field below
        # (fingerprint, vocal, tempo) still 100% hand-authored/guessed.
        #
        # 2026-09-10 (zone-map batch): RE-ENABLED as part of the owner's
        # full-roster genre BPM table rewrite ("all enabled"). The
        # zero-corpus caveat above still applied in full at that point.
        #
        # 2026-09-10 (zone-map batch, Phase 5 prep, later): reclassified
        # as a trance-family dependent instead of waiting on a dedicated
        # training-psytrance-01 pull -- owner's own framing, "trance but
        # faster," is the exact deeptrance pattern mirrored (trance's real
        # tempo bookended slower by deeptrance, faster by this profile).
        # zcr/onset_density/vocal_hnr/vocal_fmr below now inherit trance's
        # real values (replacing this profile's own 100%-guessed ones);
        # expected_bands is trance's real ribbon with a directional tilt
        # (k=+0.25, brighter -- "psychedelic mids, hyper-detailed tops" is
        # explicit textual grounding for reading brighter than trance's
        # own fingerprint), same tilt convention as the dark/bright split
        # siblings below. expected_bands_sigma is trance's own real sigma,
        # unshifted -- this is also this profile's FIRST sigma of any
        # kind, moving it off the legacy cosine-similarity fallback path
        # onto the same ribbon-fit mechanism (spectral_shape_fit) every
        # other real/tilted profile in this roster uses -- a genuine
        # mechanism change, not just new numbers, flagged since it can
        # shift live scoring behavior a bit. Still a rougher proxy than
        # real derivation (a tempo-shift-plus-tilt borrow doesn't capture
        # psytrance's hypnotic/squelchy bassline character), but
        # categorically better than the fully-guessed state it replaces.
        enabled=True,
        bass_min=28.0,
        bass_max=210.0,
        mid_min=210.0,
        mid_max=4200.0,
        treble_min=4200.0,
        treble_max=20000.0,
        bass_weight=1.05,
        mid_weight=1.25,
        treble_weight=1.15,
        beat_threshold=1.02,
        smoothing=0.08,
        curve="mid_treble_boost",
        onset_bass_emphasis=1.45,
        onset_mid_emphasis=1.35,
        onset_treble_emphasis=1.00,
        # 2026-08-14: sigma-matches-hint-band pass (see house's own field
        # comment) -- derived value 0.05, unclamped the same night (see house's own field comment).
        # NOTE: this profile's prior sigma (previously 0.16) is the fixture
        # value tests/test_bpm_detector_audit_regressions.py's sigma-floor-
        # revert regression test is built around -- re-verified passing
        # after this change (the mismatch penalty only got sharper, same
        # winner), but check that test first if this value moves again.
        # 2026-09-10 (zone-map batch): bpm_hint_max 149 -> 150 (owner's
        # genre BPM table). bpm_prior_mu/sigma left untouched -- sigma is
        # a test fixture value (see the note above), and mu still sits
        # well inside the new band.
        bpm_prior_mu=145.0,
        bpm_prior_sigma=0.0532,
        bpm_hint_min=140.0,
        bpm_hint_max=150.0,
        zcr_mu=0.0627,
        zcr_sigma=0.0271,
        onset_density_mu=3.32,
        onset_density_sigma=1.0831,
        vocal_hnr_mu=0.3711,
        vocal_fmr_mu=0.2882,
        vocal_hnr_sigma=0.1156,
        vocal_fmr_sigma=0.0378,
        expected_bands=[
            0.638, 0.652, 0.665, 0.678, 0.691, 0.705, 0.718, 0.731,
            0.730, 0.692, 0.704, 0.716, 0.728, 0.589, 0.445, 0.452,
            0.459, 0.409, 0.345, 0.334, 0.309, 0.289, 0.277, 0.248,
            0.233, 0.232, 0.229, 0.216, 0.211, 0.196, 0.196, 0.186,
            0.171, 0.160, 0.149, 0.129, 0.115, 0.115, 0.111, 0.101,
            0.103, 0.091, 0.089, 0.081, 0.074, 0.071, 0.070, 0.064,
            0.060, 0.061, 0.059, 0.045, 0.046, 0.039, 0.035, 0.031,
            0.029, 0.026, 0.022, 0.020, 0.016, 0.013, 0.009, 0.006,
        ],
        expected_bands_sigma=[
            0.170, 0.170, 0.170, 0.170, 0.170, 0.170, 0.170, 0.170,
            0.090, 0.180, 0.180, 0.180, 0.180, 0.162, 0.145, 0.145,
            0.145, 0.129, 0.128, 0.137, 0.135, 0.131, 0.137, 0.130,
            0.136, 0.135, 0.139, 0.129, 0.106, 0.099, 0.104, 0.092,
            0.093, 0.095, 0.078, 0.071, 0.064, 0.061, 0.058, 0.054,
            0.054, 0.050, 0.044, 0.048, 0.046, 0.045, 0.041, 0.037,
            0.037, 0.037, 0.037, 0.029, 0.031, 0.028, 0.028, 0.026,
            0.025, 0.021, 0.018, 0.016, 0.013, 0.010, 0.010, 0.010,
        ],
    ),
    # 2026-08-10: revived and renamed from 'electronic' (owner call, house-
    # family consolidation pass -- see docs/adr/vj-system.md). Disabled on
    # 2026-08-06 because its expected_bands fingerprint was >=0.95 cosine-
    # similar to nearly everything, including far-tempo genres -- a flat
    # signal that didn't discriminate, not a unique one. That's no longer a
    # disqualifying flaw: this profile's whole purpose now is "the same 4-
    # on-the-floor house-tempo material minus vocals" -- owner: "vocals is
    # enough to carry the split, otherwise basically indistinguishable."
    # So every field below except vocal_hnr_mu/vocal_fmr_mu is a deliberate
    # copy of house's own values, not independently authored -- the split
    # is meant to ride entirely on vocal_hnr_fit/vocal_fmr_fit (the two
    # terms that were silently reading zero all day until the copy-bug fix
    # earlier today; this is their first real use). Dict key kept as
    # 'electronic' for backward compatibility with any existing config/
    # corpus data that references it by key; only the display name changed.
    "electronic": AudioProfile(
        name="Dance",
        description="4-on-the-floor house-tempo material with no vocal presence -- otherwise identical to house",
        # Deliberately kept near-identical to house on every axis except
        # vocal_hnr/vocal_fmr (below) -- this is the owner's control pair
        # for validating the vocal-presence discriminator actually works:
        # house has vocals, electronic doesn't, everything else matches.
        #
        # DISABLED 2026-09-04 (owner, mid smoke-test-playlist build: "is
        # electronic disabled? i thought we had the generics disabled? we
        # prolly should"). It was revived 2026-08-10 specifically as a
        # control pair to validate the vocal-presence discriminator --
        # that job is done (real vocal_hnr/vocal_fmr terms landed, real
        # non-zero weights, real accuracy data this same night confirming
        # rap_rnb wins 47-51% in-pool on vocal presence). Unlike every
        # other profile in the roster it has no distinct acoustic identity
        # by design (a deliberate house-mirror, "otherwise identical to
        # house" per its own description above) -- a genuine generic, not
        # a genre pending real data like techno/synthwave.
        # Disable-not-delete, same pattern as those two -- direct lookup
        # (get_profile('electronic')) still resolves it.
        #
        # 2026-09-10 (zone-map batch): RE-ENABLED as part of the owner's
        # full-roster genre BPM table rewrite -- 'dance' (this profile's
        # display name already) fills a distinct slot in the finalized
        # roster ("no vocals, four on the floor"), no longer purely a
        # retired control pair.
        enabled=True,
        bass_min=20.0,
        bass_max=250.0,
        mid_min=250.0,
        mid_max=2000.0,
        treble_min=2000.0,
        treble_max=20000.0,
        bass_weight=1.2,
        mid_weight=1.0,
        treble_weight=0.9,
        beat_threshold=1.15,
        smoothing=0.12,
        curve="bass_boost",
        onset_bass_emphasis=1.4,
        onset_mid_emphasis=1.0,
        onset_treble_emphasis=0.75,
        # Was "same band as house" through 2026-09-04 (tempo wasn't the
        # discriminator, vocal presence was) -- see house's own field
        # comment for the sigma-tightening/unclamping rationale this
        # still carries forward, including the 2026-09-04 evidence-based
        # sigma update.
        #
        # 2026-09-10 (zone-map batch): bpm_hint_min 118 -> 116, now
        # genuinely distinct from house's own 120-126 band (owner's genre
        # BPM table gives 'dance' 116-126 vs house 120-126) -- mu (122.0)
        # still sits inside both.
        bpm_prior_mu=122.0,
        bpm_prior_sigma=0.0297,
        bpm_hint_min=116.0,
        bpm_hint_max=126.0,
        # 2026-09-10 (zone-map batch, Phase 5 pilot-run correction):
        # briefly overwritten with training-dance-01's own real measured
        # zcr/onset/vocal_hnr/vocal_fmr during the "update all our
        # fingerprints" pass below -- caught before landing. That
        # measurement showed vocal_hnr_mu ~0.44 for the "dance" crate,
        # essentially IDENTICAL to house's own, not the near-zero value
        # this profile's whole design depends on. That's a real finding
        # about the crate (its tracks aren't actually vocal-free the way
        # the "no vocal presence" design assumes), not evidence this
        # profile's deliberate discriminator is wrong -- overwriting it
        # with the crate's own average would have silently defeated the
        # entire control-pair purpose and broken test_dance_diverges_
        # from_house_only_on_tempo_band_and_vocal_presence's pinned
        # `dance.vocal_hnr_mu < 0.10` assertion. zcr/onset_density restored
        # to mirror house's own (now real, updated) values instead, same
        # "kept identical to house except vocals" design as expected_bands
        # below -- this profile still has no training list of its own,
        # 'training-dance-01' notwithstanding.
        zcr_mu=0.0372,
        zcr_sigma=0.0406,
        onset_density_mu=2.9223,
        onset_density_sigma=0.552,
        # The actual discriminator: near-zero vocal-formant harmonic/
        # modulation presence, vs. house's real ~0.44/0.33. Deliberately
        # NOT the crate's own measured value -- see the field comment
        # above.
        vocal_hnr_mu=0.05,
        vocal_fmr_mu=0.05,
        # 2026-09-04 (recommender rc.28): kept identical to house's own
        # ribbon-derived expected_bands/expected_bands_sigma (same
        # deliberate-copy design as every other field above -- this
        # profile has no training list of its own; see
        # tests/test_audio_profile_deep_house_and_disable.py
        # ::test_dance_diverges_from_house_only_on_tempo_band_and_vocal_
        # presence, which pins this exact invariant). See docs/adr/
        # vj-system.md "Spectral-Shape Ribbon Redesign".
        #
        # 2026-09-10 (zone-map batch, Phase 5): refreshed to match house's
        # own newly re-derived real fingerprint (see house's own field
        # comment) -- still the same mirror, just following house's data
        # forward.
        expected_bands=[
            0.714, 0.716, 0.722, 0.722, 0.725, 0.725, 0.725, 0.716,
            0.679, 0.634, 0.634, 0.634, 0.634, 0.525, 0.411, 0.411,
            0.413, 0.379, 0.326, 0.331, 0.322, 0.322, 0.303, 0.278,
            0.254, 0.241, 0.222, 0.210, 0.190, 0.178, 0.172, 0.172,
            0.153, 0.156, 0.123, 0.114, 0.110, 0.102, 0.092, 0.095,
            0.096, 0.081, 0.079, 0.070, 0.073, 0.060, 0.058, 0.056,
            0.057, 0.058, 0.056, 0.050, 0.050, 0.048, 0.045, 0.041,
            0.037, 0.031, 0.029, 0.024, 0.018, 0.013, 0.010, 0.007,
        ],
        expected_bands_sigma=[
            0.107, 0.107, 0.108, 0.108, 0.109, 0.109, 0.109, 0.107,
            0.102, 0.095, 0.095, 0.095, 0.095, 0.079, 0.076, 0.080,
            0.082, 0.062, 0.066, 0.058, 0.055, 0.067, 0.088, 0.096,
            0.104, 0.084, 0.076, 0.084, 0.072, 0.071, 0.070, 0.069,
            0.070, 0.064, 0.053, 0.052, 0.052, 0.048, 0.044, 0.046,
            0.048, 0.040, 0.036, 0.044, 0.046, 0.034, 0.036, 0.035,
            0.033, 0.042, 0.036, 0.033, 0.035, 0.030, 0.025, 0.023,
            0.022, 0.018, 0.016, 0.013, 0.010, 0.008, 0.006, 0.004,
        ],
    ),
    # 2026-09-03 (recommender rc.27, owner-approved): added after techno-01
    # was found "homeless" while deriving data-driven fingerprints -- the
    # roster had tech_house (disabled) and hard_techno (140-150, the fast
    # end) but nothing for plain techno, so training-techno-01 was
    # incorrectly pooled into peak_time (config A, cos(techno, big-room) =
    # 0.9943 tie-break) purely for lack of a real home. Owner correction:
    # techno is NOT peak_time ("peak time is fast house, techno is
    # techno"); big-room-01 maps to peak_time alone (config B). Every
    # field below except bpm_prior_mu/sigma/hint, expected_bands, and
    # vocal_hnr_mu/vocal_fmr_mu is a deliberate copy of hard_techno's own
    # values, not independently authored -- owner: "hard techno is just
    # fast techno; the pairs that differ only by tempo are the whole
    # problem, and the tempo term is the lever" (see docs/adr/vj-system.md
    # "Vocal-Term Calibration" entry's tempo-term follow-up for the
    # broader tempo_fit context this decision sits inside).
    #
    # DISABLED on arrival, same disable-not-delete pattern as tech_house:
    # enabling this profile as a live candidate re-broke the hard
    # requirement `house` winning `training-house-01` -- `techno`'s
    # measured expected_bands has an even higher low-band plateau (0.832)
    # than house's (0.789), so it became the new generic-runner-up-
    # everywhere profile, the third recurrence of the same defect
    # (dubstep -> house -> techno). Root cause identified: spectral_shape_
    # fit's plain cosine similarity rewards a taller shared low-band
    # plateau, not genuine shape match -- see docs/adr/vj-system.md's
    # "Vocal-Term Calibration" entry for the fix under preparation (a
    # level-normalized spectral term). This profile's own derivation
    # (fingerprint, vocal targets, bpm prior) stays here, documented and
    # ready -- get_profile('techno') still resolves it directly for
    # direct/explicit use -- re-enable once the spectral-shape fix (plus
    # the fold-aware tempo term and derived sigmas) lands together as
    # recommender rc.28, gated on the rc.41 panel.
    # 2026-09-10 (zone-map batch): RE-ENABLED as part of the owner's
    # full-roster genre BPM table rewrite ("all enabled"). The disable
    # rationale above (spectral_shape_fit's plain cosine-similarity defect
    # rewarding techno's tall low-band plateau) is the SAME root cause the
    # rest of this session's ribbon/analyzer work has been chasing --
    # still not independently re-validated for this specific profile, so
    # treat this re-enable as riding on that broader fix landing, not a
    # standalone confirmation. Flagged for Phase 5 of the zone-map/
    # sub-kick-split/recalibration plan regardless.
    "techno": AudioProfile(
        name="Techno",
        enabled=True,
        description="Driving, hypnotic 4/4 kick with minimal/industrial texture at 130-136 BPM -- no vocals",
        bass_min=28.0,
        bass_max=230.0,
        mid_min=230.0,
        mid_max=4200.0,
        treble_min=4200.0,
        treble_max=20000.0,
        bass_weight=1.25,
        mid_weight=1.15,
        treble_weight=1.00,
        beat_threshold=1.00,
        smoothing=0.08,
        curve="aggressive",
        onset_bass_emphasis=1.55,
        onset_mid_emphasis=1.25,
        onset_treble_emphasis=0.95,
        # 2026-09-03: derived from training-techno-01's own real detected-
        # BPM distribution (median 134.5, p25/p75 128.1/149.2), NOT copied
        # from hard_techno -- hint band capped at hard_techno's own floor
        # (142) to stay adjacent-not-overlapping, matching the house-family
        # convention (deep_house/house/tech_house). mu = arithmetic
        # midpoint of the hint band (135); sigma = log2(hint_max/hint_min)/2
        # per the sigma-matches-hint-band convention (see house's own field
        # comment). NOTE (2026-09-03, same night): this profile's own
        # bpm_prior_sigma is one of the ones flagged as likely undersized
        # for recommender tempo_fit scoring purposes specifically -- see
        # the tempo-term gate failure and the prepared fold-aware
        # tempo_fit / per-list sigma-derivation design in
        # docs/adr/vj-system.md. Left at this hint-band-derived value for
        # now since tempo_fit stays at weight 0.0; revisit alongside every
        # other profile's sigma once the rc.41 panel data exists.
        # 2026-09-04 (recommender rc.28, evidence-based mu/sigma pass):
        # mu 135.0 -> 136.4, sigma 0.0749 -> 0.1260 -- real per-track
        # median/spread on training-techno-01 (14 tracks), directly
        # resolving the "likely undersized" flag noted above -- this is
        # a real measurement now, not a hint-band-derived placeholder.
        #
        # 2026-09-10 (zone-map batch, owner-provided genre BPM table):
        # hint band 128-142 -> 130-136, tightened against trance/hardhouse
        # on both sides. The real measured mu (136.4) now sits just
        # outside this owner-redrawn band -- moved to 133.0 (the new
        # band's midpoint) rather than leaving a prior pointed outside its
        # own hint range (same precedent as hardstyle's own field comment
        # below). This is a placeholder reconciliation, not a new
        # measurement -- real re-fit against the new band belongs in
        # Phase 5 of the zone-map/sub-kick-split/recalibration plan.
        bpm_prior_mu=133.0,
        bpm_prior_sigma=0.1260,
        bpm_hint_min=130.0,
        bpm_hint_max=136.0,
        zcr_mu=0.0254,
        zcr_sigma=0.029,
        onset_density_mu=3.2193,
        onset_density_sigma=0.6303,
        # 2026-09-03 (recommender rc.27, vocal-term calibration): median
        # vocal_hnr/vocal_fmr from training-techno-01's own corpus (both
        # seeds, ~15.6k heartbeats) -- same methodology as every other
        # data-derived profile, NOT copied from hard_techno (which still
        # carries the generic 0.35/0.25 default, unvalidated).
        vocal_hnr_mu=0.4842,
        vocal_fmr_mu=0.3019,
        vocal_hnr_sigma=0.1742,
        vocal_fmr_sigma=0.0589,
        # 2026-09-04 (recommender rc.29, per-track median-of-medians re-fit,
        # n=14 tracks): mu shifted 0.4842->0.4783 / 0.3021->0.3051 and adds
        # a real fitted sigma in place of the flat 0.20/0.15 constant.
        # 2026-09-03 (recommender rc.27, data-derived fingerprints): mean
        # `bands` over training-techno-01's own corpus (both seeds, ~15.6k
        # heartbeats). See docs/adr/vj-system.md.
        # 2026-09-10 (zone-map batch, Phase 5 fingerprint refresh): re-derived pooling ALL packaged buckets under this list's own training slug (same per-track median/MAD ribbon methodology), including the owner's pilot-run tracks from this same session.
        expected_bands=[
            0.797, 0.802, 0.812, 0.829, 0.836, 0.832, 0.824, 0.816,
            0.732, 0.659, 0.655, 0.665, 0.661, 0.532, 0.416, 0.416,
            0.412, 0.362, 0.310, 0.328, 0.278, 0.249, 0.224, 0.209,
            0.188, 0.195, 0.191, 0.171, 0.168, 0.154, 0.134, 0.129,
            0.136, 0.127, 0.110, 0.104, 0.103, 0.082, 0.078, 0.068,
            0.068, 0.058, 0.060, 0.048, 0.047, 0.040, 0.041, 0.040,
            0.031, 0.035, 0.033, 0.026, 0.028, 0.027, 0.025, 0.025,
            0.019, 0.017, 0.015, 0.013, 0.011, 0.008, 0.006, 0.004,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.120, 0.120, 0.122, 0.124, 0.125, 0.125, 0.124, 0.122,
            0.110, 0.099, 0.098, 0.100, 0.099, 0.084, 0.106, 0.107,
            0.100, 0.103, 0.109, 0.103, 0.120, 0.100, 0.076, 0.066,
            0.057, 0.061, 0.037, 0.039, 0.025, 0.031, 0.034, 0.051,
            0.056, 0.050, 0.021, 0.036, 0.030, 0.030, 0.024, 0.030,
            0.027, 0.022, 0.027, 0.012, 0.017, 0.018, 0.021, 0.020,
            0.016, 0.025, 0.017, 0.015, 0.015, 0.013, 0.012, 0.011,
            0.010, 0.009, 0.008, 0.006, 0.006, 0.005, 0.004, 0.003,
        ],
    ),
    "hard_techno": AudioProfile(
        name="Hard Techno",
        description="Punishing kick, clipped industrial mids, and high-BPM insistence",
        # 2026-09-04 (recommender rc.29, evidence audit): was disabled --
        # zero training-list corpus, every scoring field still hand-
        # authored/guessed.
        #
        # 2026-09-10 (zone-map batch): RE-ENABLED as part of the owner's
        # full-roster genre BPM table rewrite ("all enabled"). Zero-corpus
        # caveat still applies in full -- flagged for Phase 5 of the
        # zone-map/sub-kick-split/recalibration plan.
        enabled=True,
        bass_min=28.0,
        bass_max=230.0,
        mid_min=230.0,
        mid_max=4200.0,
        treble_min=4200.0,
        treble_max=20000.0,
        bass_weight=1.25,
        mid_weight=1.15,
        treble_weight=1.00,
        beat_threshold=1.00,
        smoothing=0.08,
        curve="aggressive",
        onset_bass_emphasis=1.55,
        onset_mid_emphasis=1.25,
        onset_treble_emphasis=0.95,
        # 2026-08-14: sigma-matches-hint-band pass (see house's own field
        # comment) -- derived value 0.06, unclamped the same night (see house's own field comment).
        # 2026-09-10 (zone-map batch): hint band 142-154 -> 140-150 (owner's
        # genre BPM table). mu (148.0) still sits inside the new band.
        bpm_prior_mu=148.0,
        bpm_prior_sigma=0.0627,
        bpm_hint_min=140.0,
        bpm_hint_max=150.0,
        zcr_mu=0.075,
        zcr_sigma=0.015,
        onset_density_mu=3.5,
        onset_density_sigma=0.7,
        vocal_hnr_mu=0.35,
        vocal_fmr_mu=0.25,
        expected_bands=[
            0.850, 0.820, 0.800, 0.750, 0.700, 0.650, 0.600, 0.880,
            0.920, 0.960, 0.850, 0.780, 0.700, 0.780, 0.850, 0.900,
            0.950, 0.950, 0.950, 0.850, 0.750, 0.650, 0.750, 0.850,
            0.950, 1.000, 0.950, 0.950, 0.900, 0.950, 0.900, 0.800,
            0.700, 0.720, 0.740, 0.760, 0.780, 0.800, 0.820, 0.720,
            0.650, 0.750, 0.850, 0.950, 1.000, 0.920, 0.850, 0.940,
            0.920, 0.900, 0.850, 0.800, 0.750, 0.700, 0.650, 0.600,
            0.550, 0.500, 0.600, 0.700, 0.800, 0.850, 0.900, 0.950,
        ],
    ),
    "hardstyle": AudioProfile(
        name="Hardstyle",
        description="Distorted/pitched kick, reverse-bass sweep, and euphoric screech leads",
        # 2026-09-04 (recommender rc.29, evidence audit): was disabled --
        # zero training-list corpus, every scoring field still hand-
        # authored/guessed.
        #
        # 2026-09-10 (zone-map batch): RE-ENABLED as part of the owner's
        # full-roster genre BPM table rewrite. Owner's own framing for
        # this slot: "anything in [155-175] that is not just dnb or
        # dubstep... whatever generic is appropriate for the slot" -- kept
        # the existing Hardstyle identity/fingerprint rather than
        # genericizing it, since a real (if under-evidenced) genre label
        # beats an unnamed placeholder. Zero-corpus caveat still applies
        # in full -- flagged for Phase 5 of the zone-map/sub-kick-split/
        # recalibration plan.
        enabled=True,
        bass_min=25.0,
        bass_max=250.0,
        mid_min=250.0,
        mid_max=4000.0,
        treble_min=4000.0,
        treble_max=20000.0,
        bass_weight=1.10,
        mid_weight=1.30,
        treble_weight=1.00,
        beat_threshold=1.00,
        smoothing=0.08,
        curve="aggressive",
        # Hardstyle: distorted/reverse-bass kick + screech leads at 155-175 BPM.
        # Mid emphasis raised for onset detection since the screech-lead
        # transients carry as much rhythmic information as the kick itself.
        onset_bass_emphasis=1.50,
        onset_mid_emphasis=1.40,
        onset_treble_emphasis=1.00,
        # 2026-08-14: owner raised bpm_hint_min 145 -> 155 (dialed-in
        # expectation). mu moved to 160 (midpoint of the then-155-165
        # band -- it can't stay at 150, which would sit outside its own
        # hint range). sigma-matches-hint-band pass (see house's own field
        # comment) -- derived value 0.0481, unclamped the same night.
        # 2026-09-10 (zone-map batch): bpm_hint_max 165 -> 175 (owner's
        # genre BPM table, widening this slot's upper edge to meet
        # drum_and_bass's own new 155-175 band). mu (160.0) still sits
        # inside the new band, left unchanged.
        bpm_prior_mu=160.0,
        bpm_prior_sigma=0.0481,
        bpm_hint_min=155.0,
        bpm_hint_max=175.0,
        zcr_mu=0.130,
        zcr_sigma=0.015,
        onset_density_mu=4.0,
        onset_density_sigma=0.7,
        vocal_hnr_mu=0.35,
        vocal_fmr_mu=0.25,
        expected_bands=[
            0.900, 0.900, 0.920, 0.920, 0.850, 0.800, 0.750, 0.750,
            0.730, 0.710, 0.700, 0.700, 0.800, 0.850, 0.850, 0.880,
            0.880, 0.900, 0.900, 0.920, 0.930, 0.930, 0.950, 0.950,
            0.960, 0.960, 0.980, 0.980, 0.980, 0.980, 0.980, 0.970,
            0.940, 0.940, 0.900, 0.850, 0.780, 0.750, 0.850, 0.900,
            0.950, 1.000, 1.000, 1.000, 0.920, 0.900, 0.900, 0.900,
            0.880, 0.850, 0.820, 0.780, 0.700, 0.680, 0.650, 0.600,
            0.400, 0.300, 0.200, 0.200, 0.180, 0.160, 0.150, 0.150,
        ],
    ),
    "drum_and_bass": AudioProfile(
        name="Drum & Bass",
        description="Fast break transients, subs, and bright hats at full sprint",
        bass_min=28.0,
        bass_max=240.0,
        mid_min=240.0,
        mid_max=4500.0,
        treble_min=4500.0,
        treble_max=20000.0,
        bass_weight=1.10,
        mid_weight=1.15,
        treble_weight=1.25,
        beat_threshold=0.95,
        smoothing=0.08,
        curve="bright",
        onset_bass_emphasis=1.25,
        onset_mid_emphasis=1.20,
        onset_treble_emphasis=1.35,
        # 2026-08-14: owner widened bpm_hint 168-178 -> 165-180 (dialed-in
        # expectation; mu=174 still sits comfortably inside it, no shift
        # needed). sigma-matches-hint-band pass (see house's own field
        # comment) -- derived value 0.0805, now stored and used directly (unclamped the same night; was previously rounded to 0.08, effectively at the old floor anyway).
        # 2026-09-04 (recommender rc.28, evidence-based mu/sigma pass):
        # mu 174.0 -> 166.7, sigma 0.0805 -> 0.1260 -- real per-track
        # median/spread on training-drum-and-bass-01 (16 tracks).
        #
        # 2026-09-10 (zone-map batch): hint band 165-180 -> 155-175 (owner's
        # genre BPM table, sharing its upper edge with hardstyle's own new
        # band -- see that profile's own field comment). mu (166.7) still
        # sits inside the new band.
        bpm_prior_mu=166.7,
        bpm_prior_sigma=0.1260,
        bpm_hint_min=155.0,
        bpm_hint_max=175.0,
        zcr_mu=0.047,
        zcr_sigma=0.0464,
        onset_density_mu=3.364,
        onset_density_sigma=0.6047,
        # 2026-09-03 (recommender rc.27, vocal-term calibration): median
        # vocal_hnr/vocal_fmr from training-drum-and-bass-01's own corpus.
        # Replaces the generic 0.35/0.25 default -- see house's own field
        # comment for the full methodology pointer.
        vocal_hnr_mu=0.4278,
        vocal_fmr_mu=0.3501,
        vocal_hnr_sigma=0.19,
        vocal_fmr_sigma=0.0596,
        # 2026-09-04 (recommender rc.29, per-track median-of-medians re-fit,
        # n=16 tracks): mu shifted 0.4260->0.4485 / 0.3510->0.3468 and adds
        # a real fitted sigma in place of the flat 0.20/0.15 constant.
        # 2026-09-03 (recommender rc.27, data-derived fingerprints): mean
        # `bands` over training-drum-and-bass-01's own corpus (both seeds,
        # ~8.3k heartbeats). See docs/adr/vj-system.md.
        # 2026-09-10 (zone-map batch, Phase 5 fingerprint refresh): re-derived pooling ALL packaged buckets under this list's own training slug (same per-track median/MAD ribbon methodology), including the owner's pilot-run tracks from this same session.
        expected_bands=[
            0.692, 0.702, 0.706, 0.712, 0.716, 0.721, 0.715, 0.705,
            0.668, 0.630, 0.630, 0.635, 0.631, 0.519, 0.430, 0.421,
            0.416, 0.405, 0.364, 0.362, 0.357, 0.329, 0.293, 0.263,
            0.264, 0.224, 0.205, 0.215, 0.205, 0.183, 0.153, 0.160,
            0.148, 0.141, 0.124, 0.156, 0.130, 0.102, 0.100, 0.090,
            0.084, 0.083, 0.073, 0.069, 0.066, 0.063, 0.059, 0.056,
            0.053, 0.052, 0.046, 0.043, 0.041, 0.041, 0.037, 0.035,
            0.032, 0.031, 0.027, 0.024, 0.020, 0.013, 0.009, 0.006,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.104, 0.105, 0.106, 0.107, 0.107, 0.108, 0.107, 0.106,
            0.104, 0.109, 0.112, 0.117, 0.111, 0.129, 0.106, 0.113,
            0.113, 0.079, 0.085, 0.114, 0.138, 0.168, 0.136, 0.146,
            0.135, 0.118, 0.096, 0.115, 0.123, 0.099, 0.080, 0.077,
            0.080, 0.071, 0.076, 0.059, 0.043, 0.055, 0.038, 0.036,
            0.038, 0.041, 0.031, 0.024, 0.028, 0.023, 0.019, 0.016,
            0.012, 0.015, 0.016, 0.013, 0.013, 0.016, 0.016, 0.012,
            0.011, 0.011, 0.010, 0.007, 0.007, 0.004, 0.004, 0.003,
        ],
    ),
    "dubstep": AudioProfile(
        name="Dubstep",
        description="Half-time wobble bass, scooped growl mids, and sparse syncopated hits",
        bass_min=20.0,
        bass_max=200.0,
        mid_min=200.0,
        mid_max=2500.0,
        treble_min=2500.0,
        treble_max=20000.0,
        bass_weight=1.45,
        mid_weight=1.05,
        treble_weight=0.70,
        beat_threshold=1.15,
        smoothing=0.14,
        curve="extreme_bass_boost",
        # Dubstep: produced/tagged at ~140 BPM, but the audible pulse (snare
        # on the half-time backbeat) feels like ~70 BPM. Narrow hint range
        # keeps the ACF locked to the produced tempo instead of folding down
        # to the perceived half-time pulse. Onset emphasis kept moderate on
        # bass so the wobble LFO's own modulation doesn't false-trigger
        # onsets in place of the true (sparse) downbeat.
        onset_bass_emphasis=1.30,
        onset_mid_emphasis=1.10,
        onset_treble_emphasis=0.70,
        # 2026-08-14: sigma-matches-hint-band pass (see house's own field
        # comment) -- derived value 0.02, unclamped the same night (see house's own field comment).
        # 2026-09-04 (recommender rc.28, evidence-based sigma pass):
        # HELD BACK, not updated. A naive per-track median/MAD on real
        # corpus data gives sigma~0.14 -- but this profile's own comment
        # above documents a genuine BIMODAL true-tempo distribution
        # (produced ~140 BPM, perceived half-time pulse ~70), so a plain
        # median/MAD mixes real within-produced-tempo variance with
        # half-time-fold contamination from the SAME tracks -- exactly
        # what this profile's deliberately tight 0.0218 sigma exists to
        # keep the detector away from. Needs the fold-aware filtering
        # already discussed (docs/adr/vj-system.md, the parked tempo-term
        # work) before this can be re-derived correctly, not a naive
        # stat. Left unchanged.
        bpm_prior_mu=140.0,
        bpm_prior_sigma=0.0218,
        # 2026-08-17: hint band widened 138-142 -> 70-160 from real session
        # data (2hr-dubstep: 19.0% of readings in 70-100 AND 50.9% in
        # 130-160 -- two genuine produced-tempo bands, not one tempo plus
        # its half-time illusion; owner: "dub step *is* legit 70-100 AND
        # 130-160 lol"). The old sliver actively fought half of correct
        # dubstep readings in every hint-band consumer (HUD range, the
        # mood-prime in-band candidate pick).
        # 2026-08-17, later still: 70-160 -> 140-160. A single min/max range
        # is inherently inclusive of everything between its ends -- it was
        # never meant to also validate the 100-130 gap between the two real
        # produced-tempo bands, just their union, and this schema can't
        # express a union until bimodal hint-band support exists (flagged
        # below). Narrowed to the upper, on-`bpm_prior_mu` band alone as the
        # safer interim single range; the low (70-100) band goes
        # unrepresented in hint-band consumers until dual-range support
        # lands. Owner: "change dubstp to 140-160 until we add support for
        # dual ranges, it was not intended to be *inclusive*." Deliberately
        # hints-only: bpm_prior_mu/sigma above stay narrow -- the
        # detector-side anti-halftime-fold prior is a separate,
        # separately-validated concern, and a bimodal prior needs a schema
        # change (flagged in the round-three plan § 5.3, owner's call).
        bpm_hint_min=140.0,
        bpm_hint_max=160.0,
        # 2026-08-31: 0.095 -> 0.093. LLM tuning recommendation from the
        # training-house-01/002 matcher-validation session ("observed ZCR
        # slightly lower than expected"), owner-approved.
        zcr_mu=0.0431,
        zcr_sigma=0.0406,
        onset_density_mu=2.8699,
        onset_density_sigma=0.47,
        # 2026-09-03 (recommender rc.27, vocal-term calibration): median
        # vocal_hnr/vocal_fmr from training-dubstep-01's own corpus.
        # Replaces the generic 0.35/0.25 default -- see house's own field
        # comment for the full methodology pointer.
        vocal_hnr_mu=0.4392,
        vocal_fmr_mu=0.3283,
        vocal_hnr_sigma=0.1989,
        vocal_fmr_sigma=0.0655,
        # 2026-09-04 (recommender rc.29, per-track median-of-medians re-fit,
        # n=14 tracks): mu shifted 0.4407->0.4113 / 0.3283->0.3271 and adds
        # a real fitted sigma in place of the flat 0.20/0.15 constant. NOT
        # subject to this profile's BPM tactus-fold caveat (see
        # bpm_prior_sigma's own comment above) -- HNR/FMR measure vocal-
        # formant harmonic/modulation content, not tempo, so half-time
        # pulse-doubling contamination doesn't apply here.
        # 2026-09-03 (recommender rc.27, data-derived fingerprints): mean
        # `bands` over training-dubstep-01's own corpus (both seeds, ~7.7k
        # heartbeats). This profile's OLD shipped fingerprint was already
        # the best-calibrated in the whole roster (cos(measured, old
        # shipped) = 0.971) -- it is what won dubstep so many wrong lists,
        # not a badly-authored one; replaced anyway for consistency and to
        # close the small remaining gap. See docs/adr/vj-system.md
        # "Data-Derived expected_bands" for the full diagnosis.
        # 2026-09-10 (zone-map batch, Phase 5 fingerprint refresh): re-derived pooling ALL packaged buckets under this list's own training slug (same per-track median/MAD ribbon methodology), including the owner's pilot-run tracks from this same session.
        expected_bands=[
            0.698, 0.712, 0.721, 0.718, 0.707, 0.695, 0.681, 0.682,
            0.607, 0.542, 0.534, 0.526, 0.523, 0.447, 0.353, 0.355,
            0.356, 0.331, 0.301, 0.280, 0.261, 0.245, 0.248, 0.249,
            0.243, 0.236, 0.227, 0.217, 0.221, 0.192, 0.172, 0.191,
            0.194, 0.152, 0.137, 0.135, 0.112, 0.098, 0.099, 0.095,
            0.088, 0.068, 0.066, 0.062, 0.059, 0.059, 0.053, 0.056,
            0.050, 0.047, 0.046, 0.039, 0.034, 0.032, 0.032, 0.030,
            0.027, 0.026, 0.025, 0.020, 0.016, 0.011, 0.008, 0.006,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.181, 0.194, 0.198, 0.193, 0.176, 0.161, 0.154, 0.142,
            0.091, 0.081, 0.080, 0.079, 0.079, 0.073, 0.106, 0.119,
            0.119, 0.147, 0.139, 0.116, 0.096, 0.129, 0.137, 0.111,
            0.081, 0.107, 0.088, 0.082, 0.098, 0.103, 0.133, 0.111,
            0.087, 0.092, 0.086, 0.040, 0.039, 0.057, 0.050, 0.059,
            0.037, 0.037, 0.032, 0.020, 0.027, 0.024, 0.024, 0.021,
            0.025, 0.015, 0.013, 0.013, 0.011, 0.011, 0.013, 0.011,
            0.009, 0.006, 0.006, 0.007, 0.007, 0.006, 0.006, 0.004,
        ],
    ),
    # 2026-08-06: 'rap' and 'r&b' merged into this single profile (owner
    # call: "rap/r&b should be one") after a cosine-similarity audit found
    # them genuine siblings -- 0.9856 similarity, 3 BPM apart -- rather
    # than a false-catch-all pairing like fire_dj/electronic. Field values
    # are blended averages of the two originals, with one correction:
    # rap's old spectral_centroid_mu (1600) directly contradicted its own
    # acoustic-notes comment ("AcousticBrainz shows hip-hop centroids
    # typically 800-1200 Hz") -- the merge uses 1200 (matching that
    # documented research finding, folded toward r&b's warmer 1400) rather
    # than perpetuating the inconsistency by averaging a known-wrong number.
    # spectral_centroid_sigma tightened 600->400 now that this is a real,
    # intentionally-merged single genre rather than an accidental overlap.
    # See docs/adr/vj-system.md for the full merge record.
    # 2026-09-10 (zone-map batch): display name "Rap / R&B" -> "Rap" --
    # this profile is now the dark pole of a rap/rnb dark-vs-bright split
    # (owner: "rap (dark) / rnb (bright)"), with the bright counterpart a
    # new 'rnb' profile below (placeholder, borrows this profile's real
    # Tier-A fingerprint pending its own Phase 5 derivation). Dict key
    # kept as 'rap_rnb' for backward compatibility with existing
    # config/corpus data.
    "rap_rnb": AudioProfile(
        name="Rap",
        description="Heavy sub-bass with sustained, vocal-forward mids at 70-100 BPM -- the darker pole of the rap/R&B split",
        bass_min=30.0,
        bass_max=275.0,
        mid_min=275.0,
        mid_max=3000.0,
        treble_min=3000.0,
        treble_max=20000.0,
        bass_weight=1.25,
        mid_weight=1.3,
        treble_weight=0.85,
        beat_threshold=1.12,
        smoothing=0.135,
        curve="extreme_bass_boost",
        onset_bass_emphasis=1.6,
        onset_mid_emphasis=1.1,
        onset_treble_emphasis=0.75,
        # 2026-08-10: 86.5 -> 85.0 (band center), sigma tightened 0.27 ->
        # 0.20. Owner's own judgment call, not fit from this session's
        # corpus -- the library's own rap/r&b tracks (n=13-25) were flagged
        # as unrepresentative (mostly accidental agent-download inclusions,
        # not a curated rap/r&b test set) and, separately, confirmed to
        # carry a real ~24% one-directional 4/3 tactus-fold contamination
        # in that same small sample (see docs/adr/vj-system.md) -- so last
        # night's measured median was explicitly not used as the target
        # here. hint_min/max unchanged (70-100).
        # 2026-08-14: sigma-matches-hint-band pass (see house's own field
        # comment) -- derived value 0.29, above the old 0.20 (this profile's
        # hint band is wider than 1 old-sigma, so this widens rather than
        # tightens, unlike most of the roster).
        # 2026-09-04 (recommender rc.28, evidence-based sigma pass): HELD
        # BACK, not updated. A naive per-track median on the current
        # training-hip-hop-01 + training-rnb-01 pool reads ~139 BPM
        # (dev 64% from this mu) -- but this is the SAME profile the
        # 2026-08-10 note directly above already found carrying "a real
        # ~24% one-directional 4/3 tactus-fold contamination" in its own
        # corpus, and the owner explicitly declined to use a measured
        # median for that documented reason. The new pooled corpus (hip-
        # hop-01 + rnb-01, not the original small sample that finding was
        # made on) has not been re-checked for the same contamination --
        # until it is, this reads as the same known failure mode
        # recurring, not new counter-evidence, and mu/sigma stay
        # unchanged.
        bpm_prior_mu=85.0,
        bpm_prior_sigma=0.29,
        bpm_hint_min=70.0,
        bpm_hint_max=100.0,
        zcr_mu=0.0313,
        zcr_sigma=0.0348,
        onset_density_mu=2.9341,
        onset_density_sigma=0.4295,
        # 2026-09-04 (recommender rc.28): trap-hip-hop-01 split OUT of this
        # pool into its own re-enabled 'hyphy' profile -- owner: "trap
        # should def be on its own." hip-hop-01 + rnb-01 stay pooled
        # (owner: "rnb/hh i'll let u decide based on evidence") -- a
        # per-list confusion check found hip-hop-01 and rnb-01 the least
        # separable pair of the three by spectral shape, consistent with
        # the original 2026-08-06 "genuine siblings" merge finding, while
        # trap-hip-hop-01 discriminates clearly from both. Values below
        # (both vocal medians and expected_bands/_sigma) were measured
        # against training-hip-hop-01 + training-rnb-01 ONLY (~20k
        # heartbeats) -- see hyphy's own field comment for its half of
        # the split and the confusion-matrix evidence.
        #
        # 2026-09-10 (zone-map batch, Phase 5 fingerprint refresh):
        # DECOUPLED from the rnb pool above -- rnb is now its own real
        # profile (see rnb's own field comment) rather than a guessed
        # tilt riding on this pooled reading, so pooling hip-hop-01 with
        # rnb-01 here would double-count the same rnb-01 tracks into two
        # different profiles. Values below now come from
        # training-hip-hop-01 ALONE, pooling all its packaged buckets (47
        # tracks) -- the confusion-matrix finding above (hip-hop-01 and
        # rnb-01 being the least separable pair) is a real, still-true
        # observation about the underlying audio; it no longer determines
        # how these two profiles' fingerprints are derived.
        vocal_hnr_mu=0.5064,
        vocal_fmr_mu=0.3668,
        vocal_hnr_sigma=0.1748,
        vocal_fmr_sigma=0.0699,
        # 2026-09-04 (recommender rc.29, per-track median-of-medians re-fit,
        # n=25 tracks): mu shifted 0.5126->0.5118 / 0.3696->0.3642 and adds
        # a real fitted sigma in place of the flat 0.20/0.15 constant. NOT
        # subject to this profile's BPM 4/3-fold-contamination caveat (see
        # bpm_prior_mu/sigma's own comment above) -- HNR/FMR measure vocal-
        # formant content, not tempo, so that finding doesn't apply here.
        # Regenerated (tools/gen_spectral_fingerprints.py, scoped rerun,
        # 2026-08-06) rather than hand-blending the two originals' arrays,
        # so the merged fingerprint doesn't inherit their inconsistencies.
        # Prompt: sustained (not choppy) vocal plateau 150 Hz-3.2 kHz
        # reflecting both rap's spoken-word cadence and R&B's held melodic
        # lines, subdued hi-hats 6-12 kHz, low-to-moderate centroid.
        # (Superseded by the 2026-09-04 ribbon redesign below.)
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): mu = per-band
        # median across per-track means from training-hip-hop-01 +
        # training-rnb-01 (trap split out, see above); expected_bands_sigma
        # = MAD-derived per-band spread, floored at 15% of that band's own
        # median. See docs/adr/vj-system.md "Spectral-Shape Ribbon
        # Redesign" for the full methodology and the frame-vs-track
        # scoring bug caught and fixed before landing.
        expected_bands=[
            0.781, 0.781, 0.781, 0.781, 0.781, 0.778, 0.778, 0.778,
            0.691, 0.623, 0.623, 0.623, 0.623, 0.515, 0.416, 0.416,
            0.416, 0.377, 0.354, 0.345, 0.331, 0.306, 0.271, 0.254,
            0.226, 0.224, 0.220, 0.229, 0.209, 0.192, 0.185, 0.181,
            0.156, 0.142, 0.130, 0.112, 0.111, 0.096, 0.089, 0.085,
            0.081, 0.079, 0.067, 0.065, 0.064, 0.055, 0.056, 0.049,
            0.046, 0.045, 0.042, 0.044, 0.041, 0.040, 0.038, 0.037,
            0.033, 0.031, 0.026, 0.022, 0.018, 0.013, 0.008, 0.005,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.126, 0.118, 0.119, 0.122, 0.122, 0.121, 0.122, 0.122,
            0.113, 0.144, 0.155, 0.144, 0.144, 0.144, 0.129, 0.129,
            0.129, 0.096, 0.118, 0.130, 0.126, 0.129, 0.128, 0.113,
            0.109, 0.098, 0.110, 0.118, 0.116, 0.101, 0.085, 0.084,
            0.056, 0.059, 0.056, 0.055, 0.052, 0.050, 0.048, 0.043,
            0.046, 0.039, 0.039, 0.039, 0.041, 0.036, 0.037, 0.032,
            0.031, 0.026, 0.022, 0.025, 0.024, 0.026, 0.025, 0.025,
            0.022, 0.018, 0.013, 0.014, 0.012, 0.009, 0.006, 0.003,
        ],
    ),
    # 2026-08-10: relabeled "Hyphy" -> "Hyphy / Trap" (owner call, house-
    # family-style consolidation applied to this pair too). Dict key kept
    # as 'hyphy' for backward compatibility. Owner: "rap/rnb/trap all
    # should have solid deep bass lines as well.. hyphy not so much" -- the
    # existing bass_weight (1.5, already the highest in this family) is
    # kept as-is rather than lowered, since this merged profile's real-
    # world matches are expected to skew trap (808-driven) more than pure
    # hyphy going forward.
    "hyphy": AudioProfile(
        name="Hyphy",
        # 2026-09-04: RE-ENABLED, then DISABLED AGAIN same day (owner,
        # direct: "disable hyphy" -- mid smoke-test-playlist build, which
        # had just surfaced that the library has zero tracks ID3-tagged
        # Hyphy; every acoustic value below is fit entirely against
        # training-trap-hip-hop-01, i.e. this profile currently has no
        # content of its own distinct from a straight trap read). The
        # earlier same-day re-enable rationale (trap/hyphy split from
        # rap_rnb, confusion-matrix evidence) stands and is left below --
        # this disable doesn't reverse that finding, it just reflects that
        # there's no dedicated hyphy material to point the profile at.
        # Dict key kept as 'hyphy' for backward compatibility;
        # get_profile('hyphy') still resolves it directly.
        #
        # 2026-09-04: RE-ENABLED (same day, superseded above). Owner: "trap
        # should def be on its own" -- was disabled 2026-08-10 specifically
        # for lack of real trap/hyphy material to validate against;
        # training-trap-hip-hop-01 now supplies that. Evidence-based split
        # from rap_rnb (which pooled hip-hop-01 + trap-hip-hop-01 + rnb-01
        # until tonight): a per-list confusion check (own tracks scored
        # against each of the three lists' own ribbons, spectral_shape_fit
        # only) showed trap-hip-hop-01 and rnb-01 each discriminate real
        # distinctly from the other two, while hip-hop-01 and rnb-01 are
        # the closest, least-separable pair of the three -- so trap splits
        # out to its own profile (this one) and rap_rnb keeps hip-hop +
        # rnb pooled (see rap_rnb's own field comment). Every field below
        # except bpm_prior_mu/sigma/hint, expected_bands/_sigma, and
        # vocal_hnr_mu/vocal_fmr_mu is unchanged from the pre-disable
        # values -- not re-derived, since only the fingerprint/tempo/vocal
        # axes had real data to recalibrate against.
        #
        # 2026-09-10 (zone-map batch): RE-ENABLED AGAIN as part of the
        # owner's full-roster genre BPM table rewrite ("all enabled").
        # The "no content of its own distinct from a straight trap read"
        # caveat immediately above still applies in full -- flagged for
        # Phase 5 of the zone-map/sub-kick-split/recalibration plan.
        #
        # 2026-09-10 (zone-map batch, later): display name "Hyphy / Trap"
        # -> "Hyphy" -- this profile is now the bright pole of a hyphy/trap
        # dark-vs-bright split (owner: "hyphy (bright) / trap (dark)"),
        # with the dark counterpart a new 'trap' profile below
        # (placeholder, borrows this profile's fingerprint pending its own
        # Phase 5 derivation).
        enabled=True,
        description="Aggressive sub-bass, sustained hype-vocal chops, bright treble at 105-116 BPM -- the brighter pole of the hyphy/trap split",
        bass_min=20.0,
        bass_max=350.0,
        mid_min=350.0,
        mid_max=3000.0,
        treble_min=3000.0,
        treble_max=20000.0,
        bass_weight=1.5,
        mid_weight=1.3,
        treble_weight=1.1,
        beat_threshold=0.95,
        smoothing=0.15,
        curve="extreme_bass_boost",
        # Hyphy: aggressive sub-bass at 90-110 BPM.  Same reasoning as
        # rap — raw flux gives kicks plenty of signal; keep treble for hype.
        onset_bass_emphasis=1.5,
        onset_mid_emphasis=1.0,
        onset_treble_emphasis=0.80,
        # REVERTED 2026-09-04 (recommender rc.33): the 2026-09-04 rc.28/rc.29
        # recalibration above (mu 109.0->142.2, hint 100-118->127-155) is
        # reverted -- owner: "someone made unapproved changes.. consolidating
        # those was approved by not that bpm range! the bpm range for those
        # should be what hyphy was before." The hyphy/trap split-from-rap_rnb
        # itself was approved ("trap should def be on its own"); this specific
        # tempo change riding along in the same commit (6799bfc) was not, and
        # never should have been applied blind: it pooled raw per-track
        # *detected* BPM from training-trap-hip-hop-01 replay sessions as if
        # it were ground-truth produced tempo -- exactly the fold-contamination
        # risk this same field comment already flagged and that dubstep/
        # rap_rnb were correctly HELD BACK for (see those profiles' own
        # comments) -- but hyphy's own change was applied anyway. Restored to
        # the owner's own hand-tuned, hand-dialed values from the pre-split
        # 2026-08-10 disable commit (2eab76b): bpm_prior_mu=109.0,
        # bpm_prior_sigma=0.15, bpm_hint_min/max=100.0/118.0. If a real,
        # fold-aware (track-by-track, not pooled-detector-output) re-fit is
        # wanted later, it needs the owner's explicit sign-off first, same as
        # any other detector/recommender constant change.
        #
        # 2026-09-10 (zone-map batch): hint band 100-118 -> 105-116 (owner's
        # genre BPM table). mu (109.0) still sits inside the new band.
        bpm_prior_mu=109.0,
        bpm_prior_sigma=0.15,
        bpm_hint_min=105.0,
        bpm_hint_max=116.0,
        zcr_mu=0.0294,
        zcr_sigma=0.0348,
        onset_density_mu=3.0042,
        onset_density_sigma=0.3937,
        # 2026-09-04 (recommender rc.28, vocal-term + ribbon recalibration):
        # median vocal_hnr/vocal_fmr from training-trap-hip-hop-01's own
        # corpus (21 tracks) -- replaces the old unvalidated 0.55/0.5 guess.
        #
        # 2026-09-10 (zone-map batch, Phase 5 fingerprint refresh):
        # refreshed against ALL 34 packaged buckets under the same list
        # (still 21 distinct tracks -- more buckets, same underlying
        # crate), including the owner's pilot-run tracks from this same
        # session. This is the same source `trap` now derives its own
        # fingerprint from (see trap's own field comment) -- the two
        # profiles carry nearly identical real values as a result, an
        # honest reflection of the "no content of its own distinct from a
        # straight trap read" caveat already on file above, not a new
        # problem.
        vocal_hnr_mu=0.5324,
        vocal_fmr_mu=0.3623,
        vocal_hnr_sigma=0.1805,
        vocal_fmr_sigma=0.0711,
        # 2026-09-04 (recommender rc.29, per-track median-of-medians re-fit,
        # n=21 tracks): mu shifted 0.5323->0.5390 / 0.3621->0.3622 (small,
        # consistent with the same-night rc.28 figure) and adds a real
        # fitted sigma in place of the flat 0.20/0.15 constant.
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): mu = per-band
        # median across training-trap-hip-hop-01's own per-track means (21
        # tracks); expected_bands_sigma = MAD-derived per-band spread,
        # floored at 15% of that band's own median. Replaces the old hand-
        # authored jagged array (that array was flagged in the very
        # comment it replaced as "nearly indistinguishable from chillstep
        # under cosine similarity" -- moot now, this profile no longer
        # uses cosine similarity for spectral_shape_fit at all). See
        # docs/adr/vj-system.md "Spectral-Shape Ribbon Redesign".
        expected_bands=[
            0.746, 0.745, 0.749, 0.753, 0.753, 0.747, 0.753, 0.751,
            0.652, 0.574, 0.570, 0.571, 0.568, 0.480, 0.404, 0.406,
            0.406, 0.350, 0.297, 0.296, 0.270, 0.252, 0.236, 0.209,
            0.205, 0.217, 0.228, 0.219, 0.178, 0.182, 0.160, 0.129,
            0.120, 0.106, 0.096, 0.081, 0.069, 0.074, 0.061, 0.064,
            0.053, 0.044, 0.043, 0.041, 0.047, 0.037, 0.028, 0.026,
            0.030, 0.024, 0.023, 0.018, 0.019, 0.019, 0.021, 0.022,
            0.020, 0.018, 0.013, 0.009, 0.008, 0.005, 0.003, 0.002,
        ],
        expected_bands_sigma=[
            0.127, 0.140, 0.147, 0.157, 0.160, 0.170, 0.152, 0.131,
            0.098, 0.127, 0.124, 0.118, 0.122, 0.106, 0.150, 0.154,
            0.149, 0.146, 0.114, 0.089, 0.095, 0.118, 0.138, 0.130,
            0.106, 0.123, 0.104, 0.092, 0.081, 0.088, 0.060, 0.053,
            0.048, 0.057, 0.038, 0.034, 0.025, 0.028, 0.020, 0.032,
            0.025, 0.018, 0.019, 0.017, 0.014, 0.021, 0.018, 0.018,
            0.020, 0.016, 0.012, 0.011, 0.008, 0.009, 0.010, 0.011,
            0.015, 0.016, 0.007, 0.006, 0.007, 0.004, 0.002, 0.002,
        ],
    ),
    # 2026-09-10 (zone-map batch, owner-provided genre BPM table): display
    # name "Ambient / Chillout" -> "Ambient / Chill", owner's own
    # description note for this slot: "weird" -- kept as informational
    # context, not acted on further here.
    "ambient": AudioProfile(
        name="Ambient / Chill",
        description="Smooth, subtle reactivity with slight bass emphasis",
        bass_min=20.0,
        bass_max=120.0,
        mid_min=120.0,
        mid_max=2000.0,
        treble_min=2000.0,
        treble_max=20000.0,
        bass_weight=1.1,
        mid_weight=1.0,
        treble_weight=0.8,
        beat_threshold=1.4,
        smoothing=0.2,
        curve="warm",
        # Ambient: often weak or no beats, very wide prior. 2026-05-23 audit
        # showed lock rate ~15-25% on chill content vs ~32-42% on club mixes.
        # Bumped onset emphasis modestly (especially mid/treble) so soft
        # transients like brushed kicks and pad hits feed the ACF better.
        onset_bass_emphasis=1.4,
        onset_mid_emphasis=1.5,
        onset_treble_emphasis=1.2,
        # 2026-08-14: 0.60 -> 0.26, sigma-matches-hint-band pass (see
        # house's own field comment) -- the old 0.60 was wider than the
        # then-authored 84-116 hint band actually implied; this tightened
        # ambient to match that band while remaining the widest-or-near-
        # widest sigma in the roster, consistent with "often weak or no
        # beats" above.
        #
        # 2026-09-10 (zone-map batch): hint band 84-116 -> 60-106 (owner's
        # genre BPM table). This is also the direct fix for the zone-map
        # bleed finding earlier this session -- ambient's old hint_max
        # (116) plus the (then 10%) pre-filter margin reached to ~127.6,
        # squarely inside house's own real BPM territory; the new, lower
        # 106 ceiling closes that gap even before the margin itself
        # changes from relative to a hard +/-4 BPM. mu (100.0) still sits
        # inside the new band; sigma left unchanged (not re-derived
        # against the narrower band here -- real re-fit belongs in
        # Phase 5 of the zone-map/sub-kick-split/recalibration plan).
        bpm_prior_mu=100.0,
        bpm_prior_sigma=0.26,
        bpm_hint_min=60.0,
        bpm_hint_max=106.0,
        zcr_mu=0.0274,
        zcr_sigma=0.0232,
        onset_density_mu=2.8245,
        onset_density_sigma=0.4118,
        # 2026-09-03 (recommender rc.27, vocal-term calibration): this
        # profile had no vocal_hnr_mu/vocal_fmr_mu at all (None on both --
        # see house's own field comment for why None is not a neutral
        # choice: it gives a "free pass" on both terms, which was the root
        # cause of a similar confound found on deep_house). Values below
        # are median vocal_hnr/vocal_fmr from training-ambient-01's own
        # corpus (both seeds). See docs/adr/vj-system.md "Data-Derived
        # expected_bands" vocal-calibration addendum.
        vocal_hnr_mu=0.5438,
        vocal_fmr_mu=0.3303,
        vocal_hnr_sigma=0.1768,
        vocal_fmr_sigma=0.0716,
        # 2026-09-04 (recommender rc.29, per-track median-of-medians re-fit,
        # n=14 tracks): mu shifted 0.5445->0.5520 / 0.3307->0.3223 and adds
        # a real fitted sigma in place of the flat 0.20/0.15 constant.
        # 2026-09-03 (recommender rc.27, data-derived fingerprints): mean
        # `bands` over training-ambient-01's own corpus (both seeds, ~7.9k
        # heartbeats). Generalization checked against training-ambient-02
        # (a true numbered sibling, different session entirely): the
        # measured fingerprint still beats dubstep's own shipped
        # fingerprint on that held-out session by 0.076 (spectral_shape_
        # fit only) -- narrower than the same-list seed1/seed2 test, but a
        # real win, not overfit to one session. See docs/adr/vj-system.md.
        # 2026-09-10 (zone-map batch, Phase 5 fingerprint refresh): re-derived pooling ALL packaged buckets under this list's own training slug (same per-track median/MAD ribbon methodology), including the owner's pilot-run tracks from this same session.
        expected_bands=[
            0.441, 0.449, 0.456, 0.465, 0.463, 0.463, 0.471, 0.475,
            0.493, 0.447, 0.448, 0.441, 0.429, 0.424, 0.414, 0.403,
            0.401, 0.396, 0.393, 0.394, 0.416, 0.412, 0.397, 0.370,
            0.369, 0.325, 0.323, 0.281, 0.277, 0.260, 0.216, 0.190,
            0.194, 0.157, 0.130, 0.121, 0.103, 0.091, 0.075, 0.060,
            0.067, 0.051, 0.055, 0.049, 0.041, 0.035, 0.030, 0.029,
            0.023, 0.022, 0.020, 0.016, 0.017, 0.015, 0.012, 0.009,
            0.008, 0.007, 0.007, 0.005, 0.004, 0.003, 0.002, 0.002,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.190, 0.191, 0.208, 0.236, 0.247, 0.243, 0.223, 0.206,
            0.145, 0.125, 0.115, 0.122, 0.139, 0.157, 0.191, 0.192,
            0.230, 0.176, 0.116, 0.105, 0.074, 0.073, 0.123, 0.126,
            0.138, 0.137, 0.080, 0.103, 0.129, 0.128, 0.115, 0.109,
            0.071, 0.085, 0.053, 0.037, 0.038, 0.041, 0.045, 0.035,
            0.034, 0.022, 0.026, 0.021, 0.023, 0.020, 0.018, 0.023,
            0.017, 0.012, 0.011, 0.008, 0.011, 0.008, 0.010, 0.008,
            0.007, 0.007, 0.007, 0.006, 0.005, 0.004, 0.003, 0.002,
        ],
    ),
    # 2026-09-10 (zone-map batch, owner-provided genre BPM table): display
    # name "Chillstep / Downtempo" -> "Chillstep" -- 'downtempo' is now
    # its own separate sibling profile below (owner's table: chillstep
    # "sparse & crisp" vs. downtempo "lush and full"), no longer folded
    # into this one's name/description. downtempo's own initial
    # acoustic-fingerprint fields are a deliberate copy of this profile's
    # (its own real training-list data, training-downtempo-01, is what
    # this profile's fingerprint was originally measured from) --
    # see downtempo's own field comment.
    "chillstep": AudioProfile(
        name="Chillstep",
        description=(
            "Slow electronic groove: sparse, crisp sub-bass kick, "
            "atmospheric pads, and soft hi-hats at 60-106 BPM"
        ),
        bass_min=20.0,
        bass_max=160.0,
        mid_min=160.0,
        mid_max=2500.0,
        treble_min=2500.0,
        treble_max=20000.0,
        bass_weight=1.15,
        mid_weight=1.05,
        treble_weight=0.85,
        beat_threshold=1.35,
        smoothing=0.16,
        curve="warm",
        # Chillstep: soft kick + pads at 78-108 BPM. Onset emphasis is
        # conservative — over-weighting bass can fire on pad swells and
        # confuse the ACF; mid emphasis helps detect the snare/clap on 2+4.
        onset_bass_emphasis=1.5,
        onset_mid_emphasis=1.4,
        onset_treble_emphasis=1.0,
        # 2026-06-20: mix-03 Essentia comparison showed the ACF locking at ~94
        # BPM on three tracks Essentia placed at 103-106 BPM (Before Dawn,
        # Snow on the Sahara, Leaving).  Raising prior_mu from 90→95 shifts the
        # Gaussian pull toward the observed session median (94 BPM) and reduces
        # the chance the ACF settles on a sub-beat.  Sigma widened 0.45→0.50
        # so tracks genuinely at 105+ BPM can compete against the prior.
        # 2026-08-14: 0.50 -> 0.30, sigma-matches-hint-band pass (see
        # house's own field comment) -- ties sigma to the then-actual
        # 78-112 hint band rather than the wider historical value.
        #
        # 2026-09-10 (zone-map batch): hint band 78-112 -> 60-106 (owner's
        # genre BPM table). mu (95.0) still sits inside the new band;
        # sigma left unchanged (real re-fit belongs in Phase 5 of the
        # zone-map/sub-kick-split/recalibration plan, same as ambient).
        bpm_prior_mu=95.0,
        bpm_prior_sigma=0.30,
        bpm_hint_min=60.0,
        bpm_hint_max=106.0,
        zcr_mu=0.0297,
        zcr_sigma=0.0189,
        onset_density_mu=2.94,
        onset_density_sigma=0.5917,
        # 2026-09-03 (recommender rc.27, vocal-term calibration): this
        # profile had no vocal_hnr_mu/vocal_fmr_mu at all (None on both --
        # see house's own field comment for why None is not a neutral
        # choice). Values below are median vocal_hnr/vocal_fmr from
        # training-downtempo-01 (both seeds -- same c1 mapping as
        # expected_bands below). See docs/adr/vj-system.md "Data-Derived
        # expected_bands" vocal-calibration addendum.
        vocal_hnr_mu=0.5487,
        vocal_fmr_mu=0.3273,
        vocal_hnr_sigma=0.1017,
        vocal_fmr_sigma=0.0300,
        # 2026-09-04 (recommender rc.29, per-track median-of-medians re-fit,
        # n=14 tracks): mu shifted 0.5499->0.5487 / 0.3286->0.3273 and adds
        # a real fitted sigma in place of the flat 0.20/0.15 constant.
        # 2026-08-06: regenerated (tools/gen_spectral_fingerprints.py,
        # scoped rerun -- see docs/adr/vj-system.md and hyphy's matching
        # comment) after a cosine-similarity audit found the previous
        # fingerprint nearly indistinguishable from hyphy (0.9788) despite
        # very different acoustic character. New prompt explicitly
        # emphasized chillstep's atmospheric-pad dominance in the low-mids
        # and deliberately soft/recessed hi-hats 6-10 kHz as its defining
        # feature -- the opposite of hyphy's bright treble. Improved
        # similarity to 0.9703 -- a real but modest gain; see hyphy's
        # comment for the honest caveat on residual overlap.
        # 2026-09-03 (recommender rc.27, data-derived fingerprints): mean
        # `bands` over training-downtempo-01 (both seeds, ~7.6k
        # heartbeats) -- chillstep had no dedicated training list of its
        # own; owner mapped downtempo-01 to it (c1, matching this
        # profile's own "Chillstep / Downtempo" name/description already).
        # See docs/adr/vj-system.md.
        expected_bands=[
            0.842, 0.842, 0.842, 0.842, 0.842, 0.842, 0.842, 0.842,
            0.729, 0.635, 0.635, 0.635, 0.635, 0.537, 0.407, 0.407,
            0.407, 0.363, 0.340, 0.333, 0.321, 0.309, 0.284, 0.280,
            0.288, 0.280, 0.244, 0.219, 0.183, 0.161, 0.153, 0.140,
            0.131, 0.127, 0.093, 0.087, 0.077, 0.071, 0.064, 0.053,
            0.048, 0.039, 0.037, 0.030, 0.028, 0.025, 0.021, 0.021,
            0.020, 0.016, 0.015, 0.013, 0.013, 0.011, 0.009, 0.009,
            0.008, 0.007, 0.005, 0.005, 0.004, 0.003, 0.002, 0.001,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.202, 0.202, 0.202, 0.202, 0.202, 0.202, 0.202, 0.202,
            0.151, 0.164, 0.164, 0.164, 0.164, 0.156, 0.178, 0.178,
            0.178, 0.152, 0.156, 0.186, 0.209, 0.191, 0.178, 0.175,
            0.174, 0.175, 0.160, 0.152, 0.124, 0.106, 0.084, 0.073,
            0.062, 0.067, 0.057, 0.052, 0.041, 0.034, 0.043, 0.025,
            0.024, 0.023, 0.022, 0.019, 0.018, 0.019, 0.013, 0.013,
            0.013, 0.010, 0.010, 0.010, 0.010, 0.010, 0.010, 0.010,
            0.010, 0.010, 0.010, 0.010, 0.010, 0.010, 0.010, 0.010,
        ],
    ),
    # 2026-08-03: first-pass profile, added after a ~5 hour livestream training
    # session (assets/training/sets/20260803-synthtrax-kavinsky-tribute-20260731/,
    # ../unicorn-viz-training deploy) ran the whole night as "generic" and
    # sagged into psytrance/trance (~30% of rows) whenever detected BPM ran
    # hot -- exactly the kind of mismatch a dedicated profile with the right
    # tempo prior and search-range clamp exists to prevent. Not yet validated
    # against real session data the way house/chillstep have been (see the
    # ADR-tracked tuning history on those two) -- recalibrate once a
    # dedicated, more formal synthwave session has been packaged and scored.
    # 2026-09-10 (zone-map batch, owner-provided genre BPM table): display
    # name "Synthwave / Retrowave" -> "Synthwave" -- the wider retro-synth
    # territory this profile used to cover alone is now split across
    # dedicated siblings below (vaporwave 60-80, chillwave 84-96, this
    # profile 100-116, hardsynth 120-130), so it no longer needs to carry
    # "Retrowave" in its own name. The Kavinsky-tempo grounding note below
    # partially predates that split (Nightcall ~104-107 still fits this
    # profile's new band; Odd Look ~93 / Deadcruiser ~90-100 now sit
    # closer to chillwave's 84-96) -- left as historical reference, not
    # rewritten, since it's real measured tempo data, not a hint value.
    "synthwave": AudioProfile(
        name="Synthwave",
        description=(
            "Retro 80s-style synth-driven electronic: warm analog bass, "
            "gated-reverb drums, and bright melodic lead synths at 100-116 BPM"
        ),
        # 2026-09-04 (recommender rc.29, evidence audit): was disabled --
        # zero training-list corpus, every scoring field still hand-
        # authored/guessed.
        #
        # 2026-09-10 (zone-map batch): RE-ENABLED as part of the owner's
        # full-roster genre BPM table rewrite. Zero-corpus caveat still
        # applied in full at that point.
        #
        # 2026-09-10 (zone-map batch, Phase 5 prep, later): real corpus
        # found -- `training-synthwave-02`/`training-synthwave-03`
        # (packaged 2026-09-04, never used to derive this profile's own
        # fields). Owner's own caution proved warranted: both lists mix
        # genuine synthwave/vaporwave with unrelated Italo disco and
        # generic "80s-style edit" tracks of otherwise-unrelated genres
        # (one is an 80s-styled edit of a modern hip-hop track) -- checked
        # by track title, not assumed. Filtered to the 7 tracks whose
        # title explicitly says "synth"/"synthwave" before deriving
        # anything below (`Charles Berkhouse - Would It Be Worth It
        # (Synthwave Mix)`, `Jaguar Grace - Destination Unknown (Neon Wolf
        # Synthwave Remix)`, `James Tennant - Fool To Your Love (80s Synth
        # Mix)`, `Jan Salvadore - Synthwave (Original Mix)`, `Jean Koning -
        # Black Hole Sun (Lone Jon Zilvers Dark Synth Remix)`, `The Death
        # Beats ft Charley Young - Beyond Repair (Synthwave Mix)`, `Vandi
        # Lynnae - I Keep On Moving (Synthwave Remix)`). n=7 is thin (other
        # real profiles in this roster use 11-25 tracks) -- real, but not
        # yet a confident fit; still a genuine improvement over 100%
        # hand-authored. BPM_prior/hint fields deliberately NOT touched:
        # this filtered set's own detected BPMs scatter 110-159, mostly
        # well outside the current 100-116 hint band -- the same fold-
        # contamination risk already flagged elsewhere in this roster
        # (rap_rnb/hyphy/dubstep) for genres with fast hi-hat subdivisions,
        # not treated as ground truth here either. Spectral content
        # doesn't depend on correct BPM detection, so expected_bands/
        # zcr/onset/vocal below are still derived from it; tempo fields
        # stay exactly as the owner dialed them, pending a dedicated look.
        enabled=True,
        bass_min=20.0,
        bass_max=160.0,
        mid_min=160.0,
        mid_max=2500.0,
        treble_min=2500.0,
        treble_max=20000.0,
        bass_weight=1.0,
        # Mid-weighted, unlike chillstep's pad/bass-led balance: the lead
        # synth hook is the genre's defining, most recognizable element.
        mid_weight=1.25,
        treble_weight=0.85,
        beat_threshold=1.3,
        smoothing=0.14,
        curve="warm",
        # Gated-reverb kick/snare is present but not the dominant onset
        # driver the way a house kick is -- weight mid higher than bass so
        # snare hits and arpeggio notes register instead of only the kick,
        # mirroring chillstep's "don't over-weight bass" rationale.
        onset_bass_emphasis=1.6,
        onset_mid_emphasis=1.5,
        onset_treble_emphasis=1.0,
        # Classic/melodic synthwave tempo pocket -- grounded in real Kavinsky
        # tempos (Nightcall ~104-107 BPM, Odd Look ~93 BPM, Deadcruiser
        # ~90-100 BPM). Sigma/hint width matches chillstep's real-world
        # tempo scatter rather than a tightly-quantized genre like house.
        # 2026-08-14: 0.34 -> 0.25, sigma-matches-hint-band pass (see
        # house's own field comment) -- ties sigma to the then-actual
        # 85-118 hint band.
        # 2026-09-10 (zone-map batch): hint band 85-118 -> 100-116 (owner's
        # genre BPM table, now sharing the lower/upper edges with
        # chillwave and hardsynth respectively). mu moved 100.0 -> 108.0
        # (the new band's midpoint) -- the old value sat exactly on the
        # new floor, a real prior needs some margin on both sides, not a
        # boundary value.
        bpm_prior_mu=108.0,
        bpm_prior_sigma=0.25,
        bpm_hint_min=100.0,
        bpm_hint_max=116.0,
        # 2026-09-10 (zone-map batch, Phase 5 prep): real per-track median
        # from the 7-track filtered synth-titled subset described above
        # (5031 heartbeat rows). Supersedes the old hand-authored zcr_mu
        # (0.050) -- kept close by coincidence, not because the guess was
        # validated.
        zcr_mu=0.0313,
        zcr_sigma=0.029,
        onset_density_mu=2.7023,
        onset_density_sigma=0.4838,
        # 2026-09-10 (zone-map batch, Phase 5 prep): real per-row median
        # from the same 7-track filtered subset -- supersedes the old
        # "intentionally uncalibrated, predominantly instrumental" theory.
        # These filtered tracks carry real (if modest) vocal presence.
        vocal_hnr_mu=0.4833,
        vocal_fmr_mu=0.3117,
        vocal_hnr_sigma=0.1623,
        vocal_fmr_sigma=0.0586,
        # 2026-09-10 (zone-map batch, Phase 5 prep): real per-track ribbon
        # (median/MAD-derived sigma, same methodology as every other
        # ribbon-redesigned profile) from the 7-track filtered subset --
        # supersedes the old hand-authored ascending-then-descending shape
        # (peak at bands 39-40). The real shape is very different: a low
        # start, a broad low-mid peak around bands 6-8 (~500-700 Hz), then
        # a fast rolloff essentially dead by band 25 -- not bass-heavy,
        # not treble-heavy, mid-register-driven, consistent with a lead-
        # synth/pad-centric genre rather than a kick- or hi-hat-driven one.
        # n=7 is thin; expected_bands_sigma reflects that (wider than most
        # of the roster's real fingerprints).
        expected_bands=[
            0.144, 0.172, 0.188, 0.263, 0.285, 0.345, 0.395, 0.460,
            0.326, 0.277, 0.258, 0.276, 0.324, 0.316, 0.219, 0.178,
            0.161, 0.209, 0.179, 0.174, 0.240, 0.189, 0.209, 0.127,
            0.141, 0.022, 0.020, 0.016, 0.015, 0.014, 0.011, 0.014,
            0.012, 0.011, 0.010, 0.008, 0.008, 0.005, 0.004, 0.004,
            0.004, 0.004, 0.003, 0.002, 0.003, 0.002, 0.002, 0.003,
            0.002, 0.002, 0.001, 0.001, 0.001, 0.001, 0.001, 0.001,
            0.001, 0.001, 0.001, 0.000, 0.000, 0.000, 0.000, 0.000,
        ],
        expected_bands_sigma=[
            0.094, 0.099, 0.057, 0.118, 0.095, 0.110, 0.188, 0.141,
            0.238, 0.114, 0.206, 0.096, 0.085, 0.101, 0.127, 0.055,
            0.041, 0.100, 0.034, 0.089, 0.128, 0.088, 0.072, 0.052,
            0.122, 0.019, 0.017, 0.017, 0.014, 0.013, 0.010, 0.012,
            0.011, 0.009, 0.009, 0.007, 0.007, 0.004, 0.005, 0.004,
            0.004, 0.003, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002,
            0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002,
            0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002,
        ],
    ),
    # 2026-09-10 (zone-map batch, owner-provided genre BPM table): seven
    # brand-new profiles added in this same pass (downtempo, vaporwave,
    # chillwave, hardsynth, midtempo, electro, deeptrance). None has a
    # training-list corpus of its own yet -- every acoustic-fingerprint
    # field below (spectral_centroid/zcr/onset_density/vocal_hnr/
    # vocal_fmr/expected_bands) is a DELIBERATE COPY of its closest
    # existing sibling profile, same "borrowed starting point, not
    # independently authored" pattern already used for `electronic`
    # mirroring `house`. Only the tempo fields (bpm_prior_mu/sigma,
    # bpm_hint_min/max) are genuinely this profile's own, taken directly
    # from the owner's table. bpm_prior_mu = hint-band midpoint;
    # bpm_prior_sigma = log2(hint_max/hint_min)/2, the same sigma-
    # matches-hint-band convention used throughout this file (see
    # house's own field comment). All flagged for real derivation in
    # Phase 5 of the zone-map/sub-kick-split/recalibration plan, same as
    # every re-enabled zero-corpus profile above.
    #
    # 2026-09-10 (zone-map batch, Phase 5 prep, later): owner direction --
    # for a split with no real data of its own, "use the known version as
    # a best first starting point but shift the spectrum ribbon based on
    # your best educated guess." `expected_bands` below is no longer a
    # verbatim donor copy for the six of these seven with an identified
    # directional discriminator (`downtempo`, `midtempo`, `electro`,
    # `deeptrance`, plus `vaporwave`/`chillwave`/`hardsynth` once
    # `synthwave` itself got real data, see its own field comment) --
    # each gets the donor's real ribbon multiplied by a deliberate
    # brighten/darken tilt (a linear per-band factor, pivoted around
    # band 16 with a 16-band half-width so the shift actually lands where
    # each donor's real energy lives, saturating beyond that so the
    # already-negligible tail bands aren't perturbed): `1 + k * clip((i -
    # 16) / 16, -1, 1)`. `k`'s sign/magnitude is a judgment call grounded
    # in each profile's own already-written description, not a fitted
    # value -- still a guess, just a directional one instead of an exact
    # copy. `expected_bands_sigma` is left as the donor's own real value
    # unshifted (no basis to guess a spread that hasn't been measured).
    # `psytrance` (trance-family, not one of these seven) gets the same
    # treatment below at its own definition, since it's the same kind of
    # split with no data of its own.
    #
    # downtempo: originally a k=-0.20 (darker/warmer) tilt of chillstep's
    # own ribbon -- "vibey/jazzy/sultry" vs. chillstep's own "crisp &
    # light" (owner's own characterization).
    #
    # 2026-09-10 (zone-map batch, Phase 5 fingerprint refresh): superseded
    # by real data -- training-downtempo-01 already had 17+ packaged
    # buckets sitting unused (the SAME list chillstep's own fingerprint
    # was partly measured from historically, per that profile's own field
    # comment). Pooled ALL of them (14 tracks, including the owner's
    # pilot-run tracks from this same session) for a real per-track
    # ribbon/vocal/zcr/onset fit, replacing the guessed tilt below.
    "downtempo": AudioProfile(
        name="Downtempo",
        description="Lush, full slow electronic groove: sub-bass kick, atmospheric pads, and soft hi-hats at 60-108 BPM -- fuller/denser than chillstep's sparser sibling pocket",
        bass_min=20.0,
        bass_max=160.0,
        mid_min=160.0,
        mid_max=2500.0,
        treble_min=2500.0,
        treble_max=20000.0,
        bass_weight=1.15,
        mid_weight=1.05,
        treble_weight=0.85,
        beat_threshold=1.35,
        smoothing=0.16,
        curve="warm",
        onset_bass_emphasis=1.5,
        onset_mid_emphasis=1.4,
        onset_treble_emphasis=1.0,
        bpm_prior_mu=84.0,
        bpm_prior_sigma=0.424,
        bpm_hint_min=60.0,
        bpm_hint_max=108.0,
        zcr_mu=0.0157,
        zcr_sigma=0.0174,
        onset_density_mu=2.9875,
        onset_density_sigma=0.3666,
        vocal_hnr_mu=0.5543,
        vocal_fmr_mu=0.3287,
        vocal_hnr_sigma=0.154,
        vocal_fmr_sigma=0.0609,
        expected_bands=[
            0.666, 0.674, 0.692, 0.709, 0.698, 0.689, 0.694, 0.672,
            0.628, 0.585, 0.596, 0.579, 0.570, 0.496, 0.393, 0.392,
            0.390, 0.362, 0.360, 0.336, 0.330, 0.297, 0.259, 0.260,
            0.261, 0.247, 0.228, 0.186, 0.168, 0.143, 0.147, 0.138,
            0.129, 0.123, 0.087, 0.085, 0.073, 0.066, 0.054, 0.050,
            0.044, 0.040, 0.038, 0.029, 0.027, 0.025, 0.022, 0.019,
            0.019, 0.016, 0.015, 0.012, 0.013, 0.010, 0.010, 0.010,
            0.010, 0.009, 0.006, 0.005, 0.004, 0.002, 0.002, 0.001,
        ],
        expected_bands_sigma=[
            0.121, 0.130, 0.141, 0.139, 0.138, 0.142, 0.135, 0.148,
            0.096, 0.127, 0.113, 0.131, 0.115, 0.087, 0.109, 0.099,
            0.109, 0.101, 0.128, 0.166, 0.199, 0.166, 0.138, 0.162,
            0.176, 0.154, 0.151, 0.100, 0.085, 0.081, 0.073, 0.071,
            0.026, 0.054, 0.043, 0.051, 0.033, 0.029, 0.046, 0.021,
            0.020, 0.015, 0.018, 0.017, 0.014, 0.018, 0.013, 0.011,
            0.012, 0.007, 0.009, 0.009, 0.008, 0.008, 0.010, 0.009,
            0.010, 0.010, 0.007, 0.006, 0.004, 0.003, 0.002, 0.002,
        ],
    ),
    # vaporwave: sibling = synthwave (thematically closest -- synth-driven,
    # predominantly instrumental). "all synth = synth *driven*" per the
    # owner's own table note. Tilt k=-0.20 (darker/warmer) vs. synthwave's
    # own (now real) fingerprint: "warm analog pads and a laid-back...
    # groove" reads warmer than synthwave's brighter lead-synth register.
    "vaporwave": AudioProfile(
        name="Vaporwave",
        description="Slowed, synth-driven retro electronic -- warm analog pads and a laid-back, synth-first groove at 60-80 BPM",
        bass_min=20.0,
        bass_max=160.0,
        mid_min=160.0,
        mid_max=2500.0,
        treble_min=2500.0,
        treble_max=20000.0,
        bass_weight=1.0,
        mid_weight=1.25,
        treble_weight=0.85,
        beat_threshold=1.3,
        smoothing=0.14,
        curve="warm",
        onset_bass_emphasis=1.6,
        onset_mid_emphasis=1.5,
        onset_treble_emphasis=1.0,
        bpm_prior_mu=70.0,
        bpm_prior_sigma=0.207,
        bpm_hint_min=60.0,
        bpm_hint_max=80.0,
        # 2026-09-10 (zone-map batch, Phase 5 prep): zcr/onset/vocal now
        # inherit synthwave's own real (if thin, n=7) values instead of
        # its old hand-authored ones -- same "family inherits from a
        # freshly-measured anchor" principle as everywhere else in this
        # file.
        zcr_mu=0.0313,
        zcr_sigma=0.029,
        onset_density_mu=2.7023,
        onset_density_sigma=0.4838,
        vocal_hnr_mu=0.4833,
        vocal_fmr_mu=0.3117,
        vocal_hnr_sigma=0.1623,
        vocal_fmr_sigma=0.0586,
        # 2026-09-10 (zone-map batch, Phase 5 pilot-run fix): expected_bands_
        # sigma was missing entirely here (stayed None) even after synthwave
        # itself got a real one -- an oversight, not intentional. A missing
        # sigma keeps a profile on the legacy cosine-similarity fallback
        # path instead of spectral_shape_fit's Gaussian ribbon fit, which
        # measures SHAPE match only, independent of scale -- exactly the
        # coarser mechanism already diagnosed as a false-positive risk for
        # every other profile's old hand-authored fingerprint (see "Data-
        # Derived expected_bands" in docs/adr/vj-system.md). Confirmed live
        # in the Phase 5 pilot run: hardsynth (the same gap, same donor) won
        # the recommender's live pick across nearly every unrelated genre
        # tested. synthwave's own real sigma, unshifted -- same convention
        # as every other tilted dependent in this file.
        expected_bands_sigma=[
            0.094, 0.099, 0.057, 0.118, 0.095, 0.110, 0.188, 0.141,
            0.238, 0.114, 0.206, 0.096, 0.085, 0.101, 0.127, 0.055,
            0.041, 0.100, 0.034, 0.089, 0.128, 0.088, 0.072, 0.052,
            0.122, 0.019, 0.017, 0.017, 0.014, 0.013, 0.010, 0.012,
            0.011, 0.009, 0.009, 0.007, 0.007, 0.004, 0.005, 0.004,
            0.004, 0.003, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002,
            0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002,
            0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002,
        ],
        expected_bands=[
            0.173, 0.204, 0.221, 0.306, 0.328, 0.392, 0.444, 0.512,
            0.359, 0.301, 0.277, 0.293, 0.340, 0.328, 0.224, 0.180,
            0.161, 0.206, 0.175, 0.167, 0.228, 0.177, 0.193, 0.116,
            0.127, 0.020, 0.018, 0.014, 0.013, 0.012, 0.009, 0.011,
            0.010, 0.009, 0.008, 0.006, 0.006, 0.004, 0.003, 0.003,
            0.003, 0.003, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002,
            0.002, 0.002, 0.001, 0.001, 0.001, 0.001, 0.001, 0.001,
            0.001, 0.001, 0.001, 0.001, 0.001, 0.001, 0.001, 0.001,
        ],
    ),
    # chillwave: sibling = synthwave (same reasoning as vaporwave above).
    # Tilt k=-0.10 (mildly darker/warmer): "hazy, reverb-soaked... relaxed"
    # reads warmer than synthwave's brighter lead-synth focus, but less
    # extremely so than vaporwave's own "warm analog pads... laid-back."
    "chillwave": AudioProfile(
        name="Chillwave",
        description="Hazy, reverb-soaked synth pop with a relaxed mid-tempo groove at 84-96 BPM",
        bass_min=20.0,
        bass_max=160.0,
        mid_min=160.0,
        mid_max=2500.0,
        treble_min=2500.0,
        treble_max=20000.0,
        bass_weight=1.0,
        mid_weight=1.25,
        treble_weight=0.85,
        beat_threshold=1.3,
        smoothing=0.14,
        curve="warm",
        onset_bass_emphasis=1.6,
        onset_mid_emphasis=1.5,
        onset_treble_emphasis=1.0,
        bpm_prior_mu=90.0,
        bpm_prior_sigma=0.096,
        bpm_hint_min=84.0,
        bpm_hint_max=96.0,
        # 2026-09-10 (zone-map batch, Phase 5 prep): inherits synthwave's
        # real (n=7) zcr/onset/vocal values, same as vaporwave above.
        zcr_mu=0.0313,
        zcr_sigma=0.029,
        onset_density_mu=2.7023,
        onset_density_sigma=0.4838,
        vocal_hnr_mu=0.4833,
        vocal_fmr_mu=0.3117,
        vocal_hnr_sigma=0.1623,
        vocal_fmr_sigma=0.0586,
        # 2026-09-10 (zone-map batch, Phase 5 pilot-run fix): same missing-
        # sigma oversight as vaporwave's own field comment -- synthwave's
        # real sigma, unshifted.
        expected_bands_sigma=[
            0.094, 0.099, 0.057, 0.118, 0.095, 0.110, 0.188, 0.141,
            0.238, 0.114, 0.206, 0.096, 0.085, 0.101, 0.127, 0.055,
            0.041, 0.100, 0.034, 0.089, 0.128, 0.088, 0.072, 0.052,
            0.122, 0.019, 0.017, 0.017, 0.014, 0.013, 0.010, 0.012,
            0.011, 0.009, 0.009, 0.007, 0.007, 0.004, 0.005, 0.004,
            0.004, 0.003, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002,
            0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002,
            0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002,
        ],
        expected_bands=[
            0.158, 0.188, 0.204, 0.284, 0.306, 0.369, 0.420, 0.486,
            0.342, 0.289, 0.268, 0.285, 0.332, 0.322, 0.222, 0.179,
            0.161, 0.208, 0.177, 0.171, 0.234, 0.183, 0.201, 0.121,
            0.134, 0.021, 0.019, 0.015, 0.014, 0.013, 0.010, 0.013,
            0.011, 0.010, 0.009, 0.007, 0.007, 0.005, 0.004, 0.004,
            0.004, 0.004, 0.003, 0.002, 0.003, 0.002, 0.002, 0.003,
            0.002, 0.002, 0.001, 0.001, 0.001, 0.001, 0.001, 0.001,
            0.001, 0.001, 0.001, 0.001, 0.001, 0.001, 0.001, 0.001,
        ],
    ),
    # hardsynth: sibling = synthwave (timbral family) even though its own
    # tempo sits in the house-family zone rather than synthwave's own
    # pocket -- no other synth-genre data exists to borrow from instead.
    # Tilt k=+0.30 (the strongest of the three synth-family shifts,
    # deliberately): the profile's own description is explicit --
    # "brighter and more forceful than synthwave's classic pocket" -- a
    # textually confirmed direction, not just a genre-feel guess.
    "hardsynth": AudioProfile(
        name="Hard Synth",
        description="Driving, energetic synth-driven electronic at house-adjacent tempo -- brighter and more forceful than synthwave's classic pocket, 120-130 BPM",
        bass_min=20.0,
        bass_max=160.0,
        mid_min=160.0,
        mid_max=2500.0,
        treble_min=2500.0,
        treble_max=20000.0,
        bass_weight=1.0,
        mid_weight=1.25,
        treble_weight=0.85,
        beat_threshold=1.3,
        smoothing=0.14,
        curve="warm",
        onset_bass_emphasis=1.6,
        onset_mid_emphasis=1.5,
        onset_treble_emphasis=1.0,
        bpm_prior_mu=125.0,
        bpm_prior_sigma=0.058,
        bpm_hint_min=120.0,
        bpm_hint_max=130.0,
        # 2026-09-10 (zone-map batch, Phase 5 prep): inherits synthwave's
        # real (n=7) zcr/onset/vocal values, same as vaporwave/chillwave.
        zcr_mu=0.0313,
        zcr_sigma=0.029,
        onset_density_mu=2.7023,
        onset_density_sigma=0.4838,
        vocal_hnr_mu=0.4833,
        vocal_fmr_mu=0.3117,
        vocal_hnr_sigma=0.1623,
        vocal_fmr_sigma=0.0586,
        # 2026-09-10 (zone-map batch, Phase 5 pilot-run fix): same missing-
        # sigma oversight as vaporwave/chillwave's own field comments --
        # synthwave's real sigma, unshifted.
        expected_bands_sigma=[
            0.094, 0.099, 0.057, 0.118, 0.095, 0.110, 0.188, 0.141,
            0.238, 0.114, 0.206, 0.096, 0.085, 0.101, 0.127, 0.055,
            0.041, 0.100, 0.034, 0.089, 0.128, 0.088, 0.072, 0.052,
            0.122, 0.019, 0.017, 0.017, 0.014, 0.013, 0.010, 0.012,
            0.011, 0.009, 0.009, 0.007, 0.007, 0.004, 0.005, 0.004,
            0.004, 0.003, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002,
            0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002,
            0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002,
        ],
        expected_bands=[
            0.101, 0.124, 0.139, 0.199, 0.221, 0.274, 0.321, 0.382,
            0.277, 0.241, 0.229, 0.250, 0.300, 0.298, 0.211, 0.175,
            0.161, 0.213, 0.186, 0.184, 0.258, 0.207, 0.233, 0.144,
            0.162, 0.026, 0.024, 0.019, 0.018, 0.017, 0.014, 0.018,
            0.016, 0.014, 0.013, 0.010, 0.010, 0.007, 0.005, 0.005,
            0.005, 0.005, 0.004, 0.003, 0.004, 0.003, 0.003, 0.004,
            0.003, 0.003, 0.001, 0.001, 0.001, 0.001, 0.001, 0.001,
            0.001, 0.001, 0.001, 0.001, 0.001, 0.001, 0.001, 0.001,
        ],
    ),
    # midtempo: sibling = deep_house. Owner's own table description:
    # "deep_house... but no 4otf" -- same tempo pocket as deep_house,
    # discriminated (once real data exists) on four-on-the-floor
    # regularity rather than tempo or timbre. Tilt k=-0.15 (mildly
    # darker/bass-forward): real-world midtempo (trap-adjacent 808 sub
    # emphasis) typically reads a bit darker than deep house's soulful
    # chord-stab presence -- weaker textual grounding than the other
    # tilts here, since the profile's real discriminator is rhythmic
    # (kick_regularity), not spectral; flagged as the lowest-confidence
    # tilt in this batch.
    "midtempo": AudioProfile(
        name="Midtempo",
        description="Deep-house-tempo material without a four-on-the-floor pulse at 112-116 BPM",
        bass_min=20.0,
        bass_max=200.0,
        mid_min=200.0,
        mid_max=2200.0,
        treble_min=2200.0,
        treble_max=20000.0,
        bass_weight=1.15,
        mid_weight=1.15,
        treble_weight=0.75,
        beat_threshold=1.2,
        smoothing=0.13,
        curve="warm",
        onset_bass_emphasis=1.5,
        onset_mid_emphasis=1.3,
        onset_treble_emphasis=0.8,
        bpm_prior_mu=114.0,
        bpm_prior_sigma=0.0253,
        bpm_hint_min=112.0,
        bpm_hint_max=116.0,
        zcr_mu=0.0372,
        zcr_sigma=0.0213,
        onset_density_mu=3.0,
        onset_density_sigma=0.9913,
        vocal_hnr_mu=0.5672,
        vocal_fmr_mu=0.3244,
        vocal_hnr_sigma=0.0444,
        vocal_fmr_sigma=0.0300,
        expected_bands=[
            0.747, 0.743, 0.744, 0.809, 0.808, 0.767, 0.746, 0.710,
            0.729, 0.662, 0.657, 0.650, 0.653, 0.536, 0.395, 0.388,
            0.381, 0.360, 0.308, 0.305, 0.263, 0.241, 0.207, 0.219,
            0.221, 0.187, 0.179, 0.152, 0.130, 0.113, 0.100, 0.090,
            0.078, 0.079, 0.067, 0.060, 0.054, 0.045, 0.041, 0.037,
            0.034, 0.029, 0.026, 0.024, 0.022, 0.020, 0.019, 0.018,
            0.016, 0.014, 0.014, 0.013, 0.012, 0.010, 0.009, 0.009,
            0.008, 0.006, 0.006, 0.005, 0.004, 0.003, 0.002, 0.001,
        ],
        expected_bands_sigma=[
            0.449, 0.435, 0.382, 0.290, 0.276, 0.280, 0.344, 0.389,
            0.260, 0.269, 0.265, 0.267, 0.254, 0.211, 0.212, 0.221,
            0.227, 0.223, 0.216, 0.205, 0.204, 0.191, 0.170, 0.174,
            0.166, 0.246, 0.241, 0.215, 0.180, 0.155, 0.137, 0.132,
            0.116, 0.117, 0.101, 0.088, 0.078, 0.067, 0.059, 0.055,
            0.050, 0.044, 0.041, 0.037, 0.034, 0.030, 0.029, 0.027,
            0.025, 0.023, 0.021, 0.020, 0.019, 0.016, 0.015, 0.014,
            0.012, 0.010, 0.010, 0.010, 0.010, 0.010, 0.010, 0.010,
        ],
    ),
    # electro: sibling = house (same tempo range, vocals present). Owner's
    # own table description flags "broken syncopated beats" as this
    # profile's real discriminator from house -- not represented in any
    # field below yet (no breaks/syncopation feature exists in this
    # codebase); a real discriminator needs new instrumentation, not just
    # corpus data, before Phase 5 can fit it. Tilt k=+0.10 (mild, the
    # weakest-grounded tilt in this batch): syncopated, forward hi-hat
    # transients read marginally brighter than house's smoother groove,
    # but this isn't the real discriminator either -- kept small
    # deliberately rather than overstating confidence in a guess.
    "electro": AudioProfile(
        name="Electro",
        description="House-tempo material with vocals but no four-on-the-floor pulse -- broken, syncopated beat patterns at 120-126 BPM",
        bass_min=20.0,
        bass_max=250.0,
        mid_min=250.0,
        mid_max=2000.0,
        treble_min=2000.0,
        treble_max=20000.0,
        bass_weight=1.2,
        mid_weight=1.0,
        treble_weight=0.9,
        beat_threshold=1.15,
        smoothing=0.12,
        curve="bass_boost",
        onset_bass_emphasis=1.4,
        onset_mid_emphasis=1.0,
        onset_treble_emphasis=0.75,
        bpm_prior_mu=123.0,
        bpm_prior_sigma=0.0352,
        bpm_hint_min=120.0,
        bpm_hint_max=126.0,
        zcr_mu=0.0556,
        zcr_sigma=0.0287,
        onset_density_mu=3.0,
        onset_density_sigma=0.7521,
        vocal_hnr_mu=0.4347,
        vocal_fmr_mu=0.3315,
        vocal_hnr_sigma=0.0764,
        vocal_fmr_sigma=0.0376,
        expected_bands=[
            0.628, 0.633, 0.637, 0.661, 0.728, 0.726, 0.686, 0.663,
            0.645, 0.572, 0.575, 0.578, 0.582, 0.456, 0.324, 0.331,
            0.333, 0.298, 0.275, 0.271, 0.259, 0.227, 0.202, 0.186,
            0.167, 0.126, 0.114, 0.106, 0.102, 0.095, 0.091, 0.098,
            0.079, 0.078, 0.070, 0.061, 0.057, 0.051, 0.044, 0.043,
            0.042, 0.037, 0.034, 0.031, 0.031, 0.030, 0.029, 0.028,
            0.025, 0.028, 0.026, 0.024, 0.021, 0.021, 0.020, 0.019,
            0.019, 0.017, 0.014, 0.013, 0.011, 0.008, 0.006, 0.003,
        ],
        expected_bands_sigma=[
            0.434, 0.432, 0.414, 0.336, 0.272, 0.276, 0.333, 0.390,
            0.268, 0.271, 0.278, 0.274, 0.291, 0.218, 0.203, 0.206,
            0.216, 0.195, 0.193, 0.186, 0.184, 0.178, 0.159, 0.150,
            0.133, 0.154, 0.142, 0.134, 0.126, 0.114, 0.108, 0.110,
            0.093, 0.089, 0.082, 0.070, 0.065, 0.058, 0.053, 0.052,
            0.050, 0.045, 0.042, 0.039, 0.038, 0.036, 0.035, 0.034,
            0.031, 0.033, 0.032, 0.029, 0.026, 0.026, 0.025, 0.023,
            0.023, 0.020, 0.018, 0.016, 0.013, 0.010, 0.010, 0.010,
        ],
    ),
    # deeptrance: sibling = trance (thematically closest). Tempo range
    # (120-126) differs substantially from trance's own real 132-138 band
    # -- this placeholder's fingerprint is a rougher proxy than most of
    # the others above as a result. Tilt k=-0.15 (mildly darker): "deep"
    # variants typically read a bit warmer/bass-forward than the regular
    # genre they're a slower cousin of -- textually weak grounding
    # (trance's own family description doesn't call this out directly),
    # flagged as a softer guess than the hyphy/rap_rnb/peak_time splits.
    "deeptrance": AudioProfile(
        name="Deep Trance",
        description="Melodic, hypnotic trance at a house-adjacent tempo -- 120-126 BPM",
        bass_min=30.0,
        bass_max=200.0,
        mid_min=200.0,
        mid_max=4000.0,
        treble_min=4000.0,
        treble_max=20000.0,
        bass_weight=1.0,
        mid_weight=1.3,
        treble_weight=1.2,
        beat_threshold=1.1,
        smoothing=0.08,
        curve="mid_treble_boost",
        onset_bass_emphasis=1.8,
        onset_mid_emphasis=1.3,
        onset_treble_emphasis=0.9,
        bpm_prior_mu=123.0,
        bpm_prior_sigma=0.0352,
        bpm_hint_min=120.0,
        bpm_hint_max=126.0,
        zcr_mu=0.0627,
        zcr_sigma=0.0271,
        onset_density_mu=3.32,
        onset_density_sigma=1.0831,
        vocal_hnr_mu=0.3711,
        vocal_fmr_mu=0.2882,
        vocal_hnr_sigma=0.1156,
        vocal_fmr_sigma=0.0378,
        expected_bands=[
            0.979, 0.971, 0.963, 0.955, 0.947, 0.939, 0.931, 0.923,
            0.897, 0.860, 0.857, 0.853, 0.849, 0.672, 0.497, 0.495,
            0.493, 0.431, 0.357, 0.338, 0.307, 0.281, 0.264, 0.233,
            0.214, 0.209, 0.203, 0.188, 0.181, 0.165, 0.162, 0.151,
            0.137, 0.127, 0.118, 0.101, 0.090, 0.090, 0.086, 0.078,
            0.079, 0.070, 0.067, 0.061, 0.055, 0.053, 0.052, 0.047,
            0.044, 0.045, 0.043, 0.033, 0.033, 0.028, 0.025, 0.022,
            0.020, 0.018, 0.016, 0.014, 0.011, 0.009, 0.006, 0.004,
        ],
        expected_bands_sigma=[
            0.170, 0.170, 0.170, 0.170, 0.170, 0.170, 0.170, 0.170,
            0.090, 0.180, 0.180, 0.180, 0.180, 0.162, 0.145, 0.145,
            0.145, 0.129, 0.128, 0.137, 0.135, 0.131, 0.137, 0.130,
            0.136, 0.135, 0.139, 0.129, 0.106, 0.099, 0.104, 0.092,
            0.093, 0.095, 0.078, 0.071, 0.064, 0.061, 0.058, 0.054,
            0.054, 0.050, 0.044, 0.048, 0.046, 0.045, 0.041, 0.037,
            0.037, 0.037, 0.037, 0.029, 0.031, 0.028, 0.028, 0.026,
            0.025, 0.021, 0.018, 0.016, 0.013, 0.010, 0.010, 0.010,
        ],
    ),
    # ------------------------------------------------------------------
    # 2026-09-10 (zone-map batch, Phase 5 prep): four dark/bright split
    # siblings. `progressive` (deep_house's bright pole) got a real
    # corpus, `training-progressive-house-01`, sitting unused with 15
    # already-packaged buckets -- see its own field comment below for the
    # real derivation. The other three (`rnb`, `trap`, `peak`) still have
    # no data of their own; each gets the same directional-tilt treatment
    # as the seven family-dependent profiles above rather than a verbatim
    # donor copy (owner: "for anything we split that we don't have data
    # for... shift the spectrum ribbon based on your best educated
    # guess"). See docs/adr/vj-system.md "Fingerprint-Family Map
    # Formalized" for the full family/taxonomy reasoning this table was
    # built from.
    # ------------------------------------------------------------------
    # rnb: bright pole of the rap/rnb split. Originally a k=+0.25 tilt of
    # rap_rnb's own (pooled hip-hop+rnb) ribbon.
    #
    # 2026-09-10 (zone-map batch, Phase 5 fingerprint refresh): superseded
    # by real data -- training-rnb-01 had 20 packaged buckets already
    # sitting unused (7 distinct tracks; thin, but real, and the SAME
    # standard other real profiles in this roster get flagged at when
    # thin). rap_rnb also decoupled the same day to derive from
    # training-hip-hop-01 alone rather than pooled hip-hop+rnb (see
    # rap_rnb's own field comment) -- the two poles now have genuinely
    # independent real fingerprints instead of one pooled reading split
    # by a guess.
    "rnb": AudioProfile(
        name="R&B",
        description="Heavy sub-bass with sustained, vocal-forward mids at 70-100 BPM -- the brighter pole of the rap/R&B split",
        bass_min=30.0,
        bass_max=275.0,
        mid_min=275.0,
        mid_max=3000.0,
        treble_min=3000.0,
        treble_max=20000.0,
        bass_weight=1.25,
        mid_weight=1.3,
        treble_weight=0.85,
        beat_threshold=1.12,
        smoothing=0.135,
        curve="extreme_bass_boost",
        onset_bass_emphasis=1.6,
        onset_mid_emphasis=1.1,
        onset_treble_emphasis=0.75,
        bpm_prior_mu=85.0,
        bpm_prior_sigma=0.29,
        bpm_hint_min=70.0,
        bpm_hint_max=100.0,
        zcr_mu=0.0411,
        zcr_sigma=0.0406,
        onset_density_mu=2.7919,
        onset_density_sigma=0.4047,
        vocal_hnr_mu=0.5047,
        vocal_fmr_mu=0.3675,
        vocal_hnr_sigma=0.1716,
        vocal_fmr_sigma=0.0575,
        expected_bands=[
            0.664, 0.681, 0.672, 0.644, 0.626, 0.621, 0.617, 0.618,
            0.503, 0.417, 0.416, 0.417, 0.412, 0.349, 0.280, 0.279,
            0.277, 0.293, 0.294, 0.317, 0.317, 0.256, 0.275, 0.232,
            0.236, 0.243, 0.253, 0.279, 0.289, 0.265, 0.212, 0.243,
            0.213, 0.168, 0.161, 0.133, 0.127, 0.116, 0.099, 0.087,
            0.082, 0.076, 0.077, 0.075, 0.060, 0.066, 0.061, 0.048,
            0.054, 0.053, 0.046, 0.041, 0.038, 0.033, 0.035, 0.038,
            0.040, 0.036, 0.032, 0.027, 0.019, 0.012, 0.009, 0.007,
        ],
        expected_bands_sigma=[
            0.115, 0.120, 0.101, 0.130, 0.173, 0.170, 0.157, 0.141,
            0.119, 0.099, 0.098, 0.107, 0.102, 0.055, 0.042, 0.042,
            0.042, 0.044, 0.044, 0.051, 0.098, 0.076, 0.108, 0.087,
            0.105, 0.126, 0.137, 0.091, 0.068, 0.081, 0.123, 0.036,
            0.071, 0.025, 0.031, 0.031, 0.035, 0.017, 0.066, 0.038,
            0.031, 0.030, 0.023, 0.020, 0.023, 0.012, 0.011, 0.017,
            0.011, 0.008, 0.039, 0.022, 0.023, 0.015, 0.005, 0.010,
            0.017, 0.016, 0.026, 0.022, 0.011, 0.005, 0.004, 0.003,
        ],
    ),
    # trap: dark pole of the hyphy/trap split. Originally a k=-0.25 tilt
    # of hyphy's own ribbon.
    #
    # 2026-09-10 (zone-map batch, Phase 5 fingerprint refresh): superseded
    # by real data -- training-trap-hip-hop-01 (34 packaged buckets, 21
    # tracks) is the SAME corpus hyphy's own fingerprint already comes
    # from (hyphy's own field comment: "no content of its own distinct
    # from a straight trap read"). Deriving trap directly from it means
    # trap and hyphy now carry nearly identical real fingerprints -- an
    # honest reflection of that pre-existing caveat, not a new problem:
    # real data that happens to coincide beats a guessed tilt that
    # doesn't. hyphy's own values refreshed to the same pooled corpus
    # below, for consistency.
    "trap": AudioProfile(
        name="Trap",
        description="Aggressive sub-bass, sustained hype-vocal chops, bright treble at 105-116 BPM -- the darker pole of the hyphy/trap split",
        bass_min=20.0,
        bass_max=350.0,
        mid_min=350.0,
        mid_max=3000.0,
        treble_min=3000.0,
        treble_max=20000.0,
        bass_weight=1.5,
        mid_weight=1.3,
        treble_weight=1.1,
        beat_threshold=0.95,
        smoothing=0.15,
        curve="extreme_bass_boost",
        onset_bass_emphasis=1.5,
        onset_mid_emphasis=1.0,
        onset_treble_emphasis=0.80,
        bpm_prior_mu=109.0,
        bpm_prior_sigma=0.15,
        bpm_hint_min=105.0,
        bpm_hint_max=116.0,
        zcr_mu=0.0294,
        zcr_sigma=0.0348,
        onset_density_mu=3.0042,
        onset_density_sigma=0.3937,
        vocal_hnr_mu=0.5324,
        vocal_fmr_mu=0.3623,
        vocal_hnr_sigma=0.1805,
        vocal_fmr_sigma=0.0711,
        expected_bands=[
            0.746, 0.745, 0.749, 0.753, 0.753, 0.747, 0.753, 0.751,
            0.652, 0.574, 0.570, 0.571, 0.568, 0.480, 0.404, 0.406,
            0.406, 0.350, 0.297, 0.296, 0.270, 0.252, 0.236, 0.209,
            0.205, 0.217, 0.228, 0.219, 0.178, 0.182, 0.160, 0.129,
            0.120, 0.106, 0.096, 0.081, 0.069, 0.074, 0.061, 0.064,
            0.053, 0.044, 0.043, 0.041, 0.047, 0.037, 0.028, 0.026,
            0.030, 0.024, 0.023, 0.018, 0.019, 0.019, 0.021, 0.022,
            0.020, 0.018, 0.013, 0.009, 0.008, 0.005, 0.003, 0.002,
        ],
        expected_bands_sigma=[
            0.127, 0.140, 0.147, 0.157, 0.160, 0.170, 0.152, 0.131,
            0.098, 0.127, 0.124, 0.118, 0.122, 0.106, 0.150, 0.154,
            0.149, 0.146, 0.114, 0.089, 0.095, 0.118, 0.138, 0.130,
            0.106, 0.123, 0.104, 0.092, 0.081, 0.088, 0.060, 0.053,
            0.048, 0.057, 0.038, 0.034, 0.025, 0.028, 0.020, 0.032,
            0.025, 0.018, 0.019, 0.017, 0.014, 0.021, 0.018, 0.018,
            0.020, 0.016, 0.012, 0.011, 0.008, 0.009, 0.010, 0.011,
            0.015, 0.016, 0.007, 0.006, 0.007, 0.004, 0.002, 0.002,
        ],
    ),
    # peak: bright pole of the hard/peak split, sibling = peak_time (donor).
    # Tilt k=+0.25: "hard (dark) / peak (bright)" owner split -- peak
    # time's festival-energy, bright-tops character reads brighter than
    # the darker/heavier "hard" pole.
    "peak": AudioProfile(
        name="Peak Time",
        description="Festival-ready kick, bright tops, and no patience for low-energy lanes at 130-136 BPM -- the brighter pole of the hard/peak split",
        bass_min=25.0,
        bass_max=230.0,
        mid_min=230.0,
        mid_max=3800.0,
        treble_min=3800.0,
        treble_max=20000.0,
        bass_weight=1.15,
        mid_weight=1.10,
        treble_weight=1.00,
        beat_threshold=1.05,
        smoothing=0.09,
        curve="bright",
        onset_bass_emphasis=1.10,
        onset_mid_emphasis=1.35,
        onset_treble_emphasis=1.15,
        bpm_prior_mu=130.0,
        bpm_prior_sigma=0.0741,
        bpm_hint_min=130.0,
        bpm_hint_max=136.0,
        zcr_mu=0.0502,
        zcr_sigma=0.0343,
        onset_density_mu=2.75,
        onset_density_sigma=0.72,
        vocal_hnr_mu=0.4573,
        vocal_fmr_mu=0.3097,
        vocal_hnr_sigma=0.0847,
        vocal_fmr_sigma=0.0357,
        expected_bands=[
            0.458, 0.475, 0.495, 0.539, 0.561, 0.562, 0.556, 0.550,
            0.536, 0.505, 0.517, 0.523, 0.534, 0.502, 0.361, 0.388,
            0.398, 0.381, 0.302, 0.278, 0.238, 0.227, 0.206, 0.225,
            0.226, 0.177, 0.180, 0.155, 0.151, 0.144, 0.119, 0.100,
            0.095, 0.088, 0.073, 0.070, 0.065, 0.057, 0.054, 0.049,
            0.044, 0.037, 0.033, 0.031, 0.029, 0.025, 0.021, 0.019,
            0.015, 0.013, 0.013, 0.011, 0.013, 0.014, 0.014, 0.014,
            0.011, 0.014, 0.011, 0.010, 0.009, 0.007, 0.006, 0.005,
        ],
        expected_bands_sigma=[
            0.478, 0.444, 0.406, 0.344, 0.334, 0.320, 0.328, 0.379,
            0.311, 0.268, 0.264, 0.274, 0.264, 0.203, 0.252, 0.252,
            0.264, 0.234, 0.224, 0.203, 0.162, 0.139, 0.125, 0.141,
            0.147, 0.195, 0.187, 0.160, 0.155, 0.143, 0.120, 0.105,
            0.096, 0.090, 0.075, 0.070, 0.066, 0.059, 0.055, 0.049,
            0.045, 0.040, 0.035, 0.034, 0.032, 0.027, 0.024, 0.020,
            0.017, 0.015, 0.015, 0.013, 0.014, 0.015, 0.015, 0.015,
            0.013, 0.015, 0.012, 0.012, 0.010, 0.010, 0.010, 0.010,
        ],
    ),
    # progressive: bright pole of the deep/progressive split, sibling =
    # deep_house (donor). Shares deep_house's own 112-116 BPM window
    # exactly (owner-confirmed: "progressive (bright) & deep (dark)
    # house, same bpm range, yes").
    #
    # 2026-09-10 (zone-map batch, Phase 5 prep): unlike rnb/trap/peak
    # above, this one gets REAL data, not a guess --
    # `training-progressive-house-01` was already sitting on disk with 15
    # packaged buckets (13 distinct tracks, ~120.6k heartbeat rows),
    # never used to derive this profile's own fields. expected_bands/
    # expected_bands_sigma/vocal_hnr_mu/vocal_fmr_mu below are the real
    # per-track ribbon/median (same methodology as every other real
    # profile in this roster). zcr_mu/onset_density_mu are NOT
    # real -- this corpus predates when those fields were wired into the
    # packaged corpus writer (n=0 rows carry them), so they stay
    # inherited from deep_house pending a fresher capture. BPM fields
    # untouched regardless (owner-confirmed, see above) -- this corpus's
    # own detected BPMs scatter widely (125-176), not treated as ground
    # truth for tempo the same way its spectral content is trusted for
    # brightness.
    "progressive": AudioProfile(
        name="Progressive House",
        description=(
            "Warm rolling sub-bass, soulful/jazzy chord stabs, and soft "
            "filtered hats at 112-116 BPM -- the brighter pole of the "
            "deep/progressive split"
        ),
        bass_min=20.0,
        bass_max=200.0,
        mid_min=200.0,
        mid_max=2200.0,
        treble_min=2200.0,
        treble_max=20000.0,
        bass_weight=1.15,
        mid_weight=1.15,
        treble_weight=0.75,
        beat_threshold=1.2,
        smoothing=0.13,
        curve="warm",
        onset_bass_emphasis=1.5,
        onset_mid_emphasis=1.3,
        onset_treble_emphasis=0.8,
        bpm_prior_mu=115.0,
        bpm_prior_sigma=0.0445,
        bpm_hint_min=112.0,
        bpm_hint_max=116.0,
        # 2026-09-10 (zone-map batch, Phase 5 prep): zcr/onset_density are
        # NOT real -- inherited from deep_house pending a fresher capture
        # (training-progressive-house-01 predates when these fields were
        # wired into the corpus writer). vocal_hnr/vocal_fmr below ARE
        # real (per-row median over the same 15-bucket corpus).
        zcr_mu=0.0333,
        zcr_sigma=0.0406,
        onset_density_mu=2.8914,
        onset_density_sigma=0.4695,
        vocal_hnr_mu=0.4366,
        vocal_fmr_mu=0.2922,
        vocal_hnr_sigma=0.1826,
        vocal_fmr_sigma=0.0586,
        # 2026-09-10 (zone-map batch, Phase 5 prep): real per-track ribbon
        # (median/MAD-derived sigma) from training-progressive-house-01's
        # own 15 packaged buckets (13 tracks, ~120.6k heartbeat rows).
        # Consistently higher across nearly every band than deep_house's
        # own real ribbon -- read as generally more energetic/sustained
        # (progressive's characteristic long builds) rather than a
        # brightness-only difference; deep_house's own vocal medians
        # (0.5672/0.3244) are meaningfully higher than this profile's,
        # consistent with deep house's more pronounced soulful-vocal
        # presence vs. progressive's more instrumental-build character.
        # 2026-09-10 (zone-map batch, Phase 5 fingerprint refresh): re-derived pooling ALL packaged buckets under this list's own training slug (same per-track median/MAD ribbon methodology), including the owner's pilot-run tracks from this same session.
        expected_bands=[
            0.753, 0.756, 0.756, 0.761, 0.766, 0.770, 0.770, 0.763,
            0.700, 0.693, 0.693, 0.693, 0.693, 0.586, 0.465, 0.467,
            0.468, 0.408, 0.357, 0.330, 0.285, 0.275, 0.265, 0.284,
            0.272, 0.244, 0.182, 0.174, 0.185, 0.164, 0.154, 0.141,
            0.134, 0.124, 0.121, 0.103, 0.084, 0.083, 0.082, 0.078,
            0.070, 0.075, 0.063, 0.065, 0.050, 0.045, 0.044, 0.052,
            0.045, 0.047, 0.045, 0.040, 0.038, 0.040, 0.036, 0.036,
            0.037, 0.034, 0.036, 0.030, 0.022, 0.016, 0.010, 0.007,
        ],
        expected_bands_sigma=[
            0.113, 0.113, 0.113, 0.114, 0.116, 0.123, 0.115, 0.114,
            0.105, 0.104, 0.104, 0.104, 0.104, 0.088, 0.102, 0.106,
            0.108, 0.061, 0.054, 0.049, 0.059, 0.057, 0.126, 0.085,
            0.089, 0.103, 0.105, 0.089, 0.091, 0.081, 0.064, 0.037,
            0.035, 0.040, 0.040, 0.062, 0.047, 0.031, 0.044, 0.036,
            0.034, 0.048, 0.042, 0.042, 0.042, 0.028, 0.031, 0.038,
            0.033, 0.036, 0.032, 0.024, 0.026, 0.026, 0.021, 0.022,
            0.026, 0.016, 0.027, 0.022, 0.014, 0.009, 0.007, 0.004,
        ],
    ),
}


def get_profile(name: str) -> AudioProfile:
    """Get a profile by name. Falls back to 'house' if not found.

    2026-08-10: 'generic' (the previous fallback target) was eliminated
    entirely as part of the house-family consolidation pass -- it was a
    disabled, deliberately-uncalibrated catch-all never meant to be a real
    analyzer profile (see AudioManager.__init__'s own 'house' default and
    its field comment for the identical reasoning, established 2026-08-06).
    Falling back to 'house' here instead extends that same reasoning to
    this second, previously-inconsistent fallback path -- an unknown/typo'd
    profile key now degrades to the same well-populated, real profile the
    app already starts on by default, not a deliberately weak one.

    Direct-lookup path: resolves a disabled profile too (e.g. 'generic'
    itself, or any explicit config reference) -- only discovery
    (list_profiles() / enabled_profiles()) hides disabled profiles.
    """
    return PROFILES.get(name, PROFILES["house"])


def enabled_profiles() -> Dict[str, AudioProfile]:
    """Return {key: profile} for discoverable profiles only.

    Used by both list_profiles() (Alt+A cycling) and the auto-vj
    recommender's candidate pool, so "disabled" consistently means
    "excluded from discovery" in both places -- not just hidden from one.
    """
    return {key: profile for key, profile in PROFILES.items() if profile.enabled}


def list_profiles() -> list[str]:
    """Return list of discoverable (enabled) profile names."""
    return sorted(enabled_profiles().keys())
