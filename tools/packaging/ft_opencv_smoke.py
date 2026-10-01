"""Smoke test for the free-threaded opencv-python-headless wheel.

Run it with the interpreter the wheel was installed into (see
``build_ft_opencv_wheel.sh --verify-python``).  It exercises the paths this
project actually uses, not just ``import cv2``:

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

It also *reports* what importing cv2 does to the GIL.  That is information, not
a failure: OpenCV's bindings do not declare ``Py_mod_gil`` support, so the GIL
is expected to come back on.  Test clips are generated with the system
``ffmpeg`` (test data only; the wheel's own FFmpeg is the one under test).

    python tools/packaging/ft_opencv_smoke.py [--clips DIR]
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

W, H, FRAMES, FPS = 160, 120, 20, 10
#: Vendored libraries that would mean a GPL or non-free FFmpeg build.
FORBIDDEN_LIBS = ('libx264', 'libx265', 'libfdk', 'libxvid', 'libpostproc', 'libswresample-gpl')


def _gil_after_import() -> str:
    proc = subprocess.run(
        [sys.executable, '-W', 'ignore', '-c',
         'import sys, cv2; print(sys._is_gil_enabled())'],
        capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return f'IMPORT FAILED: {proc.stderr.strip().splitlines()[-1] if proc.stderr else "?"}'
    return 'ON (module did not declare Py_mod_gil)' if proc.stdout.strip() == 'True' else 'off'


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
        for i in range(FRAMES):
            frame = np.full((H, W, 3), (i * 12) % 255, np.uint8)
            frame[:, : (i * 8) % W] = (30, 160, 220)
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
    print(f'  GIL after a fresh `import cv2`: {_gil_after_import()}')

    info = cv2.getBuildInformation()
    expect = [(r'^\s*FFMPEG:\s+YES', 'an FFmpeg backend'),
              (r'^\s*GUI:\s+NONE', 'a headless build (no GUI backend)'),
              (r'^\s*Limited API:\s+NO', 'a full-API build (the stable ABI cannot be a cp314t build)')]
    if sys.platform.startswith('linux'):
        expect.append((r'^\s*v4l/v4l2:\s+YES', 'the V4L2 camera backend'))   # webcam-01
    for pattern, why in expect:
        if not re.search(pattern, info, re.M | re.I):
            problems.append(f'build info does not show {why}')

    if '--clips' in argv:
        clip_dir = Path(argv[argv.index('--clips') + 1])
        clips = {p.name: p for p in clip_dir.iterdir() if p.suffix in ('.mp4', '.webm')}
        tmp = None
    else:
        tmp = tempfile.TemporaryDirectory()
        clips = _make_clips(Path(tmp.name), cv2)
    for name, path in sorted(clips.items()):
        issues = _check_clip(cv2, path)
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
