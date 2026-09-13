"""VideoDeckLayer: the music-video-decks composite layer, tested without GL.

A fake frame source (the ``DeckVideoSource`` contract from videos-01) and a
fake moderngl context stand in for the real ones, so every behaviour the
core seat's ticket names is pinned here: open on first sight / close on
path change or clear, texture upload only when the pts changed, opacity =
audibility, skip below the threshold, a no-op layer when the source class
is None, and the postfx-ordering flag.
"""
from __future__ import annotations

import logging

import numpy as np
import pytest

from unicornviz.video_deck_layer import VideoDeckLayer, _MIN_OPACITY


# -- fakes ----------------------------------------------------------------

class FakeSource:
    """Mirrors DeckVideoSource's caller-facing API."""

    instances: list['FakeSource'] = []

    def __init__(self, path, *, cache_window_s=4.0, cache_long_edge=960):
        self.path = str(path)
        self.kwargs = {'cache_window_s': cache_window_s, 'cache_long_edge': cache_long_edge}
        self.size = (64, 36)
        self.targets: list[tuple[float, float, bool]] = []
        self.closed = False
        self.frames: list[tuple[float, np.ndarray]] = []
        self._stats = {'hits': 0, 'misses': 0, 'seeks': 0}
        FakeSource.instances.append(self)

    def set_target(self, t, rate, playing):
        self.targets.append((float(t), float(rate), bool(playing)))

    def frame_for(self, t):
        if not self.frames:
            return None
        return min(self.frames, key=lambda f: abs(f[0] - t))

    def close(self):
        self.closed = True

    def stats(self):
        return dict(self._stats)


class FailingSource(FakeSource):
    def __init__(self, path, **kw):
        raise RuntimeError('no video stream')


class OpenErrorSource(FakeSource):
    """videos-01 0.8.2: the constructor returns; the failure is a property."""

    def __init__(self, path, **kw):
        super().__init__(path, **kw)
        self.open_error = 'no video stream in container'


class FakeTexture:
    def __init__(self, size):
        self.size = size
        self.writes = 0
        self.released = False
        self.filter = None

    def write(self, data):
        self.writes += 1

    def use(self, location=0):
        pass

    def release(self):
        self.released = True


class _Uniform:
    def __init__(self):
        self.value = None


class FakeProgram:
    def __init__(self):
        self.u = {'uScale': _Uniform(), 'uOpacity': _Uniform(), 'tex': _Uniform()}

    def __getitem__(self, k):
        return self.u[k]

    def release(self):
        pass


class FakeVao:
    def __init__(self):
        self.renders = 0

    def render(self, mode):
        self.renders += 1

    def release(self):
        pass


class FakeCtx:
    def __init__(self):
        self.textures: list[FakeTexture] = []
        self.enabled: list = []
        self.blend_func = None
        self.vao = FakeVao()
        self.prog = FakeProgram()

    def texture(self, size, components):
        t = FakeTexture(size)
        self.textures.append(t)
        return t

    def program(self, vertex_shader, fragment_shader):
        return self.prog

    def buffer(self, data):
        return type('B', (), {'release': lambda self: None})()

    def vertex_array(self, prog, content):
        return self.vao

    def enable(self, flag):
        self.enabled.append(('on', flag))

    def disable(self, flag):
        self.enabled.append(('off', flag))


@pytest.fixture(autouse=True)
def _no_real_moderngl(monkeypatch):
    """The layer resolves moderngl constants lazily; give it ints."""
    monkeypatch.setattr(VideoDeckLayer, '_blend_flag', staticmethod(lambda: 1))
    monkeypatch.setattr(VideoDeckLayer, '_blend_func', staticmethod(lambda: (2, 3)))
    monkeypatch.setattr(VideoDeckLayer, '_triangle_strip', staticmethod(lambda: 4))
    monkeypatch.setattr(VideoDeckLayer, '_linear', staticmethod(lambda: 5))
    FakeSource.instances.clear()
    yield


def _frame(v: int = 0) -> np.ndarray:
    return np.full((36, 64, 3), v, dtype=np.uint8)


