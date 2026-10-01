#!/bin/bash
# GIL, free-threaded, repeated ROUNDS times (default 2; cancels drift), then summarize.
# LOADED=1 seeds the mixer from the owner's state (two decks, autoplay, stems, silent).
#   GIL_PY=... FT_PY=... tools/profiling/ft_ab/drive.sh
# Run it only on an idle machine (check `uptime`: load under 2), from a seat
# checkout, never the owner's main one.  It opens a 1920x1080 window and the
# mixer window; about 2 minutes per run.
D=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$D/../../.." && pwd)
AB=${AB:-/var/tmp/uv-ab}; export AB
GIL_PY=${GIL_PY:-$REPO/.venv/bin/python}
: "${FT_PY:?set FT_PY to the free-threaded venv python}"
python3 "$D/make_config.py" "$AB" ${LOADED:+--loaded} || exit 1
rm -f "$AB/cpu.txt" "$AB/window.txt" "$AB/load.txt"
ROUNDS=${ROUNDS:-2}
for r in $(seq 1 "$ROUNDS"); do
  for pair in "gil$r $GIL_PY" "ft$r $FT_PY"; do
    set -- $pair
    echo "$1 load_at_start=$(cut -d' ' -f1 /proc/loadavg)" >> "$AB/load.txt"
    "$D/run_one.sh" "$1" "$2" || { echo "aborted at $1: see $AB/cpu.txt"; exit 1; }
    sleep 8
  done
done
python3 "$D/summarize.py" "$AB"
