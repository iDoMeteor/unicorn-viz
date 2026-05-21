#!/usr/bin/env bash
# Run the BPM evaluation harness against the seed corpus.
#
# Usage:
#   tools/run_bpm_eval.sh [--engine legacy|v2] [corpus_dir]
#
# Outputs:
#   tools/bpm_eval_report.md
#   tools/bpm_eval_results.json
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

ENGINE="${1:-legacy}"
CORPUS="${2:-${REPO_ROOT}/assets/audio/bpm_eval/seed}"

cd "${REPO_ROOT}"

if [[ -f ".venv/bin/python3" ]]; then
    PYTHON=".venv/bin/python3"
else
    PYTHON="python3"
fi

echo "=== BPM Eval Harness ==="
echo "Engine  : ${ENGINE}"
echo "Corpus  : ${CORPUS}"
echo ""

"${PYTHON}" tools/bpm_eval.py \
    --engine "${ENGINE}" \
    --report tools/bpm_eval_report.md \
    --json   tools/bpm_eval_results.json \
    "${CORPUS}"