def _state(**decks) -> dict:
    return {'decks': decks}


def _deck(path='/music/a.mp4', *, has_video=True, position=1.0, rate=1.0,
          playing=True, audibility=0.8) -> dict:
    return {'path': path, 'has_video': has_video, 'position_s': position,
            'rate': rate, 'playing': playing, 'audibility': audibility}


def _layer(**kw) -> VideoDeckLayer:
    return VideoDeckLayer(FakeCtx(), FakeSource, **kw)


# -- lifecycle -------------------------------------------------------------

def test_opens_on_first_sight_with_the_configured_cache(caplog):
    layer = _layer(cache_window_s=4.0, cache_long_edge=720)
    with caplog.at_level(logging.INFO, logger='unicornviz.video_deck_layer'):
        layer.update(_state(a=_deck()))
    assert len(FakeSource.instances) == 1
    src = FakeSource.instances[0]
    assert src.path == '/music/a.mp4'
    assert src.kwargs == {'cache_window_s': 4.0, 'cache_long_edge': 720}
    assert 'opened /music/a.mp4 (64x36)' in caplog.text


def test_closes_when_the_path_changes_and_opens_the_new_one(caplog):
    layer = _layer()
    layer.update(_state(a=_deck('/music/a.mp4')))
    with caplog.at_level(logging.INFO, logger='unicornviz.video_deck_layer'):
        layer.update(_state(a=_deck('/music/b.mp4')))
    first, second = FakeSource.instances
    assert first.closed and not second.closed
    assert 'closed /music/a.mp4' in caplog.text and 'path changed' in caplog.text


def test_closes_when_the_deck_clears_or_loses_video():
    layer = _layer()
    layer.update(_state(a=_deck()))
    layer.update(_state(a=_deck(has_video=False)))
    assert FakeSource.instances[0].closed
    layer.update(_state(a=_deck('/music/c.mp4')))
    layer.update(_state())                                   # deck gone entirely
    assert FakeSource.instances[1].closed
    assert layer.active is False


def test_at_most_two_sources_are_open(caplog):
    layer = _layer()
    with caplog.at_level(logging.INFO, logger='unicornviz.video_deck_layer'):
        layer.update(_state(a=_deck('/1.mp4'), b=_deck('/2.mp4'), c=_deck('/3.mp4')))
    assert len(FakeSource.instances) == 2
    assert 'will not get one' in caplog.text


def test_a_source_that_fails_to_open_leaves_the_deck_as_no_video(caplog):
    layer = VideoDeckLayer(FakeCtx(), FailingSource)
    with caplog.at_level(logging.WARNING, logger='unicornviz.video_deck_layer'):
        layer.update(_state(a=_deck()))
    assert 'could not open' in caplog.text
    assert layer.active is False and layer.layer_opacity == 0.0


def test_set_target_receives_position_rate_and_playing():
    layer = _layer()
    layer.update(_state(a=_deck(position=12.5, rate=-1.5, playing=False)))
    assert FakeSource.instances[0].targets == [(12.5, -1.5, False)]


# -- texture upload ----------------------------------------------------------

def test_uploads_only_when_the_pts_changes():
    layer = _layer()
    ctx = layer._ctx
    layer.update(_state(a=_deck()))
    src = FakeSource.instances[0]
    src.frames = [(1.0, _frame(10))]
    layer.update(_state(a=_deck()))                          # first frame -> upload
    layer.update(_state(a=_deck()))                          # same pts   -> no upload
    layer.update(_state(a=_deck()))
    assert len(ctx.textures) == 1 and ctx.textures[0].writes == 1
    src.frames = [(2.0, _frame(20))]
    layer.update(_state(a=_deck()))                          # new pts    -> upload
    assert ctx.textures[0].writes == 2
    assert ctx.textures[0].size == (64, 36)


