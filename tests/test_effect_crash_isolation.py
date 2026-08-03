"""Regression tests: a crashing effect must not kill the show.

Covers the crash-containment surface added for RC1:
- ``_switch_effect`` survives an effect constructor raising, and does not
  destroy the pending ``_next_effect`` until the incoming instance exists.
- ``_handle_effect_crash`` detaches/destroys the crashed instance, counts
  toward the session quarantine, and schedules recovery for the main loop.
- ``_resolve_unblocked_effect`` redirects quarantined classes via the
  playlist.
- ``_render_effect_to_current_target`` contains a raising ``render()``.
- ``ensure_shutdown`` is idempotent and tolerates a never-started runtime.

The real ``App`` methods are exercised unbound against minimal stubs — no
SDL/GL context is created.
"""
from __future__ import annotations

from typing import Any

from unicornviz.app import App


class _Cfg:
    def get(self, *keys: str, default: Any = None) -> Any:
        return default


class _OkEffect:
    NAME = 'Ok Effect'

    def __init__(self, *_a: Any, **_kw: Any) -> None:
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True

    def render(self) -> None:
        pass


class _BoomInit:
    NAME = 'Boom Init'

    def __init__(self, *_a: Any, **_kw: Any) -> None:
        raise RuntimeError('shader compile failed')


class _BoomRender(_OkEffect):
    NAME = 'Boom Render'

    def render(self) -> None:
        raise RuntimeError('GL exploded')


class _Playlist:
    def __init__(self, classes: list[type]) -> None:
        self._classes = classes
        self._i = -1

    def advance(self) -> type:
        self._i = (self._i + 1) % len(self._classes)
        return self._classes[self._i]


class _AppStub:
    """Bare attribute surface for the crash-containment methods."""

    def __init__(self) -> None:
        self.cfg = _Cfg()
        self._ctx = None
        self._width = 64
        self._height = 64
        self._effect_config_overrides: dict[str, dict] = {}
        self._effect_crash_counts: dict[str, int] = {}
        self._effect_blocklist: set[str] = set()
        self._effect_crash_recover = False
        self._current_effect: Any = None
        self._next_effect: Any = None
        self._previous_effect_name = ''
        self._invert_colors = False
        self._projectm_manager_modal_active = False
        self._effect_lock = None
        self._playlist: Any = None
        self._transition_t = 0.5

    # _instantiate for the stub mirrors App's signature but skips config
    # layering — the classes under test ignore their arguments anyway.
    def _instantiate(self, cls: type, width: int | None = None,
                     height: int | None = None) -> Any:
        return cls(self._ctx, self._width, self._height, {})

    _register_effect_crash = App._register_effect_crash
    _resolve_unblocked_effect = App._resolve_unblocked_effect
    _handle_effect_crash = App._handle_effect_crash
    _EFFECT_CRASH_LIMIT = App._EFFECT_CRASH_LIMIT


def test_switch_survives_constructor_failure() -> None:
    app = _AppStub()
    pending = _OkEffect()
    app._next_effect = pending

    App._switch_effect(app, _BoomInit)  # type: ignore[arg-type]

    # The failed switch must not have destroyed or replaced the pending effect.
    assert app._next_effect is pending
    assert pending.destroyed is False
    assert app._effect_crash_counts['_BoomInit'] == 1


def test_constructor_failure_quarantines_at_limit() -> None:
    app = _AppStub()
    App._switch_effect(app, _BoomInit)  # type: ignore[arg-type]
    App._switch_effect(app, _BoomInit)  # type: ignore[arg-type]
    assert '_BoomInit' in app._effect_blocklist


def test_quarantined_class_redirects_via_playlist() -> None:
    app = _AppStub()
    app._effect_blocklist.add('_BoomInit')
    app._playlist = _Playlist([_BoomInit, _OkEffect])

    resolved = App._resolve_unblocked_effect(app, _BoomInit)  # type: ignore[arg-type]
    assert resolved is _OkEffect


