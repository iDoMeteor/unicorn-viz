"""Drop-in loading utilities.

This module provides first-class loading for code that lives under `drop-ins/`
submodules, including direct symbol loading and effect-class discovery.
"""
from __future__ import annotations

import inspect
import logging
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any, Type


log = logging.getLogger(__name__)


def _dropins_root() -> Path:
    return Path(__file__).resolve().parents[1] / 'drop-ins'


def _load_module_from_file(file_path: Path, module_name: str):
    spec = spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Failed to load module spec from {file_path}')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_dropin_symbol(relative_file: str, symbol_name: str) -> Any:
    """Load a symbol from a drop-in Python file path relative to `drop-ins/`."""
    file_path = _dropins_root() / relative_file
    if not file_path.exists():
        raise ImportError(f'Drop-in file not found: {file_path}')
    module_name = f'dropin_symbol_{file_path.stem}_{abs(hash(str(file_path)))}'
    module = _load_module_from_file(file_path, module_name)
    if not hasattr(module, symbol_name):
        raise ImportError(f'Symbol {symbol_name!r} not found in drop-in: {file_path}')
    return getattr(module, symbol_name)


def discover_dropin_effect_classes(base_cls: Type) -> list[Type]:
    """Discover concrete effect classes from all drop-in python modules."""
    root = _dropins_root()
    if not root.exists():
        return []

    discovered: list[Type] = []
    for file_path in sorted(root.glob('*/*.py')):
        if file_path.name == '__init__.py' or '__pycache__' in file_path.parts:
            continue
        module_name = f'dropin_effect_{file_path.stem}_{abs(hash(str(file_path)))}'
        try:
            module = _load_module_from_file(file_path, module_name)
        except Exception as exc:
            log.warning('Skipping drop-in module %s: %s', file_path, exc)
            continue

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, base_cls) and obj is not base_cls:
                discovered.append(obj)
    return discovered
