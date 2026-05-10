"""Compatibility shim for Unicorn Tears effect.

The canonical implementation lives in:
  drop-ins/unicorn-tears-01/unicorn_tears.py
"""
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_DROPIN_FILE = (
    Path(__file__).resolve().parents[2]
    / 'drop-ins'
    / 'unicorn-tears-01'
    / 'unicorn_tears.py'
)

if not _DROPIN_FILE.exists():
    raise ImportError(f'Unicorn Tears drop-in not found: {_DROPIN_FILE}')

_spec = spec_from_file_location('dropin_unicorn_tears', _DROPIN_FILE)
if _spec is None or _spec.loader is None:
    raise ImportError(f'Failed to load Unicorn Tears drop-in spec: {_DROPIN_FILE}')

_module = module_from_spec(_spec)
_spec.loader.exec_module(_module)

UnicornTears = _module.UnicornTears

__all__ = ['UnicornTears']
