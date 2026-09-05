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
from dataclasses import dataclass
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
_PKG_CACHE: dict[str, ModuleType] = {}


@dataclass(frozen=True, slots=True)
class DropinRuntimeCapability:
    """Declarative runtime registration metadata for a drop-in component."""

    name: str
    relative_file: str
    class_symbol: str
    subsystem_name: str | None = None
    key_handler_attr: str | None = None


@dataclass(slots=True)
class DropinBindingState:
    """Track what runtime bindings were successfully registered."""

    subsystem_registered: bool = False
    key_handler_registered: bool = False


CONTROL_ROOM_RUNTIME_CAPABILITY = DropinRuntimeCapability(
    name='control_room',
    relative_file='control-room-01/control_room.py',
    class_symbol='ControlRoomController',
    subsystem_name='control_room',
    key_handler_attr='handle_key',
)

MULTIHEAD_RUNTIME_CAPABILITY = DropinRuntimeCapability(
    name='multihead',
    relative_file='multi-head-01/multihead.py',
    class_symbol='MultiHeadController',
    subsystem_name='multihead',
)

POSTFX_RUNTIME_CAPABILITY = DropinRuntimeCapability(
    name='postfx',
    relative_file='postfx-01/postfx_controller.py',
    class_symbol='PostFxController',
    key_handler_attr='handle_key',
)

BANNER_RUNTIME_CAPABILITY = DropinRuntimeCapability(
    name='banner',
    relative_file='banner-01/banner_controller.py',
    class_symbol='BannerController',
    subsystem_name='banner',
    key_handler_attr='handle_key',
)


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


def _dropin_package_for(file_path: Path) -> str | None:
    """Register (once) a synthetic parent package for file_path's drop-in
    directory, with ``__path__`` pointing at that directory, and return its
    dotted name.

    Drop-in files are executed via ``spec_from_file_location`` rather than a
    real package import, so without this a module-level or lazy relative
    import between sibling files in the same drop-in (``from .foo import
    Bar``) always raises "attempted relative import with no known parent
    package" -- the module has no resolvable parent. Giving each drop-in
    directory a real (if empty) package entry in ``sys.modules`` with a
    correct ``__path__`` lets the standard import machinery resolve those
    siblings normally. Returns None for files not exactly one level under
    ``drop-ins/`` (deeper nesting isn't used by any current drop-in).
    """
    try:
        rel = file_path.resolve().relative_to(_dropins_root().resolve())
    except Exception:
        return None
    if len(rel.parts) != 2:
        return None
    dropin_dir = rel.parts[0]
    pkg_name = f"unicornviz_dropins_{re.sub(r'[^0-9a-zA-Z_]', '_', dropin_dir)}"
    existing = sys.modules.get(pkg_name)
    if isinstance(existing, ModuleType) and hasattr(existing, '__path__'):
        return pkg_name
    pkg = ModuleType(pkg_name)
    pkg.__path__ = [str((_dropins_root() / dropin_dir).resolve())]
    pkg.__package__ = pkg_name
    sys.modules[pkg_name] = pkg
    _PKG_CACHE[pkg_name] = pkg
    return pkg_name


def _load_module_from_file(file_path: Path, module_name: str | None = None) -> ModuleType:
    resolved = file_path.resolve()
    cached = _MODULE_CACHE.get(resolved)
    if cached is not None:
        return cached

    name = module_name
    if name is None:
        pkg_name = _dropin_package_for(resolved)
        if pkg_name:
            stem = re.sub(r'[^0-9a-zA-Z_]', '_', resolved.stem)
            name = f'{pkg_name}.{stem}'
        else:
            name = _stable_dropin_module_name(resolved)
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


