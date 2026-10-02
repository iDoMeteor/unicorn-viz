"""Never overwrite a settings file that failed to load.

``runtime/global_state.json`` holds every menu setting (config.toml is being
retired), ``config_profiles.json`` every saved profile and ``presets.json`` the
show presets.  Each store used to turn a parse failure into an empty store and
then save over the file at the next change, so one truncated or hand-mangled
byte lost everything (2026-09-30 audit, P1-6).

:func:`quarantine` is the shared answer: move the unreadable file aside as
``<name>.corrupt-<timestamp>`` (the bytes are kept untouched, a rename), log one
clear ERROR, and let the store start from defaults.

Save policy, decided here and used by all three stores: **saves go to the
original path only after the quarantine copy exists.**  If the file could be
neither moved nor copied aside (read-only directory, permissions), the store
*blocks saves for the session* (``blocked`` is True), logs that once, and the
original stays exactly as it was.
"""
from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path

log = logging.getLogger(__name__)


def _free_name(path: Path) -> Path:
    stamp = time.strftime('%Y%m%dT%H%M%S')
    candidate = path.with_name(f'{path.name}.corrupt-{stamp}')
    n = 1
    while candidate.exists():
        n += 1
        candidate = path.with_name(f'{path.name}.corrupt-{stamp}-{n}')
    return candidate


def quarantine(path: Path, reason: str, what: str = 'settings file') -> Path | None:
    """Move an unloadable ``path`` aside; return where it went, or None.

    None means the bytes could not be preserved elsewhere: the caller must then
    treat the path as read-only for the session (see the module docstring).
    A rename is tried first (the bytes never move on disk), then a copy.
    """
    target = _free_name(path)
    try:
        os.replace(path, target)
    except OSError as exc:
        try:
            shutil.copy2(path, target)
        except OSError as exc2:
            log.error('%s %s could not be loaded (%s) and could not be moved aside '
                      '(%s; %s); leaving it untouched and NOT saving to it this session',
                      what, path, reason, exc, exc2)
            return None
        # Copied but not moved: the original is still there, so saving over it
        # is only safe because the copy now holds the old bytes.
        log.error('%s %s could not be loaded (%s); its bytes are kept in %s and '
                  'the store starts from defaults', what, path, reason, target)
        return target
    log.error('%s %s could not be loaded (%s); moved to %s and starting from '
              'defaults. Nothing was lost; restore it by hand if you can repair it.',
              what, path, reason, target)
    return target


def keep_copy(path: Path, reason: str, what: str = 'settings file') -> Path | None:
    """Copy ``path`` aside without disturbing it (a loadable file whose content
    the store is about to partly drop), so the dropped bytes survive its next save."""
    target = _free_name(path)
    try:
        shutil.copy2(path, target)
    except OSError as exc:
        log.warning('%s %s: could not keep a copy (%s): %s', what, path, reason, exc)
        return None
    log.warning('%s %s: %s; the original is kept as %s', what, path, reason, target)
    return target
