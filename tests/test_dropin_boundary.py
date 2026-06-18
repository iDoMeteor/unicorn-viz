"""Drop-in / core module boundary enforcement.

Verifies that no file under ``unicornviz/`` contains a direct static import of
a drop-in path (i.e. ``from drop_ins.`` or ``import drop_ins.``).

All drop-in symbols must flow through ``unicornviz.dropins.load_dropin_symbol``
which uses ``importlib.util.spec_from_file_location`` at runtime.  A bare
static import would create a hard compile-time dependency that defeats the
optional-drop-in design and breaks the project on a clean checkout that lacks
the submodule.

The one permitted exception is ``unicornviz/dropins.py`` itself — that *is* the
gateway and necessarily references drop-in path strings.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE_DIR = ROOT / 'unicornviz'
GATEWAY = CORE_DIR / 'dropins.py'

# Match bare string literals that look like drop-in module paths used in
# importlib calls (e.g. "drop-ins/foo-01/foo.py") — allowed only in dropins.py.
_DROPIN_PATH_RE = re.compile(r'drop[-_]ins[/\\]')


def _find_py_files(directory: Path) -> list[Path]:
    return sorted(
        p for p in directory.rglob('*.py')
        if '__pycache__' not in p.parts
    )


def _collect_import_violations(path: Path) -> list[str]:
    """Return list of violation descriptions for bare drop-in static imports."""
    try:
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []  # syntax errors caught elsewhere

    violations: list[str] = []
    rel = path.relative_to(ROOT)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if 'drop_ins' in alias.name or 'drop-ins' in alias.name:
                    violations.append(
                        f'{rel}:{node.lineno}: bare import of drop-in module '
                        f'"{alias.name}" — use load_dropin_symbol() instead'
                    )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            if 'drop_ins' in module or 'drop-ins' in module:
                violations.append(
                    f'{rel}:{node.lineno}: bare from-import of drop-in module '
                    f'"{module}" — use load_dropin_symbol() instead'
                )

    return violations


def test_no_bare_dropin_imports_in_core() -> None:
    """No file under unicornviz/ (except dropins.py) may statically import drop-ins."""
    violations: list[str] = []

    for py_file in _find_py_files(CORE_DIR):
        if py_file == GATEWAY:
            continue  # dropins.py is the approved gateway; skip
        violations.extend(_collect_import_violations(py_file))

    assert not violations, (
        'Bare drop-in imports found in core unicornviz/ package '
        '(use load_dropin_symbol() instead):\n  '
        + '\n  '.join(violations)
    )


def test_dropins_gateway_uses_spec_from_file() -> None:
    """dropins.py must load drop-in code via spec_from_file_location, not bare imports."""
    source = GATEWAY.read_text(encoding='utf-8')
    assert 'spec_from_file_location' in source, (
        'unicornviz/dropins.py no longer uses spec_from_file_location — '
        'the dynamic loading contract may have changed; review before proceeding.'
    )
