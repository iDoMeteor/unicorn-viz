from __future__ import annotations

from pathlib import Path

from unicornviz.config import Config


def test_audio_startup_defaults_are_stable() -> None:
    cfg = Config(Path('tests') / '_missing_config_for_tests.toml')

    assert float(cfg.get('audio', 'start_timeout_s')) == 4.0
    assert int(cfg.get('audio', 'start_retries')) == 2
    assert float(cfg.get('audio', 'start_retry_backoff_s')) == 0.5


def test_audio_fallback_defaults_are_stable() -> None:
    cfg = Config(Path('tests') / '_missing_config_for_tests.toml')

    assert bool(cfg.get('audio', 'auto_fallback_enabled')) is False
    assert float(cfg.get('audio', 'fallback_rms_threshold')) == 0.0015
    assert float(cfg.get('audio', 'fallback_silence_seconds')) == 6.0
    assert float(cfg.get('audio', 'fallback_cooldown_seconds')) == 8.0
