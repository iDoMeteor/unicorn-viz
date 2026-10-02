#!/usr/bin/env bash
#
# build_patched_ft_opencv_wheel.sh -- build the opencv-python-headless 4.13.0.92
# free-threaded (cp314t) manylinux_2_28 wheel of the downstream project
# (unicorn-viz, "UV") with one difference: cv2 declares free-threading support
# (Py_MOD_GIL_NOT_USED), so `import cv2` no longer re-enables the GIL.
#
# This mirrors /home/jj/Repos/unicorn-viz/tools/packaging/build_ft_opencv_wheel.sh
# (read-only reference; nothing in the UV tree is modified):
#   - the same pinned sources: opencv-python git tag 92 (commit 4ddfc013...)
#     and its OpenCV submodule (b4c5ec40... = 4.13.0);
#   - the same dependency image, built from UV's ft-opencv/Containerfile
#     (manylinux_2_28 + FFmpeg 8.0.1, plain LGPL, + libvpx 1.15.2);
#   - the same limited-API removal from setup.py, numpy 2.3.2 at build time,
#     ENABLE_HEADLESS=1, `pip wheel --no-build-isolation`, and
#     `auditwheel repair --plat manylinux_2_28_x86_64`;
#   - the same smoke test (ft_opencv_smoke.py, with its licence checks).
# The additions are: (1) wheels/patches/opencv-4.13.0-free-threading.patch is
# applied to the OpenCV submodule checkout before the build; (2) the finished
# wheel gets PEP 427 build tag 1 (`python -m wheel tags --build 1 --remove`),
# which is what makes pip prefer it over the published, build-tag-less wheel of
# the same version, which stays untouched; (3) a manifest is written.
#
# What the patch does (see its hunks): declares Py_MOD_GIL_NOT_USED in the
# module init; serializes pycvRedirectError's static `last_on_error`; iterates a
# PyDict_Copy snapshot wherever a user dict is walked with PyDict_Next (flann,
# the generic std::map converter, dnn LayerParams) and a PyList_GetSlice
# snapshot in the three gapi list walkers; puts mutexes around the dnn
# `pyLayers` registry and the three highgui callback registries.
#
# Nothing is published, pushed or installed on the host: the wheel lands in
# --out and the wheelhouse is not touched.  Podman is rootless with a private
# storage dir under --work.  The sources are cloned from github (or from
# $OPENCV_PYTHON_REPO if set) into --work, never into UV's work dir.
#
# Usage:
#   wheels/build_patched_ft_opencv_wheel.sh [--out DIR] [--work DIR]
#       [--uv-packaging DIR] [--seed-image-from UV_WORK_DIR]
#       [--verify-python PATH] [--clean]
#
#   --out DIR        where the wheel and its manifest land (default <work>/out)
#   --work DIR       source checkout, podman storage, staging
#                    (default /var/tmp/ft-opencv-patched)
#   --uv-packaging DIR  UV's tools/packaging (Containerfile and smoke test are
#                    read from there)  (default /home/jj/Repos/unicorn-viz/tools/packaging)
#   --seed-image-from DIR  copy the already built uv-ft-opencv-deps image out of
#                    UV's wheel-build work dir (DIR/podman/root) into our private
#                    storage instead of spending ~15 minutes rebuilding it.
#                    UV's directory is only read.  Only valid while our storage
#                    has no image yet.
#   --verify-python PATH  a 3.14 free-threaded interpreter: install the wheel
#                    into a scratch venv and run the GIL check + UV's smoke test
#   --clean          discard the previous incremental build tree first

set -Eeuo pipefail

# --- Pinned source (same as UV's script) ---------------------------------------
OPENCV_PYTHON_VERSION="4.13.0.92"
OPENCV_PYTHON_TAG="92"
OPENCV_PYTHON_COMMIT="4ddfc013fd1f13d9b9e379dbebf2cdbeb052e7f8"
OPENCV_COMMIT="b4c5ec4042f097e2a5b386b9d413ec7333d0a184"
NUMPY_BUILD="2.3.2"
DEPS_IMAGE="uv-ft-opencv-deps:1"
MANYLINUX_PLAT="manylinux_2_28_x86_64"
# PEP 427 build tag: bump on every rebuild of the same version.
BUILD_TAG="1"

