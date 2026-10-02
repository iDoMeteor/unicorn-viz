#!/usr/bin/env bash
#
# build_ft_wheels.sh -- build free-threaded (cp314t) manylinux wheels for the
# three C/C++ extensions that have no upstream 3.14t wheel: moderngl,
# glcontext and python-rtmidi.  (moderngl and glcontext have no 3.14 wheel
# at all.)  See docs/planning/free-threaded-python-2026-09-24.md and the W1
# item of docs/planning/bug-remediation-plan-2026-09-30.md.
#
# How: a throwaway rootless podman container of the official manylinux_2_28
# image (glibc 2.28, GCC 14, CPython 3.14.7 free-threaded in
# /opt/python/cp314-cp314t) builds each pinned sdist, then auditwheel
# repairs it to the manylinux_2_28 tag (python-rtmidi vendors libasound, as
# its upstream wheels do).  Nothing is installed on the host and no sudo is
# needed; the container's storage lives under the work directory, not the
# user's own podman store.
#
# The wheels carry the cp314t ABI tag, not a build-machine runtime, so they
# load into the bundled python-build-standalone 3.14 free-threaded
# interpreter.  --verify-python proves that: it installs the result into a
# scratch venv of the given interpreter and runs ft_wheels_smoke.py.
#
# Usage:
#   tools/packaging/build_ft_wheels.sh [--out DIR] [--work DIR]
#                                      [--verify-python PATH] [--image REF]
#
#   --out DIR            where finished wheels land (default: <work>/out)
#   --work DIR           scratch + podman storage (default: /var/tmp/uv-wheel-build)
#   --verify-python PATH a 3.14 free-threaded interpreter to smoke-test with
#   --image REF          override the manylinux image
#   --patched            build the PATCHED wheels (python-rtmidi, glcontext, moderngl) of release
#                        wheelhouse-cp314t-patched-2026-10-02 instead of the PyPI sdists: sources
#                        are fetched by pinned commit from the iDoMeteor forks listed in
#                        ft-patched/recipe.json, built on the recipe's manylinux image digest,
#                        and given its PEP 427 build tags.  sphn and OpenCV have their own
#                        scripts (--patched there too); see ft-patched/README.md
#
# Old artifacts are never deleted: --out is only ever added to.
#
# Windows wheels are NOT built here (they need MSVC); see the options note
# in docs/planning/.

set -Eeuo pipefail

# --- Pinned sources: "<version> <sdist sha256>" (PyPI sdists) ----------------
# Versions track requirements.txt (tests/test_ft_wheels_build.py enforces it).
PIN_moderngl="5.12.0 52936a98ccb2f2e1d6e3cb18528b2919f6831e7e3f924e788b5873badce5129b"
PIN_glcontext="3.0.0 57168edcd38df2fc0d70c318edf6f7e59091fba1cd3dadb289d0aa50449211ef"
PIN_python_rtmidi="1.5.8 7f9ade68b068ae09000ecb562ae9521da3a234361ad5449e83fc734544d004fa"

# Cython used to (re)generate python-rtmidi's C++; >= 3.1 is what understands
# the free-threaded build.  RTMIDI_BUILD_TAG: see the rename after repair below.
CYTHON_VERSION="3.3.0"
RTMIDI_BUILD_TAG="1"

IMAGE_DEFAULT="quay.io/pypa/manylinux_2_28_x86_64:latest"
MANYLINUX_PLAT="manylinux_2_28_x86_64"

