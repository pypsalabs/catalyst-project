#!/usr/bin/env bash
# Supervised, sequential driver for pypsa-earth prenetworks (one country per stage).
#   bash config-pypsa-earth/run.sh [prestage:<CC>] [<stage> ...]
#   e.g. bash config-pypsa-earth/run.sh prestage:BR BR-smoke BR     (default: prestage:US US-smoke US)
# A stage <name> is any config-pypsa-earth/config.<name>.yaml; its target is
# networks/<name>/elec_s_<clusters>_ec_lcopt_Co2L.nc. "prestage:<CC>" runs prestage.sh for that
# country (OSM pre-filter, bundle); a bare "prestage" uses the country prefix of the next
# stage name (BR-smoke -> BR).
# Constraints enforced here: no Snakemake parallelism (-c1 -j1), the whole
# process tree capped at MEM_MAX RAM with no swap (systemd user scope), a disk
# watchdog that stops the run below MIN_FREE_GB, retries only for network-type
# failures, never for OOM. Events go to models/pypsa-earth/logs/catalyst/status.log,
# full Snakemake output to logs/catalyst/<stage>.log.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PE=""; d="$HERE"; while [ "$d" != "/" ]; do [ -d "$d/models/pypsa-earth" ] && { PE="$d/models/pypsa-earth"; break; }; d="$(dirname "$d")"; done
[ -n "$PE" ] || { echo "models/pypsa-earth not found above $HERE" >&2; exit 1; }
LOGDIR="$PE/logs/catalyst"; mkdir -p "$LOGDIR"
STATUS="$LOGDIR/status.log"
MEM_MAX=${MEM_MAX:-8G}
MIN_FREE_GB=${MIN_FREE_GB:-15}
STAGE_TIMEOUT=${STAGE_TIMEOUT:-20h}
TARGET_TMPL='networks/%s/elec_s_%s_ec_lcopt_Co2L.nc'   # %s = run name, cluster count (scenario.clusters[0] of the stage config)
NETWORK_RULES='retrieve_databundle_light|download_osm_data|build_cutout|retrieve_cost_data|build_shapes|build_powerplants'
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PATH="$HOME/.pixi/bin:$HOME/.local/bin:$PATH"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$STATUS"; }
attempt_log() { tac "$slog" | sed "/######## \[$run\] attempt $attempt /q" | tac; }   # this attempt's part of the stage log
free_gb() { df -BG --output=avail "$PE" | tail -1 | tr -dc 0-9; }

run_stage() {   # $1 = stage / run name (config.<name>.yaml must exist)
  local run="$1" cfg="$HERE/config.$1.yaml" target slog rc attempt wd rule ncl
  ncl=$(sed -n 's/^  clusters: \[\([0-9]*\)\].*/\1/p' "$cfg" | head -1); ncl=${ncl:-50}
  target=$(printf "$TARGET_TMPL" "$run" "$ncl"); slog="$LOGDIR/$run.log"
  cd "$PE" || return 1
  [ -f "$cfg" ] || { log "[$run] missing $cfg"; return 1; }
  if [ -f "$target" ]; then log "[$run] $target exists, skip"; return 0; fi
  for attempt in 1 2 3; do
    cp "$cfg" config.yaml
    # pypsa-earth aborts at DAG construction if build_cutout is enabled while the
    # cutout file already exists (terminate_if_cutout_exists), so switch the rule
    # off as soon as this stage's cutout has been built.
    cutout_name=$(grep -oP '^\s*default:\s*\K\S+' config.yaml | head -1)
    if [ -n "$cutout_name" ] && [ -f "cutouts/$cutout_name.nc" ]; then
      sed -i 's/^\(\s*build_cutout:\s*\)true/\1false/' config.yaml
      log "[$run] cutouts/$cutout_name.nc exists -> build_cutout disabled for this attempt"
    fi
    local f; f=$(free_gb)
    [ "$f" -ge "$MIN_FREE_GB" ] || { log "[$run] DISK LOW ${f} GB < ${MIN_FREE_GB} GB, abort"; return 2; }
    log "[$run] attempt $attempt -> $target (free ${f} GB, cap ${MEM_MAX}, -c1 -j1)"
    echo "######## [$run] attempt $attempt $(date) ########" >> "$slog"
    # disk watchdog: every 10 min log usage, stop snakemake if disk gets low
    ( while sleep 600; do
        g=$(free_gb); echo "[$(date '+%F %T')] [$run] disk free ${g} GB, repo $(du -sh "$PE" 2>/dev/null | cut -f1)" >> "$STATUS"
        if [ "$g" -lt "$MIN_FREE_GB" ]; then
          echo "[$(date '+%F %T')] [$run] DISK LOW -> stopping snakemake" >> "$STATUS"
          pkill -TERM -f "snakemake networks/$run/" ; fi
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
log "######## run.sh start: ${stages[*]} ########"
for i in "${!stages[@]}"; do
  s="${stages[$i]}"
  case "$s" in
    prestage|prestage:*)
      cc="${s#prestage}"; cc="${cc#:}"
      [ -n "$cc" ] || { cc="${stages[$((i+1))]:-US}"; cc="${cc%%-*}"; }
      bash "$HERE/prestage.sh" "$cc" || { log "prestage $cc FAILED -> stop"; exit 1; } ;;
    *)
      [ -f "$HERE/config.$s.yaml" ] || { log "unknown stage $s (no config.$s.yaml)"; exit 1; }
      run_stage "$s" || { log "stage $s FAILED -> stop"; exit 1; } ;;
  esac
done
log "######## run.sh finished all stages: ${stages[*]} ########"
