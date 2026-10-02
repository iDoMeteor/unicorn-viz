#!/usr/bin/env python3
"""Build the PATCHED Windows (win_amd64) cp314t wheels for free-threaded Python.

python-rtmidi, glcontext, moderngl, sphn and opencv-python-headless have no
upstream wheel for free-threaded 3.14, and the versions on PyPI do not declare
free-threading support (importing them turns the GIL back on).  This builds the
Windows counterparts of the patched Linux wheels (same versions, same sources,
same PEP 427 build tags) so the two platforms of the downstream wheelhouse match:

    python-rtmidi 1.5.8  -3   iDoMeteor/python-rtmidi  wheels/ft-1.5.8-2  (+ RtMidi sub-module)
    glcontext     3.0.0  -2   iDoMeteor/glcontext      fix-error-paths
    moderngl      5.12.0 -2   iDoMeteor/moderngl       wheels/ft-5.12.0-2
    sphn          0.2.1  -1   PyPI sdist (hash-pinned) + patches/sphn-*.patch
    opencv-python-headless 4.13.0.92 -1
                              opencv-python tag 92 + OpenCV 4.13.0 + patches/opencv-*.patch

    python build_windows_patched_wheels.py --out DIR [--work DIR]
                                           [--only NAME[,NAME...]] [--dry-run]

It is adapted from UnicornViz's ``tools/packaging/build_windows_ft_wheels.py``
(same owner; that script built the unpatched PyPI sources) and keeps its
structure.  It uses the standard library only, so any Python that happens to be
installed can launch it.  It downloads and verifies the python-build-standalone
3.14 free-threaded Windows runtime, makes a build venv from it, finds MSVC
through vswhere and imports ``vcvars64`` itself, builds each target against that
interpreter, tags it, smoke-tests each wheel in a fresh venv (the GIL must stay
OFF after importing it), runs a combined all-in-one-process check, and only then
copies verified wheels to ``--out``.  A wheel that fails its smoke test is not
left in ``--out``; the run exits non-zero if anything failed.

Every source is pinned by commit (a git source is fetched by that commit and
``HEAD`` is verified; the sphn sdist is verified by sha256) and every patch by
sha256.  The branch names are recorded for humans only.

Outputs in ``--out``: the wheels, ``SHA256SUMS`` and ``build-info.json``
(sources, patch hashes, tool versions, results).  The output directory is only
ever added to: an existing file is never overwritten (a second ``build-info``
gets a numbered name).

NOT yet exercised on a Windows machine: written against the runtime's layout
(python.exe, include/, libs/python314t.lib) and the behaviour of UV's script that
did run there; checked in ``--dry-run`` and by unit tests on Linux.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
SMOKE = HERE / 'smoke'
PATCHES = HERE / 'patches'
IS_WIN = sys.platform == 'win32'

PBS_RELEASE = '20260929'
PBS_PYVER = '3.14.7'
PBS_ASSET = (f'cpython-{PBS_PYVER}+{PBS_RELEASE}-x86_64-pc-windows-msvc-'
             'freethreaded-install_only.tar.gz')
#: From the release's SHA256SUMS (the installers pin the same build).
PBS_SHA256 = '00502edc9de197a4b2e0ed01f31aabaa8dd31b569d2202f471f97fdcc4424f85'
PBS_URL = ('https://github.com/astral-sh/python-build-standalone/releases/download/'
           f'{PBS_RELEASE}/{urllib.parse.quote(PBS_ASSET)}')

#: Cheap ones first, OpenCV (the slow one) last, so a failure shows early.  glcontext precedes
#: moderngl because moderngl's smoke test installs the glcontext wheel it imports.
TARGETS = ('glcontext', 'moderngl', 'python-rtmidi', 'sphn', 'opencv')

# ---------------------------------------------------------------- tool pins
#: Build-time tools.  These are the versions the Linux patched wheels were built
#: with (reference/patched-wheels-build-tools and the OpenCV manifest), so the two
#: platforms use the same Cython, meson, setuptools, ...  The full resolved list
#: of the build venv is recorded in build-info.json.
CYTHON = '3.3.0'
NUMPY_BUILD = '2.3.2'
BUILD_REQUIREMENTS = (
    'setuptools==84.0.0', 'wheel==0.48.0', 'packaging==26.3', 'build',
    'scikit-build==0.19.1', 'cmake==4.4.3', 'ninja==1.13.2',
    'meson==1.12.1', 'meson-python==0.22.1',
    f'cython=={CYTHON}', f'numpy=={NUMPY_BUILD}',
)
RUST_VERSION = '1.98.1'
MATURIN_VERSION = '1.15.0'


# ---------------------------------------------------------------- sources
@dataclass(frozen=True)
class GitRef:
    """A git source pinned by commit.  ``branch`` is informational only.  ``tag``
    asks for a tag clone instead of a bare fetch of the commit: opencv-python derives
    its version number (``4.13.0.92``) from ``git describe --tags``, so the tag must
    exist in the checkout; the commit is verified either way."""
    url: str
    commit: str
    branch: str = ''
    tag: str = ''


@dataclass(frozen=True)
class Patch:
    file: str        # name under patches/
    sha256: str
    applied_to: str  # what it is applied to, for the record

    @property
    def path(self) -> Path:
        return PATCHES / self.file


@dataclass(frozen=True)
class Spec:
    """One wheel: what it is, the exact version and build tag, where it comes from."""
    target: str
    dist: str
    version: str
    build_tag: str
    git: GitRef | None = None
    submodule: tuple[str, GitRef] | None = None   # (path in the tree, source)
    sdist_sha256: str = ''
    patches: tuple[Patch, ...] = ()
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def wheel_re(self) -> re.Pattern[str]:
        stem = re.sub(r'[-_.]+', '_', self.dist)
        return re.compile(rf'^{stem}-{re.escape(self.version)}-{self.build_tag}-cp314-cp314t-win_amd64\.whl$')


RTMIDI_SUBMODULE = GitRef('https://github.com/iDoMeteor/rtmidi',
                          'cf53bcae93cc1d6dcc30b1e810318628276df082', 'wheels/python-rtmidi-ft-1.5.8')

SPECS: dict[str, Spec] = {
    'python-rtmidi': Spec(
        'python-rtmidi', 'python-rtmidi', '1.5.8', '3',
        git=GitRef('https://github.com/iDoMeteor/python-rtmidi',
                   '355905673de5c958485b39f1b5537f98e00f5640', 'wheels/ft-1.5.8-2'),
        submodule=('src/rtmidi', RTMIDI_SUBMODULE)),
    'glcontext': Spec(
        'glcontext', 'glcontext', '3.0.0', '2',
        git=GitRef('https://github.com/iDoMeteor/glcontext',
                   '043bf2ef394bf0760face037f52e3ee4369fc982', 'fix-error-paths')),
    'moderngl': Spec(
        'moderngl', 'moderngl', '5.12.0', '2',
        git=GitRef('https://github.com/iDoMeteor/moderngl',
                   'a9b91456063819ef1fb5e0622f903fc59d4878bf', 'wheels/ft-5.12.0-2')),
    'sphn': Spec(
        'sphn', 'sphn', '0.2.1', '1',
        # The PyPI sdist keeps upstream's Cargo.lock (built with --locked); our change is
        # the same one line as iDoMeteor/sphn@free-threading (638b338) puts in src/lib.rs.
        sdist_sha256='3b19b1fece67d979d84080458bed545d1f55ddc5abac6ca5deae2672a184c7fe',
        patches=(Patch('sphn-0.2.1-gil-used-false.patch',
                       'b55296af3f72d2f4830f24f6e7cfc4fdca34f9d0ae29f910338405b0502c1f12',
                       'the PyPI sdist tree'),),
        extra={'equivalent_git_commit': '638b3386f7f71cf1e5d576bab619900e45843fac',
               'equivalent_git_url': 'https://github.com/iDoMeteor/sphn',
               'equivalent_git_branch': 'free-threading'}),
    'opencv': Spec(
        'opencv', 'opencv-python-headless', '4.13.0.92', '1',
        git=GitRef('https://github.com/opencv/opencv-python.git',
                   '4ddfc013fd1f13d9b9e379dbebf2cdbeb052e7f8', branch='', tag='92'),
        submodule=('opencv', GitRef('https://github.com/opencv/opencv.git',
                                    'b4c5ec4042f097e2a5b386b9d413ec7333d0a184', branch='gitlink of opencv-python tag 92')),
        patches=(Patch('opencv-4.13.0-free-threading.patch',
                       '1d19d901d66346bdadf5bd7df0ec0b1b60bdc14dfa582c6ae7878c5f613653f4',
                       'the OpenCV submodule (opencv/)'),)),
}

#: What the artifact must contain, by target (wheels are ``<dist>-<ver>-<tag>-...``).
SMOKE_SCRIPTS = {
    'moderngl': ('ft_wheels_smoke.py', ['--skip-gl', '--only', 'moderngl']),
    'glcontext': ('ft_wheels_smoke.py', ['--skip-gl', '--only', 'glcontext']),
    'python-rtmidi': ('ft_wheels_smoke.py', ['--skip-gl', '--only', 'rtmidi']),
    'sphn': ('ft_sphn_smoke.py', []),
    'opencv': ('ft_opencv_smoke.py', []),
}
#: Importable module name of each wheel, for the combined check.
MODULES = {'glcontext': 'glcontext', 'moderngl': 'moderngl', 'python-rtmidi': 'rtmidi',
           'opencv': 'cv2', 'sphn': 'sphn'}
#: A smoke test of the key needs the wheels of the values installed too.
SMOKE_NEEDS = {'moderngl': ('glcontext',)}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_pins(specs: dict[str, Spec] = SPECS) -> list[str]:
    """Problems with the pins themselves (empty = fine): commits are 40 hex chars,
    patch files exist and match their recorded hash, build tags are digits."""
    problems: list[str] = []
    for name, spec in specs.items():
        if not spec.build_tag.isdigit():
            problems.append(f'{name}: build tag {spec.build_tag!r} is not numeric (PEP 427)')
        refs = [r for r in (spec.git, spec.submodule[1] if spec.submodule else None) if r]
        for ref in refs:
            if not re.fullmatch(r'[0-9a-f]{40}', ref.commit):
                problems.append(f'{name}: {ref.url} commit {ref.commit!r} is not a full sha1')
        if spec.git is None and not re.fullmatch(r'[0-9a-f]{64}', spec.sdist_sha256):
            problems.append(f'{name}: neither a git source nor an sdist hash')
        for patch in spec.patches:
            if not patch.path.is_file():
                problems.append(f'{name}: missing {patch.path}')
            elif sha256_file(patch.path) != patch.sha256:
                problems.append(f'{name}: {patch.file} sha256 is {sha256_file(patch.path)}, '
                                f'pinned {patch.sha256}')
    return problems


# ------------------------------------------------------------------- run helpers
def resolve_exe(name: str, env: dict[str, str]) -> str:
    """The full path of command ``name`` as found on ``env``'s PATH.

    On Windows, ``subprocess`` resolves a bare command name against the parent
    process's PATH, not the ``env`` it is given, so a tool that only exists in
    the build venv (maturin, in its Scripts directory) is "not found".  Resolve
    it ourselves, against the environment it will run in.
    """
    if os.path.isabs(name) or os.sep in name or (os.altsep and os.altsep in name):
        return name
    found = shutil.which(name, path=env.get('PATH', ''))
    if found is None:
        raise FileNotFoundError(f'{name!r} not found on the build environment PATH')
    return found


def rmtree_force(path: Path) -> None:
    """``shutil.rmtree`` that also deletes read-only files (git's object files are
    read-only, which makes a plain rmtree fail on Windows)."""
    def onerror(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, ignore_errors=False, onexc=lambda f, p, e: onerror(f, p, e))
    else:
        shutil.rmtree(path, onerror=onerror)


class Ctx:
    """Everything that touches the outside world goes through here, so
    ``--dry-run`` can print the plan without doing any of it."""

    def __init__(self, work: Path, out: Path, dry_run: bool) -> None:
        self.work, self.out, self.dry = work, out, dry_run
        self.env: dict[str, str] = dict(os.environ)
        self.log_path: Path | None = None

    def set_log(self, step: str) -> None:
        """Send everything from here on to ``work/<step>.log`` (as well as the
        console): a failed run on a CI runner has to leave evidence, and the
        workflow uploads ``work/*.log``."""
        self.log_path = self.work / f'{step}.log'

    def _write_log(self, text: str) -> None:
        if self.dry or self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open('a', encoding='utf-8', errors='replace') as fh:
            fh.write(text)

    def say(self, msg: str) -> None:
        print(f'[build-win-patched] {msg}', flush=True)
        self._write_log(f'[build-win-patched] {msg}\n')

    def run(self, cmd: list[str | Path], *, cwd: Path | None = None,
            env: dict[str, str] | None = None, attempts: int = 1) -> None:
        shown = ' '.join(str(c) for c in cmd)
        self.say(f'$ {shown}' + (f'   (in {cwd})' if cwd else ''))
        if self.dry:
            return
        for attempt in range(1, attempts + 1):
            try:
                self._run_once(cmd, cwd, env)
                return
            except subprocess.CalledProcessError:
                if attempt == attempts:
                    raise
                self.say(f'  attempt {attempt} failed, retrying')
                time.sleep(5 * attempt)

    def _run_once(self, cmd: list[str | Path], cwd: Path | None, env: dict[str, str] | None) -> None:
        # Stream the child's combined output to the console and the step log.
        run_env = env or self.env
        argv = [str(c) for c in cmd]
        argv[0] = resolve_exe(argv[0], run_env)
        proc = subprocess.Popen(argv, cwd=cwd, env=run_env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors='replace', bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            self._write_log(line)
        sys.stdout.flush()
        if proc.wait() != 0:
            raise subprocess.CalledProcessError(proc.returncode, [str(c) for c in cmd])

    def capture(self, cmd: list[str | Path], *, env: dict[str, str] | None = None) -> str:
        if self.dry:
            return ''
        run_env = env or self.env
        argv = [str(c) for c in cmd]
        argv[0] = resolve_exe(argv[0], run_env)
        return subprocess.check_output(argv, text=True, env=run_env, stderr=subprocess.STDOUT).strip()

    def download(self, url: str, dest: Path, sha256: str | None) -> None:
        self.say(f'download {url} -> {dest.name}' + (f' (sha256 {sha256[:12]}...)' if sha256 else ''))
        if self.dry:
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, 6):
            try:
                urllib.request.urlretrieve(url, dest)
                break
            except OSError as exc:
                self.say(f'  attempt {attempt} failed: {exc}')
                if attempt == 5:
                    raise
                time.sleep(5)
        if sha256 is not None:
            got = sha256_file(dest)
            if got != sha256:
                raise SystemExit(f'sha256 mismatch for {dest.name}: {got} != {sha256}')

    def pypi_sdist(self, name: str, version: str, sha256: str, dest_dir: Path) -> Path:
        """Fetch and hash-check a PyPI sdist, extract it, return the tree."""
        self.say(f'sdist {name} {version}')
        if self.dry:
            return dest_dir / f'{name}-{version}'
        with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json') as resp:
            meta = json.load(resp)
        url = next(u['url'] for u in meta['urls'] if u['packagetype'] == 'sdist')
        archive = dest_dir / url.rsplit('/', 1)[-1]
        self.download(url, archive, sha256)
        with tarfile.open(archive) as tf:
            top = tf.getnames()[0].split('/')[0]
            tf.extractall(dest_dir, filter='data') if hasattr(tarfile, 'data_filter') else tf.extractall(dest_dir)
        return dest_dir / top


def venv_python(venv: Path) -> Path:
    return venv / ('Scripts/python.exe' if IS_WIN else 'bin/python')


def merge_env(base: dict[str, str], dump: str) -> dict[str, str]:
    """Overlay a ``set`` dump (``NAME=value`` lines) onto ``base``, treating names
    case-insensitively as Windows does.

    ``vcvars64.bat`` reports ``Path`` while Python's ``os.environ`` says ``PATH``;
    in a plain dict those are two keys, the child process gets an arbitrary one
    of them, and any directory prepended to the other vanishes.  All names are
    stored upper-case here, the later value winning, so there is exactly one.
    """
    env = {k.upper(): v for k, v in base.items()}
    for line in dump.splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            if key:
                env[key.upper()] = value
    return env


def prepend_path(env: dict[str, str], directory: str) -> dict[str, str]:
    """``env`` with ``directory`` first on its single PATH variable."""
    out = {k.upper(): v for k, v in env.items()}
    old = out.get('PATH', '')
    out['PATH'] = directory + (os.pathsep + old if old else '')
    return out


def git_env(base: dict[str, str]) -> dict[str, str]:
    """``base`` plus git settings that make sources byte-exact on a Windows runner:
    no CRLF conversion (the patches are LF and ``git apply`` is strict about context),
    long paths on (OpenCV's tree goes deep), no interactive prompts."""
    env = dict(base)
    env.update(GIT_CONFIG_COUNT='2', GIT_CONFIG_KEY_0='core.autocrlf', GIT_CONFIG_VALUE_0='false',
               GIT_CONFIG_KEY_1='core.longpaths', GIT_CONFIG_VALUE_1='true', GIT_TERMINAL_PROMPT='0')
    return env


def opencv_build_env(base: dict[str, str], py_base: Path) -> dict[str, str]:
    """The environment for the OpenCV build (everything OpenCV's CMake needs that
    setuptools would otherwise provide on a free-threaded interpreter).

    * ``CL=/DPy_GIL_DISABLED=1``: CPython's headers only use the free-threaded
      object layout, and only auto-link ``python314t.lib`` (instead of
      ``python314.lib``), when ``Py_GIL_DISABLED`` is defined.  setuptools defines it
      for extensions; OpenCV's CMake does not, so the first Windows run died with
      ``LNK1104: cannot open file 'python314.lib'`` and, had it linked, the module
      would have been built against the wrong object layout.  MSVC reads ``CL`` for
      every compile, which is also what makes the define reach OpenCV's own modules.
    * ``LIB``: the runtime's ``libs`` directory, so the auto-linked import library
      is found.
    * ``CMAKE_ARGS``: explicit Python library and include paths (scikit-build may not
      recognise the free-threaded import library's name).
    """
    env = {k.upper(): v for k, v in base.items()}
    libs = (py_base / 'libs').as_posix()
    env['CL'] = '/DPy_GIL_DISABLED=1' + (' ' + env['CL'] if env.get('CL') else '')
    env['LIB'] = str(py_base / 'libs') + (os.pathsep + env['LIB'] if env.get('LIB') else '')
    env.update(ENABLE_HEADLESS='1', CI_BUILD='1', OPENCV_PYTHON_SKIP_GIT_COMMANDS='1',
               CMAKE_ARGS=f'-DPYTHON3_LIBRARY={libs}/python314t.lib '
                          f'-DPYTHON3_INCLUDE_DIR={(py_base / "include").as_posix()}')
    return env


def msvc_env(ctx: Ctx) -> dict[str, str]:
    """The environment ``vcvars64.bat`` sets up (the MSVC compiler, linker and
    SDK paths), found through vswhere, so no workflow step has to do it."""
    env = {k.upper(): v for k, v in os.environ.items()}
    if not IS_WIN:
        return env
    vswhere = (Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'))
               / 'Microsoft Visual Studio' / 'Installer' / 'vswhere.exe')
    install = subprocess.check_output(
        [str(vswhere), '-latest', '-products', '*', '-requires',
         'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'],
        text=True).strip()
    if not install:
        raise SystemExit('no Visual Studio with the C++ tools found (vswhere)')
    vcvars = Path(install) / 'VC' / 'Auxiliary' / 'Build' / 'vcvars64.bat'
    dump = subprocess.check_output(f'cmd /d /s /c "call "{vcvars}" >nul && set"', shell=True, text=True)
    ctx.say(f'MSVC environment from {vcvars}')
    return merge_env(env, dump)


def wheel_has_build_tag(name: str) -> bool:
    """True if a wheel file name already carries a PEP 427 build tag
    (``dist-ver-build-py-abi-plat.whl`` has six dash-separated fields, not five)."""
    return len(name[:-len('.whl')].split('-')) == 6


def _dist_name(wheel: Path) -> str:
    return wheel.name.split('-')[0].replace('_', '-')


def _wheels(ctx: Ctx, directory: Path) -> list[Path]:
    return [] if ctx.dry else sorted(directory.glob('*.whl'))


# ------------------------------------------------------------------ the builds
class Build:
    def __init__(self, ctx: Ctx, specs: dict[str, Spec] = SPECS) -> None:
        self.ctx, self.specs = ctx, specs
        self.py_root = ctx.work / 'python'
        self.venv = ctx.work / 'venv'
        self.raw = ctx.work / 'raw'
        self.src = ctx.work / 'src'
        self.facts: dict[str, object] = {}     # tool versions etc., for build-info.json

    # -- toolchain ---------------------------------------------------------
    def bootstrap(self) -> None:
        ctx = self.ctx
        ctx.set_log('bootstrap')
        archive = ctx.work / PBS_ASSET
        ctx.download(PBS_URL, archive, PBS_SHA256)
        ctx.say(f'extract the free-threaded {PBS_PYVER} runtime to {self.py_root}')
        if not ctx.dry:
            if self.py_root.exists():
                rmtree_force(self.py_root)
            with tarfile.open(archive) as tf:
                tf.extractall(ctx.work, filter='data') if hasattr(tarfile, 'data_filter') else tf.extractall(ctx.work)
        base_py = self.py_root / ('python.exe' if IS_WIN else 'bin/python3')
        ctx.run([base_py, '-m', 'venv', self.venv])
        py = venv_python(self.venv)
        ctx.run([py, '-m', 'pip', 'install', '-q', '--upgrade', 'pip'])
        ctx.run([py, '-m', 'pip', 'install', '-q', *BUILD_REQUIREMENTS, f'maturin=={MATURIN_VERSION}'])
        ctx.say('MSVC environment')
        ctx.env = msvc_env(ctx)
        ctx.env = prepend_path(ctx.env, str(self.venv / ('Scripts' if IS_WIN else 'bin')))
        ctx.env = git_env(ctx.env)
        ctx.env.pop('PYTHON_GIL', None)       # never let the environment force the GIL state
        ctx.env['CMAKE_BUILD_PARALLEL_LEVEL'] = str(os.cpu_count() or 4)
        # libopus's bundled CMakeLists predates CMake 4's floor (sphn; see UV's build_ft_sphn_wheel.sh).
        ctx.env['CMAKE_POLICY_VERSION_MINIMUM'] = '3.5'
        self._record_tools()

    def _record_tools(self) -> None:
        """Facts about the build environment, for build-info.json (never fatal)."""
        ctx = self.ctx
        if ctx.dry:
            return
        py = venv_python(self.venv)

        def grab(key: str, cmd: list[str | Path], env: dict[str, str] | None = None) -> None:
            try:
                self.facts[key] = ctx.capture(cmd, env=env).splitlines()
            except (subprocess.CalledProcessError, OSError, FileNotFoundError) as exc:
                self.facts[key] = [f'unavailable: {exc}']

        grab('pip_freeze', [py, '-m', 'pip', 'freeze'])
        grab('git_version', ['git', '--version'])
        self.facts['msvc'] = {k: ctx.env.get(k, '') for k in
                              ('VCTOOLSVERSION', 'VISUALSTUDIOVERSION', 'WINDOWSSDKVERSION')}
        self.facts['runner'] = {k: os.environ.get(k, '') for k in
                                ('ImageOS', 'ImageVersion', 'RUNNER_OS', 'RUNNER_ARCH', 'GITHUB_SHA',
                                 'GITHUB_RUN_ID', 'GITHUB_REPOSITORY')}

    # -- sources -----------------------------------------------------------
    def fetch_git(self, ref: GitRef, dest: Path) -> None:
        """A fresh tree of exactly ``ref.commit`` (fetched by commit, not by branch),
        verified afterwards.  Only the one commit's history depth is transferred."""
        ctx = self.ctx
        label = f'branch {ref.branch}' if ref.branch else f'tag {ref.tag}' if ref.tag else ''
        ctx.say(f'source {ref.url} @ {ref.commit[:12]}' + (f' ({label})' if label else ''))
        if not ctx.dry and dest.exists():
            rmtree_force(dest)
        if ref.tag:
            for attempt in (1, 2, 3):
                try:
                    ctx.run(['git', 'clone', '-q', '--depth', '1', '--branch', ref.tag, ref.url, dest])
                    break
                except subprocess.CalledProcessError:
                    if attempt == 3:
                        raise
                    if dest.exists():
                        rmtree_force(dest)          # a clone cannot retry into a half-made directory
                    time.sleep(5 * attempt)
        else:
            ctx.run(['git', 'init', '-q', dest])
            ctx.run(['git', '-C', dest, 'remote', 'add', 'origin', ref.url])
            ctx.run(['git', '-C', dest, 'fetch', '-q', '--depth', '1', 'origin', ref.commit], attempts=3)
            ctx.run(['git', '-C', dest, 'checkout', '-q', 'FETCH_HEAD'])
        self.verify_head(dest, ref.commit)

    def verify_head(self, repo: Path, want: str) -> None:
        if self.ctx.dry:
            return
        got = self.ctx.capture(['git', '-C', repo, 'rev-parse', 'HEAD'])
        if got != want:
            raise SystemExit(f'{repo} is at {got}, expected {want}')

    def apply_patch(self, tree: Path, patch: Patch) -> None:
        """Hash-check ``patch``, then apply it to ``tree`` (an OpenCV submodule checkout,
        or an extracted sdist).  ``git apply`` is run with a ceiling directory so it
        cannot mistake an enclosing repository (the workflow's checkout contains
        ``work/``) for the one whose paths it is patching; applying is proven afterwards
        by a reverse ``--check``."""
        ctx = self.ctx
        got = sha256_file(patch.path)
        if got != patch.sha256:
            raise SystemExit(f'{patch.file}: sha256 {got} != pinned {patch.sha256}')
        env = dict(ctx.env, GIT_CEILING_DIRECTORIES=str(tree.parent))
        ctx.say(f'patch {patch.file} (sha256 {patch.sha256[:12]}...) onto {patch.applied_to}')
        ctx.run(['git', 'apply', '--check', patch.path], cwd=tree, env=env)
        ctx.run(['git', 'apply', '--whitespace=nowarn', patch.path], cwd=tree, env=env)
        ctx.run(['git', 'apply', '--check', '--reverse', patch.path], cwd=tree, env=env)

    def _wheel_from(self, tree: Path, name: str, *, remove: str | None = None,
                    env: dict[str, str] | None = None) -> Path:
        spec = self.specs[name]
        py = venv_python(self.venv)
        out = self.raw / name
        if not self.ctx.dry:
            if out.exists():
                rmtree_force(out)
            out.mkdir(parents=True)
        if remove and not self.ctx.dry:
            (tree / remove).unlink(missing_ok=True)
        self.ctx.run([py, '-m', 'pip', 'wheel', '--no-build-isolation', '--no-deps',
                      '-w', out, '.'], cwd=tree, env=env)
        self.tag(out, spec)
        return out

    def tag(self, directory: Path, spec: Spec) -> None:
        """Give the wheel its PEP 427 build tag (what makes pip prefer it over the
        same-version wheel without one) and check the result's name exactly."""
        py = venv_python(self.venv)
        wheels = _wheels(self.ctx, directory)
        if not self.ctx.dry and len(wheels) != 1:
            raise SystemExit(f'{spec.target}: expected exactly one built wheel, found '
                             f'{[w.name for w in wheels]}')
        if self.ctx.dry:
            wheels = [directory / f'<{spec.dist}>.whl']
        for whl in wheels:
            if wheel_has_build_tag(whl.name):
                raise SystemExit(f'{whl.name} already has a build tag')
            self.ctx.run([py, '-m', 'wheel', 'tags', '--build', spec.build_tag, '--remove', whl])
        if not self.ctx.dry:
            final = _wheels(self.ctx, directory)
            if len(final) != 1 or not spec.wheel_re.match(final[0].name):
                raise SystemExit(f'{spec.target}: wheel is {[w.name for w in final]}, expected '
                                 f'{spec.dist.replace("-", "_")}-{spec.version}-{spec.build_tag}-'
                                 'cp314-cp314t-win_amd64.whl')

    # -- targets: each returns the directory holding its tagged wheel -------
    def moderngl(self) -> Path:
        spec = self.specs['moderngl']
        self.ctx.set_log('moderngl')
        tree = self.src / 'moderngl'
        self.fetch_git(spec.git, tree)
        return self._wheel_from(tree, 'moderngl')

    def glcontext(self) -> Path:
        spec = self.specs['glcontext']
        self.ctx.set_log('glcontext')
        tree = self.src / 'glcontext'
        self.fetch_git(spec.git, tree)
        return self._wheel_from(tree, 'glcontext')

    def python_rtmidi(self) -> Path:
        ctx = self.ctx
        spec = self.specs['python-rtmidi']
        ctx.set_log('python-rtmidi')
        tree = self.src / 'python-rtmidi'
        self.fetch_git(spec.git, tree)
        # The RtMidi sub-module is a gitlink in that commit.  Its commit only exists on our
        # fork, so fetch it explicitly from there (the .gitmodules URL is not used) and make
        # sure it is the one the gitlink records.
        sub_path, sub = spec.submodule
        if not ctx.dry:
            link = ctx.capture(['git', '-C', tree, 'ls-tree', 'HEAD', sub_path]).split()
            if link[:2] != ['160000', 'commit'] or link[2] != sub.commit:
                raise SystemExit(f'{sub_path} gitlink is {link}, expected commit {sub.commit}')
            if (tree / sub_path).exists():
                rmtree_force(tree / sub_path)
        self.fetch_git(sub, tree / sub_path)
        if not ctx.dry and 'callUserCallback' not in (tree / sub_path / 'RtMidi.h').read_text(errors='replace'):
            raise SystemExit('the RtMidi checkout is not the patched one (no callUserCallback)')
        # A pre-generated src/_rtmidi.cpp would predate Cython's free-threading support
        # (3.1): never present in a git tree, but if one ever is, drop it so meson
        # regenerates it with the pinned Cython from the .pyx.
        return self._wheel_from(tree, 'python-rtmidi', remove='src/_rtmidi.cpp')

    def opencv(self) -> Path:
        ctx = self.ctx
        spec = self.specs['opencv']
        ctx.set_log('opencv')
        tree = self.src / 'opencv-python'
        sub_path, sub = spec.submodule
        self.fetch_git(spec.git, tree)
        # Only the OpenCV sub-module is needed (no contrib, no test data), as in UV's build.
        ctx.say(f'source {sub.url} @ {sub.commit[:12]} (the sub-module {sub_path}/, from the gitlink)')
        ctx.run(['git', '-C', tree, 'submodule', 'update', '-q', '--init', '--depth', '1', sub_path],
                attempts=3)
        self.verify_head(tree / sub_path, sub.commit)
        if not ctx.dry:
            # The stable ABI cannot exist on a free-threaded build: drop the hard-coded flag.
            setup = tree / 'setup.py'
            lines = setup.read_text().splitlines(keepends=True)
            kept = [ln for ln in lines if ln.strip() != '"-DPYTHON3_LIMITED_API=ON",']
            if len(kept) != len(lines) - 1:
                raise SystemExit('expected exactly one hard-coded PYTHON3_LIMITED_API line in setup.py')
            setup.write_text(''.join(kept))
        else:
            ctx.say('edit setup.py: remove the hard-coded "-DPYTHON3_LIMITED_API=ON",')
        for patch in spec.patches:
            self.apply_patch(tree / sub_path, patch)
        py = venv_python(self.venv)
        base = Path(ctx.capture([py, '-c', 'import sys; print(sys.base_prefix)']) or str(self.py_root))
        env = opencv_build_env(ctx.env, base)
        # Windows: OpenCV's own CMake downloads its documented-LGPL FFmpeg plugin
        # DLL (pinned by hash), so nothing is built for FFmpeg here.
        return self._wheel_from(tree, 'opencv', env=env)

    def sphn(self) -> Path:
        ctx = self.ctx
        spec = self.specs['sphn']
        ctx.set_log('sphn')
        tree = ctx.pypi_sdist('sphn', spec.version, spec.sdist_sha256, self.src)
        for patch in spec.patches:
            self.apply_patch(tree, patch)
        if not ctx.dry and 'gil_used = false' not in (tree / 'src' / 'lib.rs').read_text():
            raise SystemExit('src/lib.rs does not declare gil_used = false after patching')
        ctx.run(['rustup', 'toolchain', 'install', RUST_VERSION, '--profile', 'minimal'], attempts=3)
        env = dict(ctx.env)
        env['RUSTUP_TOOLCHAIN'] = RUST_VERSION
        out = self.raw / 'sphn'
        if not ctx.dry:
            if out.exists():
                rmtree_force(out)
            out.mkdir(parents=True)
            self.facts['rustc'] = ctx.capture(['rustc', '--version'], env=env)
        ctx.run(['maturin', 'build', '--release', '--locked', '--interpreter',
                 venv_python(self.venv), '--out', out], cwd=tree, env=env)
        self.tag(out, spec)
        return out

    # -- smoke -------------------------------------------------------------
    def _smoke_venv(self, label: str, wheel_dirs: list[Path], needs_numpy: bool) -> Path:
        ctx = self.ctx
        venv = ctx.work / f'smoke-{label}'
        if not ctx.dry and venv.exists():
            rmtree_force(venv)
        base_py = self.py_root / ('python.exe' if IS_WIN else 'bin/python3')
        ctx.run([base_py, '-m', 'venv', venv])
        py = venv_python(venv)
        if needs_numpy:
            ctx.run([py, '-m', 'pip', 'install', '-q', '--only-binary', ':all:', 'numpy'])
        find = [arg for d in wheel_dirs for arg in ('--find-links', str(d))]
        names = sorted({_dist_name(w) for d in wheel_dirs for w in _wheels(ctx, d)}) or ['<wheels>']
        ctx.run([py, '-m', 'pip', 'install', '-q', '--no-index', '--no-deps', *find, *names])
        ctx.run([py, '-m', 'pip', 'freeze'])      # what exactly was tested, in the step log
        return py

    def smoke(self, target: str, wheel_dirs: list[Path]) -> None:
        """Install the target's wheel (and what its smoke test needs) into a fresh venv of
        the runtime and run its smoke test; any failure raises."""
        ctx = self.ctx
        script, extra = SMOKE_SCRIPTS[target]
        ctx.set_log(f'smoke-{target}')
        py = self._smoke_venv(target, wheel_dirs, needs_numpy=target in ('opencv', 'sphn'))
        ctx.run([py, SMOKE / script, *extra], env=self._smoke_env())

    def smoke_combined(self, wheel_dirs: list[Path], targets: list[str]) -> None:
        ctx = self.ctx
        ctx.set_log('smoke-combined')
        py = self._smoke_venv('combined', wheel_dirs, needs_numpy=True)
        modules = ','.join(MODULES[t] for t in targets)
        ctx.run([py, SMOKE / 'ft_combined_smoke.py', '--modules', modules], env=self._smoke_env())

    def _smoke_env(self) -> dict[str, str]:
        env = dict(self.ctx.env)
        env.pop('PYTHON_GIL', None)
        return env


# ------------------------------------------------------------------------ main
def smoke_dirs(target: str, groups: dict[str, Path | None]) -> list[Path] | None:
    """The wheel directories a target's smoke test installs, or ``None`` if one of them
    was not built (moderngl is smoke-tested with the glcontext wheel it imports)."""
    dirs = [groups.get(target)] + [groups.get(n) for n in SMOKE_NEEDS.get(target, ())]
    return None if any(d is None for d in dirs) else [d for d in dirs if d is not None]


def combined_targets(smoked: list[str]) -> list[str]:
    """Which verified wheels go into the combined check: moderngl cannot be imported
    without the glcontext wheel, so it is left out when glcontext is not among them."""
    return [t for t in smoked if t != 'moderngl' or 'glcontext' in smoked]


def next_free(path: Path) -> Path:
    """``path``, or ``stem-2.suffix``, ``stem-3.suffix``... if it already exists."""
    if not path.exists():
        return path
    n = 2
    while (path.with_name(f'{path.stem}-{n}{path.suffix}')).exists():
        n += 1
    return path.with_name(f'{path.stem}-{n}{path.suffix}')


def describe_sources(wanted: list[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for name in wanted:
        s = SPECS[name]
        entry: dict[str, object] = {'dist': s.dist, 'version': s.version, 'build_tag': s.build_tag}
        if s.git:
            entry['git'] = {'url': s.git.url, 'commit': s.git.commit, 'branch': s.git.branch}
        if s.submodule:
            entry['submodule'] = {'path': s.submodule[0], 'url': s.submodule[1].url,
                                  'commit': s.submodule[1].commit, 'branch': s.submodule[1].branch}
        if s.sdist_sha256:
            entry['pypi_sdist_sha256'] = s.sdist_sha256
        if s.patches:
            entry['patches'] = [{'file': f'patches/{p.file}', 'sha256': p.sha256,
                                 'applied_to': p.applied_to} for p in s.patches]
        entry.update(s.extra)
        out[name] = entry
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--out', type=Path, required=True, help='where finished wheels are added')
    ap.add_argument('--work', type=Path, default=Path('_wheel-build'), help='scratch directory')
    ap.add_argument('--only', default=','.join(TARGETS), help=f'comma list of: {", ".join(TARGETS)}')
    ap.add_argument('--dry-run', action='store_true', help='print the plan, do nothing')
    args = ap.parse_args(argv)
    # Compiler output can contain characters a Windows console code page cannot
    # encode; never let that crash the build.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')

    wanted = [t.strip() for t in args.only.split(',') if t.strip()]
    unknown = [t for t in wanted if t not in TARGETS]
    if unknown:
        ap.error(f'unknown target(s): {", ".join(unknown)}')
    if not wanted:
        ap.error('--only selects nothing')
    if 'moderngl' in wanted and 'glcontext' not in wanted:
        print('[build-win-patched] note: moderngl is verified together with the glcontext wheel; adding glcontext')
        wanted.append('glcontext')
    wanted = [t for t in TARGETS if t in wanted]       # canonical order, no duplicates
    if not IS_WIN and not args.dry_run:
        ap.error('this builds Windows wheels and must run on Windows (use --dry-run elsewhere)')
    problems = check_pins()
    if problems:
        ap.error('pin problems: ' + '; '.join(problems))

    work = args.work.resolve()
    out = args.out.resolve()
    ctx = Ctx(work, out, args.dry_run)
    if not args.dry_run:
        work.mkdir(parents=True, exist_ok=True)
        out.mkdir(parents=True, exist_ok=True)
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    b = Build(ctx)
    ctx.say(f'targets: {", ".join(wanted)}; runtime PBS {PBS_RELEASE} / {PBS_PYVER} freethreaded')
    b.bootstrap()

    results: dict[str, str] = {}
    groups: dict[str, Path | None] = {}

    def attempt(name: str) -> Path | None:
        try:
            wheel_dir = getattr(b, name.replace('-', '_'))()
            results[name] = 'built'
            return wheel_dir
        except (Exception, SystemExit) as exc:
            results[name] = f'BUILD FAILED: {exc}'
            ctx.say(results[name])
            return None

    smoked: list[str] = []
    for name in wanted:                                # build, then smoke-test, one wheel at a time
        groups[name] = attempt(name)
        if groups[name] is None:
            continue
        dirs = smoke_dirs(name, groups)
        if dirs is None:
            results[name] = 'SMOKE SKIPPED: a wheel its smoke test needs failed to build'
            continue
        try:
            b.smoke(name, dirs)
            smoked.append(name)
        except (Exception, SystemExit) as exc:
            results[name] = f'SMOKE FAILED: {exc}'
            ctx.say(results[name])

    # All verified wheels in one interpreter (needs at least two to mean anything).
    in_combined = combined_targets(smoked)
    combined = 'not run'
    if len(in_combined) >= 2:
        try:
            b.smoke_combined([groups[n] for n in in_combined], in_combined)       # type: ignore[misc]
            combined = 'ok'
        except (Exception, SystemExit) as exc:
            combined = f'FAILED: {exc}'
            ctx.say(f'combined smoke {combined}')
    results['combined'] = combined if len(in_combined) >= 2 else 'not run (fewer than two verified wheels)'

    # Only verified wheels reach --out, and nothing there is ever overwritten.
    copied: list[Path] = []
    for name in smoked:
        for whl in _wheels(ctx, groups[name]):             # type: ignore[arg-type]
            dest = out / whl.name
            if dest.exists():
                ctx.say(f'exists, not overwriting: {dest.name}')
                continue
            ctx.say(f'publish {whl.name}')
            shutil.copy2(whl, dest)
            copied.append(dest)
        results[name] = 'ok'
    if not ctx.dry:
        sums = out / 'SHA256SUMS'
        known = sums.read_text().splitlines() if sums.exists() else []
        for whl in copied:
            known.append(f'{sha256_file(whl)}  {whl.name}')
        if copied:
            sums.write_text('\n'.join(known) + '\n')
        info = next_free(out / 'build-info.json')
        info.write_text(json.dumps({
            'started_utc': started,
            'runtime': {'pbs_release': PBS_RELEASE, 'python': PBS_PYVER, 'sha256': PBS_SHA256, 'url': PBS_URL},
            'tools': {'cython': CYTHON, 'numpy_build': NUMPY_BUILD, 'requirements': list(BUILD_REQUIREMENTS),
                      'rust': RUST_VERSION, 'maturin': MATURIN_VERSION},
            'build_environment': b.facts,
            'sources': describe_sources(wanted),
            'results': results,
            'wheels': {w.name: sha256_file(w) for w in copied}}, indent=2) + '\n')
        ctx.say(f'wrote {info.name}')

    ctx.say('summary: ' + '; '.join(f'{k}: {v}' for k, v in results.items()))
    failed = [k for k, v in results.items() if not (v == 'ok' or v.startswith('not run'))]
    return 0 if ctx.dry or not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())
