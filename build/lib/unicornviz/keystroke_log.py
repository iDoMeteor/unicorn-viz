"""Optional append-only keystroke log with beat-context snapshot.

One compact JSON line is written per keypress when enabled.
Fields are intentionally minimal to keep log files small:

    {"t": 1747341600.123, "key": "N", "effect": "Plasma", "bpm": 128,
     "beat_phase": 0.42, "energy": 0.61, "vj_mode": "CRUISE"}

Enable in config::

    [keystrokes]
    enabled = true

Log path: ``logs/keystrokes-<YYYYMMDD-HHMMSS>.log``
"""
from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_LOGS_DIR = Path(__file__).parent.parent / 'logs'


class KeystrokeLogger:
    """Appends one JSON line per keypress when enabled.

    Thread-safety: call only from the main render thread.
    """

    def __init__(self, enabled: bool, logs_dir: Path | None = None) -> None:
        self._enabled = enabled
        self._file = None
        if not enabled:
            return
        base = logs_dir or _LOGS_DIR
        try:
            base.mkdir(parents=False, exist_ok=True)
            ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
            path = base / f'keystrokes-{ts}.log'
            self._file = open(path, 'a', encoding='utf-8')  # noqa: SIM115
            log.info('Keystroke log: %s', path)
        except Exception as exc:
            log.warning('Could not open keystroke log: %s', exc)
            self._enabled = False

    def log_key(
        self,
        key_label: str,
        effect_name: str,
        *,
        bpm: float = 0.0,
        beat_phase: float = 0.0,
        energy: float = 0.0,
        vj_mode: str = '',
    ) -> None:
        """Append one entry.  Silently does nothing when disabled or on I/O error."""
        if not self._enabled or self._file is None:
            return
        entry: dict[str, Any] = {
            't': datetime.datetime.now().timestamp(),
            'key': key_label,
            'effect': effect_name,
        }
        if bpm > 0.0:
            entry['bpm'] = round(bpm, 1)
        if beat_phase > 0.0:
            entry['beat_phase'] = round(beat_phase, 3)
        if energy > 0.0:
            entry['energy'] = round(energy, 3)
        if vj_mode:
            entry['vj_mode'] = vj_mode
        try:
            self._file.write(json.dumps(entry) + '\n')
            self._file.flush()
        except Exception:
            pass

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None
