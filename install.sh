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
MANIFEST_URL="${UV_MANIFEST_URL:-${UV_DEFAULT_MANIFEST_URL}}"
VERSION=""
NO_DEPS=0
NO_DESKTOP=0
UNINSTALL=0
SYSTEM_PYTHON=0
SRC_URL=""
SRC_SHA256=""
SRC_DIR=""
SUMS_URL=""
SUMS_ASC_URL=""
FROM_DIR=""

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
  cat <<'USAGE'
Unicorn Viz Linux installer

Usage:
  ./install.sh [options]

Releases are resolved from a manifest.json (the single source of truth for the
latest version and its artifacts). By default a self-contained Python runtime is
bundled into <prefix>/runtime so the install never depends on the system
interpreter. Use --system-python to opt out.

Options:
  --prefix <dir>            Install prefix (default: ~/.local/share/unicorn-viz)
  --from <dir>              Install from a hand-off bundle directory (the one
                            containing manifest.json) instead of a URL
  --manifest-url <url>      Release manifest to read
                            (default: https://get.unicornviz.io/manifest.json;
                            env UV_MANIFEST_URL overrides)
  --version <vX.Y.Z|X.Y.Z>  Install a specific version from the manifest
  --channel <stable|prerelease>
                            Channel to follow when --version is not given
  --system-python           Use a system Python instead of the bundled runtime
  --python <bin>            System Python to use with --system-python (default: python3)
  --no-deps                 Skip system dependency installation
  --no-desktop              Skip desktop/menu integration
  --uninstall               Remove install artifacts
  --dry-run                 Print actions without executing
  -h, --help                Show this help text
USAGE
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --prefix) PREFIX="$2"; shift 2 ;;
      --manifest-url) MANIFEST_URL="$2"; shift 2 ;;
      --from) FROM_DIR="$(cd "$2" && pwd)" || uv_die "--from: no such directory: $2"; MANIFEST_URL="file://${FROM_DIR}/manifest.json"; shift 2 ;;
      --python) PYTHON_BIN="$2"; shift 2 ;;
      --system-python) SYSTEM_PYTHON=1; shift ;;
      --version) VERSION="$2"; shift 2 ;;
      --channel) CHANNEL="$2"; shift 2 ;;
      --no-deps) NO_DEPS=1; shift ;;
      --no-desktop) NO_DESKTOP=1; shift ;;
      --uninstall) UNINSTALL=1; shift ;;
      --dry-run) UV_DRY_RUN=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) uv_die "Unknown argument: $1" ;;
    esac
  done
}

# Resolve VERSION (via the channel when not pinned) and the source artifact's
# URL + checksum from the manifest.
resolve_release() {
  local manifest="${TMP_DIR}/manifest.json"

  uv_log "Reading release manifest: ${MANIFEST_URL}"
  uv_fetch_to_file "$MANIFEST_URL" "$manifest" \
    || uv_die "Could not download the release manifest from ${MANIFEST_URL}"

  if [[ -z "$VERSION" ]]; then
    case "$CHANNEL" in
      stable|prerelease) ;;
      *) uv_die "Invalid channel: ${CHANNEL}. Expected stable or prerelease." ;;
    esac
    if ! VERSION="$(uv_manifest_query "$manifest" channels "$CHANNEL" version)"; then
      # A release-candidate bundle only carries a prerelease channel (and a
      # stable-only manifest has no prerelease): fall back to whichever exists.
      local other
      [[ "$CHANNEL" == "stable" ]] && other="prerelease" || other="stable"
      VERSION="$(uv_manifest_query "$manifest" channels "$other" version)" \
        || uv_die "The manifest has neither a '${CHANNEL}' nor a '${other}' channel."
      uv_log "No '${CHANNEL}' channel in this manifest; using '${other}' (${VERSION})"
      CHANNEL="$other"
    fi
  fi
  VERSION="${VERSION#v}"

  SRC_URL="$(uv_manifest_query "$manifest" releases "$VERSION" artifacts source url)" \
    || uv_die "The manifest has no source artifact for version ${VERSION}."
  SRC_URL="$(uv_resolve_url "$MANIFEST_URL" "$SRC_URL")"
  SRC_SHA256="$(uv_manifest_query "$manifest" releases "$VERSION" artifacts source sha256)" \
    || SRC_SHA256=""
  SUMS_URL="$(uv_manifest_query "$manifest" releases "$VERSION" signatures sha256sums 2>/dev/null)" || SUMS_URL=""
  SUMS_ASC_URL="$(uv_manifest_query "$manifest" releases "$VERSION" signatures sha256sums_asc 2>/dev/null)" || SUMS_ASC_URL=""
  [[ "$SUMS_URL" == "None" ]] && SUMS_URL=""
  [[ "$SUMS_ASC_URL" == "None" ]] && SUMS_ASC_URL=""
  [[ -n "$SUMS_URL" ]] && SUMS_URL="$(uv_resolve_url "$MANIFEST_URL" "$SUMS_URL")"
  [[ -n "$SUMS_ASC_URL" ]] && SUMS_ASC_URL="$(uv_resolve_url "$MANIFEST_URL" "$SUMS_ASC_URL")"
}

