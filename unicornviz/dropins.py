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


def _normalise_help_entries(
    raw_entries: Any,
    default_section: str,
) -> list[tuple[str, str, str]]:
    """Convert mixed HELP_ENTRIES structures to (section, key, description)."""
    out: list[tuple[str, str, str]] = []
    if not isinstance(raw_entries, (list, tuple)):
        return out

    for item in raw_entries:
        if isinstance(item, dict):
            section = str(item.get('section', default_section)).strip()
            key = str(item.get('key', '')).strip()
            desc = str(
                item.get('description', item.get('desc', item.get('action', '')))
            ).strip()
            if section and key and desc:
                out.append((section, key, desc))
            continue

        if isinstance(item, (list, tuple)):
            if len(item) == 2:
                key = str(item[0]).strip()
                desc = str(item[1]).strip()
                if key and desc:
                    out.append((default_section, key, desc))
            elif len(item) >= 3:
                section = str(item[0]).strip() or default_section
                key = str(item[1]).strip()
                desc = str(item[2]).strip()
                if section and key and desc:
                    out.append((section, key, desc))
    return out


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


def discover_dropin_help_entries() -> list[tuple[str, str, str]]:
    """Discover HELP_ENTRIES from drop-in modules and classes.

    Supported formats:
    - module HELP_ENTRIES = [('Key', 'Description'), ...]
    - module HELP_ENTRIES = [('Section', 'Key', 'Description'), ...]
    - class  HELP_ENTRIES with same tuple/dict formats
    - dict items: {'section': str, 'key': str, 'description': str}
    """
    root = _dropins_root()
    if not root.exists():
        return []

    discovered: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for file_path in sorted(root.glob('*/*.py')):
        if file_path.name == '__init__.py' or '__pycache__' in file_path.parts:
            continue
        module_name = f'dropin_help_{file_path.stem}_{abs(hash(str(file_path)))}'
        try:
            module = _load_module_from_file(file_path, module_name)
        except Exception as exc:
            log.warning('Skipping drop-in help module %s: %s', file_path, exc)
            continue

        module_section = file_path.parent.name
        module_entries = _normalise_help_entries(
            getattr(module, 'HELP_ENTRIES', []),
            default_section=module_section,
        )
        for entry in module_entries:
            if entry not in seen:
                discovered.append(entry)
                seen.add(entry)

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if not hasattr(obj, 'HELP_ENTRIES'):
                continue
            default_section = str(getattr(obj, 'NAME', obj.__name__))
            cls_entries = _normalise_help_entries(
                getattr(obj, 'HELP_ENTRIES', []),
                default_section=default_section,
            )
            for entry in cls_entries:
                if entry not in seen:
                    discovered.append(entry)
                    seen.add(entry)

    return discovered
