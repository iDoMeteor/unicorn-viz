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
  reason no longer applies -- see docs/adr/vj-system.md), then disabled
  again 2026-09-04 (its vocal-presence-discriminator control-pair job is
  done; unlike every other profile in the roster it has no distinct
  acoustic identity by design, a genuine generic rather than a genre
  pending real data -- see docs/adr/vj-system.md).
- 'rap' and 'r&b' merged into 'rap_rnb' 2026-08-06 (owner call: genuine
  siblings, 0.9856 cosine similarity, 3 BPM apart -- not a false
  catch-all pairing like fire_dj/electronic).
- The new 'deep_house' profile.
"""

from __future__ import annotations

import pytest

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
    assert 'electronic' not in enabled   # disabled again 2026-09-04, see docs/adr/vj-system.md
    assert 'hyphy' not in enabled   # re-enabled then disabled again same day 2026-09-04, see docs/adr/vj-system.md
    assert 'tech_house' not in enabled   # disabled 2026-08-11, see docs/adr/vj-system.md
    assert 'house' in enabled   # a normal enabled profile is unaffected


def test_tech_house_disabled_pending_recalibrated_library_material() -> None:
    """2026-08-11: disabled (not eliminated) -- see docs/adr/vj-system.md
    'Recommender centroid_fit Weight Cut + tech_house Disabled'. Root cause
    is the same centroid_fit formula-mismatch bug documented on
    spectral_centroid_mu (expected_bands-derived, log-band-weighted) vs.
    the live measurement (linear-FFT-weighted); tech_house sits closest of
    any profile to peak_time on bpm_prior_mu and leans on that unreliable
    axis to break the tie. Direct lookup must still resolve it (disable,
    not delete -- same pattern as hyphy)."""
    tech_house = get_profile('tech_house')
    assert tech_house.enabled is False
    assert tech_house.name == 'Tech House'
    assert 'tech_house' not in enabled_profiles()
    assert 'tech_house' in PROFILES   # still directly resolvable, not eliminated
    assert 'tech_house' not in list_profiles()   # excluded from discovery, same as hyphy


def test_default_enabled_true_for_profiles_that_dont_set_it() -> None:
    """Every profile except the explicitly-disabled ones should default to
    enabled=True without having to set it themselves.

    'generic' is gone entirely now (eliminated, not merely disabled -- see
    test_generic_uk_garage_breaks_eliminated_entirely above), so it's no
    longer in this set; 'hyphy' replaced it 2026-08-10 (disabled pending
    real trap/hyphy library material -- see docs/adr/vj-system.md);
    'tech_house' added 2026-08-11 (disabled pending recalibrated library
    material, same doc); 'techno' added 2026-09-03 (disabled on arrival --
    enabling it as a live candidate re-broke house winning its own list,
    the third recurrence of spectral_shape_fit's level-reward defect; see
    docs/adr/vj-system.md "Vocal-Term Calibration"); 'psytrance',
    'hard_techno', 'hardstyle', 'synthwave' added 2026-09-04 (recommender
    rc.29, evidence audit -- disabled for having zero training-list corpus
    of any kind, every scoring field still hand-authored/guessed; see each
    profile's own field comment and docs/adr/vj-system.md); 'electronic'
    added 2026-09-04, later the same night (disabled again -- its
    vocal-presence-discriminator control-pair job is done, and unlike the
    others it has no distinct acoustic identity by design, a genuine
    generic rather than a genre pending real data)."""
    _disabled = {'hyphy', 'tech_house', 'techno', 'psytrance', 'hard_techno',
                 'hardstyle', 'synthwave', 'electronic'}
    for key, profile in PROFILES.items():
        if key in _disabled:
            continue
        assert profile.enabled is True, f'{key} unexpectedly disabled'


def test_electronic_key_now_resolves_to_the_revived_dance_profile() -> None:
    """Dict key kept as 'electronic' for backward compatibility with any
    existing config/corpus data that references it by key -- only the
    display name and enabled state changed.

    2026-09-04: disabled again -- its vocal-presence-discriminator
    control-pair job is done (see docs/adr/vj-system.md). Direct lookup
    still resolves it, same disable-not-delete pattern as tech_house/
    techno/synthwave -- only discovery (list_profiles/enabled_profiles)
    excludes it now."""
    assert 'electronic' in PROFILES
    p = PROFILES['electronic']
    assert p.enabled is False
    assert p.name == 'Dance'
    assert 'electronic' not in list_profiles()
    assert 'electronic' not in enabled_profiles()


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


def test_deep_house_vocal_fields_now_calibrated() -> None:
    """2026-09-03 (recommender rc.27, vocal-term calibration): deep_house's
    vocal_hnr_mu/vocal_fmr_mu were previously None ("intentionally left
    uncalibrated"), but None isn't neutral in _profile_score() -- it makes
    vocal_hnr_fit/vocal_fmr_fit score exactly 0.0, a free pass no
    calibrated profile gets, which was found to be the real driver behind
    deep_house dominating unrelated lists. Now calibrated from measured
    training-deep-house-01's own median (config B -- not pooled with
    training-progressive-house-01, see profiles.py's own field comment),
    same as every other profile with a matching training list -- see
    docs/adr/vj-system.md.

    2026-09-04 (recommender rc.29): superseded by a per-track median-of-
    medians re-fit (0.5384->0.5672 / 0.3192->0.3244), which also added a
    real fitted vocal_hnr_sigma/vocal_fmr_sigma in place of the flat
    0.20/0.15 constant every profile previously shared -- see
    vocal_hnr_sigma's own field comment in profiles.py."""
    p = get_profile('deep_house')
    assert p.vocal_hnr_mu == pytest.approx(0.5672)
    assert p.vocal_fmr_mu == pytest.approx(0.3244)
    assert p.vocal_hnr_sigma == pytest.approx(0.0444)
    assert p.vocal_fmr_sigma == pytest.approx(0.0300)


# ---- hyphy/chillstep fingerprint regeneration (2026-08-06) -------------


def _cosine_sim(a, b) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb)


def test_hyphy_chillstep_no_longer_compared_by_cosine() -> None:
    """2026-09-04 (recommender rc.28, ribbon redesign): both hyphy and
    chillstep now carry expected_bands_sigma, so spectral_shape_fit scores
    them via the per-band Gaussian ribbon fit, not cosine similarity on
    expected_bands -- the pre-redesign "0.9788 near-indistinguishable
    cosine similarity" regression guard this replaces no longer describes
    what actually discriminates these two profiles. See
    docs/adr/vj-system.md "Spectral-Shape Ribbon Redesign"."""
    hyphy = get_profile('hyphy')
    chillstep = get_profile('chillstep')
    assert hyphy.expected_bands_sigma is not None
    assert chillstep.expected_bands_sigma is not None
    assert len(hyphy.expected_bands_sigma) == 64
    assert len(chillstep.expected_bands_sigma) == 64


def test_hyphy_reenabled_and_recalibrated_from_trap_hip_hop_01() -> None:
    """2026-08-10: disabled -- a real 3-hour session found the recommender
    picking hyphy for real hip-hop tracks (987x) that should land on
    rap_rnb, and there were no known hyphy/trap tracks in the library to
    validate against at all, so every hyphy pick in that data was very
    likely a false positive by construction.

    2026-09-04: RE-ENABLED. training-trap-hip-hop-01 supplies exactly the
    real material the disable reason was waiting on. Owner: "trap should
    def be on its own" -- split out of the rap_rnb pool (which now covers
    only hip-hop + rnb) into this profile.

    2026-09-04, same day, REVERTED: the bpm_prior_mu/sigma/hint recalibration
    that rode along in the same commit as the split (mu 109.0->142.2, hint
    100-118->127-155, from pooled raw *detected*-BPM on trap-hip-hop-01) was
    never approved -- owner only approved the split itself, not that tempo
    change, and pooled detector output is exactly the fold-contamination risk
    this profile's own field comment already flagged. Restored to the
    owner's own hand-tuned pre-split values (100-118 BPM, mu 109.0). See
    docs/adr/vj-system.md "Spectral-Shape Ribbon Redesign" for the split
    itself and the newer entry documenting this revert.

    2026-09-04, same day, DISABLED AGAIN: owner, direct ("disable hyphy"),
    mid smoke-test-playlist build -- the library has zero tracks ID3-tagged
    Hyphy, so this profile currently has no content of its own distinct
    from a straight trap-hip-hop-01 read. Disable-not-delete: direct lookup
    and every field below (still real, still fit from training-trap-hip-
    hop-01) is unaffected -- only discovery excludes it now."""
    hyphy = get_profile('hyphy')
    assert hyphy.enabled is False
    assert hyphy.name == 'Hyphy / Trap'
    assert 'hyphy' not in enabled_profiles()
    assert 'hyphy' in PROFILES
    assert hyphy.bpm_hint_min == 100.0
    assert hyphy.bpm_hint_max == 118.0
    assert 100.0 < hyphy.bpm_prior_mu < 120.0
    assert hyphy.expected_bands_sigma is not None
    assert len(hyphy.expected_bands_sigma) == 64


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
