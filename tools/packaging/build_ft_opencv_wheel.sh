#!/usr/bin/env bash
#
# build_ft_opencv_wheel.sh -- build an opencv-python-headless cp314t
# (free-threaded) manylinux_2_28 wheel.  See W1 in
# docs/planning/bug-remediation-plan-2026-09-30.md and
# docs/planning/free-threaded-wheels-2026-09-30.md.
#
# Why it exists: PyPI ships opencv-python-headless only as a cp37-abi3 wheel
# (OpenCV hard-codes -DPYTHON3_LIMITED_API=ON), and the stable ABI does not
# exist on free-threaded builds, so no upstream wheel can install there.
# PyPI also has no sdist for the version requirements.txt pins (4.13.0.92), so
# this builds from the matching git tag of opencv/opencv-python, which carries
# the OpenCV sources as a submodule; both are pinned by commit.
#
# How: like build_ft_wheels.sh, in rootless podman with a private store.  A
# dependency image (tools/packaging/ft-opencv/Containerfile: manylinux_2_28 +
# FFmpeg + libvpx, because video-clips-01 decodes files through
# cv2.VideoCapture) is built once and cached; the OpenCV build then runs in it
# with setup.py's limited-API flag removed, and auditwheel vendors the FFmpeg
# libraries into the wheel as upstream's wheels do.
#
# Deliberate differences from upstream's wheel: no Qt (headless), no contrib,
# no AVIF, no LAPACK.  None is used by this project.
#
# Usage:
#   tools/packaging/build_ft_opencv_wheel.sh [--out DIR] [--work DIR]
#                                            [--verify-python PATH] [--clean]
#
#   --out DIR            where the finished wheel lands (default: <work>/out-opencv)
#   --work DIR           scratch, source checkout and podman storage
#                        (default: /var/tmp/uv-wheel-build)
#   --verify-python PATH a 3.14 free-threaded interpreter to smoke-test with
#   --clean              discard the previous incremental build tree first
#
# Old artifacts are never deleted: --out is only ever added to.  Windows is
# not built here.

set -Eeuo pipefail

# --- Pinned source -----------------------------------------------------------
# OPENCV_PYTHON_VERSION must equal the opencv-python-headless pin in
# requirements.txt (tests/test_ft_wheels_build.py enforces it).
OPENCV_PYTHON_VERSION="4.13.0.92"
OPENCV_PYTHON_TAG="92"
OPENCV_PYTHON_COMMIT="4ddfc013fd1f13d9b9e379dbebf2cdbeb052e7f8"
OPENCV_COMMIT="b4c5ec4042f097e2a5b386b9d413ec7333d0a184"
# Build-time numpy: oldest release with cp314t wheels (also upstream's own pin
# for 3.14), so the wheel works with any newer numpy at run time.
NUMPY_BUILD="2.3.2"

DEPS_IMAGE="uv-ft-opencv-deps:1"
MANYLINUX_PLAT="manylinux_2_28_x86_64"

