#!/usr/bin/env bash
set -euo pipefail

# Distro-aware installer for Unicorn Viz dependencies and Python environment.
# Usage:
#   ./tools/install_linux.sh
#   ./tools/install_linux.sh --python python3.11

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/install/lib.sh"

PYTHON_BIN="python3"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
NO_DEPS=0
UV_DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --no-deps)
      NO_DEPS=1
      shift
      ;;
    --dry-run)
      UV_DRY_RUN=1
      shift
      ;;
    *)
      uv_die "Unknown argument: $1"
      ;;
  esac
done

if [[ ! -f "$PROJECT_ROOT/requirements.txt" ]]; then
  uv_die "requirements.txt not found at $PROJECT_ROOT"
fi

uv_require_cmd "$PYTHON_BIN"

if [[ "$NO_DEPS" -eq 0 ]]; then
  uv_install_system_deps "$PYTHON_BIN"
else
  uv_log "Skipping system dependency installation"
fi

uv_create_venv_and_install "$PYTHON_BIN" "$PROJECT_ROOT/.venv" "$PROJECT_ROOT"

uv_log "Install complete. Run: ./run.sh"
