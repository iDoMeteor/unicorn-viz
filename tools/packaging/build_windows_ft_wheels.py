#!/usr/bin/env python3
"""Build the Windows (win_amd64) cp314t wheels for free-threaded Python.

moderngl, glcontext, python-rtmidi, opencv-python-headless and sphn have no
upstream wheel for free-threaded 3.14 (see docs/planning/free-threaded-wheels-
2026-09-30.md).  The Linux ones are built by ``build_ft_wheels.sh``,
``build_ft_opencv_wheel.sh`` and ``build_ft_sphn_wheel.sh``; this builds the
Windows ones, meant to be run by a ``windows-2022`` GitHub Actions job (the
workflow file belongs to the installer team; this script is what it calls).

    python tools/packaging/build_windows_ft_wheels.py --out DIR [--work DIR]
                                                      [--only NAME[,NAME...]] [--dry-run]

It uses the standard library only, so any Python that happens to be installed
can launch it.  It downloads and verifies the python-build-standalone 3.14
free-threaded Windows runtime (the same release the installers bundle), makes a
build venv from it, finds MSVC through vswhere and imports ``vcvars64`` itself,
then builds each target against that interpreter, smoke-tests each wheel in a
fresh venv, and only then copies it to ``--out``.  A wheel that fails its smoke
test is not left in ``--out``; the run exits non-zero if any target failed.

Version pins are *read from the Linux scripts* (they are the single source), so
the two platforms cannot drift apart.

Outputs in ``--out``: the wheels, ``SHA256SUMS`` and ``build-info.json``.  The
output directory is only ever added to: an existing file is never overwritten.

NOT yet exercised on a Windows machine: it was written against the runtime's
layout (python.exe, include/, libs/python314t.lib) and checked in ``--dry-run``
and by unit tests on Linux.  Expect the first runner run to need a fix or two.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
IS_WIN = sys.platform == 'win32'

PBS_RELEASE = '20260929'
PBS_PYVER = '3.14.7'
PBS_ASSET = (f'cpython-{PBS_PYVER}+{PBS_RELEASE}-x86_64-pc-windows-msvc-'
             'freethreaded-install_only.tar.gz')
#: From the release's SHA256SUMS (the installers pin the same build).
PBS_SHA256 = '00502edc9de197a4b2e0ed01f31aabaa8dd31b569d2202f471f97fdcc4424f85'
PBS_URL = ('https://github.com/astral-sh/python-build-standalone/releases/download/'
           f'{PBS_RELEASE}/{urllib.parse.quote(PBS_ASSET)}')

TARGETS = ('moderngl', 'glcontext', 'python-rtmidi', 'opencv', 'sphn')


# --------------------------------------------------------------------------- pins
def _grep(path: Path, pattern: str) -> re.Match[str]:
    m = re.search(pattern, path.read_text(), re.M)
    if m is None:
        raise SystemExit(f'pin not found in {path.name}: {pattern}')
    return m


def read_pins() -> dict[str, str]:
    """Collect every version / hash this build needs from the Linux recipes."""
    wheels = HERE / 'build_ft_wheels.sh'
    opencv = HERE / 'build_ft_opencv_wheel.sh'
    sphn = HERE / 'build_ft_sphn_wheel.sh'
    toolchain = HERE / 'ft-sphn' / 'Containerfile'
    pins: dict[str, str] = {}
    for name in ('moderngl', 'glcontext', 'python_rtmidi'):
        m = _grep(wheels, rf'^PIN_{name}="([0-9][0-9.]*) ([0-9a-f]{{64}})"$')
        pins[f'{name}_version'], pins[f'{name}_sha256'] = m[1], m[2]
    pins['cython'] = _grep(wheels, r'^CYTHON_VERSION="([0-9.]+)"$')[1]
    pins['rtmidi_build_tag'] = _grep(wheels, r'^RTMIDI_BUILD_TAG="([0-9]+)"$')[1]
    for key in ('OPENCV_PYTHON_VERSION', 'OPENCV_PYTHON_TAG', 'OPENCV_PYTHON_COMMIT',
                'OPENCV_COMMIT', 'NUMPY_BUILD'):
        pins[key.lower()] = _grep(opencv, rf'^{key}="([^"]+)"$')[1]
    pins['sphn_version'] = _grep(sphn, r'^SPHN_VERSION="([^"]+)"$')[1]
    pins['sphn_sha256'] = _grep(sphn, r'^SPHN_SDIST_SHA256="([0-9a-f]{64})"$')[1]
    pins['rust_version'] = _grep(toolchain, r'^ARG RUST_VERSION=([0-9.]+)$')[1]
    pins['maturin_version'] = _grep(toolchain, r'^ARG MATURIN_VERSION=([0-9.]+)$')[1]
    return pins


# ------------------------------------------------------------------- run helpers
class Ctx:
    """Everything that touches the outside world goes through here, so
    ``--dry-run`` can print the plan without doing any of it."""

    def __init__(self, work: Path, out: Path, dry_run: bool) -> None:
        self.work, self.out, self.dry = work, out, dry_run
        self.env: dict[str, str] = dict(os.environ)

    def say(self, msg: str) -> None:
        print(f'[build-win-ft] {msg}', flush=True)

    def run(self, cmd: list[str | Path], *, cwd: Path | None = None,
            env: dict[str, str] | None = None) -> None:
        shown = ' '.join(str(c) for c in cmd)
        self.say(f'$ {shown}' + (f'   (in {cwd})' if cwd else ''))
        if self.dry:
            return
        subprocess.run([str(c) for c in cmd], cwd=cwd, env=env or self.env, check=True)

    def capture(self, cmd: list[str | Path]) -> str:
        if self.dry:
            return ''
        return subprocess.check_output([str(c) for c in cmd], text=True, env=self.env).strip()

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
            got = hashlib.sha256(dest.read_bytes()).hexdigest()
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


def msvc_env(ctx: Ctx) -> dict[str, str]:
    """The environment ``vcvars64.bat`` sets up (the MSVC compiler, linker and
    SDK paths), found through vswhere, so no workflow step has to do it."""
    env = dict(os.environ)
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
    for line in dump.splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            env[key] = value
    ctx.say(f'MSVC environment from {vcvars}')
    return env


# ------------------------------------------------------------------ the builds
class Build:
    def __init__(self, ctx: Ctx, pins: dict[str, str]) -> None:
        self.ctx, self.pins = ctx, pins
        self.py_root = ctx.work / 'python'
        self.venv = ctx.work / 'venv'
        self.raw = ctx.work / 'raw'
        self.src = ctx.work / 'src'

    # -- toolchain ---------------------------------------------------------
    def bootstrap(self) -> None:
        ctx, p = self.ctx, self.pins
        archive = ctx.work / PBS_ASSET
        ctx.download(PBS_URL, archive, PBS_SHA256)
        ctx.say(f'extract the free-threaded {PBS_PYVER} runtime to {self.py_root}')
        if not ctx.dry:
            if self.py_root.exists():
                shutil.rmtree(self.py_root)
            with tarfile.open(archive) as tf:
                tf.extractall(ctx.work, filter='data') if hasattr(tarfile, 'data_filter') else tf.extractall(ctx.work)
        base_py = self.py_root / ('python.exe' if IS_WIN else 'bin/python3')
        ctx.run([base_py, '-m', 'venv', self.venv])
        py = venv_python(self.venv)
        ctx.run([py, '-m', 'pip', 'install', '-q', '--upgrade', 'pip'])
        ctx.run([py, '-m', 'pip', 'install', '-q', 'setuptools', 'wheel', 'packaging', 'build',
                 'scikit-build', 'cmake', 'ninja', 'meson', 'meson-python',
                 f'cython=={p["cython"]}', f'numpy=={p["numpy_build"]}',
                 f'maturin=={p["maturin_version"]}'])
        ctx.say('MSVC environment')
        ctx.env = msvc_env(ctx)
        scripts = str(self.venv / ('Scripts' if IS_WIN else 'bin'))
        ctx.env['PATH'] = scripts + os.pathsep + ctx.env.get('PATH', '')
        ctx.env['CMAKE_BUILD_PARALLEL_LEVEL'] = str(os.cpu_count() or 4)
        # libopus's bundled CMakeLists predates CMake 4's floor (see build_ft_sphn_wheel.sh).
        ctx.env['CMAKE_POLICY_VERSION_MINIMUM'] = '3.5'

    def _wheel_from(self, tree: Path, name: str, *, remove: str | None = None) -> None:
        py = venv_python(self.venv)
        out = self.raw / name
        if not self.ctx.dry:
            shutil.rmtree(out, ignore_errors=True)
            out.mkdir(parents=True)
        if remove and not self.ctx.dry:
            (tree / remove).unlink(missing_ok=True)
        self.ctx.run([py, '-m', 'pip', 'wheel', '--no-build-isolation', '--no-deps',
                      '-w', out, '.'], cwd=tree)

    # -- targets: each returns (smoke group, wheels dir) -------------------
    def moderngl(self) -> Path:
        p = self.pins
        tree = self.ctx.pypi_sdist('moderngl', p['moderngl_version'], p['moderngl_sha256'], self.src)
        self._wheel_from(tree, 'moderngl')
        return self.raw / 'moderngl'

    def glcontext(self) -> Path:
        p = self.pins
        tree = self.ctx.pypi_sdist('glcontext', p['glcontext_version'], p['glcontext_sha256'], self.src)
        self._wheel_from(tree, 'glcontext')
        return self.raw / 'glcontext'

    def python_rtmidi(self) -> Path:
        p = self.pins
        tree = self.ctx.pypi_sdist('python-rtmidi', p['python_rtmidi_version'],
                                   p['python_rtmidi_sha256'], self.src)
        # The sdist's pre-generated C++ came from Cython 3.0.5 (before free-threading
        # support); delete it so meson regenerates it with the pinned Cython.
        self._wheel_from(tree, 'python-rtmidi', remove='src/_rtmidi.cpp')
        py = venv_python(self.venv)
        for whl in ([] if self.ctx.dry else sorted((self.raw / 'python-rtmidi').glob('*.whl'))):
            self.ctx.run([py, '-m', 'wheel', 'tags', '--build', p['rtmidi_build_tag'], '--remove', whl])
        return self.raw / 'python-rtmidi'

    def opencv(self) -> Path:
        ctx, p = self.ctx, self.pins
        tree = self.src / 'opencv-python'
        if not tree.exists() or ctx.dry:
            ctx.run(['git', 'clone', '-q', '--depth', '1', '--branch', p['opencv_python_tag'],
                     'https://github.com/opencv/opencv-python.git', tree])
        ctx.run(['git', '-C', tree, 'submodule', 'update', '-q', '--init', '--depth', '1', 'opencv'])
        if not ctx.dry:
            for repo, want in ((tree, p['opencv_python_commit']), (tree / 'opencv', p['opencv_commit'])):
                got = ctx.capture(['git', '-C', repo, 'rev-parse', 'HEAD'])
                if got != want:
                    raise SystemExit(f'{repo} is at {got}, expected {want}')
            # The stable ABI cannot exist on a free-threaded build: drop the hard-coded flag.
            setup = tree / 'setup.py'
            lines = setup.read_text().splitlines(keepends=True)
            kept = [ln for ln in lines if ln.strip() != '"-DPYTHON3_LIMITED_API=ON",']
            if len(kept) != len(lines) - 1:
                raise SystemExit('expected exactly one hard-coded PYTHON3_LIMITED_API line in setup.py')
            setup.write_text(''.join(kept))
        else:
            ctx.say('edit setup.py: remove the hard-coded "-DPYTHON3_LIMITED_API=ON",')
        py = venv_python(self.venv)
        base = Path(ctx.capture([py, '-c', 'import sys; print(sys.base_prefix)']) or str(self.py_root))
        env = dict(ctx.env)
        env.update(ENABLE_HEADLESS='1', CI_BUILD='1', OPENCV_PYTHON_SKIP_GIT_COMMANDS='1',
                   # scikit-build may not recognise the free-threaded import library's name.
                   CMAKE_ARGS=(f'-DPYTHON3_LIBRARY={(base / "libs" / "python314t.lib").as_posix()} '
                               f'-DPYTHON3_INCLUDE_DIR={(base / "include").as_posix()}'))
        out = self.raw / 'opencv'
        if not ctx.dry:
            shutil.rmtree(out, ignore_errors=True)
            out.mkdir(parents=True)
        # Windows: OpenCV's own CMake downloads its documented-LGPL FFmpeg plugin
        # DLL (pinned by hash), so nothing is built for FFmpeg here.
        ctx.run([py, '-m', 'pip', 'wheel', '--no-build-isolation', '--no-deps', '-w', out, '.'],
                cwd=tree, env=env)
        return out

    def sphn(self) -> Path:
        ctx, p = self.ctx, self.pins
        tree = ctx.pypi_sdist('sphn', p['sphn_version'], p['sphn_sha256'], self.src)
        ctx.run(['rustup', 'toolchain', 'install', p['rust_version'], '--profile', 'minimal'])
        env = dict(ctx.env)
        env['RUSTUP_TOOLCHAIN'] = p['rust_version']
        out = self.raw / 'sphn'
        if not ctx.dry:
            shutil.rmtree(out, ignore_errors=True)
            out.mkdir(parents=True)
        ctx.run(['maturin', 'build', '--release', '--locked', '--interpreter',
                 venv_python(self.venv), '--out', out], cwd=tree, env=env)
        return out

    # -- smoke -------------------------------------------------------------
    def smoke(self, group: str, wheel_dirs: list[Path], script: str, extra: list[str],
              needs_numpy: bool) -> None:
        ctx = self.ctx
        venv = ctx.work / f'smoke-{group}'
        if not ctx.dry:
            shutil.rmtree(venv, ignore_errors=True)
        base_py = self.py_root / ('python.exe' if IS_WIN else 'bin/python3')
        ctx.run([base_py, '-m', 'venv', venv])
        py = venv_python(venv)
        if needs_numpy:
            ctx.run([py, '-m', 'pip', 'install', '-q', 'numpy'])
        find = [arg for d in wheel_dirs for arg in ('--find-links', str(d))]
        names = sorted({_dist_name(w) for d in wheel_dirs for w in _wheels(ctx, d)}) or ['<wheels>']
        ctx.run([py, '-m', 'pip', 'install', '-q', '--no-index', '--no-deps', *find, *names])
        ctx.run([py, HERE / script, *extra])


def _wheels(ctx: Ctx, directory: Path) -> list[Path]:
    return [] if ctx.dry else sorted(directory.glob('*.whl'))


def _dist_name(wheel: Path) -> str:
    return wheel.name.split('-')[0].replace('_', '-')


# ------------------------------------------------------------------------ main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--out', type=Path, required=True, help='where finished wheels are added')
    ap.add_argument('--work', type=Path, default=Path('_wheel-build'), help='scratch directory')
    ap.add_argument('--only', default=','.join(TARGETS), help=f'comma list of: {", ".join(TARGETS)}')
    ap.add_argument('--dry-run', action='store_true', help='print the plan, do nothing')
    args = ap.parse_args(argv)

    wanted = [t.strip() for t in args.only.split(',') if t.strip()]
    unknown = [t for t in wanted if t not in TARGETS]
    if unknown:
        ap.error(f'unknown target(s): {", ".join(unknown)}')
    if not IS_WIN and not args.dry_run:
        ap.error('this builds Windows wheels and must run on Windows (use --dry-run elsewhere)')

    pins = read_pins()
    work = args.work.resolve()
    out = args.out.resolve()
    ctx = Ctx(work, out, args.dry_run)
    if not args.dry_run:
        work.mkdir(parents=True, exist_ok=True)
        out.mkdir(parents=True, exist_ok=True)
    b = Build(ctx, pins)
    ctx.say(f'targets: {", ".join(wanted)}; runtime PBS {PBS_RELEASE} / {PBS_PYVER} freethreaded')
    b.bootstrap()

    results: dict[str, str] = {}
    groups: dict[str, Path] = {}
    gl_group = {'moderngl', 'glcontext', 'python-rtmidi'}

    def attempt(name: str, fn) -> Path | None:
        try:
            wheel_dir = fn()
            results[name] = 'built'
            return wheel_dir
        except (subprocess.CalledProcessError, SystemExit, OSError) as exc:
            results[name] = f'BUILD FAILED: {exc}'
            ctx.say(results[name])
            return None

    for name in wanted:
        if name in gl_group:
            groups[name] = attempt(name, getattr(b, name.replace('-', '_')))
        elif name == 'opencv':
            groups[name] = attempt(name, b.opencv)
        elif name == 'sphn':
            groups[name] = attempt(name, b.sphn)

    smoked: dict[str, tuple[str, list[Path]]] = {}
    gl = [groups[n] for n in wanted if n in gl_group and groups.get(n) is not None]
    if gl and len(gl) == len([n for n in wanted if n in gl_group]):
        try:
            b.smoke('gl-midi', gl, 'ft_wheels_smoke.py', ['--skip-gl'], needs_numpy=False)
            for n in wanted:
                if n in gl_group:
                    smoked[n] = ('ok', [groups[n]])
        except (subprocess.CalledProcessError, SystemExit, OSError) as exc:
            for n in wanted:
                if n in gl_group:
                    results[n] = f'SMOKE FAILED: {exc}'
    for name, script in (('opencv', 'ft_opencv_smoke.py'), ('sphn', 'ft_sphn_smoke.py')):
        if name in wanted and groups.get(name) is not None:
            try:
                b.smoke(name, [groups[name]], script, [], needs_numpy=True)
                smoked[name] = ('ok', [groups[name]])
            except (subprocess.CalledProcessError, SystemExit, OSError) as exc:
                results[name] = f'SMOKE FAILED: {exc}'

    # Only verified wheels reach --out, and nothing there is ever overwritten.
    copied: list[Path] = []
    for name, (_, dirs) in smoked.items():
        for d in dirs:
            for whl in _wheels(ctx, d):
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
            known.append(f'{hashlib.sha256(whl.read_bytes()).hexdigest()}  {whl.name}')
        if copied:
            sums.write_text('\n'.join(known) + '\n')
        (out / 'build-info.json').write_text(json.dumps(
            {'runtime': {'pbs_release': PBS_RELEASE, 'python': PBS_PYVER, 'sha256': PBS_SHA256},
             'pins': pins, 'results': results, 'wheels': [w.name for w in copied]}, indent=2) + '\n')

    ctx.say('summary: ' + '; '.join(f'{k}: {v}' for k, v in results.items()))
    failed = [k for k, v in results.items() if v != 'ok']
    return 0 if ctx.dry or not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())
