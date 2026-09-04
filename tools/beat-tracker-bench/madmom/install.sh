#!/usr/bin/env bash
# Reproduces the isolated madmom benchmarking venv from scratch.
#
# Dev-only tooling: builds a venv at tools/beat-tracker-bench/madmom/.venv
# (gitignored by the repo's existing `.venv/` rule) with madmom and its
# build/runtime dependencies. Nothing here touches the main project's
# requirements.txt or any system package manager. See README.md for why
# each workaround below is needed.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
MADMOM_REV="${MADMOM_REV:-27f032e8947204902c675e5e341a3faf5dc86dae}"  # main, 2024-08-25

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "error: $PYTHON_BIN not found. madmom's PyPI release (0.16.1) needs" >&2
    echo "Python 3.11 or older for a clean build; see README.md." >&2
    exit 1
fi

echo "==> creating venv at $HERE/.venv with $PYTHON_BIN"
"$PYTHON_BIN" -m venv .venv

VENV_PIP=(.venv/bin/pip)
VENV_PY=.venv/bin/python

echo "==> installing pinned build/runtime prerequisites"
"${VENV_PIP[@]}" install --upgrade pip
"${VENV_PIP[@]}" install "setuptools<70" "numpy<2" "cython==3.0.11"

echo "==> cloning madmom (main branch, not the broken 0.16.1 PyPI sdist)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
git clone --depth 1 https://github.com/CPJKU/madmom.git "$WORKDIR/madmom"
git -C "$WORKDIR/madmom" checkout "$MADMOM_REV"

echo "==> fetching the pretrained-model submodule (CC BY-NC-SA 4.0, see README.md)"
git -C "$WORKDIR/madmom" submodule update --init --recursive

echo "==> building madmom from source (regenerates Cython .c files fresh)"
find "$WORKDIR/madmom" -name "*.c" -delete
"${VENV_PIP[@]}" install --no-build-isolation "$WORKDIR/madmom"

echo "==> smoke-testing the install"
"$VENV_PY" -c "import madmom; from madmom.features.beats import RNNBeatProcessor, DBNBeatTrackingProcessor; print('madmom', madmom.__version__, 'OK')"

echo "==> done. Run the self-test with: .venv/bin/python self_test.py"
