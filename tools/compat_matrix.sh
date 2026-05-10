#!/usr/bin/env bash
set -euo pipefail

# Containerized compatibility matrix smoke test for Linux distros.
# This script does not modify the host OS.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

docker version >/dev/null

run_ubuntu() {
  docker run --rm -v "$PROJECT_ROOT":/src -w /src ubuntu:22.04 bash -lc '
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y python3.11 python3.11-venv python3.11-dev python3-pip \
      libsdl2-dev libgl1-mesa-dev libffi-dev libpipewire-0.3-dev libasound2-dev
    python3.11 -m venv /tmp/uv-matrix-venv
    /tmp/uv-matrix-venv/bin/pip install --upgrade pip wheel
    /tmp/uv-matrix-venv/bin/pip install -r requirements.txt
    /tmp/uv-matrix-venv/bin/python -m unicornviz --help >/dev/null
    /tmp/uv-matrix-venv/bin/python - << "EOF"
from unicornviz.effects.registry import get_effects
assert len(get_effects()) > 0
print("ubuntu22.04 effect_count", len(get_effects()))
EOF
  '
}

run_debian() {
  docker run --rm -v "$PROJECT_ROOT":/src -w /src debian:12 bash -lc '
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y python3 python3-venv python3-dev python3-pip \
      libsdl2-dev libgl1-mesa-dev libffi-dev libpipewire-0.3-dev libasound2-dev
    python3 -m venv /tmp/uv-matrix-venv
    /tmp/uv-matrix-venv/bin/pip install --upgrade pip wheel
    /tmp/uv-matrix-venv/bin/pip install -r requirements.txt
    /tmp/uv-matrix-venv/bin/python -m unicornviz --help >/dev/null
    /tmp/uv-matrix-venv/bin/python - << "EOF"
from unicornviz.effects.registry import get_effects
assert len(get_effects()) > 0
print("debian12 effect_count", len(get_effects()))
EOF
  '
}

run_fedora() {
  docker run --rm -v "$PROJECT_ROOT":/src -w /src fedora:44 bash -lc '
    set -euo pipefail
    dnf install -y python3 python3-devel python3-pip gcc-c++ make \
      SDL2-devel mesa-libGL-devel libffi-devel pipewire-devel alsa-lib-devel
    python3 -m venv /tmp/uv-matrix-venv
    /tmp/uv-matrix-venv/bin/pip install --upgrade pip wheel
    /tmp/uv-matrix-venv/bin/pip install -r requirements.txt
    /tmp/uv-matrix-venv/bin/python -m unicornviz --help >/dev/null
    /tmp/uv-matrix-venv/bin/python - << "EOF"
from unicornviz.effects.registry import get_effects
assert len(get_effects()) > 0
print("fedora44 effect_count", len(get_effects()))
EOF
  '
}

echo "[matrix] ubuntu:22.04"
run_ubuntu

echo "[matrix] debian:12"
run_debian

echo "[matrix] fedora:44"
run_fedora

echo "Compatibility matrix checks passed."
