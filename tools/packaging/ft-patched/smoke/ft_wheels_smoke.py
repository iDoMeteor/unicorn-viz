"""Smoke test for the patched free-threaded moderngl / glcontext / python-rtmidi wheels.

Adapted from UnicornViz's ``tools/packaging/ft_wheels_smoke.py`` (same owner).
Run it with the interpreter the wheels were installed into.  It checks that each
extension imports, that importing it leaves the GIL **off** (enforced: the
patched modules declare ``Py_mod_gil``; upstream's smoke test only reported it),
that a standalone EGL context renders and reads back (Linux; ``--skip-gl`` on a
machine without a GPU), and that MIDI ports can be listed.

With ``--skip-gl`` a context-creation probe still runs, in a child process, and
only *reports*: on a GPU-less CI runner it is expected to raise a clean Python
exception (which exercises glcontext's error paths); it never fails the run.

    python smoke/ft_wheels_smoke.py [--skip-gl] [--only glcontext,moderngl,rtmidi]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from gilcheck import env_forces_gil, gil_after_import, probe_env


def _extensions() -> tuple[str, ...]:
    """Modules whose import is probed in a fresh interpreter each, so one
    extension's GIL re-enable cannot hide the next one's.  glcontext ships a
    different set of backends per platform (egl and x11 on Linux, wgl and egl on
    Windows), so they are read from the installed package, not listed here."""
    import importlib.util
    spec = importlib.util.find_spec('glcontext')
    names: list[str] = []
    if spec is not None and spec.submodule_search_locations:
        for loc in spec.submodule_search_locations:
            for f in sorted(Path(loc).iterdir()):
                if f.suffix in ('.so', '.pyd') and '.' in f.name:
                    names.append(f'glcontext.{f.name.split(".")[0]}')
    return tuple(names)


def _selected(argv: list[str]) -> set[str]:
    if '--only' in argv:
        return {n.strip() for n in argv[argv.index('--only') + 1].split(',') if n.strip()}
    return {'glcontext', 'moderngl', 'rtmidi'}


def _probe_gl_context() -> None:
    """Informational: try to create a standalone context in a child process (a driver
    crash must not take the smoke test down) and say what happened."""
    code = ('import moderngl\n'
            'try:\n'
            '    ctx = moderngl.create_standalone_context()\n'
            '    print("context created:", ctx.info.get("GL_RENDERER"), ctx.info.get("GL_VERSION"))\n'
            '    ctx.release()\n'
            'except Exception as exc:\n'
            '    print("clean Python exception:", type(exc).__name__, exc)\n')
    try:
        proc = subprocess.run([sys.executable, '-W', 'ignore', '-c', code], capture_output=True,
                              text=True, check=False, timeout=120, env=probe_env())
    except subprocess.TimeoutExpired:
        print('  GL context probe (informational): TIMED OUT')
        return
    out = (proc.stdout.strip().splitlines() or [''])[-1]
    if proc.returncode == 0:
        print(f'  GL context probe (informational): {out}')
    else:
        print(f'  GL context probe (informational): process exited {proc.returncode} '
              f'(a crash, not a Python exception): {(proc.stderr.strip().splitlines() or ["?"])[-1]}')


def main(argv: list[str]) -> int:
    failed = False
    gil_off = hasattr(sys, '_is_gil_enabled') and not sys._is_gil_enabled()
    print(f'python {sys.version.split()[0]}  GIL at start: {"off" if gil_off else "ON"}')
    if not gil_off:
        print('  (not a free-threaded interpreter with the GIL off; results below are moot)')
        failed = True
    if env_forces_gil():
        print('  PYTHON_GIL is set in the environment: the GIL state is being forced, results are moot')
        failed = True
    chosen = _selected(argv)
    modules: list[str] = []
    if 'glcontext' in chosen:
        backends = list(_extensions())
        if not backends:
            print('  glcontext: no backend extension modules found in the installed package')
            failed = True
        modules += backends
    modules += [m for m in ('moderngl', 'rtmidi') if m in chosen]
    for module in modules:
        ok, state = gil_after_import(module)       # enforced: must be off
        failed |= not ok
        print(f'  import {module:18s} -> GIL {state}')

    if 'moderngl' in chosen and '--skip-gl' not in argv:
        import moderngl
        ctx = moderngl.create_standalone_context(backend='egl')
        fbo = ctx.simple_framebuffer((64, 64))
        fbo.use()
        fbo.clear(0.2, 0.4, 0.6, 1.0)
        pixel = tuple(fbo.read(components=4)[:4])
        print(f'EGL: {ctx.info["GL_RENDERER"]} (GL {ctx.info["GL_VERSION"][:24]}); '
              f'clear/readback pixel {pixel}')
        failed |= pixel != (51, 102, 153, 255)
        ctx.release()
    elif 'moderngl' in chosen:
        _probe_gl_context()

    if 'rtmidi' in chosen:
        import rtmidi
        apis = [rtmidi.get_api_display_name(a) for a in rtmidi.get_compiled_api()]
        print('rtmidi backends:', apis)
        if sys.platform == 'win32' and rtmidi.API_WINDOWS_MM not in rtmidi.get_compiled_api():
            print('  expected the Windows MultiMedia (WinMM) backend')
            failed = True
        # A CI runner has no MIDI hardware: an empty port list is a pass, an exception is not.
        for label, cls in (('in', rtmidi.MidiIn), ('out', rtmidi.MidiOut)):
            port = cls()
            print(f'  MIDI {label}: {port.get_ports()}')
            port.delete()

    print('FAILED' if failed else 'OK')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
