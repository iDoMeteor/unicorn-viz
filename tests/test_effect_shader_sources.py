from __future__ import annotations

from unicornviz.effects import van_gogh


def test_van_gogh_fragment_shader_defines_palette_helper() -> None:
    assert 'vec3 palette(float t)' in van_gogh._FRAG
    assert 'palette(' in van_gogh._FRAG
