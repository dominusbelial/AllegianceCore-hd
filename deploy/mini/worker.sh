#!/usr/bin/env bash
# HD ESRGAN worker (Claude 2026-10-18). Upscales every $HD_ADDON_ROOT/inputs/<model>/native.png that has no
# variants/esrgan/<model>/basecolor.png yet. Pauses while the test runner is busy (any dotnet process on the host,
# seen via pid: host), so perf/live tests keep a quiet machine.
set -u
cd /hd
while true; do
  next=""
  for f in "$HD_ADDON_ROOT"/inputs/*/native.png; do
    [ -e "$f" ] || continue
    m=$(basename "$(dirname "$f")")
    [ -e "$HD_ADDON_ROOT/variants/esrgan/$m/basecolor.png" ] && continue
    next=$m; break
  done
  if [ -z "$next" ]; then sleep 60; continue; fi
  if [ "${PAUSE_FOR_RUNNER:-1}" = 1 ] && pgrep -x dotnet >/dev/null; then echo "$(date +%T) runner busy, waiting"; sleep 120; continue; fi
  t=$(date +%s)
  if nice -n "${NICE:-10}" python esrgan_variant.py "$next" > /tmp/last.log 2>&1; then
    echo "$(date +%T) $next ok $(( $(date +%s)-t ))s"
  else
    echo "$(date +%T) $next FAILED: $(tail -1 /tmp/last.log)"; mkdir -p "$HD_ADDON_ROOT/failed" && cp /tmp/last.log "$HD_ADDON_ROOT/failed/$next.log"
    mkdir -p "$HD_ADDON_ROOT/variants/esrgan/$next" && touch "$HD_ADDON_ROOT/variants/esrgan/$next/basecolor.png.failed"; sleep 5
  fi
done
