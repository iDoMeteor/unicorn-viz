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
    # zcr_mu: zero-crossing rate per sample — correlates with harshness/noise content
    # onset_density_mu: expected onset events per second (with kick-biased weighting)
    spectral_centroid_mu: float | None = None
    zcr_mu: float | None = None
    onset_density_mu: float | None = None

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
        zcr_mu=0.060,
        onset_density_mu=2.5,
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
        zcr_mu=0.065,
        onset_density_mu=2.8,
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
        zcr_mu=0.072,
        onset_density_mu=3.2,
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
        zcr_mu=0.080,
        onset_density_mu=3.5,
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
        zcr_mu=0.090,
        onset_density_mu=4.0,
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
        # 2026-07-08: lowered 0.065 -> 0.052 (confusability pass, see ADR).
        # zcr_mu was an exact duplicate of both generic's (0.065) and
        # tech_house's (0.065) values, making this profile the closest
        # competing match to both. This is the one dimension both neighbors
        # shared, so it's a single-parameter fix that separates from both
        # simultaneously without trading centroid/onset distance against
        # either.
        zcr_mu=0.052,
        onset_density_mu=2.5,
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
        # 2026-07-08: raised 0.068 -> 0.086 (confusability pass, see ADR).
        # Was tied exactly with uk_garage's zcr_mu and close to breaks',
        # making this the 2nd/3rd-closest competing pair in the whole
        # roster. Raised rather than lowered: "rolling tribal percussion...
        # busy hats" (see description above) implies more noise-like/
        # percussive high-frequency content than its neighbors, not less --
        # this is the direction consistent with the genre's own character,
        # and numerically separates from both neighbors at once.
        zcr_mu=0.086,
        onset_density_mu=3.2,
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
        zcr_mu=0.068,
        onset_density_mu=2.8,
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
        bpm_prior_sigma=0.28,
        bpm_hint_min=132.0,
        bpm_hint_max=145.0,
        spectral_centroid_mu=1900.0,
        zcr_mu=0.075,
        onset_density_mu=3.5,
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
        zcr_mu=0.075,
        onset_density_mu=3.5,
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
        zcr_mu=0.130,
        onset_density_mu=4.0,
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
    "fire_dj": AudioProfile(
        name="Fire DJ",
        description=(
            "High-energy electronic profile for fast, wide-tempo DJ sets with "
            "heavy kick, active hats, and synth-mid drive"
        ),
        bass_min=24.0,
        bass_max=240.0,
        mid_min=240.0,
        mid_max=4600.0,
        treble_min=4600.0,
        treble_max=20000.0,
        bass_weight=1.18,
        mid_weight=1.16,
        treble_weight=1.12,
        beat_threshold=1.00,
        smoothing=0.085,
        curve="aggressive",
        # Electronic emphasis: strong kick + hats + synth mids. Less drum-kit
        # bias than metal; more tolerant than narrow hard-techno/trance lanes.
        onset_bass_emphasis=1.45,
        onset_mid_emphasis=1.30,
        onset_treble_emphasis=1.18,
        # 2026-07-08: bpm_prior_mu 148 -> 152 (confusability pass, see ADR).
        # This wide-tempo DJ-set catch-all (132-170 BPM) exactly copied
        # hard_techno's center point (148), making it the closest competing
        # match to a much narrower, specific genre profile. Shifted to sit
        # nearer the true center of this profile's own declared range
        # instead of duplicating a neighbor's.
        bpm_prior_mu=152.0,
        bpm_prior_sigma=0.32,
        bpm_hint_min=132.0,
        bpm_hint_max=170.0,
        spectral_centroid_mu=2100.0,
        zcr_mu=0.076,
        onset_density_mu=3.8,
        vocal_hnr_mu=0.35,
        vocal_fmr_mu=0.25,
        expected_bands=[
            0.920, 0.880, 0.850, 0.820, 0.780, 0.750, 0.800, 0.850,
            0.900, 0.950, 0.800, 0.850, 0.900, 0.880, 0.850, 0.900,
            0.920, 0.950, 0.850, 0.750, 0.800, 0.850, 0.880, 0.920,
            0.950, 1.000, 0.950, 0.900, 0.850, 0.800, 0.750, 0.700,
            0.650, 0.600, 0.550, 0.600, 0.650, 0.700, 0.750, 0.800,
            0.850, 0.900, 0.950, 1.000, 0.950, 0.900, 0.850, 0.700,
            0.750, 0.800, 0.850, 0.900, 0.920, 0.950, 0.850, 0.750,
            0.800, 0.850, 0.880, 0.920, 0.950, 1.000, 0.950, 0.900,
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
        zcr_mu=0.085,
        onset_density_mu=4.5,
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
        zcr_mu=0.095,
        onset_density_mu=1.8,
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
    "rap": AudioProfile(
        name="Rap / Hip-Hop",
        description="Heavy sub-bass (808 kick), sustained vocal presence, moderate treble",
        bass_min=20.0,
        bass_max=300.0,
        mid_min=300.0,
        mid_max=2500.0,
        treble_min=2500.0,
        treble_max=20000.0,
        bass_weight=1.4,
        mid_weight=1.25,
        treble_weight=0.8,
        beat_threshold=1.0,
        smoothing=0.14,
        curve="extreme_bass_boost",
        # Rap/Hip-Hop: very kick-driven at 70-100 BPM.  With raw-spectrum
        # flux the kick already dominates; restore some treble so hi-hats
        # can contribute to ACF periodicity and subdivisions are visible.
        onset_bass_emphasis=1.4,
        onset_mid_emphasis=1.0,
        onset_treble_emphasis=0.80,
        bpm_prior_mu=88.0,
        bpm_prior_sigma=0.30,
        # 2026-07-08: bpm_hint_min/max had never been set despite the genre's
        # own tempo pocket being documented above ("70-100 BPM") -- without a
        # hint, the ACF search ran the full 60-200 BPM range unconstrained,
        # relying only on the soft Gaussian prior. Wired the hint to the
        # range already documented in this profile's own comment.
        bpm_hint_min=70.0,
        bpm_hint_max=100.0,
        spectral_centroid_mu=1600.0,
        zcr_mu=0.060,
        onset_density_mu=2.0,
        vocal_hnr_mu=0.55,
        vocal_fmr_mu=0.5,
        # Fingerprint reshaped for a sustained (not choppy) plateau across the
        # 150 Hz-3.2 kHz vocal-formant range (bands 16-47) — rap vocals are a
        # continuous signal, unlike percussion transients, so the genre match
        # should reward steady mid-band presence rather than an oscillating
        # pattern. Sub/kick fundamental (bands 0-15) is unchanged.
        expected_bands=[
            0.900, 0.870, 0.840, 0.800, 0.760, 0.720, 0.680, 0.700,
            0.750, 0.800, 0.850, 0.900, 0.870, 0.900, 0.930, 0.950,
            0.900, 0.870, 0.850, 0.830, 0.850, 0.870, 0.890, 0.900,
            0.900, 0.880, 0.870, 0.860, 0.870, 0.880, 0.870, 0.850,
            0.860, 0.870, 0.880, 0.870, 0.860, 0.850, 0.840, 0.830,
            0.820, 0.800, 0.780, 0.750, 0.700, 0.650, 0.600, 0.550,
            0.500, 0.450, 0.400, 0.350, 0.300, 0.280, 0.260, 0.240,
            0.220, 0.200, 0.180, 0.160, 0.150, 0.140, 0.130, 0.120,
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
        zcr_mu=0.068,
        onset_density_mu=2.5,
        vocal_hnr_mu=0.55,
        vocal_fmr_mu=0.5,
        # Fingerprint reshaped for a sustained hype-vocal-chop plateau across
        # 200 Hz-3 kHz (bands 16-47), brighter/broader than rap's per the
        # genre's punchier, more treble-forward character.
        expected_bands=[
            0.930, 0.900, 0.870, 0.830, 0.800, 0.850, 0.880, 0.900,
            0.930, 0.960, 0.980, 0.920, 0.880, 0.900, 0.920, 0.900,
            0.870, 0.850, 0.870, 0.890, 0.870, 0.850, 0.830, 0.810,
            0.850, 0.870, 0.880, 0.870, 0.860, 0.850, 0.840, 0.830,
            0.850, 0.870, 0.880, 0.870, 0.850, 0.830, 0.810, 0.790,
            0.800, 0.790, 0.780, 0.760, 0.740, 0.720, 0.700, 0.720,
            0.750, 0.780, 0.800, 0.820, 0.800, 0.780, 0.750, 0.720,
            0.700, 0.680, 0.650, 0.620, 0.580, 0.540, 0.500, 0.460,
        ],
    ),
    "r&b": AudioProfile(
        name="R&B / Soul",
        description="Warm low-mids, sustained vocal-forward mids, smooth low-noise treble",
        bass_min=40.0,
        bass_max=250.0,
        mid_min=250.0,
        mid_max=3500.0,
        treble_min=3500.0,
        treble_max=20000.0,
        bass_weight=1.1,
        mid_weight=1.4,
        treble_weight=0.9,
        beat_threshold=1.25,
        smoothing=0.13,
        curve="warm",
        # R&B/Soul: vocal-driven at 75-100 BPM, kick + snare backbeat.
        onset_bass_emphasis=1.8,
        onset_mid_emphasis=1.2,
        onset_treble_emphasis=0.7,
        bpm_prior_mu=85.0,
        bpm_prior_sigma=0.30,
        # 2026-07-08: bpm_hint_min/max had never been set despite the genre's
        # own tempo pocket being documented above ("75-100 BPM") -- without a
        # hint, the ACF search ran the full 60-200 BPM range unconstrained.
        # Wired the hint to the range already documented in this profile's
        # own comment.
        bpm_hint_min=75.0,
        bpm_hint_max=100.0,
        spectral_centroid_mu=1400.0,
        # Lowered slightly (0.052 -> 0.048): smooth, sustained vocals are the
        # least noisy signal of the three vocal-forward profiles.
        zcr_mu=0.048,
        onset_density_mu=1.8,
        vocal_hnr_mu=0.6,
        vocal_fmr_mu=0.55,
        # Fingerprint reshaped into the broadest, most sustained vocal plateau
        # of the three (150 Hz-3.2 kHz, bands 16-47 at 0.82-0.97) — the most
        # vocal-forward genre of the set should show the steadiest mid-band
        # presence rather than a narrow peak.
        expected_bands=[
            0.620, 0.600, 0.580, 0.560, 0.600, 0.640, 0.660, 0.680,
            0.700, 0.720, 0.740, 0.720, 0.700, 0.730, 0.760, 0.790,
            0.820, 0.850, 0.870, 0.860, 0.850, 0.860, 0.870, 0.880,
            0.890, 0.900, 0.910, 0.920, 0.930, 0.940, 0.930, 0.920,
            0.930, 0.940, 0.950, 0.960, 0.970, 0.960, 0.950, 0.940,
            0.920, 0.900, 0.880, 0.850, 0.820, 0.790, 0.760, 0.730,
            0.650, 0.600, 0.550, 0.500, 0.460, 0.430, 0.400, 0.380,
            0.360, 0.340, 0.320, 0.300, 0.280, 0.260, 0.240, 0.220,
        ],
    ),
    "generic": AudioProfile(
        name="Generic",
        description="Balanced profile for unknown or mixed content",
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
        bpm_hint_min=108.0,
        bpm_hint_max=132.0,
        spectral_centroid_mu=1600.0,
        zcr_mu=0.065,
        onset_density_mu=2.5,
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
        zcr_mu=0.030,
        onset_density_mu=0.4,
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
        zcr_mu=0.040,
        onset_density_mu=1.5,
        expected_bands=[
            0.750, 0.800, 0.850, 0.900, 0.950, 1.000, 0.900, 0.800,
            0.700, 0.600, 0.550, 0.500, 0.450, 0.400, 0.650, 0.700,
            0.750, 0.800, 0.850, 0.900, 0.950, 1.000, 0.850, 0.700,
            0.600, 0.620, 0.640, 0.660, 0.680, 0.700, 0.720, 0.740,
            0.760, 0.780, 0.800, 0.820, 0.840, 0.860, 0.880, 0.900,
            0.800, 0.700, 0.600, 0.620, 0.640, 0.660, 0.680, 0.700,
            0.720, 0.740, 0.760, 0.780, 0.800, 0.820, 0.840, 0.860,
            0.880, 0.900, 0.800, 0.700, 0.600, 0.620, 0.640, 0.660,
        ],
    ),
}


def get_profile(name: str) -> AudioProfile:
    """Get a profile by name. Falls back to 'generic' if not found."""
    return PROFILES.get(name, PROFILES["generic"])


def list_profiles() -> list[str]:
    """Return list of available profile names."""
    return sorted(PROFILES.keys())
