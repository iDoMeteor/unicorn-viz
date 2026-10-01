#!/usr/bin/env bash
#
# audit_sphn_licenses.sh -- produce the THIRD-PARTY notice for the sphn wheel's
# statically linked Rust crates, from the exact Cargo.lock in the pinned sdist.
#
# The wheel is redistributed, and it compiles ~130 crates (plus libopus, built
# from C source bundled in audiopus_sys) into one extension module, so their
# license notices have to travel with it.  This runs `cargo tree` for both wheel
# targets (Linux and Windows) in the cached Rust toolchain image (download and
# resolve only; nothing is compiled), then sphn_third_party_notice.py turns the
# result and the crates' own license files into one Markdown notice.
#
# Usage:
#   tools/packaging/audit_sphn_licenses.sh [--work DIR] [--out FILE]
#
#   --work DIR  scratch and podman storage (default: /var/tmp/uv-wheel-build)
#   --out FILE  where the notice is written
#               (default: <work>/sphn-THIRD-PARTY-NOTICES.md)
#
# Needs the toolchain image from build_ft_sphn_wheel.sh (built on demand).

set -Eeuo pipefail

log() { echo "[audit-sphn-licenses] $*" >&2; }
die() { echo "[audit-sphn-licenses] ERROR: $*" >&2; exit 1; }

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# One source of truth for the pins: the build script.
SPHN_VERSION="$(grep -m1 '^SPHN_VERSION=' "$SELF/build_ft_sphn_wheel.sh" | cut -d'"' -f2)"
SPHN_SDIST_SHA256="$(grep -m1 '^SPHN_SDIST_SHA256=' "$SELF/build_ft_sphn_wheel.sh" | cut -d'"' -f2)"
TOOLCHAIN_IMAGE="$(grep -m1 '^TOOLCHAIN_IMAGE=' "$SELF/build_ft_sphn_wheel.sh" | cut -d'"' -f2)"
[[ -n "$SPHN_VERSION" && -n "$SPHN_SDIST_SHA256" && -n "$TOOLCHAIN_IMAGE" ]] || die "could not read pins from build_ft_sphn_wheel.sh"

WORK=/var/tmp/uv-wheel-build
OUT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --work) WORK="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    -h|--help) sed -n '2,24p' "$0" >&2; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done
OUT="${OUT:-$WORK/sphn-THIRD-PARTY-NOTICES.md}"

command -v podman >/dev/null || die "podman is required (rootless is fine)"
mkdir -p "$WORK/podman" "$WORK/sphn-src" "$WORK/cargo-registry" "$WORK/license-audit"
PODMAN=(env -u XDG_DATA_HOME -u XDG_CONFIG_HOME podman
        --root "$WORK/podman/root" --runroot "$WORK/podman/run")

# 1. The pinned sdist, hash-checked, in its own tree (the build's tree is left alone).
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
TREE="$WORK/license-audit/sphn-$SPHN_VERSION"
rm -rf "$TREE"
tar xzf "$SDIST" -C "$WORK/license-audit"
LOCK_SHA="$(sha256sum "$TREE/Cargo.lock" | cut -d' ' -f1)"

# 2. cargo tree for both targets, in the toolchain image.
if ! "${PODMAN[@]}" image exists "$TOOLCHAIN_IMAGE"; then
  log "building $TOOLCHAIN_IMAGE"
  "${PODMAN[@]}" build -q -t "$TOOLCHAIN_IMAGE" -f "$SELF/ft-sphn/Containerfile" "$SELF/ft-sphn" >/dev/null
fi
log "resolving crates from Cargo.lock ($LOCK_SHA)"
"${PODMAN[@]}" run --rm --security-opt label=disable \
  -v "$TREE:/src:ro" -v "$WORK/cargo-registry:/root/.cargo/registry" \
  -v "$WORK/license-audit:/out" "$TOOLCHAIN_IMAGE" bash -c '
    set -e; cd /src; export CARGO_TARGET_DIR=/tmp/target
    cargo fetch --locked >&2
    for t in x86_64-unknown-linux-gnu:linux x86_64-pc-windows-msvc:windows; do
      cargo tree --locked -e normal --prefix none --target "${t%%:*}" \
        --format "{p}|{l}|{r}" 2>/dev/null | sort -u > "/out/tree-${t##*:}.txt"
    done'

# 3. The C library compiled in through audiopus_sys: not a crate, so Cargo does not list it.
OPUS_DIR="$(ls -d "$WORK"/cargo-registry/src/*/audiopus_sys-* | head -1)"
[[ -f "$OPUS_DIR/opus/COPYING" ]] || die "no libopus COPYING in $OPUS_DIR"
{
  echo '## Statically linked C library: libopus'
  echo
  echo "The \`audiopus_sys\` crate (listed below, ISC) builds libopus from the C source bundled in its"
  echo "\`opus/\` directory and links it statically into the wheel. libopus is distributed under the"
  echo "BSD 3-clause license of Xiph.Org and contributors; its own \`COPYING\` from that directory:"
  echo
  echo '```text'
  sed 's/[[:space:]]*$//' "$OPUS_DIR/opus/COPYING"
  echo '```'
} > "$WORK/license-audit/extra-libopus.md"

# 4. Canonical SPDX texts, for crates that declare a license but ship no file (the
#    symphonia crates are MPL-2.0 and ship none).  The generator fails if any crate
#    would be left without a text, so the notice never claims one it does not carry.
SPDX="$WORK/license-audit/spdx"
mkdir -p "$SPDX"
for id in MPL-2.0 MIT; do
  [[ -s "$SPDX/$id.txt" ]] || curl -fsSL -o "$SPDX/$id.txt" "https://spdx.org/licenses/$id.txt"
done

# 5. The notice.
python3 "$SELF/sphn_third_party_notice.py" --spdx-texts "$SPDX" \
  --tree "linux=$WORK/license-audit/tree-linux.txt" --tree "windows=$WORK/license-audit/tree-windows.txt" \
  --registry "$WORK/cargo-registry" --lock-sha256 "$LOCK_SHA" --sdist "sphn-$SPHN_VERSION" \
  --extra "$WORK/license-audit/extra-libopus.md" --out "$OUT"
log "wrote $OUT"
