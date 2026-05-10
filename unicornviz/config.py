"""
TOML configuration loader.

Reads ``config.toml`` from the working directory (the project root) and
deep-merges it with built-in defaults so every key always has a value.

Usage::

    cfg = Config()                    # loads config.toml
    cfg = Config("my_config.toml")    # explicit path

    width  = cfg.get("window", "width", default=1920)
    device = cfg.get("audio", "device", default="")

``get()`` accepts an arbitrary key path and never raises; it returns
*default* when any intermediate key is missing.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


_DEFAULTS: dict[str, Any] = {
    "window": {
        "width": 1920,
        "height": 1080,
        "fullscreen": False,
        "title": "Unicorn Viz",
    },
    "demo": {
        "mode": "sequential",
        "effect_duration": 20,
        "transition": "crossfade",
        "transition_duration": 1.0,
    },
    "audio": {
        "device": "",
        "fft_bands": 512,
        "buffer_seconds": 10.0,  # Large buffer for GPU rendering stalls and resolution flexibility
        "reactivity": 1.5,
        "latency": "high",
        "try_alsa_loopback": False,
    },
    "midi": {
        "device": "",
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
        "filename_prefix": "unicornviz",
        "show_indicator": True,
    },
    "logging": {
        "level": "INFO",
        "directory": "logs",
    },
    "overlays": {
        "flash_messages": True,
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
    def __init__(self, path: str | Path = "config.toml", overrides: dict[str, Any] | None = None) -> None:
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
