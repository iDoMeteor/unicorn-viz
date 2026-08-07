"""Regression tests for VjApi.grand_finale_active (2026-08-07).

Lets a consumer (auto-vj-01's unattended-run auto-exit,
docs/planning/headless-auto-exit-plan-2026-08-07.md) watch the grand-finale
sequence's active/idle state without reaching into app._grand_finale.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from unicornviz.app import App
from unicornviz.config import Config


def _default_cfg() -> Config:
    return Config(Path('tests') / '_missing_config_for_tests.toml')


def test_grand_finale_active_false_when_drop_in_not_loaded() -> None:
    app = App(_default_cfg())
    app._grand_finale = None

    assert app.vj_api.grand_finale_active is False


def test_grand_finale_active_reflects_is_active_true() -> None:
    app = App(_default_cfg())
    app._grand_finale = SimpleNamespace(is_active=True)

    assert app.vj_api.grand_finale_active is True


def test_grand_finale_active_reflects_is_active_false() -> None:
    app = App(_default_cfg())
    app._grand_finale = SimpleNamespace(is_active=False)

    assert app.vj_api.grand_finale_active is False


def test_grand_finale_active_defaults_false_without_the_attribute() -> None:
    """A stub/older grand-finale instance with no is_active must degrade
    to False rather than raising."""
    app = App(_default_cfg())
    app._grand_finale = SimpleNamespace()

    assert app.vj_api.grand_finale_active is False