# Verify the release's SHA256SUMS signature with the project's public key when
# the manifest carries one. The key is looked for next to the manifest (bundles
# ship release-key.asc), next to this script (docs/release-key.asc), or at
# $UV_RELEASE_KEY. A bad signature is fatal; a missing gpg or key only warns.
verify_release_signature() {
  [[ -n "$SUMS_URL" && -n "$SUMS_ASC_URL" ]] || { uv_log "No release signature published for ${VERSION}; relying on sha256 only."; return 0; }
  if ! command -v gpg >/dev/null 2>&1; then
    uv_warn "gpg not installed; cannot verify the release signature (sha256 still checked)."
    return 0
  fi
  local sums="${TMP_DIR}/SHA256SUMS" asc="${TMP_DIR}/SHA256SUMS.asc" key="" keyring="${TMP_DIR}/release-keyring.gpg"
  uv_fetch_to_file "$SUMS_URL" "$sums" || uv_die "Could not download SHA256SUMS from ${SUMS_URL}"
  uv_fetch_to_file "$SUMS_ASC_URL" "$asc" || uv_die "Could not download SHA256SUMS.asc from ${SUMS_ASC_URL}"
  for candidate in "${UV_RELEASE_KEY:-}" "${FROM_DIR:+${FROM_DIR}/release-key.asc}" "${SCRIPT_DIR}/docs/release-key.asc" "${SCRIPT_DIR}/release-key.asc"; do
    [[ -n "$candidate" && -f "$candidate" ]] && { key="$candidate"; break; }
  done
  if [[ -z "$key" ]]; then
    local remote_key="${TMP_DIR}/release-key.asc"
    if uv_fetch_to_file "$(uv_resolve_url "$MANIFEST_URL" release-key.asc)" "$remote_key" 2>/dev/null; then key="$remote_key"; fi
  fi
  if [[ -z "$key" ]]; then
    uv_warn "Release public key not found; signature NOT verified (sha256 still checked). Set UV_RELEASE_KEY=/path/to/release-key.asc to verify."
    return 0
  fi
  gpg --batch --quiet --no-default-keyring --keyring "$keyring" --import "$key" 2>/dev/null \
    || uv_die "Could not import the release public key from ${key}"
  if gpg --batch --quiet --no-default-keyring --keyring "$keyring" --verify "$asc" "$sums" 2>/dev/null; then
    uv_log "Release signature verified (key $(gpg --batch --no-default-keyring --keyring "$keyring" --list-keys --with-colons 2>/dev/null | awk -F: '/^fpr/{print substr($10, length($10)-15); exit}'))"
  else
    uv_die "Release signature verification FAILED for ${VERSION}: SHA256SUMS does not match SHA256SUMS.asc. Do not install this bundle."
  fi
  # The signed sums must agree with the manifest's checksum for our tarball.
  local signed_sha
  signed_sha="$(awk -v n="unicorn-viz-${VERSION}.tar.gz" '$2 == n {print $1}' "$sums")"
  if [[ -n "$signed_sha" && -n "$SRC_SHA256" && "$signed_sha" != "$SRC_SHA256" ]]; then
    uv_die "Signed SHA256SUMS and manifest disagree about unicorn-viz-${VERSION}.tar.gz; refusing to install."
  fi
}

