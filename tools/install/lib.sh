#!/usr/bin/env bash

# Shared installer helpers for Unicorn Viz Linux installation flows.

set -Eeuo pipefail

UV_REPO_OWNER="djunicorntears"
UV_REPO_NAME="unicorn-viz"
# UV_DEFAULT_PREFIX / UV_DEFAULT_CHANNEL are read by scripts that source this
# library (install.sh), so shellcheck cannot see their use from here.
# shellcheck disable=SC2034
UV_DEFAULT_PREFIX="${HOME}/.local/share/unicorn-viz"
# shellcheck disable=SC2034
UV_DEFAULT_CHANNEL="stable"
# shellcheck disable=SC2034
UV_DEFAULT_MANIFEST_URL="https://get.unicornviz.io/manifest.json"
UV_DISTRO_FAMILY=""
UV_DISTRO_ID=""
UV_DISTRO_LIKE=""
UV_DRY_RUN=0

# Directory containing this library. When sourced from a clone this resolves to
# tools/install/; when sourced from a curl-bootstrapped temp file the sibling
# packaging/ scripts won't be found locally and are fetched from the repo raw URL.
UV_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

uv_log() {
  echo "[unicorn-viz] $*"
}

# Print the failing command and line on any unhandled error. Sourcing scripts
# opt in with:  trap 'uv_err_trap "$LINENO" "$BASH_COMMAND"' ERR
uv_err_trap() {
  local line="$1"
  local cmd="$2"
  echo "[unicorn-viz] ERROR: command failed (line ${line}): ${cmd}" >&2
}

uv_warn() {
  echo "[unicorn-viz] WARNING: $*" >&2
}

uv_die() {
  echo "[unicorn-viz] ERROR: $*" >&2
  exit 1
}

uv_run() {
  if [[ "${UV_DRY_RUN}" -eq 1 ]]; then
    uv_log "dry-run: $*"
    return 0
  fi
  "$@"
}

uv_require_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || uv_die "Required command not found: $cmd"
}

# Run a command with root privileges. Uses sudo when not already root; runs
# directly when root (e.g. inside CI containers that have no sudo). Respects
# UV_DRY_RUN via uv_run.
uv_sudo() {
  if [[ "$(id -u)" -eq 0 ]]; then
    uv_run "$@"
  elif command -v sudo >/dev/null 2>&1; then
    uv_run sudo "$@"
  else
    uv_die "This step needs root, but you are not root and sudo is unavailable: $*"
  fi
}

uv_fetch_to_file() {
  local url="$1"
  local output="$2"

  # Local hand-off bundles: file:// needs no downloader at all.
  if [[ "$url" == file://* ]]; then
    local path="${url#file://}"
    [[ -f "$path" ]] || return 1
    uv_run cp "$path" "$output"
    return
  fi

  if command -v curl >/dev/null 2>&1; then
    uv_run curl -fsSL --retry 3 --retry-delay 2 -o "$output" "$url"
    return
  fi

  if command -v wget >/dev/null 2>&1; then
    uv_run wget -q -O "$output" "$url"
    return
  fi

  uv_die "Neither curl nor wget is available for downloading installer assets."
}

uv_fetch_text() {
  local url="$1"

  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --retry 3 --retry-delay 2 "$url"
    return
  fi

  if command -v wget >/dev/null 2>&1; then
    wget -q -O - "$url"
    return
  fi

  uv_die "Neither curl nor wget is available for downloading release metadata."
}

uv_detect_distro() {
  if [[ ! -f /etc/os-release ]]; then
    uv_die "Cannot detect Linux distribution (missing /etc/os-release)."
  fi

  # shellcheck disable=SC1091
  source /etc/os-release
  UV_DISTRO_ID="${ID:-}"
  UV_DISTRO_LIKE="${ID_LIKE:-}"

  case "${UV_DISTRO_ID}" in
    ubuntu|debian|linuxmint|pop)
      UV_DISTRO_FAMILY="apt"
      ;;
    fedora|rhel|centos|rocky|almalinux)
      UV_DISTRO_FAMILY="dnf"
      ;;
    arch|manjaro|endeavouros)
      UV_DISTRO_FAMILY="pacman"
      ;;
    *)
      if [[ " ${UV_DISTRO_LIKE} " == *" debian "* ]]; then
        UV_DISTRO_FAMILY="apt"
      elif [[ " ${UV_DISTRO_LIKE} " == *" rhel "* ]] || [[ " ${UV_DISTRO_LIKE} " == *" fedora "* ]]; then
        UV_DISTRO_FAMILY="dnf"
      elif [[ " ${UV_DISTRO_LIKE} " == *" arch "* ]]; then
        UV_DISTRO_FAMILY="pacman"
      else
        UV_DISTRO_FAMILY=""
      fi
      ;;
  esac
}

