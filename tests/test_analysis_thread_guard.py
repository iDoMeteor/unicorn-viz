"""P1-5 (audit 2026-09-30): an exception in the analysis thread killed it.

``_analysis_worker`` called the silence-fallback tick, ``set_sample_rate``,
``Analyzer.process`` and ``drain_onsets`` with no guard.  Any exception ended
the daemon thread; ``get_audio_data()`` then returned the last snapshot forever
(no bass, no beats, no BPM, no Auto VJ input) and nothing noticed.  The loop
body is now guarded: the error is counted and logged once per distinct error
(then at most every 30 s with a suppressed count), the loop backs off briefly
and keeps running, and a long streak resets the analyzer.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from unicornviz.audio import manager as manager_mod
from unicornviz.audio.manager import AudioManager
from unicornviz.config import Config

sys.path.insert(0, str(Path(__file__).parent / 'fixtures'))
import audio_fake  # noqa: E402


def _until(pred, timeout: float = 6.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def manager():
    with patch('unicornviz.audio.manager.AudioCapture', audio_fake.FakeCapture):
        m = AudioManager(Config(Path('tests') / '_missing_config_for_tests.toml'))
    m.start(timeout_s=4.0)
    yield m
    m.stop()


def _alive(m: AudioManager) -> bool:
    return m._analysis_thread is not None and m._analysis_thread.is_alive()


def test_an_analyzer_exception_does_not_kill_the_thread(manager, caplog) -> None:
    real = manager._analyzer.process
    state = {'left': 5}

    def flaky(*a, **k):
        if state['left'] > 0:
            state['left'] -= 1
            raise ValueError('bad block')
        return real(*a, **k)

    manager._analyzer.process = flaky
    with caplog.at_level(logging.WARNING, logger='unicornviz.audio.manager'):
        assert _until(lambda: state['left'] == 0)
        seq = manager._publish_seq
        assert _until(lambda: manager._publish_seq > seq + 3)      # publishing again
    assert _alive(manager)
    assert manager.analysis_error_count >= 5


def test_the_same_error_is_logged_once_not_per_block(manager, caplog) -> None:
    def always(*a, **k):
        raise ValueError('same every time')

    manager._analyzer.process = always
    with caplog.at_level(logging.WARNING, logger='unicornviz.audio.manager'):
        assert _until(lambda: manager.analysis_error_count >= 30)
    lines = [r for r in caplog.records if 'analysis' in r.getMessage().lower()
             and 'same every time' in r.getMessage()]
    assert len(lines) == 1 and lines[0].levelno == logging.ERROR
    assert _alive(manager)


def test_a_different_error_is_logged_separately(manager, caplog) -> None:
    errs = iter([ValueError('first'), RuntimeError('second')])
    state = {'n': 0}
    real = manager._analyzer.process

    def two(*a, **k):
        try:
            raise next(errs)
        except StopIteration:
            return real(*a, **k)

    manager._analyzer.process = two
    with caplog.at_level(logging.WARNING, logger='unicornviz.audio.manager'):
        assert _until(lambda: manager.analysis_error_count >= 2)
    msgs = ' '.join(r.getMessage() for r in caplog.records)
    assert 'first' in msgs and 'second' in msgs and state['n'] == 0


def test_the_fallback_tick_raising_is_survived_too(manager) -> None:
    state = {'left': 3}
    real = manager._capture.maybe_fallback

    def tick():
        if state['left'] > 0:
            state['left'] -= 1
            raise OSError('probe exploded')
        real()

    manager._capture.maybe_fallback = tick
    assert _until(lambda: state['left'] == 0)
    seq = manager._publish_seq
    assert _until(lambda: manager._publish_seq > seq + 3)
    assert _alive(manager)


def test_a_long_streak_resets_the_analyzer_once(manager, monkeypatch) -> None:
    resets = []
    real_set_profile = manager._analyzer.set_profile
    monkeypatch.setattr(manager._analyzer, 'set_profile',
                        lambda p: (resets.append(p), real_set_profile(p))[1])
    real = manager._analyzer.process
    state = {'left': manager_mod.ANALYSIS_RESET_AFTER + 5}

    def flaky(*a, **k):
        if state['left'] > 0:
            state['left'] -= 1
            raise ValueError('wedged state')
        return real(*a, **k)

    manager._analyzer.process = flaky
    assert _until(lambda: state['left'] == 0, timeout=15.0)
    assert len(resets) == 1
    seq = manager._publish_seq
    assert _until(lambda: manager._publish_seq > seq + 3)


def test_stop_still_ends_the_thread_during_an_error_storm(manager) -> None:
    manager._analyzer.process = lambda *a, **k: (_ for _ in ()).throw(ValueError('x'))
    assert _until(lambda: manager.analysis_error_count >= 3)
    t0 = time.monotonic()
    manager.stop()
    assert not _alive(manager) and time.monotonic() - t0 < 3.0
