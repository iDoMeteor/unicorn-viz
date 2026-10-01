"""Smoke test for the free-threaded moderngl / glcontext / python-rtmidi wheels.

Run it with the interpreter the wheels were installed into (see
``build_ft_wheels.sh --verify-python``).  It checks that each extension
imports, a standalone EGL context renders and reads back, and MIDI ports can
be listed -- and it *reports* what each extension does to the GIL, because
an extension that does not declare itself free-threading safe silently turns
the GIL back on when imported (docs/planning/free-threaded-python-2026-09-24.md,
fact 1).  The GIL report is information, not a failure: until real
``Py_mod_gil`` support lands the main process is expected to run with the GIL
on.  Exit status is non-zero only if something actually fails.

    python tools/packaging/ft_wheels_smoke.py [--skip-gl]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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
    return (*names, 'moderngl', 'rtmidi')


def _gil_after_import(module: str) -> str:
    code = ('import sys, importlib; importlib.import_module(%r); '
            'print(sys._is_gil_enabled())' % module)
    proc = subprocess.run([sys.executable, '-W', 'ignore', '-c', code],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return f'IMPORT FAILED: {proc.stderr.strip().splitlines()[-1] if proc.stderr else "?"}'
    return 'ON (module did not declare Py_mod_gil)' if proc.stdout.strip() == 'True' else 'off'


def main(argv: list[str]) -> int:
    failed = False
    gil_off = hasattr(sys, '_is_gil_enabled') and not sys._is_gil_enabled()
    print(f'python {sys.version.split()[0]}  GIL at start: {"off" if gil_off else "ON"}')
    if not gil_off:
        print('  (not a free-threaded interpreter with the GIL off; results below are moot)')
        failed = True
    for module in _extensions():
        state = _gil_after_import(module)
        failed |= state.startswith('IMPORT FAILED')
        print(f'  import {module:14s} -> GIL {state}')

    if '--skip-gl' not in argv:
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

    import rtmidi
    print('rtmidi backends:', [rtmidi.get_api_display_name(a) for a in rtmidi.get_compiled_api()])
    for label, cls in (('in', rtmidi.MidiIn), ('out', rtmidi.MidiOut)):
        port = cls()
        print(f'  MIDI {label}: {port.get_ports()}')
        port.delete()

    print('FAILED' if failed else 'OK')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
