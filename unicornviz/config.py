"""
TOML configuration loader.

Reads ``config.toml`` from the project root (resolved via
:mod:`unicornviz.paths`) and deep-merges it with built-in defaults so every
key always has a value.  The app works correctly when launched from any
working directory.

Usage::

    cfg = Config()                    # loads APP_ROOT/config.toml
    cfg = Config("my_config.toml")    # path relative to CWD, or absolute

    width  = cfg.get("window", "width", default=1920)
    device = cfg.get("audio", "device", default="")

``get()`` accepts an arbitrary key path and never raises; it returns
*default* when any intermediate key is missing.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from unicornviz.paths import APP_ROOT


_DEFAULTS: dict[str, Any] = {
    "window": {
        "width": 1920,
        "height": 1080,
        "fullscreen": False,
        "title": "Unicorn Viz",
        "display_index": 0,
        "display_mode": "single",
        "exclude_display_indices": [],
    },
    "demo": {
        "mode": "sequential",
        "effect_duration": 20,
        "transition": "crossfade",
        "transition_duration": 1.0,
        "auto_advance": True,
    },
    "audio": {
        "device": "",
        "fft_bands": 512,
        "buffer_seconds": 10.0,  # Large buffer for GPU rendering stalls and resolution flexibility
        "profile": "house",
        "reactivity": 1.0,
        "latency": "high",
        "prefer_default_input": True,
        "start_timeout_s": 4.0,
        "start_retries": 2,
        "start_retry_backoff_s": 0.5,
        # Deprecated: automatic source fallback is disabled; source changes are manual.
        "auto_fallback_enabled": False,
        "fallback_rms_threshold": 0.0015,
        "fallback_silence_seconds": 6.0,
        "fallback_cooldown_seconds": 8.0,
        "silence_rms_floor": 0.0060,
        "silence_rms_span": 0.045,
    },
    "midi": {
        "device": "",
        "preset": "",    # named preset: "akai_mpk_mini" | "novation_launchcontrol" | "generic" | ""
        "cc_map": {},    # per-CC overrides: {CC_number: param_name} — applied after preset
        "note_map": {},  # per-note overrides: {note_number: action_name} — applied after preset
    },
    "ansi": {
        "ansi_dir_auto": "assets/ansi",
        # Backward compatibility: legacy key kept as fallback.
        "ansi_dir": "assets/ansi",
        "ansi_own_dir": "assets/ansi",
        "ansi_acid_dir": "assets/ansi/acid",
    },
    "effects": {},
    "splash": {
        "image": "images/unicorn-viz-01.png",
        "duration_audio": 7.0,
        "duration_silent": 4.0,
    },
    "playlist": {
        "sequence": [],
        "start_effect": "Audio Spectrum",
    },
    "render": {
        "internal_scale": 1.0,
    },
    "recording": {
        "enabled": True,
        "auto_record": False,
        "directory": "recordings",
        "ffmpeg_path": "ffmpeg",
        "container": "mp4",
        "fps": 60,
        "codec": "libx264",
        "preset": "veryfast",
        "crf": 18,
        "pixel_format": "yuv420p",
        "capture_audio": False,
        "audio_input_format": "pulse",
        "audio_input_device": "",
        "audio_codec": "aac",
        "audio_bitrate": "192k",
        "filename_prefix": "unicornviz",
        "show_indicator": True,
    },
    "logging": {
        "level": "INFO",
        "directory": "logs",
    },
    "overlays": {
        "flash_messages": True,
        "hud_auto_hide": True,
        "hud_timeout_s": 60.0,
    },
    "control_room": {
        "enabled": False,
        "display_index": 1,
        "width": 1440,
        "height": 900,
        "show_preview": True,
        "preview_scale": 0.52,
        "theme": "dark",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class Config:
    def __init__(self, path: str | Path = APP_ROOT / 'config.toml', overrides: dict[str, Any] | None = None) -> None:
        self._data = dict(_DEFAULTS)
        p = Path(path)
        if p.exists():
            with p.open("rb") as f:
                user = tomllib.load(f)
            self._data = _deep_merge(self._data, user)
        if overrides:
            self._data = _deep_merge(self._data, overrides)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, *keys: str, default: Any = None) -> Any:
        node = self._data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node
