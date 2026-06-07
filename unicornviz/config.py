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
from typing import Any, Callable

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
        # Automatic source switch is limited to operator-tagged viable sources.
        "auto_fallback_enabled": True,
        "fallback_rms_threshold": 0.0015,
        "fallback_silence_seconds": 6.0,
        "fallback_cooldown_seconds": 8.0,
        "silence_rms_floor": 0.0060,
        "silence_rms_span": 0.045,
    },
    "midi": {
        "device": "",
        "preset": "",    # named preset: "akai_apc_mini_mk2" | "akai_mpk_mini" | "novation_launchcontrol" | "generic" | ""
        "cc_map": {},    # per-CC overrides: {CC_number: param_name} — applied after preset
        "note_map": {},  # per-note overrides: {note_number: action_name} — applied after preset
    },
    "ansi": {
        "ansi_dir_auto": "assets/ansi",
        # Backward compatibility: legacy key kept as fallback.
        "ansi_dir": "assets/ansi",
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


class ConfigValidationError(ValueError):
    """Raised when config values fail validation."""


_DISPLAY_MODES = {'single', 'span_included', 'span_all', 'mirror_included', 'mirror_all'}
_DISPLAY_MODE_ALIASES = {
    'span': 'span_included',
    'mirror': 'mirror_included',
}
_DEMO_MODES = {'sequential', 'random'}
_TRANSITIONS = {
    'crossfade',
    'smoothfade',
    'scanwipe',
    'scanwipe_x',
    'scanwipe_y',
    'dissolve',
    'zoomblend',
    'shuffle',
    'random',
}
_AUDIO_LATENCY_LABELS = {'low', 'medium', 'high'}
_LOG_LEVELS = {'DEBUG', 'INFO', 'WARN', 'WARNING', 'ERROR', 'CRITICAL', 'NONE'}
_EXTERNAL_VALIDATORS: dict[
    str,
    Callable[[dict[str, Any]], list[str] | None],
] = {}


def _path_str(path: tuple[str, ...]) -> str:
    return '.'.join(path)


def _is_bool(value: Any) -> bool:
    return type(value) is bool


def _is_int(value: Any) -> bool:
    return type(value) is int


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_type_compatible(value: Any, default: Any) -> bool:
    if isinstance(default, bool):
        return _is_bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        return _is_int(value)
    if isinstance(default, float):
        return _is_number(value)
    if isinstance(default, str):
        return isinstance(value, str)
    if isinstance(default, list):
        return isinstance(value, list)
    if isinstance(default, dict):
        return isinstance(value, dict)
    return True


def _extra_constraints(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    window = data.get('window', {})
    demo = data.get('demo', {})
    audio = data.get('audio', {})
    playlist = data.get('playlist', {})
    logging_cfg = data.get('logging', {})
    overlays = data.get('overlays', {})
    recording = data.get('recording', {})
    midi = data.get('midi', {})

    display_mode = str(window.get('display_mode', '')).lower()
    display_mode = _DISPLAY_MODE_ALIASES.get(display_mode, display_mode)
    if display_mode not in _DISPLAY_MODES:
        errors.append(
            "window.display_mode must be one of "
            "'single', 'span_included', 'span_all', 'mirror_included', 'mirror_all' "
            "(legacy aliases span/mirror are also accepted)"
        )

    demo_mode = str(demo.get('mode', '')).lower()
    if demo_mode not in _DEMO_MODES:
        errors.append("demo.mode must be 'sequential' or 'random'")

    transition = str(demo.get('transition', '')).lower()
    if transition not in _TRANSITIONS:
        errors.append(
            'demo.transition has unsupported value '
            f"{transition!r}; see docs/configuration.md for allowed values"
        )

    latency = audio.get('latency', 'high')
    if isinstance(latency, str):
        if latency.strip().lower() not in _AUDIO_LATENCY_LABELS:
            errors.append(
                "audio.latency must be 'low', 'medium', 'high', "
                'or a positive number of seconds'
            )
    elif not _is_number(latency):
        errors.append(
            "audio.latency must be 'low', 'medium', 'high', "
            'or a positive number of seconds'
        )

    for key in (
        'reactivity',
        'buffer_seconds',
        'start_timeout_s',
        'start_retry_backoff_s',
        'fallback_rms_threshold',
        'fallback_silence_seconds',
        'fallback_cooldown_seconds',
        'silence_rms_floor',
        'silence_rms_span',
    ):
        value = audio.get(key)
        if value is not None and _is_number(value) and float(value) < 0.0:
            errors.append(f'audio.{key} must be >= 0')

    start_retries = audio.get('start_retries')
    if start_retries is not None and (_is_int(start_retries) and start_retries < 0):
        errors.append('audio.start_retries must be >= 0')

    sequence = playlist.get('sequence', [])
    if isinstance(sequence, list) and any(not isinstance(item, str) for item in sequence):
        errors.append('playlist.sequence must contain only strings')

    excludes = window.get('exclude_display_indices', [])
    if isinstance(excludes, list) and any(not _is_int(item) for item in excludes):
        errors.append('window.exclude_display_indices must contain only integers')

    level = str(logging_cfg.get('level', '')).upper()
    if level not in _LOG_LEVELS:
        errors.append(
            'logging.level must be one of '
            "'DEBUG', 'INFO', 'WARN', 'WARNING', 'ERROR', 'CRITICAL', 'NONE'"
        )

    hud_timeout = overlays.get('hud_timeout_s')
    if _is_number(hud_timeout) and float(hud_timeout) < 0.0:
        errors.append('overlays.hud_timeout_s must be >= 0')

    fps = recording.get('fps')
    if _is_int(fps) and fps <= 0:
        errors.append('recording.fps must be > 0')

    crf = recording.get('crf')
    if _is_int(crf) and not (0 <= crf <= 51):
        errors.append('recording.crf must be between 0 and 51')

    for map_key in ('cc_map', 'note_map'):
        mapping = midi.get(map_key, {})
        if isinstance(mapping, dict):
            for key, value in mapping.items():
                try:
                    int(key)
                except Exception:
                    errors.append(f'midi.{map_key} keys must be integer-like')
                    break
                if not isinstance(value, str):
                    errors.append(f'midi.{map_key} values must be strings')
                    break

    return errors


def _collect_type_errors(
    data_node: Any,
    defaults_node: Any,
    path: tuple[str, ...] = (),
) -> list[str]:
    errors: list[str] = []
    if isinstance(defaults_node, dict):
        if not isinstance(data_node, dict):
            errors.append(
                f"{_path_str(path) or '<root>'} must be a table/object"
            )
            return errors
        for key, default_value in defaults_node.items():
            if key not in data_node:
                # Defaults guarantee this in normal flow, but keep guard anyway.
                continue
            value = data_node[key]
            key_path = (*path, key)
            if isinstance(default_value, dict):
                errors.extend(_collect_type_errors(value, default_value, key_path))
                continue
            if not _is_type_compatible(value, default_value):
                expected = type(default_value).__name__
                actual = type(value).__name__
                errors.append(
                    f'{_path_str(key_path)} must be {expected}, got {actual}'
                )
    return errors


def register_config_validator(
    name: str,
    validator: Callable[[dict[str, Any]], list[str] | None],
) -> None:
    """Register an external config validator.

    External validators are intended for optional drop-ins. They receive the
    merged config dict and should return a list of human-readable errors.
    """
    key = str(name).strip()
    if not key:
        raise ValueError('validator name must be non-empty')
    _EXTERNAL_VALIDATORS[key] = validator


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

    def validate(self) -> None:
        """Validate merged config and raise on invalid values.

        Validation focuses on built-in sections under `_DEFAULTS`.
        Unknown drop-in sections remain allowed and are not rejected.
        """
        errors: list[str] = []
        errors.extend(_collect_type_errors(self._data, _DEFAULTS))
        errors.extend(_extra_constraints(self._data))
        for name, validator in sorted(_EXTERNAL_VALIDATORS.items()):
            try:
                result = validator(self._data)
            except Exception as exc:
                errors.append(f'external validator {name!r} failed: {exc}')
                continue
            if result is None:
                continue
            if isinstance(result, str):
                errors.append(f'{name}: {result}')
                continue
            if isinstance(result, (list, tuple)):
                errors.extend(f'{name}: {str(msg)}' for msg in result)
                continue
            errors.append(
                f'external validator {name!r} returned unsupported type '
                f'{type(result).__name__}'
            )
        if errors:
            lines = ['Configuration validation failed:']
            lines.extend(f'  - {err}' for err in errors)
            raise ConfigValidationError('\n'.join(lines))

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, *keys: str, default: Any = None) -> Any:
        node = self._data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node
