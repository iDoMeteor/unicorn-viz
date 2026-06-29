#!/usr/bin/env bash
#
# stage_payload.sh — assemble a curated, shippable application payload.
#
# Produces a directory containing ONLY the files that belong in a shipped
# artifact (the Python package, runtime assets, and the metadata pip needs to
# install the project) via an explicit allowlist. Everything else — .git, the
# venv(s), logs, recordings, screenshots, docs, drop-in dev trees, build
# scratch, editor junk — is excluded by construction because it is never copied.
#
# This is the second shared "foundation" helper (alongside fetch_runtime.sh):
# the Windows and macOS packaging flows, and the native .deb/.rpm builder, stage
# from here so no channel can accidentally ship the whole repo (the exact bug in
# the current Windows installer, which blanket-copies RepoRoot\*).
#
# Usage:
#   tools/packaging/stage_payload.sh --dest build/payload [--source-dir .]
#
# Prints the destination directory on stdout; diagnostics go to stderr.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SOURCE_DIR="${REPO_ROOT}"
DEST=""

log() { echo "[stage-payload] $*" >&2; }
die() { echo "[stage-payload] ERROR: $*" >&2; exit 1; }

usage() {
  cat >&2 <<'EOF'
Assemble a curated Unicorn Viz application payload.

Usage:
  stage_payload.sh --dest <dir> [--source-dir <path>]

Options:
  --dest <dir>          Output directory for the staged payload (required)
  --source-dir <path>   Source tree root (default: repository root)
  -h, --help            Show this help text
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) DEST="$2"; shift 2 ;;
    --source-dir) SOURCE_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

[[ -n "$DEST" ]] || { usage; die "--dest is required"; }
SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"

# Required payload members — fail loudly if any is missing so a broken tree never
# silently ships a partial bundle.
REQUIRED=(
  unicornviz
  assets
  config.full.example.toml
  requirements.txt
  pyproject.toml
  README.md
)
# Optional members — included when present.
OPTIONAL=(
  LICENSE
  LICENSE.txt
  LICENSE.md
)

for item in "${REQUIRED[@]}"; do
  [[ -e "${SOURCE_DIR}/${item}" ]] || die "Required payload member missing: ${item}"
done

INCLUDE=("${REQUIRED[@]}")
for item in "${OPTIONAL[@]}"; do
  [[ -e "${SOURCE_DIR}/${item}" ]] && INCLUDE+=("$item")
done

if [[ ! -e "${SOURCE_DIR}/LICENSE" && ! -e "${SOURCE_DIR}/LICENSE.txt" && ! -e "${SOURCE_DIR}/LICENSE.md" ]]; then
  log "WARNING: no LICENSE file found; pyproject declares MIT but no license text"
  log "         will ship. Add a LICENSE file before a public release."
fi

log "Staging payload from ${SOURCE_DIR}"
log "Members: ${INCLUDE[*]}"
rm -rf "$DEST"
mkdir -p "$DEST"

# Copy the allowlisted members, dropping bytecode caches and the licensed,
# non-redistributable sims asset packs (everything under assets/sims/ — gitignored
# locally and absent from a clean tarball, but excluded here too in case staging
# runs against a working tree that has them). The placement README is restored
# below so the directory's purpose is still documented, without any pack content.
tar -C "$SOURCE_DIR" \
  --exclude='__pycache__' \
  --exclude='*.py[cod]' \
  --exclude='.DS_Store' \
  --exclude='assets/sims/*' \
  -cf - "${INCLUDE[@]}" \
  | tar -C "$DEST" -xf -

if [[ -f "${SOURCE_DIR}/assets/sims/README.md" ]]; then
  mkdir -p "${DEST}/assets/sims"
  cp "${SOURCE_DIR}/assets/sims/README.md" "${DEST}/assets/sims/README.md"
fi

# Defence in depth: assert no licensed sims pack subdirectory survived.
if find "${DEST}/assets/sims" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | read -r _; then
  die "Licensed sims asset packs leaked into payload under assets/sims/"
fi

# Guard against regressions: assert nothing that must never ship leaked in.
for forbidden in .git .venv .venv-runtime logs recordings screenshots drop-ins docs tests build; do
  if [[ -e "${DEST}/${forbidden}" ]]; then
    die "Payload leak detected: ${forbidden} present in staged output"
  fi
done

log "Staged payload contents:"
( cd "$DEST" && find . -maxdepth 1 -mindepth 1 | sort | sed 's/^/  /' >&2 )
log "Payload ready at ${DEST}"
echo "$DEST"
