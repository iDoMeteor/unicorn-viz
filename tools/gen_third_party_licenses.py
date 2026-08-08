#!/usr/bin/env python3
from __future__ import annotations

"""Generate THIRD_PARTY_LICENSES.md from installed distribution metadata.

Why this exists: MIT, BSD and Apache-2.0 all permit unlimited use in exchange
for one thing — the copyright notice and license text must travel with any
binary you distribute.  Every bundle unicorn-viz ships (Flatpak, Snap, the
Windows installer) therefore has to carry the notices of everything inside it.
Maintaining that list by hand goes stale the first time a pin moves, so it is
generated from the environment that was actually validated.

Scope: the *shipped* runtime closure — the packages named in `requirements.txt`
plus everything they pull in transitively.  Development-only tooling (pytest,
ruff, bandit, pip-audit, pre-commit) is excluded because it never reaches a
user.  Optional drop-in dependencies are listed by name in a separate advisory
section, without license text, because they are installed by the operator and
are not part of any bundle we produce.

Run it from the validated virtualenv, not a bare interpreter — the whole point
is to describe the environment being shipped::

    .venv/bin/python tools/gen_third_party_licenses.py

Re-run it whenever `requirements.txt` pins change, and commit the result.
Exits non-zero if a required distribution is not installed, since a silently
short list is worse than no list at all.
"""

import argparse
import re
import sys
from importlib.metadata import Distribution, PackageNotFoundError, distribution
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = PROJECT_ROOT / 'THIRD_PARTY_LICENSES.md'
CORE_REQUIREMENTS = PROJECT_ROOT / 'requirements.txt'
DROPIN_GLOB = 'drop-ins/*/requirements.txt'

# Packages listed in requirements.txt that are optional extras rather than part
# of the shipped runtime: they are only needed by tools/package_training_set.py
# for LLM detector scoring and are never imported by the app.
OPTIONAL_CORE = frozenset({'openai', 'anthropic'})

# Environment markers we resolve as false when walking dependency metadata:
# 'extra == ...' pulls in optional feature sets nobody installed.
_EXTRA_MARKER = re.compile(r'\bextra\s*==')


def _normalize(name: str) -> str:
    """Return the PEP 503 normalized form of a distribution name."""
    return re.sub(r'[-_.]+', '-', name).lower()


def _parse_requirements(path: Path) -> list[str]:
    """Return the distribution names named in a pip requirements file."""
    names: list[str] = []
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line or line.startswith('-'):
            continue
        names.append(re.split(r'[<>=!~\[; ]', line, maxsplit=1)[0].strip())
    return [n for n in names if n]


def _runtime_requires(dist: Distribution) -> list[str]:
    """Return the non-optional distribution names `dist` depends on."""
    out: list[str] = []
    for req in dist.requires or []:
        spec, _, marker = req.partition(';')
        if marker and _EXTRA_MARKER.search(marker):
            continue
        name = re.split(r'[<>=!~\[; (]', spec, maxsplit=1)[0].strip()
        if name:
            out.append(name)
    return out


def _resolve_closure(roots: list[str]) -> tuple[dict[str, Distribution], list[str]]:
    """Walk the transitive runtime dependency closure of `roots`.

    Returns the resolved distributions keyed by normalized name, plus the
    names that could not be found in the current environment.
    """
    found: dict[str, Distribution] = {}
    missing: list[str] = []
    queue = list(roots)
    seen: set[str] = set()
    while queue:
        name = queue.pop()
        key = _normalize(name)
        if key in seen:
            continue
        seen.add(key)
        try:
            dist = distribution(name)
        except PackageNotFoundError:
            missing.append(name)
            continue
        found[key] = dist
        queue.extend(_runtime_requires(dist))
    return found, missing


def _license_id(dist: Distribution) -> str:
    """Return the best available short license identifier for `dist`."""
    meta = dist.metadata
    expr = (meta.get('License-Expression') or '').strip()
    if expr:
        return expr
    classifiers = [
        c.split('::')[-1].strip()
        for c in (meta.get_all('Classifier') or [])
        if c.startswith('License ::')
    ]
    classifiers = [c for c in classifiers if c != 'OSI Approved']
    if classifiers:
        return '; '.join(classifiers)
    declared = (meta.get('License') or '').strip()
    if declared and '\n' not in declared and len(declared) < 60:
        return declared
    if declared:
        # Some projects paste the entire license body into the License field.
        return 'see full text below'
    return 'UNKNOWN — verify manually'


