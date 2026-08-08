"""Regression tests for the 2026-08-08 performance remediation.

Covers the two core-side fixes from
docs/planning/performance-remediation-plan-2026-08-08.md: the
secondary-window present guard (which used to starve the mixer to a
quarter rate the instant the loop crossed a hardcoded 60Hz-derived
threshold), and the perf instrumentation gate (which was keyed off a
level check that could never mean what it appeared to).
"""
from __future__ import annotations

from pathlib import Path

from unicornviz.app import App, FRAME_TIME, _SUBSYS_PRESENT_MAX_SKIPS
from unicornviz.config import Config


def test_present_guard_halves_rather_than_quarters() -> None:
    """Past the threshold the mixer window must degrade to every OTHER
    frame, not one in four. At a 30fps loop the old cap meant ~7.5fps,
    which is why a general slowdown always read as 'the mixer is broken'."""
    assert _SUBSYS_PRESENT_MAX_SKIPS == 1


class _Stub:
    _subsys_present_skip_ms = App._subsys_present_skip_ms

    def __init__(self, display_index: int = 0) -> None:
        self._display_index = display_index
        self._subsys_skip_ms_cached = 0.0


def test_skip_threshold_derives_from_real_refresh(monkeypatch) -> None:
    """A 30Hz output must relax the threshold. Deriving it from a hardcoded
    60Hz put a 30Hz display permanently over budget by construction, so the
    guard fired on every single frame forever."""
    import unicornviz.app as app_mod

    class _Mode:
        refresh_rate = 30

    def _get_mode(_idx, mode):
        mode.refresh_rate = 30
        return 0

    monkeypatch.setattr(app_mod.sdl2, 'SDL_DisplayMode', _Mode, raising=False)
    monkeypatch.setattr(app_mod.sdl2, 'SDL_GetCurrentDisplayMode', _get_mode,
                        raising=False)
    stub = _Stub()
    # 30Hz -> 33.3ms interval -> 1.5x -> ~50ms, not the 25ms 60Hz figure.
    assert stub._subsys_present_skip_ms() == 1000.0 / 30.0 * 1.5


def test_fast_display_never_tightens_below_the_frame_budget(monkeypatch) -> None:
    """A 144Hz panel must not demand 10ms frames — the threshold floors at
    the 60Hz budget so a fast display cannot make the guard stricter than
    the renderer can plausibly hit."""
    import unicornviz.app as app_mod

    def _get_mode(_idx, mode):
        mode.refresh_rate = 144
        return 0

    monkeypatch.setattr(app_mod.sdl2, 'SDL_DisplayMode', type('M', (), {'refresh_rate': 144}),
                        raising=False)
    monkeypatch.setattr(app_mod.sdl2, 'SDL_GetCurrentDisplayMode', _get_mode,
                        raising=False)
    stub = _Stub()
    assert stub._subsys_present_skip_ms() == FRAME_TIME * 1000.0 * 1.5


def test_threshold_falls_back_when_sdl_cannot_answer(monkeypatch) -> None:
    import unicornviz.app as app_mod

    def _boom(*_a, **_kw):
        raise RuntimeError('no display')

    monkeypatch.setattr(app_mod.sdl2, 'SDL_GetCurrentDisplayMode', _boom,
                        raising=False)
    stub = _Stub()
    assert stub._subsys_present_skip_ms() == FRAME_TIME * 1000.0 * 1.5


def test_threshold_is_cached(monkeypatch) -> None:
    """The query must not run every frame."""
    import unicornviz.app as app_mod
    calls: list[int] = []

    def _get_mode(_idx, mode):
        calls.append(1)
        mode.refresh_rate = 60
        return 0

    monkeypatch.setattr(app_mod.sdl2, 'SDL_DisplayMode', type('M', (), {'refresh_rate': 60}),
                        raising=False)
    monkeypatch.setattr(app_mod.sdl2, 'SDL_GetCurrentDisplayMode', _get_mode,
                        raising=False)
    stub = _Stub()
    for _ in range(10):
        stub._subsys_present_skip_ms()
    assert len(calls) == 1


def test_audio_latency_defaults_to_low(tmp_path: Path) -> None:
    """Owner request 2026-08-08. beta.38 changed only a capture.py fallback
    that never fired, because Config always supplies a value."""
    cfg = Config(tmp_path / 'missing.toml')
    assert cfg.get('audio', 'latency') == 'low'


def test_set_override_changes_a_value_without_touching_the_file(tmp_path: Path) -> None:
    path = tmp_path / 'c.toml'
    path.write_text('[audio]\nlatency = "high"\n', encoding='utf-8')
    cfg = Config(path)
    assert cfg.get('audio', 'latency') == 'high'
    cfg.set_override('audio', 'latency', 'medium')
    assert cfg.get('audio', 'latency') == 'medium'
    # The owner's file is theirs; runtime choices live in runtime state.
    assert 'high' in path.read_text(encoding='utf-8')


def test_perf_frames_gate_is_a_real_config_key(tmp_path: Path) -> None:
    """The gate used to be log.isEnabledFor(DEBUG), which is True even at
    INFO because the log bands filter at the handlers — so the per-frame
    instrumentation ran in every session forever."""
    path = tmp_path / 'c.toml'
    path.write_text('[logging]\nperf_frames = true\n', encoding='utf-8')
    assert Config(path).get('logging', 'perf_frames', default=False) is True
    assert Config(tmp_path / 'none.toml').get(
        'logging', 'perf_frames', default=False) is False
