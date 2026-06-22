"""Module-extraction boundary & re-export regression tests.

Pins the refactor that moved the null fallback controllers out of
``unicornviz.app`` into ``unicornviz._null_controllers`` and the CTA hype
overlay out of ``unicornviz.overlays`` into ``unicornviz.cta_overlay``
(mono-file refactor plan items A & B, 2026-06-19).

These tests guard the invariants that keep the moves behaviour-preserving:

* the moved symbols stay importable from their *original* modules
  (backward-compatible re-exports) and resolve to the **same objects** as the
  canonical homes — so ``isinstance`` checks and existing imports never break;
* the CTA defaults keep their exact values, including the precise unicode
  codepoints of the third slot icon — a subtle detail that is easy to corrupt
  when hand-editing the escape sequence;
* ``_build_font_texture`` / ``_FONT_8X8`` did **not** move (they belong to
  ``Overlays``, not the CTA overlay);
* the new leaf modules do not import their former parents, so the extraction
  cannot silently reintroduce a circular dependency.
"""
from __future__ import annotations

import ast
from pathlib import Path

import unicornviz._null_controllers as null_mod
import unicornviz.app as app_mod
import unicornviz.cta_overlay as cta_mod
import unicornviz.overlays as overlays_mod

ROOT = Path(__file__).resolve().parent.parent

_NULL_NAMES = [
    '_NullMultiHeadController',
    '_NullScreenBurstController',
    '_NullWebcamSystem',
    '_NullRTMPStreamer',
    '_NullPostFxController',
]


def test_null_controllers_canonical_home() -> None:
    """All five null controllers live in unicornviz._null_controllers."""
    for name in _NULL_NAMES:
        assert hasattr(null_mod, name), f'{name} missing from _null_controllers'
        assert getattr(null_mod, name).__module__ == 'unicornviz._null_controllers'


def test_null_controllers_reexported_from_app() -> None:
    """app.py re-exports the null controllers as the *same* objects.

    Several call sites (and tests) do ``from unicornviz.app import _Null...``
    and ``isinstance(x, _Null...)``; those only stay correct if the re-export
    is the identical class object, not a copy.
    """
    for name in _NULL_NAMES:
        assert hasattr(app_mod, name), f'{name} no longer importable from unicornviz.app'
        assert getattr(app_mod, name) is getattr(null_mod, name), (
            f'{name} from unicornviz.app is not the same object as the canonical '
            f'unicornviz._null_controllers.{name} — isinstance checks would break'
        )


def test_cta_overlay_canonical_home_and_reexport() -> None:
    """CTAOverlay lives in cta_overlay and overlays re-exports the same object."""
    assert cta_mod.CTAOverlay.__module__ == 'unicornviz.cta_overlay'
    assert overlays_mod.CTAOverlay is cta_mod.CTAOverlay


def test_cta_defaults_reexported_and_unchanged() -> None:
    """CTA defaults are re-exported from overlays and keep exact values + codepoints."""
    assert overlays_mod._CTA_SHOW_DURATION == cta_mod._CTA_SHOW_DURATION == 4.5
    assert overlays_mod._CTA_SLOTS == cta_mod._CTA_SLOTS
    assert len(cta_mod._CTA_SLOTS) == 3

    assert cta_mod._CTA_SLOTS[0] == ('Push the buttons!', '\U0001f44d')
    assert cta_mod._CTA_SLOTS[1] == ('Do the thangs!', '\U0001f514')
    # Exact icon codepoints for slot 3: heart + variation selector + thin space
    # + outbox-tray.  Guards the unicode escape that was nearly corrupted during
    # the extraction (a literal space would silently replace U+2009).
    third_icon = cta_mod._CTA_SLOTS[2][1]
    assert cta_mod._CTA_SLOTS[2][0] == 'Share the love!'
    assert [ord(c) for c in third_icon] == [0x2764, 0xFE0F, 0x2009, 0x1F4E4]


def test_font_builder_stayed_in_overlays() -> None:
    """_build_font_texture / _FONT_8X8 belong to Overlays and must not have moved."""
    assert hasattr(overlays_mod, '_build_font_texture')
    assert hasattr(overlays_mod, '_FONT_8X8')
    assert not hasattr(cta_mod, '_build_font_texture')
    assert not hasattr(cta_mod, '_FONT_8X8')


def _imported_modules(path: Path) -> set[str]:
    """Return the set of module names imported (statically) by a Python file."""
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module)
    return mods


def test_extracted_modules_have_no_circular_parent_import() -> None:
    """Leaf modules must not import their former parent modules."""
    null_imports = _imported_modules(ROOT / 'unicornviz' / '_null_controllers.py')
    cta_imports = _imported_modules(ROOT / 'unicornviz' / 'cta_overlay.py')
    assert 'unicornviz.app' not in null_imports, (
        '_null_controllers.py must not import unicornviz.app (circular dependency)'
    )
    assert 'unicornviz.overlays' not in cta_imports, (
        'cta_overlay.py must not import unicornviz.overlays (circular dependency)'
    )
