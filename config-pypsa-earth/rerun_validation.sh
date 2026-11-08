#!/usr/bin/env bash
# Global validation re-run (2026-11-08): the grid corrections of 2026-11-02 (archetype configs: drop_duplicate_ids,
# fix_indirect_circuits, geodesic_length, links.dc_projects, p_threshold_merge_isolated) and the fleet corrections of
# 2026-11-04 (calibration/2024/capacity.csv etc. from IRENA, electricity.gas_technology_mapping) in solved networks,
# plus the Li-ion fix of the single-node runs (fork enforce_autarky, 2026-11-08). Unattended, from the repo root:
#   setsid nohup systemd-inhibit --what=handle-lid-switch:sleep:idle --who=catalyst --why="validation re-run" \
#     env MEM_MAX=20G bash config-pypsa-earth/rerun_validation.sh > models/pypsa-earth/logs/catalyst/driver.out 2>&1 &
#   tail -f models/pypsa-earth/logs/catalyst/status.log
# Steps:
#  1. move the solved `-now` / `-zero` results of 2026-10-20 to results/archive/<stage>-20261020 (run.sh skips a stage
#     whose target exists) and the archetype prenetworks to networks/archive/<R>-20261020/;
#  2. archetypes (grid options are params, not inputs): prenetwork stage <R> with --forcerun clean_osm_data, which
#     re-runs everything downstream (OSM network, base network, regions, profiles, plants, clustering); the stage
#     base.nc hardlinks networks/<R>-*/base.nc are removed so run.sh links the new base.nc;
#  3. the stage list of 2026-10-20 (all `-now`, all `-zero`, six dashboards, world page), small regions first; the
#     rest-of-world groups re-run from build_powerplants (capacity.csv is newer than every powerplants.csv);
#  4. the before/after pages against the baseline run of 2026-10-29.
# REGIONS / ARCHETYPES limit the run (smoke test: REGIONS="SG" ARCHETYPES="").
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(dirname "$HERE")"; PE="$ROOT/models/pypsa-earth"
TAG="${TAG:-20261020}"
read -ra ARCHETYPES <<< "${ARCHETYPES-BR IN NWE CN US}"   # small -> large; SG has no grid changes
read -ra REGIONS <<< "${REGIONS:-SG IS CA RU OCE NAM SAM MEA EUR AFR ASI BR IN NWE CN US}"
export CONTINUE_ON_FAIL=1 MEM_MAX="${MEM_MAX:-20G}"
STATUS="$PE/logs/catalyst/status.log"; mkdir -p "$PE/logs/catalyst"
log() { echo "[$(date '+%F %T')] [rerun_validation] $*" | tee -a "$STATUS"; }
cd "$PE" || exit 1
log "######## start: archetypes ${ARCHETYPES[*]}, regions ${REGIONS[*]} (cap $MEM_MAX, $(df -BG --output=avail . | tail -1 | tr -dc 0-9) GB free) ########"

# 1. archive
for r in "${REGIONS[@]}"; do
  for o in now zero; do
    if [ -d "results/$r-$o" ]; then
      dst="results/archive/$r-$o-$TAG"; [ -e "$dst" ] && dst="$dst-$(date +%H%M%S)"
      mv "results/$r-$o" "$dst" && log "moved results/$r-$o -> $dst"
    fi
  done
done
for r in "${ARCHETYPES[@]}"; do
  if ls "networks/$r"/elec*.nc >/dev/null 2>&1; then
    mkdir -p "networks/archive/$r-$TAG" && mv "networks/$r"/elec*.nc "networks/archive/$r-$TAG/" \
      && log "moved networks/$r/elec*.nc -> networks/archive/$r-$TAG/"
  fi
  for l in networks/"$r"-*/base.nc; do [ -f "$l" ] && rm "$l" && log "removed stage hardlink $l"; done
done

# 2. archetype prenetworks, rebuilt from clean_osm_data
failed=()
for r in "${ARCHETYPES[@]}"; do
  SNAKEMAKE_EXTRA="--forcerun clean_osm_data" bash "$HERE/run.sh" "$r" || failed+=("$r")
done

# 3. screening solves, dashboards, world page
stages=()
for r in "${REGIONS[@]}"; do stages+=("$r-now"); done
for r in "${REGIONS[@]}"; do stages+=("$r-zero"); done
for r in US BR IN NWE CN SG; do [[ " ${REGIONS[*]} " == *" $r "* ]] && stages+=("dashboard:$r"); done
bash "$HERE/run.sh" "${stages[@]}" world || failed+=("stages")

# 4. before/after pages (baseline = PyPSA-Earth v0.9.0 of 2026-10-29)
B="$ROOT/models/pypsa-earth-baseline/results/catalyst/validation_world.csv"
OUT="$ROOT/misc-quarter1/pypsa-earth-out-of-the-box-validation/figures/before-after"
if [ -f "$B" ] && [ -f results/catalyst/validation_world.csv ]; then
  pixi run python "$HERE/scripts/plot_before_after.py" --before "$B" --after results/catalyst/validation_world.csv \
      --out "$OUT/before_after.png" >> logs/catalyst/before_after.log 2>&1 || failed+=("before_after")
  pixi run python "$HERE/scripts/plot_world_before_after.py" --before "$B" --after results/catalyst/validation_world.csv \
      --out "$OUT/validation_world_before_after.png" >> logs/catalyst/before_after.log 2>&1 || failed+=("world_before_after")
  cp results/catalyst/validation_*.{png,pdf,csv} "$ROOT/misc-quarter1/pypsa-earth-out-of-the-box-validation/figures/" 2>/dev/null
else
  failed+=("before_after (missing $B or validation_world.csv)")
fi
log "######## finished${failed[*]:+ with failures: ${failed[*]}} ########"
