"""Smoke test for the patched free-threaded opencv-python-headless wheel.

Adapted from UnicornViz's ``tools/packaging/ft_opencv_smoke.py`` (same owner).
Run it with the interpreter the wheel was installed into.  It exercises the
paths that project actually uses, not just ``import cv2``:

* the build is the free-threaded, headless, FFmpeg- and V4L-enabled one (not a
  limited-API build, no GUI backend);
* ``cv2.VideoCapture`` opens and decodes a real H.264 ``.mp4`` and a VP9
  ``.webm`` (video-clips-01), including the seek-by-frame-index it does when a
  clip loops, and reports sane metadata;
* the image operations webcam-01 uses work on numpy arrays;
* two threads decode independently at the same time;
* the FFmpeg libraries vendored into the wheel report an **LGPL** license and
  none of the GPL / non-free codec libraries is bundled (the wheel is
  redistributed, so this is checked on the actual files, not assumed).

It also **enforces** that importing cv2 leaves the GIL off: the patched module
declares ``Py_MOD_GIL_NOT_USED`` (upstream's smoke test only reported it).  The
checked-in fixtures are the test clips (the wheel's own FFmpeg is under test).

    python smoke/ft_opencv_smoke.py [--clips DIR] [--no-fixtures]
"""
from __future__ import annotations

import ctypes
import glob
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from gilcheck import env_forces_gil, gil_after_import

W, H, FRAMES, FPS = 160, 120, 20, 10
#: Checked-in tiny H.264 and VP9 clips (see ft-fixtures/README.md).  Frame N has a bright
#: bar whose centre is at x = BAR_STEP * N + BAR_WIDTH // 2, so the frame is identifiable.
FIXTURE_DIR = Path(__file__).resolve().parent / 'ft-fixtures'
FIXTURE_NAMES = ('h264.mp4', 'vp9.webm')
BAR_STEP, BAR_WIDTH, BAR_TOLERANCE_PX = 7, 16, 4.0
#: Vendored libraries that would mean a GPL or non-free FFmpeg build.
FORBIDDEN_LIBS = ('libx264', 'libx265', 'libfdk', 'libxvid', 'libpostproc', 'libswresample-gpl')


def _make_clips_with_cv2(cv2, dest: Path) -> dict[str, Path]:
    """No system ffmpeg (e.g. a Windows CI runner): write clips with cv2 itself.
    MPEG-4 part 2 and MJPEG are what the LGPL FFmpeg can encode; this does not
    cover H.264 or VP9 decode, so the result is reported as a weaker check."""
    import numpy as np
    out: dict[str, Path] = {}
    for name, fourcc in (('mpeg4.mp4', 'mp4v'), ('mjpg.avi', 'MJPG')):
        path = dest / name
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc), FPS, (W, H))
        if not writer.isOpened():
            continue
        # Every frame has real content (a gradient plus a moving bar), including the
        # first: an all-black frame 0 read back as "blank" and failed the first run.
        gradient = np.tile(np.linspace(20, 235, W, dtype=np.uint8), (H, 1))
        for i in range(FRAMES):
            frame = np.stack([gradient, gradient[::-1], np.full((H, W), 90, np.uint8)], axis=2)
            frame[:, (i * 8) % W: (i * 8) % W + 16] = (30, 160, 220)
            writer.write(frame)
        writer.release()
        out[name] = path
    print('  (no system ffmpeg: clips written with cv2; H.264 and VP9 decode NOT exercised)')
    return out


def _make_clips(dest: Path, cv2=None) -> dict[str, Path]:
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg is None:
        if cv2 is None:
            raise SystemExit('no system ffmpeg to generate test clips; pass --clips DIR')
        return _make_clips_with_cv2(cv2, dest)
    src = f'testsrc=size={W}x{H}:rate={FPS}:duration={FRAMES // FPS}'
    clips = {'h264.mp4': ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '5'],
             'vp9.webm': ['-c:v', 'libvpx-vp9', '-pix_fmt', 'yuv420p', '-b:v', '200k']}
    out: dict[str, Path] = {}
    for name, codec in clips.items():
        path = dest / name
        subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', src, *codec, str(path)],
                       check=True)
        out[name] = path
    return out


