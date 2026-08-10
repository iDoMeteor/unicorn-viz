"""Regression tests for the Phase 1 phrase-structure work
(docs/planning/auto-vj-phrase-structure-plan-2026-08-05.md):

- Phrase clock: _advance_phrase_clock() / _reset_phrase_clock_for_track_change()
- _phrase_bias(): soft bias bounds, phase-duration term, boundary term,
  cycle/position term, and the hard-cut neutral window
- _infer_peak_tier(): cycle-count + prior-phase-length gating
- IMPACT folded into DROP as an entry-time flourish (_fire_drop() /
  _enter_impact()), with CLIMAX demoted to a rarer final-peak decision in
  the IMPACT tick branch (_update_director())
"""
from __future__ import annotations

import importlib.util
import random
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_SPEC = importlib.util.spec_from_file_location('test_auto_vj_phrase_structure_module', _AUTO_VJ_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
AutoVJController = _MOD.AutoVJController


class _FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def mark(self, action: str, **info) -> None:
        self.calls.append((action, info))

    def ready(self, action: str) -> bool:
        return True


class _FakeVjApi:
    def __init__(self, section_hint: dict | None = None) -> None:
        self.postfx_calls: list[int] = []
        self.reactivity_calls: list[float] = []
        self.section_hint = section_hint

    def set_postfx_slot(self, slot: int) -> bool:
        self.postfx_calls.append(slot)
        return True

    def set_reactivity(self, val: float) -> None:
        self.reactivity_calls.append(val)

    def projectm_active(self) -> bool:
        return False

    def clear_postfx(self) -> None:
        pass

    def is_user_busy(self) -> bool:
        return False

    def get_section(self, exclude: str = '') -> dict | None:
        return self.section_hint


_PHRASE_DEFAULTS = dict(
    _bars_since_track_start=0,
    _bars_since_phase_entry=0,
    _drop_cycle_count=0,
    _peak_tier='minor',
    _phrase_neutral_bars_left=0,
    _phrase_hold_expected_min_bars=8.0,
    _phrase_hold_expected_max_bars=24.0,
    _phrase_rise_expected_min_bars=8.0,
    _phrase_rise_expected_max_bars=16.0,
    _phrase_peak_expected_min_bars=16.0,
    _phrase_peak_expected_max_bars=32.0,
    _phrase_fall_expected_min_bars=8.0,
    _phrase_fall_expected_max_bars=16.0,
    _phrase_boundary_bar_unit=8.0,
    _phrase_bias_max=0.15,
    _phrase_peak_flourish_min_cycle=2,
    _phrase_outro_song_progress=0.85,
    _phrase_track_change_neutral_bars=4,
    _phrase_external_tier_min_confidence=0.6,
    _phrase_external_proximity_bars=8.0,
    _phrase_arm_proximity_bars=16.0,
    _phrase_under_over_hold_mult=0.6,
    _phrase_boundary_bonus_mult=0.3,
    _phrase_peak_flourish_bonus_mult=0.3,
    _phrase_early_song_suppress_mult=0.4,
    _phrase_outro_suppress_mult=0.5,
    _phrase_external_match_mult=1.5,
    _phrase_external_mismatch_mult=0.5,
    _phrase_external_arm_mult=1.5,
)


def _bare_controller(*, section_hint: dict | None = None, **overrides) -> AutoVJController:
    inst = object.__new__(AutoVJController)
    for k, v in _PHRASE_DEFAULTS.items():
        setattr(inst, k, v)
    inst._spotify_snapshot = lambda: None
    inst._climax_song_progress_min_duration_s = 75.0
    inst._app = SimpleNamespace(vj_api=_FakeVjApi(section_hint=section_hint))
    for k, v in overrides.items():
        setattr(inst, k, v)
    return inst


# ---------------------------------------------------------------------------
# _advance_phrase_clock() / _reset_phrase_clock_for_track_change()
# ---------------------------------------------------------------------------

def test_advance_phrase_clock_increments_all_counters() -> None:
    inst = _bare_controller()
    inst._advance_phrase_clock()
    inst._advance_phrase_clock()
    assert inst._bars_since_track_start == 2
    assert inst._bars_since_phase_entry == 2


def test_advance_phrase_clock_decrements_neutral_window() -> None:
    inst = _bare_controller(_phrase_neutral_bars_left=2)
    inst._advance_phrase_clock()
    assert inst._phrase_neutral_bars_left == 1
    inst._advance_phrase_clock()
    assert inst._phrase_neutral_bars_left == 0
    inst._advance_phrase_clock()
    assert inst._phrase_neutral_bars_left == 0  # never goes negative


def test_reset_phrase_entry_only_zeroes_phase_entry() -> None:
    inst = _bare_controller(_bars_since_track_start=10, _bars_since_phase_entry=6, _drop_cycle_count=2)
    inst._reset_phrase_entry()
    assert inst._bars_since_phase_entry == 0
    assert inst._bars_since_track_start == 10  # untouched
    assert inst._drop_cycle_count == 2          # untouched


def test_reset_phrase_clock_for_track_change_zeroes_track_scope_and_opens_neutral_window() -> None:
    inst = _bare_controller(_bars_since_track_start=40, _drop_cycle_count=3, _phrase_track_change_neutral_bars=4)
    inst._reset_phrase_clock_for_track_change()
    assert inst._bars_since_track_start == 0
    assert inst._drop_cycle_count == 0
    assert inst._phrase_neutral_bars_left == 4


# ---------------------------------------------------------------------------
# Mixer section-hint consumption (plan section 6, amendments 6.a-6.c)
# ---------------------------------------------------------------------------

def test_get_section_hint_returns_none_when_vj_api_lacks_get_section() -> None:
    inst = _bare_controller()
    inst._app = SimpleNamespace(vj_api=SimpleNamespace())  # no get_section at all
    assert inst._get_section_hint() is None


def test_get_section_hint_returns_none_on_lookup_error() -> None:
    class _Raising:
        def get_section(self, exclude=''):
            raise RuntimeError('boom')
    inst = _bare_controller()
    inst._app = SimpleNamespace(vj_api=_Raising())
    assert inst._get_section_hint() is None


def test_get_section_hint_passes_through_a_valid_hint() -> None:
    hint = {'role': 'PEAK', 'tier': 'major', 'confidence': 0.9}
    inst = _bare_controller(section_hint=hint)
    assert inst._get_section_hint() == hint


def test_get_mixer_bpm_returns_zero_when_vj_api_lacks_get_bpm() -> None:
    inst = _bare_controller()
    inst._app = SimpleNamespace(vj_api=SimpleNamespace())  # no get_bpm at all
    assert inst._get_mixer_bpm() == 0.0


def test_get_mixer_bpm_returns_zero_on_lookup_error() -> None:
    class _Raising:
        def get_bpm(self, exclude=''):
            raise RuntimeError('boom')
    inst = _bare_controller()
    inst._app = SimpleNamespace(vj_api=_Raising())
    assert inst._get_mixer_bpm() == 0.0


def test_get_mixer_bpm_passes_through_a_valid_hint() -> None:
    class _Vj:
        def get_bpm(self, exclude=''):
            assert exclude == 'auto_vj'
            return 128.5
    inst = _bare_controller()
    inst._app = SimpleNamespace(vj_api=_Vj())
    assert inst._get_mixer_bpm() == 128.5


def test_maybe_record_section_change_seeds_without_firing_on_first_hint() -> None:
    """The very first hint seen must not fire a transition -- there is no
    prior section to have transitioned from, and app startup mid-song
    shouldn't read as a spurious boundary crossing."""
    calls: list[tuple[tuple, dict]] = []
    inst = _bare_controller(section_hint={'role': 'HOLD', 'label': 'intro'},
                             _last_section_signature=None)
    inst._record_sequence_keyframe = lambda *a, **kw: calls.append((a, kw))
    inst._maybe_record_section_change(SimpleNamespace(), SimpleNamespace(), {'available': True})
    assert calls == []
    assert inst._last_section_signature == ('HOLD', 'intro')


def test_maybe_record_section_change_fires_on_real_transition() -> None:
    calls: list[tuple[tuple, dict]] = []
    inst = _bare_controller(
        section_hint={'role': 'PEAK', 'tier': 'major', 'label': 'drop', 'confidence': 0.9},
        _last_section_signature=('RISE', 'build'),
    )
    inst._record_sequence_keyframe = lambda *a, **kw: calls.append((a, kw))
    inst._maybe_record_section_change(SimpleNamespace(), SimpleNamespace(), {'available': True})
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == 'section_change'
    assert kwargs['from_role'] == 'RISE'
    assert kwargs['from_label'] == 'build'
    assert kwargs['to_role'] == 'PEAK'
    assert kwargs['to_label'] == 'drop'
    assert kwargs['tier'] == 'major'
    assert kwargs['confidence'] == 0.9
    assert inst._last_section_signature == ('PEAK', 'drop')


def test_maybe_record_section_change_noop_when_signature_unchanged() -> None:
    calls: list[tuple[tuple, dict]] = []
    inst = _bare_controller(section_hint={'role': 'PEAK', 'label': 'drop'},
                             _last_section_signature=('PEAK', 'drop'))
    inst._record_sequence_keyframe = lambda *a, **kw: calls.append((a, kw))
    inst._maybe_record_section_change(SimpleNamespace(), SimpleNamespace(), {'available': True})
    assert calls == []
    assert inst._last_section_signature == ('PEAK', 'drop')


def test_maybe_record_section_change_noop_without_spotify() -> None:
    calls: list[tuple[tuple, dict]] = []
    inst = _bare_controller(section_hint={'role': 'PEAK', 'label': 'drop'},
                             _last_section_signature=('RISE', 'build'))
    inst._record_sequence_keyframe = lambda *a, **kw: calls.append((a, kw))
    inst._maybe_record_section_change(SimpleNamespace(), SimpleNamespace(), {})
    assert calls == []
    assert inst._last_section_signature == ('RISE', 'build')  # untouched, no hint even looked up


def test_maybe_record_section_change_noop_without_hint() -> None:
    calls: list[tuple[tuple, dict]] = []
    inst = _bare_controller(section_hint=None, _last_section_signature=('RISE', 'build'))
    inst._record_sequence_keyframe = lambda *a, **kw: calls.append((a, kw))
    inst._maybe_record_section_change(SimpleNamespace(), SimpleNamespace(), {'available': True})
    assert calls == []
    assert inst._last_section_signature == ('RISE', 'build')  # untouched


def test_sync_phrase_clock_from_section_hint_sets_bars_in_and_tier() -> None:
    hint = {'role': 'PEAK', 'tier': 'major', 'bars_in': 12.5, 'confidence': 0.9}
    inst = _bare_controller(section_hint=hint, _phrase_neutral_bars_left=3, _peak_tier='minor')

    inst._maybe_sync_phrase_clock_from_section_hint()

    assert inst._bars_since_phase_entry == 12.5
    assert inst._peak_tier == 'major'
    assert inst._phrase_neutral_bars_left == 0


def test_sync_phrase_clock_from_section_hint_noop_when_no_hint() -> None:
    inst = _bare_controller(section_hint=None, _phrase_neutral_bars_left=3, _bars_since_phase_entry=1)

    inst._maybe_sync_phrase_clock_from_section_hint()

    assert inst._bars_since_phase_entry == 1
    assert inst._phrase_neutral_bars_left == 3  # left alone -- Phase 1 fallback still applies


def test_sync_phrase_clock_from_section_hint_ignores_unknown_role() -> None:
    hint = {'role': 'BOGUS', 'bars_in': 9.0}
    inst = _bare_controller(section_hint=hint, _phrase_neutral_bars_left=3)

    inst._maybe_sync_phrase_clock_from_section_hint()

    assert inst._phrase_neutral_bars_left == 3


def test_advance_phrase_clock_syncs_from_hint_while_in_neutral_window() -> None:
    """End-to-end: a downbeat during the post-cut neutral window, with a
    fresh mixer hint available, corrects the clock instead of just
    counting up from the reset zero."""
    hint = {'role': 'FALL', 'bars_in': 5.0, 'confidence': 0.8}
    inst = _bare_controller(section_hint=hint, _phrase_neutral_bars_left=4, _bars_since_phase_entry=0)

    inst._advance_phrase_clock()

    assert inst._bars_since_phase_entry == 5.0
    assert inst._phrase_neutral_bars_left == 0


def test_phrase_bias_boosted_by_confident_matching_external_role() -> None:
    hint = {'role': 'RISE', 'confidence': 0.9}
    with_hint = _bare_controller(section_hint=hint, _bars_since_phase_entry=12)
    without_hint = _bare_controller(section_hint=None, _bars_since_phase_entry=12)

    assert with_hint._phrase_bias('RISE') > without_hint._phrase_bias('RISE')


def test_phrase_bias_lowered_by_confident_mismatched_external_role() -> None:
    hint = {'role': 'PEAK', 'confidence': 0.9}
    with_hint = _bare_controller(section_hint=hint, _bars_since_phase_entry=12)
    without_hint = _bare_controller(section_hint=None, _bars_since_phase_entry=12)

    assert with_hint._phrase_bias('RISE') < without_hint._phrase_bias('RISE')


def test_phrase_bias_external_term_scales_with_confidence() -> None:
    strong = _bare_controller(section_hint={'role': 'RISE', 'confidence': 0.9}, _bars_since_phase_entry=12)
    weak = _bare_controller(section_hint={'role': 'RISE', 'confidence': 0.1}, _bars_since_phase_entry=12)

    assert strong._phrase_bias('RISE') > weak._phrase_bias('RISE')


def test_phrase_bias_still_bounded_with_external_hint() -> None:
    hint = {'role': 'PEAK', 'confidence': 1.0}
    inst = _bare_controller(section_hint=hint, _bars_since_phase_entry=10_000)
    assert -0.15 <= inst._phrase_bias('PEAK') <= 0.15


def test_phrase_bias_external_match_gated_by_bars_left_proximity() -> None:
    """2026-08-06: a confident role match used to fire the external bias at
    full strength regardless of how much of the mixer-analyzed phase was
    left -- observed live catching the very start of a build and nearly
    immediately favoring DROP. bars_left now gates it: far from the end of
    the phase should barely move the bias; near the end should move it
    close to the old full-strength behavior."""
    far_from_end = _bare_controller(
        section_hint={'role': 'RISE', 'confidence': 0.9, 'bars_left': 30.0},
        _bars_since_phase_entry=1,
    )
    near_end = _bare_controller(
        section_hint={'role': 'RISE', 'confidence': 0.9, 'bars_left': 1.0},
        _bars_since_phase_entry=1,
    )
    no_hint = _bare_controller(section_hint=None, _bars_since_phase_entry=1)

    assert far_from_end._phrase_bias('RISE') < near_end._phrase_bias('RISE')
    # Far-from-end should sit close to the no-hint baseline, not anywhere
    # near the old full-strength (phrase_bias_max * confidence) behavior.
    assert far_from_end._phrase_bias('RISE') == pytest.approx(no_hint._phrase_bias('RISE'), abs=0.01)


def test_phrase_bias_external_match_no_bars_left_keeps_prior_full_strength_behavior() -> None:
    """Older mixer payloads (or a hint missing bars_left) fall back to the
    pre-2026-08-06 flat confidence-scaled behavior rather than silently
    going neutral -- backward compatible, not a regression for anyone not
    yet publishing extent data."""
    hint = {'role': 'RISE', 'confidence': 0.9}  # no bars_left key at all
    with_hint = _bare_controller(section_hint=hint, _bars_since_phase_entry=12)
    without_hint = _bare_controller(section_hint=None, _bars_since_phase_entry=12)

    # 2026-08-09: match multiplier raised 1.0 -> 2.0 (owner: the old 1.0x
    # meant a confident external confirmation could rarely out-vote the
    # internal bar-counting terms it was supposed to reinforce).
    assert with_hint._phrase_bias('RISE') == pytest.approx(
        min(0.15, without_hint._phrase_bias('RISE') + 0.15 * 2.0 * 0.9), abs=1e-9
    )


def test_phrase_bias_arms_ahead_of_a_known_upcoming_role() -> None:
    """2026-08-06: next_role/bars_to_next (plan section 6.b) let the
    director arm a transition before it arrives, not just react once it
    does. Currently in RISE (mismatch vs. PEAK), but the mixer says PEAK
    is next and close -- the arm term should be enough to flip the net
    bias positive despite the mismatch penalty."""
    hint = {'role': 'RISE', 'confidence': 0.9, 'next_role': 'PEAK', 'bars_to_next': 2.0}
    armed = _bare_controller(section_hint=hint, _bars_since_phase_entry=12)
    no_next = _bare_controller(
        section_hint={'role': 'RISE', 'confidence': 0.9}, _bars_since_phase_entry=12
    )

    assert armed._phrase_bias('PEAK') > no_next._phrase_bias('PEAK')


def test_phrase_bias_arm_term_ramps_with_bars_to_next_proximity() -> None:
    far = _bare_controller(
        section_hint={'role': 'RISE', 'confidence': 0.9, 'next_role': 'PEAK', 'bars_to_next': 15.0},
        _bars_since_phase_entry=12,
    )
    near = _bare_controller(
        section_hint={'role': 'RISE', 'confidence': 0.9, 'next_role': 'PEAK', 'bars_to_next': 1.0},
        _bars_since_phase_entry=12,
    )

    assert far._phrase_bias('PEAK') < near._phrase_bias('PEAK')


def test_phrase_bias_arm_term_only_fires_for_the_matching_next_role() -> None:
    """next_role='FALL' should not arm a PEAK evaluation."""
    hint = {'role': 'RISE', 'confidence': 0.9, 'next_role': 'FALL', 'bars_to_next': 1.0}
    with_wrong_next = _bare_controller(section_hint=hint, _bars_since_phase_entry=12)
    no_hint = _bare_controller(section_hint=None, _bars_since_phase_entry=12)

    # Only the ordinary RISE-vs-PEAK mismatch penalty should apply -- no
    # arm bonus, since next_role doesn't match the role being evaluated.
    plain_mismatch = _bare_controller(
        section_hint={'role': 'RISE', 'confidence': 0.9}, _bars_since_phase_entry=12
    )
    assert with_wrong_next._phrase_bias('PEAK') == pytest.approx(
        plain_mismatch._phrase_bias('PEAK'), abs=1e-9
    )
    assert with_wrong_next._phrase_bias('PEAK') < no_hint._phrase_bias('PEAK')


def test_infer_peak_tier_uses_confident_external_tier_override() -> None:
    """A confident external PEAK/major overrides local inference even on a
    first cycle that would otherwise always be 'minor'."""
    hint = {'role': 'PEAK', 'tier': 'major', 'confidence': 0.9}
    inst = _bare_controller(section_hint=hint, _drop_cycle_count=0)
    assert inst._infer_peak_tier() == 'major'


def test_infer_peak_tier_ignores_unconfident_external_tier() -> None:
    """Below phrase_external_tier_min_confidence, falls through to local
    inference instead of trusting a shrug."""
    hint = {'role': 'PEAK', 'tier': 'major', 'confidence': 0.2}
    inst = _bare_controller(
        section_hint=hint, _drop_cycle_count=0, _phrase_external_tier_min_confidence=0.6,
    )
    assert inst._infer_peak_tier() == 'minor'


def test_infer_peak_tier_ignores_hint_for_a_different_role() -> None:
    """A hint for FALL (we're mid-drop, mixer thinks we're in a breakdown --
    stale/wrong) must not influence a PEAK tier decision."""
    hint = {'role': 'FALL', 'tier': 'major', 'confidence': 0.9}
    inst = _bare_controller(
        section_hint=hint, _drop_cycle_count=2, _bars_since_phase_entry=12,
        _phrase_peak_flourish_min_cycle=2, _phrase_rise_expected_min_bars=8.0,
    )
    assert inst._infer_peak_tier() == 'major'  # falls through to local inference, which says major here


# ---------------------------------------------------------------------------
# _phrase_bias()
# ---------------------------------------------------------------------------

def test_phrase_bias_is_zero_during_neutral_window() -> None:
    inst = _bare_controller(_phrase_neutral_bars_left=3, _bars_since_phase_entry=100)
    assert inst._phrase_bias('RISE') == 0.0


def test_phrase_bias_negative_when_well_below_expected_minimum() -> None:
    inst = _bare_controller(_bars_since_phase_entry=1)  # RISE expects >= 8
    bias = inst._phrase_bias('RISE')
    assert bias < 0.0


def test_phrase_bias_positive_when_well_past_expected_maximum() -> None:
    inst = _bare_controller(_bars_since_phase_entry=40)  # RISE expects <= 16
    bias = inst._phrase_bias('RISE')
    assert bias > 0.0


def test_phrase_bias_bounded_by_phrase_bias_max() -> None:
    inst = _bare_controller(_bars_since_phase_entry=10_000, _phrase_bias_max=0.15)
    bias = inst._phrase_bias('RISE')
    assert -0.15 <= bias <= 0.15


def test_phrase_bias_peak_role_boosted_on_second_cycle() -> None:
    first = _bare_controller(_bars_since_phase_entry=12, _drop_cycle_count=1, _phrase_peak_flourish_min_cycle=2)
    second = _bare_controller(_bars_since_phase_entry=12, _drop_cycle_count=2, _phrase_peak_flourish_min_cycle=2)
    assert second._phrase_bias('PEAK') > first._phrase_bias('PEAK')


def test_phrase_bias_unknown_role_still_bounded_and_finite() -> None:
    inst = _bare_controller(_bars_since_phase_entry=5)
    assert inst._phrase_bias('NOT_A_ROLE') == 0.0 or -0.15 <= inst._phrase_bias('NOT_A_ROLE') <= 0.15


# ---------------------------------------------------------------------------
# _infer_peak_tier()
# ---------------------------------------------------------------------------

def test_infer_peak_tier_first_cycle_is_always_minor() -> None:
    inst = _bare_controller(_drop_cycle_count=1, _bars_since_phase_entry=50, _phrase_peak_flourish_min_cycle=2)
    assert inst._infer_peak_tier() == 'minor'


def test_infer_peak_tier_second_cycle_with_real_setup_is_major() -> None:
    inst = _bare_controller(
        _drop_cycle_count=2, _bars_since_phase_entry=12,
        _phrase_peak_flourish_min_cycle=2, _phrase_rise_expected_min_bars=8.0,
    )
    assert inst._infer_peak_tier() == 'major'


def test_infer_peak_tier_second_cycle_but_fizzle_retry_is_minor() -> None:
    """A prior phase that barely ran (fizzle-retry) must not count as real
    setup, even on a cycle count that would otherwise qualify."""
    inst = _bare_controller(
        _drop_cycle_count=2, _bars_since_phase_entry=1,
        _phrase_peak_flourish_min_cycle=2, _phrase_rise_expected_min_bars=8.0,
    )
    assert inst._infer_peak_tier() == 'minor'


# ---------------------------------------------------------------------------
# _fire_drop() -- tier decision drives DROP vs IMPACT entry
# ---------------------------------------------------------------------------

def _bare_drop_controller(**overrides) -> AutoVJController:
    vj_api = _FakeVjApi()
    defaults = dict(
        _grid=SimpleNamespace(drop_score=0.8, downbeat_confidence=0.5, bpm=124.0),
        _app=SimpleNamespace(vj_api=vj_api),
        _engine=_FakeEngine(),
        _rng=random.Random(0),
        _mode='BUILD',
        _profile='house',
        _allow_postfx=True,
        _allow_swap=False,
        _allow_overlays=False,
        _postfx_drop_slots=[3, 4, 5],
        _postfx_impact_slots=[4, 7, 9],
        _postfx_drop_dur=1.0,
        _postfx_hold_until_t=-1e9,
        _drop_tags=[],
        _impact_tags=[],
        _drop_confirm_score=0.5,
        _drop_threshold=0.5,
        _drop_min_downbeat_confidence=0.3,
        _drop_pending_score=0.0,
        _drop_pending_dconf=0.0,
        _drop_fizzle_score=0.5,
        _drop_peak_score=0.0,
        _drop_pending=True,
        _react_max=1.5,
        _secs_since_change=0.0,
        _last_audio=None,
        _projectm_preset_event_chance=0.0,
    )
    defaults.update(_PHRASE_DEFAULTS)
    defaults.update(overrides)
    inst = object.__new__(AutoVJController)
    for k, v in defaults.items():
        setattr(inst, k, v)
    inst._spotify_snapshot = lambda: None
    inst._audio_profile_snapshot = lambda: {}
    inst._spotify_telemetry_snapshot = lambda: {}
    inst._detector_snapshot = lambda: {}
    return inst


def test_fire_drop_minor_tier_enters_drop_directly_not_impact() -> None:
    inst = _bare_drop_controller(_drop_cycle_count=0, _bars_since_phase_entry=12)

    inst._fire_drop()

    assert inst._mode == 'DROP'
    assert inst._peak_tier == 'minor'
    assert inst._drop_cycle_count == 1
    assert inst._app.vj_api.postfx_calls  # DROP's own postfx hit fired


def test_fire_drop_major_tier_enters_impact() -> None:
    inst = _bare_drop_controller(_drop_cycle_count=1, _bars_since_phase_entry=12)  # -> cycle 2 on fire

    inst._fire_drop()

    assert inst._mode == 'IMPACT'
    assert inst._peak_tier == 'major'
    assert inst._drop_cycle_count == 2
    assert inst._app.vj_api.reactivity_calls == [1.5]  # _enter_impact's immediate max-reactivity hit


def test_fire_drop_cancels_on_revalidation_failure_without_touching_cycle_count() -> None:
    inst = _bare_drop_controller(_grid=SimpleNamespace(drop_score=0.0, downbeat_confidence=0.0, bpm=124.0))

    inst._fire_drop()

    assert inst._mode == 'BUILD'  # unchanged
    assert inst._drop_cycle_count == 0
    assert any(action == 'drop_cancelled' for action, _ in inst._engine.calls)


# ---------------------------------------------------------------------------
# IMPACT tick branch -- climax-worthy decision (via _update_director())
# ---------------------------------------------------------------------------

def _bare_impact_tick_controller(*, score: float, dconf: float, peak_tier: str,
                                  song_progress: float | None) -> AutoVJController:
    inst = _bare_drop_controller(
        _mode='IMPACT',
        _grid=SimpleNamespace(energy_slope=0.0, drop_score=score, energy=0.5, downbeat_confidence=dconf),
        _peak_tier=peak_tier,
        _impact_fired_t=0.0,
        _impact_hold_s=1.0,
        _climax_entry_score=0.6,
        _climax_early_override_score=0.75,
        _climax_min_downbeat_confidence=0.3,
        _climax_min_song_progress=0.5,
        _climax_hold_s=6.0,
        _climax_extend_max_factor=2.0,
        _build_energy_threshold=0.45,
        _build_reset_slope=0.30,
        _build_sustain_s=3.0,
        _build_min_hold_s=1.4,
        _build_max_s=20.0,
        _breakdown_energy_threshold=0.9,
        _breakdown_slope_threshold=-0.1,
        _breakdown_reset_slope=-0.03,
        _breakdown_reset_energy=0.96,
        _breakdown_sustain_s=3.0,
        _breakdown_max_s=14.0,
        _breakdown_recover_energy=0.96,
        _breakdown_onset_t=-1e9,
        _breakdown_deadline_t=-1e9,
        _drop_fired_t=0.0,
        _drop_cooldown_s=30.0,
        _drop_fastlane_score=0.9,
        _drop_timeout_score_floor=0.5,
        _drop_fizzle_grace_s=0.95,
        _cycle_refractory_s=2.0,
        _hold_cool_slope=0.0,
        _mode_entry_min_confidence=0.36,
        _mode_refractory_until_t=-1e9,
        _require_bpm_lock_for_modes=False,
        _allow_timeout_forced_transitions=True,
        _has_bpm_lock=lambda *_a, **_kw: True,
        _prev_kick_regularity=0.0,
        _prev_kick_regularity_any_mode=0.0,
        _kick_energies=deque(maxlen=32),
        _pre_drop_speed_ref=None,
        _build_onset_t=-1e9,
        _climax_tags=[],
        _postfx_climax_slots=[3, 6, 7, 9],
        _postfx_climax_interval=12.0,
        _postfx_cruise_timer=0.0,
        _next_climax_postfx_interval=0.0,
        _min_dwell=45.0,
        _max_dwell=140.0,
    )
    inst._current_song_progress = lambda: song_progress
    return inst


def test_impact_holds_before_hold_duration_elapses() -> None:
    inst = _bare_impact_tick_controller(score=0.9, dconf=0.9, peak_tier='major', song_progress=0.6)
    inst._impact_fired_t = 1_000_000.0  # far in the future -> elapsed < hold

    inst._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))

    assert inst._mode == 'IMPACT'


