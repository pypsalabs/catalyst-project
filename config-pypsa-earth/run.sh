#!/usr/bin/env bash
# Supervised, sequential driver for the pypsa-earth fork (one stage at a time).
#   bash config-pypsa-earth/run.sh [prestage:<CC>] [<stage> ...]
#   e.g. bash config-pypsa-earth/run.sh prestage:BR BR-smoke BR       (default: prestage:US US-smoke US)
#        CONTINUE_ON_FAIL=1 MEM_MAX=14G bash config-pypsa-earth/run.sh NWE-now NWE-zero dashboard:NWE
# Stage kinds (config.<name>.yaml lives in config-pypsa-earth/):
#   <name>            prenetwork: target networks/<name>/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}.nc
#   <R>-<scen>        screening scenario, when no config.<R>-<scen>.yaml exists but config.<R>.yaml and
#                     overlay.<scen>.yaml do: merged config (run.name = <R>-<scen>), resources/<R>-<scen>/
#                     made of symlinks into resources/<R> so only add_electricity and downstream are rebuilt; target
#                     results/<R>-<scen>/plots/validation_...png (solve_network + plot_validation)
#   dashboard:<R>     results/catalyst/validation_<R>.png (left <R>-now, right <R>-zero; validation.smk)
#   prestage[:<CC>]   prestage.sh for that country (OSM pre-filter, bundle); bare "prestage" uses the
#                     country prefix of the next stage name (BR-smoke -> BR)
# Constraints enforced here: no Snakemake parallelism (-c1 -j1), the whole process tree capped at MEM_MAX
# RAM with no swap (systemd user scope), a disk watchdog that stops the run below MIN_FREE_GB, retries only
# for network-type failures, never for OOM. CONTINUE_ON_FAIL=1 goes on with the next stage after a failure
# (default: stop). Events go to models/pypsa-earth/logs/catalyst/status.log, full Snakemake output to
# logs/catalyst/<stage>.log, the merged config of each stage to logs/catalyst/config.<stage>.yaml.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PE=""; d="$HERE"; while [ "$d" != "/" ]; do [ -d "$d/models/pypsa-earth" ] && { PE="$d/models/pypsa-earth"; break; }; d="$(dirname "$d")"; done
[ -n "$PE" ] || { echo "models/pypsa-earth not found above $HERE" >&2; exit 1; }
LOGDIR="$PE/logs/catalyst"; mkdir -p "$LOGDIR"
STATUS="$LOGDIR/status.log"
MEM_MAX=${MEM_MAX:-8G}
MIN_FREE_GB=${MIN_FREE_GB:-15}
STAGE_TIMEOUT=${STAGE_TIMEOUT:-20h}
CONTINUE_ON_FAIL=${CONTINUE_ON_FAIL:-0}
NETWORK_RULES='retrieve_databundle_light|download_osm_data|build_cutout|retrieve_cost_data|build_shapes|build_powerplants|retrieve_validation_data'
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PATH="$HOME/.pixi/bin:$HOME/.local/bin:$PATH"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$STATUS"; }
attempt_log() { tac "$slog" | sed "/######## \[$run\] attempt $attempt /q" | tac; }   # this attempt's part of the stage log
free_gb() { df -BG --output=avail "$PE" | tail -1 | tr -dc 0-9; }
mem_avail_gb() { awk '/MemAvailable/ {printf "%d", $2/1048576}' /proc/meminfo; }

stage_kind() {   # $1 = stage name -> prenetwork | overlay | dashboard | unknown
  case "$1" in
    dashboard:*) echo dashboard ;;
    *) if [ -f "$HERE/config.$1.yaml" ]; then echo prenetwork
       elif [[ "$1" == *-* ]] && [ -f "$HERE/config.${1%-*}.yaml" ] && [ -f "$HERE/overlay.${1##*-}.yaml" ]; then echo overlay
       else echo unknown; fi ;;
  esac
}

