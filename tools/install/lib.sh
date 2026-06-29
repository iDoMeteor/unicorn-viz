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

uv_fetch_to_file() {
  local url="$1"
  local output="$2"

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
      uv_run sudo apt-get update
      uv_run sudo apt-get install -y \
        "${python_bin}" "${python_bin}-venv" "${python_bin}-dev" \
        libsdl2-dev libgl1-mesa-dev libffi-dev \
        libpipewire-0.3-dev libasound2-dev \
        portaudio19-dev libsndfile1-dev \
        ffmpeg git curl
      ;;
    dnf)
      uv_run sudo dnf install -y \
        "${python_bin}" "${python_bin}-devel" gcc-c++ make \
        SDL2-devel mesa-libGL-devel libffi-devel \
        pipewire-devel alsa-lib-devel \
        portaudio-devel libsndfile-devel \
        git curl
      # ffmpeg is available via RPM Fusion (rpmfusion-free) on Fedora 38+.
      # Enable it with: dnf install -y https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
      if ! uv_run sudo dnf install -y ffmpeg; then
        uv_warn "ffmpeg not found. Enable RPM Fusion for recording support:"
        uv_warn "  dnf install -y https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-\$(rpm -E %fedora).noarch.rpm"
      fi
      ;;
    pacman)
      uv_run sudo pacman -Sy --noconfirm \
        python python-pip sdl2 mesa libffi pipewire alsa-lib \
        portaudio libsndfile ffmpeg git curl
      ;;
    *)
      uv_die "Unsupported distribution: ${UV_DISTRO_ID:-unknown}. Install deps manually and retry."
      ;;
  esac
}

# Provision a bundled python-build-standalone runtime into <runtime_root> and
# echo the path to its python interpreter. Locates tools/packaging/fetch_runtime.sh
# from the clone; if absent (curl-bootstrapped install), fetches it from the repo.
uv_provision_runtime() {
  local runtime_root="$1"
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
  python_path="$(bash "$fetch_script" --dest "$runtime_root" --os linux)"
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
    python_path="$(uv_provision_runtime "${install_root}/runtime")"
  fi

  uv_create_venv_and_install "$python_path" "${install_root}/venv" "$source_dir"
}

uv_create_venv_and_install() {
  local python_bin="$1"
  local venv_dir="$2"
  local source_dir="$3"

  if [[ "${UV_DRY_RUN}" -eq 1 ]]; then
    uv_log "dry-run: would create venv at ${venv_dir}"
    uv_log "dry-run: would install requirements from ${source_dir}/requirements.txt"
    uv_log "dry-run: would install the project from ${source_dir}"
    return 0
  fi

  uv_require_cmd "$python_bin"

  uv_run "$python_bin" -m venv "$venv_dir"
  uv_run "$venv_dir/bin/pip" install --upgrade pip wheel
  uv_run "$venv_dir/bin/pip" install -r "$source_dir/requirements.txt"
  uv_run "$venv_dir/bin/pip" install "$source_dir"
}

uv_install_desktop_entry() {
  local prefix="$1"

  local app_dir="${HOME}/.local/share/applications"
  local icon_dir="${HOME}/.local/share/icons/hicolor/256x256/apps"
  local bin_dir="${HOME}/.local/bin"
  local launcher_path="${prefix}/venv/bin/unicorn-viz"
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

  if [[ -L "$symlink_path" || -e "$symlink_path" ]]; then
    uv_run rm -f "$symlink_path"
  fi
  uv_run ln -s "$launcher_path" "$symlink_path"

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
