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
    # Optional user-facing "sweet spot" range for HUD / diagnostics.
    bpm_hint_min: float | None = None
    bpm_hint_max: float | None = None

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
        bpm_prior_sigma=0.20,
        bpm_hint_min=120.0,
        bpm_hint_max=128.0,
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
    ),
    "rock": AudioProfile(
        name="Rock",
        description="Guitar-forward live-band profile with strong mids and cymbal energy",
        bass_min=40.0,
        bass_max=280.0,
        mid_min=250.0,
        mid_max=3500.0,
        treble_min=3000.0,
        treble_max=20000.0,
        bass_weight=0.82,
        mid_weight=1.42,
        treble_weight=1.35,
        beat_threshold=1.15,
        smoothing=0.09,
        curve="bright",
        # Rock: snare / guitars / cymbals should dominate over bass.
        onset_bass_emphasis=0.90,
        onset_mid_emphasis=1.65,
        onset_treble_emphasis=1.50,
        bpm_prior_mu=118.0,
        bpm_prior_sigma=0.28,
        bpm_hint_min=110.0,
        bpm_hint_max=138.0,
    ),
    "metal": AudioProfile(
        name="Metal / Extreme",
        description="Aggressive live-band profile with dominant mids and high-end attack",
        bass_min=40.0,
        bass_max=350.0,
        mid_min=350.0,
        mid_max=3500.0,
        treble_min=3500.0,
        treble_max=20000.0,
        bass_weight=0.78,
        mid_weight=1.50,
        treble_weight=1.42,
        beat_threshold=1.0,
        smoothing=0.09,
        curve="bright",
        # Metal: snare, guitar wall, and cymbals should outweigh the kick.
        onset_bass_emphasis=0.85,
        onset_mid_emphasis=1.70,
        onset_treble_emphasis=1.55,
        bpm_prior_mu=148.0,
        bpm_prior_sigma=0.24,
        bpm_hint_min=134.0,
        bpm_hint_max=170.0,
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
        bpm_prior_mu=148.0,
        bpm_prior_sigma=0.32,
        bpm_hint_min=132.0,
        bpm_hint_max=170.0,
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
        bpm_hint_min=84.0,
        bpm_hint_max=116.0,
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
        bpm_prior_mu=90.0,
        bpm_prior_sigma=0.45,
        bpm_hint_min=78.0,
        bpm_hint_max=108.0,
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
}


def get_profile(name: str) -> AudioProfile:
    """Get a profile by name. Falls back to 'generic' if not found."""
    return PROFILES.get(name, PROFILES["generic"])


def list_profiles() -> list[str]:
    """Return list of available profile names."""
    return sorted(PROFILES.keys())