link_resources() {   # $1 = base run, $2 = scenario run: share the expensive resources of the base run
  # resources/<run>/ is a real directory of symlinks to the base run's entries (shapes, osm, renewable_profiles,
  # powerplants, demand, natura, cost files) except bus_regions/, which gets its own directory with symlinks to the
  # two build_bus_regions outputs only: simplify_network / cluster_network write busmaps and clustered regions
  # into bus_regions/, and a shared directory would let one scenario run invalidate the other (and the base run)
  # by rewriting those files with a newer mtime (happened 2026-09-20: IN-now re-solved after IN-zero).
  # networks/<run>/base.nc is hardlinked (same inode, same mtime) because base.nc is an input of the shared
  # resources; a fresh copy would make them all look outdated.
  local base="$1" run="$2" e
  if [ -L "resources/$run" ]; then rm "resources/$run"; log "[$run] resources/$run was a directory symlink -> replaced by per-entry links"; fi
  if [ ! -d "resources/$run" ]; then
    mkdir -p "resources/$run/bus_regions"
    for e in resources/"$base"/*; do
      e="$(basename "$e")"; [ "$e" = bus_regions ] && continue
      ln -s "../$base/$e" "resources/$run/$e"
    done
    for e in regions_onshore.geojson regions_offshore.geojson; do
      [ -e "resources/$base/bus_regions/$e" ] && ln -s "../../$base/bus_regions/$e" "resources/$run/bus_regions/$e"
    done
    log "[$run] resources/$run/: per-entry symlinks to resources/$base (own bus_regions/)"
  fi
  if [ ! -e "networks/$run/base.nc" ] && [ -f "networks/$base/base.nc" ]; then
    mkdir -p "networks/$run"; ln "networks/$base/base.nc" "networks/$run/base.nc"; log "[$run] networks/$run/base.nc hardlinked from networks/$base"; fi
}

run_stage() {   # $1 = stage name (see header)
  local run="$1" kind tag target slog rc attempt wd rule
  kind=$(stage_kind "$run"); run="${run#dashboard:}"
  tag="$run"; [ "$kind" = dashboard ] && tag="dashboard_$run"
  slog="$LOGDIR/$tag.log"
  cd "$PE" || return 1
  # build config.yaml for this stage and derive its target (merge_config.py prints the target)
  target=$(pixi run python "$HERE/merge_config.py" "$kind" "$run" "$PE/config.yaml" 2>>"$slog") || { log "[$run] merge_config.py failed, see $slog"; return 1; }
  cp "$PE/config.yaml" "$LOGDIR/config.$tag.yaml"
  if [ -f "$target" ]; then log "[$run] $target exists, skip"; return 0; fi
  if [ "$kind" = overlay ]; then link_resources "${run%-*}" "$run"; fi
  for attempt in 1 2 3; do
    # pypsa-earth aborts at DAG construction if build_cutout is enabled while the
    # cutout file already exists (terminate_if_cutout_exists), so switch the rule
    # off as soon as this stage's cutout has been built.
    cutout_name=$(grep -oP '^\s*default:\s*\K\S+' config.yaml | head -1)
    if [ -n "$cutout_name" ] && [ -f "cutouts/$cutout_name.nc" ] && grep -qE '^\s*build_cutout:\s*true' config.yaml; then
      sed -i 's/^\(\s*build_cutout:\s*\)true/\1false/' config.yaml
      log "[$run] cutouts/$cutout_name.nc exists -> build_cutout disabled for this attempt"
    fi
    local f; f=$(free_gb)
    [ "$f" -ge "$MIN_FREE_GB" ] || { log "[$run] DISK LOW ${f} GB < ${MIN_FREE_GB} GB, abort"; return 2; }
    log "[$run] attempt $attempt -> $target (free ${f} GB, host MemAvailable $(mem_avail_gb) GB, cap ${MEM_MAX}, -c1 -j1)"
    echo "######## [$run] attempt $attempt $(date) ########" >> "$slog"
    # disk watchdog: every 10 min log usage, stop snakemake if disk gets low
    ( while sleep 600; do
        g=$(free_gb); echo "[$(date '+%F %T')] [$run] disk free ${g} GB, host MemAvailable $(mem_avail_gb) GB, repo $(du -sh "$PE" 2>/dev/null | cut -f1)" >> "$STATUS"
        if [ "$g" -lt "$MIN_FREE_GB" ]; then
          echo "[$(date '+%F %T')] [$run] DISK LOW -> stopping snakemake" >> "$STATUS"
          pkill -TERM -f "snakemake $target" ; fi
      done ) & wd=$!
    # the scope caps snakemake + the job + any workers; memory.peak is read from
    # inside the scope before it disappears. --rerun-triggers mtime input: never re-run a rule only
    # because its params/code provenance changed (NWE: retrieve_databundle_light wanted to re-run
    # over the read-only, shared data/ files although the bundle list was identical to the earlier stages)
    timeout --signal=TERM --kill-after=5m "$STAGE_TIMEOUT" \
      systemd-run --user --scope --quiet -p "MemoryMax=$MEM_MAX" -p MemorySwapMax=0 -p OOMPolicy=continue -- \
      bash -c 'pixi run snakemake "$1" -c1 -j1 --rerun-incomplete --rerun-triggers mtime input --set-resources build_shapes:mem_mb=2000; rc=$?
               cg=/sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup)
               echo "SCOPE memory.peak=$(( $(cat $cg/memory.peak 2>/dev/null || echo 0) / 1048576 )) MiB events: $(tr "\n" " " < $cg/memory.events 2>/dev/null)"
               exit $rc' _ "$target" >> "$slog" 2>&1
    rc=$?
    kill "$wd" 2>/dev/null; wait "$wd" 2>/dev/null
    log "[$run] attempt $attempt finished rc=$rc; $(grep -o 'SCOPE memory.peak=.*' "$slog" | tail -1)"
    [ -f "$target" ] && { log "[$run] SUCCESS $target ($(du -h "$target" | cut -f1)); free $(free_gb) GB"; return 0; }
    if [ "$rc" -eq 137 ] || attempt_log | grep -qE "SCOPE .*oom_kill [1-9]|MemoryError"; then
      log "[$run] OOM under the ${MEM_MAX} cap -> no retry, needs reconfiguration"; return 3; fi
    [ "$rc" -eq 124 ] && { log "[$run] stage timed out after $STAGE_TIMEOUT -> no retry"; return 4; }
    rule=$(attempt_log | grep -oP "Error in rule \K\w+" | tail -1)
    if echo "${rule:-}" | grep -qE "^($NETWORK_RULES)$"; then
      log "[$run] rule '$rule' failed (network/data rule) -> retry in 120 s"; sleep 120
    else
      log "[$run] rule '${rule:-?}' failed -> no retry (deterministic failure), see $slog"; return 1
    fi
  done
  log "[$run] GAVE UP after 3 attempts"; return 1
}

stages=("$@"); [ ${#stages[@]} -eq 0 ] && stages=(prestage:US US-smoke US)
log "######## run.sh start: ${stages[*]} (cap ${MEM_MAX}, continue_on_fail=${CONTINUE_ON_FAIL}) ########"
ma=$(mem_avail_gb); need=$(( ${MEM_MAX%G} + 2 ))
[ "$ma" -ge "$need" ] || log "WARNING: host MemAvailable ${ma} GB < cap ${MEM_MAX} + 2 GB; close other applications or the host OOM killer may act before the scope cap"
failed=()
for i in "${!stages[@]}"; do
  s="${stages[$i]}"
  case "$s" in
    prestage|prestage:*)
      cc="${s#prestage}"; cc="${cc#:}"
      [ -n "$cc" ] || { cc="${stages[$((i+1))]:-US}"; cc="${cc%%-*}"; }
      bash "$HERE/prestage.sh" "$cc" || { log "prestage $cc FAILED -> stop"; exit 1; } ;;
    *)
      [ "$(stage_kind "$s")" != unknown ] || { log "unknown stage $s (no config.$s.yaml, and not <R>-<scen> with config.<R>.yaml + overlay.<scen>.yaml)"; exit 1; }
      if ! run_stage "$s"; then
        if [ "$CONTINUE_ON_FAIL" = 1 ]; then log "stage $s FAILED -> continue with the next stage"; failed+=("$s")
        else log "stage $s FAILED -> stop"; exit 1; fi
      fi ;;
  esac
done
if [ ${#failed[@]} -gt 0 ]; then log "######## run.sh finished with FAILED stages: ${failed[*]} ########"; exit 1; fi
log "######## run.sh finished all stages: ${stages[*]} ########"
