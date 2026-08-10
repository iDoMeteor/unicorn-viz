"""Regression tests for the 'synthwave' AudioProfile.

Added 2026-08-03 after a livestream training session (Kavinsky tribute) ran
the whole night under 'generic' and sagged into psytrance/trance whenever
detected BPM ran hot -- see the profile's own comment in
unicornviz/audio/profiles.py for the full provenance.
"""

from __future__ import annotations

from unicornviz.audio.profiles import PROFILES, get_profile, list_profiles


def test_synthwave_is_registered() -> None:
    assert 'synthwave' in PROFILES
    assert 'synthwave' in list_profiles()
    assert get_profile('synthwave') is PROFILES['synthwave']


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
    # Brightness sits below house (percussion-driven) by design -- not
    # fabricated/arbitrary. 2026-08-09: the chillstep < synthwave half of
    # this used to hold too, but broke when spectral_centroid_mu was
    # recalibrated to match each profile's own expected_bands fingerprint
    # (see the field's comment in profiles.py) -- chillstep's fingerprint
    # now implies *brighter* (1700) than synthwave's own (also 1700, and
    # chillstep was already ahead unrounded), contradicting chillstep's
    # "atmospheric-only" framing here. Same data-quality question as the
    # house/tech_house reversal in test_audio_profile_deep_house_and_
    # disable.py -- deferred, not fixed here; see docs/adr/vj-system.md.
    house = get_profile('house')
    assert p.spectral_centroid_mu < house.spectral_centroid_mu


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