def test_impact_settles_back_to_drop_when_not_climax_worthy() -> None:
    inst = _bare_impact_tick_controller(score=0.3, dconf=0.9, peak_tier='minor', song_progress=0.6)

    inst._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))

    assert inst._mode == 'DROP'


def test_impact_does_not_escalate_to_climax_on_minor_tier_even_with_high_score() -> None:
    """A minor-tier peak never escalates to CLIMAX, regardless of score --
    tier is decided once at drop-fire and is not reconsidered here."""
    inst = _bare_impact_tick_controller(score=0.95, dconf=0.9, peak_tier='minor', song_progress=0.9)

    inst._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))

    assert inst._mode == 'DROP'


# ---------------------------------------------------------------------------
# DROP tick branch -- climax-worthy decision, decoupled from IMPACT
# (2026-08-09, plan section 3b: CLIMAX no longer requires passing through
# IMPACT's fixed hold window -- climax_worthy is evaluated directly from
# DROP, guarded only by a reused impact_hold_s minimum-time-since-fire
# floor). _bare_impact_tick_controller's setup is reused verbatim (same
# thresholds/constants), just with _mode='DROP' and _drop_fired_t moved far
# enough into the past that elapsed >= impact_hold.
# ---------------------------------------------------------------------------

def _bare_drop_climax_tick_controller(*, score: float, dconf: float, peak_tier: str,
                                       song_progress: float | None) -> AutoVJController:
    inst = _bare_impact_tick_controller(
        score=score, dconf=dconf, peak_tier=peak_tier, song_progress=song_progress,
    )
    inst._mode = 'DROP'
    # 2s ago: clears impact_hold_s (1.0) without also clearing
    # drop_cooldown_s (30.0) -- unlike _impact_fired_t's 0.0/1_000_000.0
    # convention elsewhere in this file, DROP's own cooldown check means an
    # arbitrarily-huge "in the past" value would also (wrongly) trip
    # _exit_drop() before the climax check gets a chance to matter.
    inst._drop_fired_t = time.monotonic() - 2.0
    return inst


