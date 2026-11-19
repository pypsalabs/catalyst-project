#!/usr/bin/env bash
# Resource classes as the default (2026-11-12, README "Resource classes", Phase 2): rebuild what the classes change,
# unattended. From the repo root:
#   setsid nohup systemd-inhibit --what=handle-lid-switch:sleep:idle --who=catalyst --why="resource classes rebuild" \
#     bash config-pypsa-earth/rerun_classes.sh > models/pypsa-earth/logs/catalyst/driver.out 2>&1 &
#   tail -f models/pypsa-earth/logs/catalyst/status.log
# Steps (each stage first runs build_resource_cells once per base run, then build_resource_classes on its own regions):
#   1. the pooled test-region pathways (run_test_regions.sh with HAVE = the five test regions, NEW empty): 24/7 CFE trunk
#      to 2030, cfepool, refpool, plot_branches per region. Pathway horizons are handed to Snakemake, which re-runs
#      them because the input set of add_extra_components changed (no archiving needed); also the first runs with the
#      CFE buyer-location fix of 2026-11-12. The markets of before are copied to results/learning/_JP_<TAG>/.
#   2. the global validation (rerun_validation.sh without the archetype prenetworks: their stages build their own
#      regions, and the base runs IN / NWE / US failed on 2026-11-08 anyway): all -now / -zero moved to
#      results/archive/<stage>-20261109, re-solved, dashboards, world page, before/after pages. `-now` must reproduce
#      the 2024 dispatch (classes are energy-neutral for the fleet); `-zero` changes.
# Not rebuilt (stale, pre-classes): the <G>-myopic group stages (void since 2026-11-08), the JP single-region branches
# (JP-ref, JP-cfesec / cfemid / cfeext), MA10 (cfenode / cfezone; cfezone is now cfe), the A/B record JP-{ref,refrc,cfenorc,cferc,nowrc}.
# STEPS limits the run (e.g. STEPS="pool" or STEPS="validation"); SKIP_ARCHIVE=1 continues an interrupted validation step
# (2026-11-12 19:42: the pool step failed on a DNS outage, the validation had begun; restarted as STEPS="pool validation"
# SKIP_ARCHIVE=1, run.sh now retries network errors).
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(dirname "$HERE")"; PE="$ROOT/models/pypsa-earth"
read -ra STEPS <<< "${STEPS:-pool validation}"
export MEM_MAX="${MEM_MAX:-20G}" MIN_FREE_GB="${MIN_FREE_GB:-6}"
STATUS="$PE/logs/catalyst/status.log"; mkdir -p "$PE/logs/catalyst"
log() { echo "[$(date '+%F %T')] [rerun_classes] $*" | tee -a "$STATUS"; }
log "######## start: steps ${STEPS[*]} (cap $MEM_MAX, min free $MIN_FREE_GB GB, $(df -BG --output=avail "$PE" | tail -1 | tr -dc 0-9) GB free) ########"
failed=()
for s in "${STEPS[@]}"; do
  case "$s" in
    pool) NEW="" HAVE="JP IN1 NZ ZA MA" KEEP=JP TAG="${POOL_TAG:-2026-11-12-classes}" bash "$HERE/run_test_regions.sh" || failed+=(pool) ;;
    validation) ARCHETYPES="" TAG=20261109 SKIP_ARCHIVE="${SKIP_ARCHIVE:-0}" bash "$HERE/rerun_validation.sh" || failed+=(validation) ;;
    *) log "unknown step $s"; failed+=("$s") ;;
  esac
  log "step $s done"
done
log "######## finished${failed[*]:+ with failures: ${failed[*]}} ########"
