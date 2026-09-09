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
#                                    [--dropins <pack-file>]
#
# --dropins <pack-file>: also stage the listed drop-ins (one per line; '#'
# comments) under <dest>/drop-ins/<name>/ — their TRACKED files only (each is
# its own git repo), minus tests — and write <dest>/requirements-dropins.txt,
# the union of their requirements.txt files. A line may carry modifiers after
# the name: `+pkg` adds a dependency the drop-in uses but does not declare,
# `-pkg` drops one that must not ship (e.g. `dj-mixer-01 +hidapi -demucs`), and
# `+dir:<folder>` ships a gitignored folder from the drop-in's working tree
# (bundled media: `images-01 +dir:images`, `video-clips-01 +dir:videos`).
# The app discovers drop-ins at APP_ROOT/drop-ins, so a payload that carries
# them works on every channel with no core change.
#
# Prints the destination directory on stdout; diagnostics go to stderr.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SOURCE_DIR="${REPO_ROOT}"
DEST=""
DROPINS_FILE=""

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
    --dropins) DROPINS_FILE="$2"; shift 2 ;;
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
  images
  LICENSE
  LICENSE.txt
  LICENSE.md
  THIRD_PARTY_LICENSES.md
  config.dist.toml
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

# Copy the allowlisted members.
#
# Preferred path — the source is a git checkout: stage TRACKED files only
# (git ls-files). Anything gitignored — the licensed assets/sims/ packs, the
# multi-gigabyte assets/training/ session data (recordings, corpora, keystroke
# logs), caches — can then never ship, by construction rather than by an
# ever-growing exclude list. Tracked-but-modified files ship with their local
# edits (this is a local release flow); untracked new files do not, so a warning
# is printed when any exist under the included members.
#
# Fallback path — no git (e.g. a tag tarball extracted in CI): tar the members
# with explicit excludes for the same ignored trees.
if git -C "$SOURCE_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  log "Source is a git checkout: staging tracked files only"
  untracked="$(git -C "$SOURCE_DIR" ls-files --others --exclude-standard -- "${INCLUDE[@]}" | wc -l)"
  if [[ "$untracked" -gt 0 ]]; then
    log "WARNING: ${untracked} untracked file(s) under the payload members will NOT ship (git add them first)"
  fi
  ( cd "$SOURCE_DIR" && git ls-files -z -- "${INCLUDE[@]}" ) \
    | tar -C "$SOURCE_DIR" \
        --exclude='__pycache__' \
        --exclude='*.py[cod]' \
        --exclude='.DS_Store' \
        --null -T - -cf - \
    | tar -C "$DEST" -xf -
else
  log "Source is not a git checkout: staging members with explicit excludes"
  tar -C "$SOURCE_DIR" \
    --exclude='__pycache__' \
    --exclude='*.py[cod]' \
    --exclude='.DS_Store' \
    --exclude='assets/sims/*' \
    --exclude='assets/training/*' \
    -cf - "${INCLUDE[@]}" \
    | tar -C "$DEST" -xf -
fi

# Every required member must have made it across (a required file that exists
# on disk but is untracked would otherwise be silently dropped by the git path).
for item in "${REQUIRED[@]}"; do
  [[ -e "${DEST}/${item}" ]] || die "Required payload member did not stage: ${item} (untracked?)"
done

if [[ -f "${SOURCE_DIR}/assets/sims/README.md" ]]; then
  mkdir -p "${DEST}/assets/sims"
  cp "${SOURCE_DIR}/assets/sims/README.md" "${DEST}/assets/sims/README.md"
fi

# Defence in depth: assert no licensed sims pack subdirectory survived.
if find "${DEST}/assets/sims" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | read -r _; then
  die "Licensed sims asset packs leaked into payload under assets/sims/"
fi
# ...and that no training session data survived (recordings, corpora, keystroke
# logs live under assets/training/ and are gitignored; only its .gitignore ships).
if find "${DEST}/assets/training" -mindepth 1 ! -name .gitignore 2>/dev/null | read -r _; then
  die "Training session data leaked into payload under assets/training/"
fi

