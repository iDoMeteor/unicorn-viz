#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_PATH="${SCRIPT_DIR}/tools/install/lib.sh"

if [[ -f "$LIB_PATH" ]]; then
  # shellcheck disable=SC1090,SC1091
  source "$LIB_PATH"
elif [[ -f "${PWD}/tools/install/lib.sh" ]]; then
  # shellcheck disable=SC1090,SC1091
  source "${PWD}/tools/install/lib.sh"
else
  BOOTSTRAP_LIB="$(mktemp)"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --retry 3 --retry-delay 2 \
      "https://raw.githubusercontent.com/djunicorntears/unicorn-viz/main/tools/install/lib.sh" \
      -o "$BOOTSTRAP_LIB"
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$BOOTSTRAP_LIB" \
      "https://raw.githubusercontent.com/djunicorntears/unicorn-viz/main/tools/install/lib.sh"
  else
    echo "[unicorn-viz] ERROR: install.sh requires curl or wget." >&2
    exit 1
  fi
  # shellcheck disable=SC1090
  source "$BOOTSTRAP_LIB"
fi

# Print the failing command/line on any unhandled error (helper from lib.sh).
trap 'uv_err_trap "$LINENO" "$BASH_COMMAND"' ERR

PREFIX="${UV_DEFAULT_PREFIX}"
PYTHON_BIN="python3"
CHANNEL="${UV_DEFAULT_CHANNEL}"
VERSION=""
NO_DEPS=0
NO_DESKTOP=0
UNINSTALL=0
SYSTEM_PYTHON=0

cleanup() {
  if [[ -n "${TMP_DIR:-}" && -d "${TMP_DIR}" ]]; then
    rm -rf "${TMP_DIR}"
  fi
  if [[ -n "${BOOTSTRAP_LIB:-}" && -f "${BOOTSTRAP_LIB}" ]]; then
    rm -f "${BOOTSTRAP_LIB}"
  fi
}
trap cleanup EXIT

usage() {
  cat <<'EOF'
Unicorn Viz Linux installer

Usage:
  ./install.sh [options]

By default a self-contained Python runtime is bundled into <prefix>/runtime so
the install never depends on the system interpreter. Use --system-python to opt
out and build the venv from a system Python instead.

Options:
  --prefix <dir>            Install prefix (default: ~/.local/share/unicorn-viz)
  --system-python           Use a system Python instead of the bundled runtime
  --python <bin>            System Python to use with --system-python (default: python3)
  --version <vX.Y.Z|X.Y.Z>  Install specific version tag
  --channel <stable|prerelease>
                            Release channel when --version is not given
  --no-deps                 Skip system dependency installation
  --no-desktop              Skip desktop/menu integration
  --uninstall               Remove install artifacts
  --dry-run                 Print actions without executing
  -h, --help                Show this help text
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --prefix)
        PREFIX="$2"
        shift 2
        ;;
      --python)
        PYTHON_BIN="$2"
        shift 2
        ;;
      --system-python)
        SYSTEM_PYTHON=1
        shift
        ;;
      --version)
        VERSION="$2"
        shift 2
        ;;
      --channel)
        CHANNEL="$2"
        shift 2
        ;;
      --no-deps)
        NO_DEPS=1
        shift
        ;;
      --no-desktop)
        NO_DESKTOP=1
        shift
        ;;
      --uninstall)
        UNINSTALL=1
        shift
        ;;
      --dry-run)
        UV_DRY_RUN=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        uv_die "Unknown argument: $1"
        ;;
    esac
  done
}