log() { echo "[build-patched-opencv] $*" >&2; }
die() { echo "[build-patched-opencv] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Inside the container: configure, compile, repair, tag.  Identical to UV's
# --inside mode except for the build-tag step and the build-tools record.
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
  if grep -q '^ *"-DPYTHON3_LIMITED_API=ON",' setup.py; then
    echo "the PYTHON3_LIMITED_API cmake flag is still in setup.py" >&2; exit 1
  fi
  export ENABLE_HEADLESS=1
  export CMAKE_BUILD_PARALLEL_LEVEL="$(nproc)" MAKEFLAGS="-j$(nproc)"
  export CMAKE_ARGS="-DCMAKE_PREFIX_PATH=/ffmpeg_build"
  log "compiling OpenCV $OPENCV_PYTHON_VERSION (patched) with $(nproc) jobs"
  rm -rf /tmp/raw && mkdir -p /tmp/raw /out
  /tmp/bv/bin/python -m pip wheel --no-build-isolation --no-deps -w /tmp/raw . >&2
  for w in /tmp/raw/*.whl; do
    log "repair $(basename "$w")"
    auditwheel repair --plat "$MANYLINUX_PLAT" -w /tmp/repaired "$w" >&2
  done
  for w in /tmp/repaired/*.whl; do
    log "build tag $BUILD_TAG: $(basename "$w")"
    /tmp/bv/bin/python -m wheel tags --build "$BUILD_TAG" --remove "$w" >&2
  done
  cp /tmp/repaired/*.whl /out/
  { /tmp/bv/bin/python -m pip list --format=freeze; echo "auditwheel==$(auditwheel --version | head -1 | awk '{print $2}')"; } \
    > /out/build-tools.txt
  exit 0
fi

# ---------------------------------------------------------------------------
# Host side.
# ---------------------------------------------------------------------------
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH="$HERE/patches/opencv-4.13.0-free-threading.patch"
WORK=/var/tmp/ft-opencv-patched
OUT=""
UVPKG=/home/jj/Repos/unicorn-viz/tools/packaging
SEED_FROM=""
VERIFY_PY=""
CLEAN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    --uv-packaging) UVPKG="$2"; shift 2 ;;
    --seed-image-from) SEED_FROM="$2"; shift 2 ;;
    --verify-python) VERIFY_PY="$2"; shift 2 ;;
    --clean) CLEAN=1; shift ;;
    -h|--help) sed -n '2,52p' "$0" >&2; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done
OUT="${OUT:-$WORK/out}"
SRC="$WORK/opencv-python"
STAGING="$WORK/staging"
REPO_URL="${OPENCV_PYTHON_REPO:-https://github.com/opencv/opencv-python.git}"

command -v podman >/dev/null || die "podman is required (rootless is fine)"
command -v git >/dev/null || die "git is required"
[[ -f "$PATCH" ]] || die "missing $PATCH"
[[ -f "$UVPKG/ft-opencv/Containerfile" && -f "$UVPKG/ft_opencv_smoke.py" ]] \
  || die "$UVPKG does not look like UV's tools/packaging"
mkdir -p "$WORK/podman" "$OUT"
PODMAN=(env -u XDG_DATA_HOME -u XDG_CONFIG_HOME podman
        --root "$WORK/podman/root" --runroot "$WORK/podman/run")

# 1. Source: the pinned tag and submodule, verified by commit.
if [[ ! -d "$SRC/.git" ]]; then
  log "cloning opencv-python tag $OPENCV_PYTHON_TAG from $REPO_URL"
  git clone -q --depth 1 --branch "$OPENCV_PYTHON_TAG" "$REPO_URL" "$SRC" 2>/dev/null
fi
[[ "$(git -C "$SRC" rev-parse HEAD)" == "$OPENCV_PYTHON_COMMIT" ]] \
  || die "$SRC is not at $OPENCV_PYTHON_COMMIT"
git -C "$SRC" submodule update -q --init --depth 1 opencv
[[ "$(git -C "$SRC/opencv" rev-parse HEAD)" == "$OPENCV_COMMIT" ]] \
  || die "$SRC/opencv is not at $OPENCV_COMMIT"
if [[ "$CLEAN" == 1 ]]; then rm -rf "$SRC/_skbuild"; fi

# 2. The patch, on the OpenCV checkout.  A marker records which patch is
#    applied; if the patch changed, the tracked files are reset first (the
#    touched files are recompiled either way, the rest of _skbuild is reused).
PATCH_SHA="$(sha256sum "$PATCH" | cut -d' ' -f1)"
MARK="$WORK/.applied-patch-sha256"
if [[ "$(cat "$MARK" 2>/dev/null || true)" != "$PATCH_SHA" ]]; then
  git -C "$SRC/opencv" checkout -q -- .
  log "applying $(basename "$PATCH") (sha256 ${PATCH_SHA:0:12})"
  git -C "$SRC/opencv" apply --check "$PATCH" || die "the patch does not apply to OpenCV $OPENCV_COMMIT"
  git -C "$SRC/opencv" apply "$PATCH"
  echo "$PATCH_SHA" > "$MARK"
else
  log "patch already applied (sha256 ${PATCH_SHA:0:12})"
fi

# 3. Dependency image (cached in our private storage after the first build).
if ! "${PODMAN[@]}" image exists "$DEPS_IMAGE"; then
  if [[ -n "$SEED_FROM" ]]; then
    # Read-only on UV's side: `podman unshare cp -a` can read the sub-uid owned
    # layer dirs, and the copy has its libpod db dropped (it only describes
    # containers; the image store is containers/storage, which stays).
    log "seeding the image store from $SEED_FROM/podman/root (UV's dir is only read)"
    [[ -d "$SEED_FROM/podman/root" ]] || die "$SEED_FROM/podman/root not found"
    rm -rf "$WORK/podman/root" "$WORK/podman/run"
    mkdir -p "$WORK/podman"
    "${PODMAN[@]}" unshare cp -a "$SEED_FROM/podman/root" "$WORK/podman/root.seed" 2>/dev/null || true
    rm -rf "$WORK/podman/root"
    mv "$WORK/podman/root.seed" "$WORK/podman/root"
    rm -rf "$WORK/podman/root/db.sql" "$WORK/podman/root/libpod"
    "${PODMAN[@]}" image exists "$DEPS_IMAGE" || die "seeded store has no $DEPS_IMAGE"
  else
    log "building $DEPS_IMAGE (FFmpeg + libvpx; ~15 minutes, cached afterwards)"
    "${PODMAN[@]}" build -q -t "$DEPS_IMAGE" -f "$UVPKG/ft-opencv/Containerfile" "$UVPKG/ft-opencv" >/dev/null
  fi
fi

# 4. Build, repair and tag inside it.
rm -rf "$STAGING" && mkdir -p "$STAGING"
"${PODMAN[@]}" run --rm --security-opt label=disable \
  -v "$HERE/$(basename "${BASH_SOURCE[0]}"):/build.sh:ro" -v "$SRC:/src" -v "$STAGING:/out" \
  "$DEPS_IMAGE" bash /build.sh --inside
shopt -s nullglob
WHEELS=("$STAGING"/*.whl)
[[ ${#WHEELS[@]} == 1 ]] || die "expected exactly one wheel in $STAGING, found ${#WHEELS[@]}"
WHEEL="$(basename "${WHEELS[0]}")"
[[ "$WHEEL" == opencv_python_headless-$OPENCV_PYTHON_VERSION-$BUILD_TAG-cp314-cp314t-$MANYLINUX_PLAT.whl ]] \
  || die "unexpected wheel name $WHEEL"
cp "${WHEELS[0]}" "$OUT/$WHEEL"
cp "$STAGING/build-tools.txt" "$OUT/opencv-wheel-build-tools.txt"
log "wheel: $OUT/$WHEEL"

# 5. Manifest.
WHEEL_PATH="$OUT/$WHEEL" PATCH="$PATCH" PATCH_SHA="$PATCH_SHA" UVPKG="$UVPKG" \
SRC="$SRC" OPENCV_PYTHON_COMMIT="$OPENCV_PYTHON_COMMIT" OPENCV_COMMIT="$OPENCV_COMMIT" \
OPENCV_PYTHON_VERSION="$OPENCV_PYTHON_VERSION" BUILD_TAG="$BUILD_TAG" NUMPY_BUILD="$NUMPY_BUILD" \
DEPS_IMAGE="$DEPS_IMAGE" MANIFEST="$OUT/opencv-wheel-manifest.json" \
PODMAN_JSON="$("${PODMAN[@]}" image inspect "$DEPS_IMAGE")" \
python3 - <<'PY'
import hashlib, json, os, re, subprocess
e = os.environ
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
cf = open(os.path.join(e['UVPKG'], 'ft-opencv', 'Containerfile')).read()
arg = lambda n: re.search(r'^ARG %s=(\S+)' % n, cf, re.M).group(1)
img = json.loads(e['PODMAN_JSON'])[0]
tools = dict(l.strip().split('==', 1) for l in open(os.path.join(os.path.dirname(e['WHEEL_PATH']),
             'opencv-wheel-build-tools.txt')) if '==' in l)
files = re.findall(r'^\+\+\+ b/(\S+)', open(e['PATCH']).read(), re.M)
manifest = {
  'name': 'opencv-python-headless',
  'version': e['OPENCV_PYTHON_VERSION'],
  'build_tag': e['BUILD_TAG'],
  'file': os.path.basename(e['WHEEL_PATH']),
  'sha256': sha(e['WHEEL_PATH']),
  'sources': {
    'opencv_python_repo': 'https://github.com/opencv/opencv-python.git',
    'opencv_python_tag': '92',
    'opencv_python_commit': e['OPENCV_PYTHON_COMMIT'],
    'opencv_commit': e['OPENCV_COMMIT'],
    'setup_py_change': 'removed "-DPYTHON3_LIMITED_API=ON" (as UV does)',
  },
  'patch': {
    'file': 'wheels/patches/' + os.path.basename(e['PATCH']),
    'sha256': e['PATCH_SHA'],
    'files': files,
  },
  'toolchain': {
    'ffmpeg': arg('FFMPEG_VERSION'), 'ffmpeg_sha256': arg('FFMPEG_SHA256'),
    'ffmpeg_license': 'plain LGPL (no --enable-gpl/--enable-version3/--enable-nonfree)',
    'libvpx': arg('VPX_TAG'), 'libvpx_commit': arg('VPX_COMMIT'),
    'containerfile': os.path.join(e['UVPKG'], 'ft-opencv', 'Containerfile'),
    'containerfile_sha256': sha(os.path.join(e['UVPKG'], 'ft-opencv', 'Containerfile')),
    'image_tag': e['DEPS_IMAGE'],
    'image_id': img.get('Id'),
    'image_digest': img.get('Digest'),
    'base_image': 'quay.io/pypa/manylinux_2_28_x86_64:latest (as resolved when the image was built)',
    'numpy_build': e['NUMPY_BUILD'],
    'cmake': tools.get('cmake'), 'ninja': tools.get('ninja'), 'scikit-build': tools.get('scikit-build'),
    'auditwheel': tools.get('auditwheel'), 'pip': tools.get('pip'), 'wheel': tools.get('wheel'),
  },
  'mirrors': os.path.join(e['UVPKG'], 'build_ft_opencv_wheel.sh') + ' (sha256 %s)' %
             sha(os.path.join(e['UVPKG'], 'build_ft_opencv_wheel.sh')),
}
json.dump(manifest, open(e['MANIFEST'], 'w'), indent=2)
open(e['MANIFEST'], 'a').write('\n')
print(open(e['MANIFEST']).read())
PY

# 6. Optional verification (the full acceptance run is done separately).
if [[ -n "$VERIFY_PY" ]]; then
  log "verifying against $VERIFY_PY"
  VENV="$WORK/verify-venv-opencv"
  rm -rf "$VENV"
  "$VERIFY_PY" -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q "numpy==$NUMPY_BUILD"
  "$VENV/bin/python" -m pip install -q --no-index --find-links "$OUT" --no-deps opencv-python-headless
  gil="$("$VENV/bin/python" -W error::RuntimeWarning -c 'import cv2, sys; print(sys._is_gil_enabled())')"
  [[ "$gil" == False ]] || die "GIL is $gil after import cv2"
  log "GIL stays off after import cv2"
  PYTHONDONTWRITEBYTECODE=1 "$VENV/bin/python" "$UVPKG/ft_opencv_smoke.py"
fi
