#!/usr/bin/env bash
set -euo pipefail

# Distro-aware installer for Unicorn Viz dependencies and Python environment.
# Usage:
#   ./tools/install_linux.sh
#   ./tools/install_linux.sh --python python3.11

PYTHON_BIN="python3"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

if [[ ! -f "$PROJECT_ROOT/requirements.txt" ]]; then
  echo "requirements.txt not found at $PROJECT_ROOT"
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python executable not found: $PYTHON_BIN"
  exit 1
fi

if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
else
  echo "Cannot detect Linux distribution (missing /etc/os-release)."
  exit 1
fi

install_apt() {
  sudo apt-get update
  sudo apt-get install -y \
    "$PYTHON_BIN" "${PYTHON_BIN}-venv" "${PYTHON_BIN}-dev" \
    libsdl2-dev libgl1-mesa-dev libffi-dev \
    libpipewire-0.3-dev libasound2-dev ffmpeg git
}

install_dnf() {
  sudo dnf install -y \
    "$PYTHON_BIN" "${PYTHON_BIN}-devel" gcc-c++ make \
    SDL2-devel mesa-libGL-devel libffi-devel \
    pipewire-devel alsa-lib-devel git
  if ! sudo dnf install -y ffmpeg; then
    echo "Warning: ffmpeg not available in default Fedora repos."
    echo "         Enable RPM Fusion if recording support is required."
  fi
}

install_pacman() {
  sudo pacman -Sy --noconfirm \
    python python-pip sdl2 mesa libffi pipewire alsa-lib ffmpeg git
}

case "${ID:-}" in
  ubuntu|debian)
    install_apt
    ;;
  fedora)
    install_dnf
    ;;
  arch)
    install_pacman
    ;;
  *)
    echo "Unsupported distribution: ${ID:-unknown}"
    echo "Please install deps manually (SDL2/OpenGL/FFI/PipeWire/ALSA/ffmpeg) and rerun."
    exit 1
    ;;
esac

cd "$PROJECT_ROOT"
"$PYTHON_BIN" -m venv .venv
.venv/bin/pip install --upgrade pip wheel
.venv/bin/pip install -r requirements.txt

echo "Install complete. Run: ./run.sh"
