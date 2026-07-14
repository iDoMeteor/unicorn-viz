"""Version report for unicorn-viz core and all drop-ins.

Run from anywhere:
    python tools/version_report.py
    python tools/version_report.py --plain   # no colour (for piping/logging)
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
DROPINS_DIR = ROOT / 'drop-ins'

# ---------------------------------------------------------------------------
# ANSI
# ---------------------------------------------------------------------------

RESET   = '\033[0m'
BOLD    = '\033[1m'
DIM     = '\033[2m'
RED     = '\033[91m'
GREEN   = '\033[92m'
YELLOW  = '\033[93m'
BLUE    = '\033[94m'
MAGENTA = '\033[95m'
CYAN    = '\033[96m'
WHITE   = '\033[97m'

_USE_COLOR = True


def _c(*codes: str) -> str:
    return ''.join(codes) if _USE_COLOR else ''


def _r() -> str:
    return RESET if _USE_COLOR else ''


# ---------------------------------------------------------------------------
# Version parsing helpers
# ---------------------------------------------------------------------------

_VER_RE = re.compile(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
_README_VER_RE = re.compile(r'\*\*[Vv]ersion\s+([0-9][0-9a-zA-Z.\-]*)', re.MULTILINE)


def _find_version_in_file(path: Path) -> str | None:
    try:
        m = _VER_RE.search(path.read_text(encoding='utf-8', errors='ignore'))
        return m.group(1) if m else None
    except OSError:
        return None


def _find_version_in_readme(readme: Path) -> str | None:
    try:
        m = _README_VER_RE.search(readme.read_text(encoding='utf-8', errors='ignore'))
        return m.group(1).rstrip('.*·').strip() if m else None
    except OSError:
        return None


# Primary-module priority: *_controller.py first, then any .py not starting
# with test_/__init__ at the root, sorted largest-first.
def _primary_module(directory: Path) -> Path | None:
    root_py = [
        p for p in directory.glob('*.py')
        if not p.name.startswith(('test_', '__init__'))
        and '__pycache__' not in str(p)
    ]
    controllers = [p for p in root_py if p.name.endswith('_controller.py')]
    if controllers:
        return max(controllers, key=lambda p: p.stat().st_size)
    if root_py:
        return max(root_py, key=lambda p: p.stat().st_size)
    return None


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ComponentInfo:
    name: str
    module_version: str | None
    readme_version: str | None
    module_file: str        # relative path of the file where version was found
    mismatch: bool = False

    @property
    def display_version(self) -> str:
        return self.module_version or self.readme_version or ''

    @property
    def tier(self) -> int:
        """Sort key: RC1=0, beta=1, 0.9=2, 0.8=3, 0.7=4, 0.5=5, 0.2=6, none=7."""
        v = self.display_version
        if not v:
            return 7
        if 'rc' in v.lower():
            return 0
        if 'beta' in v.lower():
            return 1
        try:
            parts = re.sub(r'-.*', '', v).split('.')
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
            return 10 - minor * 1 - (1 if patch else 0)  # higher minor = lower tier number
        except (ValueError, IndexError):
            return 6


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def _collect_core() -> ComponentInfo:
    init = ROOT / 'unicornviz' / '__init__.py'
    ver = _find_version_in_file(init) if init.exists() else None
    readme_ver = _find_version_in_readme(ROOT / 'README.md')
    return ComponentInfo(
        name='core (unicornviz)',
        module_version=ver,
        readme_version=readme_ver,
        module_file='unicornviz/__init__.py',
        mismatch=bool(ver and readme_ver and ver != readme_ver),
    )


def _collect_dropin(directory: Path) -> ComponentInfo:
    name = directory.name
    readme = directory / 'README.md'
    readme_ver = _find_version_in_readme(readme)

    primary = _primary_module(directory)
    module_ver: str | None = None
    module_file = '—'

    # Search all root .py files for __version__; prefer the primary module.
    candidates = [primary] if primary else []
    candidates += [
        p for p in sorted(directory.glob('*.py'), key=lambda p: p.stat().st_size, reverse=True)
        if p != primary
        and not p.name.startswith(('test_', '__init__'))
    ]
    for c in candidates:
        if c is None:
            continue
        v = _find_version_in_file(c)
        if v:
            module_ver = v
            module_file = c.relative_to(ROOT).as_posix()
            break
    if module_file == '—' and primary:
        module_file = primary.relative_to(ROOT).as_posix()

    return ComponentInfo(
        name=name,
        module_version=module_ver,
        readme_version=readme_ver,
        module_file=module_file,
        mismatch=bool(module_ver and readme_ver and module_ver != readme_ver),
    )


def _collect_all() -> list[ComponentInfo]:
    components: list[ComponentInfo] = [_collect_core()]
    if DROPINS_DIR.is_dir():
        for d in sorted(DROPINS_DIR.iterdir()):
            if d.is_dir() and not d.name.startswith('.'):
                components.append(_collect_dropin(d))
    return components


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _version_colour(v: str) -> str:
    if not v:
        return _c(DIM, RED)
    vl = v.lower()
    if 'rc' in vl:
        return _c(BOLD, GREEN)
    if 'beta' in vl:
        return _c(BOLD, CYAN)
    try:
        minor = int(re.sub(r'-.*', '', v).split('.')[1])
        if minor >= 9:
            return _c(BOLD, YELLOW)
        if minor >= 7:
            return _c(YELLOW)
        if minor >= 5:
            return _c(WHITE)
        return _c(DIM, WHITE)
    except (ValueError, IndexError):
        return _c(DIM, WHITE)


def _tier_label(v: str) -> str:
    if not v:
        return 'UNVERSIONED'
    vl = v.lower()
    if 'rc' in vl:
        return 'RC'
    if 'beta' in vl:
        return 'BETA'
    try:
        minor = int(re.sub(r'-.*', '', v).split('.')[1])
        if minor >= 9:
            return 'alpha ▲'
        if minor >= 7:
            return 'alpha'
        if minor >= 5:
            return 'alpha ▼'
        return 'early alpha'
    except (ValueError, IndexError):
        return '?'


def _print_report(components: list[ComponentInfo]) -> None:
    # Sort: core first, then by tier desc, then alphabetically.
    core = [c for c in components if c.name.startswith('core')]
    rest = sorted(
        [c for c in components if not c.name.startswith('core')],
        key=lambda c: (c.tier, c.name),
    )
    ordered = core + rest

    col_name  = 28
    col_ver   = 18
    col_tier  = 12
    col_src   = 10
    total_w   = col_name + col_ver + col_tier + col_src + 8

    sep = _c(DIM) + '─' * total_w + _r()

    print()
    print(_c(BOLD, CYAN) + '  Unicorn Viz — Version Report' + _r())
    print(sep)
    header = (
        f"  {'Component':<{col_name}}  {'Version':<{col_ver}}  "
        f"{'Tier':<{col_tier}}  Source"
    )
    print(_c(DIM) + header + _r())
    print(sep)

    current_tier_label: str | None = None

    for c in ordered:
        tl = _tier_label(c.display_version)

        # Tier group header
        if tl != current_tier_label:
            current_tier_label = tl
            tier_colour = {
                'RC':          _c(BOLD, GREEN),
                'BETA':        _c(BOLD, CYAN),
                'alpha ▲':     _c(BOLD, YELLOW),
                'alpha':       _c(YELLOW),
                'alpha ▼':     _c(WHITE),
                'early alpha': _c(DIM, WHITE),
                'UNVERSIONED': _c(DIM, RED),
            }.get(tl, _c(DIM))
            if c.name != ordered[0].name:
                print()
            print(tier_colour + f'  ── {tl} ' + '─' * (total_w - len(tl) - 6) + _r())

        # Version cell
        v = c.display_version or 'not set'
        vc = _version_colour(c.display_version)

        # Mismatch / source indicators
        if not c.module_version and not c.readme_version:
            src = _c(DIM, RED) + 'missing' + _r()
        elif c.mismatch:
            src = _c(RED) + f'MISMATCH (readme={c.readme_version})' + _r()
        elif c.module_version:
            src = _c(DIM) + 'module' + _r()
        else:
            src = _c(DIM) + 'readme' + _r()

        name_str = c.name
        if c.name.startswith('core'):
            name_str = _c(BOLD) + c.name + _r()

        print(
            f"  {name_str:<{col_name + (len(_c(BOLD)) + len(_r()) if c.name.startswith('core') else 0)}}  "
            f"{vc}{v:<{col_ver}}{_r()}  "
            f"{_c(DIM)}{tl:<{col_tier}}{_r()}  "
            f"{src}"
        )

    print(sep)

    # Summary
    versioned   = [c for c in components if c.display_version]
    unversioned = [c for c in components if not c.display_version]
    mismatches  = [c for c in components if c.mismatch]
    rc_count    = sum(1 for c in components if 'rc'   in c.display_version.lower())
    beta_count  = sum(1 for c in components if 'beta' in c.display_version.lower())

    print(
        f"\n  {_c(BOLD)}{len(components)}{_r()} components total  ·  "
        f"{_c(BOLD, GREEN)}{rc_count} RC{_r()}  "
        f"{_c(BOLD, CYAN)}{beta_count} beta{_r()}  "
        f"{_c(YELLOW)}{len(versioned) - rc_count - beta_count} alpha{_r()}  "
        f"{_c(DIM, RED)}{len(unversioned)} unversioned{_r()}"
    )
    if mismatches:
        print(
            f"  {_c(BOLD, RED)}⚠  {len(mismatches)} version mismatch(es): "
            + ', '.join(c.name for c in mismatches)
            + _r()
        )
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plain', action='store_true', help='Disable colour output')
    args = parser.parse_args()

    global _USE_COLOR
    _USE_COLOR = not args.plain and sys.stdout.isatty()

    components = _collect_all()
    _print_report(components)


if __name__ == '__main__':
    main()
