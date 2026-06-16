from __future__ import annotations

from unicornviz.overlays import Overlays


def test_overlays_destroy_is_safe_when_gl_attrs_are_missing() -> None:
    overlays = Overlays.__new__(Overlays)

    overlays.destroy()