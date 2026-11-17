#!/usr/bin/env bash
# One-node test regions of the 24/7 CFE catalyst with learning pooled over all of them, unattended (2026-11-10).
# From the repo root:
#   setsid nohup systemd-inhibit --what=handle-lid-switch:sleep:idle --who=catalyst --why="test regions" \
#     env NEW="NZ ZA MA" HAVE="JP IN1" bash config-pypsa-earth/run_test_regions.sh > models/pypsa-earth/logs/catalyst/driver.out 2>&1 &
#   tail -f models/pypsa-earth/logs/catalyst/status.log
# HAVE = regions whose prenetwork exists, NEW = regions that need one first (config.<R>.yaml as config.JP.yaml).
# Steps (README "Pooled learning over test regions"):
#   1. per NEW region: prestage + prenetwork; a region that fails is left out of the pool
#   2. trunk: PATHWAY_UNTIL=2030 pathway:cfe:<pool>          (2025 dispatch, 2030 first buyers; nothing learned yet)
#   3. pathway:cfepool:<pool>   24/7 CFE buyers; after every horizon the builds of all regions are added up, extrapolated
#                               to the rest of the world and the new costs applied to every region (overlay.cfepool.yaml)
#   4. pathway:refpool:<pool>   the same without buyers (overlay.refpool.yaml); runs even if step 3 failed
#   5. per region: plot_branches.py <R> refpool cfepool --out <R>-pool  (tables and figures in results/learning/<R>-pool/)
# One market per pathway, shared by all regions (results/learning/{cfe,cfepool,refpool}/), so nothing has to be swapped.
# The trunk market results/learning/cfe/ is rewritten for the pool (same numbers, other header); the folders of the
# region in KEEP (default JP: its single-region branches cfesec / cfemid / cfeext live in results/learning/) are copied
# to results/learning/_<KEEP>_<TAG>/ first.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(dirname "$HERE")"; PE="$ROOT/models/pypsa-earth"
read -ra NEW <<< "${NEW-NZ ZA MA}"; read -ra HAVE <<< "${HAVE-JP IN1}"
KEEP="${KEEP:-JP}"; TAG="${TAG:-$(date +%F)}"
export CONTINUE_ON_FAIL=0 MEM_MAX="${MEM_MAX:-20G}" MIN_FREE_GB="${MIN_FREE_GB:-4}"
L="$PE/results/learning"; STATUS="$PE/logs/catalyst/status.log"; mkdir -p "$PE/logs/catalyst"
log() { echo "[$(date '+%F %T')] [test_regions] $*" | tee -a "$STATUS"; }
run() { bash "$HERE/run.sh" "$@"; }

log "######## start: have ${HAVE[*]:-none}, new ${NEW[*]:-none}, keep $KEEP, tag $TAG (cap $MEM_MAX, $(df -BG --output=avail "$PE" | tail -1 | tr -dc 0-9) GB free) ########"
mkdir -p "$L/_${KEEP}_$TAG"
for s in ref cfe cfesec cfemid cfeext; do
  [ -d "$L/$s" ] || continue; rm -rf "$L/_${KEEP}_$TAG/$s"; cp -a "$L/$s" "$L/_${KEEP}_$TAG/$s"
done
log "market folders of $KEEP copied to results/learning/_${KEEP}_$TAG/"

pool=("${HAVE[@]}")
for r in "${NEW[@]}"; do
  if run "prestage:$r" "$r"; then pool+=("$r"); else log "prenetwork of $r FAILED -> left out of the pool"; fi
done
[ ${#pool[@]} -gt 0 ] || { log "no region in the pool, stop"; exit 1; }
P=$(IFS=,; echo "${pool[*]}")
log "==== pool: $P ===="

if PATHWAY_UNTIL=2030 run "pathway:cfe:$P"; then
  run "pathway:cfepool:$P" && log "cfepool DONE" || log "cfepool FAILED"
else
  log "trunk cfe FAILED -> no cfepool"
fi
run "pathway:refpool:$P" && log "refpool DONE" || log "refpool FAILED"

for r in "${pool[@]}"; do
  (cd "$PE" && pixi run python ../../config-pypsa-earth/scripts/plot_branches.py "$r" refpool cfepool --out "$r-pool") \
    >> "$PE/logs/catalyst/test_regions_plots.log" 2>&1 || log "plot_branches $r failed (logs/catalyst/test_regions_plots.log)"
done
log "######## finished: pool $P ########"
