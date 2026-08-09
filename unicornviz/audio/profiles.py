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
    # spectral_centroid_mu: frequency-weighted mean of spectrum (Hz) — "brightness"
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
    vocal_hnr_mu: float | None = None
    vocal_fmr_mu: float | None = None

    # 64-element normalized (0.0–1.0) spectral fingerprint: expected relative
    # magnitude per log-spaced band (30 Hz – 16 kHz, matching audio_spectrum.py).
    # Cosine similarity between the observed window-mean vector and this fingerprint
    # yields spectral_shape_fit used by the recommender. None = not yet calibrated.
    expected_bands: list[float] | None = None

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
        bpm_prior_mu=124.0,
        # 2026-06-20: house BPM spans 120-128; sigma=0.20 was too peaked and
        # depressed confidence on tracks at the edges of the range.  Widened
        # to 0.35 to flatten the prior across the full 8-BPM span.
        bpm_prior_sigma=0.35,
        bpm_hint_min=120.0,
        bpm_hint_max=128.0,
        spectral_centroid_mu=1500.0,
        spectral_centroid_sigma=600.0,
        zcr_mu=0.060,
        zcr_sigma=0.028,
        onset_density_mu=2.5,
        onset_density_sigma=0.7,
        vocal_hnr_mu=0.35,
        vocal_fmr_mu=0.25,
        expected_bands=[
            0.950, 0.900, 0.850, 0.800, 0.750, 0.700, 0.650, 0.700,
            0.750, 0.800, 0.900, 0.850, 0.650, 0.600, 0.550, 0.500,
            0.450, 0.400, 0.350, 0.300, 0.250, 0.200, 0.150, 0.200,
            0.250, 0.300, 0.350, 0.400, 0.450, 0.500, 0.550, 0.600,
            0.650, 0.700, 0.750, 0.800, 0.850, 0.900, 0.950, 0.800,
            0.850, 0.900, 1.000, 0.950, 0.900, 0.850, 0.800, 0.850,
            0.900, 0.950, 0.700, 0.750, 0.800, 0.850, 0.900, 0.950,
            0.800, 0.750, 0.700, 0.650, 0.600, 0.550, 0.500, 0.450,
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
            "filtered hats at 118-124 BPM -- slower and mellower than house"
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
        # Deep house sits clearly below house's 120-128 pocket -- centered
        # lower and narrower, reflecting a more tempo-consistent genre.
        bpm_prior_mu=121.0,
        bpm_prior_sigma=0.30,
        bpm_hint_min=118.0,
        bpm_hint_max=124.0,
        # Warmer/less bright than house (1500 Hz) -- the chord stabs and
        # rolled-off hats keep energy lower in the spectrum.
        spectral_centroid_mu=1150.0,
        spectral_centroid_sigma=400.0,
        zcr_mu=0.048,
        zcr_sigma=0.020,
        onset_density_mu=2.0,
        onset_density_sigma=0.7,
        # vocal_hnr_mu/vocal_fmr_mu intentionally left uncalibrated: soulful
        # vocal chops are common but not as reliably continuous as
        # rap/hyphy/r&b's genuinely vocal-forward material -- a fabricated
        # target would be worse than no signal here.
        expected_bands=[
            0.800, 0.830, 0.860, 0.880, 0.900, 0.870, 0.840, 0.800,
            0.780, 0.750, 0.720, 0.700, 0.680, 0.650,
            0.620, 0.600, 0.580, 0.600, 0.630,
            0.680, 0.720, 0.760, 0.800, 0.830, 0.860, 0.880, 0.850,
            0.800, 0.750, 0.700, 0.660, 0.620, 0.600, 0.580, 0.560,
            0.550, 0.540, 0.530, 0.520, 0.530, 0.550, 0.580,
            0.620, 0.650, 0.620, 0.580, 0.540, 0.500, 0.460, 0.420,
            0.380, 0.340, 0.300, 0.270, 0.240, 0.220, 0.200, 0.180,
            0.160, 0.150, 0.140, 0.130, 0.120, 0.120,
        ],
    ),
    "tech_house": AudioProfile(
        name="Tech House",
        description="Punchy low-end, clipped claps, tight hats, and steady 4/4 pressure",
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
        bpm_prior_mu=126.0,
        bpm_prior_sigma=0.16,
        bpm_hint_min=122.0,
        bpm_hint_max=130.0,
        spectral_centroid_mu=1700.0,
        spectral_centroid_sigma=250.0,
        zcr_mu=0.065,
        zcr_sigma=0.015,
        onset_density_mu=2.8,
        onset_density_sigma=0.7,
        vocal_hnr_mu=0.35,
        vocal_fmr_mu=0.25,
        expected_bands=[
            0.900, 0.850, 0.800, 0.750, 0.700, 0.650, 0.600, 0.750,
            0.800, 0.850, 0.750, 0.800, 0.850, 0.700, 0.750, 0.800,
            0.650, 0.700, 0.750, 0.600, 0.650, 0.700, 0.750, 0.800,
            0.850, 0.750, 0.800, 0.850, 0.900, 0.800, 0.750, 0.700,
            0.750, 0.800, 0.850, 0.750, 0.800, 0.850, 0.900, 0.800,
            0.850, 0.900, 1.000, 0.950, 0.900, 0.850, 0.800, 0.850,
            0.900, 0.950, 0.750, 0.800, 0.850, 0.900, 0.950, 0.800,
            0.850, 0.900, 1.000, 0.800, 0.750, 0.700, 0.650, 0.600,
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
        bpm_prior_mu=130.0,
        bpm_prior_sigma=0.24,
        bpm_hint_min=126.0,
        bpm_hint_max=136.0,
        spectral_centroid_mu=2000.0,
        spectral_centroid_sigma=400.0,
        zcr_mu=0.072,
        zcr_sigma=0.020,
        onset_density_mu=3.2,
        onset_density_sigma=1.0,
        vocal_hnr_mu=0.35,
        vocal_fmr_mu=0.25,
        expected_bands=[
            0.920, 0.880, 0.850, 0.800, 0.780, 0.760, 0.740, 0.920,
            0.900, 0.880, 0.940, 0.900, 0.800, 0.780, 0.760, 0.740,
            0.720, 0.700, 0.680, 0.700, 0.720, 0.740, 0.800, 0.780,
            0.760, 0.680, 0.700, 0.720, 0.740, 0.760, 0.780, 0.800,
            0.820, 0.840, 0.860, 0.880, 0.900, 0.920, 0.940, 0.960,
            0.980, 1.000, 0.980, 0.960, 0.940, 0.920, 0.900, 0.880,
            0.860, 0.720, 0.740, 0.760, 0.780, 0.800, 0.820, 0.760,
            0.740, 0.720, 0.700, 0.680, 0.660, 0.640, 0.620, 0.600,
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
        bpm_prior_mu=138.0,
        bpm_prior_sigma=0.20,
        bpm_hint_min=134.0,
        bpm_hint_max=142.0,
        spectral_centroid_mu=2200.0,
        spectral_centroid_sigma=400.0,
        zcr_mu=0.080,
        zcr_sigma=0.020,
        onset_density_mu=3.5,
        onset_density_sigma=0.7,
        vocal_hnr_mu=0.35,
        vocal_fmr_mu=0.25,
        expected_bands=[
            0.880, 0.860, 0.840, 0.820, 0.800, 0.780, 0.760, 0.820,
            0.880, 0.900, 0.850, 0.800, 0.750, 0.780, 0.800, 0.820,
            0.850, 0.880, 0.900, 0.880, 0.820, 0.800, 0.850, 0.900,
            0.920, 0.950, 0.950, 0.920, 0.900, 0.880, 0.860, 0.850,
            0.850, 0.880, 0.900, 0.920, 0.950, 0.980, 1.000, 0.980,
            0.950, 0.920, 0.900, 0.880, 0.850, 0.820, 0.800, 0.760,
            0.720, 0.680, 0.650, 0.620, 0.600, 0.580, 0.620, 0.660,
            0.700, 0.720, 0.680, 0.620, 0.550, 0.480, 0.420, 0.360,
        ],
    ),
    "psytrance": AudioProfile(
        name="Psytrance",
        description="Relentless rolling kick, psychedelic mids, and hyper-detailed tops",
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
        bpm_prior_mu=145.0,
        bpm_prior_sigma=0.16,
        bpm_hint_min=140.0,
        bpm_hint_max=149.0,
        spectral_centroid_mu=2500.0,
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
    "electronic": AudioProfile(
        name="Electronic",
        description="Balanced across all frequencies with emphasis on detail",
        # 2026-08-06: disabled (owner call, confirmed by cosine-similarity
        # audit against the whole catalog -- see docs/adr/vj-system.md
        # "Wide-Tier Catch-All Profiles Disabled..."). expected_bands is
        # >=0.95 cosine-similar to nearly every other profile, *higher* to
        # far-tempo genres (trance 0.9962, hyphy 0.9950, psytrance 0.9871)
        # than to its own close-tempo neighbors (deep_house 0.9547, house
        # 0.9403) -- a flat fingerprint that doesn't discriminate, not a
        # unique signal, layered on a bpm_hint range (118-132) already
        # fully covered by house/tech_house/deep_house/peak_time. Same
        # disable-not-delete pattern as 'generic': still resolvable
        # directly by key, just excluded from the recommender pool and
        # Alt+A cycling.
        enabled=False,
        bass_min=20.0,
        bass_max=200.0,
        mid_min=200.0,
        mid_max=3000.0,
        treble_min=3000.0,
        treble_max=20000.0,
        bass_weight=1.0,
        mid_weight=1.1,
        treble_weight=1.0,
        beat_threshold=1.2,
        smoothing=0.1,
        curve="flat",
        # Electronic: broad genre, moderate kick bias, wider prior.
        onset_bass_emphasis=1.9,
        onset_mid_emphasis=1.2,
        onset_treble_emphasis=0.9,
        bpm_prior_mu=125.0,
        bpm_prior_sigma=0.35,
        bpm_hint_min=118.0,
        bpm_hint_max=132.0,
        spectral_centroid_mu=1600.0,
        spectral_centroid_sigma=600.0,
        # 2026-07-08: lowered 0.065 -> 0.052 (confusability pass, see ADR).
        # zcr_mu was an exact duplicate of both generic's (0.065) and
        # tech_house's (0.065) values, making this profile the closest
        # competing match to both. This is the one dimension both neighbors
        # shared, so it's a single-parameter fix that separates from both
        # simultaneously without trading centroid/onset distance against
        # either.
        zcr_mu=0.052,
        zcr_sigma=0.028,
        onset_density_mu=2.5,
        onset_density_sigma=1.5,
        vocal_hnr_mu=0.35,
        vocal_fmr_mu=0.25,
        expected_bands=[
            0.820, 0.800, 0.780, 0.760, 0.740, 0.720, 0.700, 0.760,
            0.840, 0.880, 0.850, 0.820, 0.800, 0.780, 0.760, 0.740,
            0.720, 0.700, 0.700, 0.720, 0.740, 0.760, 0.780, 0.800,
            0.820, 0.840, 0.860, 0.880, 0.900, 0.880, 0.860, 0.840,
            0.820, 0.840, 0.860, 0.900, 1.000, 0.960, 0.920, 0.880,
            0.840, 0.800, 0.760, 0.720, 0.700, 0.680, 0.660, 0.640,
            0.620, 0.640, 0.660, 0.680, 0.700, 0.720, 0.740, 0.760,
            0.720, 0.680, 0.620, 0.560, 0.500, 0.440, 0.380, 0.320,
        ],
    ),
    "hardgroove": AudioProfile(
        name="Hardgroove",
        description="Rolling tribal percussion, fast low-end groove, and busy hats that want motion",
        bass_min=25.0,
        bass_max=240.0,
        mid_min=240.0,
        mid_max=4500.0,
        treble_min=4500.0,
        treble_max=20000.0,
        bass_weight=1.15,
        mid_weight=1.20,
        treble_weight=1.05,
        beat_threshold=1.05,
        smoothing=0.09,
        curve="mid_treble_boost",
        onset_bass_emphasis=1.45,
        onset_mid_emphasis=1.35,
        onset_treble_emphasis=1.10,
        bpm_prior_mu=136.0,
        bpm_prior_sigma=0.18,
        bpm_hint_min=132.0,
        bpm_hint_max=140.0,
        spectral_centroid_mu=1800.0,
        spectral_centroid_sigma=400.0,
        # 2026-07-08: raised 0.068 -> 0.086 (confusability pass, see ADR).
        # Was tied exactly with uk_garage's zcr_mu and close to breaks',
        # making this the 2nd/3rd-closest competing pair in the whole
        # roster. Raised rather than lowered: "rolling tribal percussion...
        # busy hats" (see description above) implies more noise-like/
        # percussive high-frequency content than its neighbors, not less --
        # this is the direction consistent with the genre's own character,
        # and numerically separates from both neighbors at once.
        zcr_mu=0.086,
        zcr_sigma=0.020,
        onset_density_mu=3.2,
        onset_density_sigma=1.0,
        vocal_hnr_mu=0.35,
        vocal_fmr_mu=0.25,
        expected_bands=[
            0.880, 0.840, 0.800, 0.760, 0.720, 0.680, 0.650, 0.900,
            0.950, 1.000, 0.920, 0.850, 0.800, 0.920, 0.880, 0.840,
            0.880, 0.820, 0.760, 0.700, 0.880, 0.940, 0.900, 0.850,
            0.800, 0.750, 0.700, 0.650, 0.600, 0.580, 0.560, 0.540,
            0.520, 0.800, 0.850, 0.900, 0.950, 1.000, 0.900, 0.800,
            0.700, 0.600, 0.580, 0.560, 0.540, 0.520, 0.500, 0.600,
            0.700, 0.800, 0.850, 0.900, 0.750, 0.800, 0.850, 0.900,
            0.950, 0.900, 0.850, 0.800, 0.750, 0.700, 0.650, 0.600,
        ],
    ),
    "uk_garage": AudioProfile(
        name="UK Garage",
        description="Swinging kick-snare, vocal chops, and crisp tops around the 130 pocket",
        bass_min=28.0,
        bass_max=220.0,
        mid_min=220.0,
        mid_max=3600.0,
        treble_min=3600.0,
        treble_max=20000.0,
        bass_weight=1.10,
        mid_weight=1.15,
        treble_weight=1.20,
        beat_threshold=1.08,
        smoothing=0.10,
        curve="slight_presence",
        onset_bass_emphasis=1.25,
        onset_mid_emphasis=1.25,
        onset_treble_emphasis=1.15,
        bpm_prior_mu=132.0,
        bpm_prior_sigma=0.20,
        bpm_hint_min=128.0,
        bpm_hint_max=136.0,
        spectral_centroid_mu=1700.0,
        spectral_centroid_sigma=400.0,
        zcr_mu=0.068,
        zcr_sigma=0.020,
        onset_density_mu=2.8,
        onset_density_sigma=1.5,
        vocal_hnr_mu=0.35,
        vocal_fmr_mu=0.25,
        expected_bands=[
            0.780, 0.760, 0.740, 0.720, 0.700, 0.680, 0.660, 0.750,
            0.800, 0.820, 0.780, 0.740, 0.700, 0.760, 0.800, 0.820,
            0.840, 0.860, 0.880, 0.900, 0.880, 0.860, 0.850, 0.880,
            0.900, 0.930, 0.960, 1.000, 0.980, 0.960, 0.930, 0.900,
            0.880, 0.850, 0.830, 0.820, 0.820, 0.800, 0.780, 0.750,
            0.720, 0.700, 0.680, 0.660, 0.650, 0.640, 0.630, 0.620,
            0.620, 0.650, 0.680, 0.720, 0.760, 0.800, 0.840, 0.880,
            0.900, 0.850, 0.780, 0.700, 0.600, 0.500, 0.420, 0.350,
        ],
    ),
    "breaks": AudioProfile(
        name="Breaks",
        description="Broken-beat energy, syncopated mids, and sharp hats with higher tempo tolerance",
        bass_min=30.0,
        bass_max=240.0,
        mid_min=240.0,
        mid_max=4200.0,
        treble_min=4200.0,
        treble_max=20000.0,
        bass_weight=1.10,
        mid_weight=1.20,
        treble_weight=1.15,
        beat_threshold=1.04,
        smoothing=0.09,
        curve="bright",
        onset_bass_emphasis=1.30,
        onset_mid_emphasis=1.35,
        onset_treble_emphasis=1.15,
        bpm_prior_mu=138.0,
        bpm_prior_sigma=0.22,
        bpm_hint_min=132.0,
        bpm_hint_max=145.0,
        spectral_centroid_mu=1900.0,
        spectral_centroid_sigma=400.0,
        zcr_mu=0.075,
        zcr_sigma=0.020,
        onset_density_mu=3.5,
        onset_density_sigma=1.5,
        vocal_hnr_mu=0.35,
        vocal_fmr_mu=0.25,
        expected_bands=[
            0.550, 0.570, 0.580, 0.600, 0.620, 0.620, 0.600, 0.650,
            0.680, 0.720, 0.750, 0.730, 0.700, 0.780, 0.850, 0.880,
            0.920, 0.950, 0.900, 0.820, 0.780, 0.740, 0.700, 0.680,
            0.620, 0.580, 0.550, 0.530, 0.520, 0.520, 0.500, 0.500,
            0.520, 0.560, 0.620, 0.680, 0.740, 0.800, 0.820, 0.800,
            0.780, 0.800, 0.820, 0.800, 0.780, 0.760, 0.740, 0.720,
            0.740, 0.780, 0.820, 0.860, 0.900, 0.940, 0.980, 1.000,
            0.950, 0.880, 0.780, 0.680, 0.580, 0.480, 0.400, 0.320,
        ],
    ),
    "hard_techno": AudioProfile(
        name="Hard Techno",
        description="Punishing kick, clipped industrial mids, and high-BPM insistence",
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
        bpm_prior_mu=148.0,
        bpm_prior_sigma=0.22,
        bpm_hint_min=142.0,
        bpm_hint_max=154.0,
        spectral_centroid_mu=2000.0,
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
        # Hardstyle: distorted/reverse-bass kick + screech leads at 145-165 BPM.
        # Mid emphasis raised for onset detection since the screech-lead
        # transients carry as much rhythmic information as the kick itself.
        onset_bass_emphasis=1.50,
        onset_mid_emphasis=1.40,
        onset_treble_emphasis=1.00,
        bpm_prior_mu=150.0,
        bpm_prior_sigma=0.16,
        bpm_hint_min=145.0,
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
        bpm_prior_mu=174.0,
        bpm_prior_sigma=0.18,
        bpm_hint_min=168.0,
        bpm_hint_max=178.0,
        spectral_centroid_mu=2200.0,
        spectral_centroid_sigma=250.0,
        zcr_mu=0.085,
        zcr_sigma=0.015,
        onset_density_mu=4.5,
        onset_density_sigma=0.7,
        vocal_hnr_mu=0.35,
        vocal_fmr_mu=0.25,
        expected_bands=[
            1.000, 0.950, 0.900, 0.850, 0.800, 0.750, 0.950, 0.970,
            0.990, 0.800, 0.900, 0.850, 0.800, 0.850, 0.900, 0.950,
            1.000, 0.900, 0.800, 0.880, 0.850, 0.800, 0.750, 0.800,
            0.850, 0.900, 0.950, 1.000, 0.900, 0.800, 0.700, 0.950,
            0.900, 0.850, 0.800, 0.850, 0.900, 0.950, 1.000, 0.850,
            0.800, 0.750, 0.700, 0.650, 0.600, 0.700, 0.800, 0.850,
            0.900, 0.950, 1.000, 0.900, 0.800, 0.700, 0.600, 0.550,
            0.500, 0.450, 0.400, 0.350, 0.300, 0.250, 0.200, 0.150,
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
        bpm_prior_mu=140.0,
        bpm_prior_sigma=0.10,
        bpm_hint_min=138.0,
        bpm_hint_max=142.0,
        spectral_centroid_mu=950.0,
        spectral_centroid_sigma=250.0,
        zcr_mu=0.095,
        zcr_sigma=0.020,
        onset_density_mu=1.8,
        onset_density_sigma=1.5,
        vocal_hnr_mu=0.35,
        vocal_fmr_mu=0.25,
        expected_bands=[
            1.000, 0.980, 0.950, 0.930, 0.920, 0.850, 0.820, 0.780,
            0.750, 0.720, 0.700, 0.650, 0.850, 0.900, 0.880, 0.850,
            0.800, 0.780, 0.720, 0.700, 0.680, 0.650, 0.650, 0.650,
            0.600, 0.600, 0.550, 0.500, 0.500, 0.400, 0.300, 0.250,
            0.200, 0.180, 0.180, 0.150, 0.120, 0.100, 0.100, 0.120,
            0.180, 0.150, 0.100, 0.100, 0.100, 0.150, 0.180, 0.200,
            0.250, 0.300, 0.350, 0.350, 0.300, 0.250, 0.200, 0.180,
            0.150, 0.120, 0.100, 0.100, 0.080, 0.080, 0.070, 0.070,
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
        description="Heavy sub-bass with sustained, vocal-forward mids -- merged hip-hop/R&B sibling profile",
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
        bpm_prior_mu=86.5,
        bpm_prior_sigma=0.27,
        bpm_hint_min=70.0,
        bpm_hint_max=100.0,
        spectral_centroid_mu=1200.0,
        spectral_centroid_sigma=400.0,
        zcr_mu=0.054,
        zcr_sigma=0.028,
        onset_density_mu=1.9,
        onset_density_sigma=1.5,
        vocal_hnr_mu=0.58,
        vocal_fmr_mu=0.53,
        # Regenerated (tools/gen_spectral_fingerprints.py, scoped rerun,
        # 2026-08-06) rather than hand-blending the two originals' arrays,
        # so the merged fingerprint doesn't inherit their inconsistencies.
        # Prompt: sustained (not choppy) vocal plateau 150 Hz-3.2 kHz
        # reflecting both rap's spoken-word cadence and R&B's held melodic
        # lines, subdued hi-hats 6-12 kHz, low-to-moderate centroid.
        expected_bands=[
            0.300, 0.350, 0.400, 0.450, 0.550, 0.680, 0.800, 1.000,
            0.950, 0.900, 0.880, 0.850, 0.800, 0.780, 0.750, 0.730,
            0.700, 0.650, 0.680, 0.750, 0.800, 0.850, 0.870, 0.900,
            0.920, 0.900, 0.850, 0.800, 0.750, 0.700, 0.680, 0.720,
            0.750, 0.780, 0.800, 0.820, 0.780, 0.750, 0.720, 0.700,
            0.680, 0.650, 0.620, 0.680, 0.650, 0.600, 0.550, 0.500,
            0.450, 0.400, 0.380, 0.350, 0.320, 0.300, 0.280, 0.250,
            0.230, 0.220, 0.200, 0.180, 0.160, 0.150, 0.130, 0.120,
        ],
    ),
    "hyphy": AudioProfile(
        name="Hyphy",
        description="Aggressive sub-bass, sustained hype-vocal chops, bright treble",
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
        bpm_prior_mu=95.0,
        bpm_prior_sigma=0.25,
        # 2026-07-08: bpm_hint_min/max had never been set despite the genre's
        # own tempo pocket being documented above ("90-110 BPM") -- without a
        # hint, the ACF search ran the full 60-200 BPM range unconstrained
        # (confirmed as a likely factor in a real Detroit-techno-into-hyphy
        # misclassification, since 120-135 BPM techno sat comfortably inside
        # this profile's uncapped search). Wired the hint to the range
        # already documented in this profile's own comment.
        bpm_hint_min=90.0,
        bpm_hint_max=110.0,
        spectral_centroid_mu=1800.0,
        spectral_centroid_sigma=600.0,
        zcr_mu=0.068,
        zcr_sigma=0.028,
        onset_density_mu=2.5,
        onset_density_sigma=1.5,
        vocal_hnr_mu=0.55,
        vocal_fmr_mu=0.5,
        # 2026-08-06: regenerated (tools/gen_spectral_fingerprints.py,
        # scoped rerun -- see docs/adr/vj-system.md) after a cosine-
        # similarity audit found the previous fingerprint nearly
        # indistinguishable from chillstep (0.9788) despite very different
        # acoustic character. New prompt explicitly emphasized hyphy's
        # bright, prominent hats/snare 4-12 kHz as its defining feature
        # (bands ~39-47) versus chillstep's deliberately soft/recessed
        # treble in the same range. Improved chillstep similarity to 0.9703
        # -- a real but modest gain, not a full fix; some residual overlap
        # looks like an inherent limit of relative-magnitude cosine
        # similarity across a cluster of genres that share a similar
        # broad sub-bass-to-treble envelope shape, not a synthesis quality
        # issue. centroid_mu (1800 vs chillstep's 900, already a full
        # octave apart) and zcr_mu remain the sharper discriminators
        # between these two -- see spectral_centroid_sigma and zcr_fit.
        expected_bands=[
            0.150, 0.180, 0.220, 0.280, 0.350, 0.400, 0.500, 0.650,
            0.750, 0.850, 0.950, 1.000, 0.950, 0.900, 0.850, 0.800,
            0.780, 0.750, 0.700, 0.850, 0.800, 0.780, 0.750, 0.720,
            0.700, 0.680, 0.650, 0.680, 0.700, 0.730, 0.750, 0.780,
            0.820, 0.850, 0.880, 0.900, 0.920, 0.950, 0.970, 1.000,
            0.950, 0.900, 0.850, 0.800, 0.780, 0.750, 0.720, 0.950,
            1.000, 0.980, 0.970, 0.950, 0.900, 0.880, 0.850, 0.800,
            0.750, 0.700, 0.650, 0.600, 0.550, 0.500, 0.450, 0.400,
        ],
    ),
    # 2026-08-03: disabled from discovery (Alt+A cycling, auto-vj recommender
    # candidate pool) now that a real genre roster covers the material this
    # was standing in for -- a flat, no-bias "unknown content" fallback was
    # actively competing against, and getting confused with, genuinely
    # calibrated profiles. Left in PROFILES (not deleted) so get_profile()'s
    # own fallback-on-unknown-key behaviour and any existing config
    # referencing it by name keep working. See enabled_profiles()/
    # AudioProfile.enabled.
    "generic": AudioProfile(
        name="Generic",
        description="Balanced profile for unknown or mixed content",
        enabled=False,
        bass_min=20.0,
        bass_max=250.0,
        mid_min=250.0,
        mid_max=3000.0,
        treble_min=3000.0,
        treble_max=20000.0,
        bass_weight=1.0,
        mid_weight=1.0,
        treble_weight=1.0,
        beat_threshold=1.2,
        smoothing=0.1,
        curve="flat",
        # Generic: balanced (matches legacy hardcoded behaviour for
        # backward compatibility with prior v1 tuning).
        onset_bass_emphasis=1.8,
        onset_mid_emphasis=1.2,
        onset_treble_emphasis=1.0,
        bpm_prior_mu=120.0,
        bpm_prior_sigma=0.55,
        # No bpm_hint_min/max: Generic is a disabled (enabled=False) catch-all
        # fallback, not a genre with a real "sweet spot" tempo range to
        # display -- see P2-E in docs/audits/2026-08-04-bpm-detector-audit.md.
        spectral_centroid_mu=1600.0,
        spectral_centroid_sigma=600.0,
        zcr_mu=0.065,
        zcr_sigma=0.028,
        onset_density_mu=2.5,
        onset_density_sigma=1.5,
        expected_bands=[
            0.620, 0.640, 0.660, 0.680, 0.700, 0.720, 0.740, 0.760,
            0.780, 0.800, 0.720, 0.740, 0.760, 0.780, 0.800, 0.820,
            0.840, 0.860, 0.880, 0.900, 0.920, 0.940, 0.960, 0.980,
            1.000, 0.980, 0.960, 0.940, 0.920, 0.900, 0.880, 0.860,
            0.840, 0.820, 0.800, 0.780, 0.760, 0.740, 0.720, 0.700,
            0.680, 0.660, 0.640, 0.620, 0.600, 0.580, 0.560, 0.540,
            0.520, 0.500, 0.520, 0.540, 0.560, 0.580, 0.600, 0.620,
            0.640, 0.660, 0.680, 0.700, 0.720, 0.740, 0.760, 0.780,
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
        bpm_prior_mu=100.0,
        bpm_prior_sigma=0.60,
        bpm_hint_min=84.0,
        bpm_hint_max=116.0,
        spectral_centroid_mu=800.0,
        spectral_centroid_sigma=600.0,
        zcr_mu=0.030,
        zcr_sigma=0.028,
        onset_density_mu=0.4,
        onset_density_sigma=2.0,
        expected_bands=[
            0.400, 0.420, 0.440, 0.460, 0.480, 0.500, 0.520, 0.540,
            0.560, 0.580, 0.600, 0.620, 0.640, 0.750, 0.800, 1.000,
            0.900, 0.860, 0.820, 0.780, 0.600, 0.400, 0.380, 0.360,
            0.340, 0.320, 0.300, 0.280, 0.260, 0.240, 0.220, 0.200,
            0.180, 0.160, 0.140, 0.120, 0.100, 0.050, 0.050, 0.050,
            0.200, 0.220, 0.250, 0.280, 0.320, 0.360, 0.400, 0.440,
            0.480, 0.500, 0.450, 0.400, 0.350, 0.320, 0.260, 0.200,
            0.150, 0.100, 0.080, 0.060, 0.050, 0.050, 0.050, 0.050,
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
        bpm_prior_mu=95.0,
        bpm_prior_sigma=0.50,
        bpm_hint_min=78.0,
        bpm_hint_max=112.0,
        spectral_centroid_mu=900.0,
        spectral_centroid_sigma=600.0,
        zcr_mu=0.040,
        zcr_sigma=0.028,
        onset_density_mu=1.5,
        onset_density_sigma=1.5,
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
        expected_bands=[
            0.200, 0.250, 0.300, 0.350, 0.400, 0.450, 0.500, 0.700,
            0.800, 0.950, 1.000, 0.950, 0.900, 0.850, 0.800, 0.750,
            0.720, 0.700, 0.680, 0.650, 0.620, 0.600, 0.580, 0.550,
            0.530, 0.500, 0.470, 0.500, 0.550, 0.600, 0.650, 0.670,
            0.700, 0.720, 0.750, 0.780, 0.800, 0.820, 0.780, 0.750,
            0.700, 0.650, 0.620, 0.680, 0.700, 0.720, 0.750, 0.600,
            0.550, 0.520, 0.500, 0.480, 0.450, 0.420, 0.400, 0.380,
            0.350, 0.330, 0.300, 0.280, 0.250, 0.230, 0.200, 0.180,
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
        bpm_prior_mu=100.0,
        bpm_prior_sigma=0.34,
        bpm_hint_min=85.0,
        bpm_hint_max=118.0,
        # Brightness sits between chillstep's pad-only atmosphere (900 Hz)
        # and house's percussion-driven brightness (1500 Hz) -- present lead
        # synths without a hi-hat-driven treble floor.
        spectral_centroid_mu=1200.0,
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
    """Get a profile by name. Falls back to 'generic' if not found.

    Direct-lookup path: resolves a disabled profile too (e.g. 'generic'
    itself, or any explicit config reference) -- only discovery
    (list_profiles() / enabled_profiles()) hides disabled profiles.
    """
    return PROFILES.get(name, PROFILES["generic"])


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