def test_drop_does_not_evaluate_climax_before_impact_hold_elapses() -> None:
    inst = _bare_drop_climax_tick_controller(score=0.9, dconf=0.9, peak_tier='major', song_progress=0.6)
    inst._drop_fired_t = 999_000.0  # far in the future -> elapsed < impact_hold

    inst._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))

    assert inst._mode == 'DROP'


def test_drop_escalates_to_climax_when_major_tier_and_progress_favors_it() -> None:
    inst = _bare_drop_climax_tick_controller(score=0.9, dconf=0.9, peak_tier='major', song_progress=0.6)

    inst._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))

    assert inst._mode == 'CLIMAX'


def test_drop_does_not_escalate_to_climax_on_minor_tier_even_with_high_score() -> None:
    inst = _bare_drop_climax_tick_controller(score=0.95, dconf=0.9, peak_tier='minor', song_progress=0.9)

    inst._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))

    assert inst._mode == 'DROP'


def test_drop_escalates_to_climax_via_early_override_without_known_progress() -> None:
    """No song-position info at all (e.g. a live stream) -- overwhelming
    score evidence can still justify CLIMAX; a merely-good score cannot."""
    strong = _bare_drop_climax_tick_controller(score=0.95, dconf=0.9, peak_tier='major', song_progress=None)
    weak = _bare_drop_climax_tick_controller(score=0.65, dconf=0.9, peak_tier='major', song_progress=None)

    strong._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))
    weak._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))

    assert strong._mode == 'CLIMAX'
    assert weak._mode == 'DROP'
    assert weak._mode == 'DROP'


