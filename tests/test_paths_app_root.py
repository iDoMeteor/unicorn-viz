"""Regression tests for ``unicornviz.paths`` app-root resolution.

These pin the contract that packaged installs rely on: ``UNICORNVIZ_APP_ROOT``
overrides the default "two levels up from this file" so assets resolve to the
install prefix even when the package lives in a bundled runtime's site-packages.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from unicornviz import paths


def test_app_root_defaults_to_package_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('UNICORNVIZ_APP_ROOT', raising=False)
    root = paths._resolve_app_root()
    assert root == Path(paths.__file__).resolve().parents[1]
    assert (root / 'unicornviz').is_dir()


def test_app_root_honors_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv('UNICORNVIZ_APP_ROOT', str(tmp_path))
    assert paths._resolve_app_root() == tmp_path.resolve()


def test_module_app_root_reflects_env_on_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv('UNICORNVIZ_APP_ROOT', str(tmp_path))
    try:
        reloaded = importlib.reload(paths)
        assert reloaded.APP_ROOT == tmp_path.resolve()
        # Relative asset paths now resolve under the overridden root.
        assert reloaded.resolve_path('assets/fonts') == tmp_path.resolve() / 'assets' / 'fonts'
    finally:
        monkeypatch.delenv('UNICORNVIZ_APP_ROOT', raising=False)
        importlib.reload(paths)


def test_resolve_path_passes_absolute_through() -> None:
    absolute = Path('/etc/unicorn-viz/config.toml')
    assert paths.resolve_path(absolute) == absolute
