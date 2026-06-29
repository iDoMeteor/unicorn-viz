#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib.sh"

PREFIX="${UV_DEFAULT_PREFIX}"
UV_DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix)
      PREFIX="$2"
      shift 2
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

uv_log "Removing Unicorn Viz installation from ${PREFIX}"
uv_uninstall_installation "$PREFIX"
