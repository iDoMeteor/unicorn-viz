"""
MIDI controller support.

Listens for Control Change and Note On messages on any connected MIDI device.
Emits a MidiEvent that registered listeners (e.g. HotkeyHandler) process.

Built-in device presets
-----------------------
``"akai_apc_mini_mk2"``
    Akai APC mini mk2 — 8×8 pad grid (notes 0–63, row 0 = bottom),
    scene launch buttons (notes 112–119), faders on Control port (CC 48–55).
    Connect to the "Notes" port for pad triggers, or "Control" port for faders.

``"akai_mpk_mini"``
    Akai MPK Mini MK2/MK3 — knobs K1-K8 (CC 70-77), pad bank A (notes 36-43),
    pad bank B (notes 44-51).

``"novation_launchcontrol"``
    Novation LaunchControl XL default factory template — send knobs + pads.

``"generic"``
    Fallback generic mapping (same as built-in defaults).

Configuration
-------------
Add ``[midi]`` to ``config.toml``::

    [midi]
    device = "apc mini mk2 notes"  # port name substring; empty = MIDI disabled
    preset = "akai_apc_mini_mk2"   # named built-in preset (optional)

    [midi.cc_map]            # per-CC overrides (applied after preset)
    48 = "speed"

    [midi.note_map]          # per-note overrides (applied after preset)
    56 = "next"
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

try:
    import rtmidi
    _RTMIDI_OK = True
except Exception as e:
    log.warning("python-rtmidi unavailable: %s — MIDI disabled", e)
    _RTMIDI_OK = False


@dataclass
class MidiEvent:
    type: str          # "cc" | "note_on" | "note_off"
    channel: int       # 0-15
    number: int        # CC number or note number
    value: float       # CC value 0.0-1.0 or note velocity 0.0-1.0


# ---------------------------------------------------------------------------
# Built-in CC/note maps
# ---------------------------------------------------------------------------

# Fallback generic CC → parameter name mapping
_CC_MAP_DEFAULT: dict[int, str] = {
    74: 'speed',
    71: 'intensity',
    91: 'glow',
    93: 'crt',
    7:  'volume',
    10: 'pan',
}

# Fallback generic note → action name mapping
_NOTE_MAP_DEFAULT: dict[int, str] = {
    60: 'next',          # C4
    62: 'prev',          # D4
    64: 'audio_toggle',  # E4
    65: 'random',        # F4
    67: 'pause',         # G4
    69: 'fullscreen',    # A4
}


# ---------------------------------------------------------------------------
# Named device presets
# ---------------------------------------------------------------------------

BUILTIN_PRESETS: dict[str, dict[str, dict[int, str]]] = {
    # Akai APC mini mk2
    # Notes port: 8x8 pad grid (notes 0-63, row 0 bottom = notes 0-7,
    #             row 7 top = notes 56-63), scene launch buttons (notes 112-119)
    # Control port: track faders 1-8 (CC 48-55), master fader (CC 56)
    # Default mapping uses top pad row (56-63) and scene buttons (112-119) for actions.
    # Connect to "APC mini mk2 Notes" for pad triggers (device = "notes").
    # Connect to "APC mini mk2 Control" for fader CCs (device = "control").
    'akai_apc_mini_mk2': {
        'cc_map': {
            # Track faders 1-8 (Control port only)
            48: 'speed',
            49: 'intensity',
            50: 'zoom',
            51: 'reactivity',
            52: 'glow',
            53: 'crt',
            54: 'volume',
            55: 'pan',
            # Master fader
            56: 'volume',
        },
        'note_map': {
            # Top pad row (row 7, notes 56-63) — primary action triggers
            56: 'next',
            57: 'prev',
            58: 'random',
            59: 'pause',
            60: 'fullscreen',
            61: 'audio_toggle',
            62: 'eq',
            63: 'ansi',
            # Scene launch buttons (notes 112-119) — same actions, right side column
            112: 'next',
            113: 'prev',
            114: 'random',
            115: 'pause',
            116: 'fullscreen',
            117: 'audio_toggle',
            118: 'eq',
            119: 'ansi',
        },
    },

    # Akai MPK Mini MK2 / MK3
    # Knobs K1-K8 → CC 70-77 (factory default program)
    # Pad bank A  → notes 36-43 (C2-B2)
    # Pad bank B  → notes 44-51 (C3-B3)
    'akai_mpk_mini': {
        'cc_map': {
            70: 'speed',
            71: 'intensity',
            72: 'glow',
            73: 'crt',
            74: 'zoom',
            75: 'volume',
            76: 'pan',
            77: 'reactivity',
        },
        'note_map': {
            # Pad bank A
            36: 'next',
            37: 'prev',
            38: 'random',
            39: 'pause',
            40: 'fullscreen',
            41: 'audio_toggle',
            42: 'eq',
            43: 'ansi',
            # Pad bank B (mirrors bank A — useful when bank A is held)
            44: 'next',
            45: 'prev',
            46: 'random',
            47: 'pause',
            48: 'fullscreen',
            49: 'audio_toggle',
            50: 'eq',
            51: 'ansi',
        },
    },

    # Novation LaunchControl XL factory template 1
    # Send knobs (top row) → CC 13-20, bottom row → CC 29-36, pads → notes 41-56
    'novation_launchcontrol': {
        'cc_map': {
            13: 'speed',
            14: 'intensity',
            15: 'glow',
            16: 'crt',
            17: 'zoom',
            18: 'volume',
            19: 'pan',
            20: 'reactivity',
            # Original default single-row mapping kept as bonus
            74: 'speed',
            71: 'intensity',
            91: 'glow',
            93: 'crt',
        },
        'note_map': {
            41: 'next',
            42: 'prev',
            43: 'random',
            44: 'pause',
            57: 'fullscreen',
            58: 'audio_toggle',
        },
    },

    # Generic / unknown device — same as built-in defaults
    'generic': {
        'cc_map': dict(_CC_MAP_DEFAULT),
        'note_map': dict(_NOTE_MAP_DEFAULT),
    },
}


def list_ports() -> list[str]:
    """Return available MIDI input port names; empty list when rtmidi is absent."""
    if not _RTMIDI_OK:
        return []
    try:
        tmp = rtmidi.MidiIn()
        ports = tmp.get_ports()
        del tmp
        return [p if isinstance(p, str) else p.decode('utf-8', errors='replace') for p in ports]
    except Exception as exc:
        log.debug('MIDI list_ports failed: %s', exc)
        return []


class MidiManager:
    """
    Opens a MIDI input port and forwards CC/Note events to registered callbacks.

    Map resolution order (later layers win):
    1. Built-in defaults (``_CC_MAP_DEFAULT`` / ``_NOTE_MAP_DEFAULT``)
    2. Named preset from ``BUILTIN_PRESETS`` (if ``preset`` is given)
    3. Per-entry overrides from ``cc_map_override`` / ``note_map_override``
       (sourced from ``[midi.cc_map]`` / ``[midi.note_map]`` in config.toml)
    """

    def __init__(
        self,
        device_hint: str = '',
        preset: str = '',
        cc_map_override: dict[int, str] | None = None,
        note_map_override: dict[int, str] | None = None,
    ) -> None:
        self._device_hint = device_hint.lower()
        self._listeners: list[Callable[[MidiEvent], None]] = []
        self._midi_in: 'rtmidi.MidiIn | None' = None
        self._port_name = ''
        self._lock = threading.Lock()
        self._cc_map, self._note_map = self._build_maps(preset, cc_map_override, note_map_override)
        self._preset = preset

    # ------------------------------------------------------------------
    # Map helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_maps(
        preset: str,
        cc_override: dict[int, str] | None,
        note_override: dict[int, str] | None,
    ) -> tuple[dict[int, str], dict[int, str]]:
        cc: dict[int, str] = dict(_CC_MAP_DEFAULT)
        note: dict[int, str] = dict(_NOTE_MAP_DEFAULT)
        if preset and preset in BUILTIN_PRESETS:
            p = BUILTIN_PRESETS[preset]
            cc.update(p.get('cc_map', {}))
            note.update(p.get('note_map', {}))
            log.info('MIDI: applied preset %r', preset)
        elif preset:
            log.warning('MIDI: unknown preset %r — using defaults', preset)
        if cc_override:
            cc.update(cc_override)
        if note_override:
            note.update(note_override)
        return cc, note

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def add_listener(self, fn: Callable[[MidiEvent], None]) -> None:
        """Register a callback; called from the rtmidi thread — keep it brief."""
        self._listeners.append(fn)

    def start(self) -> None:
        """Open the configured device port.  No-op when rtmidi is unavailable."""
        if not _RTMIDI_OK:
            return
        if not self._device_hint:
            log.info('MIDI: disabled (device hint is empty)')
            return
        self._open_port(self._device_hint)

    def reopen(self, device_hint: str) -> bool:
        """
        Hot-swap to a different MIDI port without restarting the app.

        Closes the current port (if any), then opens the port whose name
        contains ``device_hint``.  Passing an empty string closes the current
        port and leaves MIDI disabled.  Returns ``True`` on success.
        """
        self.stop()
        self._device_hint = device_hint.lower()
        if not device_hint:
            log.info('MIDI: hot-swap to no device (disabled)')
            return True
        if not _RTMIDI_OK:
            log.warning('MIDI: rtmidi unavailable — cannot reopen')
            return False
        return self._open_port(device_hint)

    def _open_port(self, hint: str) -> bool:
        try:
            midi_in = rtmidi.MidiIn()
            raw_ports = midi_in.get_ports()
            ports = [p if isinstance(p, str) else p.decode('utf-8', errors='replace')
                     for p in raw_ports]
            if not ports:
                log.info('MIDI: no ports available')
                return False

            chosen = None
            for i, name in enumerate(ports):
                if hint.lower() in name.lower():
                    chosen = i
                    break

            if chosen is None:
                log.warning(
                    'MIDI: no port matching %r — available: %s',
                    hint,
                    ', '.join(ports) or '(none)',
                )
                return False

            self._port_name = ports[chosen]
            midi_in.open_port(chosen)
            midi_in.set_callback(self._callback)
            midi_in.ignore_types(sysex=True, timing=True, active_sense=True)
            self._midi_in = midi_in
            log.info('MIDI: opened %s (preset=%r)', self._port_name, self._preset or 'default')
            return True
        except Exception as exc:
            log.warning('MIDI: failed to open port: %s', exc)
            return False

    def _callback(self, message: tuple[list[int], float], data=None) -> None:
        raw, _delta = message
        if not raw:
            return
        status = raw[0]
        msg_type = status & 0xF0
        channel  = status & 0x0F

        event: MidiEvent | None = None

        if msg_type == 0xB0 and len(raw) >= 3:    # CC
            event = MidiEvent('cc', channel, raw[1], raw[2] / 127.0)
        elif msg_type == 0x90 and len(raw) >= 3:   # Note On
            if raw[2] > 0:
                event = MidiEvent('note_on', channel, raw[1], raw[2] / 127.0)
            else:
                event = MidiEvent('note_off', channel, raw[1], 0.0)
        elif msg_type == 0x80 and len(raw) >= 3:   # Note Off
            event = MidiEvent('note_off', channel, raw[1], 0.0)

        if event is None:
            log.debug('MIDI: unhandled raw %s', [hex(b) for b in raw])
            return

        log.debug(
            'MIDI rx: %s ch=%d num=%d val=%.2f -> action=%s',
            event.type,
            event.channel,
            event.number,
            event.value,
            self._note_map.get(event.number) if event.type == 'note_on' else self._cc_map.get(event.number),
        )

        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(event)
            except Exception as exc:
                log.warning('MIDI listener error: %s', exc)

    def cc_to_param(self, cc: int) -> str | None:
        return self._cc_map.get(cc)

    def note_to_action(self, note: int) -> str | None:
        return self._note_map.get(note)

    def stop(self) -> None:
        if self._midi_in is not None:
            try:
                self._midi_in.close_port()
            except Exception:
                pass
            self._midi_in = None
            self._port_name = ''

    @property
    def port_name(self) -> str:
        return self._port_name

    @property
    def available(self) -> bool:
        return self._midi_in is not None

    @property
    def cc_map(self) -> dict[int, str]:
        return dict(self._cc_map)

    @property
    def note_map(self) -> dict[int, str]:
        return dict(self._note_map)