uv_install_system_deps() {
  local python_bin="$1"

  uv_detect_distro

  case "${UV_DISTRO_FAMILY}" in
    apt)
      uv_sudo apt-get update
      uv_sudo apt-get install -y \
        "${python_bin}" "${python_bin}-venv" "${python_bin}-dev" \
        libsdl2-dev libgl1-mesa-dev libffi-dev \
        libpipewire-0.3-dev libasound2-dev \
        portaudio19-dev libsndfile1-dev \
        ffmpeg git curl
      ;;
    dnf)
      uv_sudo dnf install -y \
        "${python_bin}" "${python_bin}-devel" gcc-c++ make \
        SDL2-devel mesa-libGL-devel libffi-devel \
        pipewire-devel alsa-lib-devel \
        portaudio-devel libsndfile-devel \
        git curl
      # ffmpeg is available via RPM Fusion (rpmfusion-free) on Fedora 38+.
      # Enable it with: dnf install -y https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
      if ! uv_sudo dnf install -y ffmpeg; then
        uv_warn "ffmpeg not found. Enable RPM Fusion for recording support:"
        uv_warn "  dnf install -y https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-\$(rpm -E %fedora).noarch.rpm"
      fi
      ;;
    pacman)
      uv_sudo pacman -Sy --noconfirm \
        python python-pip sdl2 mesa libffi pipewire alsa-lib \
        portaudio libsndfile ffmpeg git curl
      ;;
    *)
      uv_die "Unsupported distribution: ${UV_DISTRO_ID:-unknown}. Install deps manually and retry."
      ;;
  esac
}

# Which bundled CPython flavor to provision: ft = 3.14 free-threaded (cp314t),
# gil = legacy 3.11.  ft is wanted (W1: 3.11 cannot load a single mixer track)
# but only works when our cp314t wheels (moderngl, glcontext, python-rtmidi,
# opencv) are on hand, because PyPI has none: so ft is chosen on x86-64 Linux
# when <source_dir>/wheelhouse or $UV_WHEELHOUSE exists, and gil otherwise
# (other arches; a plain git checkout in CI).  UV_RUNTIME_FLAVOR=gil|ft forces
# a choice.
uv_runtime_flavor() {
  local source_dir="${1:-}"
  if [[ -n "${UV_RUNTIME_FLAVOR:-}" ]]; then
    echo "$UV_RUNTIME_FLAVOR"
  elif [[ "$(uname -m)" == "x86_64" ]] && [[ -n "$(uv_wheelhouse_args "$source_dir")" ]]; then
    echo "ft"
  else
    echo "gil"
  fi
}

# Provision a bundled python-build-standalone runtime into <runtime_root> and
# echo the path to its python interpreter. Locates tools/packaging/fetch_runtime.sh
# from the clone; if absent (curl-bootstrapped install), fetches it from the repo.
uv_provision_runtime() {
  local runtime_root="$1"
  local source_dir="${2:-}"
  local fetch_script="${UV_LIB_DIR}/../packaging/fetch_runtime.sh"
  local tmp_fetch=""

  if [[ ! -f "$fetch_script" ]]; then
    tmp_fetch="$(mktemp)"
    uv_fetch_to_file \
      "https://raw.githubusercontent.com/${UV_REPO_OWNER}/${UV_REPO_NAME}/main/tools/packaging/fetch_runtime.sh" \
      "$tmp_fetch"
    fetch_script="$tmp_fetch"
  fi

  if [[ "${UV_DRY_RUN}" -eq 1 ]]; then
    # Diagnostics to stderr; only the interpreter path goes to stdout so the
    # caller's command substitution captures a clean single line.
    uv_log "dry-run: would provision bundled runtime into ${runtime_root}/python" >&2
    echo "${runtime_root}/python/bin/python3"
    [[ -n "$tmp_fetch" ]] && rm -f "$tmp_fetch"
    return 0
  fi

  local python_path
  python_path="$(bash "$fetch_script" --dest "$runtime_root" --os linux --flavor "$(uv_runtime_flavor "$source_dir")")"
  [[ -n "$tmp_fetch" ]] && rm -f "$tmp_fetch"

  if [[ -z "$python_path" ]]; then
    uv_die "Runtime provisioning did not return an interpreter path."
  fi
  echo "$python_path"
}

