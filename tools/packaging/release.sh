#!/usr/bin/env bash
#
# release.sh — build, stage, and (optionally) publish a Unicorn Viz release.
#
# One command produces everything the distribution model in the installer plan
# (§0.1 / §18) needs, into a directory laid out exactly as it will be served:
#
#   <dest>/manifest.json                     merged; older releases stay listed
#   <dest>/<version>/unicorn-viz-<version>.tar.gz   curated source (one-liner)
#   <dest>/<version>/unicorn-viz-*.rpm / *.deb      native packages
#   <dest>/<version>/SHA256SUMS[.asc]
#
# Then, if --s3-url is given, syncs <dest> to S3-compatible storage (Cloudflare
# R2 via --endpoint-url, or plain S3).  Build host and distribution host are
# independent: run this locally and publish anywhere.
#
# Usage:
#   tools/packaging/release.sh --dest <dir> --base-url <url> [options]
#
# Options:
#   --dest <dir>          Staging directory laid out as served (required)
#   --base-url <url>      Public URL <dest> will be served at; written into the
#                         manifest's artifact URLs (required)
#   --version <X.Y.Z>     Release version (default: unicornviz.__version__)
#   --channel <stable|prerelease>
#                         Channel to point at this release (default: prerelease
#                         when the version has a pre-release suffix, else stable)
#   --formats <csv>       Artifacts to build: source,rpm,deb (default: all)
#   --sign <gpg-key-id>   Sign SHA256SUMS with this GPG key (SHA256SUMS.asc)
#   --s3-url <s3://…>     After staging, `aws s3 sync <dest>` to this URL
#   --endpoint-url <url>  S3 endpoint (e.g. https://<acct>.r2.cloudflarestorage.com)
#   --source-dir <path>   Source tree root (default: repository root)
#   --notes-url <url>     Release notes URL recorded in the manifest
#   --dry-run             Print the plan without building or publishing
#   --allow-dirty         Build even if payload members have uncommitted changes
#   -h, --help            Show this help text
#
# Native package versions: rpm/deb forbid '-' in a version, so a pre-release like
# 1.0.0-beta.110 is packaged as 1.0.0~beta.110 ('~' sorts before the final
# release in both dpkg and rpm).  The manifest and tarball keep the real version.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

VERSION=""
CHANNEL=""
DEST=""
BASE_URL=""
FORMATS="source,rpm,deb"
SIGN_KEY=""
S3_URL=""
ENDPOINT_URL=""
SOURCE_DIR="${REPO_ROOT}"
NOTES_URL=""
DRY_RUN=0
ALLOW_DIRTY=0

log() { echo "[release] $*" >&2; }
die() { echo "[release] ERROR: $*" >&2; exit 1; }
usage() { sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) DEST="$2"; shift 2 ;;
    --base-url) BASE_URL="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --channel) CHANNEL="$2"; shift 2 ;;
    --formats) FORMATS="$2"; shift 2 ;;
    --sign) SIGN_KEY="$2"; shift 2 ;;
    --s3-url) S3_URL="$2"; shift 2 ;;
    --endpoint-url) ENDPOINT_URL="$2"; shift 2 ;;
    --source-dir) SOURCE_DIR="$2"; shift 2 ;;
    --notes-url) NOTES_URL="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --allow-dirty) ALLOW_DIRTY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

[[ -n "$DEST" ]] || { usage; die "--dest is required"; }
[[ -n "$BASE_URL" ]] || { usage; die "--base-url is required (public URL --dest will be served at)"; }
SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
BASE_URL="${BASE_URL%/}"

if [[ -z "$VERSION" ]]; then
  VERSION="$(sed -n "s/^__version__ = ['\"]\([^'\"]*\)['\"].*/\1/p" "${SOURCE_DIR}/unicornviz/__init__.py" | head -n1)"
fi
[[ -n "$VERSION" ]] || die "Could not determine the version (pass --version)"
VERSION="${VERSION#v}"

if [[ -z "$CHANNEL" ]]; then
  if [[ "$VERSION" == *-* ]]; then CHANNEL="prerelease"; else CHANNEL="stable"; fi
fi
[[ "$CHANNEL" == "stable" || "$CHANNEL" == "prerelease" ]] || die "--channel must be stable or prerelease"

COMMIT="$(git -C "$SOURCE_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
TAG="v${VERSION}"

# A release must correspond to a commit: refuse a tree whose payload members
# carry uncommitted edits (another seat's in-flight work, a mid-run version
# bump) unless the caller opts in. Unrelated dirty files (config.toml, logs)
# do not block.
if git -C "$SOURCE_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  dirty="$(git -C "$SOURCE_DIR" status --porcelain --untracked-files=no -- \
    unicornviz assets requirements.txt pyproject.toml README.md LICENSE \
    THIRD_PARTY_LICENSES.md config.full.example.toml 2>/dev/null || true)"
  if [[ -n "$dirty" ]]; then
    if [[ "$ALLOW_DIRTY" -eq 1 ]]; then
      log "WARNING: building from a dirty tree (--allow-dirty):"
      while IFS= read -r line; do log "  $line"; done <<<"$dirty"
    else
      while IFS= read -r line; do log "  $line"; done <<<"$dirty"
      die "payload members have uncommitted changes; commit them (a release is a commit) or pass --allow-dirty"
    fi
  fi
