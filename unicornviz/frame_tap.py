"""Single-readback coordination for everything that wants the output frame.

Why this exists: recording, RTMP streaming, and the control-room/dj-mixer
preview panels all want the same rendered picture, and each used to pull it
off the GPU independently. With recording and streaming both live that was
**two full-resolution GPU->CPU readbacks of an identical frame every frame**
(one of them synchronous), and the planned interop outputs — v4l2loopback,
PipeWire, NDI — would have made it four or five. At 1080p60 each readback is
~6 MB, so the waste scales straight into the frame budget.

``FrameTap`` owns the *decision*, not the transfer: it tracks who is
subscribed, applies each subscriber's own rate cap, and reports which
subscribers are due on this frame. The caller performs **one** readback when
anybody is due and hands the same buffer to all of them.

It deliberately knows nothing about OpenGL, so the policy is testable
without a GL context.

Usage::

    tap = FrameTap()
    tap.sync('recording', active=recorder.is_recording)      # every frame
    tap.sync('preview', active=preview_open, max_fps=10.0)   # throttled

    due = tap.begin_frame(now)
    if due:
        frame = read_one_frame()          # exactly one readback
        for name in due:
            deliver(name, frame)
        tap.commit(due, now)

Zero-copy consumers (a PipeWire/DMA-BUF publisher sharing the GL texture
directly) must **not** subscribe — they never need a CPU-side frame, and
subscribing would force a readback that exists only to be thrown away.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _Subscriber:
    """One consumer's rate policy and delivery bookkeeping."""

    max_fps: float = 0.0          # 0.0 => every frame, no throttle
    last_delivery_t: float = -1e9

    def interval_s(self) -> float:
        return 0.0 if self.max_fps <= 0.0 else 1.0 / self.max_fps

    def is_due(self, now: float) -> bool:
        interval = self.interval_s()
        if interval <= 0.0:
            return True
        return (now - self.last_delivery_t) >= interval


@dataclass
class FrameTap:
    """Decide, once per frame, whether a readback is needed and for whom.

    Thread-safety: main render thread only. Subscribers hand the delivered
    buffer to their own worker threads; the tap itself never blocks.
    """

    _subs: dict[str, _Subscriber] = field(default_factory=dict)
    #: Readbacks avoided by fan-out — incremented once per extra subscriber
    #: served by a shared frame. Purely observability; surfaced in the HUD
    #: perf line so a regression to N-readbacks-per-frame is visible.
    readbacks_saved: int = 0
    #: Readbacks actually performed, for the same reason.
    readbacks_taken: int = 0

    # ---------------------------------------------------------------- subs

    def sync(self, name: str, active: bool, max_fps: float = 0.0) -> None:
        """Add, update, or drop a subscriber to match its live state.

        Idempotent and cheap enough to call every frame, which is the point:
        call sites express *"recording is on"* rather than tracking
        subscribe/unsubscribe transitions themselves.
        """
        if not active:
            self._subs.pop(name, None)
            return
        sub = self._subs.get(name)
        if sub is None:
            # New subscribers are due immediately: a preview panel that just
            # opened should not wait out a throttle interval before its
            # first picture.
            self._subs[name] = _Subscriber(max_fps=max(0.0, float(max_fps)))
        else:
            sub.max_fps = max(0.0, float(max_fps))

    def unsubscribe(self, name: str) -> None:
        self._subs.pop(name, None)

    @property
    def subscribers(self) -> tuple[str, ...]:
        return tuple(sorted(self._subs))

    @property
    def active(self) -> bool:
        return bool(self._subs)

    # --------------------------------------------------------------- frame

    def begin_frame(self, now: float) -> frozenset[str]:
        """Return the subscribers due for a frame at *now*.

        An empty set means **do not read back at all** — the most important
        result this returns, since it is the difference between an idle
        session costing nothing and costing a full frame transfer.
        """
        if not self._subs:
            return frozenset()
        return frozenset(
            name for name, sub in self._subs.items() if sub.is_due(now)
        )

    def commit(self, names: 'frozenset[str] | set[str] | tuple[str, ...]',
               now: float) -> None:
        """Record that *names* were delivered a frame at *now*."""
        count = 0
        for name in names:
            sub = self._subs.get(name)
            if sub is not None:
                sub.last_delivery_t = now
                count += 1
        if count:
            self.readbacks_taken += 1
            # The first consumer justifies the readback; every additional
            # one is a transfer that used to happen and now doesn't.
            self.readbacks_saved += count - 1

    def reset_stats(self) -> None:
        self.readbacks_saved = 0
        self.readbacks_taken = 0
