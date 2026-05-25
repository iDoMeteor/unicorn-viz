"""
MIDI controller support.

Listens for Control Change and Note On messages on any connected MIDI device.
Emits a MidiEvent that the App dispatches to the active effect's on_midi() hook.

Default mapping (Novation LaunchControl / generic CC layout):
  CC 74  → effect parameter "speed"
  CC 71  → effect parameter "intensity"  
  CC 91  → effect parameter "glow"
  CC 93  → audio gain override
  Note C4 (60) → next effect
  Note D4 (62) → previous effect
  Note E4 (64) → toggle audio reactive
  Note F4 (65) → random effect
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
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


# Default CC → parameter name mapping
_CC_MAP: dict[int, str] = {
    74: "speed",
    71: "intensity",
    91: "glow",
    93: "crt",
    7:  "volume",
    10: "pan",
}

# Default note → action name mapping
_NOTE_MAP: dict[int, str] = {
    60: "next",          # C4
    62: "prev",          # D4
    64: "audio_toggle",  # E4
    65: "random",        # F4
    67: "pause",         # G4
    69: "fullscreen",    # A4
}


class MidiManager:
    """
    Opens the first available MIDI input port and forwards events to
    registered callbacks.
    """

    def __init__(self, device_hint: str = "") -> None:
        self._device_hint = device_hint.lower()
        self._listeners: list[Callable[[MidiEvent], None]] = []
        self._midi_in: "rtmidi.MidiIn | None" = None
        self._port_name = ""
        self._lock = threading.Lock()
        self._cc_map = dict(_CC_MAP)
        self._note_map = dict(_NOTE_MAP)

    def add_listener(self, fn: Callable[[MidiEvent], None]) -> None:
        self._listeners.append(fn)

    def start(self) -> None:
        if not _RTMIDI_OK:
            return
        if not self._device_hint:
            log.info("MIDI: disabled (device hint is empty)")
            return
        try:
            midi_in = rtmidi.MidiIn()
            ports = midi_in.get_ports()
            if not ports:
                log.info("MIDI: no ports available")
                return

            chosen = 0
            if self._device_hint:
                for i, name in enumerate(ports):
                    if self._device_hint in name.lower():
                        chosen = i
                        break

            self._port_name = ports[chosen]
            midi_in.open_port(chosen)
            midi_in.set_callback(self._callback)
            midi_in.ignore_types(sysex=True, timing=True, active_sense=True)
            self._midi_in = midi_in
            log.info("MIDI: opened %s", self._port_name)
        except Exception as exc:
            log.warning("MIDI: failed to open port: %s", exc)

    def _callback(self, message: tuple[list[int], float], data=None) -> None:
        raw, _delta = message
        if not raw:
            return
        status = raw[0]
        msg_type = status & 0xF0
        channel  = status & 0x0F

        event: MidiEvent | None = None

        if msg_type == 0xB0 and len(raw) >= 3:   # CC
            event = MidiEvent("cc", channel, raw[1], raw[2] / 127.0)
        elif msg_type == 0x90 and len(raw) >= 3:  # Note On
            if raw[2] > 0:
                event = MidiEvent("note_on", channel, raw[1], raw[2] / 127.0)
            else:
                event = MidiEvent("note_off", channel, raw[1], 0.0)
        elif msg_type == 0x80 and len(raw) >= 3:  # Note Off
            event = MidiEvent("note_off", channel, raw[1], 0.0)

        if event is None:
            return

        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(event)
            except Exception as exc:
                log.debug("MIDI listener error: %s", exc)

    def cc_to_param(self, cc: int) -> str | None:
        return self._cc_map.get(cc)

    def note_to_action(self, note: int) -> str | None:
        return self._note_map.get(note)

    def stop(self) -> None:
        if self._midi_in is not None:
            self._midi_in.close_port()
            self._midi_in = None

    @property
    def port_name(self) -> str:
        return self._port_name

    @property
    def available(self) -> bool:
        return self._midi_in is not None
