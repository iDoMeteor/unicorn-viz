from __future__ import annotations

from unicornviz.effects import black_hole_cathedral as bhc
from unicornviz.effects.registry import get_effects


def test_discovered_by_registry() -> None:
    names = [c.NAME for c in get_effects()]
    assert 'Black Hole Cathedral' in names


def test_fragment_shader_declares_audio_and_lens_uniforms() -> None:
    frag = bhc._FRAG
    for uniform in ('iBass', 'iMid', 'iTreble', 'iBeat', 'iHue', 'iPetals', 'iSpin'):
        assert uniform in frag, f'missing uniform {uniform}'
    assert 'fragColor' in frag
    assert 'hsv2rgb' in frag  # rose-window stained glass palette helper


def test_metadata() -> None:
    assert bhc.BlackHoleCathedral.NAME == 'Black Hole Cathedral'
    assert 'cosmic' in bhc.BlackHoleCathedral.TAGS