resolve_latest_version() {
  local api_base="https://api.github.com/repos/${UV_REPO_OWNER}/${UV_REPO_NAME}/releases"
  local body

  if [[ "$CHANNEL" == "stable" ]]; then
    body="$(uv_fetch_text "${api_base}/latest")"
  elif [[ "$CHANNEL" == "prerelease" ]]; then
    body="$(uv_fetch_text "${api_base}")"
    body="$(echo "$body" | awk 'BEGIN{RS="\{";FS="\n"} /"prerelease": true/{print "{"$0; exit}')"
  else
    uv_die "Invalid channel: ${CHANNEL}. Expected stable or prerelease."
  fi

  VERSION="$(echo "$body" | sed -n 's/.*"tag_name": "\([^"]*\)".*/\1/p' | head -n 1)"
  VERSION="${VERSION#v}"

  if [[ -z "$VERSION" ]]; then
    uv_die "Could not resolve release version from GitHub API."
  fi
}

download_release_source() {
  local version="$1"
  local tar_name="unicorn-viz-${version}.tar.gz"
  local release_base="https://github.com/${UV_REPO_OWNER}/${UV_REPO_NAME}/releases/download/v${version}"
  local release_tar_url="${release_base}/${tar_name}"
  local fallback_tar_url="https://github.com/${UV_REPO_OWNER}/${UV_REPO_NAME}/archive/refs/tags/v${version}.tar.gz"
  local sums_url="${release_base}/SHA256SUMS"
  local tar_path="${TMP_DIR}/${tar_name}"
  local sums_path="${TMP_DIR}/SHA256SUMS"
  local sums_line=""
  local used_release_asset=0

  uv_log "Downloading Unicorn Viz v${version}"
  if uv_fetch_to_file "$release_tar_url" "$tar_path"; then
    used_release_asset=1
  else
    uv_warn "Release tarball asset not found; falling back to GitHub source archive."
    uv_fetch_to_file "$fallback_tar_url" "$tar_path"
  fi

  if [[ "$used_release_asset" -eq 1 ]]; then
    if [[ "$UV_DRY_RUN" -eq 1 ]]; then
      uv_log "dry-run: checksum verification for ${tar_name}"
    elif uv_fetch_to_file "$sums_url" "$sums_path"; then
      if command -v sha256sum >/dev/null 2>&1; then
        sums_line="$(grep " ${tar_name}$" "$sums_path" || true)"
        if [[ -n "$sums_line" ]]; then
          uv_log "Verifying source tarball checksum"
          (
            cd "$TMP_DIR"
            echo "$sums_line" | sha256sum -c -
          )
        else
          uv_warn "SHA256SUMS does not include ${tar_name}; skipping verification."
        fi
      else
        uv_warn "sha256sum not found; skipping checksum verification."
      fi
    else
      uv_warn "SHA256SUMS asset not found for v${version}; skipping verification."
    fi
  fi

  uv_run tar -xzf "$tar_path" -C "$TMP_DIR"

  SRC_DIR="${TMP_DIR}/${UV_REPO_NAME}-${version}"
  if [[ "$UV_DRY_RUN" -eq 0 && ! -f "${SRC_DIR}/requirements.txt" ]]; then
    uv_die "Downloaded source tree is missing requirements.txt"
  fi
}

run_install() {
  if [[ "$UNINSTALL" -eq 1 ]]; then
    uv_log "Running uninstall flow"
    uv_uninstall_installation "$PREFIX"
    return
  fi

  if [[ "$SYSTEM_PYTHON" -eq 1 ]]; then
    export UV_SYSTEM_PYTHON="$PYTHON_BIN"
  fi

  if [[ "${UV_DRY_RUN:-0}" -eq 1 ]]; then
    local dry_version="${VERSION:-latest ${CHANNEL}}"
    local runtime_note="bundled Python runtime"
    [[ "$SYSTEM_PYTHON" -eq 1 ]] && runtime_note="system Python ${PYTHON_BIN}"
    uv_log "dry-run: would install ${dry_version} into ${PREFIX}"
    uv_log "dry-run: would install system dependencies, download release assets, provision the ${runtime_note}, create the venv, and install desktop integration"
    return
  fi

  if [[ "$NO_DEPS" -eq 0 ]]; then
    uv_log "Installing system dependencies"
    uv_install_system_deps "$PYTHON_BIN"
  else
    uv_log "Skipping system dependency installation"
  fi

  TMP_DIR="$(mktemp -d)"
  if [[ -z "$VERSION" ]]; then
    resolve_latest_version
  fi

  VERSION="${VERSION#v}"
  download_release_source "$VERSION"

  uv_log "Installing into ${PREFIX}"
  uv_run mkdir -p "$PREFIX"
  uv_run cp -a "$SRC_DIR/assets" "$PREFIX/"

  uv_install_runtime_and_app "$PREFIX" "$SRC_DIR"

  if [[ "$NO_DESKTOP" -eq 0 ]]; then
    uv_log "Installing desktop/menu entry"
    uv_install_desktop_entry "$PREFIX"
  else
    uv_log "Skipping desktop/menu entry"
  fi

  uv_log "Install complete"
  uv_log "Run command: ${HOME}/.local/bin/unicorn-viz"
}

parse_args "$@"
run_install