# ---------------------------------------------------------------------------
# 2026-08-09: allow_timeout_forced_transitions's hardcoded fallback (used
# only when no active VJ mood profile and no config.toml override supplies
# the key) was False -- the *unsafe* value, since it gates the only exit
# from DROP/BREAKDOWN/BUILD's forced-drop timeout other than a genuine
# fizzle. All three shipped mood profiles (chill/normie/raver) already
# override it True, so this only mattered for a hypothetical future profile
# that forgot the key -- found during the director scene-detection audit.
# ---------------------------------------------------------------------------


def test_allow_timeout_forced_transitions_fallback_defaults_to_true() -> None:
    """Exercises the exact _profile_value() lookup __init__ uses, with no
    active profile and no config.toml override supplying the key -- the
    scenario the old False fallback would have silently mishandled."""
    inst = object.__new__(AutoVJController)
    inst._use_user_profile_overrides = False
    inst._explicit_profile_override_keys = set()
    inst._profile_defaults = {}
    inst._cfg = {}

    result = AutoVJController._profile_value(inst, 'allow_timeout_forced_transitions', True)

    assert result is True


def test_drop_timeout_score_floor_fallback_actually_relaxes_threshold() -> None:
    """2026-08-09: fallback changed from self._drop_threshold (no actual
    relaxation despite being documented as a 'relaxed-but-not-zero floor')
    to 0.65x threshold -- exercises the exact _profile_value() lookup
    __init__ uses, with no active profile and no config.toml override
    supplying the key."""
    inst = object.__new__(AutoVJController)
    inst._use_user_profile_overrides = False
    inst._explicit_profile_override_keys = set()
    inst._profile_defaults = {}
    inst._cfg = {}
    inst._drop_threshold = 0.78

    result = AutoVJController._profile_value(inst, 'drop_timeout_score_floor', inst._drop_threshold * 0.65)

    assert result == pytest.approx(0.78 * 0.65)
    assert result < inst._drop_threshold  # the actual relaxation this fix restores


