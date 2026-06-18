from __future__ import annotations

from unicornviz.overlays import Overlays


def _make_num_reader(state: dict[str, str]):
    def _reader(key: str, default: float) -> float:
        try:
            return float(state.get(key, default))
        except Exception:
            return float(default)

    return _reader


def test_system_monitor_tweakables_falls_back_to_hud_zoom_key() -> None:
    overlays = Overlays.__new__(Overlays)
    overlays._system_monitor_tweakables_provider = None

    state = {
        'reactivity': '1.25',
        'speed': '1.50',
        'zoom': '1.75',
        'render_scale': '0.50',
    }

    react, speed, zoom = overlays._system_monitor_tweakables(_make_num_reader(state))

    assert react == 1.25
    assert speed == 1.5
    assert zoom == 1.75


def test_system_monitor_tweakables_prefers_runtime_provider_values() -> None:
    overlays = Overlays.__new__(Overlays)
    overlays._system_monitor_tweakables_provider = lambda: {
        'reactivity': 2.0,
        'speed': 2.5,
        'zoom': 0.8,
    }

    state = {
        'reactivity': '1.10',
        'speed': '1.20',
        'zoom': '1.30',
    }

    react, speed, zoom = overlays._system_monitor_tweakables(_make_num_reader(state))

    assert react == 2.0
    assert speed == 2.5
    assert zoom == 0.8


def test_system_monitor_tweakables_handles_partial_provider_payload() -> None:
    overlays = Overlays.__new__(Overlays)
    overlays._system_monitor_tweakables_provider = lambda: {
        'reactivity': 1.9,
        'speed': None,
    }

    state = {
        'reactivity': '1.00',
        'speed': '1.40',
        'zoom': '1.60',
    }

    react, speed, zoom = overlays._system_monitor_tweakables(_make_num_reader(state))

    assert react == 1.9
    assert speed == 1.4
    assert zoom == 1.6


def test_system_monitor_audio_metrics_prefers_runtime_provider_values() -> None:
    overlays = Overlays.__new__(Overlays)
    overlays._system_monitor_audio_provider = lambda: {
        'fps': 59.5,
        'frame_ms': 16.8,
        'bass': 0.11,
        'mid': 0.22,
        'treble': 0.33,
        'bass_n': 0.44,
        'mid_n': 0.55,
        'treble_n': 0.66,
    }

    state = {
        'fps': '120.0',
        'frame_ms': '8.0',
        'bass': '1.0',
        'mid': '1.0',
        'treble': '1.0',
        'bass_n': '1.0',
        'mid_n': '1.0',
        'treble_n': '1.0',
    }

    values = overlays._system_monitor_audio_metrics(_make_num_reader(state))

    assert values == (59.5, 16.8, 0.11, 0.22, 0.33, 0.44, 0.55, 0.66)


def test_system_monitor_audio_metrics_fallback_to_hud_when_provider_missing() -> None:
    overlays = Overlays.__new__(Overlays)
    overlays._system_monitor_audio_provider = None

    state = {
        'fps': '60.0',
        'frame_ms': '16.67',
        'bass': '0.10',
        'mid': '0.20',
        'treble': '0.30',
        'bass_n': '0.40',
        'mid_n': '0.50',
        'treble_n': '0.60',
    }

    values = overlays._system_monitor_audio_metrics(_make_num_reader(state))

    assert values == (60.0, 16.67, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60)


def test_system_monitor_runtime_provider_smoke_overrides_hud() -> None:
    overlays = Overlays.__new__(Overlays)
    overlays._system_monitor_audio_provider = lambda: {
        'fps': 58.0,
        'frame_ms': 17.2,
        'bass': 0.12,
        'mid': 0.24,
        'treble': 0.36,
        'bass_n': 0.48,
        'mid_n': 0.60,
        'treble_n': 0.72,
    }
    overlays._system_monitor_tweakables_provider = lambda: {
        'reactivity': 1.7,
        'speed': 2.1,
        'zoom': 0.95,
    }

    # Deliberately conflicting HUD values to prove monitor runtime providers win.
    state = {
        'fps': '120.0',
        'frame_ms': '8.0',
        'bass': '0.99',
        'mid': '0.99',
        'treble': '0.99',
        'bass_n': '0.99',
        'mid_n': '0.99',
        'treble_n': '0.99',
        'reactivity': '0.1',
        'speed': '0.1',
        'zoom': '0.1',
    }
    reader = _make_num_reader(state)

    audio_values = overlays._system_monitor_audio_metrics(reader)
    tweak_values = overlays._system_monitor_tweakables(reader)

    assert audio_values == (58.0, 17.2, 0.12, 0.24, 0.36, 0.48, 0.60, 0.72)
    assert tweak_values == (1.7, 2.1, 0.95)
