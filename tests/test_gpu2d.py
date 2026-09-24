"""unicornviz.gpu2d: Pillow-compatible draw lists rendered on the GPU.

Two tiers.  The recorder/atlas tests need no GL and pin the geometry and
color conventions that make GPU output land where Pillow's did.  The render
tests draw real frames on an offscreen GL 3.3 context (SDL ``offscreen``
driver, EGL) and compare against Pillow pixel by pixel; they skip cleanly
where no such context can be made.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from unicornviz import gpu2d

_FONT_PATH = Path(__file__).resolve().parents[1] / 'assets' / 'fonts' / 'ui-font.ttf'


def _instances(frame: gpu2d.GpuFrame) -> np.ndarray:
    return np.frombuffer(frame.instances, dtype=np.float32).reshape(
        -1, gpu2d.FLOATS_PER_INSTANCE)


def _record(draw_fn, w=64, h=48, **kw) -> tuple[gpu2d.GpuFrame, gpu2d.TextureAtlas]:
    atlas = gpu2d.TextureAtlas(256, 128)
    dl = gpu2d.DrawList(atlas, **kw)
    dl.begin(w, h, clear=(1, 2, 3, 255))
    draw_fn(dl)
    frame = dl.finish()
    assert frame is not None
    return frame, atlas


# -- recorder (no GL) ---------------------------------------------------------

def test_boxes_follow_pillow_inclusive_pixels() -> None:
    frame, _ = _record(lambda d: d.rectangle([2, 3, 10, 5], fill=(9, 8, 7)))
    inst = _instances(frame)[0]
    assert inst[:4].tolist() == [2, 3, 11, 6]          # x1/y1 inclusive -> +1
    assert inst[4:8].tolist() == [9, 8, 7, 255]         # RGB gains opaque alpha
    assert inst[14] == gpu2d.KIND_RECT


def test_both_pillow_box_forms_and_named_colors() -> None:
    frame, _ = _record(lambda d: d.ellipse([(1, 1), (5, 5)], fill='red'))
    inst = _instances(frame)[0]
    assert inst[:4].tolist() == [1, 1, 6, 6]
    assert inst[4:8].tolist() == [255, 0, 0, 255]
    assert inst[14] == gpu2d.KIND_ELLIPSE


def test_outline_width_only_counts_with_an_outline() -> None:
    def draw(d):
        d.rectangle([0, 0, 4, 4], fill=(1, 1, 1), width=3)
        d.rectangle([0, 0, 4, 4], outline=(1, 1, 1), width=3)
    inst = _instances(_record(draw)[0])
    assert inst[0, 13] == 0.0 and inst[1, 13] == 3.0


def test_polylines_become_one_instance_per_pair() -> None:
    frame, _ = _record(lambda d: d.line([(0, 0), (10, 0), (10, 5), (20, 9)],
                                        fill=(5, 5, 5)))
    inst = _instances(frame)
    assert len(inst) == 3
    # Axis-aligned segments are Pillow's exact pixels, as rects.
    assert inst[0, :4].tolist() == [0, 0, 11, 1]
    assert inst[1, :4].tolist() == [10, 0, 11, 6]
    assert inst[0, 14] == inst[1, 14] == gpu2d.KIND_RECT
    # Diagonals are capsules between pixel centers; width 0 draws 1px.
    assert inst[2, :4].tolist() == [10.5, 5.5, 20.5, 9.5]
    assert inst[2, 14] == gpu2d.KIND_LINE and inst[2, 13] == 1.0


@pytest.mark.parametrize('width', [1, 2, 3, 4, 5])
def test_wide_axis_lines_cover_pillows_rows(width: int) -> None:
    frame, _ = _record(lambda d: d.line([5, 20, 30, 20], fill=(1, 1, 1),
                                        width=width))
    x0, y0, x1, y1 = _instances(frame)[0, :4]
    ref = Image.new('L', (40, 40))
    ImageDraw.Draw(ref).line([5, 20, 30, 20], fill=255, width=width)
    rows = np.nonzero(np.asarray(ref).any(axis=1))[0]
    cols = np.nonzero(np.asarray(ref).any(axis=0))[0]
    assert (y0, y1 - 1) == (rows.min(), rows.max())
    assert (x0, x1 - 1) == (cols.min(), cols.max())


def test_pillow_compat_flag_marks_shapes_but_not_text() -> None:
    font = ImageFont.truetype(str(_FONT_PATH), 12)

    def draw(d):
        d.rectangle([0, 0, 3, 3], fill=(9, 9, 9, 90))
        d.text((0, 0), 'A', font=font, fill=(255, 255, 255))
    inst = _instances(_record(draw)[0])
    assert inst[0, 15] == 1.0 and inst[1, 15] == 0.0
    off = _instances(_record(draw, pillow_rgba=False)[0])
    assert off[0, 15] == 0.0


def test_text_is_cached_once_per_string_and_font_not_per_color() -> None:
    font = ImageFont.truetype(str(_FONT_PATH), 12)

    def draw(d):
        for col in ((255, 0, 0), (0, 255, 0), (0, 0, 255)):
            d.text((1, 1), 'BPM', font=font, fill=col)
    frame, atlas = _record(draw)
    puts = [p for p in atlas.take_patches() if p[0] == 'put']
    assert len(puts) == 1
    inst = _instances(frame)
    assert (inst[:, 14] == gpu2d.KIND_IMAGE).all()
    assert inst[:, 4:7].tolist() == [[255, 0, 0], [0, 255, 0], [0, 0, 255]]


def test_atlas_reset_mid_frame_voids_the_frame_and_bumps_generation() -> None:
    atlas = gpu2d.TextureAtlas(64, 32)
    dl = gpu2d.DrawList(atlas)
    img = Image.new('RGBA', (40, 20), (255, 0, 0, 255))
    img2 = Image.new('RGBA', (40, 20), (0, 255, 0, 255))
    dl.begin(100, 100)
    dl.image(img, 0, 0)
    dl.image(img2, 0, 0)                 # does not fit beside img: resets
    assert atlas.generation == 1
    assert dl.finish() is None
    patches = atlas.take_patches()
    assert patches[0] == ('reset', 1)
    dl.begin(100, 100)
    dl.image(img2, 0, 0)
    assert dl.finish() is not None


def test_oversize_raster_is_skipped_not_raised() -> None:
    atlas = gpu2d.TextureAtlas(32, 32)
    dl = gpu2d.DrawList(atlas)
    dl.begin(10, 10)
    dl.image(Image.new('RGBA', (64, 8)), 0, 0)
    frame = dl.finish()
    assert frame is not None and frame.count == 0


def test_bulk_rects_match_single_calls() -> None:
    xs = np.array([1, 5]); ys = np.array([2, 2])
    rgba = np.array([[1, 2, 3, 255], [4, 5, 6, 255]], dtype=np.float32)
    bulk = _instances(_record(lambda d: d.rects(xs, ys, xs + 2, ys + 7, rgba))[0])

    def singles(d):
        d.rectangle([1, 2, 3, 9], fill=(1, 2, 3, 255))
        d.rectangle([5, 2, 7, 9], fill=(4, 5, 6, 255))
    assert np.array_equal(bulk, _instances(_record(singles)[0]))


def test_same_content_detects_unchanged_frames() -> None:
    draw = lambda d: d.rectangle([0, 0, 1, 1], fill=(1, 1, 1))  # noqa: E731
    a, _ = _record(draw)
    b, _ = _record(draw)
    c, _ = _record(lambda d: d.rectangle([0, 0, 2, 1], fill=(1, 1, 1)))
    assert a.same_content(b) and not a.same_content(c)


# -- real GL -----------------------------------------------------------------

@pytest.fixture(scope='module')
def gl():
    """An offscreen GL 3.3 core context, or skip."""
    sdl2 = pytest.importorskip('sdl2')
    prev = os.environ.get('SDL_VIDEODRIVER')
    os.environ['SDL_VIDEODRIVER'] = 'offscreen'
    try:
        if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO) != 0:
            pytest.skip(f'no offscreen SDL video: {sdl2.SDL_GetError().decode()}')
        for attr, val in ((sdl2.SDL_GL_CONTEXT_MAJOR_VERSION, 3),
                          (sdl2.SDL_GL_CONTEXT_MINOR_VERSION, 3),
                          (sdl2.SDL_GL_CONTEXT_PROFILE_MASK,
                           sdl2.SDL_GL_CONTEXT_PROFILE_CORE)):
            sdl2.SDL_GL_SetAttribute(attr, val)
        win = sdl2.SDL_CreateWindow(b'gpu2d-test', 0, 0, 160, 100,
                                    sdl2.SDL_WINDOW_OPENGL | sdl2.SDL_WINDOW_HIDDEN)
        ctx = sdl2.SDL_GL_CreateContext(win) if win else None
        if not ctx:
            if win:
                sdl2.SDL_DestroyWindow(win)
            sdl2.SDL_Quit()
            pytest.skip(f'no offscreen GL 3.3 context: {sdl2.SDL_GetError().decode()}')
        renderer = gpu2d.Batch2DRenderer()
        renderer.create(512, 256)
        yield renderer
        renderer.release()
        sdl2.SDL_GL_DeleteContext(ctx)
        sdl2.SDL_DestroyWindow(win)
        sdl2.SDL_Quit()
    finally:
        if prev is None:
            os.environ.pop('SDL_VIDEODRIVER', None)
        else:
            os.environ['SDL_VIDEODRIVER'] = prev


def _both(draw_fn, renderer, w=160, h=100):
    ref = Image.new('RGBA', (w, h), (12, 14, 22, 255))
    draw_fn(ImageDraw.Draw(ref, 'RGBA'))
    atlas = gpu2d.TextureAtlas(512, 256)
    dl = gpu2d.DrawList(atlas)
    dl.begin(w, h, clear=(12, 14, 22, 255))
    draw_fn(dl)
    frame = dl.finish()
    renderer._atlas_gen = -1          # fresh atlas per scene
    assert renderer.draw(frame, atlas.take_patches(), w, h)
    got = renderer.read_pixels(w, h)[..., :3].astype(int)
    return got, np.asarray(ref)[..., :3].astype(int)


def test_axis_aligned_shapes_and_text_are_pixel_exact(gl) -> None:
    font = ImageFont.truetype(str(_FONT_PATH), 13)

    def scene(d):
        d.rectangle([4, 4, 40, 20], fill=(200, 40, 40, 255))
        d.rectangle([48, 4, 90, 20], outline=(40, 200, 40, 255), width=2)
        d.rectangle([96, 4, 150, 20], fill=(30, 30, 90), outline=(250, 250, 0))
        d.rectangle([4, 26, 60, 40], fill=(255, 255, 255, 90))   # overwrite
        d.line([4, 46, 150, 46], fill=(255, 255, 255, 255))
        d.line([4, 50, 150, 50], fill=(0, 200, 255, 255), width=2)
        d.line([154, 4, 154, 90], fill=(255, 0, 200, 255), width=3)
        d.text((6, 56), 'DECK A 128.00', font=font, fill=(230, 230, 240, 255))
        d.polygon([(120, 60), (150, 75), (120, 90)], fill=(0, 255, 0, 255))
    got, ref = _both(scene, gl)
    assert np.array_equal(got, ref)


def test_curves_differ_only_by_edge_antialiasing(gl) -> None:
    def scene(d):
        d.ellipse([4, 4, 60, 50], fill=(0, 180, 200, 255))
        d.rounded_rectangle([70, 4, 150, 50], radius=8, fill=(90, 60, 160),
                            outline=(255, 255, 255), width=2)
        d.arc([10, 55, 50, 95], 0, 270, fill=(255, 0, 255), width=3)
        d.line([70, 60, 150, 95], fill=(255, 128, 0), width=3)
    got, ref = _both(scene, gl)
    differs = np.abs(got - ref).max(axis=2) > 8
    assert differs.mean() < 0.04
    # Interiors are exact: only pixels next to an edge may differ.
    assert np.array_equal(got[27, 32], ref[27, 32])
    assert np.array_equal(got[27, 110], ref[27, 110])