def _check_clip(cv2, path: Path) -> list[str]:
    problems: list[str] = []
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return [f'{path.name}: VideoCapture could not open it']
    meta = (cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
            cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if (int(meta[0]), int(meta[1])) != (W, H) or abs(meta[2] - FPS) > 0.5:
        problems.append(f'{path.name}: bad metadata {meta}')
    got = 0
    first = None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if first is None:
            first = frame.copy()
        got += 1
    if got != FRAMES:
        problems.append(f'{path.name}: decoded {got} frames, expected {FRAMES}')
    if first is None or first.shape != (H, W, 3) or int(first.std()) < 5:
        problems.append(f'{path.name}: first frame is wrong or blank')
    # What video-clips-01 does when a clip loops: seek back and read again.
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    ok, again = cap.read()
    if not ok or first is None or abs(float(again.mean()) - float(first.mean())) > 8.0:
        problems.append(f'{path.name}: seek to frame 0 did not return the first frame')
    cap.set(cv2.CAP_PROP_POS_FRAMES, FRAMES // 2)
    ok, mid = cap.read()
    if not ok or mid.shape != (H, W, 3):
        problems.append(f'{path.name}: seek to the middle failed')
    cap.release()
    return problems


def _bar_centre(frame) -> float:
    """Centre column of the bright bar in a decoded fixture frame (nan if there is none)."""
    import numpy as np
    col = frame.astype(np.float32).mean(axis=(0, 2))            # mean brightness per column
    weight = np.clip(col - (col.max() + col.min()) / 2, 0, None)  # only the bar's columns
    total = float(weight.sum())
    return float((weight * np.arange(len(weight))).sum() / total) if total > 0 else float('nan')


def _check_fixture(cv2, path: Path) -> list[str]:
    """Decode a checked-in fixture and assert what a correct decoder must produce: all
    20 frames, 160x120, each non-blank with its bar at the position that frame number
    encodes (so frames are neither dropped nor reordered), and the same after seeking
    by frame index, which is what video-clips-01 does when a clip loops."""
    problems: list[str] = []
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return [f'{path.name}: VideoCapture could not open it']

    def expected(n: int) -> float:
        return BAR_STEP * n + BAR_WIDTH // 2

    frames = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame.shape != (H, W, 3):
            problems.append(f'{path.name}: frame {frames} has shape {frame.shape}')
        elif float(frame.std()) < 5:
            problems.append(f'{path.name}: frame {frames} is blank')
        else:
            err = abs(_bar_centre(frame) - expected(frames))
            if not err <= BAR_TOLERANCE_PX:
                problems.append(f'{path.name}: frame {frames}: bar is {err:.1f} px from where it should be')
        frames += 1
    if frames != FRAMES:
        problems.append(f'{path.name}: decoded {frames} frames, expected {FRAMES}')
    for target in (0, 10, FRAMES - 1, 5):
        cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        ok, frame = cap.read()
        if not ok:
            problems.append(f'{path.name}: seek to frame {target} returned nothing')
        elif not abs(_bar_centre(frame) - expected(target)) <= BAR_TOLERANCE_PX:
            problems.append(f'{path.name}: seek to frame {target} landed on the wrong frame (bar at '
                            f'{_bar_centre(frame):.0f}, expected {expected(target)})')
    cap.release()
    return problems


def _check_imageops(cv2) -> list[str]:
    import numpy as np
    img = np.random.default_rng(1).integers(0, 255, (H, W, 3), dtype=np.uint8)
    out = cv2.GaussianBlur(img, (0, 0), 3)
    out = cv2.flip(out, 1)
    out = cv2.dilate(out, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    out = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
    return [] if out.shape == img.shape and out.dtype == np.uint8 else ['image ops returned wrong shape']


def _check_threads(cv2, path: Path) -> list[str]:
    counts: list[int] = []

    def work() -> None:
        cap = cv2.VideoCapture(str(path))
        n = 0
        while cap.read()[0]:
            n += 1
        cap.release()
        counts.append(n)

    threads = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return [] if counts == [FRAMES] * 4 else [f'threaded decode gave {counts}']


def _check_license(cv2) -> list[str]:
    """Linux wheels bundle an FFmpeg built by build_ft_opencv_wheel.sh: ask the
    libraries themselves.  Windows wheels use OpenCV's own pre-built, documented-
    LGPL ``opencv_videoio_ffmpeg*.dll`` plugin (its CMake downloads it by hash),
    which exports only OpenCV's plugin API, so there the check is that the plugin
    is present and that no GPL/non-free library is bundled."""
    problems: list[str] = []
    pkg = Path(cv2.__file__).resolve().parent
    if sys.platform == 'win32':
        plugins = sorted(p.name for p in pkg.glob('opencv_videoio_ffmpeg*.dll'))
        print('  bundled FFmpeg plugin:', ', '.join(plugins) or '(none)')
        if not plugins:
            problems.append('opencv_videoio_ffmpeg*.dll is not in the wheel (no FFmpeg backend)')
        bad = [p.name for p in pkg.rglob('*.dll') if p.name.lower().startswith(FORBIDDEN_LIBS)]
        if bad:
            problems.append(f'GPL/non-free libraries bundled: {bad}')
        return problems
    libdir = pkg.parent / 'opencv_python_headless.libs'
    bundled = sorted(p.name for p in libdir.glob('*.so*')) if libdir.is_dir() else []
    print('  vendored libs:', ', '.join(bundled) or '(none)')
    bad = [n for n in bundled if n.startswith(FORBIDDEN_LIBS)]
    if bad:
        problems.append(f'GPL/non-free libraries bundled: {bad}')
    for stem, func in (('libavutil', 'avutil_license'), ('libavcodec', 'avcodec_license'),
                       ('libavformat', 'avformat_license')):
        hits = glob.glob(str(libdir / f'{stem}-*.so*')) or glob.glob(str(libdir / f'{stem}*.so*'))
        if not hits:
            problems.append(f'{stem} is not bundled (no FFmpeg backend in the wheel?)')
            continue
        fn = getattr(ctypes.CDLL(hits[0]), func)
        fn.restype = ctypes.c_char_p
        lic = fn().decode()
        print(f'  {func}(): {lic}')
        if not lic.startswith('LGPL'):
            problems.append(f'{stem} reports license {lic!r}, not LGPL')
    return problems


def main(argv: list[str]) -> int:
    import cv2
    problems: list[str] = []
    gil_off = hasattr(sys, '_is_gil_enabled') and not sys._is_gil_enabled()
    print(f'python {sys.version.split()[0]}  GIL now: {"off" if gil_off else "ON (cv2 imported)"}')
    print(f'cv2 {cv2.__version__}  ({cv2.__file__})')
    ok, state = gil_after_import('cv2')
    print(f'  GIL after a fresh `import cv2`: {state}')
    if not ok:
        problems.append(f'importing cv2 leaves the GIL {state}')
    if not gil_off:
        problems.append('the GIL is enabled in this process after importing cv2')
    if env_forces_gil():
        problems.append('PYTHON_GIL is set in the environment: the GIL state is forced')

    info = cv2.getBuildInformation()
    expect = [(r'^\s*FFMPEG:\s+YES', 'an FFmpeg backend'),
              (r'^\s*GUI:\s+NONE', 'a headless build (no GUI backend)'),
              (r'^\s*Limited API:\s+NO', 'a full-API build (the stable ABI cannot be a cp314t build)')]
    if sys.platform.startswith('linux'):
        expect.append((r'^\s*v4l/v4l2:\s+YES', 'the V4L2 camera backend'))   # webcam-01
    for pattern, why in expect:
        if not re.search(pattern, info, re.M | re.I):
            problems.append(f'build info does not show {why}')

    fixtures = False
    if '--clips' in argv:
        clip_dir = Path(argv[argv.index('--clips') + 1])
        clips = {p.name: p for p in clip_dir.iterdir() if p.suffix in ('.mp4', '.webm')}
        tmp = None
    elif '--no-fixtures' not in argv and all((FIXTURE_DIR / n).is_file() for n in FIXTURE_NAMES):
        clips = {n: FIXTURE_DIR / n for n in FIXTURE_NAMES}      # the same clips on every platform
        fixtures = True
        tmp = None
        print('  (using the checked-in fixtures: H.264 and VP9 decode exercised on this platform)')
    else:
        tmp = tempfile.TemporaryDirectory()
        clips = _make_clips(Path(tmp.name), cv2)
    for name, path in sorted(clips.items()):
        issues = _check_fixture(cv2, path) if fixtures else _check_clip(cv2, path)
        print(f'  {name}: {"ok" if not issues else "; ".join(issues)}')
        problems += issues
    problems += _check_imageops(cv2)
    print('  image ops (blur, flip, dilate, cvtColor): ' + ('ok' if not _check_imageops(cv2) else 'FAILED'))
    if clips:
        issues = _check_threads(cv2, next(iter(clips.values())))
        print(f'  4 threads decoding at once: {"ok" if not issues else "; ".join(issues)}')
        problems += issues
    print('license of the bundled FFmpeg:')
    problems += _check_license(cv2)
    if tmp is not None:
        tmp.cleanup()

    print('FAILED: ' + '; '.join(problems) if problems else 'OK')
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
