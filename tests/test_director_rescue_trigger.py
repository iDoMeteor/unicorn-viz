"""Director placement E4: the rescue-only relative drop trigger.

Pins the plumbing of the 2026-09-03 mechanism on a bare controller:
`drop_trigger_rel_threshold` / `_window_s` / `_min_bars` are global cfg
tunables read in `_apply_profile_settings()` (live-read contract), the
relative gate is eligible only after `drop_trigger_rel_min_bars` bars without
a drop on the current track, and the per-track clock resets on track change.
The gate itself runs inside the director tick and is validated by replay
cells (see docs/adr/vj-system.md "Director Placement E4").
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_AUTO_VJ = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_SPEC = importlib.util.spec_from_file_location('test_rescue_trigger_auto_vj', _AUTO_VJ)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules['test_rescue_trigger_auto_vj'] = _MOD
_SPEC.loader.exec_module(_MOD)
_SRC = _AUTO_VJ.read_text(encoding='utf-8')


def test_rescue_tunables_are_global_cfg_reads() -> None:
    assert "_cfg.get('drop_trigger_rel_threshold'" in _SRC
    assert "_cfg.get('drop_trigger_rel_window_s'" in _SRC
    assert "_cfg.get('drop_trigger_rel_min_bars'" in _SRC


def test_rescue_gate_requires_bars_since_last_drop() -> None:
    """rel_ok = threshold on AND (bars_since_track_start - last_drop_bar) >= min_bars."""
    assert "rel_ok = rel_thr > 0.0 and (int(self._bars_since_track_start) - int(self._last_drop_bar)) >= int(getattr(self, '_drop_trigger_rel_min_bars', 0) or 0)" in _SRC
    assert "if not _trigger_hit and rel_ok and trigger_rel >= rel_thr:" in _SRC
    assert "if drop_split and not _bd_drop_evidence and rel_ok and trigger_rel >= rel_thr:" in _SRC


def test_last_drop_bar_is_set_on_fire_and_reset_on_track_change() -> None:
    assert "self._last_drop_bar = int(self._bars_since_track_start)" in _SRC
    # the track-change reset sits right after bars_since_track_start resets
    idx = _SRC.index("        self._bars_since_track_start = 0\n")
    assert "self._last_drop_bar = -10_000" in _SRC[idx: idx + 200]


def test_rescue_is_scoped_to_never_fired_tracks_by_default() -> None:
    """Director rc.15: the shipped default scopes the rescue to tracks that
    have not fired a drop on the current track (the 64-bar re-arm alone
    breached the house-family drop-count guard on the re-baseline)."""
    assert "_cfg.get('drop_trigger_rel_first_only', 1)" in _SRC
    assert "if rel_ok and getattr(self, '_drop_trigger_rel_first_only', False) and int(self._last_drop_bar) >= 0:" in _SRC


def test_relative_trigger_uses_rolling_p90_with_floor() -> None:
    assert "trigger_rel = trigger / max(0.15, p90)" in _SRC
    assert "p90 = vals[int(0.9 * (len(vals) - 1))]" in _SRC