# Provision the bundled runtime, then build the venv and install the app with it.
# Pass UV_SYSTEM_PYTHON=<bin> to skip bundling and use a system interpreter.
uv_install_runtime_and_app() {
  local install_root="$1"
  local source_dir="$2"
  local python_path

  if [[ -n "${UV_SYSTEM_PYTHON:-}" ]]; then
    uv_log "Using system Python: ${UV_SYSTEM_PYTHON} (bundled runtime skipped)"
    python_path="${UV_SYSTEM_PYTHON}"
  else
    uv_log "Provisioning bundled Python runtime"
    python_path="$(uv_provision_runtime "${install_root}/runtime" "$source_dir")"
  fi

  uv_create_venv_and_install "$python_path" "${install_root}/venv" "$source_dir"
}

# Echo pip's --find-links arguments for our own prebuilt wheels (cp314t
# moderngl / glcontext / python-rtmidi that PyPI does not carry): the payload's
# wheelhouse/ folder first, else $UV_WHEELHOUSE.  Echoes nothing when neither
# exists, in which case pip falls back to PyPI alone.
uv_wheelhouse_args() {
  local source_dir="${1:-}"
  if [[ -n "$source_dir" && -d "${source_dir}/wheelhouse" ]]; then
    echo "--find-links ${source_dir}/wheelhouse"
  elif [[ -n "${UV_WHEELHOUSE:-}" && -d "${UV_WHEELHOUSE}" ]]; then
    echo "--find-links ${UV_WHEELHOUSE}"
  fi
}

