#!/usr/bin/env python3
"""Validate embedded GLSL shader strings with glslangValidator.

The script extracts Python string literals that contain a GLSL `#version`
directive, infers their shader stage from assignment or keyword names, writes
them to temporary `.vert` / `.frag` / related files, and runs glslangValidator.
"""
from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGETS = ('unicornviz', 'drop-ins')
STAGE_SUFFIXES = {
    'VERT': 'vert',
    'VERTEX': 'vert',
    'FRAG': 'frag',
    'FRAGMENT': 'frag',
    'GEOM': 'geom',
    'GEOMETRY': 'geom',
    'COMP': 'comp',
    'COMPUTE': 'comp',
    'TESC': 'tesc',
    'TESSELLATION_CONTROL': 'tesc',
    'TESE': 'tese',
    'TESSELLATION_EVALUATION': 'tese',
}
KEYWORD_STAGES = {
    'vertex_shader': 'vert',
    'fragment_shader': 'frag',
    'geometry_shader': 'geom',
    'compute_shader': 'comp',
    'tess_control_shader': 'tesc',
    'tess_evaluation_shader': 'tese',
}


@dataclass(frozen=True)
class Shader:
    """Embedded shader source discovered in a Python file."""

    path: Path
    line: int
    name: str
    stage: str | None
    source: str


def _stage_from_name(name: str) -> str | None:
    upper = name.upper()
    for token, suffix in STAGE_SUFFIXES.items():
        if token in upper:
            return suffix
    return None


def _target_name(target: ast.expr) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _extract_from_file(path: Path) -> tuple[list[Shader], list[str]]:
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    except SyntaxError as exc:
        return [], [f'{path.relative_to(ROOT)}:{exc.lineno}: Python syntax error: {exc.msg}']

    shaders: list[Shader] = []
    seen: set[tuple[int, int]] = set()

    def add_shader(node: ast.Constant, name: str, stage: str | None) -> None:
        if not isinstance(node.value, str) or '#version' not in node.value:
            return
        key = (node.lineno, node.col_offset)
        if key in seen:
            return
        seen.add(key)
        shaders.append(
            Shader(
                path=path,
                line=node.lineno,
                name=name,
                stage=stage,
                source=node.value.strip() + '\n',
            )
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            names = [name for target in node.targets if (name := _target_name(target))]
            name = names[0] if names else f'string_at_{node.value.lineno}'
            add_shader(node.value, name, _stage_from_name(name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Constant):
            name = _target_name(node.target) or f'string_at_{node.value.lineno}'
            add_shader(node.value, name, _stage_from_name(name))
        elif isinstance(node, ast.keyword) and isinstance(node.value, ast.Constant):
            name = node.arg or f'string_at_{node.value.lineno}'
            add_shader(node.value, name, KEYWORD_STAGES.get(name))

    return shaders, []


def _iter_python_files(targets: list[Path]) -> list[Path]:
    files: list[Path] = []
    for target in targets:
        path = target if target.is_absolute() else ROOT / target
        if path.is_file() and path.suffix == '.py':
            files.append(path)
        elif path.is_dir():
            files.extend(
                p for p in path.rglob('*.py')
                if '.venv' not in p.parts and '__pycache__' not in p.parts
            )
    return sorted(set(files))


def _validate_shader(binary: str, shader: Shader, temp_root: Path) -> tuple[bool, str]:
    rel = shader.path.relative_to(ROOT)
    safe_stem = rel.as_posix().replace('/', '__').replace('.', '_')
    shader_path = temp_root / f'{safe_stem}__L{shader.line}_{shader.name}.{shader.stage}'
    shader_path.write_text(shader.source, encoding='utf-8')
    proc = subprocess.run(
        [binary, str(shader_path)],
        check=False,
        text=True,
        capture_output=True,
    )
    label = f'{rel}:{shader.line} {shader.name}.{shader.stage}'
    output = '\n'.join(part for part in (proc.stdout.strip(), proc.stderr.strip()) if part)
    return proc.returncode == 0, f'{label}\n{output}'.rstrip()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'targets',
        nargs='*',
        default=list(DEFAULT_TARGETS),
        help='Python files or directories to scan (default: unicornviz drop-ins)',
    )
    parser.add_argument(
        '--validator',
        default='glslangValidator',
        help='Validator executable name or path',
    )
    args = parser.parse_args(argv)

    binary = shutil.which(args.validator)
    if binary is None:
        print(f'error: {args.validator!r} not found on PATH', file=sys.stderr)
        return 2

    files = _iter_python_files([Path(target) for target in args.targets])
    shaders: list[Shader] = []
    parse_errors: list[str] = []
    for path in files:
        found, errors = _extract_from_file(path)
        shaders.extend(found)
        parse_errors.extend(errors)

    skipped = [shader for shader in shaders if shader.stage is None]
    runnable = [shader for shader in shaders if shader.stage is not None]
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix='unicornviz-glsl-') as temp_dir:
        temp_root = Path(temp_dir)
        for shader in runnable:
            ok, report = _validate_shader(binary, shader, temp_root)
            if not ok:
                failures.append(report)

    print(f'Scanned Python files: {len(files)}')
    print(f'Embedded GLSL shaders found: {len(shaders)}')
    print(f'Validated shaders: {len(runnable)}')
    print(f'Skipped unknown-stage shaders: {len(skipped)}')
    print(f'Python parse errors: {len(parse_errors)}')
    print(f'Validation failures: {len(failures)}')

    if skipped:
        print('\nSkipped shaders:')
        for shader in skipped:
            print(f' - {shader.path.relative_to(ROOT)}:{shader.line} {shader.name}')

    if parse_errors:
        print('\nPython parse errors:')
        for error in parse_errors:
            print(f' - {error}')

    if failures:
        print('\nValidation failures:')
        for failure in failures:
            print(f'\n{failure}')
        return 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
