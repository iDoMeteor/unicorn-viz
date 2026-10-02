"""Tests for build_windows_patched_wheels.py.

The script builds Windows cp314t wheels on a Windows CI runner, so what can be
checked here (Linux, no network by default) is its plan: that the pins agree with
the Linux builds' manifests (the reference these wheels must match), that every
patch is the one pinned, that ``--dry-run`` covers every target and touches
nothing, and that it refuses to build for real off Windows.  Set
``FT_WHEELS_ONLINE=1`` to also check, against GitHub, that every pinned branch
still points at the pinned commit.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Adapted from the upstream team's tests/test_build_windows_patched_wheels.py: only this
# root changed (the script now lives under tools/packaging/ft-patched/), plus the sys.path
# line their conftest provided (the smoke scripts import their sibling ``gilcheck``).
ROOT = Path(__file__).resolve().parents[1] / 'tools' / 'packaging' / 'ft-patched'
sys.path.insert(0, str(ROOT / 'smoke'))


@pytest.fixture(autouse=True)
def _no_git_hook_environment(monkeypatch):
    """Added when adapting the upstream tests.  Several of them run real ``git init`` / ``git apply``
    in temp directories.  Inside a git hook (pre-commit, pre-push) git exports GIT_DIR,
    GIT_INDEX_FILE and friends, which would redirect those commands at the CALLING repository
    (this is how a helper of ours fetched fake commits into the shared repo and made it shallow)."""
    import os
    for name in [k for k in os.environ if k.startswith('GIT_')]:
        monkeypatch.delenv(name)


# The upstream workflow lives in a private repo and is kept here as an inactive reference
# copy (reference/windows-patched-wheels.yml); it is NOT a workflow of this repository.
SCRIPT = ROOT / 'build_windows_patched_wheels.py'


@pytest.fixture(scope='module')
def win():
    spec = importlib.util.spec_from_file_location('build_windows_patched_wheels', SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['build_windows_patched_wheels'] = mod
    spec.loader.exec_module(mod)
    return mod


def _manifest(name: str) -> dict:
    return json.loads((ROOT / 'reference' / name).read_text())


# ------------------------------------------------------------------ pins
def test_pins_are_well_formed(win) -> None:
    assert win.check_pins() == []


def test_pins_match_the_linux_patched_wheels_manifest(win) -> None:
    """These wheels must be the Windows counterparts of the Linux ones: same version,
    same build tag, same source commits."""
    by_name = {w['name']: w for w in _manifest('patched-wheels-manifest-2.json')['wheels']}
    for target in ('python-rtmidi', 'glcontext', 'moderngl', 'sphn'):
        spec, ref = win.SPECS[target], by_name[target]
        assert (spec.version, spec.build_tag) == (ref['version'], ref['build_tag']), target
    for target in ('python-rtmidi', 'glcontext', 'moderngl'):
        assert win.SPECS[target].git.commit == by_name[target]['git_commit'], target
    assert win.SPECS['python-rtmidi'].submodule[1].commit == by_name['python-rtmidi']['rtmidi_submodule_commit']
    # sphn: the sdist plus our one-line patch is the same source as the free-threading branch.
    assert win.SPECS['sphn'].extra['equivalent_git_commit'] == by_name['sphn']['git_commit']


def test_pins_match_the_linux_opencv_manifest(win) -> None:
    ref = _manifest('opencv-wheel-manifest.json')
    spec = win.SPECS['opencv']
    assert (spec.version, spec.build_tag) == (ref['version'], ref['build_tag'])
    assert spec.git.commit == ref['sources']['opencv_python_commit']
    assert spec.git.tag == ref['sources']['opencv_python_tag']
    assert spec.submodule[1].commit == ref['sources']['opencv_commit']
    assert spec.patches[0].sha256 == ref['patch']['sha256']
    assert win.NUMPY_BUILD == ref['toolchain']['numpy_build']


def test_cython_and_build_tools_match_the_linux_build(win) -> None:
    assert win.CYTHON == _manifest('patched-wheels-manifest-2.json')['cython']
    assert f'cython=={win.CYTHON}' in win.BUILD_REQUIREMENTS


def test_patch_files_are_the_pinned_ones(win) -> None:
    for spec in win.SPECS.values():
        for patch in spec.patches:
            assert win.sha256_file(patch.path) == patch.sha256, patch.file


def test_a_changed_patch_is_a_pin_problem(win, tmp_path, monkeypatch) -> None:
    fake = tmp_path / 'x.patch'
    fake.write_text('not the pinned patch')
    patch = win.Patch('x.patch', '0' * 64, 'nowhere')
    monkeypatch.setattr(win, 'PATCHES', tmp_path)
    spec = win.Spec('t', 't', '1', '1', git=win.GitRef('u', 'a' * 40), patches=(patch,))
    assert any('sha256' in p for p in win.check_pins({'t': spec}))


def test_a_branch_name_is_not_a_pin(win) -> None:
    spec = win.Spec('t', 't', '1', 'x', git=win.GitRef('u', 'wheels/ft-1.5.8-2'))
    problems = win.check_pins({'t': spec})
    assert any('not numeric' in p for p in problems) and any('full sha1' in p for p in problems)


def test_runtime_pin_is_the_free_threaded_windows_build(win) -> None:
    assert 'freethreaded' in win.PBS_ASSET and 'windows-msvc' in win.PBS_ASSET
    assert win.PBS_RELEASE in win.PBS_URL and re.fullmatch(r'[0-9a-f]{64}', win.PBS_SHA256)


def test_sphn_patch_only_flips_gil_used(win) -> None:
    text = (ROOT / 'patches' / 'sphn-0.2.1-gil-used-false.patch').read_text()
    changed = [ln for ln in text.splitlines() if ln[:1] in '+-' and not ln.startswith(('+++', '---'))]
    assert changed == ['-#[pymodule]', '+#[pymodule(gil_used = false)]']


def test_opencv_patch_declares_free_threading_support(win) -> None:
    text = (ROOT / 'patches' / 'opencv-4.13.0-free-threading.patch').read_text()
    assert 'Py_MOD_GIL_NOT_USED' in text


# ---------------------------------------------------------- wheel names
@pytest.mark.parametrize('target,name', [
    ('python-rtmidi', 'python_rtmidi-1.5.8-3-cp314-cp314t-win_amd64.whl'),
    ('glcontext', 'glcontext-3.0.0-2-cp314-cp314t-win_amd64.whl'),
    ('moderngl', 'moderngl-5.12.0-2-cp314-cp314t-win_amd64.whl'),
    ('sphn', 'sphn-0.2.1-1-cp314-cp314t-win_amd64.whl'),
    ('opencv', 'opencv_python_headless-4.13.0.92-1-cp314-cp314t-win_amd64.whl'),
])
def test_expected_wheel_names(win, target, name) -> None:
    assert win.SPECS[target].wheel_re.match(name)


@pytest.mark.parametrize('target,name', [
    ('python-rtmidi', 'python_rtmidi-1.5.8-cp314-cp314t-win_amd64.whl'),          # no build tag
    ('python-rtmidi', 'python_rtmidi-1.5.8-1-cp314-cp314t-win_amd64.whl'),        # the old tag
    ('moderngl', 'moderngl-5.12.0-2-cp314-cp314t-manylinux_2_28_x86_64.whl'),     # wrong platform
    ('opencv', 'opencv_python_headless-4.13.0.92+abc-1-cp314-cp314t-win_amd64.whl'),  # local version
])
def test_unexpected_wheel_names_are_rejected(win, target, name) -> None:
    assert not win.SPECS[target].wheel_re.match(name)


def test_build_tag_detection(win) -> None:
    assert win.wheel_has_build_tag('python_rtmidi-1.5.8-3-cp314-cp314t-win_amd64.whl')
    assert not win.wheel_has_build_tag('python_rtmidi-1.5.8-cp314-cp314t-win_amd64.whl')


def test_dist_names_from_wheel_filenames(win) -> None:
    assert win._dist_name(Path('python_rtmidi-1.5.8-3-cp314-cp314t-win_amd64.whl')) == 'python-rtmidi'
    assert win._dist_name(Path('opencv_python_headless-4.13.0.92-1-cp314-cp314t-win_amd64.whl')) == 'opencv-python-headless'


# --------------------------------------------------------------- dry run
def test_dry_run_plans_every_target_and_writes_nothing(win, tmp_path, capsys) -> None:
    out, work = tmp_path / 'out', tmp_path / 'work'
    assert win.main(['--out', str(out), '--work', str(work), '--dry-run']) == 0
    text = capsys.readouterr().out
    for needle in (
            # sources, by commit
            '355905673de5', 'cf53bcae93cc', '043bf2ef394b', 'a9b914560638', '4ddfc013fd1f', 'b4c5ec4042f0',
            'github.com/iDoMeteor/python-rtmidi', 'github.com/iDoMeteor/rtmidi',
            'github.com/iDoMeteor/glcontext', 'github.com/iDoMeteor/moderngl',
            'opencv-python.git', 'sdist sphn 0.2.1',
            # patches, tagging, building
            'sphn-0.2.1-gil-used-false.patch', 'opencv-4.13.0-free-threading.patch', 'git apply --check',
            'wheel tags --build 3', 'wheel tags --build 2', 'wheel tags --build 1',
            'maturin build', '-DPYTHON3_LIMITED_API=ON',
            # smoke tests, per wheel and combined
            'ft_wheels_smoke.py', 'ft_opencv_smoke.py', 'ft_sphn_smoke.py', 'ft_combined_smoke.py',
            '--modules glcontext,moderngl,rtmidi,sphn,cv2'):
        assert needle in text, needle
    assert not out.exists() and not work.exists()


def test_dry_run_builds_then_smokes_each_wheel_in_turn(win, tmp_path, capsys) -> None:
    """Cheap wheels are verified before the slow OpenCV build starts, so a problem shows early."""
    win.main(['--out', str(tmp_path / 'o'), '--work', str(tmp_path / 'w'), '--dry-run'])
    text = capsys.readouterr().out
    order = [text.index(n) for n in ('smoke-glcontext', 'smoke-moderngl', 'smoke-python-rtmidi',
                                     'smoke-sphn', 'opencv-python.git', 'smoke-opencv', 'smoke-combined')]
    assert order == sorted(order)


def test_every_smoke_runs_in_a_fresh_venv_without_the_network(win, tmp_path, capsys) -> None:
    win.main(['--out', str(tmp_path / 'o'), '--work', str(tmp_path / 'w'), '--dry-run'])
    installs = [ln for ln in capsys.readouterr().out.splitlines()
                if '--no-index' in ln and 'smoke-' in ln]
    assert len(installs) == 6 and all('--no-deps' in ln for ln in installs)


def test_only_selects_targets(win, tmp_path, capsys) -> None:
    assert win.main(['--out', str(tmp_path / 'o'), '--only', 'sphn', '--dry-run']) == 0
    text = capsys.readouterr().out
    assert 'maturin build' in text and 'opencv-python.git' not in text and 'smoke-combined' not in text


def test_moderngl_pulls_in_glcontext(win, tmp_path, capsys) -> None:
    assert win.main(['--out', str(tmp_path / 'o'), '--only', 'moderngl', '--dry-run']) == 0
    text = capsys.readouterr().out
    assert 'iDoMeteor/glcontext' in text and 'iDoMeteor/moderngl' in text and 'adding glcontext' in text


def test_unknown_target_is_rejected(win, tmp_path) -> None:
    with pytest.raises(SystemExit):
        win.main(['--out', str(tmp_path), '--only', 'nope', '--dry-run'])


def test_refuses_to_build_for_real_off_windows(win, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(win, 'IS_WIN', False)
    with pytest.raises(SystemExit):
        win.main(['--out', str(tmp_path)])


def test_script_dry_run_from_the_command_line(tmp_path) -> None:
    proc = subprocess.run([sys.executable, str(SCRIPT), '--out', str(tmp_path / 'o'),
                           '--work', str(tmp_path / 'w'), '--dry-run'],
                          capture_output=True, text=True, check=False, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert 'summary:' in proc.stdout and 'combined: ok' in proc.stdout


def test_combined_check_leaves_out_moderngl_without_glcontext(win) -> None:
    assert win.combined_targets(['moderngl', 'sphn']) == ['sphn']
    assert win.combined_targets(['glcontext', 'moderngl', 'sphn']) == ['glcontext', 'moderngl', 'sphn']


def test_smoke_dirs_need_the_glcontext_wheel_for_moderngl(win) -> None:
    gl, mgl = Path('raw/glcontext'), Path('raw/moderngl')
    assert win.smoke_dirs('moderngl', {'moderngl': mgl, 'glcontext': gl}) == [mgl, gl]
    assert win.smoke_dirs('moderngl', {'moderngl': mgl, 'glcontext': None}) is None
    assert win.smoke_dirs('sphn', {'sphn': Path('raw/sphn')}) == [Path('raw/sphn')]


def test_every_target_has_a_smoke_test_and_a_module(win) -> None:
    for target in win.TARGETS:
        script, _ = win.SMOKE_SCRIPTS[target]
        assert (ROOT / 'smoke' / script).is_file()
        assert target in win.MODULES and target in win.SPECS


def test_build_info_never_overwrites(win, tmp_path) -> None:
    (tmp_path / 'build-info.json').write_text('{}')
    assert win.next_free(tmp_path / 'build-info.json').name == 'build-info-2.json'
    (tmp_path / 'build-info-2.json').write_text('{}')
    assert win.next_free(tmp_path / 'build-info.json').name == 'build-info-3.json'
    assert win.next_free(tmp_path / 'fresh.json').name == 'fresh.json'


def test_sources_are_described_for_build_info(win) -> None:
    info = win.describe_sources(['python-rtmidi', 'sphn', 'opencv'])
    assert info['python-rtmidi']['submodule']['commit'] == 'cf53bcae93cc1d6dcc30b1e810318628276df082'
    assert info['sphn']['patches'][0]['sha256'] == win.SPECS['sphn'].patches[0].sha256
    assert info['opencv']['git']['commit'] == '4ddfc013fd1f13d9b9e379dbebf2cdbeb052e7f8'
    json.dumps(info)


# ------------------------------------------------------------ run helpers
def test_command_output_is_streamed_and_logged(win, tmp_path, capsys) -> None:
    """A failed run on a CI runner must leave evidence: every command's output goes
    to work/<step>.log (the workflow uploads work/*.log) as well as the console."""
    ctx = win.Ctx(tmp_path, tmp_path / 'out', dry_run=False)
    ctx.set_log('sphn')
    ctx.run([sys.executable, '-c', 'print("hello from a build step"); '
                                   'import sys; print("and stderr", file=sys.stderr)'])
    shown = capsys.readouterr().out
    logged = (tmp_path / 'sphn.log').read_text(encoding='utf-8')
    for text in (shown, logged):
        assert 'hello from a build step' in text and 'and stderr' in text
    assert '$ ' in logged            # the command line itself is recorded too


def test_a_failing_command_raises_and_is_still_logged(win, tmp_path) -> None:
    ctx = win.Ctx(tmp_path, tmp_path / 'out', dry_run=False)
    ctx.set_log('opencv')
    with pytest.raises(subprocess.CalledProcessError):
        ctx.run([sys.executable, '-c', 'print("about to fail"); raise SystemExit(3)'])
    assert 'about to fail' in (tmp_path / 'opencv.log').read_text(encoding='utf-8')


def test_network_commands_are_retried(win, tmp_path) -> None:
    ctx = win.Ctx(tmp_path, tmp_path / 'out', dry_run=False)
    ctx.set_log('x')
    marker = tmp_path / 'tries'
    code = ('import pathlib, sys; p = pathlib.Path(sys.argv[1]); n = int(p.read_text() or 0) if p.exists() else 0; '
            'p.write_text(str(n + 1)); raise SystemExit(0 if n >= 1 else 1)')
    import time
    real_sleep = time.sleep
    time.sleep = lambda _s: None
    try:
        ctx.run([sys.executable, '-c', code, str(marker)], attempts=3)
    finally:
        time.sleep = real_sleep
    assert marker.read_text() == '2'


def test_dry_run_creates_no_log_files(win, tmp_path) -> None:
    ctx = win.Ctx(tmp_path / 'work', tmp_path / 'out', dry_run=True)
    ctx.set_log('sphn')
    ctx.run(['anything'])
    assert not (tmp_path / 'work').exists()


def test_executables_are_resolved_on_the_build_environments_path(win, tmp_path) -> None:
    """On Windows, subprocess looks a bare command up on the *parent's* PATH, not
    the PATH passed in ``env``, so a tool installed into the build venv (maturin,
    found in its Scripts dir) was 'not found' on UV's first CI run."""
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
    venv Scripts directory we prepended silently vanish."""
    merged = win.merge_env({'PATH': 'old', 'KEEP': '1'}, 'Path=new;dirs\nFOO=bar\nnot a variable line\n')
    assert [k for k in merged if k.upper() == 'PATH'] == ['PATH']
    assert merged['PATH'] == 'new;dirs' and merged['FOO'] == 'bar' and merged['KEEP'] == '1'


def test_prepend_path_edits_the_single_path_variable(win) -> None:
    env = {'PATH': 'C:/a;C:/b', 'Path': 'stale'}
    out = win.prepend_path(env, 'C:/venv/Scripts')
    assert [k for k in out if k.upper() == 'PATH'] == ['PATH']
    assert out['PATH'].startswith('C:/venv/Scripts' + os.pathsep)


def test_opencv_build_env_defines_py_gil_disabled_and_finds_the_import_library(win) -> None:
    """UV's first Windows OpenCV run: 'LNK1104: cannot open file python314.lib'.  CPython's
    headers pick the free-threaded layout and auto-link python314t.lib only when
    Py_GIL_DISABLED is defined, and OpenCV's CMake does not define it."""
    env = win.opencv_build_env({'Path': 'C:/x', 'CL': '/MP', 'LIB': 'C:/msvc/lib'}, Path('C:/runtime/python'))
    assert env['CL'].split()[0] == '/DPy_GIL_DISABLED=1' and '/MP' in env['CL']
    assert env['LIB'].startswith(str(Path('C:/runtime/python') / 'libs') + os.pathsep)
    assert 'C:/msvc/lib' in env['LIB']
    assert env['ENABLE_HEADLESS'] == '1'
    assert '-DPYTHON3_LIBRARY=C:/runtime/python/libs/python314t.lib' in env['CMAKE_ARGS']
    assert [k for k in env if k.upper() == 'PATH'] == ['PATH']


def test_opencv_build_env_works_without_existing_cl_and_lib(win) -> None:
    env = win.opencv_build_env({}, Path('/rt/python'))
    assert env['CL'] == '/DPy_GIL_DISABLED=1'


def test_git_env_keeps_sources_byte_exact(win) -> None:
    """A Windows runner's git converts to CRLF by default, which makes the LF patches fail."""
    env = win.git_env({'PATH': 'x'})
    pairs = {env[f'GIT_CONFIG_KEY_{i}']: env[f'GIT_CONFIG_VALUE_{i}'] for i in range(int(env['GIT_CONFIG_COUNT']))}
    assert pairs['core.autocrlf'] == 'false' and pairs['core.longpaths'] == 'true'
    assert env['GIT_TERMINAL_PROMPT'] == '0' and env['PATH'] == 'x'


def test_rmtree_force_removes_read_only_files(win, tmp_path) -> None:
    d = tmp_path / 'tree' / 'objects'
    d.mkdir(parents=True)
    f = d / 'pack.idx'
    f.write_text('x')
    f.chmod(0o444)
    win.rmtree_force(tmp_path / 'tree')
    assert not (tmp_path / 'tree').exists()


# --------------------------------------------------- patches really apply
def _git(*args: str, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, env=env)


def test_apply_patch_applies_and_proves_it(win, tmp_path) -> None:
    """The Build.apply_patch recipe on a throw-away tree inside an unrelated git repo (the
    way ``work/`` sits inside the workflow's checkout): the patch applies to the tree, not
    to the enclosing repo, and the hash pin is enforced."""
    outer = tmp_path / 'outer'
    tree = outer / 'work' / 'src' / 'sphn-0.2.1'
    (tree / 'src').mkdir(parents=True)
    _git('init', '-q', cwd=outer)
    (tree / 'src' / 'lib.rs').write_text('fn x() {}\n\n#[pymodule]\nfn sphn() {}\n')
    # A hand-written patch for this toy tree, pinned by its own hash.
    patch = tmp_path / 'toy.patch'
    patch.write_text('--- a/src/lib.rs\n+++ b/src/lib.rs\n@@ -1,4 +1,4 @@\n fn x() {}\n \n'
                     '-#[pymodule]\n+#[pymodule(gil_used = false)]\n fn sphn() {}\n')
    ctx = win.Ctx(outer / 'work', tmp_path / 'out', dry_run=False)
    b = win.Build(ctx)
    good = win.Patch('toy.patch', win.sha256_file(patch), 'toy')
    import build_windows_patched_wheels as mod
    old = mod.PATCHES
    mod.PATCHES = tmp_path
    try:
        b.apply_patch(tree, good)
        assert 'gil_used = false' in (tree / 'src' / 'lib.rs').read_text()
        with pytest.raises(SystemExit, match='pinned'):
            b.apply_patch(tree, win.Patch('toy.patch', '0' * 64, 'toy'))
        with pytest.raises(subprocess.CalledProcessError):      # already applied: --check fails
            b.apply_patch(tree, good)
    finally:
        mod.PATCHES = old


def test_sphn_patch_applies_to_a_tree_with_the_expected_line(win, tmp_path) -> None:
    """The real sphn patch against the one line it targets (the 0.2.1 sdist's lib.rs line
    context is checked for real by the online test below)."""
    patch = ROOT / 'patches' / 'sphn-0.2.1-gil-used-false.patch'
    assert _git('apply', '--stat', str(patch), cwd=tmp_path).returncode == 0


# ------------------------------------------------------- the workflow file
def test_workflow_is_valid_and_wired_to_the_script() -> None:
    yaml = pytest.importorskip('yaml')
    wf = yaml.safe_load((ROOT / 'reference' / 'windows-patched-wheels.yml').read_text())
    triggers = wf.get('on', wf.get(True))            # PyYAML reads a bare `on` as True
    assert set(triggers) == {'workflow_dispatch'}
    assert 'only' in triggers['workflow_dispatch']['inputs']
    build = wf['jobs']['build']
    assert build['runs-on'] == 'windows-2022' and build['timeout-minutes'] >= 150
    assert build['needs'] == 'checks' and wf['jobs']['checks']['runs-on'].startswith('ubuntu')
    steps = build['steps']
    assert any('build_windows_patched_wheels.py' in s.get('run', '') for s in steps)
    uploads = {s['with']['name']: s['with']['path'] for s in steps if 'upload-artifact' in s.get('uses', '')}
    assert uploads['cp314t-win_amd64-patched-wheels'] == 'wheels-out'
    run = next(s['run'] for s in steps if 'build_windows_patched_wheels.py' in s.get('run', ''))
    assert "'--out', 'wheels-out'" in run and "'--work', 'work'" in run
    assert (next(s for s in steps if s.get('name') == 'Build wheels')['timeout-minutes']
            < build['timeout-minutes'])               # so the artifact uploads still run
    for step in steps:
        if 'upload-artifact' in step.get('uses', ''):
            assert step['if'] == 'always()'
    checks = ' '.join(s.get('run', '') for s in wf['jobs']['checks']['steps'])
    assert 'pytest' in checks and '--dry-run' in checks


def test_workflow_input_names_are_real_targets(win) -> None:
    text = (ROOT / 'reference' / 'windows-patched-wheels.yml').read_text()
    listed = re.search(r'Comma list of wheels to build \(([^)]*)\)', text)[1].split(';')[0]
    assert {n.strip() for n in listed.split(',')} == set(win.TARGETS)


def test_smoke_scripts_and_fixtures_are_present() -> None:
    for name in ('ft_wheels_smoke.py', 'ft_opencv_smoke.py', 'ft_sphn_smoke.py',
                 'ft_combined_smoke.py', 'gilcheck.py'):
        compile((ROOT / 'smoke' / name).read_text(), name, 'exec')
    sums = (ROOT / 'smoke' / 'ft-fixtures' / 'SHA256SUMS').read_text().split()
    import hashlib
    for digest, name in zip(sums[::2], sums[1::2]):
        assert hashlib.sha256((ROOT / 'smoke' / 'ft-fixtures' / name).read_bytes()).hexdigest() == digest


# ------------------------------------------------------------- online check
@pytest.mark.skipif(os.environ.get('FT_WHEELS_ONLINE') != '1', reason='set FT_WHEELS_ONLINE=1 (needs github.com)')
def test_pinned_branches_still_point_at_the_pinned_commits(win) -> None:
    """Each pinned fork branch exists and is still at the pinned commit (the commit is what
    is built; a moved branch means the pin should be reviewed, not silently followed)."""
    refs = [(s.git, s.git.branch) for s in win.SPECS.values() if s.git and s.git.branch]
    refs.append((win.RTMIDI_SUBMODULE, win.RTMIDI_SUBMODULE.branch))
    for ref, branch in refs:
        out = subprocess.run(['git', 'ls-remote', ref.url, f'refs/heads/{branch}'],
                             capture_output=True, text=True, check=True).stdout
        assert out.split()[:1] == [ref.commit], f'{ref.url} {branch}: {out!r}'


@pytest.mark.skipif(os.environ.get('FT_WHEELS_ONLINE') != '1', reason='set FT_WHEELS_ONLINE=1 (needs github.com)')
def test_pinned_tags_resolve_to_the_pinned_commits(win) -> None:
    ref = win.SPECS['opencv'].git
    out = subprocess.run(['git', 'ls-remote', ref.url, f'refs/tags/{ref.tag}', f'refs/tags/{ref.tag}^{{}}'],
                         capture_output=True, text=True, check=True).stdout.split()
    assert ref.commit in out, f'{ref.url} tag {ref.tag}: {out}'


@pytest.mark.skipif(os.environ.get('FT_WHEELS_ONLINE') != '1', reason='set FT_WHEELS_ONLINE=1 (needs pypi.org)')
def test_sphn_sdist_hash_and_patch_apply_to_the_real_sdist(win, tmp_path) -> None:
    import tarfile
    import urllib.request
    spec = win.SPECS['sphn']
    ctx = win.Ctx(tmp_path / 'work', tmp_path / 'out', dry_run=False)
    tree = ctx.pypi_sdist('sphn', spec.version, spec.sdist_sha256, tmp_path)   # raises on a hash mismatch
    b = win.Build(ctx)
    b.apply_patch(tree, spec.patches[0])
    assert '#[pymodule(gil_used = false)]' in (tree / 'src' / 'lib.rs').read_text()


# ------------------------------------------- the publishing logic, with fake builds
@pytest.fixture
def fake_run(win, monkeypatch):
    """Run ``main`` for real (not --dry-run) with the builds and smoke tests faked: each
    target 'builds' a correctly named wheel; ``failing`` maps a step to the targets it fails for."""
    def run(tmp_path, only, failing=None, out=None):
        failing = failing or {}
        monkeypatch.setattr(win, 'IS_WIN', True)
        monkeypatch.setattr(win.Build, 'bootstrap', lambda self: None)
        calls = {'smoke': [], 'combined': []}

        def make(target):
            def build(self):
                if target in failing.get('build', ()):
                    raise SystemExit(f'{target} did not compile')
                spec = self.specs[target]
                d = self.raw / target
                d.mkdir(parents=True, exist_ok=True)
                name = f'{spec.dist.replace("-", "_")}-{spec.version}-{spec.build_tag}-cp314-cp314t-win_amd64.whl'
                (d / name).write_bytes(f'wheel of {target}'.encode())
                return d
            return build

        for t in win.TARGETS:
            monkeypatch.setattr(win.Build, t.replace('-', '_'), make(t))

        def smoke(self, target, dirs):
            calls['smoke'].append(target)
            if target in failing.get('smoke', ()):
                raise subprocess.CalledProcessError(1, ['smoke'])
        monkeypatch.setattr(win.Build, 'smoke', smoke)

        def combined(self, dirs, targets):
            calls['combined'].append(list(targets))
            if failing.get('combined'):
                raise subprocess.CalledProcessError(1, ['combined'])
        monkeypatch.setattr(win.Build, 'smoke_combined', combined)
        out = out or tmp_path / 'out'
        rc = win.main(['--out', str(out), '--work', str(tmp_path / 'work'), '--only', only])
        return rc, out, calls
    return run


def test_only_verified_wheels_are_published_and_failures_fail_the_run(win, fake_run, tmp_path) -> None:
    rc, out, calls = fake_run(tmp_path, 'glcontext,moderngl,python-rtmidi,sphn,opencv',
                              failing={'smoke': ('opencv',), 'build': ('sphn',)})
    assert rc == 1
    names = sorted(p.name for p in out.glob('*.whl'))
    assert names == ['glcontext-3.0.0-2-cp314-cp314t-win_amd64.whl',
                     'moderngl-5.12.0-2-cp314-cp314t-win_amd64.whl',
                     'python_rtmidi-1.5.8-3-cp314-cp314t-win_amd64.whl']
    assert calls['smoke'] == ['glcontext', 'moderngl', 'python-rtmidi', 'opencv']     # sphn never built
    assert calls['combined'] == [['glcontext', 'moderngl', 'python-rtmidi']]           # only verified ones
    info = json.loads((out / 'build-info.json').read_text())
    assert info['results']['sphn'].startswith('BUILD FAILED')
    assert info['results']['opencv'].startswith('SMOKE FAILED')
    assert info['results']['moderngl'] == 'ok' and info['results']['combined'] == 'ok'
    assert info['sources']['opencv']['patches'][0]['sha256'] == win.SPECS['opencv'].patches[0].sha256
    sums = dict(reversed(line.split('  ')) for line in (out / 'SHA256SUMS').read_text().splitlines())
    assert set(sums) == set(names)
    assert all(sums[n] == win.sha256_file(out / n) for n in names)


def test_a_failed_combined_check_fails_the_run_but_keeps_the_verified_wheels(fake_run, tmp_path) -> None:
    rc, out, _ = fake_run(tmp_path, 'glcontext,sphn', failing={'combined': True})
    assert rc == 1 and len(list(out.glob('*.whl'))) == 2
    assert json.loads((out / 'build-info.json').read_text())['results']['combined'].startswith('FAILED')


def test_a_good_run_exits_zero_and_a_rerun_never_overwrites(win, fake_run, tmp_path) -> None:
    rc, out, _ = fake_run(tmp_path, 'glcontext,sphn')
    assert rc == 0
    wheel = out / 'sphn-0.2.1-1-cp314-cp314t-win_amd64.whl'
    wheel.write_bytes(b'precious')                    # something already published under that name
    sums_before = (out / 'SHA256SUMS').read_text()
    rc, _, _ = fake_run(tmp_path, 'glcontext,sphn', out=out)
    assert rc == 0 and wheel.read_bytes() == b'precious'
    assert (out / 'SHA256SUMS').read_text() == sums_before     # nothing new was added
    assert (out / 'build-info.json').exists() and (out / 'build-info-2.json').exists()


def test_moderngl_is_not_published_if_its_glcontext_cannot_be_built(fake_run, tmp_path) -> None:
    rc, out, calls = fake_run(tmp_path, 'moderngl', failing={'build': ('glcontext',)})
    assert rc == 1 and not list(out.glob('*.whl')) and calls['smoke'] == []
    assert 'SMOKE SKIPPED' in json.loads((out / 'build-info.json').read_text())['results']['moderngl']
