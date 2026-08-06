"""Regression tests for:

- AudioProfile.enabled / enabled_profiles() -- capability-aware disable
  (mirrors unicorn-horn ADR-0003's pattern: disable, don't delete).
- 'generic' disabled from discovery 2026-08-03 (still resolvable directly).
- 'electronic' disabled from discovery 2026-08-06 (cosine-similarity audit
  found its expected_bands more similar to far-tempo profiles than its own
  tempo neighbors -- a non-discriminating catch-all, same treatment as
  'generic'; see docs/adr/vj-system.md).
- The new 'deep_house' profile.
"""

from __future__ import annotations

from unicornviz.audio.profiles import (
    PROFILES,
    enabled_profiles,
    get_profile,
    list_profiles,
)


# ---- enabled / disable mechanism -----------------------------------------


def test_generic_is_disabled_but_still_in_profiles() -> None:
    assert 'generic' in PROFILES
    assert PROFILES['generic'].enabled is False


def test_generic_excluded_from_discovery() -> None:
    assert 'generic' not in list_profiles()
    assert 'generic' not in enabled_profiles()


def test_generic_still_resolvable_by_direct_lookup() -> None:
    """Disabled means excluded from discovery, not deleted -- direct
    reference (explicit config, internal fallback) must keep working."""
    p = get_profile('generic')
    assert p.name == 'Generic'
    assert p is PROFILES['generic']


def test_generic_has_no_bpm_hint_range() -> None:
    """P2-E hygiene: Generic is a disabled catch-all fallback, not a genre
    with a real tempo 'sweet spot' -- it should not carry bpm_hint_min/max.
    See docs/audits/2026-08-04-bpm-detector-audit.md."""
    p = PROFILES['generic']
    assert p.bpm_hint_min is None
    assert p.bpm_hint_max is None
    # preferred_bpm_range() must still degrade gracefully (derives from the
    # prior mu/sigma instead of the removed hints).
    lo, hi = p.preferred_bpm_range()
    assert lo < hi


def test_enabled_profiles_excludes_only_disabled_entries() -> None:
    enabled = enabled_profiles()
    assert set(enabled.keys()) == {k for k, v in PROFILES.items() if v.enabled}
    assert 'generic' not in enabled
    assert 'electronic' not in enabled
    assert 'house' in enabled   # a normal enabled profile is unaffected


def test_default_enabled_true_for_profiles_that_dont_set_it() -> None:
    """Every profile except the explicitly-disabled ones should default to
    enabled=True without having to set it themselves."""
    _disabled = {'generic', 'electronic'}
    for key, profile in PROFILES.items():
        if key in _disabled:
            continue
        assert profile.enabled is True, f'{key} unexpectedly disabled'


def test_electronic_is_disabled_but_still_in_profiles() -> None:
    assert 'electronic' in PROFILES
    assert PROFILES['electronic'].enabled is False


def test_electronic_excluded_from_discovery() -> None:
    assert 'electronic' not in list_profiles()
    assert 'electronic' not in enabled_profiles()


def test_electronic_still_resolvable_by_direct_lookup() -> None:
    """Disabled means excluded from discovery, not deleted -- direct
    reference (explicit config, internal fallback) must keep working."""
    p = get_profile('electronic')
    assert p.name == 'Electronic'
    assert p is PROFILES['electronic']


# ---- deep_house -------------------------------------------------------


def test_deep_house_is_registered_and_discoverable() -> None:
    assert 'deep_house' in PROFILES
    assert 'deep_house' in list_profiles()
    assert PROFILES['deep_house'].enabled is True


def test_deep_house_tempo_sits_below_house_and_above_chillstep() -> None:
    deep_house = get_profile('deep_house')
    house = get_profile('house')
    chillstep = get_profile('chillstep')
    assert chillstep.bpm_hint_max <= deep_house.bpm_hint_min
    assert deep_house.bpm_hint_max <= house.bpm_hint_min + 4   # small edge overlap is fine
    assert deep_house.bpm_hint_min < deep_house.bpm_prior_mu < deep_house.bpm_hint_max


def test_deep_house_is_warmer_than_house_and_tech_house() -> None:
    deep_house = get_profile('deep_house')
    house = get_profile('house')
    tech_house = get_profile('tech_house')
    assert deep_house.spectral_centroid_mu < house.spectral_centroid_mu < tech_house.spectral_centroid_mu
    assert deep_house.zcr_mu < house.zcr_mu


def test_deep_house_expected_bands_well_formed() -> None:
    p = get_profile('deep_house')
    assert p.expected_bands is not None
    assert len(p.expected_bands) == 64
    assert all(0.0 <= v <= 1.0 for v in p.expected_bands)


def test_deep_house_vocal_fields_left_uncalibrated() -> None:
    p = get_profile('deep_house')
    assert p.vocal_hnr_mu is None
    assert p.vocal_fmr_mu is None