# Print the drop-in requirement files to install, one per line.  A packaged
# payload carries the curated union (requirements-dropins.txt, already carrying
# the pack's +pkg/-pkg edits) and wins; a clone falls back to each checked-out
# drop-in's own requirements.txt.  Files with no active requirement lines are
# skipped.
uv_dropin_requirement_files() {
  local source_dir="$1" f
  if [[ -f "${source_dir}/requirements-dropins.txt" ]]; then
    echo "${source_dir}/requirements-dropins.txt"
    return 0
  fi
  for f in "${source_dir}"/drop-ins/*/requirements.txt; do
    [[ -f "$f" ]] || continue
    if grep -qvE '^[[:space:]]*(#|$)' "$f"; then echo "$f"; fi
  done
}

# Packages that must be installed with --no-deps, with the extra packages they
# do need installed normally.  mediapipe's dependency chain pulls
# opencv-contrib-python, which owns the same `cv2` import path as the core's
# opencv-python-headless and silently corrupts it (webcam-01's requirements.txt
# explains).  Format: <package> <extra deps...>.
UV_NODEPS_PACKAGES=("mediapipe absl-py flatbuffers")

# Echo the extra deps if requirement line $1 names a UV_NODEPS_PACKAGES entry
# (and return 0), else return 1.
uv_nodeps_extras() {
  local line="$1" entry name
  for entry in "${UV_NODEPS_PACKAGES[@]}"; do
    name="${entry%% *}"
    if [[ "$line" =~ ^${name}([^A-Za-z0-9_.-]|$) ]]; then
      echo "${entry#"$name"}"
      return 0
    fi
  done
  return 1
}

# Install one drop-in requirements file without letting it abort the install.
# Drop-in dependencies are optional by design (each drop-in degrades without
# them), and some have no wheel on every interpreter (demucs, mediapipe,
# usd-core on 3.14t), so a single unresolvable line must not take down the rest.
# Requirements named in UV_NODEPS_PACKAGES install on their own with --no-deps.
# The rest are tried as one file first; on failure retried one requirement at a
# time, warning about each one skipped.  The root requirements.txt is passed as
# a constraints file so a drop-in can never move a core pin.
uv_pip_install_optional() {
  local pip="$1" constraints="$2" reqfile="$3"
  shift 3
  local line extras filtered
  filtered="$(mktemp)"
  while IFS= read -r line; do
    line="${line%%#*}"
    line="$(echo "$line" | xargs)"
    [[ -z "$line" ]] && continue
    if extras="$(uv_nodeps_extras "$line")"; then
      # shellcheck disable=SC2086  # extras is a space-separated package list
      if uv_run "$pip" install --prefer-binary --no-deps "$@" "$line" \
        && { [[ -z "$extras" ]] || uv_run "$pip" install --prefer-binary -c "$constraints" "$@" $extras; }; then
        :
      else
        uv_warn "Skipped ${line} (no installable build for this interpreter); the drop-in that needs it will run without it"
      fi
    else
      echo "$line" >>"$filtered"
    fi
  done <"$reqfile"

  if [[ -s "$filtered" ]]; then
    if ! uv_run "$pip" install --prefer-binary -c "$constraints" -r "$filtered" "$@"; then
      uv_warn "Some dependencies in ${reqfile} did not install together; retrying one at a time"
      while IFS= read -r line; do
        uv_run "$pip" install --prefer-binary -c "$constraints" "$@" "$line" \
          || uv_warn "Skipped ${line} (no installable build for this interpreter); the drop-in that needs it will run without it"
      done <"$filtered"
    fi
  fi
  rm -f "$filtered"
  return 0
}

uv_create_venv_and_install() {
  local python_bin="$1"
  local venv_dir="$2"
  local source_dir="$3"

  if [[ "${UV_DRY_RUN}" -eq 1 ]]; then
    uv_log "dry-run: would create venv at ${venv_dir}"
    uv_log "dry-run: would install requirements from ${source_dir}/requirements.txt"
    if [[ "${UV_NO_DROPIN_DEPS:-0}" -ne 1 ]]; then
      local dry_f
      while IFS= read -r dry_f; do
        [[ -n "$dry_f" ]] && uv_log "dry-run: would install drop-in requirements from ${dry_f}"
      done < <(uv_dropin_requirement_files "$source_dir")
    fi
    uv_log "dry-run: would install the project from ${source_dir}"
    return 0
  fi

  uv_require_cmd "$python_bin"

  # Word-splitting of the find-links args is intended (two shell words).
  # shellcheck disable=SC2207
  local wheel_args=($(uv_wheelhouse_args "$source_dir"))

  uv_run "$python_bin" -m venv "$venv_dir"
  uv_run "$venv_dir/bin/pip" install --upgrade pip wheel
  uv_run "$venv_dir/bin/pip" install --prefer-binary "${wheel_args[@]}" -r "$source_dir/requirements.txt"

  if [[ "${UV_NO_DROPIN_DEPS:-0}" -ne 1 ]]; then
    local reqfile
    while IFS= read -r reqfile; do
      [[ -z "$reqfile" ]] && continue
      uv_log "Installing drop-in dependencies from ${reqfile}"
      uv_pip_install_optional "$venv_dir/bin/pip" "$source_dir/requirements.txt" "$reqfile" "${wheel_args[@]}"
    done < <(uv_dropin_requirement_files "$source_dir")
  fi

  uv_run "$venv_dir/bin/pip" install "${wheel_args[@]}" "$source_dir"
}

uv_install_desktop_entry() {
  local prefix="$1"

  local app_dir="${HOME}/.local/share/applications"
  local icon_dir="${HOME}/.local/share/icons/hicolor/256x256/apps"
  local bin_dir="${HOME}/.local/bin"
  local symlink_path="${bin_dir}/unicorn-viz"
  local desktop_file="${app_dir}/unicorn-viz.desktop"
  local icon_target="${icon_dir}/unicorn-viz.png"
  local source_icon="${prefix}/assets/icons/unicorn-viz.png"

  uv_run mkdir -p "$app_dir" "$icon_dir" "$bin_dir"

  if [[ ! -f "$source_icon" ]]; then
    uv_warn "Icon file missing at ${source_icon}; desktop entry will still be created."
  else
    uv_run cp "$source_icon" "$icon_target"
  fi

  # Launcher is a wrapper (not a bare symlink) so it can export
  # UNICORNVIZ_APP_ROOT, which makes the app resolve assets under <prefix>/assets
  # even though the package is pip-installed into the venv's site-packages.
  if [[ "${UV_DRY_RUN}" -eq 1 ]]; then
    uv_log "dry-run: write launcher ${symlink_path}"
  else
    if [[ -L "$symlink_path" || -e "$symlink_path" ]]; then
      rm -f "$symlink_path"
    fi
    cat >"$symlink_path" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export UNICORNVIZ_APP_ROOT="${prefix}"
exec "${prefix}/venv/bin/unicorn-viz" "\$@"
EOF
    chmod +x "$symlink_path"
  fi

  if [[ "${UV_DRY_RUN}" -eq 1 ]]; then
    uv_log "dry-run: write ${desktop_file}"
  else
    cat >"$desktop_file" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Unicorn Viz
GenericName=Audio-Reactive Visualizer
Comment=Fullscreen OpenGL demoscene visualizer with audio and MIDI control
Exec=${symlink_path} %U
Icon=unicorn-viz
Terminal=false
Categories=AudioVideo;Audio;Graphics;Player;
Keywords=visualizer;demoscene;vj;audio;midi;ansi;
StartupNotify=true
StartupWMClass=unicorn-viz
EOF
  fi

  if command -v update-desktop-database >/dev/null 2>&1; then
    uv_run update-desktop-database "$app_dir" || true
  fi

  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    uv_run gtk-update-icon-cache -f "${HOME}/.local/share/icons/hicolor" || true
  fi

  if [[ ":$PATH:" != *":${HOME}/.local/bin:"* ]]; then
    uv_warn "${HOME}/.local/bin is not on PATH. Add it to launch unicorn-viz from terminal."
  fi
}

uv_uninstall_installation() {
  local prefix="$1"

  uv_log "Removing Unicorn Viz installation from ${prefix}"
  uv_run rm -rf "$prefix"
  uv_run rm -f "${HOME}/.local/bin/unicorn-viz"
  uv_run rm -f "${HOME}/.local/share/applications/unicorn-viz.desktop"
  uv_run rm -f "${HOME}/.local/share/icons/hicolor/256x256/apps/unicorn-viz.png"

  if command -v update-desktop-database >/dev/null 2>&1; then
    uv_run update-desktop-database "${HOME}/.local/share/applications" || true
  fi

  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    uv_run gtk-update-icon-cache -f "${HOME}/.local/share/icons/hicolor" || true
  fi

  uv_log "Uninstall complete."
}

# Interpreter used to read manifest.json. The bundled runtime is provisioned
# before the manifest is consulted, so installers export UV_JSON_PYTHON to it;
# --system-python installs point it at the system interpreter instead.
uv_json_python() {
  if [[ -n "${UV_JSON_PYTHON:-}" ]]; then
    echo "$UV_JSON_PYTHON"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  else
    uv_die "No Python interpreter available to read the release manifest."
  fi
}

# Print one leaf value from a manifest. Path components are separate arguments
# (versions contain dots), e.g.:
#   uv_manifest_query "$m" channels stable version
#   uv_manifest_query "$m" releases "$VERSION" artifacts source url
# Exits non-zero (quietly) when the path is missing.
uv_manifest_query() {
  local manifest="$1"
  shift
  local py
  py="$(uv_json_python)"
  "$py" - "$manifest" "$@" <<'PY'
import json, sys
with open(sys.argv[1], encoding='utf-8') as handle:
    node = json.load(handle)
try:
    for part in sys.argv[2:]:
        node = node[part]
except (KeyError, TypeError):
    sys.exit(1)
if isinstance(node, (dict, list)):
    sys.exit(1)
print(node)
PY
}

uv_sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    uv_die "Neither sha256sum nor shasum is available to verify downloads."
  fi
}

# Resolve an artifact URL from a manifest: absolute URLs pass through, relative
# ones (hand-off bundles) are joined onto the manifest's own directory.
uv_resolve_url() {
  local manifest_url="$1" ref="$2"
  if [[ "$ref" =~ ^[A-Za-z][A-Za-z0-9+.-]*:// ]]; then
    echo "$ref"
  else
    echo "${manifest_url%/*}/${ref}"
  fi
}
