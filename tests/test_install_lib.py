"""Regression tests for the bash installer library (``tools/install/lib.sh``).

Covers the helpers that hand-off bundles depend on: manifest-relative URL
resolution and ``file://`` fetches, which must work with no network at all.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / 'tools' / 'install' / 'lib.sh'


def _bash(snippet: str) -> str:
    proc = subprocess.run(
        ['bash', '-c', f'source "{_LIB}"; {snippet}'],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_resolve_url_keeps_absolute_urls() -> None:
    out = _bash('uv_resolve_url "https://get.example/manifest.json" "https://cdn.example/x.tar.gz"')
    assert out == 'https://cdn.example/x.tar.gz'


def test_resolve_url_joins_relative_onto_manifest_dir() -> None:
    out = _bash('uv_resolve_url "file:///bundle/manifest.json" "1.0.0/unicorn-viz-1.0.0.tar.gz"')
    assert out == 'file:///bundle/1.0.0/unicorn-viz-1.0.0.tar.gz'
    out = _bash('uv_resolve_url "https://get.example/rel/manifest.json" "1.0.0/SHA256SUMS"')
    assert out == 'https://get.example/rel/1.0.0/SHA256SUMS'


def test_fetch_to_file_supports_file_urls(tmp_path: Path) -> None:
    src = tmp_path / 'a.txt'
    src.write_text('hello')
    dst = tmp_path / 'b.txt'
    _bash(f'uv_fetch_to_file "file://{src}" "{dst}"')
    assert dst.read_text() == 'hello'
    proc = subprocess.run(['bash', '-c', f'source "{_LIB}"; uv_fetch_to_file "file://{tmp_path}/missing" "{dst}"'],
                          capture_output=True, text=True, timeout=30, check=False)
    assert proc.returncode != 0, 'a missing file:// source must fail'


# --- W1/W2: runtime flavor, wheelhouse, drop-in dependency installs ----------

def test_runtime_flavor_defaults_and_override(tmp_path: Path) -> None:
    assert _bash('UV_RUNTIME_FLAVOR=gil uv_runtime_flavor') == 'gil'
    assert _bash('UV_RUNTIME_FLAVOR=ft uv_runtime_flavor') == 'ft'
    src = tmp_path / 'src'
    (src / 'wheelhouse').mkdir(parents=True)
    bare = tmp_path / 'bare'
    bare.mkdir()
    base = 'unset UV_RUNTIME_FLAVOR UV_WHEELHOUSE; uname() { echo %s; }; '
    # free-threaded only where our cp314t wheels exist: x86-64 + a wheelhouse
    assert _bash(base % 'x86_64' + f'uv_runtime_flavor "{src}"') == 'ft'
    assert _bash(base % 'x86_64' + f'uv_runtime_flavor "{bare}"') == 'gil'
    assert _bash(base % 'x86_64' + 'uv_runtime_flavor ""') == 'gil'
    assert _bash(base % 'aarch64' + f'uv_runtime_flavor "{src}"') == 'gil'


def test_wheelhouse_args_prefers_payload_then_env(tmp_path: Path) -> None:
    src = tmp_path / 'src'
    src.mkdir()
    assert _bash(f'unset UV_WHEELHOUSE; uv_wheelhouse_args "{src}"') == ''
    env_wh = tmp_path / 'envwh'
    env_wh.mkdir()
    assert _bash(f'UV_WHEELHOUSE="{env_wh}" uv_wheelhouse_args "{src}"') == f'--find-links {env_wh}'
    (src / 'wheelhouse').mkdir()
    assert _bash(f'UV_WHEELHOUSE="{env_wh}" uv_wheelhouse_args "{src}"') == f'--find-links {src}/wheelhouse'


def test_dropin_requirement_files_from_clone(tmp_path: Path) -> None:
    (tmp_path / 'drop-ins' / 'a-01').mkdir(parents=True)
    (tmp_path / 'drop-ins' / 'a-01' / 'requirements.txt').write_text('av>=13  # decode\n')
    (tmp_path / 'drop-ins' / 'b-01').mkdir()
    (tmp_path / 'drop-ins' / 'b-01' / 'requirements.txt').write_text('# no deps\n\n')
    (tmp_path / 'drop-ins' / 'c-01').mkdir()  # no requirements file at all
    out = _bash(f'uv_dropin_requirement_files "{tmp_path}"')
    assert out.splitlines() == [f'{tmp_path}/drop-ins/a-01/requirements.txt']


def test_dropin_union_file_wins_over_clone_files(tmp_path: Path) -> None:
    (tmp_path / 'drop-ins' / 'a-01').mkdir(parents=True)
    (tmp_path / 'drop-ins' / 'a-01' / 'requirements.txt').write_text('av>=13\n')
    (tmp_path / 'requirements-dropins.txt').write_text('mutagen\n')
    out = _bash(f'uv_dropin_requirement_files "{tmp_path}"')
    assert out == f'{tmp_path}/requirements-dropins.txt'


def test_optional_install_falls_back_per_line_and_never_fails(tmp_path: Path) -> None:
    # Stub pip: fails whenever the unresolvable package is requested, whether
    # in a whole-file call (-r) or alone, and logs the requirements it accepted.
    log = tmp_path / 'ok.log'
    pip = tmp_path / 'pip'
    pip.write_text(
        '#!/usr/bin/env bash\n'
        'args="$*"\n'
        'prev=""; for a in "$@"; do if [[ "$prev" == -r ]]; then grep -q nosuchpkg "$a" && exit 1; exit 0; fi; prev="$a"; done\n'
        '[[ "$args" == *nosuchpkg* ]] && exit 1\n'
        f'echo "$args" >> "{log}"; exit 0\n'
    )
    pip.chmod(0o755)
    req = tmp_path / 'req.txt'
    req.write_text('av>=13   # decode\n# comment\n\nnosuchpkg>=1\nmutagen\n')
    constraints = tmp_path / 'constraints.txt'
    constraints.write_text('numpy==1\n')
    proc = subprocess.run(
        ['bash', '-c', f'source "{_LIB}"; uv_pip_install_optional "{pip}" "{constraints}" "{req}" --find-links /wh'],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert 'Skipped nosuchpkg>=1' in proc.stderr
    accepted = log.read_text()
    assert 'av>=13' in accepted and 'mutagen' in accepted
    assert '-c ' + str(constraints) in accepted and '--find-links /wh' in accepted


def test_optional_install_keeps_mediapipe_off_the_resolver(tmp_path: Path) -> None:
    # mediapipe's dependency chain drags in opencv-contrib-python, which owns
    # the same cv2 import path as the core's opencv-python-headless: it must go
    # in with --no-deps, never inside the file-wide resolve.
    log = tmp_path / 'calls.log'
    pip = tmp_path / 'pip'
    pip.write_text(
        '#!/usr/bin/env bash\n'
        f'echo "$*" >> "{log}"\n'
        'prev=""; for a in "$@"; do if [[ "$prev" == -r ]]; then cp "$a" "' + str(tmp_path) + '/filtered.txt"; fi; prev="$a"; done\n'
        'exit 0\n'
    )
    pip.chmod(0o755)
    req = tmp_path / 'req.txt'
    req.write_text('mediapipe==1.0.0\nav>=13\n')
    constraints = tmp_path / 'c.txt'
    constraints.write_text('')
    proc = subprocess.run(
        ['bash', '-c', f'source "{_LIB}"; uv_pip_install_optional "{pip}" "{constraints}" "{req}"'],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    calls = log.read_text().splitlines()
    assert any('--no-deps' in c and 'mediapipe==1.0.0' in c for c in calls)
    assert any('absl-py' in c and 'flatbuffers' in c and '--no-deps' not in c for c in calls)
    assert (tmp_path / 'filtered.txt').read_text().split() == ['av>=13']


def _torch_calls(tmp_path: Path, reqs: str, env: str = '') -> list[str]:
    log = tmp_path / 'calls.log'
    pip = tmp_path / 'pip'
    pip.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{log}"\nexit 0\n')
    pip.chmod(0o755)
    req = tmp_path / 'req.txt'
    req.write_text(reqs)
    (tmp_path / 'c.txt').write_text('')
    proc = subprocess.run(
        ['bash', '-c', f'source "{_LIB}"; {env} uv_preinstall_cpu_torch "{pip}" "{tmp_path}/c.txt" "{req}" --find-links /wh'],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return log.read_text().splitlines() if log.exists() else []


def test_cpu_torch_is_preinstalled_for_demucs_from_the_cpu_index(tmp_path: Path) -> None:
    calls = _torch_calls(tmp_path, 'av>=13\ndemucs>=4.0\n')
    assert len(calls) == 2
    assert '--no-deps' in calls[0] and 'https://download.pytorch.org/whl/cpu' in calls[0]
    assert calls[0].endswith('torch torchaudio')
    assert '--index-url' not in calls[1] and calls[1].endswith('torch torchaudio')


def test_cpu_torch_is_skipped_without_torch_users_or_when_cuda_requested(tmp_path: Path) -> None:
    (tmp_path / 'a').mkdir()
    assert _torch_calls(tmp_path / 'a', 'av>=13\nmutagen\n') == []
    (tmp_path / 'b').mkdir()
    assert _torch_calls(tmp_path / 'b', 'demucs>=4.0\n', env='UV_TORCH_CUDA=1') == []
