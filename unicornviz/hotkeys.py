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
        log.info("Key: %s (mod=0x%04x)", sym_name, mod)

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
            o.toggle_audio_selector()

        elif sym == sdl2.SDLK_m:
            o.toggle_midi_selector()

        elif sym == sdl2.SDLK_r:
            p.toggle_random()
            mode = p.mode.upper()
            o.flash_message(f"Playlist: {mode}", 1.5)

        elif sym == sdl2.SDLK_PLUS or sym == sdl2.SDLK_EQUALS:
            effect = a._current_effect  # noqa: SLF001
            if effect and "speed" in effect.parameters:
                effect.parameters["speed"] = min(
                    effect.parameters["speed"] * 1.25, 10.0
                )

        elif sym == sdl2.SDLK_MINUS:
            effect = a._current_effect  # noqa: SLF001
            if effect and "speed" in effect.parameters:
                effect.parameters["speed"] = max(
                    effect.parameters["speed"] * 0.8, 0.05
                )

        elif sym == sdl2.SDLK_g:
            am = self._audio
            if mod & sdl2.KMOD_CTRL:
                val = am.reset_reactivity()
            elif mod & sdl2.KMOD_SHIFT:
                val = am.set_reactivity(round(am.get_reactivity() - 0.1, 2))
            else:
                val = am.set_reactivity(round(am.get_reactivity() + 0.1, 2))
            o.flash_message(f"Audio reactivity: {val:.1f}x", 1.5)

        elif sdl2.SDLK_1 <= sym <= sdl2.SDLK_9:
            if not self._shortcut_effects:
                return
            # Ctrl+1..9 -> effects 21..29
            if mod & sdl2.KMOD_CTRL:
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
            # Ctrl+0 -> effect 30 (index 29)
            if mod & sdl2.KMOD_CTRL:
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
            # Launch ANSI Viewer with our hand-crafted art
            ansi_dir = self._app.cfg.get("ansi", "ansi_own_dir",
                                         default="assets/ansi")
            a.goto_ansi(ansi_dir)
            o.flash_message("ANSI: Own art", 2.0)

        elif sym == sdl2.SDLK_PERIOD:
            # Launch ANSI Viewer with ACiD art
            acid_dir = self._app.cfg.get("ansi", "ansi_acid_dir",
                                         default="assets/ansi/acid")
            a.goto_ansi(acid_dir)
            o.flash_message("ANSI: ACiD art", 2.0)

        elif sym == sdl2.SDLK_s:
            self._screenshot()

        elif sym == sdl2.SDLK_u:
            if mod & sdl2.KMOD_SHIFT:
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

        elif sym == sdl2.SDLK_t:
            a._auto_advance = not a._auto_advance
            mode = "ON" if a._auto_advance else "OFF"
            o.flash_message(f"Auto-advance: {mode}", 1.5)

        elif sym == sdl2.SDLK_i:
            enabled = a.toggle_invert()
            o.flash_message(f"Invert: {'ON' if enabled else 'OFF'}", 1.5)

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
