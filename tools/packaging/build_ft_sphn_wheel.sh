#!/usr/bin/env bash
#
# build_ft_sphn_wheel.sh -- build a sphn cp314t (free-threaded) manylinux_2_28
# wheel.  See W1 in docs/planning/bug-remediation-plan-2026-09-30.md and
# docs/planning/free-threaded-wheels-2026-09-30.md.
#
# Why: sphn 0.2.1 (audio read/write, Rust + pyo3 + maturin) has cp314 wheels
# but no cp314t, and demucs (the stem separation the mixer requires) depends on
# it, so a free-threaded environment cannot resolve demucs without this wheel.
# The pyo3 it uses (0.27) supports free-threaded builds, so no source change is
# needed; the build is `maturin build` against the free-threaded interpreter.
#
# How: like build_ft_wheels.sh, in rootless podman with a private store.  The
# toolchain image (tools/packaging/ft-sphn/Containerfile: manylinux_2_28 + a
# pinned Rust + maturin) is built once and cached.  The PyPI sdist is hash
# checked and built with `cargo --locked`, so the Rust dependency set is the one
# in the sdist's Cargo.lock.
#
# The module does not declare #[pymodule(gil_used = false)], so importing it
# turns the GIL back on (information, reported by ft_sphn_smoke.py).
#
# Usage:
#   tools/packaging/build_ft_sphn_wheel.sh [--out DIR] [--work DIR]
#                                          [--verify-python PATH] [--with-demucs]
#
#   --out DIR            where the finished wheel lands (default: <work>/out-sphn)
#   --work DIR           scratch + podman storage (default: /var/tmp/uv-wheel-build)
#   --verify-python PATH a 3.14 free-threaded interpreter to smoke-test with
#   --with-demucs        also install demucs (+ a CPU-only torch, ~200 MB) into the
#                        verify venv and check that it imports
#
# Old artifacts are never deleted: --out is only ever added to.  Windows is not
# built here.

set -Eeuo pipefail

# --- Pinned source (PyPI sdist) ----------------------------------------------
SPHN_VERSION="0.2.1"
SPHN_SDIST_SHA256="3b19b1fece67d979d84080458bed545d1f55ddc5abac6ca5deae2672a184c7fe"
TOOLCHAIN_IMAGE="uv-ft-sphn-toolchain:1"
MANYLINUX_PLAT="manylinux_2_28"

log() { echo "[build-ft-sphn] $*" >&2; }
die() { echo "[build-ft-sphn] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Inside the container: build with maturin.
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--inside" ]]; then
  cd /src
  mkdir -p /out
  # The opus crate builds libopus from bundled source whose CMakeLists asks for a
  # CMake compatibility older than 3.5, which CMake 4 (this image) refuses.  This
  # is CMake's own documented override; it only relaxes that policy floor.
  export CMAKE_POLICY_VERSION_MINIMUM=3.5
  # ...and this RHEL-family image installs libraries to lib64, which audiopus_sys
  # (it only searches lib) cannot find: "unable to find library -lopus".  cmake-rs
  # honors CMAKE_TOOLCHAIN_FILE, so pin the install dir to lib through one.
  echo 'set(CMAKE_INSTALL_LIBDIR lib CACHE STRING "" FORCE)' > /tmp/libdir-lib.cmake
  export CMAKE_TOOLCHAIN_FILE=/tmp/libdir-lib.cmake
  # maturin builds the extension against the interpreter it is told, as cp314t,
  # runs its own manylinux check, and strips the release binary.
  /opt/maturin-venv/bin/maturin build --release --locked \
    --interpreter /opt/python/cp314-cp314t/bin/python \
    --compatibility "$MANYLINUX_PLAT" --out /out >&2
  exit 0
fi

# ---------------------------------------------------------------------------
# Host side.
# ---------------------------------------------------------------------------
WORK=/var/tmp/uv-wheel-build
OUT=""
VERIFY_PY=""
WITH_DEMUCS=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    --verify-python) VERIFY_PY="$2"; shift 2 ;;
    --with-demucs) WITH_DEMUCS=1; shift ;;
    -h|--help) sed -n '2,34p' "$0" >&2; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done
OUT="${OUT:-$WORK/out-sphn}"

command -v podman >/dev/null || die "podman is required (rootless is fine)"
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$WORK/podman" "$OUT" "$WORK/sphn-src"
PODMAN=(env -u XDG_DATA_HOME -u XDG_CONFIG_HOME podman
        --root "$WORK/podman/root" --runroot "$WORK/podman/run")

# 1. Source: the PyPI sdist, verified by hash.
SDIST="$WORK/sphn-src/sphn-$SPHN_VERSION.tar.gz"
if [[ ! -f "$SDIST" ]]; then
  log "fetching sphn $SPHN_VERSION sdist"
  url="$(python3 - "$SPHN_VERSION" <<'PY'
import json, sys, urllib.request
d = json.load(urllib.request.urlopen(f'https://pypi.org/pypi/sphn/{sys.argv[1]}/json'))
print(next(u['url'] for u in d['urls'] if u['packagetype'] == 'sdist'))
PY
)"
  curl -fsSL -o "$SDIST" "$url"
fi
echo "$SPHN_SDIST_SHA256  $SDIST" | sha256sum -c - >&2 || die "sphn sdist hash mismatch"
TREE="$WORK/sphn-src/sphn-$SPHN_VERSION"
rm -rf "$TREE"
tar xzf "$SDIST" -C "$WORK/sphn-src"

# 2. Toolchain image (cached after the first build).
if ! "${PODMAN[@]}" image exists "$TOOLCHAIN_IMAGE"; then
  log "building $TOOLCHAIN_IMAGE (Rust + maturin; a few minutes, cached afterwards)"
  "${PODMAN[@]}" build -q -t "$TOOLCHAIN_IMAGE" -f "$SELF/ft-sphn/Containerfile" "$SELF/ft-sphn" >/dev/null
fi

# 3. Build inside it.
BEFORE="$(ls "$OUT")"
"${PODMAN[@]}" run --rm --security-opt label=disable \
  -v "$SELF/build_ft_sphn_wheel.sh:/build.sh:ro" -v "$TREE:/src" -v "$OUT:/out" \
  "$TOOLCHAIN_IMAGE" bash /build.sh --inside
log "wheels in $OUT:"
ls -1 "$OUT" | grep -vxF -f <(echo "$BEFORE") >&2 || true

if [[ -n "$VERIFY_PY" ]]; then
  log "verifying against $VERIFY_PY"
  VENV="$WORK/verify-venv-sphn"
  rm -rf "$VENV"
  "$VERIFY_PY" -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q numpy
  "$VENV/bin/python" -m pip install -q --no-index --find-links "$OUT" --no-deps sphn
  if [[ "$WITH_DEMUCS" == 1 ]]; then
    # torch from the CPU index: PyPI's Linux default is the CUDA build (GBs).
    "$VENV/bin/python" -m pip install -q --only-binary :all: \
      --extra-index-url https://download.pytorch.org/whl/cpu \
      --find-links "$OUT" "demucs"
  fi
  "$VENV/bin/python" "$SELF/ft_sphn_smoke.py" $([[ "$WITH_DEMUCS" == 1 ]] && echo --with-demucs)
fi
