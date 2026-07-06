"""Hotkey handler — maps SDL keysyms and MIDI notes to app/playlist/overlay actions."""
from __future__ import annotations

from collections import deque
import logging
import threading
from typing import TYPE_CHECKING

import sdl2

from unicornviz.catalog_browser import PANE_CATEGORIES, PANE_LIST
from unicornviz.paths import resolve_path

if TYPE_CHECKING:
    from unicornviz.app import App
    from unicornviz.playlist import Playlist
    from unicornviz.overlays import Overlays
    from unicornviz.audio.manager import AudioManager
    from unicornviz.midi import MidiManager, MidiEvent

log = logging.getLogger(__name__)


# Tokens that mark a help "key" string as NOT a single dispatchable chord
# (ranges, multi-key lists, wheel/mouse, or placeholder words).  Entries whose
# key contains any of these are skipped by parse_hotkey_chord().
_NON_CHORD_TOKENS = ('/', ' - ', '..', 'Wheel', 'Click', 'Arrow', 'Number', 'Drag')

_CHORD_MODIFIERS: dict[str, int] = {
    'ctrl': sdl2.KMOD_CTRL,
    'control': sdl2.KMOD_CTRL,
    'alt': sdl2.KMOD_ALT,
    'option': sdl2.KMOD_ALT,
    'shift': sdl2.KMOD_SHIFT,
}

# Help-string spellings that differ from SDL_GetKeyFromName's canonical names.
_CHORD_BASE_ALIASES: dict[str, str] = {
    'esc': 'Escape',
    'del': 'Delete',
    'ins': 'Insert',
    'ret': 'Return',
    'enter': 'Return',
    'pgup': 'PageUp',
    'pgdn': 'PageDown',
}


def parse_hotkey_chord(text: str) -> tuple[int, int] | None:
    """Parse a help-style hotkey label into an ``(sym, mod)`` pair, or ``None``.

    Accepts single-chord forms such as ``'B'``, ``'Ctrl+Shift+P'``, ``'F9'``,
    ``'Ctrl+Alt+['``, ``'Space'``.  Returns ``None`` for anything that is not a
    single dispatchable chord (ranges like ``'0 - 9'``, multi-key lists like
    ``'n / Right'``, or wheel/mouse gestures) so callers can skip it.

    The returned pair matches what SDL delivers for the equivalent keypress
    (base keycode + modifier bitmask), so it can be fed straight to
    ``HotkeyHandler.handle(sym, mod)`` to replay the binding.
    """
    if not text or not isinstance(text, str):
        return None
    s = text.strip()
    if not s or any(tok in s for tok in _NON_CHORD_TOKENS):
        return None

    parts = [p for p in s.replace(' ', '').split('+') if p]
    if not parts:
        return None

    mod = 0
    base: str | None = None
    for part in parts:
        found = _CHORD_MODIFIERS.get(part.lower())
        if found is not None:
            mod |= found
        elif base is None:
            base = part
        else:
            # Two non-modifier tokens — not a single chord.
            return None

    if not base:
        return None

    base = _CHORD_BASE_ALIASES.get(base.lower(), base)
    sym = sdl2.SDL_GetKeyFromName(base.encode('utf-8'))
    if sym == sdl2.SDLK_UNKNOWN:
        sym = sdl2.SDL_GetKeyFromName(base.lower().encode('utf-8'))
    if sym == sdl2.SDLK_UNKNOWN:
        return None
    return int(sym), int(mod)


_SHIFT_NUMBER_SYMS = [
    sdl2.SDLK_EXCLAIM, sdl2.SDLK_AT, sdl2.SDLK_HASH,
    sdl2.SDLK_DOLLAR, sdl2.SDLK_PERCENT, sdl2.SDLK_CARET,
    sdl2.SDLK_AMPERSAND, sdl2.SDLK_ASTERISK,
    sdl2.SDLK_LEFTPAREN, sdl2.SDLK_RIGHTPAREN,
]


def numeric_slot_index(sym: int, mod: int) -> int | None:
    """Resolve a number-key chord to a numeric-hotkey slot index (0-39).

    Naked 1-9,0 -> 0-9; Shift+1-9,0 -> 10-19; Ctrl+1-9,0 -> 20-29;
    Alt+1-9,0 -> 30-39. Shift is also recognised via the symbol keysyms some
    keyboard layouts send instead of number-keysym-plus-modifier (!@#$...).
    Returns None if ``sym`` is not a number-key chord.
    """
    if sym in _SHIFT_NUMBER_SYMS:
        return 10 + _SHIFT_NUMBER_SYMS.index(sym)
    if sdl2.SDLK_1 <= sym <= sdl2.SDLK_9:
        base = sym - sdl2.SDLK_1
    elif sym == sdl2.SDLK_0:
        base = 9
    else:
        return None
    if mod & sdl2.KMOD_ALT:
        return 30 + base
    if mod & sdl2.KMOD_CTRL:
        return 20 + base
    if mod & sdl2.KMOD_SHIFT:
        return 10 + base
    return base


