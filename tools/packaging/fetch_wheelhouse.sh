#!/usr/bin/env bash
#
# fetch_wheelhouse.sh — download our prebuilt cp314t wheels and verify them.
#
# PyPI has no free-threaded (cp314t) wheels of moderngl, glcontext,
# python-rtmidi, OpenCV or sphn, so we build them ourselves and publish them as
# GitHub release assets (append-only). This script is how CI gets them back:
# every wheel listed in the committed trust file (wheelhouse-cp314t.sha256) is
# downloaded from its release and must match the committed sha256. The release's
# own SHA256SUMS is not consulted and nothing outside the trust file is fetched,
# so a swapped or injected asset fails the build instead of shipping.
#
# On success <dest> holds the wheels plus a SHA256SUMS (taken from the trust
# file) in the layout stage_payload.sh --wheelhouse expects:
#
#     tools/packaging/fetch_wheelhouse.sh --dest "$RUNNER_TEMP/wheelhouse"
#     UV_WHEELHOUSE="$RUNNER_TEMP/wheelhouse" tools/packaging/build_native.sh ...
#
# Options:
#   --dest <dir>      Where to put the wheels (required)
#   --trust <file>    Trust file (default: wheelhouse-cp314t.sha256 beside this script)
#   --platform <p>    linux | windows | all (default all): only wheels for that platform are
#                     downloaded (a Linux tarball does not need the Windows OpenCV wheel)
#   --all             Fetch every listed wheel (default: only the newest build of each,
#                     see wheel_select.py; older builds stay listed as the record)
#   --repo <o/n>      GitHub repository (default: $GITHUB_REPOSITORY, else iDoMeteor/unicorn-viz)
#   --base-url <url>  Override the download base (tests): <url>/<tag>/<file>
#   -h, --help

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST=""
TRUST="${SCRIPT_DIR}/wheelhouse-cp314t.sha256"
REPO="${GITHUB_REPOSITORY:-iDoMeteor/unicorn-viz}"
BASE_URL=""
PLATFORM="all"
FETCH_ALL=0

log() { echo "[fetch-wheelhouse] $*" >&2; }
die() { echo "[fetch-wheelhouse] ERROR: $*" >&2; exit 1; }
usage() { sed -n '2,/^set -E/p' "${BASH_SOURCE[0]}" | sed '$d; s/^# \{0,1\}//' ; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) DEST="$2"; shift 2 ;;
    --trust) TRUST="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    --all) FETCH_ALL=1; shift ;;
    --base-url) BASE_URL="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

[[ -n "$DEST" ]] || die "--dest is required"
[[ -f "$TRUST" ]] || die "trust file not found: ${TRUST}"
BASE_URL="${BASE_URL:-https://github.com/${REPO}/releases/download}"

mkdir -p "$DEST"
: > "${DEST}/SHA256SUMS"

# Which wheels to fetch: by default the newest build of each (the trust file is an
# append-only record, so it also lists superseded builds nobody needs to ship).
declare -A WANTED=()
# (tr: a Windows checkout may have turned the trust file into CRLF lines.)
mapfile -t listed < <(tr -d '\r' < "$TRUST" | awk '!/^[[:space:]]*(#|$)/ {print $2}')
if [[ "$FETCH_ALL" -eq 1 ]] || ! command -v python3 >/dev/null 2>&1; then
  for n in "${listed[@]}"; do WANTED["$n"]=1; done
else
  while IFS= read -r n; do WANTED["$n"]=1; done < <(printf '%s\n' "${listed[@]}" | python3 "${SCRIPT_DIR}/wheel_select.py")
fi

tag=""
count=0
while IFS= read -r line; do
  line="${line%$'\r'}"
  if [[ "$line" =~ ^#[[:space:]]*release-tag:[[:space:]]*([^[:space:]]+) ]]; then
    tag="${BASH_REMATCH[1]}"
    continue
  fi
  [[ -z "${line//[[:space:]]/}" || "$line" == \#* ]] && continue
  read -r want name <<<"$line"
  [[ "$want" =~ ^[0-9a-f]{64}$ ]] || die "bad checksum line in ${TRUST}: ${line}"
  [[ "$name" == *.whl && "$name" != */* ]] || die "bad wheel name in ${TRUST}: ${name}"
  [[ -n "$tag" ]] || die "no '# release-tag:' line before ${name} in ${TRUST}"
  [[ -n "${WANTED[$name]:-}" ]] || continue
  case "${PLATFORM}:${name}" in
    all:*|linux:*manylinux*|windows:*win_amd64*) ;;
    linux:*|windows:*) continue ;;
    *) die "--platform must be linux, windows or all (got '${PLATFORM}')" ;;
  esac

  out="${DEST}/${name}"
  log "fetching ${name} (${tag})"
  curl -fsSL --retry 3 --retry-delay 2 -o "$out" "${BASE_URL}/${tag}/${name}" \
    || die "download failed: ${BASE_URL}/${tag}/${name}"
  have="$(sha256sum "$out" | awk '{print $1}')"
  if [[ "$have" != "$want" ]]; then
    rm -f "$out"
    die "checksum mismatch for ${name}: expected ${want}, got ${have}"
  fi
  echo "${want}  ${name}" >> "${DEST}/SHA256SUMS"
  count=$((count + 1))
done < "$TRUST"

[[ "$count" -gt 0 ]] || die "trust file lists no wheels: ${TRUST}"
log "wheelhouse ready: ${count} verified wheel(s) in ${DEST}"
echo "$DEST"