download_release_source() {
  local tar_name="unicorn-viz-${VERSION}.tar.gz"
  local tar_path="${TMP_DIR}/${tar_name}"
  local actual

  uv_log "Downloading Unicorn Viz ${VERSION}"
  uv_fetch_to_file "$SRC_URL" "$tar_path" || uv_die "Download failed: ${SRC_URL}"

  if [[ -n "$SRC_SHA256" ]]; then
    actual="$(uv_sha256_file "$tar_path")"
    if [[ "$actual" != "$SRC_SHA256" ]]; then
      uv_die "Checksum mismatch for ${tar_name}: expected ${SRC_SHA256}, got ${actual}"
    fi
    uv_log "Checksum verified"
  else
    uv_warn "The manifest carries no sha256 for ${tar_name}; skipping verification."
  fi

  uv_run tar -xzf "$tar_path" -C "$TMP_DIR"
  SRC_DIR="${TMP_DIR}/unicorn-viz-${VERSION}"
  if [[ ! -f "${SRC_DIR}/requirements.txt" ]]; then
    uv_die "Downloaded source tree is missing requirements.txt"
  fi
}

run_install() {
  if [[ "$UNINSTALL" -eq 1 ]]; then
    uv_log "Running uninstall flow"
    uv_uninstall_installation "$PREFIX"
    return
  fi

  if [[ "${UV_DRY_RUN:-0}" -eq 1 ]]; then
    local dry_version="${VERSION:-latest ${CHANNEL}}"
    local runtime_note="bundled Python runtime"
    [[ "$SYSTEM_PYTHON" -eq 1 ]] && runtime_note="system Python ${PYTHON_BIN}"
    uv_log "dry-run: would install ${dry_version} (manifest: ${MANIFEST_URL}) into ${PREFIX}"
    uv_log "dry-run: would install system dependencies, provision the ${runtime_note}, resolve and download the release from the manifest, verify its checksum, create the venv, and install desktop integration"
    return
  fi

  if [[ "$NO_DEPS" -eq 0 ]]; then
    uv_log "Installing system dependencies"
    uv_install_system_deps "$PYTHON_BIN"
  else
    uv_log "Skipping system dependency installation"
  fi

  TMP_DIR="$(mktemp -d)"
  uv_log "Installing into ${PREFIX}"
  uv_run mkdir -p "$PREFIX"

  # Runtime first: besides running the app, it is the interpreter that reads
  # the manifest, so the installer never needs a system Python.
  local python_path
  if [[ "$SYSTEM_PYTHON" -eq 1 ]]; then
    uv_log "Using system Python: ${PYTHON_BIN} (bundled runtime skipped)"
    uv_require_cmd "$PYTHON_BIN"
    python_path="$(command -v "$PYTHON_BIN")"
  else
    uv_log "Provisioning bundled Python runtime"
    python_path="$(uv_provision_runtime "${PREFIX}/runtime")"
  fi
  export UV_JSON_PYTHON="$python_path"

  resolve_release
  verify_release_signature
  download_release_source

  uv_run cp -a "$SRC_DIR/assets" "$PREFIX/"
  for doc in LICENSE THIRD_PARTY_LICENSES.md README.md config.full.example.toml; do
    [[ -f "${SRC_DIR}/${doc}" ]] && uv_run cp "${SRC_DIR}/${doc}" "${PREFIX}/${doc}"
  done
  # Starter config on first install only; a user's edited config.toml survives upgrades.
  if [[ -f "${SRC_DIR}/config.dist.toml" && ! -f "${PREFIX}/config.toml" ]]; then
    uv_run cp "${SRC_DIR}/config.dist.toml" "${PREFIX}/config.toml"
  fi
  uv_create_venv_and_install "$python_path" "${PREFIX}/venv" "$SRC_DIR"

  if [[ "$NO_DESKTOP" -eq 0 ]]; then
    uv_log "Installing desktop/menu entry"
    uv_install_desktop_entry "$PREFIX"
  else
    uv_log "Skipping desktop/menu entry"
  fi

  uv_log "Install complete: Unicorn Viz ${VERSION}"
  uv_log "Run command: ${HOME}/.local/bin/unicorn-viz"
}

parse_args "$@"
run_install
