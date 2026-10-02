#!/usr/bin/env bash
#
# build_patched_ft_wheels.sh -- build free-threaded (cp314t) manylinux_2_28
# wheels of python-rtmidi, glcontext and moderngl that carry our open
# upstream free-threading fixes, at the exact versions the downstream project
# (unicorn-viz, "UV") pins, so they can be dropped into its wheelhouse.
#
# Two rounds are defined (--round N, default: the latest):
#
#   round 1                                               build tags 2 / 1 / 1
#     python-rtmidi 1.5.8   branch ft-1.5.8 (PR SpotlightKid/python-rtmidi#230 +
#                           RtMidi fixes, sub-module branch ft-1.5.8)
#     glcontext     3.0.0   branch free-threading (PR moderngl/glcontext#41)
#     moderngl      5.12.0  branch ft-5.12.0 (PRs moderngl#751, #752, #753
#                           backported onto the 5.12.0 tag)
#
#   round 2 (adds the fixes of the later PRs)             build tags 3 / 2 / 2
#     python-rtmidi 1.5.8   branch ft-1.5.8-2 (ft-1.5.8 + PR #231, close_port docstring)
#     glcontext     3.0.0   branch fix-error-paths (#41 + PR glcontext#42, on 3.0.0)
#     moderngl      5.12.0  branch ft-5.12.0-2 (ft-5.12.0 + PRs moderngl#754 and #756
#                           and the commits that reconcile them with #751-#753)
#
# This mirrors /home/jj/Repos/unicorn-viz/tools/packaging/build_ft_wheels.sh
# (read-only reference): the same manylinux_2_28 image, the same compiler and
# Cython (3.3.0), the same `pip wheel --no-build-isolation`, the same
# `auditwheel repair --plat manylinux_2_28_x86_64` and the same
# `python -m wheel tags --build N --remove`.  The one difference is the
# source: UV builds hash-checked PyPI sdists, this builds `git archive`s of
# the local backport branches.
#
# Versions stay exactly 1.5.8 / 3.0.0 / 5.12.0 (no local version segment).
# What makes pip prefer these over the published wheels of the same version
# is a PEP 427 build tag in the file name: pip ranks wheels of equal version by
# build tag, and a wheel with a tag beats one without; python_rtmidi 1.5.8
# already has a published "-1-" wheel, so round 1 was "-2-" and round 2 is "-3-".
# Published wheels are append-only, so every round bumps the build tag.
#
# Nothing is published, pushed or installed on the host: the wheels land in
# --out, and the wheelhouse is not touched.  Podman is rootless with a private
# storage dir, so neither the user's podman store nor UV's work dir is used.
#
# Usage:
#   wheels/build_patched_ft_wheels.sh [--round N] [--out DIR] [--work DIR]
#                                     [--image REF] [--previous MANIFEST]
#
# Writes next to the wheels (overwritten on every run):
#   patched-wheels-manifest[-N].json  name, version, build tag, file, sha256,
#                                  source git commit(s), image digest, Cython
#                                  (round 1 has no suffix; wheels that were
#                                  not built this round, like sphn, are
#                                  carried over from --previous)
#   patched-wheels-build-tools[-N].txt `pip list` of the build environment

set -Eeuo pipefail

# --- What to build -----------------------------------------------------------
# name | version | build tag | repo | branch (tag the version must match)
REPOS=/home/jj/Repos/python-free-threading
SPECS_1=(
  "python-rtmidi|1.5.8|2|$REPOS/python-rtmidi|ft-1.5.8"
  "glcontext|3.0.0|1|$REPOS/glcontext|free-threading"
  "moderngl|5.12.0|1|$REPOS/moderngl|ft-5.12.0"
)
SPECS_2=(
  "python-rtmidi|1.5.8|3|$REPOS/python-rtmidi|ft-1.5.8-2"
  "glcontext|3.0.0|2|$REPOS/glcontext|fix-error-paths"
  "moderngl|5.12.0|2|$REPOS/moderngl|ft-5.12.0-2"
)
LATEST_ROUND=2
# python-rtmidi's RtMidi sub-module (a gitlink in the python-rtmidi branch).
RTMIDI_SUBMODULE_PATH="src/rtmidi"

# Same as UV: >= 3.1 is what understands free-threading, and the pre-generated
# _rtmidi.cpp is dropped so Cython regenerates it from the .pyx.
CYTHON_VERSION="3.3.0"
IMAGE_DEFAULT="quay.io/pypa/manylinux_2_28_x86_64:latest"
MANYLINUX_PLAT="manylinux_2_28_x86_64"

SCRATCH=/tmp/claude-1000/-home-jj-Repos-python-free-threading/735b617c-5c8d-472c-b2de-ef336d588b24/scratchpad

