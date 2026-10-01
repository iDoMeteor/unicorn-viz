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
# Two runtime flavors are pinned (--flavor / UV_RUNTIME_FLAVOR):
#
#   gil  CPython 3.11.10, PBS 20241016, classic GIL build (legacy default).
#   ft   CPython 3.14.7, PBS 20260929, FREE-THREADED build (ABI tag cp314t).
#        This is the bundle chosen by the 2026-09-30 W1 remediation: 3.13+
#        fixes the SharedMemory(track=) break that stops every mixer track
#        load on 3.11, and free-threading is the project's threading plan
#        (docs/planning/free-threaded-python-2026-09-24.md).
#
# IMPORTANT: the PBS release tags and CPython versions are PINNED, and so are
# the sha256 digests of the assets (pinned_sha256 below). Before cutting a real
# release, confirm the pin still resolves to a published asset at
# https://github.com/astral-sh/python-build-standalone/releases and bump it
# here. A wrong pin fails loudly with a 404 rather than silently floating to
# "latest".
#
# Integrity: PBS stopped publishing per-asset .sha256 sidecars, so a missing
# checksum is FATAL (it used to only warn, which silently downgraded
# verification). Order: the pinned digest; else the release-level SHA256SUMS;
# else a legacy per-asset sidecar. UV_ALLOW_UNVERIFIED_RUNTIME=1 overrides, for
# throwaway experiments only.

set -Eeuo pipefail

# Scratch space for builds: $TMPDIR if set, else /var/tmp where it exists
# (disk-backed on Linux; /tmp is tmpfs and too small for 200 MB staging trees),
# else the platform default (Git Bash on Windows has no /var/tmp).
build_tmp_base() {
  if [[ -n "${TMPDIR:-}" && -d "${TMPDIR}" ]]; then echo "$TMPDIR"
  elif [[ -d /var/tmp ]]; then echo /var/tmp
  else dirname "$(mktemp -u)"
  fi
}

# --- Pinned runtime ----------------------------------------------------------
PBS_BASE_URL="https://github.com/astral-sh/python-build-standalone/releases/download"
FLAVOR="${UV_RUNTIME_FLAVOR:-gil}"
PBS_RELEASE="${UV_PBS_RELEASE:-}"
PBS_PYVER="${UV_PBS_PYVER:-}"

# --- Args --------------------------------------------------------------------
OS=""
ARCH=""
DEST=""
VARIANT=""
DRY_RUN=0

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
  --flavor <name>   gil (CPython 3.11, default) | ft (CPython 3.14 free-threaded)
  --variant <name>  PBS archive variant (default: install_only for gil,
                    freethreaded-install_only for ft; the *_stripped variants
                    are smaller but drop debug symbols)
  --release <tag>   PBS release tag override (default: pinned)
  --pyver <X.Y.Z>   CPython version override (default: pinned)
  --dry-run         Print asset=, url= and sha256= lines and exit (no network)
  -h, --help        Show this help text

Environment overrides: UV_RUNTIME_FLAVOR, UV_PBS_RELEASE, UV_PBS_PYVER,
UV_ALLOW_UNVERIFIED_RUNTIME (=1 to proceed without a checksum; unsafe)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) DEST="$2"; shift 2 ;;
    --os) OS="$2"; shift 2 ;;
    --arch) ARCH="$2"; shift 2 ;;
    --flavor) FLAVOR="$2"; shift 2 ;;
    --variant) VARIANT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --release) PBS_RELEASE="$2"; shift 2 ;;
    --pyver) PBS_PYVER="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

[[ -n "$DEST" || "$DRY_RUN" == 1 ]] || { usage; die "--dest is required"; }

case "$FLAVOR" in
  gil)
    : "${PBS_RELEASE:=20241016}"
    : "${PBS_PYVER:=3.11.10}"
    : "${VARIANT:=install_only}"
    ;;
  ft)
    : "${PBS_RELEASE:=20260929}"
    : "${PBS_PYVER:=3.14.7}"
    : "${VARIANT:=freethreaded-install_only}"
    ;;
  *) die "Unknown --flavor '${FLAVOR}' (expected gil or ft)" ;;
esac

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
SUMS_URL="${PBS_BASE_URL}/${PBS_RELEASE}/SHA256SUMS"