def discover_dropin_help_entries(
    dir_filter: Callable[[str], bool] | None = None,
) -> list[tuple[str, str, str]]:
    """Discover HELP_ENTRIES from drop-in modules and classes.

    Supported formats:
    - module HELP_ENTRIES = [('Key', 'Description'), ...]
    - module HELP_ENTRIES = [('Section', 'Key', 'Description'), ...]
    - class  HELP_ENTRIES with same tuple/dict formats
    - dict items: {'section': str, 'key': str, 'description': str}

    ``dir_filter`` (drop-in directory name -> bool) scopes the scan: the scan
    **imports every module it visits** (~1.5s cold across all drop-ins), so
    restricted boot profiles pass a filter covering only the drop-ins they
    can actually load. ``None`` scans everything (normal boot).
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
        if dir_filter is not None and not dir_filter(file_path.parent.name):
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


def discover_dropin_tour_slides(
    dir_filter: Callable[[str], bool] | None = None,
) -> list[tuple[str, str, str]]:
    """Discover TOUR_SLIDES from drop-in modules for the first-run tour.

    Supported formats (module level only):
    - TOUR_SLIDES = [('Section', 'Title', 'Body'), ...]
    - TOUR_SLIDES = [{'section': ..., 'title': ..., 'body': ...}, ...]

    Bodies may use the same ``{key:<help description>}`` tokens as the core
    deck (resolved against the help registry at display time). Returns plain
    tuples so this module stays decoupled from ``unicornviz.tour``; malformed
    entries are skipped with a warning, and drop-ins are scanned in sorted
    directory order so the deck is stable across runs. ``dir_filter`` scopes
    the scan exactly like ``discover_dropin_help_entries`` — without it, a
    restricted boot profile would pay the full import wall on first F1.
    """
    root = _dropins_root()
    if not root.exists():
        return []

    discovered: list[tuple[str, str, str]] = []
    for file_path in sorted(root.glob('*/*.py')):
        if file_path.name == '__init__.py' or '__pycache__' in file_path.parts:
            continue
        if _is_dropin_excluded(file_path.parent.name):
            continue
        if dir_filter is not None and not dir_filter(file_path.parent.name):
            continue
        try:
            module = _load_module_from_file(file_path)
        except Exception as exc:
            log.warning('Skipping drop-in tour module %s: %s', file_path, exc)
            continue

        for raw in getattr(module, 'TOUR_SLIDES', []) or []:
            if isinstance(raw, dict):
                parts = (raw.get('section'), raw.get('title'), raw.get('body'))
            elif isinstance(raw, (tuple, list)) and len(raw) == 3:
                parts = tuple(raw)
            else:
                parts = None
            if parts is None or not all(isinstance(p, str) and p for p in parts):
                log.warning('Skipping malformed TOUR_SLIDES entry in %s: %r',
                            file_path, raw)
                continue
            discovered.append((parts[0], parts[1], parts[2]))
    return discovered


def load_runtime_capability_class(capability: DropinRuntimeCapability) -> type:
    """Load the class backing a runtime capability declaration."""
    cls = load_dropin_symbol(capability.relative_file, capability.class_symbol)
    if not inspect.isclass(cls):
        raise ImportError(
            f'Runtime capability {capability.name} symbol is not a class: '
            f'{capability.class_symbol}'
        )
    return cls


def register_runtime_capability(
    vj_api: Any,
    instance: Any,
    capability: DropinRuntimeCapability,
) -> DropinBindingState:
    """Register subsystem/key-handler bindings declared by capability metadata."""
    state = DropinBindingState()
    if capability.subsystem_name:
        state.subsystem_registered = bool(
            vj_api.register_subsystem(capability.subsystem_name, instance)
        )

    if capability.key_handler_attr:
        handler = getattr(instance, capability.key_handler_attr, None)
        if callable(handler):
            vj_api.register_key_handler(capability.name, handler)
            state.key_handler_registered = True
    return state


def unregister_runtime_capability(vj_api: Any, capability: DropinRuntimeCapability) -> None:
    """Undo runtime bindings for a previously-registered capability."""
    if capability.key_handler_attr:
        vj_api.unregister_key_handler(capability.name)
    if capability.subsystem_name:
        vj_api.unregister_subsystem(capability.subsystem_name)


def discover_runtime_capabilities() -> list[dict[str, Any]]:
    """Discover optional CAPABILITIES metadata from drop-in modules.

    This is a schema-light skeleton used for incremental migration away from
    hardcoded app-side drop-in wiring. Modules may expose either
    ``CAPABILITIES`` or ``DROPIN_CAPABILITIES`` as a dict/list payload.
    """
    root = _dropins_root()
    if not root.exists():
        return []

    discovered: list[dict[str, Any]] = []
    for file_path in sorted(root.glob('*/*.py')):
        if file_path.name == '__init__.py' or '__pycache__' in file_path.parts:
            continue
        if _is_dropin_excluded(file_path.parent.name):
            continue
        try:
            module = _load_module_from_file(file_path)
        except Exception as exc:
            log.warning('Skipping drop-in capability module %s: %s', file_path, exc)
            continue

        for attr_name in ('DROPIN_CAPABILITIES', 'CAPABILITIES'):
            raw = getattr(module, attr_name, None)
            if raw is None:
                continue
            if isinstance(raw, dict):
                discovered.append({'dropin': file_path.parent.name, 'file': str(file_path.name), **raw})
            elif isinstance(raw, (list, tuple)):
                for item in raw:
                    if isinstance(item, dict):
                        discovered.append({'dropin': file_path.parent.name, 'file': str(file_path.name), **item})
            break
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
