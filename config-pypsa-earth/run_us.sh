#!/usr/bin/env bash
# Supervised, sequential driver for the CONUS pypsa-earth prenetwork.
#   bash config-pypsa-earth/run_us.sh [prestage] [US-smoke] [US]     (default: all three, in order)
# Constraints enforced here: no Snakemake parallelism (-c1 -j1), the whole
# process tree capped at MEM_MAX RAM with no swap (systemd user scope), a disk
# watchdog that stops the run below MIN_FREE_GB, retries only for network-type
# failures, never for OOM. Events go to models/pypsa-earth/logs/catalyst/status.log,
# full Snakemake output to logs/catalyst/<stage>.log.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PE="$(cd "$HERE/../models/pypsa-earth" && pwd)"
LOGDIR="$PE/logs/catalyst"; mkdir -p "$LOGDIR"
STATUS="$LOGDIR/status.log"
MEM_MAX=${MEM_MAX:-8G}
MIN_FREE_GB=${MIN_FREE_GB:-15}
STAGE_TIMEOUT=${STAGE_TIMEOUT:-20h}
TARGET_TMPL='networks/%s/elec_s_50_ec_lcopt_Co2L.nc'
NETWORK_RULES='retrieve_databundle_light|download_osm_data|build_cutout|retrieve_cost_data|build_shapes|build_powerplants'
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PATH="$HOME/.pixi/bin:$HOME/.local/bin:$PATH"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$STATUS"; }
free_gb() { df -BG --output=avail "$PE" | tail -1 | tr -dc 0-9; }

run_stage() {   # $1 = run name: US-smoke | US
  local run="$1" cfg="$HERE/config.$1.yaml" target slog rc attempt wd rule
  target=$(printf "$TARGET_TMPL" "$run"); slog="$LOGDIR/$run.log"
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
    # inside the scope before it disappears
    timeout --signal=TERM --kill-after=5m "$STAGE_TIMEOUT" \
      systemd-run --user --scope --quiet -p "MemoryMax=$MEM_MAX" -p MemorySwapMax=0 -p OOMPolicy=continue -- \
      bash -c 'pixi run snakemake "$1" -c1 -j1 --rerun-incomplete --set-resources build_shapes:mem_mb=2000; rc=$?
               cg=/sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup)
               echo "SCOPE memory.peak=$(( $(cat $cg/memory.peak 2>/dev/null || echo 0) / 1048576 )) MiB events: $(tr "\n" " " < $cg/memory.events 2>/dev/null)"
               exit $rc' _ "$target" >> "$slog" 2>&1
    rc=$?
    kill "$wd" 2>/dev/null; wait "$wd" 2>/dev/null
    log "[$run] attempt $attempt finished rc=$rc; $(grep -o 'SCOPE memory.peak=.*' "$slog" | tail -1)"
    [ -f "$target" ] && { log "[$run] SUCCESS $target ($(du -h "$target" | cut -f1)); free $(free_gb) GB"; return 0; }
    if [ "$rc" -eq 137 ] || sed -n "/######## \[$run\] attempt $attempt /,\$p" "$slog" | grep -qE "SCOPE .*oom_kill [1-9]|MemoryError|Killed"; then
      log "[$run] OOM under the ${MEM_MAX} cap -> no retry, needs reconfiguration"; return 3; fi
    [ "$rc" -eq 124 ] && { log "[$run] stage timed out after $STAGE_TIMEOUT -> no retry"; return 4; }
    rule=$(sed -n "/######## \[$run\] attempt $attempt /,\$p" "$slog" | grep -oP "Error in rule \K\w+" | tail -1)
    if echo "${rule:-}" | grep -qE "^($NETWORK_RULES)$"; then
      log "[$run] rule '$rule' failed (network/data rule) -> retry in 120 s"; sleep 120
    else
      log "[$run] rule '${rule:-?}' failed -> no retry (deterministic failure), see $slog"; return 1
    fi
  done
  log "[$run] GAVE UP after 3 attempts"; return 1
}

stages=("$@"); [ ${#stages[@]} -eq 0 ] && stages=(prestage US-smoke US)
log "######## run_us.sh start: ${stages[*]} ########"
for s in "${stages[@]}"; do
  case "$s" in
    prestage) bash "$HERE/prestage.sh" || { log "prestage FAILED -> stop"; exit 1; } ;;
    US-smoke|US) run_stage "$s" || { log "stage $s FAILED -> stop"; exit 1; } ;;
    *) log "unknown stage $s"; exit 1 ;;
  esac
done
log "######## run_us.sh finished all stages: ${stages[*]} ########"