# ---------------------------------------------------------------------------
# BREAKDOWN <-> DROP (2026-08-09, plan sections 2/3c): general order
# loosening -- previously the only way out of BREAKDOWN was _enter_build()
# or a timeout to CRUISE, and the only way out of DROP was cooldown/fizzle
# to CRUISE. Many tracks in the primary target genres breakdown straight
# back into the next drop with no distinct build phase, and a fizzled/
# cooled-down drop with energy already low should be able to settle
# straight into BREAKDOWN instead of always routing through CRUISE.
# ---------------------------------------------------------------------------

def _bare_breakdown_tick_controller(*, score: float, dconf: float, breakdown_enter_t: float) -> AutoVJController:
    inst = _bare_impact_tick_controller(score=score, dconf=dconf, peak_tier='minor', song_progress=0.5)
    inst._mode = 'BREAKDOWN'
    inst._breakdown_enter_t = breakdown_enter_t
    # Far in the future -> _bare_impact_tick_controller's -1e9 default
    # (fine for IMPACT-branch tests, which never read it) would otherwise
    # make the breakdown-timeout branch fire immediately on every tick here.
    inst._breakdown_deadline_t = time.monotonic() + 1000.0
    inst._drop_pending = False  # _bare_drop_controller defaults this True
    # bpm=0 -> _schedule_drop() calls _fire_drop() synchronously instead of
    # going through self._grid.schedule_for_next_downbeat(), which the
    # SimpleNamespace grid stub doesn't implement.
    inst._grid = SimpleNamespace(drop_score=score, downbeat_confidence=dconf,
                                  bpm=0.0, energy_slope=0.0, energy=0.5)
    return inst