def test_texture_is_rebuilt_when_the_frame_size_changes():
    layer = _layer()
    ctx = layer._ctx
    layer.update(_state(a=_deck()))
    src = FakeSource.instances[0]
    src.frames = [(1.0, _frame())]
    layer.update(_state(a=_deck()))
    src.frames = [(2.0, np.zeros((72, 128, 3), dtype=np.uint8))]
    layer.update(_state(a=_deck()))
    assert ctx.textures[0].released and ctx.textures[1].size == (128, 72)


def test_no_frame_yet_means_not_visible():
    layer = _layer()
    layer.update(_state(a=_deck(audibility=1.0)))            # source open, ring empty
    assert layer.active is False and layer.status_pill() is None


# -- opacity and draw --------------------------------------------------------

def _visible_layer(audibility=0.82, **extra):
    layer = _layer(**extra)
    layer.update(_state(a=_deck(audibility=audibility)))
    FakeSource.instances[0].frames = [(1.0, _frame())]
    layer.update(_state(a=_deck(audibility=audibility)))
    return layer


def test_opacity_is_the_decks_audibility_and_feeds_the_pill():
    layer = _visible_layer(0.82)
    assert layer.active and abs(layer.layer_opacity - 0.82) < 1e-9
    assert layer.status_pill() == 'VIDEO A 82%'


def test_draw_is_skipped_below_the_opacity_threshold():
    layer = _visible_layer(_MIN_OPACITY / 2.0)
    ctx = layer._ctx
    layer.draw(1920, 1080)
    assert ctx.vao.renders == 0 and layer.active is False
    assert layer.layer_opacity == 0.0 and layer.status_pill() is None


def test_draw_letterboxes_blends_and_restores_state():
    layer = _visible_layer(0.5)
    ctx = layer._ctx
    layer.draw(1920, 1080)                                   # 16:9 frame on 16:9 target
    assert ctx.vao.renders == 1
    sx, sy = ctx.prog['uScale'].value
    assert abs(sx - 1.0) < 1e-6 and abs(sy - 1.0) < 1e-6
    assert ctx.prog['uOpacity'].value == 0.5
    assert ctx.enabled == [('on', 1), ('off', 1)] and ctx.blend_func == (2, 3)
    layer.draw(1080, 1080)                                   # square target: pillar/letterbox
    sx, sy = ctx.prog['uScale'].value
    assert abs(sx - 1.0) < 1e-6 and abs(sy - 36 / 64) < 1e-6


def test_two_decks_draw_in_a_b_order_with_their_own_opacity():
    layer = _layer()
    st = _state(a=_deck('/a.mp4', audibility=0.3), b=_deck('/b.mp4', audibility=0.9))
    layer.update(st)
    for src in FakeSource.instances:
        src.frames = [(1.0, _frame())]
    layer.update(st)
    seen: list[float] = []
    orig = layer._ctx.vao.render
    layer._ctx.vao.render = lambda mode: (seen.append(layer._ctx.prog['uOpacity'].value), orig(mode))
    layer.draw(1920, 1080)
    assert seen == [0.3, 0.9]
    assert layer.status_pill() == 'VIDEO A 30%  B 90%'
    assert abs(layer.layer_opacity - 0.9) < 1e-9


# -- no-op and flags ---------------------------------------------------------

def test_layer_is_a_no_op_when_the_source_class_is_none():
    ctx = FakeCtx()
    layer = VideoDeckLayer(ctx, None)
    assert layer.enabled is False
    layer.update(_state(a=_deck(audibility=1.0)))
    layer.draw(1920, 1080)
    assert ctx.textures == [] and ctx.vao.renders == 0
    assert layer.active is False and layer.layer_opacity == 0.0
    assert layer.status_pill() is None and layer.last_frame_ms == 0.0


def test_disabled_by_config_is_also_a_no_op():
    layer = _layer(enabled=False)
    layer.update(_state(a=_deck()))
    assert FakeSource.instances == []


def test_postfx_ordering_flag_round_trips():
    assert _layer().postfx_over_video is True
    layer = _layer(postfx_over_video=False)
    assert layer.postfx_over_video is False
    layer.postfx_over_video = True
    assert layer.postfx_over_video is True


