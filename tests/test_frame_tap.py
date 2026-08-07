"""Regression tests for the single-readback frame tap.

Pins the contract that makes the interop plan affordable: recording,
streaming and (later) v4l2loopback/NDI share ONE GPU->CPU readback per
frame instead of each taking their own. Before the tap, recording and
streaming both live meant two full-resolution transfers of an identical
frame every frame — one of them synchronous.
"""
from __future__ import annotations

from unicornviz.frame_tap import FrameTap


def test_idle_tap_requests_no_readback() -> None:
    """The most important result: nobody subscribed => never read back."""
    tap = FrameTap()
    assert tap.begin_frame(100.0) == frozenset()
    assert tap.active is False


def test_two_consumers_share_one_readback() -> None:
    tap = FrameTap()
    tap.sync('recording', True)
    tap.sync('streaming', True)

    due = tap.begin_frame(100.0)
    assert due == {'recording', 'streaming'}
    tap.commit(due, 100.0)

    # One readback served both consumers.
    assert tap.readbacks_taken == 1
    assert tap.readbacks_saved == 1


def test_sync_false_drops_the_subscriber() -> None:
    tap = FrameTap()
    tap.sync('recording', True)
    tap.sync('streaming', True)
    tap.sync('recording', False)          # recording stopped

    assert tap.subscribers == ('streaming',)
    assert tap.begin_frame(100.0) == {'streaming'}


def test_rate_cap_throttles_only_the_capped_subscriber() -> None:
    tap = FrameTap()
    tap.sync('streaming', True)             # uncapped: every frame
    tap.sync('preview', True, max_fps=10.0)  # 100 ms

    due = tap.begin_frame(100.0)
    assert due == {'streaming', 'preview'}   # new subscribers are due at once
    tap.commit(due, 100.0)

    # 16 ms later (one 60 fps frame): streaming due, preview throttled.
    due = tap.begin_frame(100.016)
    assert due == {'streaming'}
    tap.commit(due, 100.016)

    # Past the preview's 100 ms interval: both due again.
    due = tap.begin_frame(100.2)
    assert due == {'streaming', 'preview'}


def test_new_subscriber_is_due_immediately() -> None:
    """A preview panel that just opened shouldn't wait out an interval."""
    tap = FrameTap()
    tap.sync('preview', True, max_fps=1.0)   # 1 s interval
    assert tap.begin_frame(500.0) == {'preview'}


def test_uncommitted_frame_does_not_advance_the_clock() -> None:
    """A failed readback must not count as delivered, or a throttled
    consumer would silently skip its slot."""
    tap = FrameTap()
    tap.sync('preview', True, max_fps=10.0)
    due = tap.begin_frame(100.0)
    assert due == {'preview'}
    # readback failed -> no commit
    assert tap.begin_frame(100.001) == {'preview'}
    assert tap.readbacks_taken == 0


def test_commit_ignores_unknown_names() -> None:
    tap = FrameTap()
    tap.sync('streaming', True)
    tap.commit({'streaming', 'gone-away'}, 100.0)
    assert tap.readbacks_taken == 1
    assert tap.readbacks_saved == 0   # only one real subscriber served


def test_max_fps_change_is_applied_in_place() -> None:
    tap = FrameTap()
    tap.sync('preview', True, max_fps=10.0)
    tap.commit({'preview'}, 100.0)
    assert tap.begin_frame(100.05) == frozenset()   # 50 ms < 100 ms
    tap.sync('preview', True, max_fps=30.0)         # consumer asked for faster
    assert tap.begin_frame(100.05) == {'preview'}   # 50 ms > 33 ms


def test_three_consumers_save_two_readbacks() -> None:
    """Shape of the interop future: the more consumers, the bigger the win."""
    tap = FrameTap()
    for name in ('recording', 'streaming', 'v4l2'):
        tap.sync(name, True)
    due = tap.begin_frame(100.0)
    tap.commit(due, 100.0)
    assert tap.readbacks_taken == 1
    assert tap.readbacks_saved == 2