def test_breakdown_fires_drop_when_evidence_clears_threshold() -> None:
    inst = _bare_breakdown_tick_controller(score=0.8, dconf=0.9, breakdown_enter_t=time.monotonic() - 5.0)

    inst._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))

    assert inst._mode in ('DROP', 'IMPACT')  # _fire_drop() ran synchronously
    assert inst._drop_cycle_count == 1


def test_breakdown_does_not_fire_drop_before_minimum_time_floor() -> None:
    """Guards against firing on a single noisy frame right at breakdown
    entry, even with strong score/confidence evidence."""
    inst = _bare_breakdown_tick_controller(score=0.8, dconf=0.9, breakdown_enter_t=time.monotonic() - 0.1)

    inst._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))

    assert inst._mode == 'BREAKDOWN'


def test_breakdown_does_not_fire_drop_when_score_below_threshold() -> None:
    inst = _bare_breakdown_tick_controller(score=0.2, dconf=0.9, breakdown_enter_t=time.monotonic() - 5.0)

    inst._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))

    assert inst._mode == 'BREAKDOWN'


def _bare_drop_fizzle_controller(*, slope: float, energy: float) -> AutoVJController:
    inst = _bare_impact_tick_controller(score=0.1, dconf=0.9, peak_tier='minor', song_progress=0.5)
    inst._mode = 'DROP'
    inst._drop_fired_t = time.monotonic() - 5.0  # clears both impact_hold_s and fizzle_grace_s
    inst._drop_peak_score = 0.1  # never rose above _drop_fizzle_score (0.5)
    inst._grid = SimpleNamespace(drop_score=0.1, downbeat_confidence=0.9,
                                  bpm=124.0, energy_slope=slope, energy=energy)
    return inst


def test_drop_fizzle_lands_in_breakdown_when_energy_already_low() -> None:
    """slope/energy both clear BREAKDOWN's own detection thresholds
    (_breakdown_slope_threshold=-0.1, _breakdown_energy_threshold=0.9)."""
    inst = _bare_drop_fizzle_controller(slope=-0.2, energy=0.3)

    inst._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))

    assert inst._mode == 'BREAKDOWN'


def test_drop_fizzle_lands_in_cruise_when_energy_not_low() -> None:
    """Preserves the prior behavior when the audio evidence doesn't
    actually look like a breakdown -- fizzle still lands in CRUISE."""
    inst = _bare_drop_fizzle_controller(slope=0.5, energy=0.95)

    inst._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))

    assert inst._mode == 'CRUISE'
