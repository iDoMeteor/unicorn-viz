"""Tests for tools/packaging/build_windows_ft_wheels.py.

The script builds Windows cp314t wheels on a Windows CI runner, so what can be
checked here (Linux, no network) is its plan: that it reads its pins from the
Linux recipes (one source of truth), that ``--dry-run`` covers every target
and touches nothing, and that it refuses to build for real off Windows.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools' / 'packaging' / 'build_windows_ft_wheels.py'


@pytest.fixture(scope='module')
def win():
    spec = importlib.util.spec_from_file_location('build_windows_ft_wheels', SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pins_come_from_the_linux_recipes_and_requirements(win) -> None:
    pins = win.read_pins()
    req = (ROOT / 'requirements.txt').read_text()
    assert pins['moderngl_version'] == re.search(r'^moderngl==([0-9.]+)', req, re.M)[1]
    assert pins['python_rtmidi_version'] == re.search(r'^python-rtmidi==([0-9.]+)', req, re.M)[1]
    assert pins['opencv_python_version'] == re.search(r'^opencv-python-headless==([0-9.]+)', req, re.M)[1]
    for key in ('moderngl_sha256', 'glcontext_sha256', 'python_rtmidi_sha256', 'sphn_sha256'):
        assert re.fullmatch(r'[0-9a-f]{64}', pins[key])
    assert re.fullmatch(r'[0-9a-f]{40}', pins['opencv_python_commit'])
    assert pins['rtmidi_build_tag'] == '1'


def test_runtime_pin_is_the_free_threaded_windows_build(win) -> None:
    assert 'freethreaded' in win.PBS_ASSET and 'windows-msvc' in win.PBS_ASSET
    assert win.PBS_RELEASE in win.PBS_URL and re.fullmatch(r'[0-9a-f]{64}', win.PBS_SHA256)


def test_dry_run_plans_every_target_and_writes_nothing(win, tmp_path, capsys) -> None:
    out, work = tmp_path / 'out', tmp_path / 'work'
    assert win.main(['--out', str(out), '--work', str(work), '--dry-run']) == 0
    text = capsys.readouterr().out
    for needle in ('moderngl', 'glcontext', 'python-rtmidi', 'opencv-python.git', 'maturin build',
                   'ft_wheels_smoke.py', 'ft_opencv_smoke.py', 'ft_sphn_smoke.py',
                   '-DPYTHON3_LIMITED_API=ON'):
        assert needle in text, needle
    assert not out.exists() and not work.exists()


def test_only_selects_targets(win, tmp_path, capsys) -> None:
    assert win.main(['--out', str(tmp_path / 'o'), '--only', 'sphn', '--dry-run']) == 0
    text = capsys.readouterr().out
    assert 'maturin build' in text and 'opencv-python.git' not in text


def test_unknown_target_is_rejected(win, tmp_path) -> None:
    with pytest.raises(SystemExit):
        win.main(['--out', str(tmp_path), '--only', 'nope', '--dry-run'])


def test_refuses_to_build_for_real_off_windows(win, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(win, 'IS_WIN', False)
    with pytest.raises(SystemExit):
        win.main(['--out', str(tmp_path)])


def test_dist_names_from_wheel_filenames(win) -> None:
    assert win._dist_name(Path('python_rtmidi-1.5.8-1-cp314-cp314t-win_amd64.whl')) == 'python-rtmidi'
    assert win._dist_name(Path('opencv_python_headless-4.13.0.92-cp314-cp314t-win_amd64.whl')) == 'opencv-python-headless'


def test_command_output_is_streamed_and_logged(win, tmp_path, capsys) -> None:
    """A failed run on a CI runner must leave evidence: every command's output goes
    to work/<step>.log (the workflow uploads work/*.log) as well as the console."""
    import sys as _sys
    ctx = win.Ctx(tmp_path, tmp_path / 'out', dry_run=False)
    ctx.set_log('sphn')
    ctx.run([_sys.executable, '-c', 'print("hello from a build step"); '
                                    'import sys; print("and stderr", file=sys.stderr)'])
    shown = capsys.readouterr().out
    logged = (tmp_path / 'sphn.log').read_text(encoding='utf-8')
    for text in (shown, logged):
        assert 'hello from a build step' in text and 'and stderr' in text
    assert '$ ' in logged            # the command line itself is recorded too


def test_a_failing_command_raises_and_is_still_logged(win, tmp_path) -> None:
    import subprocess
    import sys as _sys
    ctx = win.Ctx(tmp_path, tmp_path / 'out', dry_run=False)
    ctx.set_log('opencv')
    with pytest.raises(subprocess.CalledProcessError):
        ctx.run([_sys.executable, '-c', 'print("about to fail"); raise SystemExit(3)'])
    assert 'about to fail' in (tmp_path / 'opencv.log').read_text(encoding='utf-8')


def test_dry_run_creates_no_log_files(win, tmp_path) -> None:
    ctx = win.Ctx(tmp_path / 'work', tmp_path / 'out', dry_run=True)
    ctx.set_log('sphn')
    ctx.run(['anything'])
    assert not (tmp_path / 'work').exists()


def test_executables_are_resolved_on_the_build_environments_path(win, tmp_path) -> None:
    """On Windows, subprocess looks a bare command up on the *parent's* PATH, not
    the PATH passed in ``env``, so a tool installed into the build venv (maturin,
    found in its Scripts dir) was 'not found' on the first CI run.  Resolve it
    against the environment we are about to run it in."""
    import os
    tool = tmp_path / ('mytool.exe' if os.name == 'nt' else 'mytool')
    tool.write_text('')
    tool.chmod(0o755)
    env = {'PATH': str(tmp_path), 'PATHEXT': '.EXE'}
    assert Path(win.resolve_exe('mytool', env)).resolve() == tool.resolve()
    absolute = str(tmp_path / 'anything')
    assert win.resolve_exe(absolute, env) == absolute      # explicit paths are left alone


def test_unknown_executable_is_a_clear_error(win) -> None:
    with pytest.raises(FileNotFoundError, match='definitely-not-a-tool'):
        win.resolve_exe('definitely-not-a-tool', {'PATH': ''})


def test_env_merge_is_case_insensitive_like_windows(win) -> None:
    """vcvars64 reports ``Path``; Python's os.environ says ``PATH``.  Windows treats
    them as one variable, a plain dict does not, and a duplicate pair made the
    venv Scripts directory we prepended silently vanish (meson-python then could
    not find ``meson``).  Merging must leave exactly one PATH, with vcvars's value."""
    merged = win.merge_env({'PATH': 'old', 'KEEP': '1'}, 'Path=new;dirs\nFOO=bar\nnot a variable line\n')
    assert [k for k in merged if k.upper() == 'PATH'] == ['PATH']
    assert merged['PATH'] == 'new;dirs' and merged['FOO'] == 'bar' and merged['KEEP'] == '1'


def test_prepend_path_edits_the_single_path_variable(win) -> None:
    env = {'PATH': 'C:/a;C:/b', 'Path': 'stale'}
    out = win.prepend_path(env, 'C:/venv/Scripts')
    assert [k for k in out if k.upper() == 'PATH'] == ['PATH']
    import os
    assert out['PATH'].startswith('C:/venv/Scripts' + os.pathsep)


def test_opencv_build_env_defines_py_gil_disabled_and_finds_the_import_library(win) -> None:
    """First Windows OpenCV run: 'LNK1104: cannot open file python314.lib'.  CPython's
    headers pick the free-threaded layout and auto-link python314t.lib only when
    Py_GIL_DISABLED is defined, and OpenCV's CMake does not define it."""
    import os
    env = win.opencv_build_env({'Path': 'C:/x', 'CL': '/MP', 'LIB': 'C:/msvc/lib'}, Path('C:/runtime/python'))
    assert env['CL'].split()[0] == '/DPy_GIL_DISABLED=1' and '/MP' in env['CL']
    assert env['LIB'].startswith(str(Path('C:/runtime/python') / 'libs') + os.pathsep)   # first: found before the SDK's
    assert 'C:/msvc/lib' in env['LIB']
    assert env['ENABLE_HEADLESS'] == '1'
    assert '-DPYTHON3_LIBRARY=C:/runtime/python/libs/python314t.lib' in env['CMAKE_ARGS']
    assert [k for k in env if k.upper() == 'PATH'] == ['PATH']


def test_opencv_build_env_works_without_existing_cl_and_lib(win) -> None:
    env = win.opencv_build_env({}, Path('/rt/python'))
    assert env['CL'] == '/DPy_GIL_DISABLED=1'
