"""Regression tests for the 'synthwave' AudioProfile.

Added 2026-08-03 after a livestream training session (Kavinsky tribute) ran
the whole night under 'generic' and sagged into psytrance/trance whenever
detected BPM ran hot -- see the profile's own comment in
unicornviz/audio/profiles.py for the full provenance.
"""

from __future__ import annotations

from unicornviz.audio.profiles import PROFILES, get_profile, list_profiles


def test_synthwave_is_registered() -> None:
    """2026-09-04 (recommender rc.29, evidence audit): was disabled -- zero
    training-list corpus of any kind, every scoring field still hand-
    authored/guessed (same standing rule as psytrance/hard_techno/
    hardstyle, see docs/adr/vj-system.md).

    2026-09-10 (zone-map batch): RE-ENABLED as part of the owner's
    full-roster genre BPM table rewrite ("all enabled"). The zero-corpus
    caveat above still applied in full at that point.

    2026-09-10 (zone-map batch, Phase 5 pilot-run cleanup, later):
    DISABLED again -- owner, direct: "disable all the genres we do not
    have library coverage for." Disable-not-delete -- direct lookup
    (get_profile(...)) still resolves it; it just no longer appears in
    discovery (list_profiles()/enabled_profiles()). See
    test_default_enabled_true_for_profiles_that_dont_set_it in
    test_audio_profile_deep_house_and_disable.py for the full current
    disabled-roster set this test's assertion below is part of."""
    assert 'synthwave' in PROFILES
    assert 'synthwave' not in list_profiles()
    assert get_profile('synthwave') is PROFILES['synthwave']
    assert PROFILES['synthwave'].enabled is False


def test_synthwave_tempo_prior_matches_classic_kavinsky_range() -> None:
    """2026-09-10 (zone-map batch): hint band 85-118 -> 100-116 (owner's
    genre BPM table) -- the wider retro-synth territory this profile used
    to cover alone is now split across dedicated siblings (vaporwave
    60-80, chillwave 84-96, hardsynth 120-130); see profiles.py's own
    field comment on the Kavinsky-tempo grounding note this narrowed."""
    p = get_profile('synthwave')
    assert p.bpm_hint_min == 100.0
    assert p.bpm_hint_max == 116.0
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
    """2026-09-10 (zone-map batch, recommender rc.41): spectral_centroid_mu
    (and the whole centroid_fit term/field pair) removed entirely -- the
    brightness-ordering claim this test used to make against house no
    longer applies to anything (no field to compare, no term to score
    it). zcr_mu/onset_density_mu are still real, live-scoring fields."""
    p = get_profile('synthwave')
    assert p.zcr_mu is not None
    assert p.onset_density_mu is not None


def test_synthwave_vocal_fields_now_real_not_uncalibrated() -> None:
    """2026-09-10 (zone-map batch, Phase 5 prep): superseded -- real (if
    thin, n=7) vocal_hnr/vocal_fmr medians measured from a filtered subset
    of training-synthwave-02/03, replacing the old "predominantly
    instrumental, leave uncalibrated" theory. The filtered tracks carry
    real, if modest, vocal presence."""
    p = get_profile('synthwave')
    assert p.vocal_hnr_mu is not None
    assert p.vocal_fmr_mu is not None


def test_synthwave_expected_bands_well_formed() -> None:
    """2026-09-10 (zone-map batch, Phase 5 prep): peak-band assertion
    superseded -- expected_bands is now the real per-track ribbon from a
    filtered, synth-titled subset of training-synthwave-02/03 (n=7), not
    the old hand-authored ascending-then-descending shape. The real shape
    peaks in the low-mid register (band ~7, ~500-700 Hz) and rolls off
    fast, not at bands 39-40."""
    p = get_profile('synthwave')
    assert p.expected_bands is not None
    assert len(p.expected_bands) == 64
    assert all(0.0 <= v <= 1.0 for v in p.expected_bands)
    peak_idx = max(range(64), key=lambda i: p.expected_bands[i])
    assert 0 <= peak_idx <= 12


def test_synthwave_hud_bpm_range_label() -> None:
    """2026-09-10 (zone-map batch): hint band 85-118 -> 100-116."""
    p = get_profile('synthwave')
    assert p.hud_bpm_range_label() == '100-116'
