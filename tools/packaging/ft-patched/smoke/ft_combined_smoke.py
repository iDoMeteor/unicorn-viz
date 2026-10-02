"""Combined smoke test: the patched free-threaded wheels, all in one interpreter.

Run it with the interpreter the wheels were installed into (the build script
installs every built wheel into one fresh venv).  Importing the modules together
must leave the GIL **off** at every step, in either import order, and a short
multi-threaded exercise of the importable APIs must neither raise nor turn the
GIL back on.  Individual wheels are covered by their own smoke tests; this is the
"does it all live in one process" check a downstream application needs.

    python smoke/ft_combined_smoke.py [--modules glcontext,moderngl,rtmidi,cv2,sphn]

No GPU and no MIDI hardware is needed: moderngl is only imported (a render check
needs a GPU), and MIDI ports are only listed.
"""
from __future__ import annotations

import subprocess
import sys
import threading

from gilcheck import env_forces_gil, gil_after_import, probe_env

ALL = ('glcontext', 'moderngl', 'rtmidi', 'cv2', 'sphn')
THREADS, ROUNDS, RATE = 8, 25, 24_000


def _modules(argv: list[str]) -> list[str]:
    if '--modules' in argv:
        names = [n.strip() for n in argv[argv.index('--modules') + 1].split(',') if n.strip()]
        unknown = [n for n in names if n not in ALL]
        if unknown:
            raise SystemExit(f'unknown module(s): {unknown}')
        return names
    return list(ALL)


def _worker(modules: list[str], errors: list[str], index: int) -> None:
    try:
        import numpy as np
        rng = np.random.default_rng(index)
        for _ in range(ROUNDS):
            if 'cv2' in modules:
                import cv2
                img = rng.integers(0, 255, (96, 128, 3), dtype=np.uint8)
                out = cv2.cvtColor(cv2.flip(cv2.GaussianBlur(img, (0, 0), 2), 1), cv2.COLOR_BGR2RGB)
                assert out.shape == img.shape
            if 'sphn' in modules:
                import sphn
                t = np.arange(RATE // 4) / RATE
                tone = (np.sin(2 * np.pi * 440 * t)[None, :] * 0.5).astype(np.float32)
                res = sphn.resample(tone, RATE, 48_000)
                assert np.isfinite(res).all()
            if 'rtmidi' in modules:
                import rtmidi
                for cls in (rtmidi.MidiIn, rtmidi.MidiOut):
                    port = cls()
                    port.get_ports()
                    port.delete()
            if 'moderngl' in modules:
                import moderngl
                assert moderngl.__version__
    except BaseException as exc:                      # noqa: BLE001 - report, do not lose it in a thread
        errors.append(f'thread {index}: {type(exc).__name__}: {exc}')


def main(argv: list[str]) -> int:
    modules = _modules(argv)
    problems: list[str] = []
    print(f'python {sys.version.split()[0]}; modules: {", ".join(modules)}')
    if env_forces_gil():
        problems.append('PYTHON_GIL is set in the environment: the GIL state is forced')
    if not (hasattr(sys, '_is_gil_enabled') and not sys._is_gil_enabled()):
        problems.append('not a free-threaded interpreter with the GIL off at start')

    # Each order in a fresh interpreter, so one import cannot mask another.
    for order in (modules, modules[::-1]):
        ok, state = gil_after_import(*order)
        print(f'  import {" -> ".join(order)}: GIL {state}')
        if not ok:
            problems.append(f'importing {order} leaves the GIL {state}')

    # In this process: import everything, then run threads against it.
    for name in modules:
        __import__(name)
    print('  imported in this process; GIL enabled:', sys._is_gil_enabled())
    if sys._is_gil_enabled():
        problems.append('the GIL is enabled after importing everything in this process')
    errors: list[str] = []
    threads = [threading.Thread(target=_worker, args=(modules, errors, i)) for i in range(THREADS)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    print(f'  {THREADS} threads x {ROUNDS} rounds: {"ok" if not errors else errors[:3]}')
    problems += errors[:3]
    if sys._is_gil_enabled():
        problems.append('the GIL was enabled by the threaded exercise')

    # Interpreter exit with every extension loaded must be clean.
    proc = subprocess.run([sys.executable, '-W', 'ignore', '-c',
                           'import ' + ', '.join(modules)], capture_output=True, text=True,
                          check=False, env=probe_env())
    print(f'  clean interpreter exit with everything imported: {"ok" if proc.returncode == 0 else proc.returncode}')
    if proc.returncode != 0:
        problems.append(f'exit status {proc.returncode} after importing everything')

    print('FAILED: ' + '; '.join(problems) if problems else 'OK')
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
