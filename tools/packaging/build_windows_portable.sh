#!/usr/bin/env bash
#
# build_windows_portable.sh — build UnicornViz-Portable-<version>-win-x64.zip
# on any host (installer plan §18 Block E1).
#
# Layout inside the zip:
#   UnicornViz/unicornviz/, assets/           curated payload (stage_payload.sh)
#   UnicornViz/runtime/python/                python-build-standalone for Windows
#   UnicornViz/runtime/python/Lib/site-packages   pinned deps, cross-installed
#   UnicornViz/unicorn-viz.cmd                launcher (sets UNICORNVIZ_APP_ROOT)
#
# Dependencies are cross-installed with pip's --platform/--python-version/
# --target support (wheels only), so this runs on Linux/macOS/Windows alike.
# The result is BUILT here and must be VERIFIED on Windows (double-click
# unicorn-viz.cmd; `unicorn-viz.cmd --self-test`) — see plan §18 Block E.
#
# Usage:
#   tools/packaging/build_windows_portable.sh [--version X.Y.Z] [--output-dir dir]
#                                             [--source-dir dir] [--python-version 3.11]
#                                             [--payload-out dir]   # also leave the assembled
#                                                                   # UnicornViz/ tree here for Inno Setup

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

VERSION=""
OUTPUT_DIR="${REPO_ROOT}/dist"
SOURCE_DIR="${REPO_ROOT}"
PYVER="3.11"
PAYLOAD_OUT=""

log() { echo "[win-portable] $*" >&2; }
die() { echo "[win-portable] ERROR: $*" >&2; exit 1; }
usage() { sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    --source-dir) SOURCE_DIR="$2"; shift 2 ;;
    --python-version) PYVER="$2"; shift 2 ;;
    --payload-out) PAYLOAD_OUT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
if [[ -z "$VERSION" ]]; then
  VERSION="$(sed -n "s/^__version__ = ['\"]\([^'\"]*\)['\"].*/\1/p" "${SOURCE_DIR}/unicornviz/__init__.py" | head -n1)"
fi
[[ -n "$VERSION" ]] || die "Could not determine the version (pass --version)"
ABI="cp${PYVER//./}"

HOST_PY="${REPO_ROOT}/.venv/bin/python"
[[ -x "$HOST_PY" ]] || HOST_PY="$(command -v python3 || true)"
[[ -n "$HOST_PY" ]] || die "python3 is required on the build host"

mkdir -p "$OUTPUT_DIR"
WORK="$(mktemp -d -p "${TMPDIR:-/var/tmp}")"
trap 'rm -rf "$WORK"' EXIT
APP="${WORK}/UnicornViz"

log "Staging curated payload"
"${SCRIPT_DIR}/stage_payload.sh" --source-dir "$SOURCE_DIR" --dest "$APP" >/dev/null

log "Provisioning the Windows runtime (python-build-standalone, x86_64)"
"${SCRIPT_DIR}/fetch_runtime.sh" --dest "${APP}/runtime" --os windows --arch x86_64 >/dev/null
[[ -f "${APP}/runtime/python/python.exe" ]] || die "python.exe missing after runtime provisioning"

SITE="${APP}/runtime/python/Lib/site-packages"
log "Cross-installing pinned dependencies for win_amd64 / cp${PYVER//./} (wheels only)"
# --no-compile: bytecode would be produced by the HOST interpreter (wrong
# version for the Windows runtime); Windows compiles its own on first run.
"$HOST_PY" -m pip install --quiet --upgrade --no-compile \
  --target "$SITE" \
  --platform win_amd64 --python-version "$PYVER" --implementation cp --abi "$ABI" \
  --only-binary=:all: \
  -r "${APP}/requirements.txt" >&2
find "$SITE" -type d -name __pycache__ -prune -exec rm -rf {} +

log "Writing launcher"
printf '%s\r\n' \
  '@echo off' \
  'setlocal' \
  'rem Unicorn Viz portable launcher: assets resolve under this folder.' \
  'set "UNICORNVIZ_APP_ROOT=%~dp0"' \
  'set "PYTHONPATH=%~dp0;%PYTHONPATH%"' \
  '"%~dp0runtime\python\python.exe" -m unicornviz %*' \
  > "${APP}/unicorn-viz.cmd"
printf '%s\r\n' \
  "Unicorn Viz ${VERSION} - portable build for Windows 10/11 (x64)" \
  '' \
  'Run:        double-click unicorn-viz.cmd (or run it from a terminal with options)' \
  'Check:      unicorn-viz.cmd --self-test' \
  'Uninstall:  delete this folder' \
  '' \
  'This build is unsigned: on first run Windows SmartScreen may show "Windows' \
  'protected your PC" - choose "More info" then "Run anyway".' \
  > "${APP}/README-PORTABLE.txt"

if [[ -n "$PAYLOAD_OUT" ]]; then
  log "Leaving the assembled tree at ${PAYLOAD_OUT}/UnicornViz (for packaging/windows/UnicornViz.iss)"
  mkdir -p "$PAYLOAD_OUT"; rm -rf "${PAYLOAD_OUT}/UnicornViz"; cp -a "$APP" "${PAYLOAD_OUT}/UnicornViz"
fi

ZIP="${OUTPUT_DIR}/UnicornViz-Portable-${VERSION}-win-x64.zip"
log "Zipping → ${ZIP}"
rm -f "$ZIP"
( cd "$WORK" && "$HOST_PY" -m zipfile -c "$ZIP" UnicornViz )

# Sanity: junk-free, runtime present, native wheels really are Windows ones.
"$HOST_PY" - "$ZIP" <<'PY'
import sys, zipfile
names = zipfile.ZipFile(sys.argv[1]).namelist()
top = {n.split('/')[1] for n in names if n.count('/') >= 1}
bad = sorted(top & {'.git', '.venv', '.venv-runtime', 'drop-ins', 'logs', 'docs', 'tests', 'build', 'recordings', 'screenshots'})
assert not bad, f'junk in zip: {bad[:5]}'
assert 'UnicornViz/runtime/python/python.exe' in names, 'python.exe missing'
assert 'UnicornViz/unicorn-viz.cmd' in names, 'launcher missing'
pyd = [n for n in names if n.endswith('.pyd')]
assert pyd, 'no .pyd extension modules: cross-install did not produce Windows wheels'
assert not any(n.endswith('.so') for n in names if 'site-packages' in n), 'Linux .so files leaked into site-packages'
assert not any('__pycache__' in n for n in names if 'site-packages' in n), 'host bytecode leaked into site-packages'
print(f'ok: {len(names)} entries, {len(pyd)} Windows extension modules', file=sys.stderr)
PY
log "Built ${ZIP} ($(du -h "$ZIP" | cut -f1))"
echo "$ZIP"
