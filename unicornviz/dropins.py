"""Drop-in loading utilities.

This module provides first-class loading for code that lives under `drop-ins/`
submodules, including direct symbol loading and effect-class discovery.
"""
from __future__ import annotations

import inspect
import logging
import re
import sys
import tomllib
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Type

from unicornviz.config import register_config_validator
from unicornviz.paths import APP_ROOT


log = logging.getLogger(__name__)

_EXCLUDE_CACHE_SIG: tuple[float, int] | None = None
_EXCLUDE_CACHE: tuple[bool, set[str]] = (False, set())
_REGISTERED_VALIDATOR_FILES: set[str] = set()
_MODULE_CACHE: dict[Path, ModuleType] = {}


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
    return APP_ROOT / 'drop-ins'


def _project_config_path() -> Path:
    return APP_ROOT / 'config.toml'


def _dropin_aliases(name: str) -> set[str]:
    """Return normalized aliases for a drop-in folder name.

    Examples:
    - 'unicorn-tears-01' -> {'unicorn-tears-01', 'unicorn-tears'}
    - 'postfx-01'        -> {'postfx-01', 'postfx'}
    """
    n = name.strip().lower()
    if not n:
        return set()
    aliases = {n}
    aliases.add(re.sub(r'-\d+$', '', n))
    return aliases


def _parse_dropin_exclude_setting(raw: Any) -> tuple[bool, set[str]]:
    """Parse drop-in exclusion setting.

    Returns:
    - (True, set()) when value is 'all'
    - (False, set()) when value is 'none' or empty
    - (False, {'a', 'b'}) for explicit list/CSV names
    """
    if raw is None:
        return False, set()

    parts: list[str] = []
    if isinstance(raw, str):
        parts = [p.strip().lower() for p in raw.split(',') if p.strip()]
    elif isinstance(raw, (list, tuple)):
        parts = [str(p).strip().lower() for p in raw if str(p).strip()]
    else:
        parts = [str(raw).strip().lower()]

    if not parts:
        return False, set()
    if any(p == 'all' for p in parts):
        return True, set()
    if any(p == 'none' for p in parts):
        return False, set()

    excludes: set[str] = set()
    for p in parts:
        excludes.update(_dropin_aliases(p))
    return False, excludes


def _get_dropin_excludes() -> tuple[bool, set[str]]:
    """Read and cache drop-in exclusion config from config.toml.

    Supported config keys:
    - [dropins] exclude = 'none' | 'all' | 'name-a,name-b'
    - top-level `exclude_dropins` with same format (fallback)
    """
    global _EXCLUDE_CACHE_SIG, _EXCLUDE_CACHE

    cfg_path = _project_config_path()
    if not cfg_path.exists():
        return False, set()

    st = cfg_path.stat()
    sig = (st.st_mtime, st.st_size)
    if _EXCLUDE_CACHE_SIG == sig:
        return _EXCLUDE_CACHE

    try:
        with cfg_path.open('rb') as f:
            data = tomllib.load(f)
    except Exception as exc:
        log.warning('Failed reading config.toml for drop-in excludes: %s', exc)
        _EXCLUDE_CACHE_SIG = sig
        _EXCLUDE_CACHE = (False, set())
        return _EXCLUDE_CACHE

    raw = None
    if isinstance(data.get('dropins'), dict):
        raw = data['dropins'].get('exclude')
    if raw is None:
        raw = data.get('exclude_dropins')

    _EXCLUDE_CACHE_SIG = sig
    _EXCLUDE_CACHE = _parse_dropin_exclude_setting(raw)
    return _EXCLUDE_CACHE


def _is_dropin_excluded(name: str) -> bool:
    all_excluded, excludes = _get_dropin_excludes()
    if all_excluded:
        return True
    aliases = _dropin_aliases(name)
    return any(a in excludes for a in aliases)


def _stable_dropin_module_name(file_path: Path) -> str:
    """Return a deterministic module name for a drop-in file path."""
    try:
        rel = file_path.resolve().relative_to(_dropins_root().resolve())
    except Exception:
        rel = file_path.resolve()
    stem = rel.with_suffix('')
    parts = [re.sub(r'[^0-9a-zA-Z_]', '_', p) for p in stem.parts]
    return f"unicornviz_dropins_{'_'.join(parts)}"


def _load_module_from_file(file_path: Path, module_name: str | None = None) -> ModuleType:
    resolved = file_path.resolve()
    cached = _MODULE_CACHE.get(resolved)
    if cached is not None:
        return cached

    name = module_name or _stable_dropin_module_name(resolved)
    existing = sys.modules.get(name)
    if isinstance(existing, ModuleType):
        _MODULE_CACHE[resolved] = existing
        return existing

    spec = spec_from_file_location(name, resolved)
    if spec is None or spec.loader is None:
        raise ImportError(f'Failed to load module spec from {file_path}')
    module = module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    _MODULE_CACHE[resolved] = module
    return module


def load_dropin_symbol(relative_file: str, symbol_name: str) -> Any:
    """Load a symbol from a drop-in Python file path relative to `drop-ins/`."""
    dropin_name = Path(relative_file).parts[0] if Path(relative_file).parts else ''
    if dropin_name and _is_dropin_excluded(dropin_name):
        raise ImportError(f'Drop-in excluded by config: {dropin_name}')

    file_path = _dropins_root() / relative_file
    if not file_path.exists():
        raise ImportError(f'Drop-in file not found: {file_path}')
    module = _load_module_from_file(file_path)
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
        if _is_dropin_excluded(file_path.parent.name):
            continue
        try:
            module = _load_module_from_file(file_path)
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
        if _is_dropin_excluded(file_path.parent.name):
            continue
        try:
            module = _load_module_from_file(file_path)
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


def register_dropin_config_validators() -> list[str]:
    """Register per-drop-in config validators from `config_validator.py` files.

    Each drop-in may optionally provide:

    - `drop-ins/<name>/config_validator.py`
    - callable `validate_config(config_data: dict) -> list[str] | None`

    Returned error strings are namespaced by drop-in and merged into the core
    config validation output.
    """
    root = _dropins_root()
    if not root.exists():
        return []

    registered: list[str] = []
    for file_path in sorted(root.glob('*/config_validator.py')):
        dropin_name = file_path.parent.name
        if _is_dropin_excluded(dropin_name):
            continue

        key = str(file_path.resolve())
        if key in _REGISTERED_VALIDATOR_FILES:
            continue

        try:
            module = _load_module_from_file(file_path)
        except Exception as exc:
            log.warning('Skipping drop-in config validator %s: %s', file_path, exc)
            continue

        validator = getattr(module, 'validate_config', None)
        if not callable(validator):
            log.warning(
                'Drop-in config validator module %s has no callable validate_config()',
                file_path,
            )
            continue

        register_config_validator(f'dropin:{dropin_name}', validator)
        _REGISTERED_VALIDATOR_FILES.add(key)
        registered.append(dropin_name)

    return registered