fi
PKG_VERSION="${VERSION//-/\~}"
OUT="${DEST}/${VERSION}"

PY="${REPO_ROOT}/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3 || true)"
[[ -n "$PY" ]] || die "python3 is required on the build host to write manifest.json"

IFS=',' read -ra FMTS <<<"$FORMATS"
for f in "${FMTS[@]}"; do
  case "$f" in
    source|rpm|deb) ;;
    *) die "Unknown format in --formats: ${f}" ;;
  esac
done

log "Release ${VERSION} (${TAG} @ ${COMMIT}) → channel ${CHANNEL}"
log "Formats: ${FORMATS}; staging to ${OUT}; served at ${BASE_URL}"
[[ -n "$SIGN_KEY" ]] && log "Signing SHA256SUMS with GPG key ${SIGN_KEY}"
[[ -n "$S3_URL" ]] && log "Will publish to ${S3_URL}${ENDPOINT_URL:+ (endpoint ${ENDPOINT_URL})}"

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "dry-run: nothing built, nothing published."
  exit 0
fi

for f in "${FMTS[@]}"; do
  if [[ "$f" != "source" ]]; then command -v fpm >/dev/null 2>&1 || die "fpm is required for --formats ${f}"; fi
done
[[ -z "$SIGN_KEY" ]] || command -v gpg >/dev/null 2>&1 || die "gpg is required for --sign"
[[ -z "$S3_URL" ]] || command -v aws >/dev/null 2>&1 || die "aws CLI is required for --s3-url"

WORK="$(mktemp -d -p "${TMPDIR:-/var/tmp}")"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUT"

ARTIFACT_ARGS=()

for f in "${FMTS[@]}"; do
  case "$f" in
    source)
      name="unicorn-viz-${VERSION}.tar.gz"
      log "Building ${name} from the curated payload"
      "${SCRIPT_DIR}/stage_payload.sh" --source-dir "$SOURCE_DIR" --dest "${WORK}/unicorn-viz-${VERSION}" >/dev/null
      tar -C "$WORK" -czf "${OUT}/${name}" "unicorn-viz-${VERSION}"
      ARTIFACT_ARGS+=(--artifact "source=${OUT}/${name}")
      ;;
    rpm|deb)
      log "Building ${f} (package version ${PKG_VERSION})"
      "${SCRIPT_DIR}/build_native.sh" --format "$f" --version "$PKG_VERSION" \
        --source-dir "$SOURCE_DIR" --output-dir "$OUT" >&2
      file="$(find "$OUT" -maxdepth 1 -type f -name "*.${f}" -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"
      [[ -f "$file" ]] || die "build_native.sh produced no .${f}"
      arch="$(uname -m)"
      if [[ "$f" == "deb" ]]; then
        case "$arch" in x86_64) arch="amd64" ;; aarch64) arch="arm64" ;; esac
      fi
      ARTIFACT_ARGS+=(--artifact "${f}-${arch}=${file}")
      ;;
  esac
done

# SHA256SUMS covers every artifact present in the version dir, not just this
# run's, so incremental runs (source now, rpm/deb later) stay consistent with
# the merged manifest.
log "Writing SHA256SUMS"
( cd "$OUT" && find . -maxdepth 1 -type f \( -name '*.tar.gz' -o -name '*.rpm' -o -name '*.deb' -o -name '*.zip' \) -printf '%f\n' | sort | xargs sha256sum > SHA256SUMS )
SUMS_ASC_ARGS=()
if [[ -n "$SIGN_KEY" ]]; then
  log "Signing SHA256SUMS"
  gpg --batch --yes --armor --detach-sign --local-user "$SIGN_KEY" \
    --output "${OUT}/SHA256SUMS.asc" "${OUT}/SHA256SUMS"
  SUMS_ASC_ARGS=(--sumsfile-asc "${OUT}/SHA256SUMS.asc")
fi

log "Updating ${DEST}/manifest.json"
NOTES_ARGS=()
[[ -n "$NOTES_URL" ]] && NOTES_ARGS=(--notes-url "$NOTES_URL")
"$PY" "${SCRIPT_DIR}/manifest.py" update \
  --manifest "${DEST}/manifest.json" \
  --version "$VERSION" --channel "$CHANNEL" --tag "$TAG" --commit "$COMMIT" \
  --base-url "$BASE_URL" \
  "${ARTIFACT_ARGS[@]}" \
  --sumsfile "${OUT}/SHA256SUMS" "${SUMS_ASC_ARGS[@]}" "${NOTES_ARGS[@]}" >/dev/null

if [[ -n "$S3_URL" ]]; then
  log "Publishing ${DEST} → ${S3_URL}"
  ENDPOINT_ARGS=()
  [[ -n "$ENDPOINT_URL" ]] && ENDPOINT_ARGS=(--endpoint-url "$ENDPOINT_URL")
  aws s3 sync "$DEST" "$S3_URL" "${ENDPOINT_ARGS[@]}" >&2
fi

log "Done."
"$PY" "${SCRIPT_DIR}/manifest.py" show --manifest "${DEST}/manifest.json" >&2
echo "$DEST"
