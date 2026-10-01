#!/bin/bash
# One A/B run: start the app, wait for the mixer engine, warm up, measure CPU of
# the main process and the audio helper, then stop it with SIGTERM to the main
# pid.  Aborts (exit 1) if anything is left running, so runs never overlap.
#   run_one.sh <label> <python>        env: AB (dir), WARM=30, MEASURE=60
# Not SIGINT: a background job started by a non-interactive shell ignores it.
label=$1; py=$2
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
AB=${AB:-/var/tmp/uv-ab}; WARM=${WARM:-30}; MEASURE=${MEASURE:-60}
log=$AB/$label.log; rm -f "$log"; mkdir -p "$AB"
cd "$REPO"
SDL_VIDEODRIVER=x11 "$py" -m unicornviz --config "$AB/config.toml" --windowed --width 1920 --height 1080 \
  --display-mode single --display-index 1 --no-record --mode sequential --start-effect "Plasma" \
  --effect-duration 9999 > "$log" 2>&1 &
main=$!
for _ in $(seq 1 90); do sleep 1; grep -q "audio engine running" "$log" && break; done
helper=$(pgrep -P "$main" -f unicornviz.remote_objects | head -1)
[ -n "$helper" ] || { echo "$label: no helper found" >> "$AB/cpu.txt"; kill -TERM "$main"; exit 1; }
sleep "$WARM"
cpu() { awk '{print $14+$15}' "/proc/$1/stat"; }
w0=$(date +%T); t0=$(date +%s.%N); m0=$(cpu "$main"); h0=$(cpu "$helper")
sleep "$MEASURE"
w1=$(date +%T); t1=$(date +%s.%N); m1=$(cpu "$main"); h1=$(cpu "$helper")
python3 -c "
hz=$(getconf CLK_TCK); w=$t1-$t0
print('$label main_cpu_pct=%.1f helper_cpu_pct=%.1f window_s=%.1f' % (100*($m1-$m0)/hz/w, 100*($h1-$h0)/hz/w, w))" >> "$AB/cpu.txt"
echo "$label $w0 $w1" >> "$AB/window.txt"
sess=$(ls -t "$REPO"/logs/unicornviz_*.log | head -1)
kill -TERM "$main"
for _ in $(seq 1 90); do sleep 1; kill -0 "$main" 2>/dev/null || break; done
if kill -0 "$main" 2>/dev/null || pgrep -f "unicornviz.remote_objects" >/dev/null; then
  echo "$label: LEFT RUNNING" >> "$AB/cpu.txt"; kill -KILL "$main" 2>/dev/null; exit 1
fi
cp "$sess" "$AB/$label.session.log"
