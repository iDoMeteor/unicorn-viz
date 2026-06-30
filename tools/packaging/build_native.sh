#!/usr/bin/env bash
#
# build_native.sh — build a native .deb / .rpm for Unicorn Viz.
#
# Layout shipped (INSTALL_ROOT defaults to /opt/unicorn-viz):
#
#   <INSTALL_ROOT>/unicornviz/        app package (source, not pip-installed)
#   <INSTALL_ROOT>/assets/            runtime assets (licensed sims packs stripped)
#   <INSTALL_ROOT>/runtime/python/    bundled python-build-standalone interpreter,
#                                     with the core dependencies pip-installed into it
#   /usr/bin/unicorn-viz              wrapper: PYTHONPATH=<INSTALL_ROOT> exec
#                                     <INSTALL_ROOT>/runtime/python/bin/python3 -m unicornviz
#   /usr/share/applications/unicorn-viz.desktop
#   /usr/share/icons/hicolor/256x256/apps/unicorn-viz.png
#   /usr/share/doc/unicorn-viz/{README.md,LICENSE,config.full.example.toml}
#
# Why ship the package as source under INSTALL_ROOT and run with PYTHONPATH
# instead of `pip install`ing the project?  Because unicornviz.paths.APP_ROOT is
# `Path(__file__).resolve().parents[1]` — the parent of the package dir — and the
# app loads assets relative to APP_ROOT.  Installing the package into the bundled
# interpreter's site-packages would make APP_ROOT point at site-packages, where
# `assets/` does not live.  Keeping unicornviz/ and assets/ as siblings under
# INSTALL_ROOT makes APP_ROOT resolve to INSTALL_ROOT, so assets are found.
#
# Only the core dependency set (requirements.txt) is installed into the bundled
# runtime; drop-ins are core-excluded (see installer plan §6) and are not shipped.
#
# Usage:
#   tools/packaging/build_native.sh --format <deb|rpm> --version <X.Y.Z> [options]
#
# Options:
#   --format <deb|rpm>     Package format (required unless --no-package)
#   --version <X.Y.Z>      Package version (required unless --no-package)
#   --source-dir <path>    Source tree root (default: repository root)
#   --output-dir <path>    Output dir for the package(s) (default: <repo>/dist)
#   --install-root <path>  On-target install prefix (default: /opt/unicorn-viz)
#   --runtime-os <os>      Runtime OS for fetch_runtime (default: autodetect)
#   --runtime-arch <arch>  Runtime arch for fetch_runtime (default: autodetect)
#   --no-package           Stage everything but skip fpm; keep + print the staging
#                          tree (for local relocatability testing)
#   -h, --help             Show this help text

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

FORMAT=""
VERSION=""
SOURCE_DIR="${REPO_ROOT}"
OUTPUT_DIR="${REPO_ROOT}/dist"
INSTALL_ROOT="/opt/unicorn-viz"
RUNTIME_OS=""
RUNTIME_ARCH=""
NO_PACKAGE=0

log() { echo "[build-native] $*" >&2; }
die() { echo "[build-native] ERROR: $*" >&2; exit 1; }

usage() { sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --format) FORMAT="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --source-dir) SOURCE_DIR="$2"; shift 2 ;;
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    --install-root) INSTALL_ROOT="$2"; shift 2 ;;
    --runtime-os) RUNTIME_OS="$2"; shift 2 ;;
    --runtime-arch) RUNTIME_ARCH="$2"; shift 2 ;;
    --no-package) NO_PACKAGE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

if [[ "$NO_PACKAGE" -eq 0 ]]; then
  [[ -n "$FORMAT" ]] || die "--format is required (deb or rpm)"
  [[ -n "$VERSION" ]] || die "--version is required"
  [[ "$FORMAT" == "deb" || "$FORMAT" == "rpm" ]] || die "--format must be deb or rpm"
  command -v fpm >/dev/null 2>&1 || die "fpm is required but not installed"
else
  VERSION="${VERSION:-0.0.0-staging}"
fi

[[ "${INSTALL_ROOT:0:1}" == "/" ]] || die "--install-root must be an absolute path"

SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
mkdir -p "$OUTPUT_DIR"

STAGE_SCRIPT="${SCRIPT_DIR}/stage_payload.sh"
FETCH_SCRIPT="${SCRIPT_DIR}/fetch_runtime.sh"
[[ -f "$STAGE_SCRIPT" ]] || die "stage_payload.sh not found next to this script"
[[ -f "$FETCH_SCRIPT" ]] || die "fetch_runtime.sh not found next to this script"

KEEP_STAGING="$NO_PACKAGE"
TMP_DIR="$(mktemp -d)"
cleanup() { [[ "$KEEP_STAGING" -eq 1 ]] || rm -rf "$TMP_DIR"; }
trap cleanup EXIT

STAGING_DIR="${TMP_DIR}/staging"
APP_ROOT="${STAGING_DIR}${INSTALL_ROOT}"
RUNTIME_DIR="${APP_ROOT}/runtime"
BIN_DIR="${STAGING_DIR}/usr/bin"
APP_DESKTOP_DIR="${STAGING_DIR}/usr/share/applications"
ICON_DIR="${STAGING_DIR}/usr/share/icons/hicolor/256x256/apps"
DOC_DIR="${STAGING_DIR}/usr/share/doc/unicorn-viz"

mkdir -p "$APP_ROOT" "$BIN_DIR" "$APP_DESKTOP_DIR" "$ICON_DIR" "$DOC_DIR"

# 1. Curated payload (no .git/.venv/logs/docs/drop-ins/licensed sims packs).
PAYLOAD_DIR="${TMP_DIR}/payload"
log "Staging curated payload"
"$STAGE_SCRIPT" --source-dir "$SOURCE_DIR" --dest "$PAYLOAD_DIR" >/dev/null

# 2. Bundled, relocatable runtime.
log "Provisioning bundled runtime into ${RUNTIME_DIR}"
fetch_args=(--dest "$RUNTIME_DIR")
[[ -n "$RUNTIME_OS" ]] && fetch_args+=(--os "$RUNTIME_OS")
[[ -n "$RUNTIME_ARCH" ]] && fetch_args+=(--arch "$RUNTIME_ARCH")
RUNTIME_PY="$(bash "$FETCH_SCRIPT" "${fetch_args[@]}")"

# 3. Install ONLY the core dependencies into the bundled runtime (not the project
#    itself — the app runs from the shipped source tree via PYTHONPATH).
log "Installing core dependencies into the bundled runtime"
# pip writes to stdout; route it to stderr so stdout stays reserved for the
# staging path printed at the end (the script's machine-readable contract).
"$RUNTIME_PY" -m pip install --no-cache-dir --upgrade pip wheel >&2
"$RUNTIME_PY" -m pip install --no-cache-dir -r "${PAYLOAD_DIR}/requirements.txt" >&2

# 4. App package + assets as siblings under INSTALL_ROOT (so APP_ROOT == INSTALL_ROOT).
cp -a "${PAYLOAD_DIR}/unicornviz" "${APP_ROOT}/"
cp -a "${PAYLOAD_DIR}/assets" "${APP_ROOT}/"

# 5. Docs.
cp "${PAYLOAD_DIR}/README.md" "${DOC_DIR}/README.md"
[[ -f "${PAYLOAD_DIR}/LICENSE" ]] && cp "${PAYLOAD_DIR}/LICENSE" "${DOC_DIR}/LICENSE"
cp "${SOURCE_DIR}/config.full.example.toml" "${DOC_DIR}/config.full.example.toml"
# NOTE: config.toml is intentionally NOT shipped as a dpkg/rpm conffile yet —
# it is being cleaned up for distribution by a separate effort. Once the
# distribution-ready config lands, install it to /etc/unicorn-viz/config.toml and
# declare it with fpm's --config-files so package upgrades preserve user edits.

# 6. Relocatability: pip wrote console-script shebangs pointing at the staging
#    path. We launch via `python -m`, but rewrite them so the runtime is
#    self-consistent at the final install path.
if compgen -G "${RUNTIME_DIR}/python/bin/*" >/dev/null; then
  while IFS= read -r script; do
    sed -i "s|${STAGING_DIR}||g" "$script"
  done < <(grep -rIlF "$STAGING_DIR" "${RUNTIME_DIR}/python/bin" 2>/dev/null || true)
