"""Compatibility shim for multi-head controller.

The canonical implementation lives in:
  drop-ins/multi-head-01/multihead.py
"""
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_DROPIN_FILE = (
    Path(__file__).resolve().parents[2]
    / 'drop-ins'
    / 'multi-head-01'
    / 'multihead.py'
)

if not _DROPIN_FILE.exists():
    raise ImportError(f'Multi-head drop-in not found: {_DROPIN_FILE}')

_spec = spec_from_file_location('dropin_multihead', _DROPIN_FILE)
if _spec is None or _spec.loader is None:
    raise ImportError(f'Failed to load multi-head drop-in spec: {_DROPIN_FILE}')

_module = module_from_spec(_spec)
_spec.loader.exec_module(_module)

MultiHeadController = _module.MultiHeadController

__all__ = ['MultiHeadController']
