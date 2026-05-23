"""Audio profile system for frequency-response tuning by genre.

Each profile defines:
- Frequency range emphasis for bass/mid/treble
- FFT band grouping and weighting
- Reactivity sensitivity curve
- Beat detection thresholds
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
        bpm_prior_sigma=0.20,
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
    ),
    "rap": AudioProfile(
        name="Rap / Hip-Hop",
        description="Heavy sub-bass (kick), focused low-mids (punch), moderate treble",
        bass_min=20.0,
        bass_max=300.0,
        mid_min=300.0,
        mid_max=2500.0,
        treble_min=2500.0,
        treble_max=20000.0,
        bass_weight=1.4,
        mid_weight=1.1,
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
    ),
    "hyphy": AudioProfile(
        name="Hyphy",
        description="Aggressive sub-bass, bright mids, punchy treble for hype",
        bass_min=20.0,
        bass_max=350.0,
        mid_min=350.0,
        mid_max=3000.0,
        treble_min=3000.0,
        treble_max=20000.0,
        bass_weight=1.5,
        mid_weight=1.2,
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
    ),
    "r&b": AudioProfile(
        name="R&B / Soul",
        description="Warm low-mids, vocal-focused mids, smooth treble",
        bass_min=40.0,
        bass_max=250.0,
        mid_min=250.0,
        mid_max=3500.0,
        treble_min=3500.0,
        treble_max=20000.0,
        bass_weight=1.1,
        mid_weight=1.3,
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
    ),
    "rock": AudioProfile(
        name="Rock",
        description="Full-range emphasis, strong mid-bass (kick/tom), treble for cymbals",
        bass_min=40.0,
        bass_max=300.0,
        mid_min=300.0,
        mid_max=3000.0,
        treble_min=3000.0,
        treble_max=20000.0,
        bass_weight=1.2,
        mid_weight=1.1,
        treble_weight=1.0,
        beat_threshold=1.15,
        smoothing=0.09,
        curve="midrange_presence",
        # Rock: kick + snare + cymbals, wide tempo range 80-160 BPM.
        onset_bass_emphasis=1.6,
        onset_mid_emphasis=1.4,
        onset_treble_emphasis=1.0,
        bpm_prior_mu=120.0,
        bpm_prior_sigma=0.40,
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
    ),
    "classical": AudioProfile(
        name="Classical / Orchestral",
        description="Wide dynamic range, emphasis on mid and treble detail",
        bass_min=60.0,
        bass_max=200.0,
        mid_min=200.0,
        mid_max=4000.0,
        treble_min=4000.0,
        treble_max=20000.0,
        bass_weight=0.9,
        mid_weight=1.2,
        treble_weight=1.3,
        beat_threshold=1.3,
        smoothing=0.08,
        curve="bright",
        # Classical: no consistent kick, wide dynamic range.
        onset_bass_emphasis=1.0,
        onset_mid_emphasis=1.3,
        onset_treble_emphasis=1.0,
        bpm_prior_mu=110.0,
        bpm_prior_sigma=0.50,
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
    ),
    "pop": AudioProfile(
        name="Pop",
        description="Radio-friendly balance with slight treble emphasis",
        bass_min=30.0,
        bass_max=200.0,
        mid_min=200.0,
        mid_max=3000.0,
        treble_min=3000.0,
        treble_max=20000.0,
        bass_weight=1.0,
        mid_weight=1.05,
        treble_weight=1.1,
        beat_threshold=1.2,
        smoothing=0.11,
        curve="slight_presence",
        # Pop: kick + snare at 95-125 BPM.
        onset_bass_emphasis=1.7,
        onset_mid_emphasis=1.3,
        onset_treble_emphasis=0.8,
        bpm_prior_mu=110.0,
        bpm_prior_sigma=0.30,
    ),
    "metal": AudioProfile(
        name="Metal / Extreme",
        description="Aggressive full-range, emphasized mids and treble",
        bass_min=40.0,
        bass_max=350.0,
        mid_min=350.0,
        mid_max=3500.0,
        treble_min=3500.0,
        treble_max=20000.0,
        bass_weight=1.3,
        mid_weight=1.2,
        treble_weight=1.1,
        beat_threshold=1.0,
        smoothing=0.09,
        curve="aggressive",
        # Metal: kick (often double-bass) + snare + cymbals, 100-180 BPM.
        onset_bass_emphasis=1.5,
        onset_mid_emphasis=1.4,
        onset_treble_emphasis=1.1,
        bpm_prior_mu=140.0,
        bpm_prior_sigma=0.40,
    ),
}


def get_profile(name: str) -> AudioProfile:
    """Get a profile by name. Falls back to 'generic' if not found."""
    return PROFILES.get(name, PROFILES["generic"])


def list_profiles() -> list[str]:
    """Return list of available profile names."""
    return sorted(PROFILES.keys())
