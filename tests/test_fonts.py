"""Regression tests for the shared cross-platform font resolver.

Pins the Windows-release contract: the bundled UI font is always the first
candidate on every platform (system dirs are fallbacks only), Windows gets
real font-directory candidates instead of silently degrading to PIL's
bitmap font, and load_font never raises.
"""
from __future__ import annotations

import unicornviz.fonts as fonts


def test_bundled_font_is_first_candidate_and_ships() -> None:
    candidates = fonts.font_candidates()
    assert candidates, 'candidate list must never be empty'
    first = candidates[0]
    assert first.name == 'ui-font.ttf'
    assert first.exists(), 'bundled assets/fonts/ui-font.ttf must ship'


def test_load_font_returns_truetype_at_requested_size() -> None:
    font = fonts.load_font(17)
    assert font is not None
    # The bundled candidate exists, so we must get a scalable face,
    # never the tiny PIL bitmap fallback.
    assert getattr(font, 'size', None) == 17


def test_windows_candidates_cover_fonts_dir(monkeypatch) -> None:
    monkeypatch.setattr(fonts.sys, 'platform', 'win32')
    monkeypatch.setenv('WINDIR', 'C:\\Windows')
    names = [p.name for p in fonts.font_candidates()]
    assert names[0] == 'ui-font.ttf'
    assert 'consola.ttf' in names
    emoji_names = [p.name for p in fonts.emoji_candidates()]
    assert 'seguiemj.ttf' in emoji_names


def test_load_font_never_raises_without_candidates(monkeypatch) -> None:
    monkeypatch.setattr(fonts, 'font_candidates', lambda: [])
    assert fonts.load_font(12) is not None  # PIL bitmap fallback


def test_emoji_font_absent_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(fonts, 'emoji_candidates', lambda: [])
    assert fonts.load_emoji_font(140) is None
