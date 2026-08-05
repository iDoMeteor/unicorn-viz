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


def test_impact_escalates_to_climax_when_major_tier_and_progress_favors_it() -> None:
    inst = _bare_impact_tick_controller(score=0.9, dconf=0.9, peak_tier='major', song_progress=0.6)

    inst._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))

    assert inst._mode == 'CLIMAX'


def test_impact_does_not_escalate_to_climax_on_minor_tier_even_with_high_score() -> None:
    """A minor-tier peak never escalates to CLIMAX, regardless of score --
    tier is decided once at drop-fire and is not reconsidered here."""
    inst = _bare_impact_tick_controller(score=0.95, dconf=0.9, peak_tier='minor', song_progress=0.9)

    inst._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))

    assert inst._mode == 'DROP'


def test_impact_escalates_to_climax_via_early_override_without_known_progress() -> None:
    """No song-position info at all (e.g. a live stream) -- overwhelming
    score evidence can still justify CLIMAX; a merely-good score cannot."""
    strong = _bare_impact_tick_controller(score=0.95, dconf=0.9, peak_tier='major', song_progress=None)
    weak = _bare_impact_tick_controller(score=0.65, dconf=0.9, peak_tier='major', song_progress=None)

    strong._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))
    weak._update_director(dt=1 / 60, state=SimpleNamespace(), audio=SimpleNamespace(spectral_flux=0.0))

    assert strong._mode == 'CLIMAX'
    assert weak._mode == 'DROP'
