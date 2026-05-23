#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

FORMAT=""
VERSION=""
SOURCE_DIR="${REPO_ROOT}"
OUTPUT_DIR="${REPO_ROOT}/dist"
PYTHON_BIN="python3"

usage() {
  cat <<'EOF'
Build Unicorn Viz native package via fpm.

Usage:
  tools/packaging/build_native.sh --format <deb|rpm> --version <X.Y.Z> [options]

Options:
  --format <deb|rpm>      Package format to build (required)
  --version <X.Y.Z>       Package version (required)
  --source-dir <path>     Source tree root (default: repository root)
  --output-dir <path>     Output directory for generated package(s)
  --python <bin>          Python executable used to build venv (default: python3)
  -h, --help              Show this help text
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --format)
      FORMAT="$2"
      shift 2
      ;;
    --version)
      VERSION="$2"
      shift 2
      ;;
    --source-dir)
      SOURCE_DIR="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$FORMAT" || -z "$VERSION" ]]; then
  usage
  exit 1
fi

if [[ "$FORMAT" != "deb" && "$FORMAT" != "rpm" ]]; then
  echo "--format must be either deb or rpm" >&2
  exit 1
fi

if [[ ! -f "${SOURCE_DIR}/requirements.txt" ]]; then
  echo "requirements.txt not found in ${SOURCE_DIR}" >&2
  exit 1
fi

if [[ ! -f "${SOURCE_DIR}/pyproject.toml" ]]; then
  echo "pyproject.toml not found in ${SOURCE_DIR}" >&2
  exit 1
fi

if [[ ! -d "${SOURCE_DIR}/unicornviz" ]]; then
  echo "unicornviz package directory not found in ${SOURCE_DIR}" >&2
  exit 1
fi

if [[ ! -d "${SOURCE_DIR}/assets" ]]; then
  echo "assets directory not found in ${SOURCE_DIR}" >&2
  exit 1
fi

if [[ ! -f "${SOURCE_DIR}/assets/icons/unicorn-viz.png" ]]; then
  echo "assets/icons/unicorn-viz.png not found in ${SOURCE_DIR}" >&2
  exit 1
fi

if [[ ! -f "${SOURCE_DIR}/README.md" ]]; then
  echo "README.md not found in ${SOURCE_DIR}" >&2
  exit 1
fi

if [[ ! -f "${SOURCE_DIR}/config.full.example.toml" ]]; then
  echo "config.full.example.toml not found in ${SOURCE_DIR}" >&2
  exit 1
fi

command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
  echo "Python executable not found: ${PYTHON_BIN}" >&2
  exit 1
}
command -v fpm >/dev/null 2>&1 || {
  echo "fpm is required but not installed" >&2
  exit 1
}

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

STAGING_DIR="${TMP_DIR}/staging"
INSTALL_ROOT="/opt/unicorn-viz"
APP_ROOT="${STAGING_DIR}${INSTALL_ROOT}"
VENV_DIR="${APP_ROOT}/venv"
BIN_DIR="${STAGING_DIR}/usr/bin"
APP_DIR="${STAGING_DIR}/usr/share/applications"
ICON_DIR="${STAGING_DIR}/usr/share/icons/hicolor/256x256/apps"
DOC_DIR="${STAGING_DIR}/usr/share/doc/unicorn-viz"

mkdir -p "$APP_ROOT" "$BIN_DIR" "$APP_DIR" "$ICON_DIR" "$DOC_DIR" "$OUTPUT_DIR"

cp -a "${SOURCE_DIR}/unicornviz" "$APP_ROOT/"
cp -a "${SOURCE_DIR}/assets" "$APP_ROOT/"
if [[ -d "${SOURCE_DIR}/drop-ins" ]]; then
  cp -a "${SOURCE_DIR}/drop-ins" "$APP_ROOT/"
else
  echo "[build-native] drop-ins directory missing in source tree; packaging core-only bundle" >&2
fi
cp "${SOURCE_DIR}/requirements.txt" "$APP_ROOT/"
cp "${SOURCE_DIR}/pyproject.toml" "$APP_ROOT/"
cp "${SOURCE_DIR}/README.md" "$DOC_DIR/README.md"
cp "${SOURCE_DIR}/config.full.example.toml" "$DOC_DIR/config.full.example.toml"

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip wheel
"$VENV_DIR/bin/pip" install -r "${SOURCE_DIR}/requirements.txt"
"$VENV_DIR/bin/pip" install "$SOURCE_DIR"

cat >"${BIN_DIR}/unicorn-viz" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exec /opt/unicorn-viz/venv/bin/unicorn-viz "$@"
EOF
chmod +x "${BIN_DIR}/unicorn-viz"

cat >"${APP_DIR}/unicorn-viz.desktop" <<'EOF'
[Desktop Entry]
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

PKG_NAME="unicorn-viz"
COMMON_ARGS=(
  -s dir
  -t "$FORMAT"
  -n "$PKG_NAME"
  -v "$VERSION"
  --iteration 1
  --description "Audio-reactive demoscene visualizer"
  --url "https://github.com/djunicorntears/unicorn-viz"
  --maintainer "Unicorn Viz"
  --vendor "Unicorn Viz"
  --license "MIT"
  --architecture native
  --chdir "$STAGING_DIR"
  --package "$OUTPUT_DIR"
  usr
  opt
)

if [[ "$FORMAT" == "deb" ]]; then
  fpm "${COMMON_ARGS[@]}" \
    --depends libsdl2-2.0-0 \
    --depends libgl1 \
    --depends libffi8 \
    --depends libpipewire-0.3-0 \
    --depends libasound2 \
    --depends ffmpeg
else
  fpm "${COMMON_ARGS[@]}" \
    --depends SDL2 \
    --depends mesa-libGL \
    --depends libffi \
    --depends pipewire \
    --depends alsa-lib \
    --depends ffmpeg
fi

echo "Built ${FORMAT} package(s) in ${OUTPUT_DIR}"