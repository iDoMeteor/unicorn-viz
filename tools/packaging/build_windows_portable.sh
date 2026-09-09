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
#                                             [--dropins pack.txt]  # ship a drop-in pack (see
#                                                                   # stage_payload.sh --dropins)
#                                             [--vlc-installer vlc-*-win64.exe]  # bundle the official
#                                                                   # VLC installer for media-01
#                                             [--label for-DJs]     # zip name: UnicornViz-Portable-<label>-...

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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

VERSION=""
OUTPUT_DIR="${REPO_ROOT}/dist"
SOURCE_DIR="${REPO_ROOT}"
PYVER="3.11"
PAYLOAD_OUT=""
DROPINS_FILE=""
VLC_INSTALLER=""
LABEL=""

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
    --dropins) DROPINS_FILE="$2"; shift 2 ;;
    --vlc-installer) VLC_INSTALLER="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
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

# Absolute paths: the zip is written from inside the work dir, and CI passes
# relative --output-dir / --payload-out (that is how the first Windows CI run
# died with "No such file: dist/...zip").
mkdir -p "$OUTPUT_DIR"; OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
if [[ -n "$PAYLOAD_OUT" ]]; then mkdir -p "$PAYLOAD_OUT"; PAYLOAD_OUT="$(cd "$PAYLOAD_OUT" && pwd)"; fi
WORK="$(mktemp -d -p "$(build_tmp_base)")"
trap 'rm -rf "$WORK"' EXIT
APP="${WORK}/UnicornViz"

log "Staging curated payload${DROPINS_FILE:+ + drop-in pack ${DROPINS_FILE}}"
stage_args=(--source-dir "$SOURCE_DIR" --dest "$APP")
[[ -n "$DROPINS_FILE" ]] && stage_args+=(--dropins "$DROPINS_FILE")
"${SCRIPT_DIR}/stage_payload.sh" "${stage_args[@]}" >/dev/null

log "Provisioning the Windows runtime (python-build-standalone, x86_64)"
"${SCRIPT_DIR}/fetch_runtime.sh" --dest "${APP}/runtime" --os windows --arch x86_64 >/dev/null
[[ -f "${APP}/runtime/python/python.exe" ]] || die "python.exe missing after runtime provisioning"

SITE="${APP}/runtime/python/Lib/site-packages"
EXTRA_REQS=()
[[ -f "${APP}/requirements-dropins.txt" ]] && EXTRA_REQS=(-r "${APP}/requirements-dropins.txt")
log "Cross-installing pinned dependencies for win_amd64 / cp${PYVER//./} (wheels only)"
# --no-compile: bytecode would be produced by the HOST interpreter (wrong
# version for the Windows runtime); Windows compiles its own on first run.
"$HOST_PY" -m pip install --quiet --upgrade --no-compile \
  --target "$SITE" \
  --platform win_amd64 --python-version "$PYVER" --implementation cp --abi "$ABI" \
  --only-binary=:all: \
  -r "${APP}/requirements.txt" "${EXTRA_REQS[@]}" >&2
find "$SITE" -type d -name __pycache__ -prune -exec rm -rf {} +

log "Writing launchers"
mkdir -p "${APP}/tools" "${APP}/vendor"
# Console launcher. Skips the VLC pre-flight for --self-test (headless CI).
printf '%s\r\n' \
  '@echo off' \
  'setlocal' \
  'rem Unicorn Viz portable launcher: assets resolve under this folder.' \
  'set "UNICORNVIZ_APP_ROOT=%~dp0"' \
  'set "PYTHONPATH=%~dp0;%PYTHONPATH%"' \
  'echo %* | findstr /C:"--self-test" >nul || powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\vlc-check.ps1" -Vendor "%~dp0vendor"' \
  '"%~dp0runtime\python\python.exe" -m unicornviz %*' \
  > "${APP}/unicorn-viz.cmd"
# GUI launcher for shortcuts: no console window; same VLC pre-flight.
# shellcheck disable=SC2016  # PowerShell source, deliberately not expanded by bash
printf '%s\r\n' \
  '# Unicorn Viz GUI launcher (used by the Start-menu / desktop shortcuts).' \
  '$root = $PSScriptRoot' \
  '$env:UNICORNVIZ_APP_ROOT = $root' \
  '$env:PYTHONPATH = "$root;$env:PYTHONPATH"' \
  '& "$root\tools\vlc-check.ps1" -Vendor "$root\vendor"' \
  'Start-Process -FilePath "$root\runtime\python\pythonw.exe" -ArgumentList @("-m", "unicornviz") -WorkingDirectory $root' \
  > "${APP}/unicorn-viz-gui.ps1"