def test_quarantined_class_without_playlist_is_dropped() -> None:
    app = _AppStub()
    app._effect_blocklist.add('_BoomInit')
    assert App._resolve_unblocked_effect(app, _BoomInit) is None  # type: ignore[arg-type]


def test_handle_crash_detaches_current_and_schedules_recovery() -> None:
    app = _AppStub()
    effect = _OkEffect()
    app._current_effect = effect
    try:
        raise RuntimeError('boom')
    except RuntimeError:
        App._handle_effect_crash(app, effect, 'update')  # type: ignore[arg-type]

    assert app._current_effect is None
    assert app._effect_crash_recover is True
    assert effect.destroyed is True
    assert app._effect_crash_counts['_OkEffect'] == 1


def test_handle_crash_cancels_transition_for_next_effect() -> None:
    app = _AppStub()
    effect = _OkEffect()
    app._next_effect = effect
    try:
        raise RuntimeError('boom')
    except RuntimeError:
        App._handle_effect_crash(app, effect, 'render')  # type: ignore[arg-type]

    assert app._next_effect is None
    assert app._transition_t == 0.0
    assert app._effect_crash_recover is False  # only the current effect recovers


class _Scissor:
    """Minimal moderngl-context stand-in for the render guard test."""

    def __init__(self) -> None:
        self.viewport = (0, 0, 0, 0)
        self.scissor = None


def test_render_guard_contains_effect_crash() -> None:
    app = _AppStub()
    app._ctx = _Scissor()
    effect = _BoomRender()
    app._current_effect = effect

    def _viewport(w: int, h: int, _e: Any) -> tuple[int, int, int, int]:
        return (0, 0, w, h)

    app._effect_viewport_for_target = _viewport  # type: ignore[attr-defined]
    # Must not raise:
    App._render_effect_to_current_target(app, effect, 64, 64)  # type: ignore[arg-type]

    assert app._current_effect is None
    assert app._effect_crash_recover is True
    assert effect.destroyed is True


def test_ensure_shutdown_is_idempotent_on_cold_app() -> None:
    """ensure_shutdown() on a never-started App must not raise, and must
    only run the teardown once."""
    cfg = _Cfg()
    app = App.__new__(App)
    # Simulate the attribute surface a constructed-but-never-run App has.
    app.cfg = cfg
    app._shutdown_complete = False
    app._recorder = None
    app._streamer = None
    app._auto_vj = None
    app._grand_finale = None
    app._subsystems = {}
    app._claimed_window_handlers = {}
    app._hotkeys = None
    app._control_room = None
    app._keystroke_logger = None
    app._audio_manager = None
    app._midi_manager = None
    app._webcam_system = None
    app._candy_frame = None
    app._postfx_controller = None
    app._color_grade = None
    app._beat_flash = None
    app._current_effect = None
    app._next_effect = None
    app._invert_vao = None
    app._invert_vbo = None
    app._invert_prog = None
    app._present_vao = None
    app._present_vbo = None
    app._present_prog = None
    app._burst_vao = None
    app._burst_vbo = None
    app._burst_prog = None
    app._gl_context = None
    app._window = None

    calls = {'summary': 0, 'save': 0, 'pbo': 0}
    app._log_deleted_effects_summary = lambda: calls.__setitem__('summary', calls['summary'] + 1)  # type: ignore[attr-defined]
    app._release_readback_pbos = lambda: calls.__setitem__('pbo', calls['pbo'] + 1)  # type: ignore[attr-defined]

    class _State:
        def save(self) -> None:
            calls['save'] += 1

    app._runtime_state = _State()

    app.ensure_shutdown()
    app.ensure_shutdown()  # second call must be a no-op

    assert calls == {'summary': 1, 'save': 1, 'pbo': 1}
    assert app._shutdown_complete is True
