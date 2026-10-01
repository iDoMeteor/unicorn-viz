"""G1 (2026-09-30 hardware/GPU-run audit): ``--effect-duration`` always
failed config validation.

``__main__`` declares the flag ``type=float`` while the built-in default
was the int ``60``, and the validator rejects a float where the default is
an int.  So every README / user-guide launch example with the flag exited
at startup.  The default is now ``60.0``; a float default accepts ints too,
so an owner's ``effect_duration = 60`` in config.toml stays valid.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from unicornviz.__main__ import _build_overrides, _build_parser
from unicornviz.config import Config, ConfigValidationError

_NO_FILE = Path('tests') / '_missing_config_for_tests.toml'


def _config_for(argv: list[str]) -> Config:
    args = _build_parser().parse_args(argv)
    return Config(_NO_FILE, overrides=_build_overrides(args))


def test_effect_duration_flag_passes_validation() -> None:
    cfg = _config_for(['--effect-duration', '7'])
    cfg.validate()
    assert cfg.get('demo', 'effect_duration') == 7.0


def test_integer_effect_duration_from_a_config_file_is_still_accepted() -> None:
    cfg = Config(_NO_FILE, overrides={'demo': {'effect_duration': 45}})
    cfg.validate()
    assert float(cfg.get('demo', 'effect_duration')) == 45.0


def test_non_numeric_effect_duration_is_still_rejected() -> None:
    cfg = Config(_NO_FILE, overrides={'demo': {'effect_duration': 'long'}})
    with pytest.raises(ConfigValidationError):
        cfg.validate()
