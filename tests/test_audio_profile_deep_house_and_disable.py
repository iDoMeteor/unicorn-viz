"""Regression tests for:

- AudioProfile.enabled / enabled_profiles() -- capability-aware disable
  (mirrors unicorn-horn ADR-0003's pattern: disable, don't delete).
- 'generic' disabled from discovery 2026-08-03 (still resolvable directly),
  then eliminated entirely 2026-08-10 (house-family consolidation pass --
  get_profile()'s unknown-key fallback moved from 'generic' to 'house',
  see docs/adr/vj-system.md). 'uk_garage' and 'breaks' eliminated the same
  day, no fallback role to reassign.
- 'electronic' disabled from discovery 2026-08-06 (cosine-similarity audit
  found its expected_bands more similar to far-tempo profiles than its own
  tempo neighbors -- a non-discriminating catch-all, same treatment as
  'generic'; see docs/adr/vj-system.md), then revived and renamed to
  'Dance' 2026-08-10 (owner call: a deliberately house-identical profile
  minus vocal presence, so the old "too similar to neighbors" disable
  reason no longer applies -- see docs/adr/vj-system.md).
- 'rap' and 'r&b' merged into 'rap_rnb' 2026-08-06 (owner call: genuine
  siblings, 0.9856 cosine similarity, 3 BPM apart -- not a false
  catch-all pairing like fire_dj/electronic).
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


def test_generic_uk_garage_breaks_hardgroove_eliminated_entirely() -> None:
    """2026-08-10/11: unlike 'electronic' (disabled, then revived), these
    were removed outright, not just disabled -- no dict entry survives.
    'hardgroove' (2026-08-11) had zero validated library examples across
    every recent session and overlapped tech_house/peak_time/hard_techno
    on nearly every axis (BPM, centroid, onset density) -- see
    docs/adr/vj-system.md."""
    for key in ('generic', 'uk_garage', 'breaks', 'hardgroove'):
        assert key not in PROFILES, f'{key} should have been eliminated entirely'
        assert key not in list_profiles()
        assert key not in enabled_profiles()


def test_get_profile_unknown_key_falls_back_to_house_not_generic() -> None:
    """get_profile()'s fallback-on-unknown-key moved from 'generic' (now
    eliminated) to 'house' -- an unknown/typo'd profile key degrades to the
    same well-populated real profile the app already starts on by default,
    not a deliberately weak catch-all."""
    p = get_profile('this-key-does-not-exist')
    assert p.name == 'House'
    assert p is PROFILES['house']
    # Also covers the literal now-dead key, for anyone with a stale
    # config.toml reference or old corpus data.
    assert get_profile('generic') is PROFILES['house']


def test_enabled_profiles_excludes_only_disabled_entries() -> None:
    enabled = enabled_profiles()
    assert set(enabled.keys()) == {k for k, v in PROFILES.items() if v.enabled}
    assert 'generic' not in enabled
    assert 'electronic' in enabled   # revived as 'Dance' 2026-08-10
    assert 'hyphy' not in enabled   # disabled 2026-08-10, see docs/adr/vj-system.md
    assert 'house' in enabled   # a normal enabled profile is unaffected


def test_default_enabled_true_for_profiles_that_dont_set_it() -> None:
    """Every profile except the explicitly-disabled ones should default to
    enabled=True without having to set it themselves.

    'generic' is gone entirely now (eliminated, not merely disabled -- see
    test_generic_uk_garage_breaks_eliminated_entirely above), so it's no
    longer in this set; 'hyphy' replaced it 2026-08-10 (disabled pending
    real trap/hyphy library material -- see docs/adr/vj-system.md)."""
    _disabled = {'hyphy'}
    for key, profile in PROFILES.items():
        if key in _disabled:
            continue
        assert profile.enabled is True, f'{key} unexpectedly disabled'


def test_electronic_key_now_resolves_to_the_revived_dance_profile() -> None:
    """Dict key kept as 'electronic' for backward compatibility with any
    existing config/corpus data that references it by key -- only the
    display name and enabled state changed."""
    assert 'electronic' in PROFILES
    p = PROFILES['electronic']
    assert p.enabled is True
    assert p.name == 'Dance'
    assert 'electronic' in list_profiles()
    assert 'electronic' in enabled_profiles()


def test_dance_matches_house_on_everything_except_vocal_presence() -> None:
    """The split between 'house' and 'dance' (electronic, revived) is meant
    to ride entirely on vocal_hnr_fit/vocal_fmr_fit -- owner: 'vocals is
    enough to carry the split, otherwise basically indistinguishable.'"""
    house = get_profile('house')
    dance = get_profile('electronic')
    assert dance.bpm_prior_mu == house.bpm_prior_mu
    assert dance.bpm_prior_sigma == house.bpm_prior_sigma
    assert dance.bpm_hint_min == house.bpm_hint_min
    assert dance.bpm_hint_max == house.bpm_hint_max
    assert dance.expected_bands == house.expected_bands
    # The actual discriminator: dance has near-zero vocal presence, house
    # has a real target.
    assert dance.vocal_hnr_mu is not None and dance.vocal_hnr_mu < 0.10
    assert dance.vocal_fmr_mu is not None and dance.vocal_fmr_mu < 0.10
    assert house.vocal_hnr_mu is not None and house.vocal_hnr_mu > dance.vocal_hnr_mu
    assert house.vocal_fmr_mu is not None and house.vocal_fmr_mu > dance.vocal_fmr_mu


# ---- rap + r&b merged into rap_rnb (2026-08-06) ------------------------


def test_rap_and_rnb_no_longer_exist_separately() -> None:
    assert 'rap' not in PROFILES
    assert 'r&b' not in PROFILES