log() { echo "[patched-ft-wheels] $*" >&2; }
die() { echo "[patched-ft-wheels] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Inside the container: build, repair, tag.  Reads /src/<dir> trees and
# /src/specs.tsv (name, version, build tag, dir), writes finished wheels to
# /out and the build-tool listing to /out/.build-tools.txt.
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--inside" ]]; then
  PY=/opt/python/cp314-cp314t/bin/python
  # Compile-time headers/libs the three extensions need (not in the image).
  yum install -y -q alsa-lib-devel mesa-libEGL-devel mesa-libGL-devel libX11-devel >/dev/null
  $PY -m venv /tmp/bv
  /tmp/bv/bin/python -m pip install -q --upgrade pip
  /tmp/bv/bin/python -m pip install -q setuptools wheel "cython==$CYTHON_VERSION" meson-python meson ninja
  export PATH=/tmp/bv/bin:$PATH      # meson-python shells out to meson / ninja
  /tmp/bv/bin/python -m pip list --format=freeze > /out/.build-tools.txt
  mkdir -p /tmp/build /tmp/raw /tmp/repaired

  while IFS=$'\t' read -r name ver tag dir; do
    log "$name $ver: build from /src/$dir"
    # Build in a copy: the source mount is read-only and setuptools builds in tree.
    cp -a "/src/$dir" "/tmp/build/$dir"
    if [[ "$name" == python-rtmidi ]]; then
      # Belt and braces: git archive has no generated file, but if one ever
      # appears it would predate Cython's free-threading support.
      rm -f "/tmp/build/$dir/src/_rtmidi.cpp"
    fi
    /tmp/bv/bin/python -m pip wheel -q --no-build-isolation --no-deps -w /tmp/raw "/tmp/build/$dir"
  done < /src/specs.tsv

  for w in /tmp/raw/*.whl; do
    log "repair $(basename "$w")"
    auditwheel repair --plat "$MANYLINUX_PLAT" -w /tmp/repaired "$w" >&2
  done

  # PEP 427 build tag, so pip prefers these over the same-version wheels
  # already published.  `wheel tags --build N --remove` renames the file and
  # rewrites WHEEL's Build: header; it keeps the version untouched.
  while IFS=$'\t' read -r name ver tag dir; do
    shopt -s nullglob
    files=(/tmp/repaired/"${name//-/_}-$ver"-cp314-cp314t-*.whl)
    shopt -u nullglob
    [[ ${#files[@]} -eq 1 ]] || { echo "expected one repaired $name wheel, found ${#files[@]}" >&2; exit 1; }
    /tmp/bv/bin/python -m wheel tags --build "$tag" --remove "${files[0]}" >&2
  done < /src/specs.tsv

  cp -f /tmp/repaired/*.whl /out/
  exit 0
fi

# ---------------------------------------------------------------------------
# Host side.
# ---------------------------------------------------------------------------
WORK="$SCRATCH/wheels-work"
OUT="$SCRATCH/wheels-out"
IMAGE="$IMAGE_DEFAULT"
ROUND="$LATEST_ROUND"
PREVIOUS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/patched-wheels-manifest.json"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --round) ROUND="$2"; shift 2 ;;
    --previous) PREVIOUS="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    --image) IMAGE="$2"; shift 2 ;;
    -h|--help) sed -n '2,52p' "$0" >&2; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

case "$ROUND" in
  1) SPECS=("${SPECS_1[@]}"); SUFFIX=""; MANIFEST=patched-wheels-manifest.json ;;
  2) SPECS=("${SPECS_2[@]}"); SUFFIX="-2"; MANIFEST=patched-wheels-manifest-2.json ;;
  *) die "Unknown round: $ROUND (1 or 2)" ;;
esac
command -v podman >/dev/null || die "podman is required (rootless is fine)"
command -v git >/dev/null || die "git is required"
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
SRC="$WORK/src"
STAGE="$WORK/stage"
rm -rf "$SRC" "$STAGE"
mkdir -p "$WORK/podman" "$SRC" "$STAGE" "$OUT"

# --- 1. Source archives of the backport branches -----------------------------
# The commit is resolved once and archived by hash, so the manifest records
# exactly what was built even if a branch moves while the script runs.
: > "$SRC/specs.tsv"
: > "$STAGE/commits.tsv"
for spec in "${SPECS[@]}"; do
  IFS='|' read -r name ver tag repo branch <<<"$spec"
  commit="$(git -C "$repo" rev-parse --verify --quiet "refs/heads/$branch^{commit}")" \
    || die "$name: branch $branch not found in $repo"
  dir="$name-$ver"
  log "$name $ver: archive $branch @ ${commit:0:12}"
  mkdir "$SRC/$dir"
  git -C "$repo" archive --format=tar "$commit" | tar -x -C "$SRC/$dir"
  extra=""
  if [[ "$name" == python-rtmidi ]]; then
    # git archive leaves a sub-module out, so archive the commit the gitlink
    # records from the sub-module clone and overlay it.  That commit is the
    # RtMidi backport (sub-module branch ft-1.5.8); it only exists locally.
    sub="$(git -C "$repo" ls-tree "$commit" "$RTMIDI_SUBMODULE_PATH" | awk '$2=="commit"{print $3}')"
    [[ -n "$sub" ]] || die "$name: $RTMIDI_SUBMODULE_PATH is not a gitlink in $branch"
    git -C "$repo/$RTMIDI_SUBMODULE_PATH" cat-file -e "$sub^{commit}" \
      || die "$name: sub-module commit $sub is missing from the local clone"
    rm -rf "${SRC:?}/$dir/$RTMIDI_SUBMODULE_PATH"
    mkdir -p "$SRC/$dir/$RTMIDI_SUBMODULE_PATH"
    git -C "$repo/$RTMIDI_SUBMODULE_PATH" archive --format=tar "$sub" \
      | tar -x -C "$SRC/$dir/$RTMIDI_SUBMODULE_PATH"
    [[ -f "$SRC/$dir/$RTMIDI_SUBMODULE_PATH/RtMidi.cpp" ]] || die "$name: sub-module overlay has no RtMidi.cpp"
    grep -q callUserCallback "$SRC/$dir/$RTMIDI_SUBMODULE_PATH/RtMidi.h" \
      || die "$name: the RtMidi overlay is not the patched one"
    extra="$sub"
  fi
  printf '%s\t%s\t%s\t%s\n' "$name" "$ver" "$tag" "$dir" >> "$SRC/specs.tsv"
  printf '%s\t%s\t%s\t%s\t%s\n' "$name" "$ver" "$tag" "$commit" "$extra" >> "$STAGE/commits.tsv"
done

# --- 2. Build in the container ----------------------------------------------
# A private store: neither the user's default podman store nor UV's work dir.
PODMAN=(env -u XDG_DATA_HOME -u XDG_CONFIG_HOME podman
        --root "$WORK/podman/root" --runroot "$WORK/podman/run")

log "image: $IMAGE"
"${PODMAN[@]}" pull -q "$IMAGE" >/dev/null
IMAGE_ID="$("${PODMAN[@]}" image inspect --format '{{.Id}} {{index .RepoDigests 0}}' "$IMAGE")"
"${PODMAN[@]}" run --rm --security-opt label=disable \
  -v "$SELF:/build.sh:ro" -v "$SRC:/src:ro" -v "$STAGE:/out" "$IMAGE" \
  bash /build.sh --inside

# --- 3. Collect: copy to --out (never deleting anything) and write the manifest
cp -f "$STAGE/.build-tools.txt" "$OUT/patched-wheels-build-tools$SUFFIX.txt"
python3 - "$STAGE" "$OUT" "$IMAGE" "$IMAGE_ID" "$CYTHON_VERSION" "$ROUND" "$MANIFEST" "$PREVIOUS" <<'PY'
import hashlib, json, re, shutil, sys
from pathlib import Path

stage, out = Path(sys.argv[1]), Path(sys.argv[2])
image, image_id, cython, round_, manifest_name, previous = sys.argv[3:]
entries = []
for line in (stage / "commits.tsv").read_text().splitlines():
    name, ver, tag, commit, sub = line.split("\t") + [""] * (5 - len(line.split("\t")))
    wheels = sorted(stage.glob(f"{name.replace('-', '_')}-{ver}-{tag}-cp314-cp314t-*.whl"))
    if len(wheels) != 1:
        sys.exit(f"{name}: expected exactly one wheel with build tag {tag}, found {wheels}")
    wheel = wheels[0]
    # Exact version, build tag in the file name, no local version.
    m = re.fullmatch(rf"{name.replace('-', '_')}-{re.escape(ver)}-{tag}-cp314-cp314t-[A-Za-z0-9_.]+\.whl", wheel.name)
    if not m or "+" in wheel.name:
        sys.exit(f"unexpected wheel name {wheel.name}")
    shutil.copy2(wheel, out / wheel.name)
    entry = {
        "name": name, "version": ver, "build_tag": tag, "file": wheel.name,
        "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "git_commit": commit,
    }
    if sub:
        entry["rtmidi_submodule_commit"] = sub
    entries.append(entry)
# Wheels of the previous manifest that this round did not rebuild (sphn).
built = {e["name"] for e in entries}
prev = Path(previous)
if prev.is_file():
    for e in json.loads(prev.read_text())["wheels"]:
        if e["name"] not in built:
            entries.append({**e, "carried_over_from": prev.name})
manifest = {"round": int(round_), "image": image, "image_id": image_id, "cython": cython, "wheels": entries}
(out / manifest_name).write_text(json.dumps(manifest, indent=2) + "\n")
for e in entries:
    if "carried_over_from" in e:
        continue
    print(f"[patched-ft-wheels] {e['file']}\n    sha256 {e['sha256']}\n    commit {e['git_commit']}"
          + (f"  (RtMidi {e['rtmidi_submodule_commit']})" if "rtmidi_submodule_commit" in e else ""),
          file=sys.stderr)
PY
log "wheels and manifest in $OUT"