# Guard against regressions: assert nothing that must never ship leaked in.
# (drop-ins/ is allowed only when --dropins asked for it.)
if [[ -z "$DROPINS_FILE" && -e "${DEST}/drop-ins" ]]; then
  die "Payload leak detected: drop-ins present in staged output without --dropins"
fi
for forbidden in .git .venv .venv-runtime logs recordings screenshots docs tests build; do
  if [[ -e "${DEST}/${forbidden}" ]]; then
    die "Payload leak detected: ${forbidden} present in staged output"
  fi
done

# Optional drop-in pack.
if [[ -n "$DROPINS_FILE" ]]; then
  [[ -f "$DROPINS_FILE" ]] || die "--dropins: no such file: ${DROPINS_FILE}"
  : > "${DEST}/requirements-dropins.txt"
  staged=0
  while IFS= read -r line; do
    line="${line%%#*}"; line="${line#"${line%%[![:space:]]*}"}"; line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue
    read -r name mods <<<"$line"
    src="${SOURCE_DIR}/drop-ins/${name}"
    [[ -d "$src" ]] || die "--dropins: drop-in not found: ${name}"
    if ! git -C "$src" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      die "--dropins: ${name} is not a git checkout (submodule not initialized?)"
    fi
    if [[ -z "$(git -C "$src" ls-files | head -n1)" ]]; then
      die "--dropins: ${name} has no tracked files (submodule not initialized?)"
    fi
    mkdir -p "${DEST}/drop-ins/${name}"
    ( cd "$src" && git ls-files -z ) \
      | tar -C "$src" --exclude='__pycache__' --exclude='*.py[cod]' --exclude='tests' --exclude='tests/*' \
            --null -T - -cf - \
      | tar -C "${DEST}/drop-ins/${name}" -xf -
    if [[ -f "${src}/requirements.txt" ]]; then
      grep -vE '^\s*(#|$)' "${src}/requirements.txt" | sed 's/#.*//; s/[[:space:]]//g' >> "${DEST}/requirements-dropins.txt"
    fi
    for mod in $mods; do
      case "$mod" in
        +dir:*) sub="${mod#+dir:}"
            [[ -d "${src}/${sub}" ]] || die "--dropins: ${name} +dir:${sub}: no such folder in the working tree"
            mkdir -p "${DEST}/drop-ins/${name}/${sub}"
            cp -a "${src}/${sub}/." "${DEST}/drop-ins/${name}/${sub}/"
            log "  ${name}: bundled ${sub}/ ($(du -sh "${src}/${sub}" | cut -f1), $(find "${src}/${sub}" -type f | wc -l) files)" ;;
        +*) echo "${mod#+}" >> "${DEST}/requirements-dropins.txt" ;;
        -*) pkg="${mod#-}"; grep -viE "^${pkg}([<>=!~ ]|$)" "${DEST}/requirements-dropins.txt" > "${DEST}/requirements-dropins.tmp" || true
            mv "${DEST}/requirements-dropins.tmp" "${DEST}/requirements-dropins.txt"
            # ...and from the shipped copy of the drop-in's own requirements, so
            # `unicorn-viz --self-test` does not flag a deliberate exclusion.
            shipped="${DEST}/drop-ins/${name}/requirements.txt"
            if [[ -f "$shipped" ]]; then
              grep -viE "^\s*${pkg}([<>=!~ ]|$)" "$shipped" > "${shipped}.tmp" || true; mv "${shipped}.tmp" "$shipped"
            fi ;;
        *) die "--dropins: bad modifier '${mod}' on ${name} (use +pkg / -pkg)" ;;
      esac
    done
    staged=$((staged + 1))
  done < "$DROPINS_FILE"
  sort -u -o "${DEST}/requirements-dropins.txt" "${DEST}/requirements-dropins.txt"
  log "Drop-in pack: ${staged} drop-in(s); extra requirements: $(tr '\n' ' ' < "${DEST}/requirements-dropins.txt")"
fi

log "Staged payload contents:"
( cd "$DEST" && find . -maxdepth 1 -mindepth 1 | sort | sed 's/^/  /' >&2 )
log "Payload ready at ${DEST}"
echo "$DEST"
