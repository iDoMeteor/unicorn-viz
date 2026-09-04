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
    # spectral_centroid_mu: frequency-weighted mean of spectrum (Hz) — "brightness".
    #   2026-08-09: recalibrated for all 20 profiles. The original values
    #   (independently hand/LLM-authored, same synthesis pass as bpm_prior_mu
    #   etc.) disagreed substantially with each profile's own expected_bands
    #   fingerprint -- computing the same weighted-mean-frequency the live
    #   recommender uses, directly against expected_bands, showed 14 of 20
    #   profiles implied a meaningfully *brighter* target than the stated mu
    #   (up to 1.9x for chillstep, 1.77x for house). Found live: a real
    #   session's observed centroid (~2900-4300 Hz) looked like a wild outlier
    #   against the old mu values but was actually close to what most
    #   profiles' own fingerprints already implied. Now mu = the centroid
    #   implied by that same profile's expected_bands (rounded to the nearest
    #   50 Hz), so the two brightness representations can't disagree by
    #   construction. This does NOT validate expected_bands itself -- see
    #   docs/adr/vj-system.md's centroid recalibration entry for two known
    #   ordering surprises (house now implies brighter than tech_house;
    #   chillstep now implies brighter than synthwave) that contradict the
    #   genres' own documented acoustic character, meaning the fingerprints
    #   themselves may need their own accuracy pass, not just this one.
    #
    #   2026-09-04 (recommender rc.29): mechanically re-derived for the 13
    #   profiles whose expected_bands moved under the same-night ribbon
    #   redesign (house, deep_house, tech_house, peak_time, trance,
    #   electronic, techno, drum_and_bass, dubstep, rap_rnb, hyphy, ambient,
    #   chillstep) -- same formula/rounding as the 2026-08-09 pass above, run
    #   against each profile's CURRENT (ribbon-derived, real per-track
    #   median) expected_bands instead of the stale pre-redesign arrays.
    #   centroid_fit's weight is 0.0 (dormant) so this has zero live-scoring
    #   effect either way -- purely a "keep the two brightness
    #   representations from disagreeing by construction" mechanical fix,
    #   per the same reasoning as 2026-08-09.
    #
    #   Result is worth flagging before this term is ever un-dormant: the 13
    #   recomputed values landed in a narrow 250-450 Hz band (vs. the old
    #   950-2900 Hz spread) -- confirms, with real per-track corpus data
    #   this time, the exact failure mode auto_vj.py's own centroid formula
    #   comment already documented from 2026-08-11 (real measured band
    #   energy decays bass-dominant much faster than any hand/LLM-authored
    #   fingerprint assumed, collapsing the log-band-implied centroid toward
    #   ~300-450 Hz for nearly all real audio regardless of genre). Do NOT
    #   re-enable centroid_fit's weight against these values without first
    #   addressing that discriminating-power problem -- it would reproduce
    #   the 2026-08-11 "recommender stuck on one profile" incident.
    # spectral_centroid_sigma: how tightly this genre's brightness clusters
    #   around spectral_centroid_mu (Hz). Mirrors bpm_prior_sigma's role for
    #   tempo -- a genre with a very characteristic, consistent timbral
    #   signature (dubstep's wobble, psytrance's saw leads) should be tight;
    #   a broad-church catch-all (house, generic) should be wide.
    #   2026-08-06: added as a coarse tight/medium/wide tier assignment by
    #   genre feel (250/400/600), not a fitted value -- see
    #   drop-ins/auto-vj-01/docs/weights-and-thresholds.md and the accuracy
    #   tracking spec for the plan to replace these with measured values
    #   once real hit/miss data exists. 400 (the old fixed constant every
    #   profile used before this field existed) is the default for any
    #   profile that doesn't set it explicitly.
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
    #   fields. `zcr_sigma` landed on the 0.03 floor for all 12 profiles --
    #   the real MAD came in below it every time, so zcr_sigma currently
    #   discriminates nothing between genres (zcr_mu still does, e.g.
    #   chillstep 0.0297 vs trance 0.0627, a ~2x spread). Worth a flag:
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
    spectral_centroid_mu: float | None = None
    spectral_centroid_sigma: float = 400.0
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
        bpm_prior_mu=122.0,
        bpm_prior_sigma=0.0297,
        bpm_hint_min=118.0,
        bpm_hint_max=126.0,
        spectral_centroid_mu=450.0,
        spectral_centroid_sigma=600.0,
        zcr_mu=0.0556,
        zcr_sigma=0.03,
        onset_density_mu=3.0,
        onset_density_sigma=0.4596,
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
        vocal_hnr_mu=0.4347,
        vocal_fmr_mu=0.3315,
        vocal_hnr_sigma=0.0764,
        vocal_fmr_sigma=0.0376,
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
        expected_bands=[
            0.808, 0.808, 0.808, 0.808, 0.808, 0.808, 0.808, 0.808,
            0.745, 0.672, 0.672, 0.672, 0.672, 0.527, 0.437, 0.437,
            0.437, 0.410, 0.375, 0.357, 0.334, 0.314, 0.292, 0.253,
            0.220, 0.213, 0.198, 0.176, 0.169, 0.147, 0.152, 0.145,
            0.145, 0.122, 0.107, 0.108, 0.095, 0.093, 0.083, 0.086,
            0.082, 0.070, 0.065, 0.072, 0.064, 0.053, 0.060, 0.054,
            0.046, 0.050, 0.053, 0.049, 0.047, 0.044, 0.043, 0.037,
            0.036, 0.035, 0.029, 0.022, 0.021, 0.013, 0.011, 0.006,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.121, 0.121, 0.121, 0.121, 0.121, 0.121, 0.121, 0.121,
            0.112, 0.117, 0.117, 0.117, 0.117, 0.079, 0.075, 0.075,
            0.075, 0.061, 0.090, 0.077, 0.064, 0.061, 0.053, 0.077,
            0.090, 0.095, 0.060, 0.054, 0.056, 0.059, 0.070, 0.061,
            0.034, 0.018, 0.027, 0.039, 0.030, 0.054, 0.039, 0.035,
            0.049, 0.034, 0.043, 0.043, 0.042, 0.040, 0.042, 0.038,
            0.029, 0.034, 0.034, 0.030, 0.029, 0.027, 0.025, 0.023,
            0.031, 0.019, 0.022, 0.016, 0.015, 0.009, 0.008, 0.005,
        ],
    ),
    # 2026-08-03: added alongside 'synthwave' -- 'house' and 'tech_house'
    # were the only two points on the house-family spectrum, leaving the
    # warmer/slower/chord-driven end uncovered and prone to landing on
    # 'house' with a poor spectral match.
    "deep_house": AudioProfile(
        name="Deep House",
        description=(
            "Warm rolling sub-bass, soulful/jazzy chord stabs, and soft "
            "filtered hats at 112-118 BPM -- slower, darker, and more "
            "melodic than house"
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
        bpm_prior_mu=115.0,
        bpm_prior_sigma=0.0445,
        bpm_hint_min=112.0,
        bpm_hint_max=118.0,
        # Warmer/less bright than house (1500 Hz) -- the chord stabs and
        # rolled-off hats keep energy lower in the spectrum.
        spectral_centroid_mu=350.0,
        spectral_centroid_sigma=400.0,
        zcr_mu=0.0372,
        zcr_sigma=0.03,
        onset_density_mu=3.0,
        onset_density_sigma=0.4225,
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
        vocal_hnr_mu=0.5672,
        vocal_fmr_mu=0.3244,
        vocal_hnr_sigma=0.0444,
        vocal_fmr_sigma=0.0300,
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
            0.720, 0.720, 0.720, 0.720, 0.720, 0.720, 0.720, 0.720,
            0.709, 0.709, 0.709, 0.709, 0.709, 0.604, 0.506, 0.506,
            0.506, 0.452, 0.440, 0.445, 0.439, 0.384, 0.319, 0.288,
            0.321, 0.330, 0.299, 0.257, 0.234, 0.201, 0.177, 0.180,
            0.158, 0.172, 0.143, 0.112, 0.096, 0.081, 0.071, 0.065,
            0.057, 0.051, 0.066, 0.054, 0.051, 0.044, 0.044, 0.048,
            0.045, 0.040, 0.034, 0.029, 0.029, 0.025, 0.023, 0.023,
            0.021, 0.018, 0.015, 0.010, 0.008, 0.006, 0.004, 0.003,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.108, 0.108, 0.108, 0.108, 0.108, 0.108, 0.108, 0.108,
            0.106, 0.106, 0.106, 0.106, 0.106, 0.091, 0.086, 0.086,
            0.086, 0.112, 0.083, 0.082, 0.081, 0.112, 0.157, 0.116,
            0.096, 0.050, 0.085, 0.098, 0.077, 0.070, 0.041, 0.056,
            0.065, 0.064, 0.061, 0.050, 0.031, 0.032, 0.022, 0.022,
            0.012, 0.008, 0.024, 0.026, 0.027, 0.026, 0.021, 0.011,
            0.017, 0.018, 0.014, 0.013, 0.011, 0.015, 0.014, 0.014,
            0.015, 0.013, 0.009, 0.007, 0.005, 0.004, 0.002, 0.002,
        ],
    ),
    "tech_house": AudioProfile(
        name="Tech House",
        # 2026-08-11: disabled -- pending a library with enough tech_house-
        # specific material to recalibrate spectral_centroid_mu against a
        # real measured average. Root cause: spectral_centroid_mu here
        # (2900.0, below) comes from the same buggy expected_bands-derived
        # formula flagged in auto_vj.py's _DEFAULT_RECO_WEIGHTS
        # ('centroid_fit' comment) and docs/adr/vj-system.md -- log-band-
        # weighted, not the live linear-FFT-weighted measurement it's
        # compared against -- and this profile sits closest of any in the
        # roster to peak_time on both bpm_prior_mu (130.5 vs 130.0, bands
        # fully overlapping) and onset_density_mu (2.8 vs peak_time's 3.2),
        # so it leans on that unreliable centroid axis harder than most to
        # win ties. Same disable-not-delete pattern as hyphy (owner: this
        # is a pause, not a removal) -- re-enable once real tech_house
        # material exists to recalibrate against.
        enabled=False,
        description="Punchy low-end, clipped claps, tight hats, and steady 4/4 pressure at 127-134 BPM -- darker than house",
        bass_min=25.0,
        bass_max=220.0,
        mid_min=220.0,
        mid_max=3200.0,
        treble_min=3200.0,
        treble_max=20000.0,
        bass_weight=1.25,
        mid_weight=1.05,
        treble_weight=0.95,
        beat_threshold=1.10,
        smoothing=0.10,
        curve="bass_boost",
        onset_bass_emphasis=1.55,
        onset_mid_emphasis=1.10,
        onset_treble_emphasis=0.80,
        # 2026-08-10: house-family consolidation, see house's own field
        # comment for the full rationale. Band moved from 122-130
        # (overlapping house's old 120-128 across 6 of its 8 BPM span) to
        # 127-134, adjacent to house's new 118-126, no longer overlapping.
        # 2026-08-14: sigma-matches-hint-band pass (see house's own field
        # comment) -- derived value 0.04, unclamped the same night (see house's own field comment).
        # 2026-09-04 (recommender rc.28, evidence-based sigma pass):
        # 0.0412 -> 0.0445, real per-track spread on training-tech-house-01
        # (17 tracks). mu DELIBERATELY unchanged -- see house's own
        # 2026-09-04 field comment (this profile's real median, 129.9,
        # sits right at the edge of the house-family cluster).
        bpm_prior_mu=130.5,
        bpm_prior_sigma=0.0445,
        bpm_hint_min=127.0,
        bpm_hint_max=134.0,
        # 2026-08-09: 2550 -> 2900 (LLM tuning rec from `library/a`, observed
        # 2910.5) -- increases separation from house's own mu (2650), the
        # exact pair behind that session's #1 confusion (Tech House ->
        # house, 1060x). See docs/planning/
        # auto-vj-director-detector-refinement-plan-2026-08-09.md section 1.
        spectral_centroid_mu=400.0,
        spectral_centroid_sigma=250.0,
        zcr_mu=0.0449,
        zcr_sigma=0.03,
        onset_density_mu=2.88,
        onset_density_sigma=0.5486,
        # 2026-09-03 (recommender rc.27, vocal-term calibration): median
        # vocal_hnr/vocal_fmr from training-tech-house-01's own corpus.
        # Replaces the generic 0.35/0.25 default -- see house's own field
        # comment for the full methodology pointer.
        vocal_hnr_mu=0.4777,
        vocal_fmr_mu=0.3171,
        vocal_hnr_sigma=0.0711,
        vocal_fmr_sigma=0.0300,
        # 2026-09-04 (recommender rc.29, per-track median-of-medians re-fit,
        # n=17 tracks): mu shifted 0.4598->0.4777 / 0.3159->0.3171 and adds
        # a real fitted sigma in place of the flat 0.20/0.15 constant.
        # 2026-09-03 (recommender rc.27, data-derived fingerprints): mean
        # `bands` over training-tech-house-01's own corpus (both seeds,
        # ~7.6k heartbeats). Updated for consistency/future re-enable even
        # though this profile is currently disabled=True. See
        # docs/adr/vj-system.md "Data-Derived expected_bands".
        expected_bands=[
            0.786, 0.786, 0.786, 0.786, 0.786, 0.786, 0.786, 0.786,
            0.715, 0.603, 0.603, 0.603, 0.603, 0.507, 0.404, 0.404,
            0.404, 0.371, 0.360, 0.329, 0.277, 0.262, 0.253, 0.253,
            0.244, 0.225, 0.224, 0.209, 0.191, 0.195, 0.184, 0.164,
            0.152, 0.140, 0.105, 0.114, 0.101, 0.095, 0.084, 0.075,
            0.073, 0.060, 0.061, 0.053, 0.053, 0.053, 0.046, 0.048,
            0.046, 0.044, 0.035, 0.032, 0.029, 0.033, 0.029, 0.030,
            0.028, 0.025, 0.021, 0.019, 0.015, 0.011, 0.008, 0.005,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.118, 0.118, 0.118, 0.118, 0.118, 0.118, 0.118, 0.118,
            0.107, 0.090, 0.090, 0.090, 0.090, 0.076, 0.113, 0.113,
            0.113, 0.086, 0.092, 0.092, 0.087, 0.077, 0.086, 0.059,
            0.053, 0.063, 0.058, 0.054, 0.077, 0.083, 0.048, 0.064,
            0.078, 0.072, 0.030, 0.049, 0.039, 0.025, 0.023, 0.015,
            0.026, 0.025, 0.020, 0.023, 0.023, 0.016, 0.014, 0.018,
            0.018, 0.012, 0.009, 0.008, 0.012, 0.013, 0.011, 0.014,
            0.014, 0.014, 0.011, 0.008, 0.008, 0.005, 0.004, 0.003,
        ],
    ),
    "peak_time": AudioProfile(
        name="Peak-Time",
        description="Festival-ready kick, bright tops, and no patience for low-energy lanes",
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
        # sits right at the edge of the house-family cluster, same as
        # tech_house).
        bpm_prior_mu=130.0,
        bpm_prior_sigma=0.0741,
        bpm_hint_min=126.0,
        bpm_hint_max=136.0,
        spectral_centroid_mu=400.0,
        spectral_centroid_sigma=400.0,
        zcr_mu=0.0502,
        zcr_sigma=0.03,
        onset_density_mu=2.75,
        onset_density_sigma=0.1927,
        # 2026-09-03 (recommender rc.27, vocal-term calibration, config B):
        # median vocal_hnr/vocal_fmr from training-big-room-01's OWN corpus
        # ONLY (both seeds, ~14.9k heartbeats) -- see expected_bands below
        # for why this profile is no longer pooled with training-techno-01.
        # Supersedes the first-landed value (0.4748/0.3133, pooled with
        # techno) the same night, before that config ever shipped.
        vocal_hnr_mu=0.4573,
        vocal_fmr_mu=0.3097,
        vocal_hnr_sigma=0.0847,
        vocal_fmr_sigma=0.0357,
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
        expected_bands=[
            0.810, 0.810, 0.810, 0.810, 0.810, 0.810, 0.810, 0.810,
            0.749, 0.668, 0.668, 0.668, 0.668, 0.606, 0.484, 0.484,
            0.484, 0.411, 0.342, 0.307, 0.262, 0.247, 0.240, 0.242,
            0.242, 0.241, 0.227, 0.206, 0.179, 0.175, 0.171, 0.172,
            0.143, 0.137, 0.141, 0.118, 0.106, 0.095, 0.107, 0.102,
            0.084, 0.070, 0.073, 0.069, 0.069, 0.061, 0.054, 0.054,
            0.052, 0.046, 0.045, 0.042, 0.038, 0.034, 0.030, 0.029,
            0.026, 0.024, 0.024, 0.021, 0.018, 0.014, 0.010, 0.006,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.121, 0.121, 0.121, 0.121, 0.121, 0.121, 0.121, 0.121,
            0.112, 0.100, 0.100, 0.100, 0.100, 0.091, 0.113, 0.113,
            0.113, 0.062, 0.077, 0.053, 0.039, 0.059, 0.086, 0.043,
            0.036, 0.039, 0.045, 0.047, 0.034, 0.034, 0.095, 0.051,
            0.060, 0.088, 0.050, 0.040, 0.040, 0.067, 0.052, 0.029,
            0.022, 0.037, 0.015, 0.021, 0.019, 0.011, 0.014, 0.018,
            0.008, 0.007, 0.012, 0.018, 0.023, 0.017, 0.018, 0.020,
            0.018, 0.014, 0.009, 0.007, 0.006, 0.005, 0.003, 0.005,
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
        bpm_prior_mu=134.5,
        bpm_prior_sigma=0.0593,
        bpm_hint_min=134.0,
        bpm_hint_max=142.0,
        spectral_centroid_mu=450.0,
        spectral_centroid_sigma=400.0,
        zcr_mu=0.0627,
        zcr_sigma=0.03,
        onset_density_mu=3.32,
        onset_density_sigma=0.3855,
        # 2026-09-03 (recommender rc.27, vocal-term calibration): median
        # vocal_hnr/vocal_fmr from training-trance-01's own corpus.
        # Replaces the generic 0.35/0.25 default -- see house's own field
        # comment for the full methodology pointer.
        vocal_hnr_mu=0.3711,
        vocal_fmr_mu=0.2882,
        vocal_hnr_sigma=0.1156,
        vocal_fmr_sigma=0.0378,
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
        expected_bands=[
            0.798, 0.798, 0.798, 0.798, 0.798, 0.798, 0.798, 0.798,
            0.770, 0.748, 0.748, 0.748, 0.748, 0.634, 0.488, 0.488,
            0.488, 0.417, 0.368, 0.346, 0.327, 0.312, 0.298, 0.258,
            0.242, 0.244, 0.227, 0.258, 0.215, 0.192, 0.204, 0.197,
            0.178, 0.165, 0.162, 0.140, 0.148, 0.121, 0.114, 0.103,
            0.107, 0.089, 0.079, 0.077, 0.067, 0.072, 0.063, 0.064,
            0.061, 0.059, 0.054, 0.047, 0.044, 0.040, 0.035, 0.033,
            0.036, 0.031, 0.028, 0.025, 0.019, 0.014, 0.010, 0.006,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.120, 0.120, 0.120, 0.120, 0.120, 0.120, 0.120, 0.120,
            0.116, 0.150, 0.150, 0.150, 0.150, 0.121, 0.122, 0.122,
            0.122, 0.062, 0.070, 0.103, 0.070, 0.058, 0.070, 0.039,
            0.046, 0.077, 0.066, 0.087, 0.072, 0.055, 0.060, 0.042,
            0.043, 0.051, 0.037, 0.027, 0.034, 0.029, 0.038, 0.036,
            0.041, 0.038, 0.024, 0.025, 0.021, 0.029, 0.023, 0.023,
            0.016, 0.015, 0.019, 0.011, 0.010, 0.018, 0.020, 0.024,
            0.017, 0.014, 0.012, 0.011, 0.012, 0.009, 0.006, 0.004,
        ],
    ),
    "psytrance": AudioProfile(
        name="Psytrance",
        description="Relentless rolling kick, psychedelic mids, and hyper-detailed tops",
        # 2026-09-04 (recommender rc.29, evidence audit): disabled, not
        # deleted -- zero training-list corpus of any kind exists for this
        # profile, so every scoring field below (fingerprint, vocal, tempo)
        # is still 100% hand-authored/guessed with no real-data check.
        # Owner standing rule: a profile with no real evidence for ANY
        # scoring field stays out of discovery until it has some -- see
        # docs/adr/vj-system.md. Re-enable once a training-psytrance-01 (or
        # equivalent) list is packaged and this profile is re-derived the
        # same way house/techno/etc. were.
        enabled=False,
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
        bpm_prior_mu=145.0,
        bpm_prior_sigma=0.0532,
        bpm_hint_min=140.0,
        bpm_hint_max=149.0,
        spectral_centroid_mu=2150.0,
        spectral_centroid_sigma=250.0,
        zcr_mu=0.090,
        zcr_sigma=0.015,
        onset_density_mu=4.0,
        onset_density_sigma=0.7,
        vocal_hnr_mu=0.35,
        vocal_fmr_mu=0.25,
        expected_bands=[
            0.850, 0.850, 0.850, 0.820, 0.820, 0.820, 0.820, 0.880,
            0.920, 0.960, 0.850, 0.780, 0.700, 0.780, 0.850, 0.900,
            0.950, 0.950, 0.950, 0.850, 0.750, 0.650, 0.750, 0.850,
            0.950, 1.000, 0.950, 0.950, 0.900, 0.950, 0.900, 0.800,
            0.700, 0.720, 0.740, 0.760, 0.780, 0.800, 0.820, 0.720,
            0.650, 0.750, 0.850, 0.950, 1.000, 0.920, 0.850, 0.940,
            0.920, 0.900, 0.850, 0.800, 0.750, 0.700, 0.750, 0.800,
            0.850, 0.900, 0.800, 0.700, 0.600, 0.500, 0.400, 0.300,
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
        # Same band as house -- tempo is not the discriminator, vocal
        # presence is. See house's own field comment for the sigma-
        # tightening/unclamping rationale; kept identical to house on
        # purpose, including the 2026-09-04 evidence-based sigma update.
        # See docs/adr/vj-system.md.
        bpm_prior_mu=122.0,
        bpm_prior_sigma=0.0297,
        bpm_hint_min=118.0,
        bpm_hint_max=126.0,
        spectral_centroid_mu=450.0,
        spectral_centroid_sigma=600.0,
        zcr_mu=0.060,
        zcr_sigma=0.028,
        onset_density_mu=2.5,
        onset_density_sigma=0.7,
        # The actual discriminator: near-zero vocal-formant harmonic/
        # modulation presence, vs. house's 0.35/0.25.
        vocal_hnr_mu=0.05,
        vocal_fmr_mu=0.05,
        # 2026-09-04 (recommender rc.28): kept identical to house's own
        # newly ribbon-derived expected_bands/expected_bands_sigma (same
        # deliberate-copy design as every other field above -- this
        # profile has no training list of its own; see
        # tests/test_audio_profile_deep_house_and_disable.py
        # ::test_dance_matches_house_on_everything_except_vocal_presence,
        # which pins this exact invariant). See docs/adr/vj-system.md
        # "Spectral-Shape Ribbon Redesign".
        expected_bands=[
            0.808, 0.808, 0.808, 0.808, 0.808, 0.808, 0.808, 0.808,
            0.745, 0.672, 0.672, 0.672, 0.672, 0.527, 0.437, 0.437,
            0.437, 0.410, 0.375, 0.357, 0.334, 0.314, 0.292, 0.253,
            0.220, 0.213, 0.198, 0.176, 0.169, 0.147, 0.152, 0.145,
            0.145, 0.122, 0.107, 0.108, 0.095, 0.093, 0.083, 0.086,
            0.082, 0.070, 0.065, 0.072, 0.064, 0.053, 0.060, 0.054,
            0.046, 0.050, 0.053, 0.049, 0.047, 0.044, 0.043, 0.037,
            0.036, 0.035, 0.029, 0.022, 0.021, 0.013, 0.011, 0.006,
        ],
        expected_bands_sigma=[
            0.121, 0.121, 0.121, 0.121, 0.121, 0.121, 0.121, 0.121,
            0.112, 0.117, 0.117, 0.117, 0.117, 0.079, 0.075, 0.075,
            0.075, 0.061, 0.090, 0.077, 0.064, 0.061, 0.053, 0.077,
            0.090, 0.095, 0.060, 0.054, 0.056, 0.059, 0.070, 0.061,
            0.034, 0.018, 0.027, 0.039, 0.030, 0.054, 0.039, 0.035,
            0.049, 0.034, 0.043, 0.043, 0.042, 0.040, 0.042, 0.038,
            0.029, 0.034, 0.034, 0.030, 0.029, 0.027, 0.025, 0.023,
            0.031, 0.019, 0.022, 0.016, 0.015, 0.009, 0.008, 0.005,
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
    "techno": AudioProfile(
        name="Techno",
        enabled=False,
        description="Driving, hypnotic 4/4 kick with minimal/industrial texture at 128-142 BPM -- the mid-tempo techno pocket below hard_techno's punishing fast end",
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
        bpm_prior_mu=136.4,
        bpm_prior_sigma=0.1260,
        bpm_hint_min=128.0,
        bpm_hint_max=142.0,
        spectral_centroid_mu=350.0,
        spectral_centroid_sigma=250.0,
        zcr_mu=0.0406,
        zcr_sigma=0.03,
        onset_density_mu=3.065,
        onset_density_sigma=0.9266,
        # 2026-09-03 (recommender rc.27, vocal-term calibration): median
        # vocal_hnr/vocal_fmr from training-techno-01's own corpus (both
        # seeds, ~15.6k heartbeats) -- same methodology as every other
        # data-derived profile, NOT copied from hard_techno (which still
        # carries the generic 0.35/0.25 default, unvalidated).
        vocal_hnr_mu=0.4783,
        vocal_fmr_mu=0.3051,
        vocal_hnr_sigma=0.0601,
        vocal_fmr_sigma=0.0315,
        # 2026-09-04 (recommender rc.29, per-track median-of-medians re-fit,
        # n=14 tracks): mu shifted 0.4842->0.4783 / 0.3021->0.3051 and adds
        # a real fitted sigma in place of the flat 0.20/0.15 constant.
        # 2026-09-03 (recommender rc.27, data-derived fingerprints): mean
        # `bands` over training-techno-01's own corpus (both seeds, ~15.6k
        # heartbeats). See docs/adr/vj-system.md.
        expected_bands=[
            0.858, 0.858, 0.858, 0.858, 0.858, 0.858, 0.858, 0.858,
            0.786, 0.705, 0.705, 0.705, 0.705, 0.565, 0.437, 0.437,
            0.437, 0.380, 0.324, 0.345, 0.288, 0.259, 0.229, 0.219,
            0.195, 0.209, 0.202, 0.183, 0.181, 0.164, 0.145, 0.140,
            0.148, 0.136, 0.118, 0.112, 0.111, 0.090, 0.084, 0.072,
            0.075, 0.063, 0.065, 0.051, 0.050, 0.043, 0.044, 0.042,
            0.033, 0.039, 0.036, 0.029, 0.031, 0.030, 0.028, 0.027,
            0.021, 0.019, 0.017, 0.014, 0.011, 0.009, 0.007, 0.005,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.129, 0.129, 0.129, 0.129, 0.129, 0.129, 0.129, 0.129,
            0.118, 0.106, 0.106, 0.106, 0.106, 0.085, 0.094, 0.094,
            0.094, 0.103, 0.124, 0.116, 0.118, 0.100, 0.075, 0.067,
            0.056, 0.062, 0.035, 0.038, 0.031, 0.035, 0.035, 0.054,
            0.057, 0.055, 0.022, 0.038, 0.030, 0.034, 0.023, 0.032,
            0.029, 0.025, 0.031, 0.017, 0.016, 0.020, 0.022, 0.023,
            0.020, 0.026, 0.018, 0.015, 0.016, 0.015, 0.014, 0.012,
            0.011, 0.009, 0.009, 0.007, 0.007, 0.005, 0.004, 0.003,
        ],
    ),
    "hard_techno": AudioProfile(
        name="Hard Techno",
        description="Punishing kick, clipped industrial mids, and high-BPM insistence",
        # 2026-09-04 (recommender rc.29, evidence audit): disabled, not
        # deleted -- same reasoning as psytrance's own comment above: zero
        # training-list corpus, every scoring field still hand-authored/
        # guessed. See docs/adr/vj-system.md.
        enabled=False,
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
        bpm_prior_mu=148.0,
        bpm_prior_sigma=0.0627,
        bpm_hint_min=142.0,
        bpm_hint_max=154.0,
        spectral_centroid_mu=2450.0,
        spectral_centroid_sigma=250.0,
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
        # 2026-09-04 (recommender rc.29, evidence audit): disabled, not
        # deleted -- same reasoning as psytrance's own comment above: zero
        # training-list corpus, every scoring field still hand-authored/
        # guessed. See docs/adr/vj-system.md.
        enabled=False,
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
        # Hardstyle: distorted/reverse-bass kick + screech leads at 155-165 BPM.
        # Mid emphasis raised for onset detection since the screech-lead
        # transients carry as much rhythmic information as the kick itself.
        onset_bass_emphasis=1.50,
        onset_mid_emphasis=1.40,
        onset_treble_emphasis=1.00,
        # 2026-08-14: owner raised bpm_hint_min 145 -> 155 (dialed-in
        # expectation). mu moved to 160 (midpoint of the new 155-165 band --
        # it can't stay at 150, which would sit outside its own hint range).
        # sigma-matches-hint-band pass (see house's own field comment) --
        # derived value 0.0481, unclamped the same night.
        bpm_prior_mu=160.0,
        bpm_prior_sigma=0.0481,
        bpm_hint_min=155.0,
        bpm_hint_max=165.0,
        spectral_centroid_mu=1550.0,
        spectral_centroid_sigma=250.0,
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
        # median/spread on training-drum-and-bass-01 (16 tracks). Sits at
        # the low edge of the still-owner-dialed 165-180 hint band, not
        # touched here.
        bpm_prior_mu=166.7,
        bpm_prior_sigma=0.1260,
        bpm_hint_min=165.0,
        bpm_hint_max=180.0,
        spectral_centroid_mu=450.0,
        spectral_centroid_sigma=250.0,
        zcr_mu=0.0609,
        zcr_sigma=0.03,
        onset_density_mu=3.41,
        onset_density_sigma=0.3262,
        # 2026-09-03 (recommender rc.27, vocal-term calibration): median
        # vocal_hnr/vocal_fmr from training-drum-and-bass-01's own corpus.
        # Replaces the generic 0.35/0.25 default -- see house's own field
        # comment for the full methodology pointer.
        vocal_hnr_mu=0.4485,
        vocal_fmr_mu=0.3468,
        vocal_hnr_sigma=0.0840,
        vocal_fmr_sigma=0.0306,
        # 2026-09-04 (recommender rc.29, per-track median-of-medians re-fit,
        # n=16 tracks): mu shifted 0.4260->0.4485 / 0.3510->0.3468 and adds
        # a real fitted sigma in place of the flat 0.20/0.15 constant.
        # 2026-09-03 (recommender rc.27, data-derived fingerprints): mean
        # `bands` over training-drum-and-bass-01's own corpus (both seeds,
        # ~8.3k heartbeats). See docs/adr/vj-system.md.
        expected_bands=[
            0.789, 0.789, 0.789, 0.789, 0.789, 0.789, 0.789, 0.789,
            0.727, 0.696, 0.696, 0.696, 0.696, 0.577, 0.458, 0.458,
            0.458, 0.439, 0.395, 0.386, 0.379, 0.347, 0.316, 0.280,
            0.286, 0.260, 0.241, 0.240, 0.234, 0.208, 0.174, 0.183,
            0.171, 0.165, 0.144, 0.178, 0.148, 0.117, 0.113, 0.102,
            0.097, 0.094, 0.082, 0.083, 0.077, 0.073, 0.069, 0.065,
            0.062, 0.060, 0.053, 0.050, 0.047, 0.047, 0.043, 0.041,
            0.038, 0.037, 0.031, 0.026, 0.022, 0.015, 0.011, 0.007,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.118, 0.118, 0.118, 0.118, 0.118, 0.118, 0.118, 0.118,
            0.109, 0.124, 0.124, 0.124, 0.124, 0.136, 0.121, 0.121,
            0.121, 0.095, 0.103, 0.127, 0.151, 0.173, 0.157, 0.150,
            0.155, 0.135, 0.117, 0.143, 0.137, 0.107, 0.096, 0.088,
            0.097, 0.088, 0.093, 0.073, 0.052, 0.068, 0.049, 0.046,
            0.045, 0.050, 0.041, 0.026, 0.026, 0.027, 0.021, 0.017,
            0.015, 0.016, 0.015, 0.012, 0.012, 0.017, 0.017, 0.014,
            0.013, 0.014, 0.010, 0.006, 0.006, 0.004, 0.004, 0.004,
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
        spectral_centroid_mu=450.0,
        spectral_centroid_sigma=250.0,
        # 2026-08-31: 0.095 -> 0.093. LLM tuning recommendation from the
        # training-house-01/002 matcher-validation session ("observed ZCR
        # slightly lower than expected"), owner-approved.
        zcr_mu=0.0581,
        zcr_sigma=0.03,
        onset_density_mu=2.75,
        onset_density_sigma=0.1779,
        # 2026-09-03 (recommender rc.27, vocal-term calibration): median
        # vocal_hnr/vocal_fmr from training-dubstep-01's own corpus.
        # Replaces the generic 0.35/0.25 default -- see house's own field
        # comment for the full methodology pointer.
        vocal_hnr_mu=0.4113,
        vocal_fmr_mu=0.3271,
        vocal_hnr_sigma=0.0910,
        vocal_fmr_sigma=0.0300,
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
        expected_bands=[
            0.774, 0.774, 0.774, 0.774, 0.774, 0.774, 0.774, 0.774,
            0.670, 0.584, 0.584, 0.584, 0.584, 0.495, 0.375, 0.375,
            0.375, 0.350, 0.320, 0.295, 0.270, 0.255, 0.259, 0.262,
            0.254, 0.259, 0.247, 0.237, 0.241, 0.211, 0.189, 0.211,
            0.211, 0.167, 0.151, 0.148, 0.123, 0.107, 0.106, 0.103,
            0.094, 0.074, 0.073, 0.067, 0.065, 0.064, 0.057, 0.061,
            0.054, 0.051, 0.049, 0.042, 0.037, 0.035, 0.035, 0.033,
            0.030, 0.029, 0.026, 0.022, 0.017, 0.012, 0.009, 0.006,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.198, 0.198, 0.198, 0.198, 0.198, 0.198, 0.198, 0.198,
            0.101, 0.088, 0.088, 0.088, 0.088, 0.074, 0.125, 0.125,
            0.125, 0.143, 0.145, 0.123, 0.097, 0.138, 0.139, 0.109,
            0.085, 0.114, 0.095, 0.089, 0.103, 0.110, 0.149, 0.114,
            0.091, 0.096, 0.095, 0.044, 0.041, 0.063, 0.054, 0.066,
            0.039, 0.039, 0.034, 0.022, 0.030, 0.026, 0.027, 0.023,
            0.028, 0.016, 0.014, 0.014, 0.012, 0.012, 0.013, 0.011,
            0.011, 0.006, 0.005, 0.007, 0.008, 0.007, 0.007, 0.004,
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
    "rap_rnb": AudioProfile(
        name="Rap / R&B",
        description="Heavy sub-bass with sustained, vocal-forward mids at 70-100 BPM -- merged hip-hop/R&B sibling profile",
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
        spectral_centroid_mu=450.0,
        spectral_centroid_sigma=400.0,
        zcr_mu=0.0563,
        zcr_sigma=0.03,
        onset_density_mu=2.81,
        onset_density_sigma=0.3706,
        # 2026-09-04 (recommender rc.28): trap-hip-hop-01 split OUT of this
        # pool into its own re-enabled 'hyphy' profile -- owner: "trap
        # should def be on its own." hip-hop-01 + rnb-01 stay pooled
        # (owner: "rnb/hh i'll let u decide based on evidence") -- a
        # per-list confusion check found hip-hop-01 and rnb-01 the least
        # separable pair of the three by spectral shape, consistent with
        # the original 2026-08-06 "genuine siblings" merge finding, while
        # trap-hip-hop-01 discriminates clearly from both. Values below
        # (both vocal medians and expected_bands/_sigma) are now measured
        # against training-hip-hop-01 + training-rnb-01 ONLY (~20k
        # heartbeats) -- see hyphy's own field comment for its half of
        # the split and the confusion-matrix evidence.
        vocal_hnr_mu=0.5118,
        vocal_fmr_mu=0.3642,
        vocal_hnr_sigma=0.0901,
        vocal_fmr_sigma=0.0300,
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
            0.731, 0.731, 0.731, 0.731, 0.731, 0.731, 0.731, 0.731,
            0.629, 0.495, 0.495, 0.495, 0.495, 0.417, 0.315, 0.315,
            0.315, 0.324, 0.322, 0.336, 0.325, 0.268, 0.259, 0.244,
            0.237, 0.248, 0.304, 0.303, 0.300, 0.242, 0.214, 0.217,
            0.180, 0.171, 0.148, 0.123, 0.119, 0.105, 0.094, 0.081,
            0.079, 0.075, 0.071, 0.064, 0.060, 0.059, 0.048, 0.043,
            0.044, 0.045, 0.035, 0.034, 0.036, 0.029, 0.031, 0.028,
            0.027, 0.027, 0.022, 0.018, 0.014, 0.011, 0.007, 0.004,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.155, 0.155, 0.155, 0.155, 0.155, 0.155, 0.155, 0.155,
            0.110, 0.130, 0.130, 0.130, 0.130, 0.063, 0.065, 0.065,
            0.065, 0.100, 0.127, 0.142, 0.122, 0.085, 0.109, 0.107,
            0.111, 0.125, 0.115, 0.100, 0.089, 0.090, 0.090, 0.088,
            0.058, 0.034, 0.047, 0.039, 0.042, 0.047, 0.050, 0.042,
            0.038, 0.031, 0.030, 0.027, 0.029, 0.024, 0.028, 0.027,
            0.024, 0.024, 0.024, 0.027, 0.022, 0.022, 0.017, 0.018,
            0.016, 0.017, 0.014, 0.012, 0.009, 0.008, 0.005, 0.002,
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
        name="Hyphy / Trap",
        # 2026-09-04: RE-ENABLED. Owner: "trap should def be on its own" --
        # was disabled 2026-08-10 specifically for lack of real trap/hyphy
        # material to validate against; training-trap-hip-hop-01 now
        # supplies that. Evidence-based split from rap_rnb (which pooled
        # hip-hop-01 + trap-hip-hop-01 + rnb-01 until tonight): a per-list
        # confusion check (own tracks scored against each of the three
        # lists' own ribbons, spectral_shape_fit only) showed trap-hip-
        # hop-01 and rnb-01 each discriminate real distinctly from the
        # other two, while hip-hop-01 and rnb-01 are the closest, least-
        # separable pair of the three -- so trap splits out to its own
        # profile (this one) and rap_rnb keeps hip-hop + rnb pooled (see
        # rap_rnb's own field comment). Every field below except bpm_prior_
        # mu/sigma/hint, expected_bands/_sigma, and vocal_hnr_mu/vocal_fmr_
        # mu is unchanged from the pre-disable values -- not re-derived,
        # since only the fingerprint/tempo/vocal axes had real data to
        # recalibrate against.
        enabled=True,
        description="Aggressive sub-bass, sustained hype-vocal chops, bright treble at 127-155 BPM",
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
        # 2026-09-04: fully recalibrated from training-trap-hip-hop-01's
        # own real detected-bpm distribution (median 141.2, p25/p75 127.2/
        # 154.5) -- the old 100-118 hand-guess (never validated against
        # real material) was far off; trap's PRODUCED tempo reads much
        # higher, same "produced vs perceived pulse" pattern already
        # documented for dubstep. Hint band = p25/p75 rounded; mu = the
        # band's arithmetic midpoint; sigma via the sigma-matches-hint-band
        # formula used throughout this file (log2(hint_max/hint_min)/2).
        # 2026-09-04, later the same night (recommender rc.28, evidence-
        # based sigma pass): re-checked with the per-track median/MAD
        # methodology (21 tracks) -- mu 141.0 -> 142.2 (0.8% shift,
        # trivial, well within noise) and sigma 0.1436 -> 0.1334 (real
        # measured spread, close to the hint-band-derived placeholder it
        # replaces). Small delta applied directly; NOT given the same
        # full hold-back as dubstep/rap_rnb despite this profile's own
        # comment above flagging the same "produced vs perceived pulse"
        # risk pattern, because the per-track approach already landed
        # close to the original value (unlike rap_rnb's 64% jump, which
        # is the actual signature of real contamination) -- but flagging
        # this explicitly rather than treating the closeness as proof of
        # cleanliness: this profile has not been checked track-by-track
        # for individual half-time-fold outliers the way dubstep's design
        # already accounts for structurally.
        bpm_prior_mu=142.2,
        bpm_prior_sigma=0.1334,
        bpm_hint_min=127.0,
        bpm_hint_max=155.0,
        spectral_centroid_mu=300.0,
        # 2026-08-10: 600.0 (wide tier) -> 400.0 (medium, the dataclass
        # default tier) -- wide was never re-justified for hyphy the way it
        # was for house's genuinely diverse library content; with zero
        # validated hyphy examples, "wide" just meant "forgiving," letting
        # it act as a low-resistance catch-all on the centroid axis.
        spectral_centroid_sigma=400.0,
        zcr_mu=0.0376,
        zcr_sigma=0.03,
        onset_density_mu=2.88,
        onset_density_sigma=0.2669,
        # 2026-09-04 (recommender rc.28, vocal-term + ribbon recalibration):
        # median vocal_hnr/vocal_fmr from training-trap-hip-hop-01's own
        # corpus (21 tracks) -- replaces the old unvalidated 0.55/0.5 guess.
        vocal_hnr_mu=0.5390,
        vocal_fmr_mu=0.3622,
        vocal_hnr_sigma=0.0968,
        vocal_fmr_sigma=0.0300,
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
            0.774, 0.774, 0.774, 0.774, 0.774, 0.774, 0.774, 0.774,
            0.679, 0.598, 0.598, 0.598, 0.598, 0.497, 0.413, 0.413,
            0.413, 0.372, 0.303, 0.304, 0.278, 0.256, 0.245, 0.224,
            0.215, 0.225, 0.236, 0.226, 0.194, 0.190, 0.176, 0.140,
            0.123, 0.115, 0.098, 0.083, 0.074, 0.078, 0.062, 0.065,
            0.053, 0.045, 0.045, 0.042, 0.050, 0.040, 0.029, 0.028,
            0.031, 0.025, 0.024, 0.019, 0.020, 0.020, 0.022, 0.024,
            0.021, 0.019, 0.012, 0.010, 0.009, 0.006, 0.003, 0.002,
        ],
        expected_bands_sigma=[
            0.175, 0.175, 0.175, 0.175, 0.175, 0.175, 0.175, 0.175,
            0.111, 0.138, 0.138, 0.138, 0.138, 0.108, 0.142, 0.142,
            0.142, 0.142, 0.130, 0.088, 0.113, 0.127, 0.152, 0.125,
            0.117, 0.129, 0.117, 0.099, 0.090, 0.094, 0.072, 0.059,
            0.045, 0.058, 0.040, 0.032, 0.024, 0.029, 0.016, 0.030,
            0.025, 0.020, 0.018, 0.018, 0.017, 0.020, 0.018, 0.017,
            0.017, 0.017, 0.012, 0.011, 0.008, 0.009, 0.010, 0.012,
            0.015, 0.016, 0.006, 0.006, 0.007, 0.004, 0.002, 0.002,
        ],
    ),
    "ambient": AudioProfile(
        name="Ambient / Chillout",
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
        # authored 84-116 hint band actually implies; this tightens ambient
        # to match that band while remaining the widest-or-near-widest
        # sigma in the roster, consistent with "often weak or no beats"
        # above.
        bpm_prior_mu=100.0,
        bpm_prior_sigma=0.26,
        bpm_hint_min=84.0,
        bpm_hint_max=116.0,
        spectral_centroid_mu=350.0,
        spectral_centroid_sigma=600.0,
        zcr_mu=0.0381,
        zcr_sigma=0.03,
        onset_density_mu=2.66,
        onset_density_sigma=0.4151,
        # 2026-09-03 (recommender rc.27, vocal-term calibration): this
        # profile had no vocal_hnr_mu/vocal_fmr_mu at all (None on both --
        # see house's own field comment for why None is not a neutral
        # choice: it gives a "free pass" on both terms, which was the root
        # cause of a similar confound found on deep_house). Values below
        # are median vocal_hnr/vocal_fmr from training-ambient-01's own
        # corpus (both seeds). See docs/adr/vj-system.md "Data-Derived
        # expected_bands" vocal-calibration addendum.
        vocal_hnr_mu=0.5520,
        vocal_fmr_mu=0.3223,
        vocal_hnr_sigma=0.1066,
        vocal_fmr_sigma=0.0300,
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
        expected_bands=[
            0.520, 0.520, 0.520, 0.520, 0.520, 0.520, 0.520, 0.520,
            0.572, 0.507, 0.507, 0.507, 0.507, 0.480, 0.443, 0.443,
            0.443, 0.421, 0.436, 0.427, 0.435, 0.434, 0.419, 0.398,
            0.384, 0.377, 0.373, 0.326, 0.315, 0.299, 0.252, 0.221,
            0.226, 0.185, 0.151, 0.138, 0.119, 0.104, 0.087, 0.070,
            0.077, 0.059, 0.065, 0.057, 0.048, 0.041, 0.035, 0.035,
            0.027, 0.025, 0.024, 0.018, 0.019, 0.017, 0.015, 0.011,
            0.009, 0.009, 0.008, 0.006, 0.005, 0.004, 0.003, 0.002,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.245, 0.245, 0.245, 0.245, 0.245, 0.245, 0.245, 0.245,
            0.194, 0.140, 0.140, 0.140, 0.140, 0.156, 0.199, 0.199,
            0.199, 0.159, 0.124, 0.109, 0.086, 0.098, 0.127, 0.133,
            0.159, 0.165, 0.106, 0.117, 0.149, 0.148, 0.128, 0.129,
            0.079, 0.098, 0.062, 0.042, 0.044, 0.046, 0.051, 0.042,
            0.038, 0.027, 0.035, 0.026, 0.027, 0.024, 0.021, 0.027,
            0.021, 0.013, 0.012, 0.010, 0.013, 0.009, 0.012, 0.009,
            0.009, 0.008, 0.008, 0.007, 0.006, 0.004, 0.003, 0.002,
        ],
    ),
    "chillstep": AudioProfile(
        name="Chillstep / Downtempo",
        description=(
            "Slow electronic groove: sub-bass kick, atmospheric pads, "
            "and soft hi-hats at 75-110 BPM"
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
        # house's own field comment) -- ties sigma to the actual 78-112
        # hint band above rather than the wider historical value.
        bpm_prior_mu=95.0,
        bpm_prior_sigma=0.30,
        bpm_hint_min=78.0,
        bpm_hint_max=112.0,
        spectral_centroid_mu=250.0,
        spectral_centroid_sigma=600.0,
        zcr_mu=0.0297,
        zcr_sigma=0.03,
        onset_density_mu=2.94,
        onset_density_sigma=0.4151,
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
            0.757, 0.757, 0.757, 0.757, 0.757, 0.757, 0.757, 0.757,
            0.692, 0.646, 0.646, 0.646, 0.646, 0.539, 0.434, 0.434,
            0.434, 0.396, 0.385, 0.361, 0.344, 0.315, 0.273, 0.277,
            0.276, 0.276, 0.255, 0.208, 0.187, 0.158, 0.164, 0.153,
            0.144, 0.136, 0.096, 0.094, 0.080, 0.073, 0.061, 0.055,
            0.050, 0.045, 0.043, 0.032, 0.030, 0.028, 0.024, 0.021,
            0.021, 0.018, 0.016, 0.013, 0.014, 0.012, 0.011, 0.011,
            0.011, 0.010, 0.007, 0.005, 0.004, 0.002, 0.002, 0.001,
        ],
        # 2026-09-04 (recommender rc.28, "ribbon" redesign): MAD-
        # derived per-band spread across per-track means, floored at
        # 15% of that band's own median -- see expected_bands' own
        # field comment for the full methodology.
        expected_bands_sigma=[
            0.147, 0.147, 0.147, 0.147, 0.147, 0.147, 0.147, 0.147,
            0.104, 0.107, 0.107, 0.107, 0.107, 0.081, 0.091, 0.091,
            0.091, 0.096, 0.131, 0.173, 0.211, 0.183, 0.150, 0.178,
            0.194, 0.175, 0.169, 0.108, 0.095, 0.088, 0.083, 0.079,
            0.030, 0.062, 0.048, 0.057, 0.036, 0.032, 0.051, 0.022,
            0.022, 0.017, 0.020, 0.018, 0.015, 0.021, 0.014, 0.013,
            0.014, 0.007, 0.010, 0.010, 0.009, 0.009, 0.011, 0.010,
            0.011, 0.011, 0.008, 0.007, 0.005, 0.003, 0.003, 0.002,
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
    "synthwave": AudioProfile(
        name="Synthwave / Retrowave",
        description=(
            "Retro 80s-style synth-driven electronic: warm analog bass, "
            "gated-reverb drums, and bright melodic lead synths at 85-118 BPM"
        ),
        # 2026-09-04 (recommender rc.29, evidence audit): disabled, not
        # deleted -- same reasoning as psytrance's own comment above: zero
        # training-list corpus, every scoring field still hand-authored/
        # guessed. See docs/adr/vj-system.md.
        enabled=False,
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
        # tempo scatter rather than a tightly-quantized genre like tech_house.
        # 2026-08-14: 0.34 -> 0.25, sigma-matches-hint-band pass (see
        # house's own field comment) -- ties sigma to the actual 85-118
        # hint band above.
        bpm_prior_mu=100.0,
        bpm_prior_sigma=0.25,
        bpm_hint_min=85.0,
        bpm_hint_max=118.0,
        # Brightness sits between chillstep's pad-only atmosphere (900 Hz)
        # and house's percussion-driven brightness (1500 Hz) -- present lead
        # synths without a hi-hat-driven treble floor.
        spectral_centroid_mu=1700.0,
        spectral_centroid_sigma=400.0,
        zcr_mu=0.050,
        zcr_sigma=0.020,
        onset_density_mu=1.9,
        onset_density_sigma=1.0,
        # vocal_hnr_mu/vocal_fmr_mu intentionally left uncalibrated: classic
        # synthwave (Kavinsky et al.) is predominantly instrumental, and a
        # fabricated target would be worse than no signal on this dimension.
        # Fingerprint: smooth single peak at bands 39-40 (~1.4-1.6 kHz, the
        # lead-synth register), tapering into a rolled-off extreme-high tail
        # -- distinguishes it from trance/psytrance's near-constant high-
        # frequency energy and from house's jagged percussion-transient shape.
        expected_bands=[
            0.350, 0.370, 0.400, 0.420, 0.450, 0.470, 0.500, 0.520,
            0.550, 0.580, 0.600, 0.620, 0.650, 0.670, 0.660, 0.640,
            0.630, 0.620, 0.600, 0.590, 0.600, 0.620, 0.640, 0.630,
            0.620, 0.640, 0.660, 0.680, 0.700, 0.720, 0.750, 0.780,
            0.820, 0.850, 0.880, 0.900, 0.930, 0.950, 0.970, 1.000,
            0.980, 0.970, 0.950, 0.930, 0.900, 0.850, 0.800, 0.750,
            0.680, 0.620, 0.550, 0.500, 0.450, 0.420, 0.380, 0.350,
            0.320, 0.280, 0.250, 0.220, 0.200, 0.180, 0.160, 0.150,
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
