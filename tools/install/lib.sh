#!/usr/bin/env bash

# Shared installer helpers for Unicorn Viz Linux installation flows.

set -euo pipefail

UV_REPO_OWNER="djunicorntears"
UV_REPO_NAME="unicorn-viz"
UV_DEFAULT_PREFIX="${HOME}/.local/share/unicorn-viz"
UV_DEFAULT_CHANNEL="stable"
UV_DISTRO_FAMILY=""
UV_DISTRO_ID=""
UV_DISTRO_LIKE=""
UV_DRY_RUN=0

uv_log() {
  echo "[unicorn-viz] $*"
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
        libpipewire-0.3-dev libasound2-dev ffmpeg git curl
      ;;
    dnf)
      uv_run sudo dnf install -y \
        "${python_bin}" "${python_bin}-devel" gcc-c++ make \
        SDL2-devel mesa-libGL-devel libffi-devel \
        pipewire-devel alsa-lib-devel git curl
      if ! uv_run sudo dnf install -y ffmpeg; then
        uv_warn "ffmpeg not available in default Fedora repos."
        uv_warn "Enable RPM Fusion if recording support is required."
      fi
      ;;
    pacman)
      uv_run sudo pacman -Sy --noconfirm \
        python python-pip sdl2 mesa libffi pipewire alsa-lib ffmpeg git curl
      ;;
    *)
      uv_die "Unsupported distribution: ${UV_DISTRO_ID:-unknown}. Install deps manually and retry."
      ;;
  esac
}

uv_create_venv_and_install() {
  local python_bin="$1"
  local venv_dir="$2"
  local source_dir="$3"

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
Comment=Audio-reactive demoscene visualizer
Exec=${symlink_path}
Icon=unicorn-viz
Terminal=false
Categories=AudioVideo;Graphics;
StartupNotify=true
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