def _license_files(dist: Distribution) -> list[tuple[str, str]]:
    """Return (display name, text) for every license file `dist` ships."""
    out: list[tuple[str, str]] = []
    for entry in dist.files or []:
        upper = entry.name.upper()
        if not (upper.startswith(('LICEN', 'COPYING', 'NOTICE'))
                or 'LICENSE' in upper):
            continue
        if entry.suffix.lower() in {'.py', '.pyc', '.so', '.xml'}:
            continue
        # Read through locate(): PackagePath.read_text() takes no `errors`
        # argument, and a few wheels ship license files with stray bytes.
        try:
            text = Path(str(entry.locate())).read_text(
                encoding='utf-8', errors='replace',
            )
        except Exception:  # unreadable/binary artefact — skip, note nothing
            continue
        if text.strip():
            out.append((entry.name, text.strip()))
    return out


def _dropin_optional() -> dict[str, list[str]]:
    """Return {drop-in name: [dependency names]} from drop-in requirements."""
    out: dict[str, list[str]] = {}
    for path in sorted(PROJECT_ROOT.glob(DROPIN_GLOB)):
        names = _parse_requirements(path)
        if names:
            out[path.parent.name] = names
    return out


def _render(dists: dict[str, Distribution], optional: dict[str, list[str]]) -> str:
    """Render the full attribution document."""
    ordered = sorted(dists.values(), key=lambda d: _normalize(d.metadata['Name']))
    lines: list[str] = []
    add = lines.append

    add('# Third-Party Licenses')
    add('')
    add('Unicorn Viz is distributed under the MIT license (see `LICENSE`).  It')
    add('bundles and depends on the third-party software listed below, each')
    add('under its own license.  This file satisfies the attribution')
    add('requirement those licenses place on binary distribution, and is')
    add('installed alongside the application by every packaging target.')
    add('')
    add('**Do not edit this file by hand.**  Regenerate it from the validated')
    add('environment whenever `requirements.txt` pins change::')
    add('')
    add('    .venv/bin/python tools/gen_third_party_licenses.py')
    add('')
    add('## Summary')
    add('')
    add('| Package | Version | License |')
    add('|---|---|---|')
    for dist in ordered:
        add(f'| {dist.metadata["Name"]} | {dist.version} | {_license_id(dist)} |')
    add('')

    if optional:
        add('## Optional drop-in dependencies (not bundled)')
        add('')
        add('These are declared by individual drop-ins and installed by the')
        add('operator on their own machine.  They are **not** included in any')
        add('bundle produced from this repository, so their licenses are not')
        add('reproduced here — but note that some carry obligations that would')
        add('attach to a bundle if one ever shipped them.  See')
        add('`docs/audits/2026-08-08-licensing-audit.md`.')
        add('')
        add('| Drop-in | Dependencies |')
        add('|---|---|')
        for name, deps in sorted(optional.items()):
            add(f'| {name} | {", ".join(sorted(deps))} |')
        add('')

    add('## Full license texts')
    add('')
    for dist in ordered:
        name = dist.metadata['Name']
        add(f'### {name} {dist.version}')
        add('')
        add(f'License: {_license_id(dist)}')
        homepage = dist.metadata.get('Home-page') or ''
        if homepage:
            add('')
            add(f'Homepage: {homepage}')
        add('')
        files = _license_files(dist)
        if not files:
            # Some projects ship no license file but paste the whole license
            # body into the metadata `License` field instead.
            declared = (dist.metadata.get('License') or '').strip()
            if len(declared) > 200:
                add('```')
                add(declared)
                add('```')
                add('')
                continue
            add('*No license file is included in this distribution.  Consult the')
            add("project's repository for the authoritative license text.*")
            add('')
            continue
        for filename, text in files:
            if len(files) > 1:
                add(f'#### {filename}')
                add('')
            add('```')
            add(text)
            add('```')
            add('')
    return '\n'.join(lines) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--out', type=Path, default=DEFAULT_OUT,
        help=f'output path (default: {DEFAULT_OUT.relative_to(PROJECT_ROOT)})',
    )
    parser.add_argument(
        '--check', action='store_true',
        help='exit non-zero if the output file is out of date instead of writing',
    )
    args = parser.parse_args()

    roots = [
        n for n in _parse_requirements(CORE_REQUIREMENTS)
        if _normalize(n) not in {_normalize(o) for o in OPTIONAL_CORE}
    ]
    dists, missing = _resolve_closure(roots)
    if missing:
        print(
            'error: not installed in this interpreter: ' + ', '.join(sorted(missing)),
            file=sys.stderr,
        )
        print(
            'Run this from the validated virtualenv (.venv/bin/python).',
            file=sys.stderr,
        )
        return 1

    rendered = _render(dists, _dropin_optional())

    if args.check:
        current = args.out.read_text(encoding='utf-8') if args.out.exists() else ''
        if current != rendered:
            print(f'error: {args.out} is out of date — regenerate it', file=sys.stderr)
            return 1
        print(f'{args.out} is up to date ({len(dists)} packages)')
        return 0

    args.out.write_text(rendered, encoding='utf-8')
    print(f'wrote {args.out} — {len(dists)} packages')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