# VLC pre-flight: media-01 binds libvlc through python-vlc. If VLC is absent,
# offer the bundled official installer (vendor\vlc-*-win64.exe) when present,
# else the download page. Never blocks the app: media-01 just stays off.
# shellcheck disable=SC2016  # PowerShell source, deliberately not expanded by bash
printf '%s\r\n' \
  'param([string]$Vendor = "")' \
  '$candidates = @()' \
  'try { $ip = (Get-ItemProperty "HKLM:\SOFTWARE\VideoLAN\VLC" -ErrorAction Stop).InstallDir; if ($ip) { $candidates += (Join-Path $ip "libvlc.dll") } } catch {}' \
  'if ($env:ProgramFiles) { $candidates += (Join-Path $env:ProgramFiles "VideoLAN\VLC\libvlc.dll") }' \
  'if (${env:ProgramFiles(x86)}) { $candidates += (Join-Path ${env:ProgramFiles(x86)} "VideoLAN\VLC\libvlc.dll") }' \
  'foreach ($c in $candidates) { if (Test-Path $c) { exit 0 } }' \
  'Add-Type -AssemblyName System.Windows.Forms' \
  '$title = "Unicorn Viz - VLC needed for the media player"' \
  '$installer = $null' \
  'if ($Vendor -and (Test-Path $Vendor)) { $installer = Get-ChildItem -Path $Vendor -Filter "vlc-*-win64.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 }' \
  'if ($installer) {' \
  '  $msg = "The built-in media player needs VLC, which is not installed.`n`nInstall VLC now? Unicorn Viz starts afterwards either way; without VLC the media player stays off."' \
  '  $r = [System.Windows.Forms.MessageBox]::Show($msg, $title, "YesNo", "Question")' \
  '  if ($r -eq "Yes") { Start-Process -FilePath $installer.FullName -Wait }' \
  '} else {' \
  '  $msg = "The built-in media player needs VLC, which is not installed.`n`nOpen the VLC download page now? (https://www.videolan.org/vlc/download-windows.html)`nUnicorn Viz starts afterwards either way; without VLC the media player stays off."' \
  '  $r = [System.Windows.Forms.MessageBox]::Show($msg, $title, "YesNo", "Question")' \
  '  if ($r -eq "Yes") { Start-Process "https://www.videolan.org/vlc/download-windows.html" }' \
  '}' \
  'exit 0' \
  > "${APP}/tools/vlc-check.ps1"
if [[ -n "$VLC_INSTALLER" ]]; then
  [[ -f "$VLC_INSTALLER" ]] || die "--vlc-installer: no such file: ${VLC_INSTALLER}"
  cp "$VLC_INSTALLER" "${APP}/vendor/"; log "Bundled VLC installer: $(basename "$VLC_INSTALLER")"
fi
DROPIN_NOTE=""
if [[ -d "${APP}/drop-ins" ]]; then
  DROPIN_NOTE="Included drop-ins: $(find "${APP}/drop-ins" -mindepth 1 -maxdepth 1 -type d -printf '%f ' | sort)"
fi
printf '%s\r\n' \
  "Unicorn Viz ${VERSION}${LABEL:+ (${LABEL})} - portable build for Windows 10/11 (x64)" \
  '' \
  'Run:        double-click unicorn-viz.cmd (or run it from a terminal with options)' \
  'Check:      unicorn-viz.cmd --self-test   (lists what is installed and which drop-ins are live)' \
  'Uninstall:  delete this folder' \
  '' \
  'Media player (media-01) needs VLC. If it is missing, the launcher offers to install it' \
  '(bundled installer under vendor\, or the download page). Everything else runs without it.' \
  '' \
  "$DROPIN_NOTE" \
  '' \
  'This build is unsigned: on first run Windows SmartScreen may show "Windows' \
  'protected your PC" - choose "More info" then "Run anyway".' \
  > "${APP}/README-PORTABLE.txt"

# Leave the assembled tree for Inno Setup (packaging/windows/UnicornViz.iss
# packages it via /DPayloadDir). This block sits right before zipping so the
# tree is complete; an earlier edit deleted it and CI's ISCC step found no tree.
if [[ -n "$PAYLOAD_OUT" ]]; then
  log "Leaving the assembled tree at ${PAYLOAD_OUT}/UnicornViz (for packaging/windows/UnicornViz.iss)"
  rm -rf "${PAYLOAD_OUT}/UnicornViz"
  cp -a "$APP" "${PAYLOAD_OUT}/UnicornViz"
  [[ -f "${PAYLOAD_OUT}/UnicornViz/LICENSE" ]] || die "payload-out tree is missing LICENSE"
fi

ZIP="${OUTPUT_DIR}/UnicornViz-Portable${LABEL:+-${LABEL}}-${VERSION}-win-x64.zip"
log "Zipping → ${ZIP}"
rm -f "$ZIP"
( cd "$WORK" && "$HOST_PY" -m zipfile -c "$ZIP" UnicornViz )

# Sanity: junk-free, runtime present, native wheels really are Windows ones.
"$HOST_PY" - "$ZIP" "$DROPINS_FILE" <<'PY'
import sys, zipfile
names = zipfile.ZipFile(sys.argv[1]).namelist()
top = {n.split('/')[1] for n in names if n.count('/') >= 1}
forbidden = {'.git', '.venv', '.venv-runtime', 'logs', 'docs', 'tests', 'build', 'recordings', 'screenshots'}
if not sys.argv[2]:
    forbidden.add('drop-ins')  # only a --dropins pack may ship drop-ins
bad = sorted(top & forbidden)
assert not bad, f'junk in zip: {bad[:5]}'
assert 'UnicornViz/runtime/python/python.exe' in names, 'python.exe missing'
assert 'UnicornViz/unicorn-viz.cmd' in names and 'UnicornViz/unicorn-viz-gui.ps1' in names and 'UnicornViz/tools/vlc-check.ps1' in names, 'launcher missing'
pyd = [n for n in names if n.endswith('.pyd')]
assert pyd, 'no .pyd extension modules: cross-install did not produce Windows wheels'
assert not any(n.endswith('.so') for n in names if 'site-packages' in n), 'Linux .so files leaked into site-packages'
assert not any('__pycache__' in n for n in names if 'site-packages' in n), 'host bytecode leaked into site-packages'
print(f'ok: {len(names)} entries, {len(pyd)} Windows extension modules', file=sys.stderr)
PY
log "Built ${ZIP} ($(du -h "$ZIP" | cut -f1))"
echo "$ZIP"
