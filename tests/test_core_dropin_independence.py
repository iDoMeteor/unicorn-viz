"""Core must start and run with every drop-in absent.

Static half of the independence audit (2026-09-09). Two rules from CLAUDE.md
("Drop-In Independence Rules"), checked over every module under
``unicornviz/``:

1. No module imports drop-in code directly. Drop-ins are reached only through
   the loaders in ``unicornviz.dropins`` (``load_dropin_symbol``,
   ``load_runtime_capability_class``).
2. Every loader call is fault-tolerant: it sits inside a ``try`` block, or
   inside a ``_load_*`` helper that either wraps it in ``try`` itself or is
   only ever called from inside a ``try``.

The dynamic half (stage a core-only payload, import every core module, run
``--self-test`` with no ``drop-ins/`` directory) is run by the installer
team's audit script and CI; see docs/planning/installers.md.
"""
from __future__ import annotations

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'unicornviz'
LOADERS = {'load_dropin_symbol', 'load_runtime_capability_class'}
# Helpers whose body is the guarded fallback path (not a loader passthrough).
DROPIN_MODULE_PREFIXES = ('drop_ins', 'drop-ins', 'unicornviz_dropins')


def _call_name(node: ast.Call) -> str:
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return getattr(fn, 'id', '')


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _enclosing_try(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.Try | None:
    p = parents.get(node)
    while p is not None:
        if isinstance(p, ast.Try):
            return p
        if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return None
        p = parents.get(p)
    return None


def _inside_try(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    return _enclosing_try(node, parents) is not None


def _swallows(try_node: ast.Try) -> bool:
    """True when no handler re-raises (a helper that re-raises is a passthrough)."""
    for handler in try_node.handlers:
        if any(isinstance(n, ast.Raise) for n in ast.walk(handler)):
            return False
    return bool(try_node.handlers)


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    p = parents.get(node)
    while p is not None:
        if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return p.name
        p = parents.get(p)
    return ''


def _core_modules() -> list[tuple[Path, ast.Module]]:
    return [(f, ast.parse(f.read_text())) for f in sorted(CORE.rglob('*.py'))]


def test_core_never_imports_a_dropin_directly() -> None:
    offenders = []
    for f, tree in _core_modules():
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                names = [n.module or '']
            else:
                continue
            for nm in names:
                if nm.startswith(DROPIN_MODULE_PREFIXES) or '.drop_ins' in nm:
                    offenders.append(f'{f.relative_to(CORE.parent)}:{n.lineno} imports {nm}')
    assert not offenders, '\n'.join(offenders)


def test_every_dropin_loader_call_is_guarded() -> None:
    # Pass 1: which `_load_*` helpers guard their own loader call?
    self_guarding: set[str] = set()
    passthrough: set[str] = set()
    for _f, tree in _core_modules():
        parents = _parents(tree)
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and _call_name(n) in LOADERS:
                fn = _enclosing_function(n, parents)
                if fn.startswith('_load_') or fn.startswith('load_'):
                    guard = _enclosing_try(n, parents)
                    (self_guarding if guard is not None and _swallows(guard) else passthrough).add(fn)
    passthrough -= self_guarding
    # Pass 2: every raw loader call, and every call to a passthrough helper,
    # must sit inside a try block.
    unguarded = []
    for f, tree in _core_modules():
        parents = _parents(tree)
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            name = _call_name(n)
            is_loader = name in LOADERS
            is_passthrough_helper = name in passthrough
            if not (is_loader or is_passthrough_helper):
                continue
            fn = _enclosing_function(n, parents)
            if is_loader and (fn.startswith('_load_') or fn.startswith('load_')):
                continue          # judged by its callers (pass 1)
            if not _inside_try(n, parents):
                unguarded.append(f'{f.relative_to(CORE.parent)}:{n.lineno} {name}()')
    assert not unguarded, 'drop-in loader reachable without try/except:\n' + '\n'.join(unguarded)