# Pinned sha256 digests, keyed by asset file name (a case statement, not an
# associative array, so this runs on the bash 3.2 that macOS ships). The ft
# rows were taken from the release's SHA256SUMS and cross-checked against the
# downloaded linux/windows x86-64 archives on 2026-09-30. Add a row whenever
# the pin above moves; an asset with no row falls back to SHA256SUMS.
pinned_sha256() {
  case "$1" in
    cpython-3.14.7+20260929-x86_64-unknown-linux-gnu-freethreaded-install_only.tar.gz) echo 730c33d387c937bea8995d69d4bc20a24084844120c7d56ed5e0b6f4bfc92641 ;;
    cpython-3.14.7+20260929-x86_64-unknown-linux-gnu-freethreaded-install_only_stripped.tar.gz) echo a938c5902cf057989f03707eb706cb7275f9ab2da639b5b34f41948016aef872 ;;
    cpython-3.14.7+20260929-x86_64-pc-windows-msvc-freethreaded-install_only.tar.gz) echo 00502edc9de197a4b2e0ed01f31aabaa8dd31b569d2202f471f97fdcc4424f85 ;;
    cpython-3.14.7+20260929-x86_64-pc-windows-msvc-freethreaded-install_only_stripped.tar.gz) echo 1d68afce9cac1eb009b5afd56840e528b5630fd6aa8b8cb3e7bd5755219c78ab ;;
    cpython-3.14.7+20260929-aarch64-unknown-linux-gnu-freethreaded-install_only.tar.gz) echo 07b9e1b0d4e343e2b0b7fa2af0643f8692eb6545fb3fe84546171e02316a61fd ;;
    cpython-3.14.7+20260929-aarch64-unknown-linux-gnu-freethreaded-install_only_stripped.tar.gz) echo 57c4633c68b206f9f42e3b5b46a4395b49cc6ff867a90340a617e9861383ea4e ;;
    cpython-3.14.7+20260929-aarch64-apple-darwin-freethreaded-install_only.tar.gz) echo 38829145928f644c5c8976a37c8a1a44281cd027100ad60f9e8c20343b98ddc1 ;;
    cpython-3.14.7+20260929-aarch64-apple-darwin-freethreaded-install_only_stripped.tar.gz) echo 17a37df285d019be16909aeedd1e3f8acba90a21903037df10ec0ee11fa06595 ;;
    cpython-3.14.7+20260929-x86_64-apple-darwin-freethreaded-install_only.tar.gz) echo 4eaff85393f87e0e0019f0e11cec9f6fb3f50b479b6346629f55f7c8bb3ffd84 ;;
    cpython-3.14.7+20260929-x86_64-apple-darwin-freethreaded-install_only_stripped.tar.gz) echo 3ea6d5fa82bda86246757ef4b730a2392a7757af15fb4697e11caf771827f38d ;;
    *) echo "" ;;
  esac
}

if [[ "$DRY_RUN" == 1 ]]; then
  echo "asset=${ASSET}"
  echo "url=${ASSET_URL}"
  echo "sha256=$(pinned_sha256 "$ASSET")"
  exit 0
fi

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
TMP_DIR="$(mktemp -d -p "$(build_tmp_base)")"
trap 'rm -rf "$TMP_DIR"' EXIT

TAR_PATH="${TMP_DIR}/${ASSET}"

log "Runtime: CPython ${PBS_PYVER} (PBS ${PBS_RELEASE}, ${FLAVOR}) for ${TRIPLE}"
log "Downloading ${ASSET}"
fetch_to_file "$ASSET_URL" "$TAR_PATH"

# Resolve the expected digest: pin, then release SHA256SUMS, then legacy sidecar.
expected="$(pinned_sha256 "$ASSET")"
source_of="pinned digest"
if [[ -z "$expected" ]]; then
  source_of="release SHA256SUMS"
  if fetch_to_file "$SUMS_URL" "${TMP_DIR}/SHA256SUMS" 2>/dev/null; then
    expected="$(awk -v a="$ASSET" '$2 == a || $2 == "*" a {print $1; exit}' "${TMP_DIR}/SHA256SUMS")"
  fi
fi
if [[ -z "$expected" ]]; then
  source_of="${ASSET}.sha256"
  if fetch_to_file "$SHA_URL" "${TMP_DIR}/${ASSET}.sha256" 2>/dev/null; then
    expected="$(awk '{print $1}' "${TMP_DIR}/${ASSET}.sha256" | head -n1)"
  fi
fi

actual="$(sha256_of "$TAR_PATH")"
if [[ -z "$expected" ]]; then
  if [[ "${UV_ALLOW_UNVERIFIED_RUNTIME:-0}" == 1 ]]; then
    warn "No checksum available for ${ASSET}; continuing UNVERIFIED (sha256 ${actual})."
  else
    die "No checksum available for ${ASSET} (no pin, not in SHA256SUMS, no sidecar). Refusing to install an unverified runtime; add a pin to pinned_sha256 (sha256 ${actual}) after checking it against the release, or set UV_ALLOW_UNVERIFIED_RUNTIME=1 to override."
  fi
elif [[ "$expected" != "$actual" ]]; then
  die "Checksum mismatch for ${ASSET} (${source_of}): expected ${expected}, got ${actual}"
else
  log "Checksum verified (${source_of})."
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
