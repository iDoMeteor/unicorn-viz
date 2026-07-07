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
import time
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
# Drop-ins extend this at startup via MidiManager.register_preset().
# ---------------------------------------------------------------------------

BUILTIN_PRESETS: dict[str, dict[str, dict[int, str]]] = {
    # Generic / unknown device — same as built-in defaults.
    # Device-specific presets (APC mini mk2, MPK Mini, Novation LaunchControl)
    # are registered at startup by the midi-controllers-01 drop-in via
    # MidiManager.register_preset().
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


def list_output_ports() -> list[str]:
    """Return available MIDI output port names; empty list when rtmidi is absent."""
    if not _RTMIDI_OK:
        return []
    try:
        tmp = rtmidi.MidiOut()
        ports = tmp.get_ports()
        del tmp
        return [p if isinstance(p, str) else p.decode('utf-8', errors='replace') for p in ports]
    except Exception as exc:
        log.debug('MIDI list_output_ports failed: %s', exc)
        return []


class MidiManager:
    """
    Opens one or more MIDI input ports and forwards CC/Note events to listeners.

    Map resolution order (later layers win):
    1. Built-in defaults (``_CC_MAP_DEFAULT`` / ``_NOTE_MAP_DEFAULT``)
    2. Named preset from ``BUILTIN_PRESETS`` (if ``preset`` is given)
    3. Per-entry overrides from ``cc_map_override`` / ``note_map_override``
       (sourced from ``[midi.cc_map]`` / ``[midi.note_map]`` in config.toml)

    Drop-ins extend ``BUILTIN_PRESETS`` via :meth:`register_preset` and
    enable dual-port auto-bind via :meth:`register_dual_port_model`.
    """

    # preset_name → model substring that triggers dual-port auto-bind.
    _dual_port_registry: 'dict[str, str]' = {}

    @classmethod
    def register_preset(
        cls,
        name: str,
        mapping: dict[str, dict[int, str]],
    ) -> None:
        """Register a named preset so it can be selected via ``config.toml``.

        Call this before ``MidiManager.__init__`` (typically from a drop-in
        initialiser).  Silently overwrites any existing preset of the same name.
        """
        BUILTIN_PRESETS[name] = mapping
        log.debug('MIDI: registered preset %r', name)

    @classmethod
    def register_dual_port_model(cls, preset_name: str, model_token: str) -> None:
        """Register a model token that enables dual-port auto-bind for a preset.

        When ``preset_name`` is active, ``_resolve_target_indices`` will scan
        available ports for ``model_token`` (case-insensitive substring) and
        open both the Notes and Control ports automatically.
        """
        cls._dual_port_registry[preset_name] = model_token.lower()
        log.debug('MIDI: registered dual-port token %r for preset %r', model_token, preset_name)

    def __init__(
        self,
        device_hint: str = '',
        preset: str = '',
        cc_map_override: dict[int, str] | None = None,
        note_map_override: dict[int, str] | None = None,
    ) -> None:
        self._device_hint = device_hint.lower()
        self._listeners: list[Callable[[MidiEvent], None]] = []
        self._named_listeners: dict[str, Callable[[MidiEvent], None]] = {}
        self._midi_ins: list['rtmidi.MidiIn'] = []
        self._port_names: list[str] = []
        self._port_name = ''
        self._last_maintenance_attempt = 0.0
        self._maintenance_interval_s = 2.0
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

    def add_named_listener(self, name: str, fn: Callable[[MidiEvent], None]) -> None:
        """Register a named MIDI event listener, replacing any with the same name."""
        with self._lock:
            self._named_listeners[str(name)] = fn

    def remove_named_listener(self, name: str) -> None:
        """Remove a named listener previously added via add_named_listener."""
        with self._lock:
            self._named_listeners.pop(str(name), None)

    def set_note_binding(self, note: int, action: str) -> None:
        """Bind *note* to *action*, overriding any preset mapping."""
        self._note_map[int(note)] = str(action)

    def clear_note_binding(self, note: int) -> None:
        """Remove any binding for *note*."""
        self._note_map.pop(int(note), None)

    def set_cc_binding(self, cc: int, param: str) -> None:
        """Bind CC *cc* to *param*, overriding any preset mapping."""
        self._cc_map[int(cc)] = str(param)

    def clear_cc_binding(self, cc: int) -> None:
        """Remove any binding for CC *cc*."""
        self._cc_map.pop(int(cc), None)

    def start(self) -> None:
        """Open the configured device port(s).  No-op when rtmidi is unavailable."""
        if not _RTMIDI_OK:
            return
        if not self._device_hint:
            log.info('MIDI: disabled (device hint is empty)')
            return
        hint = self._device_hint
        if not self._open_ports(hint):
            # Disable background maintenance polling until the operator explicitly
            # selects a MIDI device again from the runtime selector.
            self._device_hint = ''
            log.info(
                'MIDI: startup device %r unavailable; polling disabled until explicit selection',
                hint,
            )

    def reopen(self, device_hint: str) -> bool:
        """
        Hot-swap to a different MIDI port without restarting the app.

        Closes active port(s), then opens port(s) matching ``device_hint``.
        Passing an empty string closes active ports and leaves MIDI disabled.
        Returns ``True`` on success.
        """
        self.stop()
        self._device_hint = device_hint.lower()
        if not device_hint:
            log.info('MIDI: hot-swap to no device (disabled)')
            return True
        if not _RTMIDI_OK:
            log.warning('MIDI: rtmidi unavailable — cannot reopen')
            return False
        ok = self._open_ports(device_hint)
        if not ok:
            # Avoid repeated ALSA sequencer probing noise when the requested
            # device is absent; keep MIDI disabled until next explicit select.
            self._device_hint = ''
        return ok

    def maintenance_update(self) -> None:
        """Best-effort hotplug maintenance for reconnect/disconnect handling."""
        if not _RTMIDI_OK or not self._device_hint:
            return

        now = time.monotonic()
        if (now - self._last_maintenance_attempt) < self._maintenance_interval_s:
            return
        self._last_maintenance_attempt = now

        available_ports = list_ports()
        available_lower = {p.lower() for p in available_ports}

        if self.available:
            missing = [p for p in self._port_names if p.lower() not in available_lower]
            if missing:
                log.warning(
                    'MIDI: active port(s) disappeared: %s — attempting reconnect',
                    ', '.join(missing),
                )
                self.reopen(self._device_hint)
            return

        if self._resolve_target_indices(available_ports, self._device_hint, self._preset):
            if self._open_ports(self._device_hint):
                log.info('MIDI: reconnected %s', self.active_port_label)

    @staticmethod
    def _normalize_port_name(name: str) -> str:
        return ' '.join(name.lower().split())

    @classmethod
    def _resolve_target_indices(cls, ports: list[str], hint: str, preset: str) -> list[int]:
        hint_norm = cls._normalize_port_name(hint)
        matches = [
            i for i, name in enumerate(ports)
            if hint_norm and hint_norm in cls._normalize_port_name(name)
        ]

        model_token = cls._dual_port_registry.get(preset, '')
        if not model_token:
            return matches[:1]

        # Dual-port auto-bind: find all ports matching the registered model token.
        model_ports = [
            i for i, name in enumerate(ports)
            if model_token in cls._normalize_port_name(name)
        ]
        if not model_ports:
            return matches[:1]

        # Respect an explicit hint pointing at a non-model device.
        if matches and not any(i in model_ports for i in matches):
            return matches[:1]

        candidates = list(model_ports)
        notes = [
            i for i in candidates
            if 'notes' in cls._normalize_port_name(ports[i]) or ' note' in cls._normalize_port_name(ports[i])
        ]
        control = [i for i in candidates if 'control' in cls._normalize_port_name(ports[i])]

        chosen: list[int] = []
        if notes:
            chosen.append(notes[0])
        if control and control[0] not in chosen:
            chosen.append(control[0])

        for idx in candidates:
            if len(chosen) >= 2:
                break
            if idx not in chosen:
                chosen.append(idx)

        return chosen[:2]

    def _open_ports(self, hint: str) -> bool:
        try:
            ports = list_ports()
            if not ports:
                log.info('MIDI: no ports available')
                return False

            chosen = self._resolve_target_indices(ports, hint, self._preset)

            if not chosen:
                log.warning(
                    'MIDI: no port matching %r — available: %s',
                    hint,
                    ', '.join(ports) or '(none)',
                )
                return False

            opened: list['rtmidi.MidiIn'] = []
            chosen_names = [ports[i] for i in chosen]
            for idx in chosen:
                midi_in = rtmidi.MidiIn()
                midi_in.open_port(idx)
                midi_in.set_callback(self._callback)
                midi_in.ignore_types(sysex=True, timing=True, active_sense=True)
                opened.append(midi_in)

            self._midi_ins = opened
            self._port_names = chosen_names
            self._port_name = chosen_names[0]
            log.info(
                'MIDI: opened %s (preset=%r)',
                self.active_port_label,
                self._preset or 'default',
            )
            return True
        except Exception as exc:
            self.stop()
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
            named = list(self._named_listeners.values())
        for fn in listeners:
            try:
                fn(event)
            except Exception as exc:
                log.warning('MIDI listener error: %s', exc)
        for fn in named:
            try:
                fn(event)
            except Exception as exc:
                log.warning('MIDI named listener error: %s', exc)

    def cc_to_param(self, cc: int) -> str | None:
        return self._cc_map.get(cc)

    def note_to_action(self, note: int) -> str | None:
        return self._note_map.get(note)

    def stop(self) -> None:
        for midi_in in self._midi_ins:
            try:
                midi_in.close_port()
            except Exception:
                pass
        self._midi_ins = []
        self._port_names = []
        self._port_name = ''

    @property
    def port_name(self) -> str:
        return self._port_name

    @property
    def port_names(self) -> list[str]:
        return list(self._port_names)

    @property
    def active_port_label(self) -> str:
        if not self._port_names:
            return ''
        return ' + '.join(self._port_names)

    @property
    def available(self) -> bool:
        return bool(self._midi_ins)

    @property
    def cc_map(self) -> dict[int, str]:
        return dict(self._cc_map)

    @property
    def note_map(self) -> dict[int, str]:
        return dict(self._note_map)


# ---------------------------------------------------------------------------
# MIDI output (LED feedback / SysEx)
# ---------------------------------------------------------------------------

class MidiOut:
    """Thin rtmidi.MidiOut wrapper for LED feedback and SysEx output.

    Safe to instantiate when rtmidi is unavailable; all methods degrade
    gracefully to no-ops.  One port is held open per instance; call
    :meth:`open` before :meth:`send`.

    Thread safety: :meth:`send` is safe to call from any thread once the
    port is open, but :meth:`open` / :meth:`close` must be called from the
    main thread.
    """

    _RETRY_INTERVAL_S = 10.0   # seconds between re-attempts when port not found

    def __init__(self) -> None:
        self._port: 'rtmidi.MidiOut | None' = None
        self._port_name: str = ''
        self._hint: str = ''
        self._last_open_attempt: float = -self._RETRY_INTERVAL_S  # allow first attempt

    def list_ports(self) -> list[str]:
        """Return available MIDI output port names."""
        return list_output_ports()

    def open(self, hint: str) -> bool:
        """Open the first output port whose name contains *hint* (case-insensitive).

        Closes any previously open port first.  Silently skips re-attempts
        that arrive within ``_RETRY_INTERVAL_S`` of the last failed attempt so
        callers can invoke this on every frame without flooding the log.
        Returns True on success.
        """
        if not _RTMIDI_OK:
            return False
        now = time.monotonic()
        if now - self._last_open_attempt < self._RETRY_INTERVAL_S:
            return False
        self._last_open_attempt = now
        self.close()
        try:
            ports = list_output_ports()
            hint_low = hint.lower()
            idx = next(
                (i for i, p in enumerate(ports) if hint_low in p.lower()),
                None,
            )
            if idx is None:
                log.debug(
                    'MidiOut: no output port matching %r — available: %s',
                    hint,
                    ', '.join(ports) or '(none)',
                )
                return False
            out = rtmidi.MidiOut()
            out.open_port(idx)
            self._port = out
            self._port_name = ports[idx]
            self._hint = hint
            log.info('MidiOut: opened %r', self._port_name)
            return True
        except Exception as exc:
            self.close()
            log.warning('MidiOut: failed to open port: %s', exc)
            return False

    def send(self, message: list[int]) -> bool:
        """Send a raw MIDI message; returns True on success."""
        if self._port is None:
            return False
        try:
            self._port.send_message(message)
            return True
        except Exception as exc:
            log.debug('MidiOut: send failed: %s', exc)
            return False

    def close(self) -> None:
        """Close the active output port."""
        if self._port is not None:
            try:
                self._port.close_port()
            except Exception:
                pass
            self._port = None
            self._port_name = ''
            self._hint = ''

    @property
    def available(self) -> bool:
        """Return True when an output port is open."""
        return self._port is not None

    @property
    def port_name(self) -> str:
        """Return the name of the active output port, or empty string."""
        return self._port_name

    @property
    def hint(self) -> str:
        """Return the hint string used to open the current port."""
        return self._hint