log() { echo "[build-ft-opencv] $*" >&2; }
die() { echo "[build-ft-opencv] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Inside the container: configure, compile, repair.
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--inside" ]]; then
  PY=/opt/python/cp314-cp314t/bin/python
  [[ -d /tmp/bv ]] || $PY -m venv /tmp/bv
  /tmp/bv/bin/python -m pip install -q --upgrade pip
  /tmp/bv/bin/python -m pip install -q "numpy==$NUMPY_BUILD" scikit-build cmake ninja \
    setuptools wheel packaging
  export PATH=/tmp/bv/bin:$PATH
  cd /src
  # The stable ABI cannot exist on a free-threaded build: drop the hard-coded flag
  # (idempotent), so the bindings are built against the full C API as cp314t.
  sed -i '/"-DPYTHON3_LIMITED_API=ON",/d' setup.py
  if grep -q "PYTHON3_LIMITED_API=ON" setup.py && ! grep -q '^# *uv-threads' setup.py; then
    grep -n "LIMITED_API" setup.py >&2
  fi
  export ENABLE_HEADLESS=1
  export CMAKE_BUILD_PARALLEL_LEVEL="$(nproc)" MAKEFLAGS="-j$(nproc)"
  export CMAKE_ARGS="-DCMAKE_PREFIX_PATH=/ffmpeg_build"
  log "compiling OpenCV $OPENCV_PYTHON_VERSION with $(nproc) jobs"
  rm -rf /tmp/raw && mkdir -p /tmp/raw /out
  /tmp/bv/bin/python -m pip wheel --no-build-isolation --no-deps -w /tmp/raw . >&2
  for w in /tmp/raw/*.whl; do
    log "repair $(basename "$w")"
    auditwheel repair --plat "$MANYLINUX_PLAT" -w /out "$w" >&2
  done
  exit 0
fi

# ---------------------------------------------------------------------------
# Host side.
# ---------------------------------------------------------------------------
WORK=/var/tmp/uv-wheel-build
OUT=""
VERIFY_PY=""
CLEAN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    --verify-python) VERIFY_PY="$2"; shift 2 ;;
    --clean) CLEAN=1; shift ;;
    -h|--help) sed -n '2,38p' "$0" >&2; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done
OUT="${OUT:-$WORK/out-opencv}"
SRC="$WORK/opencv-python"

command -v podman >/dev/null || die "podman is required (rootless is fine)"
command -v git >/dev/null || die "git is required"
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$WORK/podman" "$OUT"
PODMAN=(env -u XDG_DATA_HOME -u XDG_CONFIG_HOME podman
        --root "$WORK/podman/root" --runroot "$WORK/podman/run")

# 1. Source: the pinned tag and submodule, verified by commit.
if [[ ! -d "$SRC/.git" ]]; then
  log "cloning opencv-python tag $OPENCV_PYTHON_TAG"
  git clone -q --depth 1 --branch "$OPENCV_PYTHON_TAG" \
    https://github.com/opencv/opencv-python.git "$SRC"
fi
[[ "$(git -C "$SRC" rev-parse HEAD)" == "$OPENCV_PYTHON_COMMIT" ]] \
  || die "$SRC is not at $OPENCV_PYTHON_COMMIT"
git -C "$SRC" submodule update -q --init --depth 1 opencv
[[ "$(git -C "$SRC/opencv" rev-parse HEAD)" == "$OPENCV_COMMIT" ]] \
  || die "$SRC/opencv is not at $OPENCV_COMMIT"
if [[ "$CLEAN" == 1 ]]; then rm -rf "$SRC/_skbuild"; fi

# 2. Dependency image (cached after the first build).
if ! "${PODMAN[@]}" image exists "$DEPS_IMAGE"; then
  log "building $DEPS_IMAGE (FFmpeg + libvpx; ~15 minutes, cached afterwards)"
  "${PODMAN[@]}" build -q -t "$DEPS_IMAGE" -f "$SELF/ft-opencv/Containerfile" "$SELF/ft-opencv" >/dev/null
fi

# 3. Build and repair inside it.
BEFORE="$(ls "$OUT")"
"${PODMAN[@]}" run --rm --security-opt label=disable \
  -v "$SELF/build_ft_opencv_wheel.sh:/build.sh:ro" -v "$SRC:/src" -v "$OUT:/out" \
  "$DEPS_IMAGE" bash /build.sh --inside
log "wheels in $OUT:"
ls -1 "$OUT" | grep -vxF -f <(echo "$BEFORE") >&2 || true

if [[ -n "$VERIFY_PY" ]]; then
  log "verifying against $VERIFY_PY"
  VENV="$WORK/verify-venv-opencv"
  rm -rf "$VENV"
  "$VERIFY_PY" -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q "numpy==$NUMPY_BUILD"
  "$VENV/bin/python" -m pip install -q --no-index --find-links "$OUT" --no-deps opencv-python-headless
  "$VENV/bin/python" "$SELF/ft_opencv_smoke.py"
fi
