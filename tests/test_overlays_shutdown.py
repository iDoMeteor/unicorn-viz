"""Overlays.destroy() / help-icon reload -- GL resource release tests.

destroy() used to release only the help-icon textures and the icon
VAO/VBO/program (plus a dead block for CTAOverlay-only attrs), leaking the
font atlas, the text and panel programs/buffers, and the CTA overlay's own
resources.  _load_help_icon_textures() also dropped the previous dict on a
bucket change (resize across 3840 px) without releasing it.  Bare
``Overlays`` via object.__new__ with fake GL objects that record release().
"""
from __future__ import annotations

from pathlib import Path

from unicornviz.overlays import Overlays


class _Fake:
    def __init__(self, log: list[str], name: str) -> None:
        self._log = log
        self._name = name

    def release(self) -> None:
        self._log.append(self._name)


class _FakeCTA:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    def destroy(self) -> None:
        self._log.append('cta.destroy')


def test_overlays_destroy_is_safe_when_gl_attrs_are_missing() -> None:
    overlays = Overlays.__new__(Overlays)

    overlays.destroy()


def test_destroy_releases_every_gl_resource_and_the_cta_overlay() -> None:
    log: list[str] = []
    ov = Overlays.__new__(Overlays)
    for attr in (
        '_font_tex', '_prog', '_vbo', '_vao',
        '_panel_prog', '_panel_vbo', '_panel_vao',
        '_icon_prog', '_icon_vbo', '_icon_vao',
    ):
        setattr(ov, attr, _Fake(log, attr))
    ov._help_icon_textures = {'help': _Fake(log, 'icon:help'), 'settings': _Fake(log, 'icon:settings')}
    ov._cta = _FakeCTA(log)

    ov.destroy()

    assert set(log) == {
        '_font_tex', '_prog', '_vbo', '_vao',
        '_panel_prog', '_panel_vbo', '_panel_vao',
        '_icon_prog', '_icon_vbo', '_icon_vao',
        'icon:help', 'icon:settings', 'cta.destroy',
    }
    assert len(log) == 13, 'each resource released exactly once'
    assert ov._help_icon_textures == {}
    # VAOs go before the buffers/programs they bind.
    assert log.index('_vao') < log.index('_vbo') < log.index('_prog')
    assert log.index('_panel_vao') < log.index('_panel_vbo') < log.index('_panel_prog')
    assert log.index('_icon_vao') < log.index('_icon_vbo') < log.index('_icon_prog')


def test_destroy_keeps_going_when_one_release_raises() -> None:
    log: list[str] = []

    class _Broken:
        def release(self) -> None:
            raise RuntimeError('already released')

    ov = Overlays.__new__(Overlays)
    ov._vao = _Broken()
    ov._vbo = _Fake(log, '_vbo')
    ov._cta = _FakeCTA(log)

    ov.destroy()

    assert log == ['_vbo', 'cta.destroy']


def test_help_icon_reload_releases_the_previous_textures(tmp_path: Path) -> None:
    log: list[str] = []
    ov = Overlays.__new__(Overlays)
    ov._help_icon_textures = {'help': _Fake(log, 'icon:help')}
    # Point at an empty asset dir so nothing new is loaded and no GL
    # context is needed; the previous set must still be released.
    ov._help_icon_asset_dir = tmp_path / 'missing'
    ov._help_icon_asset_bucket = '152px'

    ov._load_help_icon_textures()

    assert log == ['icon:help']
    assert ov._help_icon_textures == {}


def test_resize_across_the_3840_boundary_releases_old_bucket_textures(tmp_path: Path) -> None:
    log: list[str] = []
    ov = Overlays.__new__(Overlays)
    ov._width, ov._height = 1920, 1080
    ov._help_icon_asset_bucket = '76px'
    ov._help_icon_textures = {'help': _Fake(log, 'icon:help:76')}
    ov._help_icon_asset_dir = tmp_path / 'missing'

    ov.resize(3840, 2160)

    assert ov._help_icon_asset_bucket == '152px'
    assert log == ['icon:help:76']
