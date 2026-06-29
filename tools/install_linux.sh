#!/usr/bin/env bash
set -Eeuo pipefail

# Distro-aware installer for Unicorn Viz dependencies and Python environment.
# By default a self-contained python-build-standalone runtime is bundled into
# .venv-runtime/ and the .venv is built from it, so a clone never depends on the
# system interpreter. Pass --system-python to build the venv from a system Python.
#
# Usage:
#   ./tools/install_linux.sh
#   ./tools/install_linux.sh --system-python --python python3.11

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/install/lib.sh"

trap 'uv_err_trap "$LINENO" "$BASH_COMMAND"' ERR

PYTHON_BIN="python3"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
NO_DEPS=0
SYSTEM_PYTHON=0
UV_DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --system-python)
      SYSTEM_PYTHON=1
      shift
      ;;
    --no-deps)
      NO_DEPS=1
      shift
      ;;
    --dry-run)
      # UV_DRY_RUN is read by lib.sh's uv_run; cross-file use is invisible here.
      # shellcheck disable=SC2034
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

if [[ "$NO_DEPS" -eq 0 ]]; then
  uv_install_system_deps "$PYTHON_BIN"
else
  uv_log "Skipping system dependency installation"
fi

if [[ "$SYSTEM_PYTHON" -eq 1 ]]; then
  uv_log "Using system Python: ${PYTHON_BIN} (bundled runtime skipped)"
  uv_require_cmd "$PYTHON_BIN"
  PY="$PYTHON_BIN"
else
  uv_log "Provisioning bundled Python runtime"
  PY="$(uv_provision_runtime "$PROJECT_ROOT/.venv-runtime")"
fi

uv_create_venv_and_install "$PY" "$PROJECT_ROOT/.venv" "$PROJECT_ROOT"

uv_log "Install complete. Run: ./run.sh"
