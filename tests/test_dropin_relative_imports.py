"""Regression test: relative imports between sibling files within a single
drop-in must resolve.

Drop-in files are loaded via ``importlib.util.spec_from_file_location``
rather than a real package import (see ``unicornviz.dropins``). Without a
registered parent package, any ``from .sibling import X`` inside a drop-in
file raises "attempted relative import with no known parent package" --
silently at module-discovery time (a logged warning, feature just missing)
or loudly at runtime for a lazy import inside a function (a caught exception
that disables the feature it guards).

cta-01 is a real example: ``cta_controller.py`` lazily imports its editor
overlay with ``from .cta_editor import CTAEditor`` inside ``_open_editor()``,
and ``cta_editor.py`` itself imports a sibling with
``from .text_field import TextField``. Both must resolve.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from unicornviz.dropins import load_dropin_symbol


def test_lazy_sibling_relative_import_resolves() -> None:
    """cta_controller._open_editor()'s lazy `from .cta_editor import CTAEditor`
    must succeed instead of silently no-opping."""
    CTAController = load_dropin_symbol('cta-01/cta_controller.py', 'CTAController')
    controller = CTAController({})
    controller.set_vj_api(MagicMock())

    controller._open_editor()

    assert controller.editor_open is True
    assert controller._editor is not None


def test_transitive_sibling_relative_import_resolves() -> None:
    """cta_editor.py's own `from .text_field import TextField` must resolve
    too, since it's loaded as a sibling submodule of the same synthetic
    drop-in package, not directly via load_dropin_symbol."""
    CTAController = load_dropin_symbol('cta-01/cta_controller.py', 'CTAController')
    controller = CTAController({})
    controller.set_vj_api(MagicMock())
    controller._open_editor()

    editor = controller._editor
    assert editor is not None
    assert type(editor).__module__.endswith('.cta_editor')