def hotkey_slot_label(slot: int) -> str:
    """Return a short display label for a numeric-hotkey slot (e.g. 'C+3')."""
    digit = '0' if slot % 10 == 9 else str((slot % 10) + 1)
    prefix = ('', 'S+', 'C+', 'A+')[slot // 10] if 0 <= slot < 40 else ''
    return f'{prefix}{digit}'


_MODIFIER_KEYSYMS = frozenset((
    sdl2.SDLK_LSHIFT, sdl2.SDLK_RSHIFT,
    sdl2.SDLK_LCTRL, sdl2.SDLK_RCTRL,
    sdl2.SDLK_LALT, sdl2.SDLK_RALT,
    sdl2.SDLK_LGUI, sdl2.SDLK_RGUI,
))


def is_modifier_keysym(sym: int) -> bool:
    """Return True if ``sym`` is a bare modifier key (Shift/Ctrl/Alt/GUI).

    Used to reject binding a rebindable action to a modifier key alone, which
    would be meaningless as a standalone hotkey chord.
    """
    return sym in _MODIFIER_KEYSYMS


def chord_label(sym: int, mod: int) -> str:
    """Return a short human display label for a (sym, mod) chord, e.g. 'Ctrl+F'."""
    parts = []
    if mod & sdl2.KMOD_CTRL:
        parts.append('Ctrl')
    if mod & sdl2.KMOD_ALT:
        parts.append('Alt')
    if mod & sdl2.KMOD_SHIFT:
        parts.append('Shift')
    if mod & sdl2.KMOD_GUI:
        parts.append('Gui')
    name = sdl2.SDL_GetKeyName(sym)
    if isinstance(name, bytes):
        name = name.decode('utf-8', errors='replace')
    parts.append(name or f'Key{sym}')
    return '+'.join(parts)


# Canonical {action_name: (sym, mod)} table for named global actions - the
# single source of truth for both MIDI note→key replay (below) and the
# hotkey-rebinding "enabler": App.hotkey_overrides() lets an operator rebind
# any of these actions to a different chord (persisted); translate_override_
# chord() converts an incoming override chord back to its action's *default*
# chord before the (unmodified) global dispatch chain in handle() runs, so no
# dispatch logic needs to change for a rebind to take effect. Only applied in
# the global tail (after every modal has had first refusal), so a rebind never
# changes in-modal key behaviour.
_MIDI_NOTE_KEY_BINDINGS: dict[str, tuple[int, int]] = {
    'next': (sdl2.SDLK_n, 0),
    'prev': (sdl2.SDLK_p, 0),
    'random': (sdl2.SDLK_r, 0),
    'pause': (sdl2.SDLK_SPACE, 0),
    'fullscreen': (sdl2.SDLK_f, 0),
    'audio_toggle': (sdl2.SDLK_e, 0),
    'eq': (sdl2.SDLK_e, 0),
    'ansi': (sdl2.SDLK_a, 0),
    'audio_selector': (sdl2.SDLK_a, sdl2.KMOD_SHIFT),
    'midi_selector': (sdl2.SDLK_m, sdl2.KMOD_ALT),
    'system_monitor': (sdl2.SDLK_m, 0),
    'control_room': (sdl2.SDLK_m, sdl2.KMOD_SHIFT),
    'projectm_manager': (sdl2.SDLK_m, sdl2.KMOD_CTRL),
    'controller_help': (sdl2.SDLK_h, sdl2.KMOD_CTRL | sdl2.KMOD_ALT),
    'help': (sdl2.SDLK_h, 0),
    'hud': (sdl2.SDLK_TAB, 0),
    'screenshot': (sdl2.SDLK_s, 0),
    'replay_splash': (sdl2.SDLK_u, 0),
    'invert': (sdl2.SDLK_i, 0),
    'display_single': (sdl2.SDLK_x, 0),
    'display_span_included': (sdl2.SDLK_x, sdl2.KMOD_CTRL),
    'display_span_all': (sdl2.SDLK_x, sdl2.KMOD_CTRL | sdl2.KMOD_SHIFT),
    'display_mirror_included': (sdl2.SDLK_x, sdl2.KMOD_ALT),
    'display_mirror_all': (sdl2.SDLK_x, sdl2.KMOD_ALT | sdl2.KMOD_SHIFT),
    'grand_finale': (sdl2.SDLK_f, sdl2.KMOD_CTRL | sdl2.KMOD_ALT),
    'grand_finale_abort': (
        sdl2.SDLK_f,
        sdl2.KMOD_CTRL | sdl2.KMOD_ALT | sdl2.KMOD_SHIFT,
    ),
    'speed_random': (sdl2.SDLK_F6, 0),
    'reactivity_random': (sdl2.SDLK_F7, 0),
    'zoom_random': (sdl2.SDLK_z, sdl2.KMOD_ALT),
}


def default_action_binding(action: str) -> tuple[int, int] | None:
    """Return the built-in default (sym, mod) for a named global action."""
    return _MIDI_NOTE_KEY_BINDINGS.get(action)


def action_names() -> list[str]:
    """Return all rebindable global-action names (for a future hotkey editor)."""
    return list(_MIDI_NOTE_KEY_BINDINGS.keys())


def translate_override_chord(
    sym: int, mod: int, overrides: 'dict[str, tuple[int, int]]'
) -> tuple[int, int]:
    """Translate a possibly-rebound chord back to its action's default chord.

    If ``(sym, mod)`` exactly matches an operator override for some action,
    return that action's *default* chord, so the existing dispatch chain
    (which still matches on default chords) fires correctly without needing
    to know rebinding exists. If ``(sym, mod)`` matches no override, it is
    returned unchanged.
    """
    if not overrides:
        return sym, mod
    for action, chord in overrides.items():
        if chord == (sym, mod):
            default = _MIDI_NOTE_KEY_BINDINGS.get(action)
            if default is not None:
                return default
    return sym, mod


_MIDI_CONTEXT_SLOT_BINDINGS: dict[str, dict[int, tuple[int, int]]] = {
    # Default live-performance mapping when no selector/modal is active.
    'performance': {
        1: (sdl2.SDLK_n, 0),
        2: (sdl2.SDLK_p, 0),
        3: (sdl2.SDLK_r, 0),
        4: (sdl2.SDLK_SPACE, 0),
        5: (sdl2.SDLK_f, 0),
        6: (sdl2.SDLK_e, 0),
        7: (sdl2.SDLK_a, 0),
        8: (sdl2.SDLK_h, sdl2.KMOD_CTRL | sdl2.KMOD_ALT),
    },
    # Audio selector context: navigate, toggle viable, commit, back.
    'audio_selector': {
        1: (sdl2.SDLK_UP, 0),
        2: (sdl2.SDLK_DOWN, 0),
        3: (sdl2.SDLK_LEFT, 0),
        4: (sdl2.SDLK_RIGHT, 0),
        5: (sdl2.SDLK_RETURN, 0),
        6: (sdl2.SDLK_t, 0),
        7: (sdl2.SDLK_ESCAPE, 0),
        8: (sdl2.SDLK_a, sdl2.KMOD_SHIFT),
    },
    # MIDI selector context.
    'midi_selector': {
        1: (sdl2.SDLK_UP, 0),
        2: (sdl2.SDLK_DOWN, 0),
        3: (sdl2.SDLK_LEFT, 0),
        4: (sdl2.SDLK_RIGHT, 0),
        5: (sdl2.SDLK_RETURN, 0),
        6: (sdl2.SDLK_ESCAPE, 0),
        7: (sdl2.SDLK_m, sdl2.KMOD_ALT),
        8: (sdl2.SDLK_h, 0),
    },
    # Help context: section nav/toggle/expand/collapse and exit.
    'help': {
        1: (sdl2.SDLK_UP, 0),
        2: (sdl2.SDLK_DOWN, 0),
        3: (sdl2.SDLK_LEFT, 0),
        4: (sdl2.SDLK_RIGHT, 0),
        5: (sdl2.SDLK_RETURN, 0),
        6: (sdl2.SDLK_PLUS, sdl2.KMOD_SHIFT),
        7: (sdl2.SDLK_MINUS, sdl2.KMOD_SHIFT),
        8: (sdl2.SDLK_h, 0),
    },
    # System monitor modal: quick close + escape hatch actions.
    'system_monitor': {
        1: (sdl2.SDLK_ESCAPE, 0),
        2: (sdl2.SDLK_m, 0),
        3: (sdl2.SDLK_m, sdl2.KMOD_SHIFT),
        4: (sdl2.SDLK_m, sdl2.KMOD_ALT),
        5: (sdl2.SDLK_n, 0),
        6: (sdl2.SDLK_p, 0),
        7: (sdl2.SDLK_r, 0),
        8: (sdl2.SDLK_SPACE, 0),
    },
    # ProjectM manager context: nav/focus/search/commit/close.
    'projectm_manager': {
        1: (sdl2.SDLK_UP, 0),
        2: (sdl2.SDLK_DOWN, 0),
        3: (sdl2.SDLK_LEFT, 0),
        4: (sdl2.SDLK_RIGHT, 0),
        5: (sdl2.SDLK_RETURN, 0),
        6: (sdl2.SDLK_TAB, 0),
        7: (sdl2.SDLK_SLASH, 0),
        8: (sdl2.SDLK_ESCAPE, 0),
    },
    # Controller help context: close-focused with minimal navigation.
    'controller_help': {
        1: (sdl2.SDLK_UP, 0),
        2: (sdl2.SDLK_DOWN, 0),
        3: (sdl2.SDLK_LEFT, 0),
        4: (sdl2.SDLK_RIGHT, 0),
        5: (sdl2.SDLK_TAB, 0),
        6: (sdl2.SDLK_h, 0),
        7: (sdl2.SDLK_ESCAPE, 0),
        8: (sdl2.SDLK_h, sdl2.KMOD_CTRL | sdl2.KMOD_ALT),
    },
    # Webcam editor context.
    'webcam_editor': {
        1: (sdl2.SDLK_UP, 0),
        2: (sdl2.SDLK_DOWN, 0),
        3: (sdl2.SDLK_LEFTBRACKET, 0),
        4: (sdl2.SDLK_RIGHTBRACKET, 0),
        5: (sdl2.SDLK_RETURN, 0),
        6: (sdl2.SDLK_e, 0),
        7: (sdl2.SDLK_r, 0),
        8: (sdl2.SDLK_k, sdl2.KMOD_CTRL | sdl2.KMOD_ALT),
    },
}


class HotkeyHandler:
    def __init__(
        self,
        app: "App",
        playlist: "Playlist",
        overlays: "Overlays",
        audio_manager: "AudioManager",
    ) -> None:
        self._app = app
        self._playlist = playlist
        self._overlays = overlays
        self._audio = audio_manager
        self._projectm_preview_origin_path: str = ''
        self._projectm_preview_committed_path: str = ''
        self._projectm_preview_dirty: bool = False
        self._projectm_search_mode: bool = False
        self._effects_browser_search_mode: bool = False
        self._pending_midi_events: deque[MidiEvent] = deque()
        self._midi_lock = threading.Lock()

    def attach_midi(self, midi: "MidiManager") -> None:
        """Register MIDI event listener after construction."""
        midi.add_listener(self._on_midi)

    def _on_midi(self, event: "MidiEvent") -> None:
        with self._midi_lock:
            self._pending_midi_events.append(event)

    def process_pending_midi(self) -> None:
        """Dispatch queued MIDI input on the main thread."""
        with self._midi_lock:
            events = list(self._pending_midi_events)
            self._pending_midi_events.clear()
        for event in events:
            self._dispatch_midi_event(event)

    def _dispatch_midi_event(self, event: "MidiEvent") -> None:
        a = self._app
        o = self._overlays
        if event.type == 'note_on':
            action_raw = a.midi_action_for_note(event.number)
            action = str(action_raw or '').strip().lower()
            if not action:
                return

            if self._dispatch_contextual_midi_action(action):
                return

            if action.startswith('context_slot_'):
                suffix = action.removeprefix('context_slot_')
                if suffix.isdigit() and self._dispatch_context_slot(int(suffix)):
                    return

            if action.startswith('postfx_'):
                suffix = action.removeprefix('postfx_')
                key_code = None
                if suffix.isdigit():
                    idx = int(suffix)
                    if idx == 10:
                        key_code = sdl2.SDLK_0
                    elif 1 <= idx <= 9:
                        key_code = sdl2.SDLK_1 + (idx - 1)
                if key_code is not None:
                    self.handle(key_code, sdl2.KMOD_CTRL | sdl2.KMOD_ALT)
                    return

            binding = _MIDI_NOTE_KEY_BINDINGS.get(action)
            if binding is not None:
                self.handle(binding[0], binding[1])
                return

            log.debug('MIDI: unmapped note action %r for note %d', action_raw, event.number)
        elif event.type == 'cc':
            effect = a.current_effect
            if effect is not None:
                param = a.midi_param_for_cc(event.number)
                if param and param in effect.parameters:
                    lo, hi = 0.1, 4.0
                    effect.parameters[param] = lo + event.value * (hi - lo)
                    o.flash_message(f'MIDI {param}: {effect.parameters[param]:.2f}', 1.0)

    def _dispatch_contextual_midi_action(self, action: str) -> bool:
        """Dispatch selector/context navigation actions without hardcoding notes."""
        up_actions = {'context_up', 'nav_up', 'select_up'}
        down_actions = {'context_down', 'nav_down', 'select_down'}
        left_actions = {'context_left', 'nav_left'}
        right_actions = {'context_right', 'nav_right'}
        select_actions = {'context_select', 'select', 'apply'}
        back_actions = {'context_back', 'back', 'cancel'}

        if action in up_actions:
            self.handle(sdl2.SDLK_UP, 0)
            return True
        if action in down_actions:
            self.handle(sdl2.SDLK_DOWN, 0)
            return True
        if action in left_actions:
            self.handle(sdl2.SDLK_LEFT, 0)
            return True
        if action in right_actions:
            self.handle(sdl2.SDLK_RIGHT, 0)
            return True
        if action in select_actions:
            self.handle(sdl2.SDLK_RETURN, 0)
            return True
        if action in back_actions:
            self.handle(sdl2.SDLK_ESCAPE, 0)
            return True
        return False

    def _active_midi_context(self) -> str:
        """Resolve the current MIDI context for slot-dispatch actions."""
        o = self._overlays
        if bool(getattr(o, 'presets_visible', False)):
            return 'presets'
        if bool(getattr(o, 'effects_browser_visible', False)):
            return 'effects_browser'
        if bool(getattr(o, 'webcam_editor_modal_visible', False)):
            return 'webcam_editor'
        if bool(getattr(o, 'projectm_manager_visible', False)):
            return 'projectm_manager'
        if bool(getattr(o, 'controller_help_modal_visible', False)):
            return 'controller_help'
        if bool(getattr(o, 'audio_selector_visible', False)):
            return 'audio_selector'
        if bool(getattr(o, 'midi_selector_visible', False)):
            return 'midi_selector'
        if bool(getattr(o, 'help_visible', False)):
            return 'help'
        if bool(getattr(o, 'system_monitor_modal_visible', False)):
            return 'system_monitor'
        return 'performance'

    def _dispatch_context_slot(self, slot: int) -> bool:
        """Dispatch a context slot action based on the active UI/runtime mode."""
        if slot < 1 or slot > 8:
            return False
        context = self._active_midi_context()
        binding = _MIDI_CONTEXT_SLOT_BINDINGS.get(context, {}).get(slot)
        if binding is None:
            binding = _MIDI_CONTEXT_SLOT_BINDINGS['performance'].get(slot)
        if binding is None:
            return False
        self.handle(binding[0], binding[1])
        return True

    def _dispatch_shortcut_slot(self, idx: int, a: "App", o: "Overlays") -> None:
        """Jump to the effect at numeric-hotkey slot ``idx`` (0-39), if any.

        Slots are recomputed fresh from the playlist's *enabled* effects on
        every call (see Playlist.shortcut_effects) so the mapping dynamically
        re-packs as effects are enabled/disabled/pinned — never a stale cache.
        A slot beyond the current enabled count is a graceful no-op with a
        flash message rather than wrapping around to an unrelated effect.
        """
        effects = self._playlist.shortcut_effects
        if not (0 <= idx < len(effects)):
            o.flash_message(f'Key {hotkey_slot_label(idx)}: no effect assigned', 1.0)
            return
        cls = effects[idx]
        log.info("Scene change → %s (key index %d)", cls.NAME, idx)
        a.goto_effect(cls)
        o.flash_name(cls.NAME)

    def handle(self, sym: int, mod: int) -> None:
        a = self._app
        p = self._playlist
        o = self._overlays
        sym_name = sdl2.SDL_GetKeyName(sym)
        if isinstance(sym_name, bytes):
            sym_name = sym_name.decode("utf-8", errors="replace")
        log.debug("Key: %s (mod=0x%04x)", sym_name, mod)

        mod_labels: list[str] = []
        if mod & sdl2.KMOD_CTRL:
            mod_labels.append('CTRL')
        if mod & sdl2.KMOD_SHIFT:
            mod_labels.append('SHIFT')
        if mod & sdl2.KMOD_ALT:
            mod_labels.append('ALT')
        if mod & sdl2.KMOD_GUI:
            mod_labels.append('GUI')

        # Keystroke logger — capture key + beat context if enabled.
        ks_log = getattr(a, '_keystroke_logger', None)
        if ks_log is not None:
            _vj = a.auto_vj_controller
            _grid = getattr(_vj, '_grid', None) if _vj is not None else None
            ks_log.log_key(
                sym_name,
                effect_name=a.current_effect_name,
                modifiers=mod_labels,
                bpm=float(getattr(_grid, 'bpm', 0.0) or 0.0),
                beat_phase=float(getattr(_grid, 'beat_phase', 0.0) or 0.0),
                energy=float(getattr(_grid, 'energy', 0.0) or 0.0),
                vj_mode=str(getattr(_vj, '_mode', '')),
            )

        # Phase 1 Auto VJ guard: user input should pause automation briefly.
        # Passive keys intentionally excluded: TAB, h, and ?.
        is_plain_h = sym == sdl2.SDLK_h and not (mod & sdl2.KMOD_SHIFT)
        is_question = sym == sdl2.SDLK_QUESTION or (
            sym == sdl2.SDLK_SLASH and (mod & sdl2.KMOD_SHIFT)
        )
        is_modifier_key = sym in {
            sdl2.SDLK_LSHIFT, sdl2.SDLK_RSHIFT,
            sdl2.SDLK_LCTRL, sdl2.SDLK_RCTRL,
            sdl2.SDLK_LALT, sdl2.SDLK_RALT,
            sdl2.SDLK_LGUI, sdl2.SDLK_RGUI,
        }
        is_system_combo = (
            ((mod & sdl2.KMOD_ALT) and sym == sdl2.SDLK_TAB)
            or ((mod & sdl2.KMOD_ALT) and sym == sdl2.SDLK_F4)
            or bool(mod & sdl2.KMOD_GUI)
        )
        # Non-visual controls should not force Auto VJ into USER hold.
        is_non_visual = sym in {
            sdl2.SDLK_v,        # recording toggle
            sdl2.SDLK_h,        # help overlay
            sdl2.SDLK_TAB,      # HUD toggle
        }
        is_passive = (
            sym == sdl2.SDLK_TAB
            or is_plain_h
            or is_question
            or is_modifier_key
            or is_system_combo
            or is_non_visual
        )
        is_auto_vj_control = (
            ((mod & sdl2.KMOD_CTRL) and (mod & sdl2.KMOD_ALT) and sym == sdl2.SDLK_j)
            or ((mod & sdl2.KMOD_CTRL) and sym == sdl2.SDLK_j)
            or bool(getattr(a.auto_vj_controller, '_ctrlj_armed', False))
        )
        if not is_passive and not is_auto_vj_control:
            a.vj_api.mark_user_action('key')

        effect = a.current_effect

        def _projectm_manager_effect():
            current = a.resolve_projectm_manager_effect()
            if current is None:
                log.info('ProjectM manager unavailable: no ProjectM effect instance could be resolved')
                return None
            required = (
                'preset_catalog',
                'goto_preset_path',
                'enable_all_presets',
                'disable_all_presets',
                'enable_category',
                'disable_category',
                'isolate_category',
                'set_presets_enabled',
                'delete_presets',
                'undo_last_bulk_state_change',
                'redo_last_bulk_state_change',
            )
            for name in required:
                if not callable(getattr(current, name, None)):
                    log.info(
                        'ProjectM manager unavailable for effect %s: missing %s',
                        getattr(current, 'NAME', current.__class__.__name__),
                        name,
                    )
                    return None
            return current

        def _sync_projectm_manager():
            manager_effect = _projectm_manager_effect()
            if manager_effect is None:
                return None
            catalog = manager_effect.preset_catalog()
            current_path = str(getattr(manager_effect, 'current_preset_path', '') or '')
            log.debug(
                'ProjectM manager sync: effect=%s catalog=%d current=%s',
                getattr(manager_effect, 'NAME', manager_effect.__class__.__name__),
                len(catalog),
                current_path,
            )
            o.set_projectm_manager_entries(catalog, current_path)
            return manager_effect

        def _set_projectm_manager_visible(visible: bool) -> None:
            visible = bool(visible)
            if bool(getattr(o, 'projectm_manager_visible', False)) != visible:
                o.toggle_projectm_manager()
            setter = getattr(a, 'set_projectm_manager_modal_active', None)
            if callable(setter):
                setter(visible)
            if not visible:
                self._projectm_preview_origin_path = ''
                self._projectm_preview_committed_path = ''
                self._projectm_preview_dirty = False
                self._projectm_search_mode = False
                o.clear_projectm_search_query()

        def _preview_projectm_selection(manager_effect) -> str | None:
            selected = o.get_projectm_selected_preset()
            if selected is None or not bool(selected.get('enabled', False)):
                return None
            target_path = str(selected.get('path', '') or '')
            if not target_path:
                return None
            current_path = str(getattr(manager_effect, 'current_preset_path', '') or '')
            if current_path == target_path:
                return getattr(manager_effect, '_active_label', None)
            result = manager_effect.goto_preset_path(target_path)
            if result:
                committed = self._projectm_preview_committed_path
                self._projectm_preview_dirty = bool(committed and target_path != committed)
                _sync_projectm_manager()
            return result

        def _commit_projectm_selection() -> None:
            selected = o.get_projectm_selected_preset()
            if selected is None:
                return
            target_path = str(selected.get('path', '') or '')
            if not target_path:
                return
            self._projectm_preview_committed_path = target_path
            self._projectm_preview_dirty = False

        def _close_projectm_manager_with_revert(manager_effect) -> None:
            if self._projectm_preview_dirty and self._projectm_preview_committed_path:
                restored = manager_effect.goto_preset_path(self._projectm_preview_committed_path)
                _sync_projectm_manager()
                if restored:
                    o.flash_message(f'ProjectM reverted: {restored}', 1.6)
            _set_projectm_manager_visible(False)

        def _projectm_search_char() -> str:
            if sdl2.SDLK_a <= sym <= sdl2.SDLK_z:
                base = chr(ord('a') + (sym - sdl2.SDLK_a))
                if mod & sdl2.KMOD_SHIFT:
                    return base.upper()
                return base
            if sdl2.SDLK_0 <= sym <= sdl2.SDLK_9:
                return chr(ord('0') + (sym - sdl2.SDLK_0))
            if sdl2.SDLK_KP_0 <= sym <= sdl2.SDLK_KP_9:
                return chr(ord('0') + (sym - sdl2.SDLK_KP_0))
            if sym == sdl2.SDLK_SPACE:
                return ' '
            if sym in (sdl2.SDLK_MINUS, sdl2.SDLK_KP_MINUS):
                return '-'
            if sym in (sdl2.SDLK_PERIOD, sdl2.SDLK_KP_PERIOD):
                return '.'
            if sym in (sdl2.SDLK_SLASH, sdl2.SDLK_KP_DIVIDE):
                return '/'
            return ''

        def _refresh_webcam_editor_payload() -> None:
            devices = a.vj_api.list_webcam_cameras()
            image_state = a.vj_api.webcam_image_state()
            setter = getattr(o, 'set_webcam_editor_data', None)
            if callable(setter):
                setter(devices, image_state)

        # Effect-local Ctrl+Shift+N/Ctrl+Shift+P/Ctrl+Shift+R variant navigation.
        if (mod & sdl2.KMOD_CTRL) and (mod & sdl2.KMOD_SHIFT) and effect is not None:
            if sym == sdl2.SDLK_n:
                method = getattr(effect, 'next_variant', None)
                if callable(method):
                    result = method()
                    if result:
                        o.flash_message(f'Variant: {result}', 1.5)
                    return
            elif sym == sdl2.SDLK_p:
                method = getattr(effect, 'prev_variant', None)
                if callable(method):
                    result = method()
                    if result:
                        o.flash_message(f'Variant: {result}', 1.5)
                    return
            elif sym == sdl2.SDLK_r:
                method = getattr(effect, 'random_variant', None)
                if callable(method):
                    result = method()
                    if result:
                        o.flash_message(f'Variant: {result}', 1.5)
                    return

        # Effect-local Ctrl+N/Ctrl+P/Ctrl+R navigation when supported.
        if mod & sdl2.KMOD_CTRL and effect is not None:
            if sym == sdl2.SDLK_n:
                for method_name, label in (
                    ('next_preset', 'Preset'),
                    ('next_scene', 'Scene'),
                    ('next_variant', 'Variant'),
                ):
                    method = getattr(effect, method_name, None)
                    if callable(method):
                        result = method()
                        if result:
                            o.flash_message(f'{label}: {result}', 1.5)
                        else:
                            o.flash_message(f'{label}: nothing loaded', 1.5)
                        return
            elif sym == sdl2.SDLK_p:
                for method_name, label in (
                    ('prev_preset', 'Preset'),
                    ('prev_scene', 'Scene'),
                    ('prev_variant', 'Variant'),
                ):
                    method = getattr(effect, method_name, None)
                    if callable(method):
                        result = method()
                        if result:
                            o.flash_message(f'{label}: {result}', 1.5)
                        else:
                            o.flash_message(f'{label}: nothing loaded', 1.5)
                        return
            elif sym == sdl2.SDLK_r:
                for method_name, label in (
                    ('random_preset', 'Preset'),
                    ('random_scene', 'Scene'),
                    ('random_variant', 'Variant'),
                ):
                    method = getattr(effect, method_name, None)
                    if callable(method):
                        result = method()
                        if result:
                            o.flash_message(f'{label}: {result}', 1.5)
                        else:
                            o.flash_message(f'{label}: nothing loaded', 1.5)
                        return

        # Registered drop-in key handlers.
        # Skip drop-in dispatch while any text-entry mode is active so that
        # character keys (bare/shift) reach the modal handler instead of
        # accidentally firing a drop-in hotkey (e.g. C toggling chat mid-search).
        _get_sub = getattr(a.vj_api, 'get_subsystem', None)
        _cta_editor_open = bool(getattr(
            _get_sub('cta') if callable(_get_sub) else None,
            'editor_open', False,
        ))
        _user_typing = (
            not _cta_editor_open
            and (
                self._effects_browser_search_mode
                or self._projectm_search_mode
                or (getattr(o, 'presets_visible', False) and getattr(o, 'presets_name_mode', False))
            )
        )
        if not _user_typing:
            for _name, _handler in a.vj_api.key_handler_items():
                try:
                    _result = _handler(sym, mod)
                except Exception:
                    log.exception('Key handler %r raised; unregistering', _name)
                    a.vj_api.unregister_key_handler(_name)
                    continue
                if _result is not False:
                    if isinstance(_result, str) and _result:
                        o.flash_message(_result, 2.0)
                    return

        # Help overlay interaction mode: section expand/collapse and focus nav.
        if getattr(o, 'help_visible', False):
            o.note_help_activity()
            focus_region_getter = getattr(o, 'help_focus_region', None)
            focus_region = focus_region_getter() if callable(focus_region_getter) else 'sections'
            if sym == sdl2.SDLK_TAB:
                if o.toggle_help_focus_region():
                    return
            if focus_region == 'icons':
                if sym in (sdl2.SDLK_LEFT, sdl2.SDLK_UP):
                    if o.move_help_icon_focus(-1):
                        return
                elif sym in (sdl2.SDLK_RIGHT, sdl2.SDLK_DOWN):
                    if o.move_help_icon_focus(1):
                        return
                elif sym in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
                    if o.activate_help_focus_item():
                        pop_action = getattr(o, 'pop_help_icon_action', None)
                        action = pop_action() if callable(pop_action) else None
                        if isinstance(action, dict):
                            msg = a.handle_help_icon_action(action)
                            if msg:
                                o.flash_message(msg, 1.6)
                        return
                elif sym in (sdl2.SDLK_ESCAPE,):
                    pass
                elif ((mod & sdl2.KMOD_SHIFT) and sym in (sdl2.SDLK_EQUALS, sdl2.SDLK_PLUS)) or sym == sdl2.SDLK_KP_PLUS:
                    return
                elif ((mod & sdl2.KMOD_SHIFT) and sym == sdl2.SDLK_MINUS) or sym == sdl2.SDLK_KP_MINUS:
                    return
                # Icon focus intentionally ignores the section collapse shortcuts.
            else:
                # Toggle by section number: supports top-row, shifted symbols, and keypad.
                shift_digit_syms = [
                    sdl2.SDLK_EXCLAIM, sdl2.SDLK_AT, sdl2.SDLK_HASH,
                    sdl2.SDLK_DOLLAR, sdl2.SDLK_PERCENT, sdl2.SDLK_CARET,
                    sdl2.SDLK_AMPERSAND, sdl2.SDLK_ASTERISK,
                    sdl2.SDLK_LEFTPAREN, sdl2.SDLK_RIGHTPAREN,
                ]
                if sdl2.SDLK_1 <= sym <= sdl2.SDLK_9:
                    if o.toggle_help_section(sym - sdl2.SDLK_1):
                        return
                elif sym == sdl2.SDLK_0:
                    if o.toggle_help_section(9):
                        return
                elif sym in shift_digit_syms:
                    if o.toggle_help_section(shift_digit_syms.index(sym)):
                        return
                elif sdl2.SDLK_KP_1 <= sym <= sdl2.SDLK_KP_9:
                    if o.toggle_help_section(sym - sdl2.SDLK_KP_1):
                        return
                elif sym == sdl2.SDLK_KP_0:
                    if o.toggle_help_section(9):
                        return
                elif sym == sdl2.SDLK_UP:
                    if o.move_help_focus(-1):
                        return
                elif sym == sdl2.SDLK_DOWN:
                    if o.move_help_focus(1):
                        return
                elif sym == sdl2.SDLK_LEFT:
                    if o.move_help_focus(-1):
                        return
                elif sym == sdl2.SDLK_RIGHT:
                    if o.move_help_focus(1):
                        return
                elif sym in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
                    if o.toggle_help_focus_section():
                        return
                elif ((mod & sdl2.KMOD_SHIFT) and sym in (sdl2.SDLK_EQUALS, sdl2.SDLK_PLUS)) or sym == sdl2.SDLK_KP_PLUS:
                    o.set_all_help_sections_collapsed(False)
                    o.flash_message('Help: expanded all sections', 1.2)
                    return
                elif ((mod & sdl2.KMOD_SHIFT) and sym == sdl2.SDLK_MINUS) or sym == sdl2.SDLK_KP_MINUS:
                    o.set_all_help_sections_collapsed(True)
                    o.flash_message('Help: collapsed all sections', 1.2)
                    return

        # Audio selector navigation — active when the audio source picker is open.
        if o.audio_selector_visible:
            o.note_help_activity()
            if sym in (sdl2.SDLK_UP, sdl2.SDLK_LEFT):
                o.move_audio_selection(-1)
                return
            elif sym in (sdl2.SDLK_DOWN, sdl2.SDLK_RIGHT):
                o.move_audio_selection(1)
                return
            elif sym == sdl2.SDLK_t:
                source_idx = o.get_audio_selected_index()
                msg = a.toggle_audio_source_viable(source_idx)
                o.toggle_audio_selected_viable()
                o.flash_message(msg, 2.0)
                return
            elif sym in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
                source_idx = o.get_audio_selected_index()
                msg = a.select_audio_source(source_idx)
                o.toggle_audio_selector()
                o.flash_message(msg, 2.5)
                return
            # Any other key falls through to ESC check below.

        if getattr(o, 'webcam_editor_modal_visible', False):
            o.note_help_activity()
            _refresh_webcam_editor_payload()
            if sym in (sdl2.SDLK_UP, sdl2.SDLK_LEFT):
                o.move_webcam_editor_selection(-1)
                return
            elif sym in (sdl2.SDLK_DOWN, sdl2.SDLK_RIGHT):
                o.move_webcam_editor_selection(1)
                return
            elif sym in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
                camera_id = o.get_webcam_editor_selected_camera_id()
                if camera_id is None or camera_id < 0:
                    o.flash_message('Webcam: no camera selected', 1.2)
                    return
                label = a.vj_api.set_active_webcam_camera(camera_id)
                if label is None:
                    o.flash_message('Webcam: unable to switch camera', 1.4)
                else:
                    o.flash_message(f'Webcam camera: {label}', 1.4)
                _refresh_webcam_editor_payload()
                return
            elif sym == sdl2.SDLK_e:
                camera_id = o.get_webcam_editor_selected_camera_id()
                if camera_id is None or camera_id < 0:
                    o.flash_message('Webcam: no camera selected', 1.2)
                    return
                devices = a.vj_api.list_webcam_cameras()
                target_enabled = None
                for dev in devices:
                    if int(dev.get('id', -1)) == int(camera_id):
                        target_enabled = not bool(dev.get('enabled', True))
                        break
                if target_enabled is None:
                    o.flash_message('Webcam: camera unavailable', 1.2)
                    return
                ok = a.vj_api.set_webcam_camera_enabled(camera_id, target_enabled)
                if ok:
                    o.flash_message(
                        f'Webcam camera {camera_id}: {"enabled" if target_enabled else "disabled"}',
                        1.4,
                    )
                else:
                    o.flash_message('Webcam: camera unavailable', 1.2)
                _refresh_webcam_editor_payload()
                return
            elif sym == sdl2.SDLK_r:
                devices = a.vj_api.rediscover_webcam_cameras()
                o.flash_message(f'Webcam rediscover: {len(devices)} found', 1.4)
                _refresh_webcam_editor_payload()
                return
            elif sym == sdl2.SDLK_h:
                active = a.vj_api.toggle_webcam_flip_horizontal()
                o.flash_message(f'Webcam flip H: {"ON" if active else "OFF"}', 1.3)
                _refresh_webcam_editor_payload()
                return
            elif sym == sdl2.SDLK_v:
                active = a.vj_api.toggle_webcam_flip_vertical()
                o.flash_message(f'Webcam flip V: {"ON" if active else "OFF"}', 1.3)
                _refresh_webcam_editor_payload()
                return
            elif sym == sdl2.SDLK_LEFTBRACKET:
                value = a.vj_api.adjust_webcam_brightness(-0.05)
                o.flash_message(f'Webcam brightness {value:.2f}', 1.2)
                _refresh_webcam_editor_payload()
                return
            elif sym == sdl2.SDLK_RIGHTBRACKET:
                value = a.vj_api.adjust_webcam_brightness(0.05)
                o.flash_message(f'Webcam brightness {value:.2f}', 1.2)
                _refresh_webcam_editor_payload()
                return
            elif sym == sdl2.SDLK_SEMICOLON:
                value = a.vj_api.adjust_webcam_contrast(-0.05)
                o.flash_message(f'Webcam contrast {value:.2f}', 1.2)
                _refresh_webcam_editor_payload()
                return
            elif sym == sdl2.SDLK_QUOTE:
                value = a.vj_api.adjust_webcam_contrast(0.05)
                o.flash_message(f'Webcam contrast {value:.2f}', 1.2)
                _refresh_webcam_editor_payload()
                return
            elif (mod & sdl2.KMOD_CTRL) and (mod & sdl2.KMOD_ALT) and sym == sdl2.SDLK_k:
                o.toggle_webcam_editor_modal()
                return
            # Any other key falls through to ESC handling.

        # MIDI selector navigation — active when the MIDI device picker is open.
        if o.midi_selector_visible:
            o.note_help_activity()
            if sym in (sdl2.SDLK_UP, sdl2.SDLK_LEFT):
                o.move_midi_selection(-1)
                return
            elif sym in (sdl2.SDLK_DOWN, sdl2.SDLK_RIGHT):
                o.move_midi_selection(1)
                return
            elif sym in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
                port = o.get_midi_selected_port()
                msg = a.select_midi_device(port)
                o.toggle_midi_selector()
                o.flash_message(msg, 2.5)
                return
            # Any other key falls through to ESC check below.

        if getattr(o, 'presets_visible', False):
            pb = o.presets_browser
            if o.presets_name_mode:
                if sym == sdl2.SDLK_ESCAPE:
                    o.set_presets_name_mode(False)
                    return
                if sym in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
                    name = o.presets_name_text.strip()
                    o.set_presets_name_mode(False)
                    if name:
                        saved = a.presets_save_named(name)
                        if saved:
                            o.flash_message(f'Preset saved: {saved}', 1.6)
                    return
                if sym == sdl2.SDLK_BACKSPACE:
                    o.set_presets_name_text(o.presets_name_text[:-1])
                    return
                ch = _projectm_search_char()
                if ch:
                    o.set_presets_name_text(o.presets_name_text + ch)
                return

            if sym == sdl2.SDLK_ESCAPE:
                a.close_presets()
                return
            if sym == sdl2.SDLK_UP:
                pb.move_selection(-1)
                return
            if sym == sdl2.SDLK_DOWN:
                pb.move_selection(1)
                return
            if sym in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
                name = a.presets_load_selected()
                if name:
                    o.flash_message(f'Preset loaded: {name}', 1.6)
                return
            if sym == sdl2.SDLK_s and not (mod & (sdl2.KMOD_CTRL | sdl2.KMOD_ALT | sdl2.KMOD_GUI)):
                o.set_presets_name_text('')
                o.set_presets_name_mode(True)
                return
            if sym in (sdl2.SDLK_d, sdl2.SDLK_DELETE) and not (mod & (sdl2.KMOD_CTRL | sdl2.KMOD_ALT | sdl2.KMOD_GUI)):
                name = a.presets_delete_selected()
                if name:
                    o.flash_message(f'Preset deleted: {name}', 1.4)
                return
            # Swallow all other keys while the presets modal is open.
            return

        if getattr(o, 'effects_browser_visible', False):
            b = o.effects_browser
            if self._effects_browser_search_mode:
                if sym == sdl2.SDLK_ESCAPE:
                    self._effects_browser_search_mode = False
                    b.set_search_mode(False)
                    return
                if sym in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
                    self._effects_browser_search_mode = False
                    b.set_search_mode(False)
                    a.effects_browser_mark_nav()
                    return
                if (mod & sdl2.KMOD_CTRL) and sym == sdl2.SDLK_BACKSPACE:
                    b.clear_search_query()
                    a.effects_browser_mark_nav()
                    return
                if sym == sdl2.SDLK_BACKSPACE:
                    q = b.search_query
                    if q:
                        b.set_search_query(q[:-1])
                        a.effects_browser_mark_nav()
                    return
                ch = _projectm_search_char()
                if ch:
                    b.set_search_query(b.search_query + ch)
                    a.effects_browser_mark_nav()
                return

            if sym == sdl2.SDLK_ESCAPE or (
                sym == sdl2.SDLK_b
                and not (mod & (sdl2.KMOD_CTRL | sdl2.KMOD_SHIFT | sdl2.KMOD_ALT | sdl2.KMOD_GUI))
            ):
                a.close_effects_browser(commit=False)
                return
            if sym == sdl2.SDLK_SLASH and not (mod & (sdl2.KMOD_CTRL | sdl2.KMOD_ALT | sdl2.KMOD_GUI | sdl2.KMOD_SHIFT)):
                self._effects_browser_search_mode = True
                b.set_search_mode(True)
                o.flash_message('Effects search: type to filter', 1.2)
                return
            if sym == sdl2.SDLK_TAB:
                b.toggle_focus_pane()
                return
            if sym == sdl2.SDLK_LEFT:
                b.set_focus_pane(PANE_CATEGORIES)
                return
            if sym == sdl2.SDLK_RIGHT:
                b.set_focus_pane(PANE_LIST)
                return
            if sym == sdl2.SDLK_UP:
                if b.focus_pane() == PANE_CATEGORIES:
                    b.move_category(-1)
                else:
                    b.set_focus_pane(PANE_LIST)
                    b.move_selection(-1)
                a.effects_browser_mark_nav()
                return
            if sym == sdl2.SDLK_DOWN:
                if b.focus_pane() == PANE_CATEGORIES:
                    b.move_category(1)
                else:
                    b.set_focus_pane(PANE_LIST)
                    b.move_selection(1)
                a.effects_browser_mark_nav()
                return
            if sym in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
                name = a.effects_browser_commit()
                if name:
                    o.flash_message(f'Effect: {name}', 1.4)
                return
            if sym == sdl2.SDLK_p and not (mod & (sdl2.KMOD_CTRL | sdl2.KMOD_ALT | sdl2.KMOD_GUI)):
                msg = a.effects_browser_pin()
                if msg:
                    o.flash_message(msg, 1.6)
                return
            if sym == sdl2.SDLK_SPACE:
                msg = a.effects_browser_toggle_enabled()
                if msg:
                    o.flash_message(msg, 1.2)
                return
            if (_slot := numeric_slot_index(sym, mod)) is not None:
                # Reuse the same chord that would jump to this slot outside
                # the browser to pin/unpin the selected effect to it.
                msg = a.effects_browser_toggle_pin_slot(_slot)
                if msg:
                    o.flash_message(msg, 1.6)
                return
            # Swallow all other keys while the browser is open.
            return

        if getattr(o, 'projectm_manager_visible', False):
            manager_effect = _sync_projectm_manager()
            if manager_effect is None:
                _set_projectm_manager_visible(False)
                o.flash_message('ProjectM manager unavailable', 1.5)
                return

            if self._projectm_search_mode:
                if sym == sdl2.SDLK_ESCAPE:
                    self._projectm_search_mode = False
                    o.flash_message('ProjectM search mode: off', 1.0)
                    return
                if sym in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
                    self._projectm_search_mode = False
                    _preview_projectm_selection(manager_effect)
                    o.flash_message('ProjectM search applied', 1.0)
                    return
                if (mod & sdl2.KMOD_CTRL) and sym == sdl2.SDLK_BACKSPACE:
                    o.clear_projectm_search_query()
                    _preview_projectm_selection(manager_effect)
                    return
                if sym == sdl2.SDLK_BACKSPACE:
                    q = o.projectm_search_query
                    if q:
                        o.set_projectm_search_query(q[:-1])
                        _preview_projectm_selection(manager_effect)
                    return
                ch = _projectm_search_char()
                if ch:
                    o.set_projectm_search_query(o.projectm_search_query + ch)
                    _preview_projectm_selection(manager_effect)
                return

            if sym == sdl2.SDLK_ESCAPE:
                _close_projectm_manager_with_revert(manager_effect)
                return
            if sym == sdl2.SDLK_m and (mod & sdl2.KMOD_CTRL):
                _close_projectm_manager_with_revert(manager_effect)
                return
            if sym == sdl2.SDLK_SLASH and not (mod & (sdl2.KMOD_CTRL | sdl2.KMOD_ALT | sdl2.KMOD_GUI | sdl2.KMOD_SHIFT)):
                self._projectm_search_mode = True
                o.flash_message('ProjectM search mode: type to filter', 1.2)
                return

            if sym == sdl2.SDLK_TAB:
                o.move_projectm_focus(1)
                return
            if sym == sdl2.SDLK_LEFT:
                o.move_projectm_focus(-1)
                return
            if sym == sdl2.SDLK_RIGHT:
                o.move_projectm_focus(1)
                return
            if sym == sdl2.SDLK_UP:
                if o.projectm_manager_focus_pane == 0:
                    o.move_projectm_category_selection(-1)
                    _preview_projectm_selection(manager_effect)
                else:
                    o.move_projectm_preset_selection(-1)
                    _preview_projectm_selection(manager_effect)
                return
            if sym == sdl2.SDLK_DOWN:
                if o.projectm_manager_focus_pane == 0:
                    o.move_projectm_category_selection(1)
                    _preview_projectm_selection(manager_effect)
                else:
                    o.move_projectm_preset_selection(1)
                    _preview_projectm_selection(manager_effect)
                return
            if sym in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
                if o.projectm_manager_focus_pane == 0:
                    o.move_projectm_focus(1)
                    _preview_projectm_selection(manager_effect)
                    return
                selected = o.get_projectm_selected_preset()
                if selected is None:
                    o.flash_message('ProjectM: no preset selected', 1.2)
                    return
                if not bool(selected.get('enabled', False)):
                    o.flash_message('ProjectM: preset is disabled', 1.4)
                    return
                result = _preview_projectm_selection(manager_effect)
                if result:
                    _commit_projectm_selection()
                    _sync_projectm_manager()
                    o.flash_message(f'Preset committed: {result}', 1.6)
                return
            if (mod & sdl2.KMOD_CTRL) and (mod & sdl2.KMOD_SHIFT) and sym == sdl2.SDLK_a:
                remaining = manager_effect.disable_all_presets()
                _sync_projectm_manager()
                o.flash_message(f'ProjectM: all disabled ({remaining} enabled)', 1.8)
                return
            if (mod & sdl2.KMOD_CTRL) and sym == sdl2.SDLK_a:
                remaining = manager_effect.enable_all_presets()
                _sync_projectm_manager()
                o.flash_message(f'ProjectM: enabled all ({remaining} enabled)', 1.8)
                return
            if (mod & sdl2.KMOD_CTRL) and sym == sdl2.SDLK_z:
                restored = manager_effect.undo_last_bulk_state_change()
                _sync_projectm_manager()
                if restored:
                    o.flash_message(f'ProjectM undo: {restored}', 2.0)
                else:
                    o.flash_message('ProjectM undo: no snapshot available', 1.6)
                return
            if (mod & sdl2.KMOD_CTRL) and (
                sym == sdl2.SDLK_y
                or ((mod & sdl2.KMOD_SHIFT) and sym == sdl2.SDLK_z)
            ):
                restored = manager_effect.redo_last_bulk_state_change()
                _sync_projectm_manager()
                if restored:
                    o.flash_message(f'ProjectM redo: {restored}', 2.0)
                else:
                    o.flash_message('ProjectM redo: no snapshot available', 1.6)
                return
            if sym == sdl2.SDLK_i and o.projectm_manager_focus_pane == 0:
                category = o.get_projectm_selected_category()
                remaining = manager_effect.enable_all_presets() if category == '(all)' else manager_effect.isolate_category(category)
                _sync_projectm_manager()
                o.flash_message(f'ProjectM isolate: {category} ({remaining} enabled)', 1.8)
                return
            if sym == sdl2.SDLK_e:
                if o.projectm_manager_focus_pane == 0:
                    category = o.get_projectm_selected_category()
                    remaining = manager_effect.enable_all_presets() if category == '(all)' else manager_effect.enable_category(category)
                    _sync_projectm_manager()
                    o.flash_message(f'ProjectM enabled: {category} ({remaining} enabled)', 1.8)
                else:
                    selected = o.get_projectm_selected_preset()
                    if selected is None:
                        o.flash_message('ProjectM: no preset selected', 1.2)
                        return
                    remaining = manager_effect.set_presets_enabled([str(selected.get('path', ''))], True)
                    _sync_projectm_manager()
                    o.flash_message(f'ProjectM preset enabled ({remaining} enabled)', 1.6)
                return
            if sym == sdl2.SDLK_d:
                if o.projectm_manager_focus_pane == 0:
                    category = o.get_projectm_selected_category()
                    remaining = manager_effect.disable_all_presets() if category == '(all)' else manager_effect.disable_category(category)
                    _sync_projectm_manager()
                    o.flash_message(f'ProjectM disabled: {category} ({remaining} enabled)', 1.8)
                else:
                    selected = o.get_projectm_selected_preset()
                    if selected is None:
                        o.flash_message('ProjectM: no preset selected', 1.2)
                        return
                    remaining = manager_effect.set_presets_enabled([str(selected.get('path', ''))], False)
                    _sync_projectm_manager()
                    o.flash_message(f'ProjectM preset disabled ({remaining} enabled)', 1.6)
                return
            if sym == sdl2.SDLK_DELETE:
                selected = o.get_projectm_selected_preset()
                if selected is None:
                    o.flash_message('ProjectM: no preset selected', 1.2)
                    return
                permanent = bool(mod & sdl2.KMOD_SHIFT)
                deleted = manager_effect.delete_presets([str(selected.get('path', ''))], permanent=permanent)
                if deleted > 0:
                    _sync_projectm_manager()
                    o.flash_message('ProjectM preset hard-deleted' if permanent else 'ProjectM preset moved to trash', 1.8)
                else:
                    o.flash_message('ProjectM delete failed', 1.6)
                return
            return

        # No modal consumed this key. Translate a rebound chord back to its
        # action's default chord (a no-op unless the operator has an override
        # set) so the unmodified global dispatch below fires as if the
        # default chord had been pressed. See App.hotkey_overrides().
        _get_overrides = getattr(a, 'hotkey_overrides', None)
        if callable(_get_overrides):
            sym, mod = translate_override_chord(sym, mod, _get_overrides())

        if sym == sdl2.SDLK_ESCAPE:
            # ESC closes the currently-open menu first; only exits when no menu is open.
            if getattr(o, 'help_visible', False):
                o.toggle_help()
                return
            if o.name_overlay_visible:
                o.toggle_name_overlay()
                return
            if getattr(o, 'system_monitor_modal_visible', False):
                o.toggle_system_monitor_modal()
                return
            if getattr(o, 'controller_help_modal_visible', False):
                o.toggle_controller_help_modal()
                return
            if getattr(o, 'webcam_editor_modal_visible', False):
                o.toggle_webcam_editor_modal()
                return
            if o.audio_selector_visible:
                o.toggle_audio_selector()
                return
            if o.midi_selector_visible:
                o.toggle_midi_selector()
                return
            if getattr(o, 'projectm_manager_visible', False):
                _set_projectm_manager_visible(False)
                return
            a.request_exit()

        elif sym in (sdl2.SDLK_n, sdl2.SDLK_RIGHT):
            if p.mode == "random":
                cls = p.advance()
                log.info("Scene change → %s (random next)", cls.NAME)
            else:
                cls = p.go_index(p.index + 1)
                log.info("Scene change → %s (next)", cls.NAME)
            a.goto_effect(cls)
            o.flash_name(cls.NAME)

        elif sym in (sdl2.SDLK_p, sdl2.SDLK_LEFT):
            if sym == sdl2.SDLK_p and (mod & sdl2.KMOD_CTRL) and (mod & sdl2.KMOD_SHIFT):
                a.open_presets()
            elif p.mode == "random":
                cls = p.advance()
                log.info("Scene change → %s (random prev)", cls.NAME)
                a.goto_effect(cls)
                o.flash_name(cls.NAME)
            else:
                cls = p.go_index(p.index - 1)
                log.info("Scene change → %s (prev)", cls.NAME)
                a.goto_effect(cls)
                o.flash_name(cls.NAME)

        elif sym == sdl2.SDLK_f:
            a.toggle_fullscreen()

        elif sym == sdl2.SDLK_SPACE:
            a.toggle_pause()
            o.flash_message("PAUSED" if a.paused else "RESUMED", 1.5)

        elif sym == sdl2.SDLK_TAB:
            o.toggle_name_overlay()

        elif sym == sdl2.SDLK_h:
            if (mod & sdl2.KMOD_CTRL) and (mod & sdl2.KMOD_ALT):
                o.toggle_controller_help_modal()
            elif mod & sdl2.KMOD_SHIFT:
                # H (Shift+h) — toggle flash message notifications
                enabled = o.toggle_flash_messages()
                # Force-render the status even if flash was just turned on.
                o.set_flash_messages_enabled(True)
                o.flash_message('Notifications ON' if enabled else 'Notifications OFF', 1.5)
                if not enabled:
                    o.set_flash_messages_enabled(False)
            else:
                # h — toggle help overlay
                o.toggle_help()

        elif sym == sdl2.SDLK_k:
            if (mod & sdl2.KMOD_CTRL) and (mod & sdl2.KMOD_ALT):
                _refresh_webcam_editor_payload()
                o.toggle_webcam_editor_modal()

        elif sym == sdl2.SDLK_QUESTION or (
            sym == sdl2.SDLK_SLASH and (mod & sdl2.KMOD_SHIFT)
        ):
            # ? — toggle help (same behavior as lowercase h).
            # Some layouts emit Shift+/ (SDLK_SLASH + KMOD_SHIFT) instead of SDLK_QUESTION.
            o.toggle_help()

        elif sym == sdl2.SDLK_a:
            if (mod & sdl2.KMOD_ALT) and (mod & sdl2.KMOD_SHIFT):
                # Alt+Shift+A — previous audio profile (wraps around)
                profiles = self._audio.list_profiles()
                current_key = self._audio.get_profile_key()
                current_profile = self._audio.get_profile()
                current_idx = profiles.index(current_key) if current_key in profiles else 0
                prev_idx = (current_idx - 1) % len(profiles)
                prev_profile = self._audio.set_profile(profiles[prev_idx])
                o.flash_message(f'BPM Profile: {prev_profile.name}', 1.2)
                log.info('Audio profile changed: %s → %s', current_profile.name, prev_profile.name)
            elif mod & sdl2.KMOD_ALT:
                # Alt+A — next audio profile (wraps around)
                profiles = self._audio.list_profiles()
                current_key = self._audio.get_profile_key()
                current_profile = self._audio.get_profile()
                current_idx = profiles.index(current_key) if current_key in profiles else 0
                next_idx = (current_idx + 1) % len(profiles)
                next_profile = self._audio.set_profile(profiles[next_idx])
                o.flash_message(f'BPM Profile: {next_profile.name}', 1.2)
                log.info('Audio profile changed: %s → %s', current_profile.name, next_profile.name)
            elif (mod & sdl2.KMOD_CTRL) and (mod & sdl2.KMOD_SHIFT):
                # Ctrl+Shift+A is intentionally unbound to avoid conflicts.
                return
            elif (mod & sdl2.KMOD_CTRL) and not (mod & sdl2.KMOD_SHIFT):
                # Ctrl+A — legacy fallback binding for audio source selector
                sources = a.get_audio_sources()
                current_idx = a.get_audio_source_index()
                viable_flags = a.get_audio_source_viable_flags()
                o.set_audio_sources(sources, current_idx, viable_flags)
                o.toggle_audio_selector()
            else:
                # A-family default — open audio source selector menu.
                sources = a.get_audio_sources()
                current_idx = a.get_audio_source_index()
                viable_flags = a.get_audio_source_viable_flags()
                o.set_audio_sources(sources, current_idx, viable_flags)
                o.toggle_audio_selector()

        elif sym == sdl2.SDLK_b:
            if not (mod & (sdl2.KMOD_CTRL | sdl2.KMOD_SHIFT | sdl2.KMOD_ALT | sdl2.KMOD_GUI)):
                a.open_effects_browser()

        elif sym == sdl2.SDLK_m:
            if mod & sdl2.KMOD_CTRL:
                log.info(
                    'Ctrl+M pressed: effect=%s mods=%s',
                    a.current_effect_name or '(none)',
                    '+'.join(mod_labels) or '(none)',
                )
                manager_effect = _sync_projectm_manager()
                if manager_effect is None:
                    log.info(
                        'ProjectM manager open rejected for effect=%s',
                        a.current_effect_name or '(none)',
                    )
                    o.flash_message('ProjectM manager unavailable for this effect', 1.6)
                else:
                    next_state = not o.projectm_manager_visible
                    log.info(
                        'ProjectM manager %s for effect=%s',
                        'opening' if next_state else 'closing',
                        getattr(manager_effect, 'NAME', manager_effect.__class__.__name__),
                    )
                    if next_state:
                        self._projectm_preview_origin_path = str(getattr(manager_effect, 'current_preset_path', '') or '')
                        self._projectm_preview_committed_path = self._projectm_preview_origin_path
                        self._projectm_preview_dirty = False
                        _set_projectm_manager_visible(True)
                        _preview_projectm_selection(manager_effect)
                    else:
                        _close_projectm_manager_with_revert(manager_effect)
            elif mod & sdl2.KMOD_ALT:
                if o.midi_selector_visible:
                    o.toggle_midi_selector()
                else:
                    ports = a.get_midi_ports()
                    current = a._midi_manager.port_name if a._midi_manager is not None else ''  # noqa: SLF001
                    o.set_midi_ports(ports, current)
                    o.toggle_midi_selector()
            elif mod & sdl2.KMOD_SHIFT:
                _active, msg = a.toggle_control_room()
                o.flash_message(msg, 1.6)
            else:
                o.toggle_system_monitor_modal()

        elif sym == sdl2.SDLK_l and (mod & sdl2.KMOD_CTRL):
            # Ctrl+L — toggle ProjectM-only mode (lock the system to ProjectM).
            _on, msg = a.toggle_projectm_only()
            o.flash_message(msg, 1.6)

        elif sym == sdl2.SDLK_c and not (
            mod & (sdl2.KMOD_CTRL | sdl2.KMOD_ALT | sdl2.KMOD_SHIFT)
        ):
            # Naked C — toggle the configuration editor.
            o.toggle_config_editor()

        elif sym == sdl2.SDLK_F6:
            effect = a.current_effect
            # Toggle is global — persists even when current effect lacks 'speed'.
            if a.speed_randomized:
                a.set_speed_randomized(False)
                if effect is not None and 'speed' in effect.parameters:
                    o.flash_message(f'Speed random OFF  {effect.parameters["speed"]:.2f}', 1.2)
                else:
                    o.flash_message('Speed random OFF', 1.2)
            else:
                a.apply_random_speed()
                a.set_speed_randomized(True)
                lo, hi = a.random_range_for('speed', 0.25, 2.50)
                if effect is not None and 'speed' in effect.parameters:
                    o.flash_message(f'Speed random ON  {effect.parameters["speed"]:.2f}  [{lo:.2f}-{hi:.2f}]', 1.6)
                else:
                    o.flash_message(f'Speed random ON  (armed)  [{lo:.2f}-{hi:.2f}]', 1.6)

        elif sym == sdl2.SDLK_F7:
            am = self._audio
            if am is None:
                o.flash_message('Reactivity control not available', 1.2)
                a.set_reactivity_randomized(False)
            else:
                # Toggle randomization on/off
                if a.reactivity_randomized:
                    a.set_reactivity_randomized(False)
                    current = am.get_reactivity()
                    o.flash_message(f'Reactivity random OFF  {current:.2f}', 1.2)
                else:
                    a.apply_random_reactivity()
                    lo, hi = a.random_range_for('reactivity', 0.40, 2.00)
                    current = am.get_reactivity()
                    o.flash_message(f'Reactivity random ON  {current:.2f}  [{lo:.2f}-{hi:.2f}]', 1.6)

        elif sym == sdl2.SDLK_e:
            eq_cls = None
            for cls in p.effects:
                if cls.__name__ == 'AudioSpectrum' or cls.NAME in {'Audio Spectrum', 'EQ'}:
                    eq_cls = cls
                    break
            if eq_cls is not None:
                log.info('Scene change → %s (EQ hotkey)', eq_cls.NAME)
                a.goto_effect(eq_cls)
                o.flash_name(eq_cls.NAME)
            else:
                o.flash_message('Audio Spectrum not found', 1.5)

        elif sym == sdl2.SDLK_r:
            p.toggle_random()
            mode = p.mode.upper()
            o.flash_message(f"Playlist: {mode}", 1.5)

        elif sym == sdl2.SDLK_PLUS or sym == sdl2.SDLK_EQUALS:
            effect = a.current_effect
            if effect and "speed" in effect.parameters:
                if mod & sdl2.KMOD_ALT:
                    # Alt+= — toggle random speed on
                    a.apply_random_speed()
                    a.set_speed_randomized(True)
                    lo, hi = a.random_range_for('speed', 0.25, 2.50)
                    o.flash_message(f'Speed random ON  {effect.parameters["speed"]:.2f}  [{lo:.2f}-{hi:.2f}]', 1.6)
                elif mod & sdl2.KMOD_CTRL:
                    # Ctrl+= — speed MAX
                    effect.parameters["speed"] = 10.0
                    o.flash_message("Speed  MAX", 1.5)
                else:
                    # = — speed up
                    effect.parameters["speed"] = min(
                        effect.parameters["speed"] * 1.25, 10.0
                    )
                    o.flash_message(f"Speed  {effect.parameters['speed']:.2f}", 1.0)
            else:
                o.flash_message('Speed not available for this effect', 1.0)

        elif sym == sdl2.SDLK_MINUS:
            effect = a.current_effect
            if effect and "speed" in effect.parameters:
                if mod & sdl2.KMOD_ALT:
                    # Alt+- — toggle random speed off
                    a.set_speed_randomized(False)
                    o.flash_message(f'Speed random OFF  {effect.parameters["speed"]:.2f}', 1.2)
                elif mod & sdl2.KMOD_CTRL:
                    # Ctrl+- — speed MIN
                    effect.parameters["speed"] = 0.05
                    o.flash_message("Speed  MIN", 1.5)
                else:
                    # - — speed down
                    effect.parameters["speed"] = max(
                        effect.parameters["speed"] * 0.8, 0.05
                    )
                    o.flash_message(f"Speed  {effect.parameters['speed']:.2f}", 1.0)
            else:
                o.flash_message('Speed not available for this effect', 1.0)

        elif sym == sdl2.SDLK_g:
            am = self._audio
            if mod & sdl2.KMOD_CTRL:
                # Ctrl+G — reset speed to initial default
                default = a.reset_speed()
                if default is not None:
                    o.flash_message(f"Speed reset  {default:.2f}", 1.5)
                else:
                    o.flash_message('Speed control not available', 1.2)
            else:
                # G — reset reactivity to config default
                val = am.reset_reactivity()
                a.set_reactivity_randomized(False)
                o.flash_message(f"Reactivity reset  {val:.2f}", 1.5)

        elif sym == sdl2.SDLK_LEFTBRACKET:
            am = self._audio
            if mod & sdl2.KMOD_SHIFT:
                # { — reactivity min
                val = am.set_reactivity(0.1)
                o.flash_message("Reactivity  MIN  0.10", 1.5)
            else:
                # [ — reactivity down
                val = am.set_reactivity(round(am.get_reactivity() - 0.1, 2))
                o.flash_message(f"Reactivity  {val:.2f}", 1.0)

        elif sym == sdl2.SDLK_RIGHTBRACKET:
            am = self._audio
            if mod & sdl2.KMOD_SHIFT:
                # } — reactivity max
                val = am.set_reactivity(5.0)
                o.flash_message("Reactivity  MAX  5.00", 1.5)
            else:
                # ] — reactivity up
                val = am.set_reactivity(round(am.get_reactivity() + 0.1, 2))
                o.flash_message(f"Reactivity  {val:.2f}", 1.0)

        elif (_num_idx := numeric_slot_index(sym, mod)) is not None:
            self._dispatch_shortcut_slot(_num_idx, a, o)

        elif sym == sdl2.SDLK_COMMA:
            # , = scale down, Shift+, (<) = scale MIN, Ctrl+, = scale reset
            if mod & sdl2.KMOD_CTRL:
                # Ctrl+, — scale reset
                val = a.reset_render_scale()
                o.flash_message(f'Res scale reset  {val:.2f}', 1.2)
            elif mod & sdl2.KMOD_SHIFT:
                # Shift+, (<) — scale MIN
                val = a.set_render_scale(0.5)
                o.flash_message(f'Res scale  MIN  {val:.2f}', 1.2)
            else:
                # , — scale down
                val = a.apply_render_scale_delta(-0.05)
                o.flash_message(f'Res scale  {val:.2f}', 1.0)

        elif sym == sdl2.SDLK_PERIOD:
            # . = scale up, Shift+. (>) = scale MAX, Ctrl+. = scale reset
            if mod & sdl2.KMOD_CTRL:
                # Ctrl+. — scale reset
                val = a.reset_render_scale()
                o.flash_message(f'Res scale reset  {val:.2f}', 1.2)
            elif mod & sdl2.KMOD_SHIFT:
                # Shift+. (>) — scale MAX
                val = a.set_render_scale(1.0)
                o.flash_message(f'Res scale  MAX  {val:.2f}', 1.2)
            else:
                # . — scale up
                val = a.apply_render_scale_delta(0.05)
                o.flash_message(f'Res scale  {val:.2f}', 1.0)

        elif sym == sdl2.SDLK_s:
            self._screenshot()

        elif sym == sdl2.SDLK_v:
            _active, msg = a.toggle_recording()
            o.flash_message(msg, 2.0)

        elif sym == sdl2.SDLK_z:
            effect = a.current_effect
            has_zoom = effect is not None and 'zoom' in effect.parameters
            if mod & sdl2.KMOD_ALT:
                # Alt+Z — toggle random zoom (global flag, applies when supported)
                if a.zoom_randomized:
                    a.set_zoom_randomized(False)
                    if has_zoom:
                        o.flash_message(f'Zoom random OFF  {effect.parameters["zoom"]:.2f}', 1.2)
                    else:
                        o.flash_message('Zoom random OFF', 1.2)
                else:
                    a.apply_random_zoom()
                    a.set_zoom_randomized(True)
                    lo, hi = a.random_range_for('zoom', 0.30, 1.80)
                    if has_zoom:
                        o.flash_message(f'Zoom random ON  {effect.parameters["zoom"]:.2f}  [{lo:.2f}-{hi:.2f}]', 1.6)
                    else:
                        o.flash_message(f'Zoom random ON  (armed)  [{lo:.2f}-{hi:.2f}]', 1.6)
            elif mod & sdl2.KMOD_CTRL:
                # Ctrl+Z — reset zoom to default
                val = a.reset_zoom()
                if val is not None:
                    o.flash_message(f'Zoom reset  {val:.2f}', 1.2)
                else:
                    o.flash_message('Zoom not available for this effect', 1.2)
            elif mod & sdl2.KMOD_SHIFT:
                # Shift+Z — zoom out
                val = a.apply_zoom_delta(-0.10)
                if val > 0:
                    o.flash_message(f'Zoom  {val:.2f}', 1.0)
                else:
                    o.flash_message('Zoom not available for this effect', 1.0)
            else:
                # Z — zoom in
                val = a.apply_zoom_delta(0.10)
                if val > 0:
                    o.flash_message(f'Zoom  {val:.2f}', 1.0)
                else:
                    o.flash_message('Zoom not available for this effect', 1.0)

        elif sym == sdl2.SDLK_x:
            # Display mode controls:
            # X=single
            # Shift+X=cycle single/span/mirror included/all
            # Ctrl+X=span included, Ctrl+Shift+X=span all
            # Alt+X=mirror included, Alt+Shift+X=mirror all
            if (mod & sdl2.KMOD_ALT) and (mod & sdl2.KMOD_SHIFT):
                mode = a.set_display_mode('mirror_all')
                o.flash_message(f'Display mode: {mode}', 1.5)
            elif (mod & sdl2.KMOD_CTRL) and (mod & sdl2.KMOD_SHIFT):
                mode = a.set_display_mode('span_all')
                o.flash_message(f'Display mode: {mode}', 1.5)
            elif mod & sdl2.KMOD_ALT:
                mode = a.set_display_mode('mirror_included')
                o.flash_message(f'Display mode: {mode}', 1.5)
            elif mod & sdl2.KMOD_CTRL:
                mode = a.set_display_mode('span_included')
                o.flash_message(f'Display mode: {mode}', 1.5)
            elif mod & sdl2.KMOD_SHIFT:
                mode = a.cycle_display_mode()
                o.flash_message(f'Display mode: {mode} (cycle)', 1.5)
            else:
                mode = a.set_display_mode('single')
                o.flash_message(f'Display mode: {mode}', 1.5)

        elif sym == sdl2.SDLK_t:
            a._auto_advance = not a._auto_advance
            mode = "ON" if a._auto_advance else "OFF"
            o.flash_message(f"Auto-advance: {mode}", 1.5)

        elif sym == sdl2.SDLK_SEMICOLON:
            val = a.adjust_advance_interval(-10.0)
            o.flash_message(f'Advance interval: {val:.0f}s', 1.5)

        elif sym == sdl2.SDLK_QUOTE:
            val = a.adjust_advance_interval(10.0)
            o.flash_message(f'Advance interval: {val:.0f}s', 1.5)

        elif sym == sdl2.SDLK_BACKSLASH:
            val = a.reset_advance_interval()
            o.flash_message(f'Advance interval: {val:.0f}s (reset)', 1.5)

        elif sym == sdl2.SDLK_i:
            enabled = a.toggle_invert()
            o.flash_message(f"Invert: {'ON' if enabled else 'OFF'}", 1.5)

    def _screenshot(self) -> None:
        import datetime
        from pathlib import Path
        from PIL import Image

        ctx = self._app.vj_api.ctx
        if ctx is None:
            return

        # Use the actual screen framebuffer size for readback. In multi-head
        # modes the logical render size can differ from the current screen size.
        try:
            w, h = ctx.screen.size
            w = int(w)
            h = int(h)
        except Exception:
            w = int(self._app.vj_api.render_width)
            h = int(self._app.vj_api.render_height)

        data = ctx.screen.read(components=3, alignment=1)
        expected = max(1, int(w)) * max(1, int(h)) * 3
        if len(data) < expected:
            log.error(
                'Screenshot readback short: got=%d expected=%d size=%dx%d',
                len(data),
                expected,
                w,
                h,
            )
            self._overlays.flash_message('Screenshot failed: short GPU readback', 2.0)
            return
        if len(data) > expected:
            data = data[:expected]

        img = Image.frombytes("RGB", (w, h), data)
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = resolve_path("screenshots")
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"unicornviz_{ts}.png"
        img.save(path)
        self._overlays.flash_message(f"Screenshot: {path}", 3.0)
        log.info("Screenshot saved: %s", path)
