"""Public VJ automation API for unicorn-viz.

This module defines the stable automation surface exposed as ``App.vj_api``.
Phase 1 implementation is intentionally conservative: wrappers are added without
changing runtime behavior unless explicitly called by a controller.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from unicornviz.deck_sim import DeckSimLayout
from unicornviz.operator_panels import MAIN_PAGE, OperatorPage, OperatorPanel, sort_pages
from unicornviz.effects.registry import get_effects

if TYPE_CHECKING:
    import moderngl

    from unicornviz.app import App


VJ_API_VERSION = (1, 0, 0)

log = logging.getLogger(__name__)

__all__ = ['VJ_API_VERSION', 'VJState', 'VJApi']


@dataclass(slots=True)
class VJState:
    """Serializable snapshot of app state for automation logic."""

    effect_name: str
    playlist_mode: str
    playlist_index: int
    playlist_size: int
    auto_advance: bool
    paused: bool
    fullscreen: bool
    is_transitioning: bool
    advance_interval: float
    advance_time_remaining: float
    reactivity: float
    speed: float | None
    zoom: float | None
    audio_source: str
    invert: bool
    is_postfx_active: bool
    postfx_slot: int
    is_dancing_active: bool
    is_nova_active: bool
    is_burst_active: bool
    recording_active: bool
    streaming_active: bool
    streaming_provider: str
    display_mode: str
    display_index: int
    user_busy: bool
    manual_grace_remaining_s: float
    status_pill: str
    session_elapsed_s: float
    session_remaining_s: float | None


class VJApi:
    """Stable, public automation surface for system-driven control."""

    VERSION = VJ_API_VERSION

    # The API the running app installed. Effects are constructed with only a
    # GL context, a size and their config -- they have no handle to the App --
    # so anything effect-side that wants runtime context (song structure,
    # tempo) has no way to ask for it. This class attribute is that way in,
    # read through :meth:`current`. It is ``None`` whenever no app is running,
    # which is the normal case under tests and offscreen renders, so every
    # caller must treat the API as optional.
    _current: 'VJApi | None' = None

    def __init__(self, app: App) -> None:
        self._app = app
        VJApi._current = self
        self._key_handlers: dict[str, Callable[[int, int], 'str | None | bool']] = {}
        self._midi_action_registry: dict[str, list[tuple[str, str]]] = {}
        self._midi_action_handlers: dict[str, Callable[[], None]] = {}
        # Deck-sim (Control Room controller-mirror view) surface — see
        # unicornviz/deck_sim.py and drop-ins/control-room-01/docs/deck-sim-plan.md.
        self._deck_sim_layouts: dict[str, DeckSimLayout] = {}
        self._midi_action_colors_provider: 'Callable[[], dict[str, tuple[int, int]]] | None' = None
        self._midi_active_actions_provider: 'Callable[[], set[str]] | None' = None
        # Operator-panel registry (Control Room panels/pages a drop-in claims)
        # -- see unicornviz/operator_panels.py and
        # docs/planning/control-room-panel-registry-plan-2026-09-04.md.
        self._operator_panels: dict[str, OperatorPanel] = {}
        self._operator_pages: dict[str, OperatorPage] = {}

    @classmethod
    def current(cls) -> 'VJApi | None':
        """Return the running app's API, or ``None`` when there is no app.

        For code that cannot be handed one -- effects, above all. Callers must
        degrade gracefully rather than requiring it: there is no app under the
        test suite, offscreen renders or any standalone tool.
        """
        return cls._current

    @property
    def ctx(self) -> moderngl.Context | None:
        """Return the active moderngl context, or ``None`` before init."""
        return self._app._ctx  # noqa: SLF001

    @property
    def render_width(self) -> int:
        """Return the app's logical render width."""
        return int(self._app._width)  # noqa: SLF001

    @property
    def render_height(self) -> int:
        """Return the app's logical render height."""
        return int(self._app._height)  # noqa: SLF001

    def has_postfx(self) -> bool:
        """Return True when the post-FX controller is available."""
        return self._app._postfx_controller is not None  # noqa: SLF001

    def register_subsystem(self, name: str, subsystem: object) -> bool:
        """Register a runtime subsystem with the main app loop."""
        return self._app.register_subsystem(name, subsystem)

    def unregister_subsystem(self, name: str) -> None:
        """Unregister a runtime subsystem previously added via ``register_subsystem``."""
        self._app.unregister_subsystem(name)

    def has_subsystem(self, name: str) -> bool:
        """Return True when a named runtime subsystem is registered."""
        return self._app.has_subsystem(name)

    def get_subsystem(self, name: str) -> object | None:
        """Return a named runtime subsystem instance when registered."""
        return self._app.get_subsystem(name)

    def list_subsystems(self) -> list[str]:
        """Return the names of all currently registered runtime subsystems.

        Useful for drop-ins that need to coordinate with other subsystems at
        runtime (e.g. an automation controller checking whether streaming or
        the control room is active).
        """
        return self._app.list_subsystems()

    def register_now_playing(self, name: str, snapshot_fn, priority: int = 0,
                             ambient: bool = False) -> None:
        """Register a now-playing announcement source (track banner + HUD pane).

        *snapshot_fn* returns the shared snapshot dict (see
        :mod:`unicornviz.now_playing` for the contract).  Higher *priority*
        wins when several sources are playing (dj mixer 30, media player 20,
        spotify 10); *ambient* sources are also shown while idle.  Degrades to
        a no-op on older cores.
        """
        hub = getattr(self._app, 'now_playing', None)
        if hub is not None:
            hub.register(name, snapshot_fn, priority=priority, ambient=ambient)

    def unregister_now_playing(self, name: str) -> None:
        """Remove a now-playing source registered by this drop-in."""
        hub = getattr(self._app, 'now_playing', None)
        if hub is not None:
            hub.unregister(name)

    def active_now_playing(self) -> tuple[str, dict] | None:
        """Return ``(name, snapshot)`` for whichever now-playing source is
        currently audible, or None when nothing is registered/playing.

        Playing sources win by priority (dj mixer 30, media player 20,
        spotify 10); falls back to an ambient-available source when nothing
        is playing. See :meth:`unicornviz.now_playing.NowPlayingHub.active`.
        Degrades to None on older cores.
        """
        hub = getattr(self._app, 'now_playing', None)
        active = getattr(hub, 'active', None)
        if not callable(active):
            return None
        try:
            return active()
        except Exception:
            return None

    def set_now_spinning(self, enabled: bool) -> bool:
        """Enable/disable the core Now Spinning corner-platter overlay."""
        self._app.now_spinning_enabled = bool(enabled)
        return self._app.now_spinning_enabled

    def toggle_now_spinning(self) -> bool:
        """Flip the Now Spinning overlay; returns the new state."""
        return self.set_now_spinning(not getattr(self._app,
                                                 'now_spinning_enabled', False))

    @property
    def now_spinning_enabled(self) -> bool:
        return bool(getattr(self._app, 'now_spinning_enabled', False))

    def publish_bpm(self, source: str, bpm: float) -> None:
        """Publish a BPM estimate on the shared hint bus (under *source*).

        Tempo-aware drop-ins (dj-mixer, auto-vj, ...) publish here so others may
        read it via :meth:`get_bpm` — they interact without depending on one
        another.  Degrades to a no-op on older cores.
        """
        fn = getattr(self._app, 'publish_bpm', None)
        if callable(fn):
            fn(str(source), bpm)

    def get_bpm(self, exclude: str = '') -> float:
        """Return the freshest non-stale BPM hint from a source != *exclude*.

        Returns 0.0 when none is available.  Lets a drop-in borrow another's
        tempo as a fallback without coupling to it.
        """
        fn = getattr(self._app, 'get_bpm', None)
        return float(fn(str(exclude))) if callable(fn) else 0.0

    def publish_track_path(self, source: str, path: str) -> None:
        """Publish a local file path on the shared hint bus (under *source*).

        A source that knows a real local file for what's currently playing
        (e.g. dj-mixer-01, loading from its own crate folder) publishes
        here so an offline consumer (training-kit-01's packaging step) may
        read it via :meth:`get_track_path` and run independent analysis
        against the actual audio -- without either side depending on the
        other. Degrades to a no-op on older cores.
        """
        fn = getattr(self._app, 'publish_track_path', None)
        if callable(fn):
            fn(str(source), path)

    def get_track_path(self, exclude: str = '') -> str:
        """Return the freshest non-stale track-path hint from a source !=
        *exclude*, or '' when no usable hint exists.

        Degrades to '' on older cores.
        """
        fn = getattr(self._app, 'get_track_path', None)
        return str(fn(str(exclude))) if callable(fn) else ''

    def publish_section(self, source: str, payload: dict) -> None:
        """Publish a song-structure hint on the shared hint bus (under *source*).

        *payload* is the wire contract from
        docs/planning/auto-vj-phrase-structure-plan-2026-08-05.md section
        6.a: at minimum ``role`` (HOLD/RISE/PEAK/FALL/CLOSE), plus
        ``tier``/``label``/``bars_in``/``bars_left``/``confidence`` when
        known. A source that has pre-analyzed the whole track (dj-mixer's
        structure detector) publishes here so a phrase-aware consumer
        (auto-vj) may read it via :meth:`get_section` without either
        depending on the other. Degrades to a no-op on older cores.
        """
        fn = getattr(self._app, 'publish_section', None)
        if callable(fn):
            fn(str(source), payload)

    def get_section(self, exclude: str = '') -> dict | None:
        """Return the freshest non-stale song-structure hint from a source
        != *exclude*, or None when no usable hint exists.

        Degrades to None on older cores.
        """
        fn = getattr(self._app, 'get_section', None)
        if not callable(fn):
            return None
        result = fn(str(exclude))
        return result if isinstance(result, dict) else None

    def publish_session(self, source: str, payload: dict) -> None:
        """Publish a set-clock hint on the shared hint bus (under *source*).

        *payload* is the wire contract from
        docs/planning/auto-vj-phrase-structure-plan-2026-08-05.md section
        6.3: at minimum ``phase`` (running/closing/final/over), plus
        ``source`` (clock|last_track), ``seconds_left``/``minutes_left``,
        and finale-timing fields (``final_peak_s``/``final_peak_in_s``)
        when known. Where :meth:`get_section` says where you are in a
        *track*, this says where you are in the *night* -- the other half
        of the same question, and what the grand finale depends on.
        Degrades to a no-op on older cores.
        """
        fn = getattr(self._app, 'publish_session', None)
        if callable(fn):
            fn(str(source), payload)

    def get_session(self, exclude: str = '') -> dict | None:
        """Return the freshest non-stale set-clock hint from a source !=
        *exclude*, or None when no usable hint exists.

        Degrades to None on older cores.
        """
        fn = getattr(self._app, 'get_session', None)
        if not callable(fn):
            return None
        result = fn(str(exclude))
        return result if isinstance(result, dict) else None

    def register_playlist_sink(self, name: str, fn) -> None:
        """Register this drop-in as a destination for playlists from others.

        *fn* takes ``(playlist_name, paths)`` and returns how many tracks it
        accepted.  Lets one drop-in hand a list to another without either
        importing the other.  Degrades to a no-op on older cores.
        """
        reg = getattr(self._app, 'register_playlist_sink', None)
        if callable(reg):
            reg(str(name), fn)

    def unregister_playlist_sink(self, name: str) -> None:
        """Stop offering this drop-in as a playlist destination."""
        fn = getattr(self._app, 'unregister_playlist_sink', None)
        if callable(fn):
            fn(str(name))

    def playlist_sinks(self) -> list:
        """Names of every registered playlist destination (for a menu)."""
        fn = getattr(self._app, 'playlist_sinks', None)
        if not callable(fn):
            return []
        try:
            return list(fn())
        except Exception:                # pragma: no cover - defensive
            return []

    def export_playlist(self, target: str, name: str, paths) -> tuple:
        """Send *paths* to a registered sink as a playlist called *name*.

        Returns ``(ok, message)``; the message is written to be shown to a
        person as-is.  ``(False, ...)`` on an older core or a missing sink.
        """
        fn = getattr(self._app, 'export_playlist', None)
        if not callable(fn):
            return (False, 'this build cannot export playlists')
        try:
            return tuple(fn(str(target), str(name), list(paths or [])))
        except Exception as exc:         # pragma: no cover - defensive
            return (False, str(exc))

    def get_runtime_state(self, dotted_path: str = '', default: object | None = None) -> object:
        """Read a value from shared runtime state using dotted-path keys."""
        return self._app.get_runtime_state(str(dotted_path), default)

    def set_runtime_state(self, dotted_path: str, value: object) -> bool:
        """Set a value in shared runtime state using dotted-path keys."""
        key = str(dotted_path).strip()
        if not key:
            return False
        self._app.set_runtime_state(key, value)
        return True

    def request_exit(self, *, force: bool = False) -> bool:
        """Request the whole application to exit (graceful shutdown).

        Lets a subsystem (e.g. the dj-mixer Quit button) close unicorn-viz
        itself rather than just its own window.  Returns True if the exit was
        accepted.  A no-op returning False if the app can't be reached.
        """
        fn = getattr(self._app, 'request_exit', None)
        return bool(fn(force=force)) if callable(fn) else False

    def claim_window_events(self, window_id: int, handler) -> bool:
        """Claim SDL events for a subsystem-owned window id."""
        return self._app.claim_window_events(window_id, handler)

    def main_window_id(self) -> int:
        """SDL window id of the main (audience) window, or -1.

        A hosted subsystem claims this to receive the main window's input --
        see the mixer-only boot profile, where the console *is* the main
        window and there is no second one to claim.
        """
        win = getattr(self._app, '_window', None)
        if win is None:
            return -1
        try:
            import sdl2  # noqa: PLC0415
            return int(sdl2.SDL_GetWindowID(win))
        except Exception:                # pragma: no cover - defensive
            return -1

    def release_window_events(self, window_id: int) -> None:
        """Release SDL event ownership for a subsystem window."""
        self._app.release_window_events(window_id)

    def rebind_main_gl_context(self) -> bool:
        """Re-bind the main audience window's GL context as current.

        Subsystems that create or destroy secondary SDL windows should call this
        afterwards so any GL state implicitly migrated by the windowing system is
        restored to the audience window.  Returns True on success.
        """
        return self._app.rebind_main_gl_context()

    def dispatch_subwindow_keydown(self, sym: int, mod: int, repeat: bool = False) -> None:
        """Forward a keydown event from a subsystem-owned window to global hotkeys.

        Subsystems that claim their own SDL window (via claim_window_events)
        receive keyboard events exclusively while that window has OS input
        focus — they never reach the main app's hotkey dispatch otherwise.
        Call this for any key the subsystem doesn't handle itself, so global
        hotkeys (and modifier-key state tracked by the main app, e.g. Ctrl)
        keep working while the subsystem window has focus.
        """
        self._app.dispatch_subwindow_keydown(sym, mod, repeat)

    def dispatch_subwindow_keyup(self, sym: int) -> None:
        """Forward a keyup event from a subsystem-owned window (see dispatch_subwindow_keydown)."""
        self._app.dispatch_subwindow_keyup(sym)

    def get_frame_bytes(self) -> bytes | None:
        """Return the latest cached audience-output frame bytes, if available."""
        frame, _width, _height, _components = self._app.get_frame_capture()
        return frame

    def get_frame_size(self) -> tuple[int, int, int]:
        """Return (width, height, components) for the cached frame snapshot."""
        _frame, width, height, components = self._app.get_frame_capture()
        return width, height, components

    def state(self) -> VJState:
        app = self._app
        effect_name = '-'
        speed = None
        zoom = None
        if app._current_effect is not None:  # noqa: SLF001
            effect_name = app._current_effect.NAME  # noqa: SLF001
            if 'speed' in app._current_effect.parameters:  # noqa: SLF001
                speed = float(app._current_effect.parameters['speed'])  # noqa: SLF001
            if 'zoom' in app._current_effect.parameters:  # noqa: SLF001
                zoom = float(app._current_effect.parameters['zoom'])  # noqa: SLF001

        reactivity = 1.0
        audio_source = '-'
        if app._audio_manager is not None:  # noqa: SLF001
            reactivity = float(app._audio_manager.get_reactivity())  # noqa: SLF001
            audio_source = str(app._audio_manager.get_source_label())  # noqa: SLF001

        postfx_slot = 0
        postfx_active = False
        if app._postfx_controller is not None:  # noqa: SLF001
            postfx_active = bool(app._postfx_controller.is_active())  # noqa: SLF001
            postfx_slot = int(getattr(app._postfx_controller, 'active_slot', 0))  # noqa: SLF001

        dancing_active = False
        if app._dancing_unicorn is not None:  # noqa: SLF001
            dancing_active = bool(getattr(app._dancing_unicorn, '_active', False))  # noqa: SLF001

        nova_active = False
        if app._rainbow_nova is not None:  # noqa: SLF001
            nova_active = bool(app._rainbow_nova.is_active)  # noqa: SLF001

        burst_active = bool(app._burst_controller.active)  # noqa: SLF001
        recording_active = bool(app._recorder is not None and app._recorder.is_recording)  # noqa: SLF001
        streaming_active = bool(app._streamer is not None and app._streamer.is_streaming)  # noqa: SLF001
        streaming_provider = '-'
        if app._streamer is not None:  # noqa: SLF001
            streaming_provider = str(getattr(app._streamer, 'provider', '-'))  # noqa: SLF001

        return VJState(
            effect_name=effect_name,
            playlist_mode=str(getattr(app, '_playlist_mode', 'unknown')),  # noqa: SLF001
            playlist_index=int(getattr(app, '_playlist_index', -1)),  # noqa: SLF001
            playlist_size=int(getattr(app, '_playlist_size', 0)),  # noqa: SLF001
            auto_advance=bool(app._auto_advance),  # noqa: SLF001
            paused=bool(app._paused),  # noqa: SLF001
            fullscreen=bool(app._fullscreen),  # noqa: SLF001
            is_transitioning=bool(app._next_effect is not None),  # noqa: SLF001
            advance_interval=float(app._effect_duration),  # noqa: SLF001
            advance_time_remaining=max(0.0, float(app._effect_duration - app._demo_timer)),  # noqa: SLF001
            reactivity=reactivity,
            speed=speed,
            zoom=zoom,
            audio_source=audio_source,
            invert=bool(app._invert_colors),  # noqa: SLF001
            is_postfx_active=postfx_active,
            postfx_slot=postfx_slot,
            is_dancing_active=dancing_active,
            is_nova_active=nova_active,
            is_burst_active=burst_active,
            recording_active=recording_active,
            streaming_active=streaming_active,
            streaming_provider=streaming_provider,
            display_mode=str(getattr(app, '_display_mode', 'single')),  # noqa: SLF001
            display_index=int(getattr(app, '_display_index', 0)),  # noqa: SLF001
            user_busy=self.is_user_busy(),
            manual_grace_remaining_s=max(0.0, float(app._user_action_deadline - time.monotonic())),  # noqa: SLF001
            status_pill=str(getattr(app, '_vj_status_pill', '')),  # noqa: SLF001
            session_elapsed_s=float(self.get_elapsed_time()),
            session_remaining_s=self.get_time_remaining(),
        )

    @staticmethod
    def _resolve_effect_class(target: 'str | type') -> type | None:
        """Resolve a display-name/class-name string or class object to an
        effect class, or None if a string target matches nothing."""
        if isinstance(target, type):
            return target
        name = str(target).strip().lower()
        if not name:
            return None
        for cls in get_effects():
            if cls.NAME.lower() == name or cls.__name__.lower() == name:
                return cls
        return None

    def goto_effect(self, target: 'str | type') -> bool:
        """Navigate to a named or class-referenced effect.

        ``target`` may be a display-name/class-name string or a class object.
        """
        cls = self._resolve_effect_class(target)
        if cls is None:
            return False
        self._app.goto_effect(cls)
        return True

    def pin_effect_pair(self, target_a: 'str | type', target_b: 'str | type') -> bool:
        """Instantiate and hold two named/class-referenced effects alive for
        hard-cut ping-pong alternation -- see ``App.pin_effect_pair()``.

        Cheaper than repeated ``goto_effect()`` calls between the same two
        effects: each swap after this becomes a pointer assignment
        (``cut_to_pinned_effect()``) instead of a full instantiate+destroy
        transition. Returns False if either target doesn't resolve to a
        known effect class, or the app-level pin fails (pair already
        pinned, ProjectM manager open, instantiation error).
        """
        cls_a = self._resolve_effect_class(target_a)
        cls_b = self._resolve_effect_class(target_b)
        if cls_a is None or cls_b is None:
            return False
        return self._app.pin_effect_pair(cls_a, cls_b)

    def cut_to_pinned_effect(self, which: str) -> bool:
        """Hard-cut to the pinned 'a' or 'b' effect -- see
        ``App.cut_to_pinned()``. Returns False if no pair is pinned."""
        return self._app.cut_to_pinned(which)

    def unpin_effect_pair(self) -> None:
        """Release the pinned effect pair -- see
        ``App.unpin_effect_pair()``."""
        self._app.unpin_effect_pair()

    def lock_effect(self, name: str) -> None:
        """Pin the system to the effect with display NAME *name* (ProjectM-only
        mode / future effects-browser 'pin'). Does not itself switch effects."""
        self._app.lock_effect(name)

    def unlock_effect(self) -> None:
        """Clear any effect lock so normal rotation resumes."""
        self._app.unlock_effect()

    @property
    def effect_lock(self) -> 'str | None':
        """Display NAME of the locked effect, or None when not locked."""
        return self._app.effect_lock

    def toggle_projectm_only(self) -> tuple[bool, str]:
        """Toggle ProjectM-only mode; returns (is_on, status message)."""
        return self._app.toggle_projectm_only()

    def find_effect(self, class_name: str, display_name: str | None = None) -> type | None:
        """Return the effect class matching *class_name* or (optionally) *display_name*.

        Returns ``None`` when no matching effect is registered.
        """
        for cls in get_effects():
            if cls.__name__ == class_name or (display_name and cls.NAME == display_name):
                return cls
        return None

    def show_splash(self) -> None:
        """Replay the startup splash sequence."""
        self._app.show_splash()  # noqa: SLF001

    def projectm_available(self) -> bool:
        """Return True when ProjectM is registered *and* operator-enabled.

        The enablement half matters: Auto VJ's projectM-affinity path calls
        ``goto_effect('ProjectM Presets')`` directly, and a direct goto bypasses
        the playlist's disabled set (which only gates auto-rotation).  Without
        checking here, disabling ProjectM in the effects browser did not stop
        the director from pulling it back up.
        """
        if self.find_effect('ProjectMEffect', 'ProjectM Presets') is None:
            return False
        return self.effect_enabled('ProjectM Presets') and self.effect_enabled('ProjectMEffect')

    def effect_enabled(self, name: str) -> bool:
        """Return whether *name* (display or class name) is operator-enabled."""
        try:
            return bool(self._app.effect_enabled(str(name)))
        except Exception:                      # pragma: no cover - defensive
            return True

    # -- Effects-browser favorites --------------------------------------------
    # Marked in the effects browser (F key), capped at App.MAX_FAVORITE_EFFECTS
    # (16) and auto-assigned to the lowest free slot -- built for a future
    # 1:1 mapping onto a 16-pad MIDI grid (e.g. an Akai APC mini's clip-launch
    # pads). A pad controller reads/writes favorites entirely through this
    # surface, never through App._favorite_effects directly (see CLAUDE.md
    # "Public Runtime Surface Rules").

    def favorite_effects(self) -> dict[int, str]:
        """Return the current favorite slots ({slot: effect name}, 0-15)."""
        try:
            return dict(self._app.favorite_effects())
        except Exception:                      # pragma: no cover - defensive
            return {}

    def favorite_slot_for(self, name: str) -> 'int | None':
        """Return the slot index *name* is favorited into, or None."""
        try:
            return self._app.favorite_slot_for(str(name))
        except Exception:                      # pragma: no cover - defensive
            return None

    def is_favorite(self, name: str) -> bool:
        """Return whether *name* currently holds a favorite slot."""
        return self.favorite_slot_for(name) is not None

    def toggle_favorite(self, name: str) -> tuple[bool, str]:
        """Toggle *name*'s favorite status. Returns (is_favorite_now, msg)."""
        try:
            return self._app.toggle_favorite(str(name))
        except Exception:                      # pragma: no cover - defensive
            return False, 'Favorites unavailable'

    def goto_favorite_slot(self, slot: int) -> bool:
        """Navigate to whichever effect currently occupies *slot* (0-15).

        Convenience for a MIDI pad handler: resolves the slot to an effect
        name and calls ``goto_effect()``. Returns False if the slot is
        empty or out of range.
        """
        favorites = self.favorite_effects()
        name = favorites.get(int(slot))
        if not name:
            return False
        return self.goto_effect(name)

    def projectm_active(self) -> bool:
        """Return True when ProjectMEffect is the currently displayed effect."""
        try:
            inst = self._app._current_effect  # noqa: SLF001
            return inst is not None and type(inst).__name__ == 'ProjectMEffect'
        except Exception:
            return False

    def projectm_preset_count(self) -> int:
        """Return the number of loaded projectM presets (0 when not active or unavailable)."""
        try:
            inst = self._app._current_effect  # noqa: SLF001
            if inst is None or type(inst).__name__ != 'ProjectMEffect':
                return 0
            return int(getattr(inst, 'preset_count', 0) or 0)
        except Exception:
            return 0

    def projectm_next_preset(self) -> str | None:
        """Advance to the next projectM preset; returns label or None."""
        try:
            inst = self._app._current_effect  # noqa: SLF001
            if inst is None or type(inst).__name__ != 'ProjectMEffect':
                return None
            return inst.next_preset()  # type: ignore[union-attr]
        except Exception:
            return None

    def projectm_prev_preset(self) -> str | None:
        """Step to the previous projectM preset; returns label or None."""
        try:
            inst = self._app._current_effect  # noqa: SLF001
            if inst is None or type(inst).__name__ != 'ProjectMEffect':
                return None
            return inst.prev_preset()  # type: ignore[union-attr]
        except Exception:
            return None

    def projectm_random_preset(self) -> str | None:
        """Jump to a random projectM preset; returns label or None."""
        try:
            inst = self._app._current_effect  # noqa: SLF001
            if inst is None or type(inst).__name__ != 'ProjectMEffect':
                return None
            return inst.random_preset()  # type: ignore[union-attr]
        except Exception:
            return None

    def projectm_goto_preset(self, index: int) -> str | None:
        """Go to a specific preset by index; returns label or None."""
        try:
            inst = self._app._current_effect  # noqa: SLF001
            if inst is None or type(inst).__name__ != 'ProjectMEffect':
                return None
            return inst.goto_preset(int(index))  # type: ignore[union-attr]
        except Exception:
            return None

    def is_effect_enabled(self, name: str) -> bool:
        """Return whether an effect (by display or class name) is rotation-enabled."""
        return self._app.effect_enabled(name)

    def enabled_effect_classes(self) -> list[type]:
        """Return auto-rotatable effect classes: operator-enabled and not
        AUTO_ROTATE=False (manual-only effects are excluded from auto-selection)."""
        return [
            cls for cls in get_effects()
            if getattr(cls, 'AUTO_ROTATE', True) and self._app.effect_enabled(cls.NAME)
        ]

    def goto_random_effect(self, tags: list[str] | None = None, exclude_current: bool = True) -> str | None:
        # Only auto-select effects the operator has left enabled.
        effects = self.enabled_effect_classes()
        if exclude_current and self._app._current_effect is not None:  # noqa: SLF001
            cur_name = self._app._current_effect.__class__.__name__  # noqa: SLF001
            effects = [cls for cls in effects if cls.__name__ != cur_name]
        base_effects = effects  # enabled set before tag filtering
        if tags:
            tag_set = {t.lower() for t in tags}
            filtered: list[type] = []
            for cls in effects:
                cls_tags = {str(t).lower() for t in getattr(cls, 'TAGS', [])}
                if cls_tags & tag_set:
                    filtered.append(cls)
            # Fallback: if no *enabled* effect carries any requested tag, don't
            # strand the director on the current effect — pick from any enabled
            # effect so under-tagged effects still get airtime instead of the
            # scene silently collapsing to whatever handful happens to match.
            effects = filtered if filtered else base_effects
        if not effects:
            return None
        cls = self._app._rng.choice(effects)  # noqa: SLF001
        self._app.goto_effect(cls)
        return cls.NAME

    def list_effects(self) -> list[tuple[str, list[str]]]:
        # Sourced from the shared catalog helper so the control-room list and the
        # effects browser modal stay in lockstep (same order, same tags).
        from unicornviz.effects.registry import browser_entries
        return [(e.name, list(e.tags)) for e in browser_entries()]

    def get_audio_sources(self) -> list[str]:
        """Return available audio capture source labels."""
        try:
            return self._app.get_audio_sources()
        except Exception:
            return []

    def get_audio_source_index(self) -> int:
        """Return the currently active audio source index."""
        try:
            return int(self._app.get_audio_source_index())
        except Exception:
            return 0

    def get_audio_source_viable_flags(self) -> list[bool]:
        """Return current per-source viability flags for audio selector UIs."""
        try:
            return [bool(v) for v in self._app.get_audio_source_viable_flags()]
        except Exception:
            return []

    def select_audio_source(self, index: int) -> str:
        """Select a specific audio source index and return status text."""
        try:
            return str(self._app.select_audio_source(int(index)))
        except Exception:
            return 'Audio source selection failed'

    def toggle_audio_source_viable(self, index: int) -> str:
        """Toggle viability for an audio source row and return status text."""
        try:
            return str(self._app.toggle_audio_source_viable(int(index)))
        except Exception:
            return 'Audio source viability update failed'

    def sync_audio_selector(self) -> None:
        """Refresh overlay audio-selector rows from current runtime source state."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            overlays.set_audio_sources(
                self._app.get_audio_sources(),
                self._app.get_audio_source_index(),
                self._app.get_audio_source_viable_flags(),
            )
        except Exception:
            return

    def close_audio_selector(self) -> None:
        """Close the audio selector overlay when currently open."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if bool(getattr(overlays, 'audio_selector_visible', False)):
                overlays.toggle_audio_selector()
        except Exception:
            return

    def open_audio_selector(self) -> bool:
        """Open the audio selector overlay and sync its row state."""
        try:
            self.sync_audio_selector()
            overlays = self._app._overlays  # noqa: SLF001
            if not bool(getattr(overlays, 'audio_selector_visible', False)):
                overlays.toggle_audio_selector()
            return True
        except Exception:
            return False

    def set_audio_selector_index(self, index: int) -> int:
        """Set highlighted audio selector row and return clamped index."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            setter = getattr(overlays, 'set_audio_selected_index', None)
            if callable(setter):
                return int(setter(int(index)))
        except Exception:
            pass
        return 0

    def get_audio_selector_index(self) -> int:
        """Return highlighted audio selector row index."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            getter = getattr(overlays, 'get_audio_selected_index', None)
            if callable(getter):
                return int(getter())
        except Exception:
            pass
        return 0

    def sync_midi_selector(self) -> None:
        """Refresh overlay MIDI-selector rows from current runtime port state."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            current = ''
            manager = getattr(self._app, '_midi_manager', None)  # noqa: SLF001
            if manager is not None:
                current = str(getattr(manager, 'port_name', '') or '')
            overlays.set_midi_ports(self._app.get_midi_ports(), current)
        except Exception:
            return

    def close_midi_selector(self) -> None:
        """Close the MIDI selector overlay when currently open."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if bool(getattr(overlays, 'midi_selector_visible', False)):
                overlays.toggle_midi_selector()
        except Exception:
            return

    def open_midi_selector(self) -> bool:
        """Open the MIDI selector overlay and sync its row state."""
        try:
            self.sync_midi_selector()
            overlays = self._app._overlays  # noqa: SLF001
            if not bool(getattr(overlays, 'midi_selector_visible', False)):
                overlays.toggle_midi_selector()
            return True
        except Exception:
            return False

    def set_midi_selector_index(self, index: int) -> int:
        """Set highlighted MIDI selector row and return clamped index."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            setter = getattr(overlays, 'set_midi_selected_index', None)
            if callable(setter):
                return int(setter(int(index)))
        except Exception:
            pass
        return 0

    def get_midi_selector_index(self) -> int:
        """Return highlighted MIDI selector row index."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            getter = getattr(overlays, 'get_midi_selected_index', None)
            if callable(getter):
                return int(getter())
        except Exception:
            pass
        return 0

    def select_midi_device(self, port_name: str) -> str:
        """Select a MIDI input device by name (empty string disables MIDI)."""
        try:
            return str(self._app.select_midi_device(str(port_name)))
        except Exception:
            return 'MIDI selection failed'

    def close_webcam_editor_modal(self) -> None:
        """Close the webcam editor overlay modal when currently open."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if bool(getattr(overlays, 'webcam_editor_modal_visible', False)):
                overlays.toggle_webcam_editor_modal()
        except Exception:
            return

    def open_webcam_editor_modal(self) -> bool:
        """Open the webcam editor overlay modal."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if not bool(getattr(overlays, 'webcam_editor_modal_visible', False)):
                overlays.toggle_webcam_editor_modal()
            return True
        except Exception:
            return False

    def close_system_monitor_modal(self) -> None:
        """Close system monitor overlay modal when currently open."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if bool(getattr(overlays, 'system_monitor_modal_visible', False)):
                overlays.toggle_system_monitor_modal()
        except Exception:
            return

    def open_system_monitor_modal(self) -> bool:
        """Open system monitor overlay modal."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if not bool(getattr(overlays, 'system_monitor_modal_visible', False)):
                overlays.toggle_system_monitor_modal()
            return True
        except Exception:
            return False

    def close_controller_help_modal(self) -> None:
        """Close controller help overlay modal when currently open."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if bool(getattr(overlays, 'controller_help_modal_visible', False)):
                overlays.toggle_controller_help_modal()
        except Exception:
            return

    def open_controller_help_modal(self) -> bool:
        """Open controller help overlay modal."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if not bool(getattr(overlays, 'controller_help_modal_visible', False)):
                overlays.toggle_controller_help_modal()
            return True
        except Exception:
            return False

    def close_projectm_manager(self) -> None:
        """Close the ProjectM manager overlay modal when currently open."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if bool(getattr(overlays, 'projectm_manager_visible', False)):
                overlays.toggle_projectm_manager()
        except Exception:
            return

    def open_projectm_manager(self) -> bool:
        """Open the ProjectM manager overlay modal and sync manager catalog."""
        try:
            self.sync_projectm_manager()
            overlays = self._app._overlays  # noqa: SLF001
            if not bool(getattr(overlays, 'projectm_manager_visible', False)):
                overlays.toggle_projectm_manager()
            return True
        except Exception:
            return False

    def open_effects_browser(self) -> bool:
        """Open the effects browser modal (keyboard + mouse, live preview)."""
        try:
            self._app.open_effects_browser()
            return True
        except Exception:
            return False

    def effects_browser_active(self) -> bool:
        """Return whether the effects browser modal is open."""
        return bool(getattr(self._app, 'effects_browser_active', False))

    def open_presets(self) -> bool:
        """Open the show-presets modal."""
        try:
            self._app.open_presets()
            return True
        except Exception:
            return False

    def presets_active(self) -> bool:
        """Return whether the show-presets modal is open."""
        try:
            return bool(self._app.presets_modal_active)
        except Exception:
            return False

    def toggle_help_overlay(self) -> bool:
        """Toggle help overlay visibility; returns new visible state when known."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            overlays.toggle_help()
            return bool(getattr(overlays, 'help_visible', False))
        except Exception:
            return False

    def toggle_hud_overlay(self) -> bool:
        """Toggle HUD/name overlay visibility; returns new visible state when known."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            overlays.toggle_name_overlay()
            return bool(getattr(overlays, 'name_overlay_visible', False))
        except Exception:
            return False

    def close_help_overlay(self) -> None:
        """Close help overlay when currently visible."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if bool(getattr(overlays, 'help_visible', False)):
                overlays.toggle_help()
        except Exception:
            return

    def help_move_focus(self, delta: int) -> bool:
        """Move help section focus by delta; returns True if overlays support it."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            return bool(overlays.move_help_focus(int(delta)))
        except Exception:
            return False

    def help_set_focus(self, index: int) -> bool:
        """Set help section focus to a specific index."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            n = int(getattr(overlays, 'help_section_count', lambda: 0)())
            if 0 <= index < n:
                overlays.move_help_focus(index - overlays._help_focus_idx)  # noqa: SLF001
                return True
            return False
        except Exception:
            return False

    def close_hud_overlay(self) -> None:
        """Close HUD/name overlay when currently visible."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if bool(getattr(overlays, 'name_overlay_visible', False)):
                overlays.toggle_name_overlay()
        except Exception:
            return

    def system_telemetry_snapshot(self) -> dict[str, float]:
        """Return current system telemetry for operator surfaces."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            sample = getattr(overlays, '_sample_system_telemetry', None)
            if callable(sample):
                sample()
            return {
                'cpu': float(getattr(overlays, '_sysmon_cpu', 0.0) or 0.0),
                'ram': float(getattr(overlays, '_sysmon_ram', 0.0) or 0.0),
                'swap': float(getattr(overlays, '_sysmon_swap', 0.0) or 0.0),
                'disk_mbs': float(getattr(overlays, '_sysmon_disk_mbs', 0.0) or 0.0),
                'net_mbs': float(getattr(overlays, '_sysmon_net_mbs', 0.0) or 0.0),
                'fps': float(getattr(self._app, '_last_frame_fps', 0.0) or 0.0),
            }
        except Exception:
            return {
                'cpu': 0.0,
                'ram': 0.0,
                'swap': 0.0,
                'disk_mbs': 0.0,
                'net_mbs': 0.0,
                'fps': 0.0,
            }

    def auto_vj_snapshot(self) -> dict[str, object]:
        """Return Auto VJ runtime state for operator/control-room surfaces."""
        try:
            auto_vj = getattr(self._app, '_auto_vj', None)  # noqa: SLF001
            # The HUD state dict lives on Overlays (App only writes it via
            # overlays.set_hud_state), not on App -- reading App._hud_state
            # always yielded {} and blanked mood/scene/bpm on the CR panel.
            overlays = getattr(self._app, '_overlays', None)  # noqa: SLF001
            hud = getattr(overlays, '_hud_state', {}) if overlays is not None else {}  # noqa: SLF001
            if not isinstance(hud, dict):
                hud = {}
            available = auto_vj is not None
            return {
                'available': bool(available),
                'enabled': bool(getattr(auto_vj, 'enabled', False)) if available else False,
                'status': str(getattr(auto_vj, 'status_text', 'AUTO VJ OFF')) if available else 'AUTO VJ UNAVAILABLE',
                'profile': str(getattr(auto_vj, '_profile', '-')) if available else '-',  # noqa: SLF001
                'mode': str(getattr(auto_vj, '_mode', '-')) if available else '-',  # noqa: SLF001
                'mood': str(hud.get('auto_vj_mood', '-') or '-'),
                'scene': str(hud.get('auto_vj_scene', '-') or '-'),
                'bpm': str(hud.get('auto_vj_bpm', '--') or '--'),
                'action_in': str(hud.get('auto_vj_action_in', '--') or '--'),
                'audio_profile': str(hud.get('audio_profile', '-') or '-'),
                'audio_profile_reco': str(hud.get('audio_profile_reco', '-') or '-'),
                'audio_profile_score': str(hud.get('audio_profile_score', '') or ''),
            }
        except Exception:
            return {
                'available': False,
                'enabled': False,
                'status': 'AUTO VJ UNAVAILABLE',
                'profile': '-',
                'mode': '-',
                'mood': '-',
                'scene': '-',
                'bpm': '--',
                'action_in': '--',
                'audio_profile': '-',
                'audio_profile_reco': '-',
                'audio_profile_score': '',
            }

    def sync_projectm_manager(self) -> bool:
        """Refresh ProjectM manager entries from the active effect and return success."""
        try:
            manager_effect = self._app.resolve_projectm_manager_effect()
            if manager_effect is None:
                return False
            catalog_getter = getattr(manager_effect, 'preset_catalog', None)
            if not callable(catalog_getter):
                return False
            overlays = self._app._overlays  # noqa: SLF001
            current_path = str(getattr(manager_effect, 'current_preset_path', '') or '')
            overlays.set_projectm_manager_entries(catalog_getter(), current_path)
            return True
        except Exception:
            return False

    def set_projectm_focus_pane(self, pane: int) -> int:
        """Set ProjectM manager focus pane (0=category, 1=preset)."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            setter = getattr(overlays, 'set_projectm_focus_pane', None)
            if callable(setter):
                return int(setter(int(pane)))
        except Exception:
            pass
        return 1 if int(pane) > 0 else 0

    def set_projectm_category_index(self, index: int) -> int:
        """Set ProjectM manager category row index and return clamped value."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            setter = getattr(overlays, 'set_projectm_category_index', None)
            if callable(setter):
                return int(setter(int(index)))
        except Exception:
            pass
        return 0

    def set_projectm_preset_index(self, index: int) -> int:
        """Set ProjectM manager preset row index and return clamped value."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            setter = getattr(overlays, 'set_projectm_preset_index', None)
            if callable(setter):
                return int(setter(int(index)))
        except Exception:
            pass
        return 0

    def apply_selected_projectm_preset(self) -> str | None:
        """Apply currently selected ProjectM manager preset and return active label."""
        try:
            manager_effect = self._app.resolve_projectm_manager_effect()
            if manager_effect is None:
                return None
            goto = getattr(manager_effect, 'goto_preset_path', None)
            if not callable(goto):
                return None
            overlays = self._app._overlays  # noqa: SLF001
            selected_getter = getattr(overlays, 'get_projectm_selected_preset', None)
            if not callable(selected_getter):
                return None
            selected = selected_getter()
            if not isinstance(selected, dict):
                return None
            if not bool(selected.get('enabled', False)):
                return None
            path = str(selected.get('path', '') or '')
            if not path:
                return None
            result = goto(path)
            self.sync_projectm_manager()
            return str(result) if result else None
        except Exception:
            return None

    def projectm_enable_selected_category(self) -> tuple[str, int] | None:
        """Enable all presets in selected ProjectM category; returns category and enabled count."""
        try:
            manager_effect = self._app.resolve_projectm_manager_effect()
            if manager_effect is None:
                return None
            overlays = self._app._overlays  # noqa: SLF001
            get_category = getattr(overlays, 'get_projectm_selected_category', None)
            if not callable(get_category):
                return None
            category = str(get_category() or '(all)')
            if category == '(all)':
                remaining = int(manager_effect.enable_all_presets())
            else:
                remaining = int(manager_effect.enable_category(category))
            self.sync_projectm_manager()
            return (category, remaining)
        except Exception:
            return None

    def projectm_disable_selected_category(self) -> tuple[str, int] | None:
        """Disable all presets in selected ProjectM category; returns category and enabled count."""
        try:
            manager_effect = self._app.resolve_projectm_manager_effect()
            if manager_effect is None:
                return None
            overlays = self._app._overlays  # noqa: SLF001
            get_category = getattr(overlays, 'get_projectm_selected_category', None)
            if not callable(get_category):
                return None
            category = str(get_category() or '(all)')
            if category == '(all)':
                remaining = int(manager_effect.disable_all_presets())
            else:
                remaining = int(manager_effect.disable_category(category))
            self.sync_projectm_manager()
            return (category, remaining)
        except Exception:
            return None

    def projectm_isolate_selected_category(self) -> tuple[str, int] | None:
        """Enable only selected ProjectM category; returns category and enabled count."""
        try:
            manager_effect = self._app.resolve_projectm_manager_effect()
            if manager_effect is None:
                return None
            overlays = self._app._overlays  # noqa: SLF001
            get_category = getattr(overlays, 'get_projectm_selected_category', None)
            if not callable(get_category):
                return None
            category = str(get_category() or '(all)')
            if category == '(all)':
                remaining = int(manager_effect.enable_all_presets())
            else:
                remaining = int(manager_effect.isolate_category(category))
            self.sync_projectm_manager()
            return (category, remaining)
        except Exception:
            return None

    def projectm_set_selected_preset_enabled(self, enabled: bool) -> int | None:
        """Set selected ProjectM preset enabled state; returns enabled preset count."""
        try:
            manager_effect = self._app.resolve_projectm_manager_effect()
            if manager_effect is None:
                return None
            overlays = self._app._overlays  # noqa: SLF001
            get_selected = getattr(overlays, 'get_projectm_selected_preset', None)
            if not callable(get_selected):
                return None
            selected = get_selected()
            if not isinstance(selected, dict):
                return None
            path = str(selected.get('path', '') or '')
            if not path:
                return None
            remaining = int(manager_effect.set_presets_enabled([path], bool(enabled)))
            self.sync_projectm_manager()
            return remaining
        except Exception:
            return None

    def projectm_undo_last_bulk_state_change(self) -> str | None:
        """Undo last ProjectM bulk state snapshot and return restored preset label."""
        try:
            manager_effect = self._app.resolve_projectm_manager_effect()
            if manager_effect is None:
                return None
            undo = getattr(manager_effect, 'undo_last_bulk_state_change', None)
            if not callable(undo):
                return None
            restored = undo()
            self.sync_projectm_manager()
            return str(restored) if restored else None
        except Exception:
            return None

    def projectm_redo_last_bulk_state_change(self) -> str | None:
        """Redo last ProjectM bulk state snapshot and return restored preset label."""
        try:
            manager_effect = self._app.resolve_projectm_manager_effect()
            if manager_effect is None:
                return None
            redo = getattr(manager_effect, 'redo_last_bulk_state_change', None)
            if not callable(redo):
                return None
            restored = redo()
            self.sync_projectm_manager()
            return str(restored) if restored else None
        except Exception:
            return None

    def set_auto_advance(self, enabled: bool) -> None:
        self._app._auto_advance = bool(enabled)  # noqa: SLF001

    def toggle_pause(self) -> bool:
        """Toggle playback pause and return the new paused state."""
        self._app.toggle_pause()
        return bool(self._app.paused)

    def toggle_recording(self) -> tuple[bool, str]:
        """Toggle recording on or off."""
        return self._app.toggle_recording()

    def toggle_streaming(self) -> tuple[bool, str]:
        """Toggle RTMP streaming on or off."""
        return self._app.toggle_streaming()

    def trigger_cta_custom(
        self,
        text: str,
        icon: str = '',
        duration: 'float | None' = None,
    ) -> None:
        """Trigger a custom CTA message on the main overlay."""
        overlays = getattr(self._app, '_overlays', None)
        if overlays is not None:
            overlays.trigger_cta_custom(str(text), str(icon), duration)

    def register_text_input_handler(self, name: str, fn: 'Callable[[str], None]') -> None:
        """Register *fn(text)* to receive SDL_TEXTINPUT characters on the main window."""
        self._app.register_text_input_handler(str(name), fn)

    def unregister_text_input_handler(self, name: str) -> None:
        """Unregister a text input handler registered via register_text_input_handler."""
        self._app.unregister_text_input_handler(str(name))

    def start_text_input(self) -> None:
        """Enable SDL IME text-input mode (call when opening a text editor)."""
        try:
            import sdl2  # noqa: PLC0415
            sdl2.SDL_StartTextInput()
        except Exception:
            pass

    def stop_text_input(self) -> None:
        """Disable SDL IME text-input mode (call when closing a text editor)."""
        try:
            import sdl2  # noqa: PLC0415
            sdl2.SDL_StopTextInput()
        except Exception:
            pass

    # ── MIDI output & binding surface ─────────────────────────────────────────

    def midi_available(self) -> bool:
        """Return True when a MIDI input device is connected."""
        m = getattr(self._app, '_midi_manager', None)
        return bool(m is not None and getattr(m, 'available', False))

    def midi_cc_map(self) -> dict[int, str]:
        """Return a copy of the active CC → parameter mapping."""
        m = getattr(self._app, '_midi_manager', None)
        if m is None:
            return {}
        return dict(getattr(m, '_cc_map', {}))

    def midi_note_map(self) -> dict[int, str]:
        """Return a copy of the active note → action mapping."""
        m = getattr(self._app, '_midi_manager', None)
        if m is None:
            return {}
        return dict(getattr(m, '_note_map', {}))

    def midi_active_port_name(self) -> str:
        """Return the connected MIDI input port's name ('' when none is open).

        Public readback of ``MidiManager.port_name`` (see
        ``sync_midi_selector()``, which reads the same attribute directly
        for the overlay) -- exposed here so a drop-in's Control Room panel
        doesn't need to reach into ``app._midi_manager`` itself.
        """
        m = getattr(self._app, '_midi_manager', None)
        if m is None:
            return ''
        return str(getattr(m, 'port_name', '') or '')

    def midi_preset_name(self) -> str:
        """Return the name of the active MIDI preset/profile ('' when none).

        Drop-ins need this to know which controller profile is live — at
        startup the preset comes from ``config.toml``, so the drop-in that owns
        the surface has no other way to find out which profile's LED palette to
        paint with.
        """
        m = getattr(self._app, '_midi_manager', None)
        if m is None:
            return ''
        return str(getattr(m, 'preset', '') or '')

    def midi_preset_device(self) -> str:
        """Return the active MIDI preset's device-model token ('' when unknown).

        A ``ControllerProfile``'s ``meta.device`` rides along in the payload
        ``register_preset()`` stores (``ControllerProfile.to_preset()``
        includes it alongside ``note_map``/``cc_map``), so this is a plain
        readback — see ``MidiManager.preset_device()``. Used by
        :meth:`active_deck_sim_layout` to resolve which registered layout
        matches the connected surface.
        """
        m = getattr(self._app, '_midi_manager', None)
        if m is None:
            return ''
        fn = getattr(m, 'preset_device', None)
        if not callable(fn):
            return ''
        try:
            return str(fn() or '')
        except Exception:
            return ''

    def midi_apply_preset(self, name: str) -> bool:
        """Switch the live MIDI maps to a registered preset/profile.

        Ports are left open, so switching does not interrupt input.  Returns
        False when *name* is not registered or MIDI is unavailable.
        """
        m = getattr(self._app, '_midi_manager', None)
        if m is None:
            return False
        fn = getattr(m, 'apply_preset', None)
        if not callable(fn):
            return False
        return bool(fn(str(name)))

    def midi_bind_note(self, note: int, action: str) -> None:
        """Bind MIDI note *note* to *action*, overriding any preset mapping."""
        m = getattr(self._app, '_midi_manager', None)
        if m is not None:
            fn = getattr(m, 'set_note_binding', None)
            if callable(fn):
                fn(int(note), str(action))

    def midi_unbind_note(self, note: int) -> None:
        """Remove any binding for MIDI note *note*."""
        m = getattr(self._app, '_midi_manager', None)
        if m is not None:
            fn = getattr(m, 'clear_note_binding', None)
            if callable(fn):
                fn(int(note))

    def midi_bind_cc(self, cc: int, param: str) -> None:
        """Bind MIDI CC *cc* to parameter *param*, overriding any preset mapping."""
        m = getattr(self._app, '_midi_manager', None)
        if m is not None:
            fn = getattr(m, 'set_cc_binding', None)
            if callable(fn):
                fn(int(cc), str(param))

    def midi_unbind_cc(self, cc: int) -> None:
        """Remove any binding for MIDI CC *cc*."""
        m = getattr(self._app, '_midi_manager', None)
        if m is not None:
            fn = getattr(m, 'clear_cc_binding', None)
            if callable(fn):
                fn(int(cc))

    def midi_add_raw_listener(self, name: str, fn: Callable) -> None:
        """Register a named raw MIDI event listener (receives MidiEvent objects)."""
        m = getattr(self._app, '_midi_manager', None)
        if m is not None:
            add_fn = getattr(m, 'add_named_listener', None)
            if callable(add_fn):
                add_fn(str(name), fn)

    def midi_remove_raw_listener(self, name: str) -> None:
        """Remove a named raw MIDI event listener."""
        m = getattr(self._app, '_midi_manager', None)
        if m is not None:
            rm_fn = getattr(m, 'remove_named_listener', None)
            if callable(rm_fn):
                rm_fn(str(name))

    # -- Deck-sim (Control Room controller-mirror view) -----------------------
    # See unicornviz/deck_sim.py and
    # drop-ins/control-room-01/docs/deck-sim-plan.md for the full design.
    # Registration lives here (core) exactly like register_midi_actions/
    # register_now_playing above; the drop-in that owns a device's physical
    # geometry (midi-controllers-01 for the APC mini mk2 today) registers a
    # descriptor once at startup, and any consumer (Control Room) resolves
    # the active one generically -- neither side imports the other.

    def register_deck_sim_layout(self, layout: DeckSimLayout) -> None:
        """Register a controller model's physical layout for the deck-sim view.

        Call once per device model, typically at drop-in startup. Replaces
        any previously registered layout for the same device token
        (``layout.device``).
        """
        self._deck_sim_layouts[str(layout.device)] = layout

    def deck_sim_layouts(self) -> 'dict[str, DeckSimLayout]':
        """Return every registered deck-sim layout, keyed by device token."""
        return dict(self._deck_sim_layouts)

    def active_deck_sim_layout(self) -> 'DeckSimLayout | None':
        """Return the layout for the currently active MIDI device, or None.

        None when MIDI is unavailable, no preset is active, the active
        preset is unscoped (no ``meta.device`` recorded), or no layout has
        been registered for that device token yet -- any of these means
        "nothing to mirror", not an error; callers should hide the deck-sim
        toggle entirely in that case (see the plan doc's availability §6).
        """
        device = self.midi_preset_device()
        if not device:
            return None
        return self._deck_sim_layouts.get(device)

    def register_midi_action_colors(
        self, provider: 'Callable[[], dict[str, tuple[int, int]]]',
    ) -> None:
        """Register a callable returning the live ``{action: (idle, active)}`` palette.

        Called by the LED-feedback-owning drop-in (midi-controllers-01) so a
        consumer (a deck-sim mirror view) can read true pad colors without
        importing or reaching into that drop-in's private state. The
        provider is called fresh on every :meth:`midi_action_colors` call
        rather than snapshotted here, since the palette changes live
        (profile switch, MIDI Learn idle-color overrides).
        """
        self._midi_action_colors_provider = provider

    def midi_action_colors(self) -> 'dict[str, tuple[int, int]]':
        """Return the current ``{action: (idle, active)}`` color palette.

        Empty when no provider is registered (LED feedback unavailable/not
        loaded) or the provider raises.
        """
        if self._midi_action_colors_provider is None:
            return {}
        try:
            return dict(self._midi_action_colors_provider())
        except Exception:
            return {}

    def register_midi_active_actions(self, provider: 'Callable[[], set[str]]') -> None:
        """Register a callable returning the live set of "active" actions.

        Companion to :meth:`register_midi_action_colors`: that gives the
        static ``(idle, active)`` color pair per action; this says which
        actions are *currently* in their active state (pause while paused,
        the current display mode, the current postfx slot, ...) so a
        consumer can pick the right one of the pair without reimplementing
        that per-action resolution itself. Same live-provider shape and
        rationale as the color registration right above.
        """
        self._midi_active_actions_provider = provider

    def midi_active_actions(self) -> 'set[str]':
        """Return the current set of "active" action names.

        Empty when no provider is registered or it raises.
        """
        if self._midi_active_actions_provider is None:
            return set()
        try:
            return set(self._midi_active_actions_provider())
        except Exception:
            return set()

    # -- Operator panels / pages (Control Room registry) --------------------
    # Same provider-descriptor pattern as register_deck_sim_layout(): a
    # drop-in registers a frozen descriptor once; the Control Room reads the
    # registry fresh each frame and calls the descriptor's content() itself.

    def register_operator_panel(self, panel: OperatorPanel) -> None:
        """Register (or replace, by ``name``) a Control Room panel."""
        if not isinstance(panel, OperatorPanel):
            raise TypeError('register_operator_panel expects an OperatorPanel')
        self._operator_panels[panel.name] = panel

    def unregister_operator_panel(self, name: str) -> bool:
        """Remove a registered panel; returns whether one was present."""
        return self._operator_panels.pop(str(name), None) is not None

    def operator_panels(self, page: 'str | None' = None) -> 'list[OperatorPanel]':
        """Registered panels, ordered by ``(priority, name)``.

        ``page`` filters to one page; ``None`` returns every panel.
        """
        panels = [p for p in self._operator_panels.values() if page is None or p.page == page]
        panels.sort(key=lambda p: (p.priority, p.name))
        return panels

    def operator_panel(self, name: str) -> 'OperatorPanel | None':
        """Look one panel up by name (``None`` when unregistered)."""
        return self._operator_panels.get(str(name))

    def register_operator_page(self, page: OperatorPage) -> None:
        """Register (or replace, by ``name``) a Control Room page."""
        if not isinstance(page, OperatorPage):
            raise TypeError('register_operator_page expects an OperatorPage')
        self._operator_pages[page.name] = page

    def unregister_operator_page(self, name: str) -> bool:
        """Remove a registered page; returns whether one was present.

        Panels still pointing at the page keep their ``page`` field; the
        Control Room treats panels on an unregistered page as hidden.
        """
        return self._operator_pages.pop(str(name), None) is not None

    def operator_pages(self) -> 'list[OperatorPage]':
        """Registered pages in tab order (by title). ``main`` is never listed."""
        return sort_pages([p for p in self._operator_pages.values() if p.name != MAIN_PAGE])

    def operator_page(self, name: str) -> 'OperatorPage | None':
        """Look one page up by name (``None`` when unregistered)."""
        return self._operator_pages.get(str(name))

    def midi_add_input_device(self, device_hint: str) -> bool:
        """Open an additional raw-only MIDI input device (e.g. a second controller).

        Events from it reach raw listeners only (tagged with
        ``MidiEvent.source == device_hint``) and never drive the primary
        action/param maps, so a drop-in can decode its own controller while the
        primary VJ controller keeps working.  Returns True when a port is open.
        The caller owns cleanup via :meth:`midi_remove_input_device`.
        """
        m = getattr(self._app, '_midi_manager', None)
        if m is None:
            return False
        fn = getattr(m, 'add_input_device', None)
        return bool(fn(str(device_hint))) if callable(fn) else False

    def midi_remove_input_device(self, device_hint: str) -> None:
        """Close an aux MIDI input device previously opened for *device_hint*."""
        m = getattr(self._app, '_midi_manager', None)
        if m is not None:
            fn = getattr(m, 'remove_input_device', None)
            if callable(fn):
                fn(str(device_hint))

    def midi_list_ports(self) -> list[str]:
        """Return available MIDI input port names."""
        try:
            from unicornviz.midi import list_ports  # noqa: PLC0415
            return list_ports()
        except Exception:
            return []

    def midi_list_output_ports(self) -> list[str]:
        """Return available MIDI output port names."""
        try:
            from unicornviz.midi import list_output_ports  # noqa: PLC0415
            return list_output_ports()
        except Exception:
            return []

    def midi_send_output(self, port_hint: str, message: list[int]) -> bool:
        """Send a raw MIDI message to the first output port matching *port_hint*.

        Opens and caches the port on first use; subsequent calls with the same
        hint reuse the open port.  Returns True on success.
        """
        return self._app.midi_send_output(str(port_hint), list(message))

    def midi_inject_event(self, raw: list[int]) -> None:
        """Inject raw MIDI bytes as if received from the primary MIDI device.

        Used by the libusb/rawmidi bypass path to feed APC pad and CC events
        into the normal dispatch chain (note→action, CC→parameter) without
        going through the ALSA sequencer.  Calls MidiManager._callback with
        source=None so events reach action-dispatch listeners (same path as
        the primary rtmidi device).  Thread-safe: may be called from the
        libusb/rawmidi reader thread.
        """
        m = getattr(self._app, '_midi_manager', None)
        if m is not None:
            fn = getattr(m, '_callback', None)
            if callable(fn):
                fn((list(raw), 0.0), None)

    def register_midi_actions(self, section: str, actions: list[tuple[str, str]]) -> None:
        """Register additional MIDI-bindable actions from a drop-in, organized by section.

        Drop-ins call this once after startup so their actions appear in the MIDI
        Learn modal alongside built-in actions.  *section* is the group header
        label; *actions* is a list of ``(action_name, display_label)`` tuples.
        """
        self._midi_action_registry[str(section)] = [(str(a), str(lbl)) for a, lbl in actions]

    def get_registered_midi_actions(self) -> dict[str, list[tuple[str, str]]]:
        """Return all drop-in registered MIDI actions keyed by section name."""
        return dict(self._midi_action_registry)

    def register_midi_action_handler(self, action: str, fn: 'Callable[[], None]') -> None:
        """Register a zero-argument callable to fire when a MIDI note bound to *action* arrives.

        Drop-ins call this alongside :meth:`register_midi_actions` so the MIDI
        dispatch chain can actually fire their actions, not just display them in
        the learn modal.  Replaces any previously registered handler for the
        same action name.
        """
        self._midi_action_handlers[str(action)] = fn

    def fire_midi_action(self, action: str) -> bool:
        """Invoke the registered handler for *action*.

        Called by the MIDI dispatch chain when a note fires an action that is
        not in the built-in ``_MIDI_NOTE_KEY_BINDINGS`` table.  Returns True
        if a handler was found and invoked, False otherwise.
        """
        fn = self._midi_action_handlers.get(action)
        if fn is None:
            return False
        try:
            fn()
        except Exception as exc:
            log.debug('fire_midi_action %r raised: %s', action, exc)
        return True

    def toggle_control_room(self) -> tuple[bool, str]:
        """Toggle the operator control-room window."""
        return self._app.toggle_control_room()

    def set_display_mode(self, mode: str | None = None, reset_to_config: bool = False) -> str:
        """Set the main audience display mode."""
        return self._app.set_display_mode(mode, reset_to_config=reset_to_config)

    def supported_display_modes(self) -> tuple[str, ...]:
        """Return display modes currently supported by the runtime."""
        getter = getattr(self._app, 'supported_display_modes', None)
        if not callable(getter):
            return ('single',)
        try:
            modes = getter()
        except Exception:
            return ('single',)
        out = tuple(str(mode).strip().lower() for mode in modes if str(mode).strip())
        return out or ('single',)

    def set_advance_interval(self, seconds: float) -> float:
        self._app._effect_duration = max(10.0, float(seconds))  # noqa: SLF001
        return float(self._app._effect_duration)  # noqa: SLF001

    def reset_advance_interval(self) -> float:
        return float(self._app.reset_advance_interval())

    def set_show_duration(self, seconds: float | None) -> None:
        """Set optional session/show duration in seconds.

        ``None`` (or non-positive value) disables countdown mode.
        """
        if seconds is None:
            self._app._show_duration_s = None  # noqa: SLF001
            return
        val = float(seconds)
        self._app._show_duration_s = val if val > 0.0 else None  # noqa: SLF001

    def get_elapsed_time(self) -> float:
        """Return session elapsed seconds since app run-loop start."""
        started = float(getattr(self._app, '_session_started_at', 0.0))  # noqa: SLF001
        if started <= 0.0:
            return 0.0
        return max(0.0, float(time.monotonic() - started))

    def get_time_remaining(self) -> float | None:
        """Return remaining seconds to configured show end, or ``None`` if unlimited."""
        duration = getattr(self._app, '_show_duration_s', None)  # noqa: SLF001
        if duration is None:
            return None
        return max(0.0, float(duration) - self.get_elapsed_time())

    def format_session_clock(self) -> str:
        """Return elapsed session time as ``MM:SS`` or ``HH:MM:SS``.

        This is a public helper for UI surfaces (HUD/overlays/log views)
        that need a stable, human-readable runtime clock.
        """
        elapsed = max(0, int(self.get_elapsed_time()))
        minutes, seconds = divmod(elapsed, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f'{hours:02d}:{minutes:02d}:{seconds:02d}'
        return f'{minutes:02d}:{seconds:02d}'

    def set_reactivity(self, value: float) -> float:
        if self._app._audio_manager is None:  # noqa: SLF001
            return 1.0
        return float(self._app._audio_manager.set_reactivity(value))  # noqa: SLF001

    def set_speed(self, value: float) -> float | None:
        effect = self._app._current_effect  # noqa: SLF001
        if effect is None or 'speed' not in effect.parameters:
            return None
        prev_speed = float(effect.parameters['speed'])
        new_speed = max(0.05, min(10.0, float(value)))
        # Intentional exception: when Auto VJ is actively running in the
        # raver profile, preserve the old discontinuous slew look on purpose.
        # Lower-third raver BPM (126-138: prog house, early trance) gets the
        # scramble only 1-in-3 calls — enough chaos without overwhelming slower
        # material.  Mid (138-155) and fast (155+) raver run it every time.
        auto_vj = getattr(self._app, '_auto_vj', None)  # noqa: SLF001
        raver_scramble = False
        if (
            auto_vj is not None
            and bool(getattr(auto_vj, 'enabled', False))
            and str(getattr(auto_vj, '_profile', '')).lower() == 'raver'
        ):
            import random
            _grid = getattr(auto_vj, '_grid', None)
            _bpm = float(getattr(_grid, 'bpm', 0.0) or 0.0) if _grid is not None else 0.0
            if _bpm >= 138.0:
                raver_scramble = True
            else:
                raver_scramble = random.random() < (1.0 / 3.0)
        # Keep shader phase continuous for effects that use
        # t = iTime * (bias + scale * iSpeed).
        # Defaults match the common t = iTime * iSpeed case.
        if (not raver_scramble) and abs(new_speed - prev_speed) > 1e-9 and hasattr(effect, 'time'):
            try:
                t = float(getattr(effect, 'time'))
                bias = float(getattr(effect, 'SPEED_TIME_BIAS', 0.0))
                scale = float(getattr(effect, 'SPEED_TIME_SCALE', 1.0))
                prev_factor = bias + scale * prev_speed
                next_factor = bias + scale * new_speed
                if abs(prev_factor) > 1e-9 and abs(next_factor) > 1e-9:
                    setattr(effect, 'time', (t * prev_factor) / next_factor)
            except Exception:
                # Never fail speed changes due to continuity bookkeeping.
                pass
        effect.parameters['speed'] = new_speed
        return float(effect.parameters['speed'])

    def set_zoom(self, value: float) -> float | None:
        effect = self._app._current_effect  # noqa: SLF001
        if effect is None or 'zoom' not in effect.parameters:
            return None
        lo = float(self._app.cfg.get('hotkeys', 'zoom_min', default=0.1))  # noqa: SLF001
        hi = float(self._app.cfg.get('hotkeys', 'zoom_max', default=3.0))  # noqa: SLF001
        effect.parameters['zoom'] = max(lo, min(hi, float(value)))
        return float(effect.parameters['zoom'])

    def get_effect_parameters(self) -> dict[str, float]:
        """Return a copy of the current effect's tweakable parameters.

        Public surface for control surfaces (OSC bridge, control room) to
        enumerate live parameters without reaching into the current effect.
        """
        effect = self._app._current_effect  # noqa: SLF001
        if effect is None:
            return {}
        params = getattr(effect, 'parameters', None)
        return dict(params) if isinstance(params, dict) else {}

    def set_effect_parameter(self, name: str, value: float) -> float | None:
        """Set a named tweakable parameter on the current effect.

        Returns the new value, or ``None`` when the effect has no such
        parameter.  ``speed`` and ``zoom`` route through their dedicated setters
        to preserve phase-continuity / configured clamping; all other named
        parameters are assigned directly.
        """
        effect = self._app._current_effect  # noqa: SLF001
        if effect is None:
            return None
        params = getattr(effect, 'parameters', None)
        if not isinstance(params, dict) or name not in params:
            return None
        if name == 'speed':
            return self.set_speed(value)
        if name == 'zoom':
            return self.set_zoom(value)
        params[name] = float(value)
        return float(params[name])

    def set_invert(self, enabled: bool) -> bool:
        enabled = bool(enabled)
        if bool(self._app._invert_colors) != enabled:  # noqa: SLF001
            self._app.toggle_invert()
        return bool(self._app._invert_colors)  # noqa: SLF001

    def trigger_rainbow_nova(self) -> bool:
        if self._app._rainbow_nova is None:  # noqa: SLF001
            return False
        self._app.trigger_rainbow_nova()
        return True

    def trigger_screen_burst(self) -> bool:
        self._app.trigger_burst()
        return bool(self._app._burst_controller.active)  # noqa: SLF001

    def trigger_dancing_unicorn(self) -> bool:
        if self._app._dancing_unicorn is None:  # noqa: SLF001
            return False
        self._app.trigger_dancing_unicorn()
        return True

    def trigger_grand_finale(self) -> str:
        """Trigger the grand finale sequence; returns a flash-message string."""
        if self._app._grand_finale is None:  # noqa: SLF001
            return 'Grand Finale drop-in not loaded'
        return str(self._app.trigger_grand_finale())

    def abort_grand_finale(self) -> str:
        """Abort the grand finale and restore pre-finale state."""
        return str(self._app.abort_grand_finale())

    @property
    def grand_finale_active(self) -> bool:
        """Whether the grand-finale sequence is currently mid-run.

        True from the moment it actually starts advancing (PEAK/DROP/OUTRO/
        BLACKOUT) until it returns to idle after the BLACKOUT tail. False if
        the drop-in isn't loaded, or the sequence was never triggered.
        Lets a consumer (e.g. auto-vj-01's unattended-run auto-exit) watch
        for the True -> False completion edge without reaching into
        app._grand_finale directly.
        """
        finale = self._app._grand_finale  # noqa: SLF001
        if finale is None:
            return False
        return bool(getattr(finale, 'is_active', False))

    def toggle_auto_vj(self) -> str:
        """Toggle Auto VJ controller on/off; returns a flash-message string."""
        return str(self._app.toggle_auto_vj())

    def toggle_candy_frame(self) -> str:
        """Toggle the Candy Frame neon border on/off."""
        return str(self._app.toggle_candy_frame())

    def candy_frame_active(self) -> bool:
        """Return whether the Candy Frame overlay is currently active."""
        candy_frame = getattr(self._app, '_candy_frame', None)  # noqa: SLF001
        return bool(candy_frame is not None and bool(getattr(candy_frame, 'active', False)))

    def select_postfx_slot(self, slot: int) -> str:
        """Activate post-FX slot *slot* (1–10); returns a flash-message string."""
        return str(self._app.select_postfx_slot(int(slot)))

    def set_stream_provider(self, provider: str) -> str:
        """Switch the RTMP stream provider preset; returns provider name string."""
        return str(self._app.set_stream_provider(str(provider)))

    def set_camera_layout(self, token: str) -> bool:
        """Set the webcam PiP layout token ('0', '.', '1'–'9')."""
        return bool(self._app.set_camera_layout(str(token)))

    def scale_pip(self, delta: float) -> float:
        """Scale the webcam PiP overlay by *delta* fraction (+/- 0.05)."""
        return float(self._app.scale_pip(float(delta)))

    def goto_prev_webcam_effect(self) -> str | None:
        """Step to the previous webcam treatment; returns name or None."""
        return self._app.goto_prev_webcam_effect()

    def goto_next_webcam_effect(self) -> str | None:
        """Step to the next webcam treatment; returns name or None."""
        return self._app.goto_next_webcam_effect()

    def toggle_webcam_auto_cycle(self) -> bool:
        """Toggle the webcam treatment auto-cycle; returns new active state."""
        return bool(self._app.toggle_webcam_auto_cycle())

    def goto_prev_camera(self) -> str | None:
        """Switch to the previous camera device; returns device label or None."""
        return self._app.goto_prev_camera()

    def goto_next_camera(self) -> str | None:
        """Switch to the next camera device; returns device label or None."""
        return self._app.goto_next_camera()

    def list_webcam_cameras(self) -> list[dict[str, object]]:
        """Return detected webcam devices with enabled/selected metadata."""
        return self._app.list_webcam_cameras()

    def rediscover_webcam_cameras(self) -> list[dict[str, object]]:
        """Re-scan webcam devices and return refreshed camera metadata."""
        return self._app.rediscover_webcam_cameras()

    def set_webcam_camera_enabled(self, camera_id: int, enabled: bool) -> bool:
        """Enable or disable a webcam device by camera index."""
        return bool(self._app.set_webcam_camera_enabled(int(camera_id), bool(enabled)))

    def set_active_webcam_camera(self, camera_id: int) -> str | None:
        """Switch directly to a webcam device by camera index."""
        return self._app.set_active_webcam_camera(int(camera_id))

    def set_webcam_brightness(self, value: float) -> float:
        """Set webcam brightness multiplier and return clamped value."""
        return float(self._app.set_webcam_brightness(float(value)))

    def set_webcam_contrast(self, value: float) -> float:
        """Set webcam contrast multiplier and return clamped value."""
        return float(self._app.set_webcam_contrast(float(value)))

    def adjust_webcam_brightness(self, delta: float) -> float:
        """Adjust webcam brightness by delta and return new value."""
        return float(self._app.adjust_webcam_brightness(float(delta)))

    def adjust_webcam_contrast(self, delta: float) -> float:
        """Adjust webcam contrast by delta and return new value."""
        return float(self._app.adjust_webcam_contrast(float(delta)))

    def set_webcam_flip_horizontal(self, enabled: bool) -> bool:
        """Enable or disable horizontal mirror flip for webcam frames."""
        return bool(self._app.set_webcam_flip_horizontal(bool(enabled)))

    def set_webcam_flip_vertical(self, enabled: bool) -> bool:
        """Enable or disable vertical flip for webcam frames."""
        return bool(self._app.set_webcam_flip_vertical(bool(enabled)))

    def toggle_webcam_flip_horizontal(self) -> bool:
        """Toggle horizontal mirror flip for webcam frames."""
        return bool(self._app.toggle_webcam_flip_horizontal())

    def toggle_webcam_flip_vertical(self) -> bool:
        """Toggle vertical flip for webcam frames."""
        return bool(self._app.toggle_webcam_flip_vertical())

    def webcam_flip_state(self) -> dict[str, bool]:
        """Return webcam horizontal/vertical flip state."""
        return self._app.webcam_flip_state()

    def webcam_image_state(self) -> dict[str, float | bool]:
        """Return webcam image controls (brightness/contrast/flip) state."""
        return self._app.webcam_image_state()

    def trigger_burst(self) -> bool:
        """Trigger a screen-burst effect (alias for trigger_screen_burst)."""
        return self.trigger_screen_burst()

    def set_postfx_slot(self, slot: int) -> bool:
        if int(slot) == 0:
            return self.clear_postfx()
        msg = self._app.select_postfx_slot(int(slot))
        lower = msg.lower()
        if 'unavailable' in lower:
            return False
        if 'invalid slot' in lower:
            return False
        if 'use ctrl+alt+1..9' in lower:
            return False
        if 'coming soon' in lower:
            return False
        return True

    def postfx_slots(self) -> list[tuple[int, str, bool]]:
        """Return available post-FX slot definitions as (slot, label, enabled)."""
        pc = self._app._postfx_controller  # noqa: SLF001
        if pc is None:
            return []
        slot_map = getattr(pc, 'SLOT_MAP', ())
        out: list[tuple[int, str, bool]] = []
        for item in slot_map:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            slot = int(item[0])
            label = str(item[1])
            enabled = bool(item[2]) if len(item) > 2 else True
            out.append((slot, label, enabled))
        return out

    def hold_postfx_slot(self, slot: int, duration_s: float) -> bool:
        # Phase 1: trigger slot immediately; timed holds land in later phases.
        _ = duration_s
        return self.set_postfx_slot(slot)

    def clear_postfx(self) -> bool:
        if self._app._postfx_controller is None:  # noqa: SLF001
            return False
        clear_slot = getattr(self._app._postfx_controller, 'clear_active_slot', None)  # noqa: SLF001
        if not callable(clear_slot):
            return False
        clear_slot()
        return True

    def postfx_slot_duration(self, slot: int) -> float:
        """Return the configured display duration (seconds) for a post-FX slot.

        Returns 1.0 when the post-FX controller is unavailable or the slot is
        not found.
        """
        try:
            pc = self._app._postfx_controller  # noqa: SLF001
            if pc is not None:
                return float(pc._slot_hit_duration.get(int(slot), 1.0))  # noqa: SLF001
        except Exception:
            pass
        return 1.0

    def postfx_friend_pairs(self) -> list[tuple[int, int]]:
        """Return post-FX friend pairs for ping-pong use.

        Returns a list of ``(slot_a, slot_b)`` tuples where each pair represents
        a curated pairing.  Returns an empty list when no Post-FX controller is
        available.
        """
        try:
            pc = self._app._postfx_controller  # noqa: SLF001
            if pc is None:
                return []
            return pc.friend_pairs()
        except Exception:
            return []

    def postfx_friend_groups(self) -> list[tuple[int, ...]]:
        """Return post-FX friend groups (pairs and trios) for ping-pong use.

        Returns a list of tuples where each tuple is a curated group of 2 or 3
        slot indices.  Trios are derived from entries in ``POSTFX_FRIENDS`` that
        have two partners.  Returns an empty list when no Post-FX controller is
        available.
        """
        try:
            pc = self._app._postfx_controller  # noqa: SLF001
            if pc is None:
                return []
            return pc.friend_groups()
        except Exception:
            return []

    def is_user_busy(self) -> bool:
        return bool(time.monotonic() < self._app._user_action_deadline)  # noqa: SLF001

    def mark_user_action(self, kind: str = 'generic') -> None:
        self._app._mark_user_action(kind)  # noqa: SLF001

    def set_status_pill(self, text: str | None) -> None:
        self._app._vj_status_pill = '' if text is None else str(text)  # noqa: SLF001

    # ── Overlay helpers ────────────────────────────────────────────────────

    def flash_message(self, text: str, duration: float = 2.0) -> None:
        """Push a timed flash message to the HUD overlay."""
        try:
            self._app._overlays.flash_message(str(text), float(duration))  # noqa: SLF001
        except Exception:
            pass

    def overlay_modal_snapshot(self) -> dict[str, object]:
        """Return active overlay modal payload for alternate operator surfaces."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            snap = getattr(overlays, 'modal_snapshot', None)
            if callable(snap):
                payload = snap()
                if isinstance(payload, dict):
                    return payload
        except Exception:
            pass
        return {}

    def hue_scroll(self, dy: int) -> None:
        """Accumulate scroll-wheel hue shift by dy steps (+up / -down)."""
        try:
            pc = self._app._postfx_controller  # noqa: SLF001
            if pc is not None:
                pc.on_scroll(int(dy))
        except Exception:
            pass

    def rotate_scroll(self, dy: int) -> bool:
        """Accumulate Ctrl+scroll rotation by dy steps (+up / -down)."""
        pc = self._app._postfx_controller  # noqa: SLF001
        if pc is None:
            return False
        pc.on_ctrl_scroll(int(dy))
        return True

    def trigger_scroll_fx(self, dy: int, *, rotate: bool = False) -> bool:
        """Trigger postfx scroll behavior through the active controller.

        ``rotate=False`` routes to hue-shift (wheel).
        ``rotate=True`` routes to rotation (Ctrl+wheel).
        Returns True when a controller is present and the event was sent.
        """
        pc = self._app._postfx_controller  # noqa: SLF001
        if pc is None:
            return False
        if rotate:
            pc.on_ctrl_scroll(int(dy))
        else:
            pc.on_scroll(int(dy))
        return True

    def clear_hue_shift(self) -> None:
        """Immediately clear the scroll-wheel hue-shift pass."""
        try:
            pc = self._app._postfx_controller  # noqa: SLF001
            if pc is not None:
                pc.clear_hue_shift()
        except Exception:
            pass

    def rotate_scroll_degrees(self, degrees: float) -> bool:
        """Accumulate ctrl+scroll scene rotation by explicit degrees.

        Returns True when a postfx controller is present.
        """
        pc = self._app._postfx_controller  # noqa: SLF001
        if pc is None:
            return False
        if hasattr(pc, 'on_ctrl_scroll_degrees'):
            pc.on_ctrl_scroll_degrees(float(degrees))
        else:
            # Backward-compatible fallback for older postfx controllers.
            step = float(getattr(pc, '_rot_step_rad', 0.07) or 0.07)
            dy = int(round((float(degrees) * 0.017453292519943295) / max(1e-6, step)))
            if dy != 0:
                pc.on_ctrl_scroll(dy)
        return True

    def clear_scroll_fx(self) -> None:
        """Clear both scroll-driven post-fx states (hue + rotation)."""
        try:
            pc = self._app._postfx_controller  # noqa: SLF001
            if pc is not None:
                pc.clear_scroll_fx()
        except Exception:
            pass

    def set_hue_offset(self, value: float) -> bool:
        """Set scroll-driven hue offset directly in normalized [0, 1] space."""
        pc = self._app._postfx_controller  # noqa: SLF001
        if pc is None:
            return False
        try:
            pc._hue_offset = max(0.0, min(1.0, float(value)))  # noqa: SLF001
            pc._hue_idle_t = float(getattr(pc, '_hue_idle_timeout', 3.0) or 3.0)  # noqa: SLF001
            pc._hue_active = True  # noqa: SLF001
            return True
        except Exception:
            return False

    def set_rotation_degrees(self, degrees: float) -> bool:
        """Set scroll-driven scene rotation directly in degrees."""
        pc = self._app._postfx_controller  # noqa: SLF001
        if pc is None:
            return False
        try:
            pc._rot_angle = float(degrees) * 0.017453292519943295  # noqa: SLF001
            pc._rot_idle_t = float(getattr(pc, '_rot_idle_timeout', 3.0) or 3.0)  # noqa: SLF001
            pc._rot_active = True  # noqa: SLF001
            return True
        except Exception:
            return False

    def scroll_fx_state(self) -> dict[str, float | bool]:
        """Return scroll-driven post-fx state for operator surfaces."""
        pc = self._app._postfx_controller  # noqa: SLF001
        if pc is None:
            return {
                'available': False,
                'hue_active': False,
                'rotation_active': False,
                'hue_offset': 0.0,
                'rotation_degrees': 0.0,
            }

        hue_offset = 0.0
        rot_angle = 0.0
        try:
            hue_offset = float(getattr(pc, '_hue_offset', 0.0) or 0.0)
        except Exception:
            hue_offset = 0.0
        try:
            rot_angle = float(getattr(pc, '_rot_angle', 0.0) or 0.0)
        except Exception:
            rot_angle = 0.0

        return {
            'available': True,
            'hue_active': bool(getattr(pc, 'is_hue_active', False)),
            'rotation_active': bool(getattr(pc, 'is_rotation_active', False)),
            'hue_offset': hue_offset,
            'rotation_degrees': rot_angle * 57.29577951308232,
        }

    def effect_param_range(self, name: str) -> tuple[float | None, float | None]:
        """Return the active effect's config overrides for ``random_<name>_min/max``.

        Returns ``(None, None)`` when the current effect has no config or has
        not declared overrides for *name*.  Used by automation subsystems (e.g.
        Auto VJ) to honour per-effect tweakable bounds when drifting parameters.

        *name* should be one of ``"speed"``, ``"zoom"``, or ``"reactivity"``.
        """
        effect = self._app._current_effect  # noqa: SLF001
        cfg = getattr(effect, 'config', None) if effect is not None else None
        if not isinstance(cfg, dict):
            return (None, None)
        lo_raw = cfg.get(f'random_{name}_min')
        hi_raw = cfg.get(f'random_{name}_max')
        return (
            float(lo_raw) if lo_raw is not None else None,
            float(hi_raw) if hi_raw is not None else None,
        )

    # ── Drop-in key handler registry ──────────────────────────────────────

    def register_key_handler(
        self,
        name: str,
        handler: Callable[[int, int], 'str | None | bool'],
    ) -> None:
        """Register a drop-in key handler.

        *handler(sym, mod)* is called for every SDL KEYDOWN event before core
        key bindings.  It must return:

        - ``str``   — handled; the string is shown as a flash message
        - ``None``  — handled silently; no flash
        - ``False`` — not handled; pass through to the next handler / core
        """
        self._key_handlers[str(name)] = handler
        log.debug('Key handler registered: %s', name)

    def unregister_key_handler(self, name: str) -> None:
        """Remove a previously registered handler (e.g. on drop-in teardown)."""
        self._key_handlers.pop(str(name), None)

    @property
    def key_handlers(self) -> list[Callable[[int, int], 'str | None | bool']]:
        """Current list of registered handlers in insertion order."""
        return list(self._key_handlers.values())

    def key_handler_items(self) -> list[tuple[str, Callable[[int, int], 'str | None | bool']]]:
        """Registered (name, handler) pairs in insertion order."""
        return list(self._key_handlers.items())
