"""Regression tests for the Spotify HUD pane layout in overlays.py.

Guards the centered single-line text + full-width progress bar redesign
and the auto-VJ waveform history mode so neither can silently revert.
"""
from __future__ import annotations

import numpy as np
from unittest.mock import MagicMock

from unicornviz.overlays import Overlays


# ---------------------------------------------------------------------------
# Minimal stub factory — bypasses GL __init__, only sets what _render_hud needs.
# ---------------------------------------------------------------------------

_BASE_HUD_STATE: dict[str, str] = {
    'title': 'Unicorn Viz',
    'effect': 'Test',
    'previous_effect': '-',
    'next_effect': '-',
    'transition': 'fade',
    'transition_t': '0%',
    'fps': '60.0',
    'frame_ms': '16.7',
    'resolution': '1920x1080',
    'render_scale': '1.00',
    'playlist': 'default',
    'paused': 'NO',
    'fullscreen': 'NO',
    'auto_advance': 'ON',
    'advance_time': '10.0/20.0s',
    'reactivity': '1.0x',
    'speed': '1.0x',
    'audio_source': 'default',
    'audio_profile': 'house',
    'audio_profile_name': 'house',
    'audio_profile_reco': '',
    'audio_rms': '0.1',
    'audio_beat': '0.000',
    'preset_slot_label': 'PRESET IDX',
    'preset_slot': '1/5',
    'variant_slot_label': 'VARIANT',
    'variant_slot': '1/3',
    'auto_vj_label': 'AUTO VJ',
    'auto_vj_training_badge': '',
    'auto_vj_bpm': '0',
    'auto_vj_mood': 'energetic',
    'auto_vj_scene': '1',
    'auto_vj_action_in': '30s',
    'recording': 'OFF',
    'streaming': 'OFF',
    'streaming_provider': '-',
    'spotify_visible': 'YES',
    'spotify_auth_visible': 'NO',
    'spotify_auth_status': 'OFF',
    'spotify_status': 'PLAYING',
    'spotify_track': 'My Song',
    'spotify_artist': 'The Artist',
    'spotify_progress': '02:30/05:00 50%',
    'postfx': 'N/A',
    'bass': '0.50',
    'mid': '0.30',
    'treble': '0.20',
    'bass_n': '0.50',
    'mid_n': '0.30',
    'treble_n': '0.20',
    'display_mode': 'single',
    'display_index': '0',
    'invert': 'OFF',
    'vj_status': '',
    'zoom': '1.0',
    'session_time': '05:00',
    'compose_debug': '',
}


def _make_stub(extra: dict[str, str] | None = None) -> Overlays:
    """Create a bare Overlays instance suitable for calling _render_hud()."""
    ov: Overlays = object.__new__(Overlays)
    ov._width = 1920
    ov._height = 1080
    ov._hud_t = 0.0
    ov._glyph_w = 8
    ov._glyph_h = 16
    ov._font_scale_norm = 0.5  # = 8.0 / 16
    ov._hud_rect = None
    ov._hud_state = dict(_BASE_HUD_STATE)
    if extra:
        ov._hud_state.update(extra)
    # Waveform attributes (normally set in __init__).
    ov._live_waveform = None
    ov._spotify_beat_decay = 0.0
    ov._draw_text = MagicMock()  # type: ignore[method-assign]
    ov._draw_rect = MagicMock()  # type: ignore[method-assign]
    return ov


def _text_calls(ov: Overlays) -> list[str]:
    return [c.args[0] for c in ov._draw_text.call_args_list]  # type: ignore[attr-defined]


def _rect_calls(ov: Overlays) -> list[tuple[float, float, float, float]]:
    return [c.args[:4] for c in ov._draw_rect.call_args_list]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Text format tests
# ---------------------------------------------------------------------------

class TestSpotifyHudPaneFormat:
    """Verify the Spotify pane uses the redesigned centered single-line layout."""

    def test_centered_line_contains_artist_track_progress(self) -> None:
        """Exactly one text draw in the pane must carry artist | track | progress."""
        ov = _make_stub()
        ov._render_hud()

        expected = 'The Artist | My Song | 02:30/05:00 50%'
        texts = _text_calls(ov)
        assert expected in texts, (
            f'Expected centered Spotify line not found.\n'
            f'Expected: {expected!r}\n'
            f'Got draw_text calls: {texts}'
        )

    def test_no_legacy_spotify_prefix_in_text(self) -> None:
        """The old 'SPOTIFY PLAYING | ...' pane line must not appear.

        Note: 'SPOTIFY AUTH ...' is a legitimately-drawn data-zone string and
        must not be flagged.  The old pane format is distinguishable by the
        pipe-separated artist/progress fields that follow the status word.
        """
        ov = _make_stub()
        ov._render_hud()

        texts = _text_calls(ov)
        bad = [t for t in texts if t.startswith('SPOTIFY ') and ' | ' in t]
        assert not bad, f'Legacy SPOTIFY pane line found in draw_text calls: {bad}'

    def test_track_not_drawn_separately(self) -> None:
        """Track name must not be drawn as a standalone right-aligned string."""
        ov = _make_stub()
        ov._render_hud()

        texts = _text_calls(ov)
        standalone = [t for t in texts if t == 'My Song']
        assert not standalone, (
            f'Track name drawn as standalone string (old right-aligned format): {standalone}'
        )

    def test_progress_not_drawn_as_standalone_label(self) -> None:
        """Progress string must not appear as a separate small-scale text label."""
        ov = _make_stub()
        ov._render_hud()

        texts = _text_calls(ov)
        standalone = [t for t in texts if t == '02:30/05:00 50%']
        assert not standalone, (
            f'Progress drawn as standalone label (duplicate old behavior): {standalone}'
        )


