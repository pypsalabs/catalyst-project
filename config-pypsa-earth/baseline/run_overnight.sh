#!/usr/bin/env bash
# Before/after comparison of the catalyst patches, BEFORE side, in one unattended run: PyPSA-Earth v0.9.0 as it comes
# (+ the 12 run-enabling patches, worktree models/pypsa-earth-baseline, branch baseline-v0.9.0) solved for every stage of
# the 2026-10-20 validation, `now` and `zero` with the out-of-the-box overlays of baseline/, then the six dashboards, the
# world page and the before/after page (scripts/plot_before_after.py against the main fork's validation_world.csv).
# From the repo root:
#   setsid nohup systemd-inhibit --what=handle-lid-switch:sleep:idle --who=catalyst --why="pypsa-earth baseline run" \
#     env MEM_MAX=20G bash config-pypsa-earth/baseline/run_overnight.sh > models/pypsa-earth-baseline/logs/catalyst/driver.out 2>&1 &
#   tail -f models/pypsa-earth-baseline/logs/catalyst/status.log
# Resumable: prep_region.sh and run.sh skip whatever exists. REGIONS="SG" limits the run (smoke test).
# Safety: the main fork is only read (hardlinks, see prep_region.sh); every snakemake call carries --allowed-rules, so a
# stage that would rebuild profiles or write into the linked data/ / cutouts/ fails instead; at the end the driver lists
# any file of the main fork's results/, resources/, networks/ newer than its start stamp (expected: none).
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; CFG="$(dirname "$HERE")"; ROOT="$(dirname "$CFG")"
B="$ROOT/models/pypsa-earth-baseline"; M="$ROOT/models/pypsa-earth"
export CATALYST_BASELINE=1 CATALYST_PE="$B" CATALYST_MAIN="$M" MEM_MAX="${MEM_MAX:-20G}" CONTINUE_ON_FAIL=1
export CATALYST_RUN="env PATH=$M/.pixi/envs/default/bin:$PATH"
read -ra REGIONS <<< "${REGIONS:-BR IN NWE US CN SG CA OCE EUR MEA AFR ASI NAM SAM RU IS}"
ARCHETYPES=(US BR IN NWE CN SG)
SOLVE_RULES="retrieve_cost_data process_cost_data build_demand_profiles add_electricity simplify_network cluster_network
add_extra_components prepare_network solve_network plot_validation build_validation_points retrieve_validation_data
validation_dashboard"
OUT="${BA_OUT:-$ROOT/misc-quarter1/pypsa-earth-out-of-the-box-validation/figures/before-after}"   # BA_OUT: elsewhere (smoke test)
STATUS="$B/logs/catalyst/status.log"; mkdir -p "$B/logs/catalyst"
log() { echo "[$(date '+%F %T')] [baseline] $*" | tee -a "$STATUS"; }

# preflight
[ -f "$B/.git" ] && [ "$(git -C "$B" rev-parse --abbrev-ref HEAD)" = baseline-v0.9.0 ] || { log "ABORT: $B is not the baseline-v0.9.0 worktree"; exit 1; }
[ -f "$HOME/gurobi.lic" ] || { log "ABORT: no ~/gurobi.lic"; exit 1; }
free=$(df -BG --output=avail "$B" | tail -1 | tr -dc 0-9)
[ "$free" -ge "${MIN_START_GB:-55}" ] || { log "ABORT: ${free} GB free < ${MIN_START_GB:-55} GB"; exit 1; }
STAMP="$B/logs/catalyst/start.stamp"; touch "$STAMP"
git -C "$M" status --short > "$B/logs/catalyst/main_status_before.txt"
log "######## start: ${REGIONS[*]} (cap $MEM_MAX, ${free} GB free) ########"

failed=()
for r in "${REGIONS[@]}"; do
  bash "$HERE/prep_region.sh" "$r" || { failed+=("prep:$r"); log "prep $r FAILED -> skip its solves"; continue; }
  SNAKEMAKE_EXTRA="--allowed-rules $SOLVE_RULES" bash "$CFG/run.sh" "$r-now" "$r-zero" || failed+=("$r-now/zero")
done

dash=()
for r in "${ARCHETYPES[@]}"; do [[ " ${REGIONS[*]} " == *" $r "* ]] && dash+=("dashboard:$r"); done
SNAKEMAKE_EXTRA="--allowed-rules $SOLVE_RULES" bash "$CFG/run.sh" "${dash[@]}" world || failed+=("dashboards/world")

# before/after page + copies of the before pages for the colleagues' folder
mkdir -p "$OUT/before"
cp "$B"/results/catalyst/validation_*.{png,pdf,csv} "$OUT/before/" 2>/dev/null
if (cd "$M" && $CATALYST_RUN python "$CFG/scripts/plot_before_after.py" --before "$B/results/catalyst/validation_world.csv" \
      --after "$M/results/catalyst/validation_world.csv" --out "$OUT/before_after.png") >> "$B/logs/catalyst/before_after.log" 2>&1; then
  log "before/after page -> $OUT/before_after.png"
else
  failed+=("before_after"); log "plot_before_after.py FAILED, see $B/logs/catalyst/before_after.log"
fi
(cd "$M" && $CATALYST_RUN python "$CFG/scripts/plot_world_before_after.py" --before "$B/results/catalyst/validation_world.csv" \
    --after "$M/results/catalyst/validation_world.csv" --out "$OUT/validation_world_before_after.png") >> "$B/logs/catalyst/before_after.log" 2>&1 \
  || { failed+=("world_before_after"); log "plot_world_before_after.py FAILED, see $B/logs/catalyst/before_after.log"; }

# the main fork must be untouched
touched=$(find "$M/results" "$M/resources" "$M/networks" -newer "$STAMP" 2>/dev/null | head -20)
git -C "$M" status --short | diff -q - "$B/logs/catalyst/main_status_before.txt" >/dev/null || touched+=$'\n(git status of the main fork changed)'
[ -z "$touched" ] && log "main fork untouched (no file newer than the start stamp)" || log "WARNING main fork files changed: ${touched//$'\n'/ }"
log "######## finished${failed[*]:+ with FAILED: ${failed[*]}} ########"
