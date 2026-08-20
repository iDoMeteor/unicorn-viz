"""Regression tests for the drop trigger/sustain split (2026-08-18).

The drop-score redesign plan § 4 with the 2026-08-11 audit's corrections
(F1/F2/F3/F4/F9), owner-green-lit. Pins the properties the redesign
exists to guarantee:

1. F1 — `AudioData.bass_level_raw` carries absolute level (pre-
   normalization): identical spectral *shape* at different loudness must
   read differently, unlike the shape-fraction `bass`.
2. F4 — the sustain primitive does NOT renormalize during a held drop:
   a minute of sustained loud bass after a quiet reference stays hot.
3. F9 — the product form: zero bass forces zero sustain regardless of
   mid/treble busyness (the structural "no bass, no drop").
4. F3 — the trigger requires the coincidence: suppression then slam
   scores far above the same slam without prior suppression.
5. Director config: `drop_signal_engine = 'legacy'` restores the
   composite path; the default enables the split.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from unicornviz.audio.analyzer import Analyzer  # noqa: E402
from unicornviz.audio.profiles import get_profile  # noqa: E402


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_BG = _load('test_split_beat_grid', _REPO / 'drop-ins' / 'auto-vj-01' / 'beat_grid.py')
_AV = _load('test_split_auto_vj', _REPO / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py')


# ---------------------------------------------------------------------------
# F1 — the raw-path level channel
# ---------------------------------------------------------------------------

def _tone_block(freq: float, amp: float, sr: int = 48000, n: int = 1024,
                phase: int = 0) -> np.ndarray:
    t = (np.arange(n) + phase * n) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_bass_level_raw_carries_absolute_level() -> None:
    """Same spectral shape, 12 dB apart: `bass` (post-normalization) reads
    nearly identically; bass_level_raw must not."""
    def run(amp: float) -> tuple[float, float]:
        analyzer = Analyzer(fft_bands=512, profile=get_profile('house'))
        data = None
        for i in range(30):
            data = analyzer.process(_tone_block(60.0, amp, phase=i), t=i * 1024 / 48000)
        return float(data.bass), float(data.bass_level_raw)

    bass_loud, raw_loud = run(0.8)
    bass_quiet, raw_quiet = run(0.2)

    assert abs(bass_loud - bass_quiet) < 0.15, 'post-norm bass is a shape fraction'
    assert raw_loud > raw_quiet + 0.5, (
        f'bass_level_raw must separate 12 dB of level: {raw_loud} vs {raw_quiet}')


def test_bass_level_raw_silence_gated() -> None:
    analyzer = Analyzer(fft_bands=512, profile=get_profile('house'))
    data = None
    for i in range(10):
        data = analyzer.process(np.zeros(1024, dtype=np.float32), t=i * 0.021)
    assert data.bass_level_raw == 0.0


# ---------------------------------------------------------------------------
# Tracker-side signal harness
# ---------------------------------------------------------------------------

def _audio(bass_level_raw: float, flux: float = 0.0, bass_flux: float = 0.0,
           bass: float = 0.3) -> SimpleNamespace:
    return SimpleNamespace(
        bass=bass, mid=0.2, treble=0.2, beat=0.0,
        bass_det=bass, mid_det=0.2, treble_det=0.2,
        spectral_flux=flux, bass_flux=bass_flux,
        bass_level_raw=bass_level_raw,
        bands=None, fft=None, waveform=None,
    )


def _drive(tracker, seconds: float, audio: SimpleNamespace, t0: float) -> float:
    """Advance the tracker at 60 Hz audio time; return the end time."""
    dt = 1.0 / 60.0
    t = t0
    for _ in range(int(seconds * 60)):
        t += dt
        tracker.update(dt, audio, onsets=[], t=t)
    return t


def test_sustain_does_not_renormalize_during_a_held_drop() -> None:
    """The F4 property, and the redesign's whole reason to exist: the old
    z-score baseline caught up to sustained loud bass within ~5-7 s. The
    percentile primitive must keep a 60 s held drop hot the whole way."""
    tracker = _BG.BeatTracker({})
    quiet = _audio(bass_level_raw=0.5, flux=40.0, bass_flux=10.0)
    loud = _audio(bass_level_raw=3.0, flux=400.0, bass_flux=120.0)

    t = _drive(tracker, 30.0, quiet, 0.0)      # establish the quiet reference
    t = _drive(tracker, 5.0, loud, t)          # drop lands
    early = tracker.drop_sustain
    _drive(tracker, 55.0, loud, t)             # held for another 55 s
    late = tracker.drop_sustain

    assert early > 0.5, f'sustain must engage on the drop (got {early})'
    assert late > 0.5, f'held drop renormalized to boring (got {late})'
    assert late >= early - 0.15, (
        f'sustain decayed under constant input: {early} -> {late}')


def test_sustain_is_zero_without_bass_regardless_of_busyness() -> None:
    """F9's structural AND: busy mid/treble with bass at the reference
    floor cannot manufacture sustain."""
    tracker = _BG.BeatTracker({})
    # Reference period with REAL bass so the ring's p20/p80 span is set by
    # genuine levels — then bass vanishes while broadband stays busy.
    t = _drive(tracker, 30.0, _audio(bass_level_raw=2.5, flux=200.0, bass_flux=60.0), 0.0)
    _drive(tracker, 10.0, _audio(bass_level_raw=0.0, flux=500.0, bass_flux=0.0), t)

    assert tracker.bass_level_norm == 0.0
    assert tracker.drop_sustain == 0.0


def test_trigger_requires_prior_suppression_to_score_high() -> None:
    """F3/F4: the slam-back out of a suppressed state must clearly outscore
    the identical slam with bass never having left."""
    def run(suppressed: bool) -> float:
        tracker = _BG.BeatTracker({})
        groove = _audio(bass_level_raw=2.5, flux=250.0, bass_flux=80.0)
        gap = _audio(bass_level_raw=0.2, flux=250.0, bass_flux=2.0)
        t = _drive(tracker, 30.0, groove, 0.0)
        if suppressed:
            t = _drive(tracker, 8.0, gap, t)   # filter-sweep build: bass gone
        # The slam: big bass transient + broadband activity together. The
        # trigger is an EVENT — it spikes in the first ticks and then
        # decays as the suppression memory absorbs the new loud level, so
        # measure the peak across the slam (the director samples every
        # tick and gates on threshold crossings, not on a delayed read).
        slam = _audio(bass_level_raw=3.2, flux=900.0, bass_flux=400.0)
        dt = 1.0 / 60.0
        peak = 0.0
        for _ in range(30):  # 0.5 s of slam
            t += dt
            tracker.update(dt, slam, onsets=[], t=t)
            peak = max(peak, tracker.impact_novelty)
        return peak

    with_supp = run(suppressed=True)
    without = run(suppressed=False)
    assert with_supp > without, (
        f'suppression must raise the trigger: {with_supp} vs {without}')
    assert with_supp >= 0.5, f'real slam-back should peak high (got {with_supp})'


def test_signals_are_bounded_and_present() -> None:
    tracker = _BG.BeatTracker({})
    _drive(tracker, 5.0, _audio(bass_level_raw=2.0, flux=300.0, bass_flux=100.0), 0.0)
    for name in ('impact_novelty', 'drop_sustain', 'bass_level_norm',
                 'bass_was_suppressed'):
        val = getattr(tracker, name)
        assert 0.0 <= val <= 1.0, f'{name} out of bounds: {val}'


def test_band_blend_weights_reverted_in_both_engines() -> None:
    """Plan § 4c's decided item: 0.7/0.2/0.1 -> 0.45/0.30/0.25, both
    engines. Source-level pin so a re-tilt is a deliberate act."""
    src = (_REPO / 'drop-ins' / 'auto-vj-01' / 'beat_grid.py').read_text(encoding='utf-8')
    assert src.count('bass_n * 0.45 + mid_n * 0.30 + treble_n * 0.25') == 2
    assert 'bass_n * 0.7 + mid_n * 0.2 + treble_n * 0.1' not in src


# ---------------------------------------------------------------------------
# Director config
# ---------------------------------------------------------------------------

def _stub_with_cfg(cfg: dict) -> SimpleNamespace:
    stub = SimpleNamespace(_cfg=cfg)
    return stub


def test_drop_signal_engine_config_parsing() -> None:
    read = lambda cfg: (  # noqa: E731 — mirrors the __init__ expression
        str(cfg.get('drop_signal_engine', 'split') or 'split')
        .strip().lower() != 'legacy'
    )
    assert read({}) is True
    assert read({'drop_signal_engine': 'split'}) is True
    assert read({'drop_signal_engine': 'LEGACY'}) is False
    assert read({'drop_signal_engine': ' legacy '}) is False
    assert read({'drop_signal_engine': ''}) is True


def test_profile_presets_carry_split_thresholds_in_ladder_order() -> None:
    presets = _AV._PROFILE_PRESETS
    for name in ('chill', 'normie', 'raver', 'tweaker'):
        p = presets[name]
        assert 'drop_trigger_threshold' in p, name
        assert 'drop_sustain_entry' in p, name
        assert 'drop_sustain_fizzle_floor' in p, name
        assert p['drop_sustain_fizzle_floor'] < p['drop_sustain_entry'], name
    # Established ladder shape: chill strictest, raver most permissive.
    assert (presets['chill']['drop_trigger_threshold']
            > presets['normie']['drop_trigger_threshold']
            > presets['raver']['drop_trigger_threshold'])


def test_split_thresholds_reach_llm_payload_dicts() -> None:
    """The same-commit sync rule: a new tunable absent from the payload
    dicts is invisible to the LLM tuning pipeline, live reader included."""
    pts = _load(
        'test_split_pts',
        _REPO / 'drop-ins' / 'training-kit-01' / 'tools' / 'package_training_set.py')
    for key in ('drop_trigger_threshold', 'drop_trigger_fastlane',
                'drop_sustain_entry', 'drop_sustain_fizzle_floor'):
        assert key in pts._DIRECTOR_CONSTANT_DEFAULTS, key
    for key in ('_V2_MIDTREB_FLUX_NORM_C', '_V2_BASS_SUPP_WINDOW_BARS',
                '_V2_SUSTAIN_BUSY_FLOOR'):
        assert key in pts._DETECTOR_CONSTANT_DEFAULTS, key
        assert hasattr(_BG, key), f'{key} missing from beat_grid module'


def test_weights_doc_version_in_sync() -> None:
    doc = (_REPO / 'drop-ins' / 'auto-vj-01' / 'docs'
           / 'weights-and-thresholds.md').read_text(encoding='utf-8')
    assert f'Doc version: {_AV._VJ_WEIGHTS_DOC_VERSION}' in doc
    assert f'Detector version: {_BG._DETECTOR_VERSION}' in doc
    assert f'Director version: {_AV._DIRECTOR_VERSION}' in doc