def test_accepts_list_shaped_and_top_level_deck_records():
    layer = _layer()
    layer.update({'decks': [dict(deck='b', **_deck('/list.mp4'))]})
    assert FakeSource.instances[-1].path == '/list.mp4'
    layer.update({'a': _deck('/top.mp4'), 'b': _deck('/list.mp4')})
    assert FakeSource.instances[-1].path == '/top.mp4'


def test_destroy_closes_sources_and_releases_textures():
    layer = _visible_layer()
    layer.destroy()
    assert FakeSource.instances[0].closed
    assert layer._ctx.textures[0].released
    layer.destroy()                                          # idempotent


def test_debug_log_carries_opacity_pts_and_cache_stats(caplog, monkeypatch):
    layer = _visible_layer(0.82, log_interval_s=0.2)
    FakeSource.instances[0]._stats = {'hits': 7, 'misses': 2, 'seeks': 1}
    layer._next_log_t = 0.0
    with caplog.at_level(logging.DEBUG, logger='unicornviz.video_deck_layer'):
        layer.update(_state(a=_deck(audibility=0.82)))
    line = next(r.getMessage() for r in caplog.records if 'Video decks: A' in r.getMessage())
    assert 'op=0.82' in line and 'pts=1.000' in line and 'hit=7 miss=2 seek=1' in line


def test_output_latency_shifts_the_frame_to_the_audible_instant():
    """The mixer publishes its write cursor; the ear hears it latency_s later.
    With latency_s in the payload the layer targets position - latency."""
    layer = _layer()
    rec = _deck(position=10.0)
    rec['latency_s'] = 0.256
    layer.update(_state(a=rec))
    assert FakeSource.instances[0].targets == [(10.0 - 0.256, 1.0, True)]
    rec2 = _deck(position=10.0)                               # no latency field: unchanged
    layer.update(_state(a=rec2))
    assert FakeSource.instances[0].targets[-1] == (10.0, 1.0, True)


def test_trace_file_gets_one_line_per_visible_deck_frame(tmp_path, monkeypatch):
    trace = tmp_path / 'trace.jsonl'
    monkeypatch.setenv('UNICORNVIZ_VIDEO_DECKS_TRACE', str(trace))
    layer = _layer()
    layer.update(_state(a=_deck(position=1.0)))
    FakeSource.instances[0].frames = [(1.0, _frame())]
    layer.update(_state(a=_deck(position=1.0)))
    layer.destroy()
    import json
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    assert rows and rows[-1]['deck'] == 'a' and rows[-1]['pts'] == 1.0
    assert rows[-1]['upload_ms'] >= 0.0 and rows[-1]['position_s'] == 1.0


def test_open_error_closes_the_source_once_and_does_not_retry(caplog):
    layer = VideoDeckLayer(FakeCtx(), OpenErrorSource)
    with caplog.at_level(logging.WARNING, logger='unicornviz.video_deck_layer'):
        layer.update(_state(a=_deck('/bad.mp4', audibility=1.0)))
        layer.update(_state(a=_deck('/bad.mp4', audibility=1.0)))
        layer.update(_state(a=_deck('/bad.mp4', audibility=1.0)))
    assert len(FakeSource.instances) == 1                    # opened once, not per frame
    assert FakeSource.instances[0].closed
    assert sum('could not open /bad.mp4' in r.getMessage() for r in caplog.records) == 1
    assert layer.active is False and layer.layer_opacity == 0.0
    layer.update(_state(a=_deck('/good.mp4')))               # a new path is tried again
    assert len(FakeSource.instances) == 2


def test_first_frame_logs_the_real_size(caplog):
    layer = _layer()
    layer.update(_state(a=_deck()))
    FakeSource.instances[0].frames = [(1.0, np.zeros((36, 64, 3), dtype=np.uint8))]
    with caplog.at_level(logging.INFO, logger='unicornviz.video_deck_layer'):
        layer.update(_state(a=_deck()))
        layer.update(_state(a=_deck()))
    assert sum('first frame 64x36' in r.getMessage() for r in caplog.records) == 1