fi

# 7. Launcher wrapper. PYTHONPATH makes unicornviz importable; the bundled,
#    relocatable interpreter runs it via -m. INSTALL_ROOT is baked in.
cat >"${BIN_DIR}/unicorn-viz" <<EOF
#!/usr/bin/env bash
set -euo pipefail
# UNICORNVIZ_APP_ROOT pins asset resolution to the install prefix regardless of
# where the package is imported from; PYTHONPATH makes it importable.
export UNICORNVIZ_APP_ROOT="${INSTALL_ROOT}"
export PYTHONPATH="${INSTALL_ROOT}\${PYTHONPATH:+:\$PYTHONPATH}"
exec "${INSTALL_ROOT}/runtime/python/bin/python3" -m unicornviz "\$@"
EOF
chmod +x "${BIN_DIR}/unicorn-viz"

# 8. Desktop entry + icon.
cat >"${APP_DESKTOP_DIR}/unicorn-viz.desktop" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Unicorn Viz
GenericName=Audio-Reactive Visualizer
Comment=Fullscreen OpenGL demoscene visualizer with audio and MIDI control
Exec=unicorn-viz %U
Icon=unicorn-viz
Terminal=false
Categories=AudioVideo;Audio;Graphics;Player;
Keywords=visualizer;demoscene;vj;audio;midi;ansi;
StartupNotify=true
StartupWMClass=unicorn-viz
EOF
cp "${SOURCE_DIR}/assets/icons/unicorn-viz.png" "${ICON_DIR}/unicorn-viz.png"

if [[ "$NO_PACKAGE" -eq 1 ]]; then
  log "Staging-only run (--no-package); skipping fpm."
  log "Install root staged at: ${APP_ROOT}"
  log "Runtime python: ${APP_ROOT}/runtime/python/bin/python3"
  echo "$STAGING_DIR"
  exit 0
fi

# 9. Package control scripts: refresh desktop + icon caches.
HOOK_DIR="${TMP_DIR}/hooks"
mkdir -p "$HOOK_DIR"
cat >"${HOOK_DIR}/after-install.sh" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -qtf /usr/share/icons/hicolor || true
fi
exit 0
EOF
cp "${HOOK_DIR}/after-install.sh" "${HOOK_DIR}/after-remove.sh"

# 10. fpm. Package the /usr tree and the INSTALL_ROOT top-level dir.
INSTALL_TOP="${INSTALL_ROOT#/}"; INSTALL_TOP="${INSTALL_TOP%%/*}"
COMMON_ARGS=(
  -s dir
  -t "$FORMAT"
  -n "unicorn-viz"
  -v "$VERSION"
  --iteration 1
  --description "Audio-reactive demoscene visualizer"
  --url "https://github.com/djunicorntears/unicorn-viz"
  --maintainer "Unicorn Viz"
  --vendor "Unicorn Viz"
  --license "MIT"
  --architecture native
  --after-install "${HOOK_DIR}/after-install.sh"
  --after-remove "${HOOK_DIR}/after-remove.sh"
  --chdir "$STAGING_DIR"
  --package "$OUTPUT_DIR"
)

# fpm requires all flags before the positional input dirs, so the staged trees
# (usr/ and the INSTALL_ROOT top-level dir) come last on every invocation.
if [[ "$FORMAT" == "deb" ]]; then
  fpm "${COMMON_ARGS[@]}" \
    --depends libsdl2-2.0-0 \
    --depends libgl1 \
    --depends libffi8 \
    --depends libpipewire-0.3-0 \
    --depends libasound2 \
    --depends ffmpeg \
    usr "$INSTALL_TOP"
else
  fpm "${COMMON_ARGS[@]}" \
    --depends SDL2 \
    --depends mesa-libGL \
    --depends libffi \
    --depends pipewire \
    --depends alsa-lib \
    --depends ffmpeg \
    usr "$INSTALL_TOP"
fi

log "Built ${FORMAT} package(s) in ${OUTPUT_DIR}"
