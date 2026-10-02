"""Shared GIL check for the smoke tests.

Every wheel built here declares free-threading support (``Py_mod_gil`` /
``gil_used = false``), so importing its module(s) must leave the GIL off.  The
upstream-style smoke tests only *reported* this; here it is *enforced*.

The probe runs in a fresh interpreter per module, so one extension's GIL
re-enable cannot hide another's, and with ``PYTHON_GIL`` removed from the
environment: ``PYTHON_GIL=0`` (or ``-X gil=0``) would force the GIL off and make
the check meaningless.
"""
from __future__ import annotations

import os
import subprocess
import sys


def verdict(returncode: int, stdout: str, stderr: str) -> tuple[bool, str]:
    """Interpret a probe's result: ``(ok, human-readable state)``.  Only a clean
    exit whose last output line is ``False`` (``sys._is_gil_enabled()``) passes."""
    if returncode != 0:
        lines = stderr.strip().splitlines()
        return False, f'IMPORT FAILED: {lines[-1] if lines else "?"}'
    last = stdout.strip().splitlines()[-1] if stdout.strip() else ''
    if last == 'False':
        return True, 'off'
    if last == 'True':
        return False, 'ON (the module did not declare free-threading support)'
    return False, f'UNEXPECTED PROBE OUTPUT: {stdout.strip()[-80:]!r}'


def probe_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop('PYTHON_GIL', None)
    return env


def gil_after_import(*modules: str) -> tuple[bool, str]:
    """Import ``modules`` in order in a fresh interpreter; ``ok`` only if the GIL
    is still off after each one."""
    code = ('import sys, importlib\n'
            f'for m in {list(modules)!r}:\n'
            '    importlib.import_module(m)\n'
            '    if sys._is_gil_enabled():\n'
            '        print("re-enabled by", m); print(True); raise SystemExit(0)\n'
            'print(sys._is_gil_enabled())\n')
    proc = subprocess.run([sys.executable, '-W', 'ignore', '-c', code],
                          capture_output=True, text=True, check=False, env=probe_env())
    ok, state = verdict(proc.returncode, proc.stdout, proc.stderr)
    if not ok and 're-enabled by' in proc.stdout:
        culprit = proc.stdout.split('re-enabled by', 1)[1].split()[0]
        state = f'ON (re-enabled by importing {culprit})'
    return ok, state


def env_forces_gil() -> bool:
    """True if ``PYTHON_GIL`` is set in this process's environment, which would
    force the GIL state and invalidate every check in a smoke test."""
    return bool(os.environ.get('PYTHON_GIL'))
