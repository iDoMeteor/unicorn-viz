"""Boot-profile resolution for mixer-only mode.

One switch boots Unicorn Viz as a DJ mixer that happens to share the
visualizer's engine (see drop-ins/dj-mixer-01/docs/mixer-only-mode-plan.md).
This module owns the *decision*: which profile the app boots into and which
config sections stay loadable under it. Every boot gate in ``app.py`` reads
``App._boot_profile`` — resolved here exactly once — never the raw config,
so precedence lives in one place:

    --mixer CLI flag  >  [dj_mixer] mixer_only  >  full (default)

Contradictions degrade to the full profile with a loud note rather than a
crash: mixer-only with the dj-mixer drop-in absent or disabled boots normal.
``safe_mode`` + mixer profile boots the mixer (the profile wins for the
mixer itself — safe_mode alone would gate the dj-mixer block too, making
the combination boot into nothing) while every other drop-in stays skipped.
"""
from __future__ import annotations

from typing import Any, Callable

PROFILE_FULL = 'full'
PROFILE_MIXER = 'mixer'

# Config sections always loadable in the mixer profile, regardless of
# mixer_allow: the mixer itself. (MIDI is core-owned and not section-gated.)
_ALWAYS_ALLOWED = frozenset({'dj_mixer'})


def resolve_boot_profile(
    cfg: Any, dropin_present: bool | Callable[[], bool],
) -> tuple[str, list[str]]:
    """Resolve the boot profile once, early.

    ``cfg`` is the app Config (CLI overrides already merged — ``--mixer``
    arrives as ``[dj_mixer] mixer_only = true``). ``dropin_present`` reports
    whether the dj-mixer-01 drop-in exists on disk. Returns
    ``(profile, notes)`` where ``notes`` are operator-facing messages the
    caller should log loudly.
    """
    if not bool(cfg.get('dj_mixer', 'mixer_only', default=False)):
        return PROFILE_FULL, []
    if callable(dropin_present):
        dropin_present = bool(dropin_present())
    notes: list[str] = []
    if not bool(cfg.get('dj_mixer', 'enabled', default=True)):
        notes.append(
            'mixer_only=true but [dj_mixer] enabled=false — contradiction; '
            'booting the full profile',
        )
        return PROFILE_FULL, notes
    if not dropin_present:
        notes.append(
            'mixer_only requires the dj-mixer-01 drop-in, which is absent; '
            'booting the full profile',
        )
        return PROFILE_FULL, notes
    if bool(cfg.get('dropins', 'safe_mode', default=False)):
        notes.append(
            'safe_mode + mixer_only: the mixer profile wins for the mixer '
            'itself; every other drop-in stays skipped',
        )
    return PROFILE_MIXER, notes


def mixer_allowed_sections(cfg: Any) -> frozenset[str]:
    """Config sections loadable in the mixer profile.

    ``[dj_mixer] mixer_allow`` lists extra drop-ins by config-section name
    (e.g. ``["media", "osc"]``); the mixer itself is always included.
    """
    raw = cfg.get('dj_mixer', 'mixer_allow', default=[]) or []
    allowed = set(_ALWAYS_ALLOWED)
    if isinstance(raw, (list, tuple)):
        for item in raw:
            name = str(item).strip().lower()
            if name:
                allowed.add(name)
    return frozenset(allowed)
