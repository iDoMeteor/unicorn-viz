"""Hotkey handler — maps SDL keysyms and MIDI notes to app/playlist/overlay actions."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import sdl2

if TYPE_CHECKING:
    from unicornviz.app import App
    from unicornviz.playlist import Playlist
    from unicornviz.overlays import Overlays
    from unicornviz.audio.manager import AudioManager
    from unicornviz.midi import MidiManager, MidiEvent

log = logging.getLogger(__name__)


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
        self._shortcut_effects = playlist.shortcut_effects
        self._overlays = overlays
        self._audio = audio_manager

    def attach_midi(self, midi: "MidiManager") -> None:
        """Register MIDI event listener after construction."""
        midi.add_listener(self._on_midi)

    def _on_midi(self, event: "MidiEvent") -> None:
        a = self._app
        p = self._playlist
        o = self._overlays
        if event.type == "note_on":
            action = a._midi_manager.note_to_action(event.number)  # noqa: SLF001
            if action == "next":
                self.handle(sdl2.SDLK_n, 0)
            elif action == "prev":
                self.handle(sdl2.SDLK_p, 0)
            elif action == "random":
                self.handle(sdl2.SDLK_r, 0)
            elif action == "pause":
                self.handle(sdl2.SDLK_SPACE, 0)
            elif action == "fullscreen":
                self.handle(sdl2.SDLK_f, 0)
        elif event.type == "cc":
            effect = a._current_effect  # noqa: SLF001
            if effect is not None:
                param = a._midi_manager.cc_to_param(event.number)  # noqa: SLF001
                if param and param in effect.parameters:
                    lo, hi = 0.1, 4.0
                    effect.parameters[param] = lo + event.value * (hi - lo)
                    o.flash_message(f"MIDI {param}: {effect.parameters[param]:.2f}", 1.0)

    def handle(self, sym: int, mod: int) -> None:
        a = self._app
        p = self._playlist
        o = self._overlays
        sym_name = sdl2.SDL_GetKeyName(sym)
        if isinstance(sym_name, bytes):
            sym_name = sym_name.decode("utf-8", errors="replace")
        log.debug("Key: %s (mod=0x%04x)", sym_name, mod)

        effect = a._current_effect  # noqa: SLF001

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

        # System-level post-process slot controls (Ctrl+Alt+number).
        # Handle before help-overlay numeric controls and effect jump shortcuts.
        if (mod & sdl2.KMOD_CTRL) and (mod & sdl2.KMOD_ALT):
            if sdl2.SDLK_1 <= sym <= sdl2.SDLK_8:
                slot = int(sym - sdl2.SDLK_0)
                message = a.select_postfx_slot(slot)
                o.flash_message(message, 1.5)
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
                        return

        # Help overlay interaction mode: section expand/collapse and focus nav.
        if getattr(o, 'help_visible', False):
            if sdl2.SDLK_1 <= sym <= sdl2.SDLK_9:
                if o.toggle_help_section(sym - sdl2.SDLK_1):
                    return
            elif sym == sdl2.SDLK_0:
                if o.toggle_help_section(9):
                    return
            elif sym == sdl2.SDLK_UP:
                if o.move_help_focus(-1):
                    return
            elif sym == sdl2.SDLK_DOWN:
                if o.move_help_focus(1):
                    return
            elif sym in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
                if o.toggle_help_focus_section():
                    return
            elif (mod & sdl2.KMOD_SHIFT) and sym in (sdl2.SDLK_EQUALS, sdl2.SDLK_PLUS):
                o.set_all_help_sections_collapsed(False)
                o.flash_message('Help: expanded all sections', 1.2)
                return
            elif (mod & sdl2.KMOD_SHIFT) and sym == sdl2.SDLK_MINUS:
                o.set_all_help_sections_collapsed(True)
                o.flash_message('Help: collapsed all sections', 1.2)
                return

        if sym == sdl2.SDLK_ESCAPE:
            a._running = False  # noqa: SLF001

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
            if p.mode == "random":
                cls = p.advance()
                log.info("Scene change → %s (random prev)", cls.NAME)
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
            o.toggle_help()

        elif sym == sdl2.SDLK_a:
            if (mod & sdl2.KMOD_ALT) and (mod & sdl2.KMOD_SHIFT):
                # Alt+Shift+A — previous audio profile (wraps around)
                profiles = self._audio.list_profiles()
                current_profile = self._audio.get_profile()
                current_name = current_profile.name
                try:
                    current_idx = profiles.index(current_profile.name)
                except ValueError:
                    current_idx = 0
                prev_idx = (current_idx - 1) % len(profiles)
                prev_profile = self._audio.set_profile(profiles[prev_idx])
                o.flash_message(f'Audio Profile: {prev_profile.name}', 1.2)
                log.info('Audio profile changed: %s → %s', current_name, prev_profile.name)
            elif mod & sdl2.KMOD_ALT:
                # Alt+A — next audio profile (wraps around)
                profiles = self._audio.list_profiles()
                current_profile = self._audio.get_profile()
                current_name = current_profile.name
                try:
                    current_idx = profiles.index(current_profile.name)
                except ValueError:
                    current_idx = 0
                next_idx = (current_idx + 1) % len(profiles)
                next_profile = self._audio.set_profile(profiles[next_idx])
                o.flash_message(f'Audio Profile: {next_profile.name}', 1.2)
                log.info('Audio profile changed: %s → %s', current_name, next_profile.name)
            elif mod & sdl2.KMOD_CTRL:
                # Ctrl+A — audio source selector
                o.toggle_audio_selector()
            elif mod & sdl2.KMOD_SHIFT:
                # Shift+A — our own ANSI art
                ansi_dir = self._app.cfg.get("ansi", "ansi_own_dir",
                                             default="assets/ansi")
                a.goto_ansi(ansi_dir)
                o.flash_message("ANSI: Own art", 2.0)
            else:
                # a — ACiD art
                acid_dir = self._app.cfg.get("ansi", "ansi_acid_dir",
                                             default="assets/ansi/acid")
                a.goto_ansi(acid_dir)
                o.flash_message("ACiD: Art", 2.0)

        elif sym == sdl2.SDLK_m:
            o.toggle_midi_selector()

        elif sym == sdl2.SDLK_F8:
            live, message = a.toggle_streaming()
            o.flash_message(message, 1.8 if live else 1.2)

        elif sym == sdl2.SDLK_F6:
            effect = a._current_effect  # noqa: SLF001
            # Toggle is global — persists even when current effect lacks 'speed'.
            if a._speed_randomized:  # noqa: SLF001
                a._speed_randomized = False  # noqa: SLF001
                if effect is not None and 'speed' in effect.parameters:
                    o.flash_message(f'Speed random OFF  {effect.parameters["speed"]:.2f}', 1.2)
                else:
                    o.flash_message('Speed random OFF', 1.2)
            else:
                a._apply_random_speed()  # noqa: SLF001  (sets flag + applies if supported)
                a._speed_randomized = True  # noqa: SLF001  ensure flag set even if not applied
                lo, hi = a._random_range_for('speed', 0.25, 2.50)  # noqa: SLF001
                if effect is not None and 'speed' in effect.parameters:
                    o.flash_message(f'Speed random ON  {effect.parameters["speed"]:.2f}  [{lo:.2f}-{hi:.2f}]', 1.6)
                else:
                    o.flash_message(f'Speed random ON  (armed)  [{lo:.2f}-{hi:.2f}]', 1.6)

        elif sym == sdl2.SDLK_F7:
            am = self._audio
            if am is None:
                o.flash_message('Reactivity control not available', 1.2)
                a._reactivity_randomized = False  # noqa: SLF001
            else:
                # Toggle randomization on/off
                if a._reactivity_randomized:  # noqa: SLF001
                    a._reactivity_randomized = False  # noqa: SLF001
                    current = am.get_reactivity()
                    o.flash_message(f'Reactivity random OFF  {current:.2f}', 1.2)
                else:
                    a._apply_random_reactivity()  # noqa: SLF001
                    lo, hi = a._random_range_for('reactivity', 0.40, 2.00)  # noqa: SLF001
                    current = am.get_reactivity()
                    o.flash_message(f'Reactivity random ON  {current:.2f}  [{lo:.2f}-{hi:.2f}]', 1.6)

        elif (mod & sdl2.KMOD_CTRL) and sym == sdl2.SDLK_F9:
            provider = a.set_stream_provider('rumble')
            o.flash_message(f'Stream provider: {provider}', 1.2)

        elif (mod & sdl2.KMOD_CTRL) and sym == sdl2.SDLK_F10:
            provider = a.set_stream_provider('youtube')
            o.flash_message(f'Stream provider: {provider}', 1.2)

        elif (mod & sdl2.KMOD_CTRL) and sym == sdl2.SDLK_F11:
            provider = a.set_stream_provider('custom')
            o.flash_message(f'Stream provider: {provider}', 1.2)

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
            effect = a._current_effect  # noqa: SLF001
            if effect and "speed" in effect.parameters:
                if mod & sdl2.KMOD_ALT:
                    # Alt+= — toggle random speed on
                    a._apply_random_speed()  # noqa: SLF001
                    a._speed_randomized = True  # noqa: SLF001
                    lo, hi = a._random_range_for('speed', 0.25, 2.50)  # noqa: SLF001
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
            effect = a._current_effect  # noqa: SLF001
            if effect and "speed" in effect.parameters:
                if mod & sdl2.KMOD_ALT:
                    # Alt+- — toggle random speed off
                    a._speed_randomized = False  # noqa: SLF001
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
                effect = a._current_effect  # noqa: SLF001
                if effect and "speed" in effect.parameters:
                    default = effect._initial_parameters.get("speed", 1.0)  # noqa: SLF001
                    effect.parameters["speed"] = default
                    a._speed_randomized = False  # noqa: SLF001
                    o.flash_message(f"Speed reset  {default:.2f}", 1.5)
                else:
                    o.flash_message('Speed control not available', 1.2)
            else:
                # G — reset reactivity to config default
                val = am.reset_reactivity()
                a._reactivity_randomized = False  # noqa: SLF001
                o.flash_message(f"Reactivity reset  {val:.2f}", 1.5)

        elif sym == sdl2.SDLK_LEFTBRACKET:
            am = self._audio
            if mod & sdl2.KMOD_ALT:
                # Alt+[ — PiP size down (webcam)
                if a._webcam_system:  # noqa: SLF001
                    val = a.scale_pip(-0.05)
                    o.flash_message(f'Camera PiP: {val:.0%}', 1.0)
                else:
                    o.flash_message('Camera PiP not available', 1.0)
            elif mod & sdl2.KMOD_SHIFT:
                # { — reactivity min
                val = am.set_reactivity(0.1)
                o.flash_message("Reactivity  MIN  0.10", 1.5)
            else:
                # [ — reactivity down
                val = am.set_reactivity(round(am.get_reactivity() - 0.1, 2))
                o.flash_message(f"Reactivity  {val:.2f}", 1.0)

        elif sym == sdl2.SDLK_RIGHTBRACKET:
            am = self._audio
            if mod & sdl2.KMOD_ALT:
                # Alt+] — PiP size up (webcam)
                if a._webcam_system:  # noqa: SLF001
                    val = a.scale_pip(0.05)
                    o.flash_message(f'Camera PiP: {val:.0%}', 1.0)
                else:
                    o.flash_message('Camera PiP not available', 1.0)
            elif mod & sdl2.KMOD_SHIFT:
                # } — reactivity max
                val = am.set_reactivity(5.0)
                o.flash_message("Reactivity  MAX  5.00", 1.5)
            else:
                # ] — reactivity up
                val = am.set_reactivity(round(am.get_reactivity() + 0.1, 2))
                o.flash_message(f"Reactivity  {val:.2f}", 1.0)

        elif sdl2.SDLK_1 <= sym <= sdl2.SDLK_9:
            if not self._shortcut_effects:
                return
            # Alt+1..9 -> effects 31..39
            if mod & sdl2.KMOD_ALT:
                idx = 30 + (sym - sdl2.SDLK_1)   # 30..38
            # Ctrl+1..9 -> effects 21..29
            elif mod & sdl2.KMOD_CTRL:
                idx = 20 + (sym - sdl2.SDLK_1)   # 20..28
            # Support both SDL behaviors for Shift+number:
            # 1) symbol keysyms (!@#$...) handled below
            # 2) number keysyms with KMOD_SHIFT handled here
            elif mod & sdl2.KMOD_SHIFT:
                idx = 10 + (sym - sdl2.SDLK_1)   # 10..18
            else:
                idx = sym - sdl2.SDLK_1          # 0..8
            cls = self._shortcut_effects[idx % len(self._shortcut_effects)]
            log.info("Scene change → %s (key index %d)", cls.NAME, idx)
            a.goto_effect(cls)
            o.flash_name(cls.NAME)

        elif sym == sdl2.SDLK_0:
            if not self._shortcut_effects:
                return
            # Alt+0 -> effect 40 (index 39)
            if mod & sdl2.KMOD_ALT:
                idx = 39
            # Ctrl+0 -> effect 30 (index 29)
            elif mod & sdl2.KMOD_CTRL:
                idx = 29
            # Support both SDL behaviors for Shift+0: idx 19 (')')
            elif mod & sdl2.KMOD_SHIFT:
                idx = 19
            else:
                idx = 9
            cls = self._shortcut_effects[idx % len(self._shortcut_effects)]
            a.goto_effect(cls)
            o.flash_name(cls.NAME)

        # Shift+1..0 → effects 10–19  (keysyms: !, @, #, $, %, ^, &, *, (, ))
        elif sym in (sdl2.SDLK_EXCLAIM, sdl2.SDLK_AT, sdl2.SDLK_HASH,
                     sdl2.SDLK_DOLLAR, sdl2.SDLK_PERCENT, sdl2.SDLK_CARET,
                     sdl2.SDLK_AMPERSAND, sdl2.SDLK_ASTERISK,
                     sdl2.SDLK_LEFTPAREN, sdl2.SDLK_RIGHTPAREN):
            if not self._shortcut_effects:
                return
            _shift_syms = [
                sdl2.SDLK_EXCLAIM, sdl2.SDLK_AT, sdl2.SDLK_HASH,
                sdl2.SDLK_DOLLAR, sdl2.SDLK_PERCENT, sdl2.SDLK_CARET,
                sdl2.SDLK_AMPERSAND, sdl2.SDLK_ASTERISK,
                sdl2.SDLK_LEFTPAREN, sdl2.SDLK_RIGHTPAREN,
            ]
            idx = 10 + _shift_syms.index(sym)   # effects 10–19
            cls = self._shortcut_effects[idx % len(self._shortcut_effects)]
            a.goto_effect(cls)
            o.flash_name(cls.NAME)

        elif sym == sdl2.SDLK_COMMA:
            # , = scale down, Shift+, (<) = scale MIN, Ctrl+, = scale reset, Alt+, = scale random
            if mod & sdl2.KMOD_ALT:
                # Alt+, — toggle random render scale
                if a._scale_randomized:  # noqa: SLF001
                    val = a._reset_render_scale()  # noqa: SLF001
                    a._scale_randomized = False  # noqa: SLF001
                    o.flash_message(f'Res scale random OFF  {val:.2f}', 1.2)
                else:
                    a._apply_random_render_scale()  # noqa: SLF001
                    lo, hi = a._random_range_for('scale', 0.5, 1.0)  # noqa: SLF001
                    o.flash_message(f'Res scale random ON  {a._render_scale:.2f}  [{lo:.2f}-{hi:.2f}]', 1.6)  # noqa: SLF001
            elif mod & sdl2.KMOD_CTRL:
                # Ctrl+, — scale reset
                val = a._reset_render_scale()  # noqa: SLF001
                o.flash_message(f'Res scale reset  {val:.2f}', 1.2)
            elif mod & sdl2.KMOD_SHIFT:
                # Shift+, (<) — scale MIN
                lo, _hi = a._random_range_for('scale', 0.5, 1.0)  # noqa: SLF001
                val = a._set_render_scale(lo)  # noqa: SLF001
                o.flash_message(f'Res scale  MIN  {val:.2f}', 1.2)
            else:
                # , — scale down
                val = a._apply_render_scale_delta(-0.05)  # noqa: SLF001
                o.flash_message(f'Res scale  {val:.2f}', 1.0)

        elif sym == sdl2.SDLK_PERIOD:
            # . = scale up, Shift+. (>) = scale MAX, Ctrl+. = scale reset, Alt+. = scale random
            if mod & sdl2.KMOD_ALT:
                # Alt+. — toggle random render scale
                if a._scale_randomized:  # noqa: SLF001
                    val = a._reset_render_scale()  # noqa: SLF001
                    a._scale_randomized = False  # noqa: SLF001
                    o.flash_message(f'Res scale random OFF  {val:.2f}', 1.2)
                else:
                    a._apply_random_render_scale()  # noqa: SLF001
                    lo, hi = a._random_range_for('scale', 0.5, 1.0)  # noqa: SLF001
                    o.flash_message(f'Res scale random ON  {a._render_scale:.2f}  [{lo:.2f}-{hi:.2f}]', 1.6)  # noqa: SLF001
            elif mod & sdl2.KMOD_CTRL:
                # Ctrl+. — scale reset
                val = a._reset_render_scale()  # noqa: SLF001
                o.flash_message(f'Res scale reset  {val:.2f}', 1.2)
            elif mod & sdl2.KMOD_SHIFT:
                # Shift+. (>) — scale MAX
                _lo, hi = a._random_range_for('scale', 0.5, 1.0)  # noqa: SLF001
                val = a._set_render_scale(hi)  # noqa: SLF001
                o.flash_message(f'Res scale  MAX  {val:.2f}', 1.2)
            else:
                # . — scale up
                val = a._apply_render_scale_delta(0.05)  # noqa: SLF001
                o.flash_message(f'Res scale  {val:.2f}', 1.0)

        elif sym == sdl2.SDLK_s:
            self._screenshot()

        elif sym == sdl2.SDLK_v:
            _active, msg = a.toggle_recording()
            o.flash_message(msg, 2.0)

        elif sym == sdl2.SDLK_z:
            effect = a._current_effect  # noqa: SLF001
            has_zoom = effect is not None and 'zoom' in effect.parameters  # noqa: SLF001
            if mod & sdl2.KMOD_ALT:
                # Alt+Z — toggle random zoom (global flag, applies when supported)
                if a._zoom_randomized:  # noqa: SLF001
                    a._zoom_randomized = False  # noqa: SLF001
                    if has_zoom:
                        o.flash_message(f'Zoom random OFF  {effect.parameters["zoom"]:.2f}', 1.2)
                    else:
                        o.flash_message('Zoom random OFF', 1.2)
                else:
                    a._apply_random_zoom()  # noqa: SLF001  (sets flag + applies if supported)
                    a._zoom_randomized = True  # noqa: SLF001  ensure flag set even if not applied
                    lo, hi = a._random_range_for('zoom', 0.30, 1.80)  # noqa: SLF001
                    if has_zoom:
                        o.flash_message(f'Zoom random ON  {effect.parameters["zoom"]:.2f}  [{lo:.2f}-{hi:.2f}]', 1.6)
                    else:
                        o.flash_message(f'Zoom random ON  (armed)  [{lo:.2f}-{hi:.2f}]', 1.6)
            elif mod & sdl2.KMOD_CTRL:
                # Ctrl+Z — reset zoom to default
                val = a._reset_zoom()  # noqa: SLF001
                if val is not None:
                    o.flash_message(f'Zoom reset  {val:.2f}', 1.2)
                else:
                    o.flash_message('Zoom not available for this effect', 1.2)
            elif mod & sdl2.KMOD_SHIFT:
                # Shift+Z — zoom out
                val = a._apply_zoom_delta(-0.10)  # noqa: SLF001
                if val > 0:
                    o.flash_message(f'Zoom  {val:.2f}', 1.0)
                else:
                    o.flash_message('Zoom not available for this effect', 1.0)
            else:
                # Z — zoom in
                val = a._apply_zoom_delta(0.10)  # noqa: SLF001
                if val > 0:
                    o.flash_message(f'Zoom  {val:.2f}', 1.0)
                else:
                    o.flash_message('Zoom not available for this effect', 1.0)

        elif sym == sdl2.SDLK_k:
            if mod & sdl2.KMOD_ALT:
                # Alt+K — toggle random render scale
                if a._scale_randomized:  # noqa: SLF001
                    val = a._reset_render_scale()  # noqa: SLF001  (turns off random, restores default)
                    a._scale_randomized = False  # noqa: SLF001
                    o.flash_message(f'Res scale random OFF  {val:.2f}', 1.2)
                else:
                    a._apply_random_render_scale()  # noqa: SLF001
                    lo, hi = a._random_range_for('scale', 0.5, 1.0)  # noqa: SLF001
                    o.flash_message(f'Res scale random ON  {a._render_scale:.2f}  [{lo:.2f}-{hi:.2f}]', 1.6)  # noqa: SLF001
            elif mod & sdl2.KMOD_CTRL:
                # Ctrl+K — reset render scale to config default
                val = a._reset_render_scale()  # noqa: SLF001
                o.flash_message(f'Res scale reset  {val:.2f}', 1.2)
            elif mod & sdl2.KMOD_SHIFT:
                # Shift+K — scale down
                val = a._apply_render_scale_delta(-0.05)  # noqa: SLF001
                o.flash_message(f'Res scale  {val:.2f}', 1.0)
            else:
                # K — scale up
                val = a._apply_render_scale_delta(0.05)  # noqa: SLF001
                o.flash_message(f'Res scale  {val:.2f}', 1.0)

        elif sym == sdl2.SDLK_u:
            if mod & sdl2.KMOD_CTRL and mod & sdl2.KMOD_ALT:
                a.trigger_burst()
                o.flash_message('\U0001f300  BURST', 0.6)
            elif mod & sdl2.KMOD_CTRL:
                a.trigger_dancing_unicorn()
                o.flash_message('\U0001f984  UNICORN INCOMING', 0.8)
            elif mod & sdl2.KMOD_SHIFT:
                a.show_splash()
                o.flash_message("Splash replay", 1.5)
            else:
                unicorn_cls = None
                for cls in p.effects:
                    if cls.__name__ == "UnicornTears" or cls.NAME == "Unicorn Tears":
                        unicorn_cls = cls
                        break
                if unicorn_cls is not None:
                    a.goto_effect(unicorn_cls)
                    o.flash_name(unicorn_cls.NAME)
                else:
                    o.flash_message("Unicorn Tears not found", 1.5)

        elif sym == sdl2.SDLK_x:
            # Display mode controls: X=single, Shift+X=span, Ctrl+X=mirror, Alt+X=config
            if mod & sdl2.KMOD_ALT:
                mode = a.set_display_mode(reset_to_config=True)
                o.flash_message(f'Display mode: {mode} (config)', 1.5)
            elif mod & sdl2.KMOD_CTRL:
                mode = a.set_display_mode('mirror_all')
                o.flash_message(f'Display mode: {mode}', 1.5)
            elif mod & sdl2.KMOD_SHIFT:
                mode = a.set_display_mode('span_all')
                o.flash_message(f'Display mode: {mode}', 1.5)
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

        # Webcam PiP layout controls (numpad only; does not affect top-row shortcuts)
        elif sym == sdl2.SDLK_KP_0:
            if a.set_camera_layout('0'):
                o.flash_message('Camera: fullscreen', 1.5)
            else:
                o.flash_message('Camera: not available', 1.2)

        elif sym == sdl2.SDLK_KP_PERIOD:
            if a.set_camera_layout('.'):
                o.flash_message('Camera: hidden', 1.5)
            else:
                o.flash_message('Camera: not available', 1.2)

        elif sym in (
            sdl2.SDLK_KP_1, sdl2.SDLK_KP_2, sdl2.SDLK_KP_3,
            sdl2.SDLK_KP_4, sdl2.SDLK_KP_5, sdl2.SDLK_KP_6,
            sdl2.SDLK_KP_7, sdl2.SDLK_KP_8, sdl2.SDLK_KP_9,
        ):
            kp_map = {
                sdl2.SDLK_KP_1: '1', sdl2.SDLK_KP_2: '2', sdl2.SDLK_KP_3: '3',
                sdl2.SDLK_KP_4: '4', sdl2.SDLK_KP_5: '5', sdl2.SDLK_KP_6: '6',
                sdl2.SDLK_KP_7: '7', sdl2.SDLK_KP_8: '8', sdl2.SDLK_KP_9: '9',
            }
            token = kp_map[sym]
            labels = {
                '1': 'bottom-left', '2': 'bottom-center', '3': 'bottom-right',
                '4': 'left', '5': 'center', '6': 'right',
                '7': 'top-left', '8': 'top-center', '9': 'top-right',
            }
            if a.set_camera_layout(token):
                o.flash_message(f"Camera: {labels[token]}", 1.5)
            else:
                o.flash_message('Camera: not available', 1.2)

        # Camera treatment cycling / PiP sizing (KP operator row)
        elif sym == sdl2.SDLK_KP_DIVIDE:
            name = a.goto_prev_webcam_effect()
            if name:
                o.flash_message(f'Camera treatment: {name}', 1.5)
            else:
                o.flash_message('Camera: not available', 1.2)

        elif sym == sdl2.SDLK_KP_MULTIPLY:
            name = a.goto_next_webcam_effect()
            if name:
                o.flash_message(f'Camera treatment: {name}', 1.5)
            else:
                o.flash_message('Camera: not available', 1.2)

        elif sym == sdl2.SDLK_KP_MINUS:
            val = a.scale_pip(-0.05)
            if val > 0:
                o.flash_message(f'Camera PiP: {val:.0%}', 1.0)
            else:
                o.flash_message('Camera: not available', 1.0)

        elif sym == sdl2.SDLK_KP_PLUS:
            val = a.scale_pip(0.05)
            if val > 0:
                o.flash_message(f'Camera PiP: {val:.0%}', 1.0)
            else:
                o.flash_message('Camera: not available', 1.0)

        elif sym == sdl2.SDLK_KP_ENTER:
            active = a.toggle_webcam_auto_cycle()
            state = 'ON' if active else 'OFF'
            o.flash_message(f'Camera treatment auto-cycle: {state}', 1.5)

    def _screenshot(self) -> None:
        import datetime
        import numpy as np
        from pathlib import Path
        from PIL import Image

        ctx = self._app._ctx  # noqa: SLF001
        if ctx is None:
            return
        w, h = self._app._width, self._app._height  # noqa: SLF001
        data = ctx.screen.read(components=3)
        img = Image.frombytes("RGB", (w, h), data)
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path("screenshots")
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"unicornviz_{ts}.png"
        img.save(path)
        self._overlays.flash_message(f"Screenshot: {path}", 3.0)
        log.info("Screenshot saved: %s", path)
