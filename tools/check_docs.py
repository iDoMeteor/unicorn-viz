#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
OWNER_RE = re.compile(r"^(?:\*\*)?Owner:(?:\*\*)?\s*\S+", re.IGNORECASE)
STATUS_RE = re.compile(r"^(?:\*\*)?Status:(?:\*\*)?\s*\S+", re.IGNORECASE)
UPDATED_RE = re.compile(r"^(?:\*\*)?Last updated:(?:\*\*)?\s*\S+", re.IGNORECASE)


def _is_managed_doc(path: Path) -> bool:
    rel = path.as_posix()
    if rel.startswith('docs/archive/'):
        return False
    if rel.startswith('docs/planning/'):
        return True
    if rel.startswith('docs/debug/'):
        return True
    if rel.startswith('docs/audits/'):
        return True
    if rel.startswith('docs/marketing/'):
        return True
    if rel.startswith('drop-ins/') and '/docs/' in rel:
        return True
    if rel == 'REFERENCE.md':
        return True
    return False


def _metadata_ok(text: str) -> bool:
    lines = [ln.strip() for ln in text.splitlines()[:40] if ln.strip()]
    has_owner = any(OWNER_RE.match(ln) for ln in lines)
    has_status = any(STATUS_RE.match(ln) for ln in lines)
    has_updated = any(UPDATED_RE.match(ln) for ln in lines)
    return has_owner and has_status and has_updated


def _link_targets(text: str) -> list[str]:
    return [m.group(1).strip() for m in LINK_RE.finditer(text)]


def _is_external_or_anchor(target: str) -> bool:
    lower = target.lower()
    if lower.startswith('http://') or lower.startswith('https://'):
        return True
    if lower.startswith('mailto:'):
        return True
    if target.startswith('#'):
        return True
    return False


def _check_links(path: Path, text: str) -> list[str]:
    errs: list[str] = []
    for target in _link_targets(text):
        if _is_external_or_anchor(target):
            continue

        path_part = target.split('#', 1)[0].strip()
        if not path_part:
            continue

        resolved = (path.parent / path_part).resolve()
        if not resolved.exists():
            errs.append(f'{path.as_posix()}: broken relative link target: {target}')
    return errs


def _all_doc_files() -> list[Path]:
    """Return all markdown files in docs/, drop-ins/*/docs/, and root-level docs."""
    roots = [
        ROOT / 'docs',
        ROOT / 'REFERENCE.md',
        ROOT / 'README.md',
    ]
    found: list[Path] = []
    for r in roots:
        if r.is_file():
            found.append(r)
        elif r.is_dir():
            found.extend(sorted(r.rglob('*.md')))
    for dropin_docs in sorted((ROOT / 'drop-ins').glob('*/docs')):
        found.extend(sorted(dropin_docs.rglob('*.md')))
    return found


def main(argv: list[str]) -> int:
    warn_only = '--warn-only' in argv
    full_scan = '--full' in argv

    if full_scan:
        files = [f.resolve() for f in _all_doc_files()]
    else:
        files = [Path(a).resolve() for a in argv if a.endswith('.md')]
    errors: list[str] = []

    for abs_path in files:
        try:
            rel_path = abs_path.relative_to(ROOT)
        except ValueError:
            continue

        if not rel_path.exists():
            continue

        try:
            text = rel_path.read_text(encoding='utf-8')
        except Exception as exc:
            errors.append(f'{rel_path.as_posix()}: unable to read file: {exc}')
            continue

        if _is_managed_doc(rel_path) and not _metadata_ok(text):
            errors.append(
                f'{rel_path.as_posix()}: missing metadata header '
                '(Owner, Status, Last updated in first 40 lines)'
            )

        # Archive docs intentionally contain links to moved/deleted files.
        if not rel_path.as_posix().startswith('docs/archive/'):
            errors.extend(_check_links(rel_path, text))

    if errors:
        if warn_only:
            print('docs-check warnings:')
        else:
            print('docs-check failed:')
        for err in errors:
            print(f' - {err}')
        return 0 if warn_only else 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
