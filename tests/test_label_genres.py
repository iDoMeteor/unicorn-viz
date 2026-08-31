"""Tests for the Stage 0 genre labeler's mapping logic (label_genres.py).

The essentia-tensorflow inference itself needs a dedicated venv and a
downloaded model (see the tool's docstring); everything mapping-shaped
is importable without either, and that's what this covers: the
Discogs-style → tempo-family/profile mapping, the BPM partition, the
DJ-edit caveat flag, and track gathering.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    'test_label_genres_module',
    _REPO / 'drop-ins' / 'training-kit-01' / 'tools' / 'label_genres.py')
assert spec is not None and spec.loader is not None
lg = importlib.util.module_from_spec(spec)
sys.modules['test_label_genres_module'] = lg
spec.loader.exec_module(lg)


def test_bpm_family_partition_boundaries() -> None:
    assert lg.bpm_family(0.0) == 'unknown'
    assert lg.bpm_family(87.0) == 'slow'
    assert lg.bpm_family(112.0) == 'midlow'
    assert lg.bpm_family(122.0) == 'house'
    assert lg.bpm_family(130.0) == 'peak'
    assert lg.bpm_family(140.0) == 'fast'
    assert lg.bpm_family(174.0) == 'double'


def test_style_mapping_hits_the_fold_relevant_genres() -> None:
    assert lg.style_to_family('Electronic---Drum n Bass') == ('double', 'drum_and_bass')
    assert lg.style_to_family('Hip Hop---Trap') == ('slow', 'rap_rnb')
    assert lg.style_to_family('Electronic---Tech House') == ('peak', 'tech_house')
    assert lg.style_to_family('Electronic---Deep House') == ('midlow', 'deep_house')
    assert lg.style_to_family('Electronic---House') == ('house', 'house')
    assert lg.style_to_family('Electronic---Dubstep') == ('fast', 'dubstep')
    assert lg.style_to_family('Electronic---Psy-Trance') == ('fast', 'psytrance')


def test_style_mapping_specific_beats_generic() -> None:
    # 'Tech House' must not fall through to the generic 'house' entry,
    # and 'Psy-Trance' must not read as plain 'trance'.
    assert lg.style_to_family('Electronic---Tech House')[1] == 'tech_house'
    assert lg.style_to_family('Electronic---Goa Trance')[1] == 'psytrance'
    assert lg.style_to_family('Electronic---Hard Techno')[1] == 'hard_techno'


def test_unmapped_style_is_unknown_not_error() -> None:
    assert lg.style_to_family('Rock---Grunge') == ('unknown', '')
    assert lg.style_to_family('Classical---Baroque') == ('unknown', '')


def test_edit_caveat_flags_non_electronic_umbrellas() -> None:
    assert lg.is_edit_caveat('Rock---Pop Rock') is True
    assert lg.is_edit_caveat('Pop---Ballad') is True
    assert lg.is_edit_caveat('Electronic---House') is False
    assert lg.is_edit_caveat('Hip Hop---Trap') is False


def test_gather_tracks_unions_baseline_and_playlists(tmp_path: Path) -> None:
    a = tmp_path / 'a.mp3'
    b = tmp_path / 'b.mp3'
    a.write_bytes(b'')
    b.write_bytes(b'')
    baseline = tmp_path / 'baseline.json'
    baseline.write_text(json.dumps({
        'a': {'path': str(a), 'bpm_truth': 125.0},
        'gone': {'path': str(tmp_path / 'gone.mp3'), 'bpm_truth': 100.0},
    }), encoding='utf-8')
    playlists = tmp_path / 'media_playlists.json'
    playlists.write_text(json.dumps({
        'playlists': {'traing - toughies': [str(b), str(a)]},
    }), encoding='utf-8')

    tracks = lg.gather_tracks(baseline, playlists, ['traing - toughies'])
    assert tracks[str(a)] == 125.0        # baseline bpm wins for shared track
    assert tracks[str(b)] == 0.0          # playlist-only track, no store bpm
    assert str(tmp_path / 'gone.mp3') not in tracks
