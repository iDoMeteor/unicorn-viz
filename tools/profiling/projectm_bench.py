"""Time libprojectM's per-frame calls the way projectm-01 drives them.

Creates a hidden SDL window with a GL 3.3 core context, loads the drop-in's
``_ProjectMBridge`` and a real preset, then times each call the effect makes
per frame in isolation.  The 2026-09-12 finding this exists to guard: the
effect's per-frame ``configure()`` re-sent the texture search paths on every
frame and cost about 72 ms a call on an Iris Xe, versus 0.01 ms without them,
while the actual 1080p render was under 5 ms.  projectm-01 0.12.7 diffs
``configure()`` against the last-applied values, so a healthy bridge now
reports it near 0 ms; a regression shows up as tens of milliseconds again.

Run from the repo root (needs a display; the window is never shown)::

    .venv/bin/python tools/profiling/projectm_bench.py
    .venv/bin/python tools/profiling/projectm_bench.py --preset "Blood In Me" --size 1920x1080 --n 60

``--preset`` is a substring match against the preset filename; ``! Transition``
presets are skipped.  Texture directories come from ``[effects.ProjectMEffect] texture_dirs``
in config.toml unless ``--texture-dir`` is given.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import os
import statistics
import sys
import time
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import sdl2

ROOT = Path(__file__).resolve().parents[2]
EFFECT_MODULE = ROOT / 'drop-ins' / 'projectm-01' / 'projectm_effect.py'
PRESET_ROOT = ROOT / 'drop-ins' / 'projectm-01' / 'presets'


def _load_effect_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        'unicornviz_dropins_projectm_01.projectm_effect', EFFECT_MODULE)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot load {EFFECT_MODULE}')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _texture_dirs_from_config() -> list[str]:
    cfg = ROOT / 'config.toml'
    if not cfg.is_file():
        return []
    with cfg.open('rb') as fh:
        data = tomllib.load(fh)
    # The effect reads its keys from [effects.ProjectMEffect] (BaseEffect
    # config); an older [projectm] table is honored as a fallback.
    section = data.get('effects', {}).get('ProjectMEffect') or data.get('projectm', {})
    raw = section.get('texture_dirs', [])
    if isinstance(raw, str):
        raw = [t for t in raw.split(',')]
    return [str(t).strip() for t in raw if str(t).strip()]


def _pick_preset(needle: str) -> Path:
    cands = [p for p in PRESET_ROOT.rglob('*.milk') if 'transition' not in p.parent.name.lower()]
    if not cands:
        raise SystemExit(f'no presets under {PRESET_ROOT}')
    hits = [p for p in cands if needle.lower() in p.name.lower()] if needle else cands
    return sorted(hits or cands)[0]


def _gl_proc(name: bytes, restype: Any, *argtypes: Any) -> Callable[..., Any]:
    ptr = sdl2.SDL_GL_GetProcAddress(name)
    if not ptr:
        raise RuntimeError(f'{name.decode()} unavailable in this GL context')
    return ctypes.CFUNCTYPE(restype, *argtypes)(ctypes.cast(ptr, ctypes.c_void_p).value)


def _bench(label: str, fn: Callable[[int], Any], n: int) -> None:
    xs: list[float] = []
    for i in range(n):
        t = time.perf_counter()
        fn(i)
        xs.append((time.perf_counter() - t) * 1000)
    print(f'{label:60s} median {statistics.median(xs):7.2f} ms   '
          f'p90 {sorted(xs)[int(0.9 * n)]:7.2f} ms   max {max(xs):7.2f} ms')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--preset', default='', help='substring of a preset filename')
    parser.add_argument('--size', default='1920x1080', help='render size WxH')
    parser.add_argument('--n', type=int, default=40, help='iterations per measurement')
    parser.add_argument('--texture-dir', action='append', default=None,
                        help='texture search dir (repeatable; default: config.toml)')
    args = parser.parse_args(argv)
    width, height = (int(v) for v in args.size.lower().split('x'))
    tex = args.texture_dir if args.texture_dir is not None else _texture_dirs_from_config()

    if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO) != 0:
        print('SDL_Init failed:', sdl2.SDL_GetError(), file=sys.stderr)
        return 1
    sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MAJOR_VERSION, 3)
    sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MINOR_VERSION, 3)
    sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_PROFILE_MASK, sdl2.SDL_GL_CONTEXT_PROFILE_CORE)
    win = sdl2.SDL_CreateWindow(b'projectm-bench', 0, 0, width, height,
                                sdl2.SDL_WINDOW_OPENGL | sdl2.SDL_WINDOW_HIDDEN)
    if not win or not sdl2.SDL_GL_CreateContext(win):
        print('GL window/context failed:', sdl2.SDL_GetError(), file=sys.stderr)
        return 1
    sdl2.SDL_GL_SetSwapInterval(0)
    print(f'video driver: {sdl2.SDL_GetCurrentVideoDriver().decode()}  size: {width}x{height}')

    mod = _load_effect_module()
    gl_finish = _gl_proc(b'glFinish', None)
    bridge = mod._ProjectMBridge('')  # noqa: SLF001 -- benchmarking the drop-in's own bridge
    bridge.configure(width, height, 60, 1.0, 20.0, False, False, tex)
    preset = _pick_preset(args.preset)
    print(f'preset: {preset.name}')
    print(f'texture_dirs: {tex or "(none)"}')
    bridge.load_preset(str(preset), False)
    pcm = (np.random.default_rng(0).standard_normal(1024) * 0.1).astype(np.float32)
    t0 = 1000.0

    def frame(i: int) -> None:
        bridge.set_timing(t0 + i / 60.0, 60)
        bridge.add_pcm(pcm)
        bridge.render()

    for i in range(30):
        frame(i)
    gl_finish()

    n = args.n
    _bench('configure() every frame, same args, WITH texture_dirs',
           lambda i: bridge.configure(width, height, 60, 1.0, 20.0, False, False, tex), n)
    _bench('configure() every frame, same args, WITHOUT texture_dirs',
           lambda i: bridge.configure(width, height, 60, 1.0, 20.0, False, False, []), n)
    _bench('set_window_size() same size only', lambda i: bridge.set_window_size(width, height), n)
    _bench('set_timing() + add_pcm() only',
           lambda i: (bridge.set_timing(t0 + i / 60.0, 60), bridge.add_pcm(pcm)), n)
    _bench('render() (no sync)', lambda i: bridge.render(), n)

    def render_sync(i: int) -> None:
        bridge.render()
        gl_finish()
    _bench('render() + glFinish (GPU time per frame)', render_sync, n)

    glrp = mod._get_glReadPixels()  # noqa: SLF001
    buf = ctypes.create_string_buffer(48 * 48 * 3)
    points = getattr(mod.ProjectMEffect, '_COLOR_SAMPLE_POINTS',
                     ((0.5, 0.5), (0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)))

    def readback(i: int) -> None:
        bridge.render()
        for fx, fy in points:
            glrp(int(width * fx) - 24, int(height * fy) - 24, 48, 48,
                 mod._GL_RGB, mod._GL_UNSIGNED_BYTE, buf)  # noqa: SLF001
    _bench('render() + solid-color glReadPixels blocks', readback, n)

    def full(i: int) -> None:
        bridge.set_timing(t0 + i / 60.0, 60)
        bridge.add_pcm(pcm)
        bridge.configure(width, height, 60, 1.0, 20.0, False, False, tex)
        bridge.render()
        gl_finish()
    _bench('FULL per-frame path (timing+pcm+configure+render+finish)', full, n)

    def full_noconf(i: int) -> None:
        frame(i)
        gl_finish()
    _bench('per-frame path without configure() (timing+pcm+render+finish)', full_noconf, n)

    other = _pick_preset('')
    t = time.perf_counter()
    bridge.load_preset(str(other), True)
    frame(0)
    gl_finish()
    print(f'load_preset (smooth) + first frame: {(time.perf_counter() - t) * 1000:.0f} ms '
          f'[{other.name[:50]}]')
    bridge.destroy()
    sdl2.SDL_Quit()
    return 0


if __name__ == '__main__':
    os.environ.setdefault('PYSDL2_DLL_PATH', '')
    raise SystemExit(main())
