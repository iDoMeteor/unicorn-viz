"""Opt-in replay tests over local audio fixtures (v3 plan Phase A item 6).

Gated on ``UNICORNVIZ_TRACK_FIXTURES`` pointing at a directory containing
a ``fixtures.json`` manifest; skips cleanly (CI and other machines are
unaffected) when unset. Audio files are never committed — the fixture
directory is local-only.

Manifest format (``fixtures.json``)::

    [
        {
            "path": "chillstep/song.mp3",        // relative to the manifest dir
                                                  // (absolute paths also allowed)
            "expected_bpm": 140.0,
            "expected_fold_tolerance": true,      // optional: accept Acc2
                                                  // folds (default true);
                                                  // false requires Acc1
            "profile": "house",                   // optional audio profile
            "max_duration_s": 150                 // optional, default 150
        },
        ...
    ]

Assertions are floors, not exact values (the plan's anti-flake rule):
each fixture must reach Acc2 (or Acc1 when ``expected_fold_tolerance``
is false) against its ``expected_bpm``.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

_ENV_VAR = 'UNICORNVIZ_TRACK_FIXTURES'


def _load_manifest() -> list[dict]:
    root = os.environ.get(_ENV_VAR, '').strip()
    if not root:
        return []
    manifest = Path(root).expanduser() / 'fixtures.json'
    if not manifest.exists():
        return []
    try:
        entries = json.loads(manifest.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(entries, list):
        return []
    for entry in entries:
        if isinstance(entry, dict):
            entry['_root'] = str(Path(root).expanduser())
    return [e for e in entries if isinstance(e, dict) and e.get('path')]


_ENTRIES = _load_manifest()

pytestmark = pytest.mark.local_tracks

if not _ENTRIES:
    pytest.skip(
        f'{_ENV_VAR} not set (or no fixtures.json found) — local-track '
        'replay tier skipped',
        allow_module_level=True,
    )


def _track_replay():
    path = _REPO / 'drop-ins' / 'training-kit-01' / 'tools' / 'track_replay.py'
    spec = importlib.util.spec_from_file_location('local_track_replay_mod', path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['local_track_replay_mod'] = mod  # dataclasses need this
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    'entry', _ENTRIES, ids=[Path(e['path']).stem for e in _ENTRIES])
def test_local_fixture_tracks_to_expected_bpm(entry: dict) -> None:
    track_replay = _track_replay()
    from unicornviz.audio.analyzer import Analyzer
    from unicornviz.audio.profiles import get_profile

    path = Path(entry['path']).expanduser()
    if not path.is_absolute():
        path = Path(entry['_root']) / path
    if not path.exists():
        pytest.skip(f'fixture audio missing: {path}')

    expected = float(entry['expected_bpm'])
    assert expected > 0.0, 'manifest entry needs expected_bpm > 0'
    accept_folds = bool(entry.get('expected_fold_tolerance', True))
    max_duration = float(entry.get('max_duration_s', 150.0))

    profile = get_profile(str(entry.get('profile', 'house')))
    analyzer = Analyzer(fft_bands=512, profile=profile)
    tracker = track_replay.load_beat_grid_module().BeatTracker({})
    tracker.set_profile(profile)

    result = track_replay.stream_track(path, analyzer, tracker,
                                       max_duration_s=max_duration)
    metrics = track_replay.replay_metrics(result, expected)

    detail = (f'{path.name}: predicted {metrics["bpm_median"]} vs expected '
              f'{expected} (fold {metrics["fold"]}, '
              f'lock {metrics["time_to_first_lock_s"]}s)')
    assert metrics['locked_ticks'] > 0, f'never locked — {detail}'
    if accept_folds:
        assert metrics['acc2'], f'outside every accepted fold — {detail}'
    else:
        assert metrics['acc1'], f'outside ±4% — {detail}'
