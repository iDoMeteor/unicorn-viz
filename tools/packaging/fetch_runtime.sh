#!/usr/bin/env bash
#
# fetch_runtime.sh — provision a bundled, relocatable CPython runtime.
#
# Downloads an "install_only" python-build-standalone (PBS) interpreter for the
# requested OS/arch, verifies it against the checksum published alongside the
# asset, and extracts it into a destination directory. This is the single shared
# "bundling system" consumed by the Linux installers (install.sh,
# tools/install_linux.sh) and, in later phases, the native .deb/.rpm, Windows,
# and macOS packaging flows — so every channel ships the same CPython instead of
# depending on whatever Python happens to be on the user's machine.
#
# Diagnostic output goes to stderr. The ONLY thing printed to stdout is the path
# to the extracted python interpreter, so callers can capture it with:
#
#     PY="$(tools/packaging/fetch_runtime.sh --dest /opt/unicorn-viz/runtime)"
#     "$PY" -m venv /opt/unicorn-viz/venv
#
# IMPORTANT: the PBS release tag and CPython version below are PINNED. Before
# cutting a real release, confirm the pin still resolves to a published asset at
# https://github.com/astral-sh/python-build-standalone/releases and bump it here.
# A wrong pin fails loudly with a 404 rather than silently floating to "latest".

set -Eeuo pipefail

# --- Pinned runtime ----------------------------------------------------------
PBS_RELEASE="${UV_PBS_RELEASE:-20241016}"
PBS_PYVER="${UV_PBS_PYVER:-3.11.10}"
PBS_BASE_URL="https://github.com/astral-sh/python-build-standalone/releases/download"

# --- Args --------------------------------------------------------------------
OS=""
ARCH=""
DEST=""
VARIANT="install_only"

log() { echo "[fetch-runtime] $*" >&2; }
warn() { echo "[fetch-runtime] WARNING: $*" >&2; }
die() { echo "[fetch-runtime] ERROR: $*" >&2; exit 1; }

usage() {
  cat >&2 <<'EOF'
Provision a bundled python-build-standalone CPython runtime.

Usage:
  fetch_runtime.sh --dest <dir> [options]

Options:
  --dest <dir>      Destination directory; runtime is extracted to <dir>/python (required)
  --os <name>       Target OS: linux|macos|windows (default: autodetect)
  --arch <name>     Target arch: x86_64|aarch64|universal2 (default: autodetect)
  --variant <name>  PBS archive variant (default: install_only)
  --release <tag>   PBS release tag override (default: pinned)
  --pyver <X.Y.Z>   CPython version override (default: pinned)
  -h, --help        Show this help text

Environment overrides: UV_PBS_RELEASE, UV_PBS_PYVER
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) DEST="$2"; shift 2 ;;
    --os) OS="$2"; shift 2 ;;
    --arch) ARCH="$2"; shift 2 ;;
    --variant) VARIANT="$2"; shift 2 ;;
    --release) PBS_RELEASE="$2"; shift 2 ;;
    --pyver) PBS_PYVER="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

[[ -n "$DEST" ]] || { usage; die "--dest is required"; }

# --- Autodetect OS/arch ------------------------------------------------------
if [[ -z "$OS" ]]; then
  case "$(uname -s)" in
    Linux) OS="linux" ;;
    Darwin) OS="macos" ;;
    MINGW*|MSYS*|CYGWIN*) OS="windows" ;;
    *) die "Cannot autodetect OS from uname; pass --os." ;;
  esac
fi

if [[ -z "$ARCH" ]]; then
  case "$(uname -m)" in
    x86_64|amd64) ARCH="x86_64" ;;
    aarch64|arm64) ARCH="aarch64" ;;
    *) die "Cannot autodetect arch from uname; pass --arch." ;;
  esac
fi

# --- Map (os, arch) -> PBS target triple -------------------------------------
case "${OS}:${ARCH}" in
  linux:x86_64) TRIPLE="x86_64-unknown-linux-gnu" ;;
  linux:aarch64) TRIPLE="aarch64-unknown-linux-gnu" ;;
  macos:x86_64) TRIPLE="x86_64-apple-darwin" ;;
  macos:aarch64) TRIPLE="aarch64-apple-darwin" ;;
  macos:universal2) TRIPLE="universal2-apple-darwin" ;;
  windows:x86_64) TRIPLE="x86_64-pc-windows-msvc" ;;
  *) die "Unsupported os/arch combination: ${OS}/${ARCH}" ;;
esac

ASSET="cpython-${PBS_PYVER}+${PBS_RELEASE}-${TRIPLE}-${VARIANT}.tar.gz"
ASSET_URL="${PBS_BASE_URL}/${PBS_RELEASE}/${ASSET}"
SHA_URL="${ASSET_URL}.sha256"

# --- Tooling -----------------------------------------------------------------
fetch_to_file() {
  local url="$1" out="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --retry 3 --retry-delay 2 -o "$out" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$out" "$url"
  else
    die "Neither curl nor wget is available to download the runtime."
  fi
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    die "Neither sha256sum nor shasum is available to verify the runtime."
  fi
}

# --- Download, verify, extract ----------------------------------------------
TMP_DIR="$(mktemp -d -p "${TMPDIR:-/var/tmp}")"
trap 'rm -rf "$TMP_DIR"' EXIT

TAR_PATH="${TMP_DIR}/${ASSET}"
SHA_PATH="${TMP_DIR}/${ASSET}.sha256"

log "Runtime: CPython ${PBS_PYVER} (PBS ${PBS_RELEASE}) for ${TRIPLE}"
log "Downloading ${ASSET}"
fetch_to_file "$ASSET_URL" "$TAR_PATH"

if fetch_to_file "$SHA_URL" "$SHA_PATH"; then
  expected="$(awk '{print $1}' "$SHA_PATH" | head -n1)"
  actual="$(sha256_of "$TAR_PATH")"
  if [[ -z "$expected" ]]; then
    warn "Checksum file was empty; skipping verification."
  elif [[ "$expected" != "$actual" ]]; then
    die "Checksum mismatch for ${ASSET}: expected ${expected}, got ${actual}"
  else
    log "Checksum verified."
  fi
else
  warn "Could not download ${ASSET}.sha256; skipping verification."
fi

mkdir -p "$DEST"
# PBS install_only archives extract to a top-level python/ directory.
if [[ -d "${DEST}/python" ]]; then
  log "Removing existing runtime at ${DEST}/python"
  rm -rf "${DEST}/python"
fi
log "Extracting into ${DEST}"
tar -xzf "$TAR_PATH" -C "$DEST"

if [[ "$OS" == "windows" ]]; then
  PY_PATH="${DEST}/python/python.exe"
else
  PY_PATH="${DEST}/python/bin/python3"
fi

[[ -x "$PY_PATH" || -f "$PY_PATH" ]] || die "Expected interpreter not found at ${PY_PATH} after extraction."

log "Runtime ready: ${PY_PATH}"
echo "$PY_PATH"
