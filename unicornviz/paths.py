"""
App-root path resolution for Unicorn Viz.

Provides ``APP_ROOT`` (the project root directory) and ``resolve_path()``, a
helper that resolves relative path strings/objects against APP_ROOT instead of
the process working directory.

This module is intentionally dependency-free (no unicornviz imports) so it can
be imported early in startup without triggering circular imports.

Usage::

    from unicornviz.paths import APP_ROOT, resolve_path

    font = resolve_path("assets/fonts/font8x16.bin")   # → APP_ROOT/assets/…
    cfg  = resolve_path("/etc/my-config.toml")         # → absolute, unchanged
"""
from __future__ import annotations

from pathlib import Path

# Two levels up from this file: unicornviz/paths.py → unicornviz/ → project root
APP_ROOT: Path = Path(__file__).resolve().parents[1]


def resolve_path(rel_path: str | Path) -> Path:
    """Resolve *rel_path* against :data:`APP_ROOT`.

    Absolute paths are returned unchanged.  Relative paths are resolved
    relative to the project root regardless of the process working directory,
    so the app works correctly when launched from any directory (menu
    shortcuts, systemd units, packaged installs, etc.).
    """
    p = Path(rel_path)
    return p if p.is_absolute() else APP_ROOT / p