# ---------------------------------------------------------------------------
# Flat-bar fallback tests (auto_vj_bpm == 0)
# ---------------------------------------------------------------------------

class TestSpotifyHudPaneBar:
    """Verify the full-width flat-bar fallback when auto-VJ is not active."""

    # No BPM → flat bar fallback.
    _FLAT: dict[str, str] = {'auto_vj_bpm': '0'}

    def test_progress_bar_is_full_width(self) -> None:
        """Progress bar rail_w must be >> old 33% width; rail_h is now 26px."""
        ov = _make_stub(self._FLAT)
        ov._render_hud()

        rects = _rect_calls(ov)
        # Rail rects: h=26, w >> 100.  Corner decorations are h=6 so excluded.
        bar_rects = [(x, y, w, h) for (x, y, w, h) in rects if abs(h - 26.0) < 0.1 and w > 100.0]
        assert bar_rects, 'No progress bar rect found (expected h≈26, w>100)'
        max_rail_w = max(w for (_, _, w, _) in bar_rects)

        # Old bar: band_w * 0.33 ≈ 341px.  New bar: band_w - 24 ≈ 1010px.
        assert max_rail_w > 600.0, (
            f'Progress bar width {max_rail_w:.1f}px looks like old narrow 33% bar'
        )

    def test_pct_zero_fills_nothing(self) -> None:
        """At 0% the fill rect should have near-zero width."""
        ov = _make_stub({**self._FLAT, 'spotify_progress': '00:00/05:00 0%'})
        ov._render_hud()

        rects = _rect_calls(ov)
        near_zero = [w for (_, _, w, _) in rects if w < 2.0]
        assert near_zero, (
            'Expected a zero-width fill rect at 0% but none found. '
            f'All widths: {[round(w, 1) for (_, _, w, _) in rects]}'
        )

    def test_pct_full_fills_rail(self) -> None:
        """At 100% the fill rect width should equal the rail background width."""
        ov = _make_stub({**self._FLAT, 'spotify_progress': '05:00/05:00 100%'})
        ov._render_hud()

        rects = _rect_calls(ov)
        bar_rects = [(x, y, w, h) for (x, y, w, h) in rects if abs(h - 26.0) < 0.1 and w > 100.0]
        assert len(bar_rects) == 2, (
            f'Expected exactly 2 bar rects (background + fill) at 100%, got: {bar_rects}'
        )
        widths = sorted(w for (_, _, w, _) in bar_rects)
        assert abs(widths[0] - widths[1]) < 2.0, (
            f'At 100%: fill width {widths[0]:.1f}px ≠ rail width {widths[1]:.1f}px'
        )


# ---------------------------------------------------------------------------
# Waveform mode tests (auto_vj_bpm > 0 + audio_beat present)
# ---------------------------------------------------------------------------

class TestSpotifyHudPaneWaveform:
    """Verify waveform mode draws live column bars instead of a flat fill rect."""

    _WF: dict[str, str] = {
        'auto_vj_bpm': '128',
        'audio_beat': '0.8',
        'audio_rms': '0.3',
        'spotify_progress': '02:30/05:00 50%',
    }

    @staticmethod
    def _stub_with_waveform(extra: dict[str, str] | None = None) -> 'Overlays':
        ov = _make_stub({**TestSpotifyHudPaneWaveform._WF, **(extra or {})})
        # Supply a real 512-sample sine waveform so waveform_mode activates.
        ov._live_waveform = np.sin(np.linspace(0, np.pi * 8, 512)).astype(np.float32)
        return ov

    def test_waveform_mode_draws_many_narrow_rects(self) -> None:
        """In waveform mode many narrow column bars should appear in the played region."""
        ov = self._stub_with_waveform()
        ov._render_hud()

        rects = _rect_calls(ov)
        # Column bars are narrow (<20px) and taller than 1px.
        col_bars = [(x, y, w, h) for (x, y, w, h) in rects if w < 20.0 and h > 1.5]
        assert len(col_bars) > 20, (
            f'Expected >20 column bars in waveform mode, got {len(col_bars)}'
        )

    def test_waveform_mode_no_single_mid_width_fill_rect(self) -> None:
        """In waveform mode a single ~50%-wide fill rect must not appear."""
        ov = self._stub_with_waveform()
        ov._render_hud()

        rects = _rect_calls(ov)
        # A flat fill at 50% would be ~505px wide with h≈26.
        suspicious = [
            (x, y, w, h) for (x, y, w, h) in rects
            if 400.0 < w < 700.0 and abs(h - 26.0) < 0.1
        ]
        assert not suspicious, (
            f'Found a wide single fill rect that looks like the old flat bar: {suspicious}'
        )

    def test_beat_decay_updates_on_render(self) -> None:
        """With a strong beat signal, _spotify_beat_decay should be > 0 after render."""
        ov = self._stub_with_waveform({'audio_beat': '1.0'})
        ov._spotify_beat_decay = 0.0
        ov._render_hud()
        assert ov._spotify_beat_decay > 0.0, (
            '_spotify_beat_decay should increase when audio_beat > 0'
        )


# ---------------------------------------------------------------------------
# Pane hidden
# ---------------------------------------------------------------------------

class TestSpotifyHudPaneHidden:
    """When spotify_visible is NO, no Spotify content should be drawn."""

    def test_no_spotify_draws_when_hidden(self) -> None:
        ov = _make_stub({'spotify_visible': 'NO'})
        ov._render_hud()

        texts = _text_calls(ov)
        spotify_texts = [t for t in texts if 'The Artist' in t or 'My Song' in t]
        assert not spotify_texts, (
            f'Spotify content drawn despite spotify_visible=NO: {spotify_texts}'
        )
