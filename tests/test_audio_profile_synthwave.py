"""Regression tests for the 'synthwave' AudioProfile.

Added 2026-08-03 after a livestream training session (Kavinsky tribute) ran
the whole night under 'generic' and sagged into psytrance/trance whenever
detected BPM ran hot -- see the profile's own comment in
unicornviz/audio/profiles.py for the full provenance.
"""

from __future__ import annotations

from unicornviz.audio.profiles import PROFILES, get_profile, list_profiles


def test_synthwave_is_registered() -> None:
    """2026-09-04 (recommender rc.29, evidence audit): disabled -- zero
    training-list corpus of any kind, every scoring field still hand-
    authored/guessed (same standing rule as psytrance/hard_techno/
    hardstyle, see docs/adr/vj-system.md). Still directly resolvable by
    key/get_profile(), same disable-not-delete pattern as tech_house --
    only excluded from list_profiles()/enabled_profiles() discovery."""
    assert 'synthwave' in PROFILES
    assert 'synthwave' not in list_profiles()
    assert get_profile('synthwave') is PROFILES['synthwave']
    assert PROFILES['synthwave'].enabled is False


def test_synthwave_tempo_prior_matches_classic_kavinsky_range() -> None:
    p = get_profile('synthwave')
    assert p.bpm_hint_min == 85.0
    assert p.bpm_hint_max == 118.0
    assert p.bpm_hint_min < p.bpm_prior_mu < p.bpm_hint_max
    # Clearly separated from house's hint range so a synthwave track's
    # tempo can't be silently absorbed into the wrong neighbor. <=, not <:
    # 2026-08-10's house-family consolidation moved house's own hint_min to
    # 118, exactly touching synthwave's hint_max -- adjacent bands with a
    # shared boundary are fine (same convention as deep_house/chillstep
    # elsewhere in this profile roster), an actual overlap is not.
    house = get_profile('house')
    assert p.bpm_hint_max <= house.bpm_hint_min


def test_synthwave_spectral_fields_are_calibrated() -> None:
    p = get_profile('synthwave')
    assert p.spectral_centroid_mu is not None
    assert p.zcr_mu is not None
    assert p.onset_density_mu is not None
    # 2026-08-09: brightness used to sit below house by design (not
    # fabricated/arbitrary) -- see the field's comment in profiles.py.
    #
    # 2026-09-04 (recommender rc.29): flipped again, this time for real
    # reasons rather than a data-quality question. house's (and the other
    # 12 real-fingerprint profiles') spectral_centroid_mu was mechanically
    # re-derived against the same-night ribbon-redesigned expected_bands
    # (real per-track median fingerprints), which collapsed every
    # recomputed value into a narrow 250-450 Hz band -- house is now 450.
    # synthwave is one of the four still-disabled, no-training-corpus
    # profiles (see its own field comment / enabled=False) and was
    # correctly NOT touched by that recompute, so it kept its old
    # hand-authored 1700. The ordering is now an artifact of which
    # profiles have real per-track data, not a genre-brightness claim --
    # see spectral_centroid_mu's own field comment in profiles.py for the
    # full finding (centroid_fit stays weight-0.0/dormant throughout, so
    # none of this has live-scoring effect).
    house = get_profile('house')
    assert p.spectral_centroid_mu > house.spectral_centroid_mu


def test_synthwave_vocal_fields_left_uncalibrated() -> None:
    """Classic synthwave (Kavinsky et al.) is predominantly instrumental --
    a fabricated vocal target would be worse than no signal at all."""
    p = get_profile('synthwave')
    assert p.vocal_hnr_mu is None
    assert p.vocal_fmr_mu is None


def test_synthwave_expected_bands_well_formed() -> None:
    p = get_profile('synthwave')
    assert p.expected_bands is not None
    assert len(p.expected_bands) == 64
    assert all(0.0 <= v <= 1.0 for v in p.expected_bands)
    # Peak should land in the lead-synth register (bands 39-40, ~1.4-1.6 kHz),
    # not in the sub-bass region the way a kick-driven genre's fingerprint does.
    peak_idx = max(range(64), key=lambda i: p.expected_bands[i])
    assert 35 <= peak_idx <= 44


def test_synthwave_hud_bpm_range_label() -> None:
    p = get_profile('synthwave')
    assert p.hud_bpm_range_label() == '85-118'