def test_rap_rnb_is_registered_and_discoverable() -> None:
    assert 'rap_rnb' in PROFILES
    assert 'rap_rnb' in list_profiles()
    assert 'rap_rnb' in enabled_profiles()
    assert PROFILES['rap_rnb'].enabled is True


def test_rap_rnb_bpm_prior_reflects_2026_08_10_owner_judgment_call() -> None:
    """mu moved 86.5 (the original rap/r&b merge blend) -> 85.0 the same
    day as the house-family consolidation pass -- an explicit owner
    judgment call, not fit from this session's corpus (that corpus's own
    rap/r&b sample was flagged as unrepresentative and separately found to
    carry real tactus-fold contamination -- see docs/adr/vj-system.md).
    hint_min/max unchanged, independently authored from mu/sigma."""
    p = PROFILES['rap_rnb']
    assert p.bpm_prior_mu == 85.0
    assert p.bpm_hint_min == 70.0
    assert p.bpm_hint_max == 100.0


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
    # 2026-08-09: house < tech_house no longer holds after spectral_centroid_mu
    # was recalibrated to match each profile's own expected_bands fingerprint
    # (see the field's comment in profiles.py) -- house's fingerprint now
    # implies *brighter* (2650) than tech_house's (2550), contradicting
    # tech_house's own documented "pronounced hi-hat energy 8-16 kHz" vs
    # house's "modest... moderate presence" acoustic notes. This points at a
    # data-quality question in the fingerprints themselves (deferred, not
    # fixed here -- see docs/adr/vj-system.md), not a broken assertion to
    # paper over. deep_house < both siblings still holds either way.
    assert deep_house.spectral_centroid_mu < house.spectral_centroid_mu
    assert deep_house.spectral_centroid_mu < tech_house.spectral_centroid_mu
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


# ---- hyphy/chillstep fingerprint regeneration (2026-08-06) -------------


def _cosine_sim(a, b) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb)


def test_hyphy_chillstep_similarity_improved_and_stays_bounded() -> None:
    """Regression guard against silently reverting to the old,
    near-indistinguishable arrays (0.9788 similarity) -- and against a
    future edit accidentally making them *more* similar again. Doesn't
    assert a specific 'good enough' number since cosine similarity across
    this genre cluster has an honest structural ceiling (see
    docs/adr/vj-system.md) -- just that today's regenerated pair is
    measurably better than the pre-2026-08-06 baseline."""
    hyphy = get_profile('hyphy')
    chillstep = get_profile('chillstep')
    sim = _cosine_sim(hyphy.expected_bands, chillstep.expected_bands)
    assert sim < 0.975  # was 0.9788 before the scoped regeneration


def test_hyphy_disabled_and_tightened_pending_real_library_material() -> None:
    """2026-08-10: a real 3-hour session found the recommender picking
    hyphy for real hip-hop tracks (987x) that should land on rap_rnb, and
    there are no known hyphy/trap tracks in the library to validate
    against at all -- so every hyphy pick in that data was very likely a
    false positive by construction. Disabled (still directly resolvable,
    same disable-not-delete pattern already used for 'electronic'/
    'generic' before generic's later full elimination) and tightened in
    the same pass: bpm_prior_sigma 0.20 -> 0.15, spectral_centroid_sigma
    600 (wide tier) -> 400 (medium, the dataclass default) -- 'wide' was
    never re-justified for hyphy the way it was for house's genuinely
    diverse library content. See docs/adr/vj-system.md."""
    hyphy = get_profile('hyphy')
    assert hyphy.enabled is False
    assert hyphy.name == 'Hyphy / Trap'
    assert 'hyphy' not in enabled_profiles()
    assert 'hyphy' in PROFILES   # still directly resolvable, not eliminated
    assert hyphy.bpm_prior_sigma == 0.15
    assert hyphy.spectral_centroid_sigma == 400.0
    # Band itself untouched -- tightening is about discrimination sharpness
    # within the band, not closing an overlap gap (100-118 was already
    # adjacent to house's 118-126 and rap_rnb's 70-100, not overlapping).
    assert hyphy.bpm_hint_min == 100.0
    assert hyphy.bpm_hint_max == 118.0


# ---- mu-in-hint drift canary (2026-08-10) -------------------------------
#
# bpm_prior_mu/sigma (steers the live tempo search + drives tempo_fit, the
# recommender's highest-weighted term) and bpm_hint_min/max (a display
# label + a scorecard "was the detected bpm in range" metric, currently NO
# live effect on recommendation) are independently authored -- deliberately
# NOT derived from each other. Deriving hint from sigma was considered and
# rejected: hint grades the detector, sigma steers it, so computing the
# yardstick from the steering knob would let widening the knob
# auto-improve the score with nothing having actually gotten better (the
# same failure shape as the hard-clamp bug already reverted, relocated
# into measurement instead of search). This test is the cheap alternative:
# assert the two independently-authored numbers still agree on the basic
# fact that the prior's center falls inside the display range, so a future
# edit to one without the other fails loudly instead of drifting silently.


def test_bpm_prior_mu_falls_inside_its_own_hint_range() -> None:
    for key, profile in PROFILES.items():
        if profile.bpm_hint_min is None or profile.bpm_hint_max is None:
            continue
        assert profile.bpm_hint_min <= profile.bpm_prior_mu <= profile.bpm_hint_max, (
            f'{key}: bpm_prior_mu={profile.bpm_prior_mu} falls outside '
            f'bpm_hint range [{profile.bpm_hint_min}, {profile.bpm_hint_max}]'
        )
