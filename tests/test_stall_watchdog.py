"""StallWatchdog: an all-thread dump when the main loop stops coming around.

The 2026-09-05 mixer-search hang ended in a force-quit, which leaves the
same zero-byte faulthandler file a clean exit does.  These tests pin the
watchdog that turns such a hang into evidence: it must fire only when
``tick()`` stops, re-arm cheaply, and actually write a dump.
"""
from __future__ import annotations

import faulthandler
import time
from pathlib import Path

import pytest

from unicornviz.stall_watchdog import StallWatchdog


@pytest.fixture(autouse=True)
def _no_leftover_timer():
    yield
    faulthandler.cancel_dump_traceback_later()


def test_tick_arms_once_then_rearms_only_after_the_interval(monkeypatch) -> None:
    calls: list[float] = []
    monkeypatch.setattr(faulthandler, 'dump_traceback_later',
                        lambda timeout, **kw: calls.append(timeout))
    wd = StallWatchdog(file=None, timeout_s=5.0, rearm_s=1.0)
    assert wd.tick(now=100.0) is True
    assert wd.tick(now=100.5) is False      # same second: no thread churn
    assert wd.tick(now=100.99) is False
    assert wd.tick(now=101.0) is True
    assert calls == [5.0, 5.0]
    assert wd.armed


def test_stop_cancels_and_a_later_tick_rearms(monkeypatch) -> None:
    armed: list[float] = []
    cancelled: list[bool] = []
    monkeypatch.setattr(faulthandler, 'dump_traceback_later',
                        lambda timeout, **kw: armed.append(timeout))
    monkeypatch.setattr(faulthandler, 'cancel_dump_traceback_later',
                        lambda: cancelled.append(True))
    wd = StallWatchdog(file=None, timeout_s=3.0)
    wd.tick(now=0.0)
    wd.stop()
    wd.stop()                                   # idempotent
    assert cancelled == [True]
    assert wd.armed is False
    assert wd.tick(now=0.1) is True             # re-arms immediately after stop
    assert len(armed) == 2


def test_a_real_stall_writes_an_all_thread_dump(tmp_path: Path) -> None:
    """End to end against the real faulthandler: no tick -> dump lands in the file."""
    path = tmp_path / 'faulthandler_test.log'
    with open(path, 'w', encoding='utf-8') as fh:
        wd = StallWatchdog(file=fh, timeout_s=0.3, rearm_s=0.05)
        wd.tick()
        time.sleep(0.8)                         # the "hang": no tick arrives
        wd.stop()
    text = path.read_text()
    assert 'Timeout (0:00:00.300000)!' in text or 'Timeout' in text
    assert 'Thread' in text and 'File' in text


def test_a_live_loop_never_dumps(tmp_path: Path) -> None:
    path = tmp_path / 'faulthandler_live.log'
    with open(path, 'w', encoding='utf-8') as fh:
        wd = StallWatchdog(file=fh, timeout_s=0.3, rearm_s=0.05)
        end = time.monotonic() + 0.8
        while time.monotonic() < end:
            wd.tick()
            time.sleep(0.02)
        wd.stop()
    assert path.read_text() == ''
