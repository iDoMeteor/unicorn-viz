"""G3 (2026-09-30 hardware/GPU-run audit): Ctrl+C in a terminal crashed
shutdown.

The audio helper died of the group SIGINT first, ``_audio_manager.stop()``
raised ``HostGone`` out of ``_shutdown_runtime``, and everything after it
was skipped: relay and webcam state, MIDI close, GL/SDL teardown and the
final runtime-state save.  The stop is now guarded like the other steps.
"""
from __future__ import annotations

from unicornviz.app import App
from unicornviz.remote_objects import HostGone


class _Cfg:
    def get(self, *_args, default=None):
        return default


def _cold_app() -> App:
    app = App.__new__(App)
    app.cfg = _Cfg()
    app._shutdown_complete = False
    for name in ('_recorder', '_streamer', '_auto_vj', '_grand_finale', '_hotkeys',
                 '_control_room', '_keystroke_logger', '_midi_manager',
                 '_webcam_system', '_candy_frame', '_postfx_controller',
                 '_color_grade', '_beat_flash', '_video_postfx', '_current_effect',
                 '_next_effect', '_invert_vao', '_invert_vbo', '_invert_prog',
                 '_present_vao', '_present_vbo', '_present_prog', '_burst_vao',
                 '_burst_vbo', '_burst_prog', '_gl_context', '_window'):
        setattr(app, name, None)
    app._subsystems = {}
    app._claimed_window_handlers = {}
    app._log_deleted_effects_summary = lambda: None  # type: ignore[attr-defined]
    app._release_readback_pbos = lambda: None  # type: ignore[attr-defined]
    return app


class _DeadAudioManager:
    def stop(self) -> None:
        raise HostGone('helper process is gone')


class _State:
    saved = 0

    def save(self) -> None:
        self.saved += 1


def test_shutdown_completes_when_the_audio_helper_is_already_gone() -> None:
    app = _cold_app()
    app._audio_manager = _DeadAudioManager()
    state = _State()
    app._runtime_state = state
    midi_stopped = []
    app._midi_manager = type('M', (), {'stop': lambda self: midi_stopped.append(1)})()

    app.ensure_shutdown()                       # must not raise

    assert midi_stopped == [1]                  # the steps after the stop ran
    assert state.saved == 1
    assert app._shutdown_complete is True