log() { echo "[build-ft-wheels] $*" >&2; }
die() { echo "[build-ft-wheels] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Inside the container: build, check, repair.
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--inside" ]]; then
  PY=/opt/python/cp314-cp314t/bin/python
  # Compile-time headers/libs the three extensions need (not in the image).
  yum install -y -q alsa-lib-devel mesa-libEGL-devel mesa-libGL-devel libX11-devel >/dev/null
  $PY -m venv /tmp/bv
  /tmp/bv/bin/python -m pip install -q --upgrade pip
  /tmp/bv/bin/python -m pip install -q setuptools wheel "cython==$CYTHON_VERSION" meson-python meson ninja
  export PATH=/tmp/bv/bin:$PATH      # meson-python shells out to meson / ninja
  mkdir -p /tmp/src /tmp/raw /out
  if [[ -f /patched-src/specs.tsv ]]; then
    # PATCHED mode: the trees were fetched by commit on the host (fetch_patched_sources.py).
    # Build in a copy (the mount is read-only and setuptools builds in tree), regenerate
    # python-rtmidi's C++ with this Cython, repair, then give each wheel its build tag.
    mkdir -p /tmp/build /tmp/repaired
    /tmp/bv/bin/python -m pip list --format=freeze > /out/.patched-build-tools.txt
    while IFS=$'\t' read -r name ver tag dir; do
      log "$name $ver (patched, build tag $tag): build from /patched-src/$dir"
      cp -a "/patched-src/$dir" "/tmp/build/$dir"
      [[ "$name" == python-rtmidi ]] && rm -f "/tmp/build/$dir/src/_rtmidi.cpp"
      /tmp/bv/bin/python -m pip wheel -q --no-build-isolation --no-deps -w /tmp/raw "/tmp/build/$dir"
    done < /patched-src/specs.tsv
    for w in /tmp/raw/*.whl; do
      log "repair $(basename "$w")"
      auditwheel repair --plat "$MANYLINUX_PLAT" -w /tmp/repaired "$w" >&2
    done
    while IFS=$'\t' read -r name ver tag dir; do
      files=(/tmp/repaired/"${name//-/_}-$ver"-cp314-cp314t-*.whl)
      [[ ${#files[@]} -eq 1 && -f "${files[0]}" ]] || die "expected one repaired $name wheel, found ${#files[@]}"
      /tmp/bv/bin/python -m wheel tags --build "$tag" --remove "${files[0]}" >&2
    done < /patched-src/specs.tsv
    cp /tmp/repaired/*.whl /out/
    exit 0
  fi
  for spec in "moderngl:$PIN_moderngl" "glcontext:$PIN_glcontext" "python-rtmidi:$PIN_python_rtmidi"; do
    name="${spec%%:*}"; read -r ver sha <<<"${spec#*:}"
    log "$name $ver: fetch sdist"
    /tmp/bv/bin/python -m pip download -q --no-deps --no-binary :all: --no-build-isolation \
      -d /tmp/src "$name==$ver"
    sd="$(ls /tmp/src/*.tar.gz | grep -iE "/${name//-/[-_]}-$ver\.tar\.gz$")"
    echo "$sha  $sd" | sha256sum -c - >&2 || die "$name sdist hash mismatch"
    tar xzf "$sd" -C /tmp/src
    tree="/tmp/src/$(basename "$sd" .tar.gz)"
    if [[ "$name" == python-rtmidi ]]; then
      # The sdist ships _rtmidi.cpp pre-generated by Cython 3.0.5, which
      # predates free-threading support (3.1).  Drop it so meson regenerates
      # it with $CYTHON_VERSION from the .pyx.
      rm -f "$tree/src/_rtmidi.cpp"
    fi
    log "$name $ver: build"
    /tmp/bv/bin/python -m pip wheel -q --no-build-isolation --no-deps -w /tmp/raw "$tree"
  done
  for w in /tmp/raw/*.whl; do
    log "repair $(basename "$w")"
    auditwheel repair --plat "$MANYLINUX_PLAT" -w /out "$w" >&2
  done
  # Same name+version as the wheel first published from the 3.0.5-generated
  # source, and the wheelhouse is append-only: a PEP 427 build tag (-1-) makes
  # the regenerated one a distinct file that pip prefers.
  for w in /out/python_rtmidi-*-cp314-cp314t-*.whl; do
    [[ "$(basename "$w")" == python_rtmidi-*-1-cp314-* ]] && continue
    /tmp/bv/bin/python -m wheel tags --build "$RTMIDI_BUILD_TAG" --remove "$w" >&2
  done
  exit 0
fi

# ---------------------------------------------------------------------------
# Host side.
# ---------------------------------------------------------------------------
WORK=/var/tmp/uv-wheel-build
OUT=""
VERIFY_PY=""
IMAGE=""
PATCHED=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    --verify-python) VERIFY_PY="$2"; shift 2 ;;
    --image) IMAGE="$2"; shift 2 ;;
    --patched) PATCHED=1; shift ;;
    -h|--help) sed -n '2,42p' "$0" >&2; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done
OUT="${OUT:-$WORK/out}"
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECIPE="$SELF/ft-patched/recipe.json"
if [[ -z "$IMAGE" ]]; then
  if [[ "$PATCHED" == 1 ]]; then
    # The exact image the patched wheels were built on (see the recipe), not a moving tag.
    IMAGE="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['manylinux_image']['digest_round_2'])" "$RECIPE")"
  else
    IMAGE="$IMAGE_DEFAULT"
  fi
fi

command -v podman >/dev/null || die "podman is required (rootless is fine)"
mkdir -p "$WORK/podman" "$OUT"
# A private store: the user's default store can be unusable (a snap-versioned
# path mismatch under VS Code) and this build should not touch it anyway.
PODMAN=(env -u XDG_DATA_HOME -u XDG_CONFIG_HOME podman
        --root "$WORK/podman/root" --runroot "$WORK/podman/run")

log "image: $IMAGE"
"${PODMAN[@]}" pull -q "$IMAGE" >/dev/null
MOUNTS=()
if [[ "$PATCHED" == 1 ]]; then
  PSRC="$WORK/patched-src"
  rm -rf "$PSRC"
  python3 "$SELF/ft-patched/fetch_patched_sources.py" --recipe "$RECIPE" --dest "$PSRC" >&2
  MOUNTS=(-v "$PSRC:/patched-src:ro")
fi
BEFORE="$(ls "$OUT")"
"${PODMAN[@]}" run --rm --security-opt label=disable \
  -v "$SELF/build_ft_wheels.sh:/build.sh:ro" -v "$OUT:/out" ${MOUNTS[@]+"${MOUNTS[@]}"} "$IMAGE" \
  bash /build.sh --inside
if [[ "$PATCHED" == 1 ]]; then
  # What was built, for the record: the fetched commits, the image, the build tools.
  IMAGE_ID="$("${PODMAN[@]}" image inspect --format '{{.Id}}' "$IMAGE")"
  python3 - "$PSRC/sources.json" "$IMAGE" "$IMAGE_ID" "$OUT" <<'PY'
import hashlib, json, sys
from pathlib import Path
sources, image, image_id, out = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])
rows = json.loads(sources.read_text())
for row in rows.values():
    wheels = sorted(out.glob(f"{row['name'].replace('-', '_')}-{row['version']}-{row['build_tag']}-cp314-cp314t-*.whl"))
    assert len(wheels) == 1, (row['name'], wheels)
    row['file'], row['sha256'] = wheels[0].name, hashlib.sha256(wheels[0].read_bytes()).hexdigest()
(out / 'patched-build-manifest.json').write_text(json.dumps({'image': image, 'image_id': image_id, 'wheels': rows}, indent=2) + '\n')
PY
  mv -f "$OUT/.patched-build-tools.txt" "$OUT/patched-build-tools.txt"
fi
log "wheels in $OUT:"
ls -1 "$OUT" | grep -vxF -f <(echo "$BEFORE") >&2 || true

if [[ -n "$VERIFY_PY" ]]; then
  log "verifying against $VERIFY_PY"
  VENV="$WORK/verify-venv"
  rm -rf "$VENV"
  "$VERIFY_PY" -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q --no-index --find-links "$OUT" \
    moderngl glcontext python-rtmidi
  if [[ "$PATCHED" == 1 ]]; then
    # The patched modules declare free-threading support: this smoke test ENFORCES that the
    # GIL stays off after importing them (the unpatched one only reports it).
    "$VENV/bin/python" "$SELF/ft-patched/smoke/ft_wheels_smoke.py"
  else
    "$VENV/bin/python" "$SELF/ft_wheels_smoke.py"
  fi
fi
