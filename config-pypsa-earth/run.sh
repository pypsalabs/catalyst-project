#!/usr/bin/env bash
# Supervised, sequential driver for the pypsa-earth fork (one stage at a time).
#   bash config-pypsa-earth/run.sh [prestage:<CC>] [<stage> ...]
#   e.g. bash config-pypsa-earth/run.sh prestage:BR BR-smoke BR       (default: prestage:USW USW USE)
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
#   world             results/catalyst/validation_world.{png,pdf,csv}: scripts/plot_world.py over every solved
#                     <R>-now / <R>-zero network (archetypes and rest-of-world groups), run directly (no Snakemake)
#   assumptions       technology-assumptions/build/technology_assumptions.pdf from technology_assumptions.csv and
#                     technology-assumptions/doc (assumptions.smk; no network, always re-checked, never skipped)
#   pathway:<scen>:<R1>,<R2>,...
#                     myopic pathway with a learning market (overlay.<scen>.yaml with catalyst.learning, e.g.
#                     pathway:myopic:SG,CA,OCE): all stages <R>-<scen> advance one planning horizon at a time (target
#                     results/<R>-<scen>/networks/<stem>_<year>.nc, always handed to Snakemake so a changed market file
#                     re-runs exactly the affected horizons), and between horizons scripts/clear_market.py clears the
#                     market of the advanced technologies over all of them (results/learning/<scen>/market_<year>.csv,
#                     read by the palette costs of that year); at the end scripts/plot_learning.py draws
#                     results/learning/<scen>/learning.png. Resumable: a second call re-runs nothing that is up to date.
#                     LEARNING_EXOGENOUS=<csv> (technology, year, gw) adds deployment outside the model (test hook).
#                     PATHWAY_UNTIL=<year> stops after that horizon (the trunk of branched sensitivities). A branch
#                     overlay (catalyst.branch, e.g. pathway:cfeext:JP) solves only the horizons after the branch year,
#                     starting from the parent stage's solved network, with its market seeded from the parent's.
#   Rest-of-world groups (config.<G>.yaml with catalyst.single_node, from scripts/select_countries.py) run as
#   prestage:<G> <G> <G>-now <G>-zero; their overlay target is the solved network itself.
# Constraints enforced here: no Snakemake parallelism (-c1 -j1), the whole process tree capped at MEM_MAX
# RAM with no swap (systemd user scope; inside a Slurm job the job's own limit, see cluster/run.sbatch), a disk watchdog that stops the run below MIN_FREE_GB, retries only
# for network-type failures, never for OOM. CONTINUE_ON_FAIL=1 goes on with the next stage after a failure
# (default: stop). Events go to models/pypsa-earth/logs/catalyst/status.log, full Snakemake output to
# logs/catalyst/<stage>.log, the merged config of each stage to logs/catalyst/config.<stage>.yaml.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PE="${CATALYST_PE:-}"; d="$HERE"; [ -n "$PE" ] || while [ "$d" != "/" ]; do [ -d "$d/models/pypsa-earth" ] && { PE="$d/models/pypsa-earth"; break; }; d="$(dirname "$d")"; done
[ -n "$PE" ] || { echo "models/pypsa-earth not found above $HERE" >&2; exit 1; }
LOGDIR="$PE/logs/catalyst"; mkdir -p "$LOGDIR"
STATUS="$LOGDIR/status.log"
MEM_MAX=${MEM_MAX:-8G}
MIN_FREE_GB=${MIN_FREE_GB:-15}
STAGE_TIMEOUT=${STAGE_TIMEOUT:-20h}
CONTINUE_ON_FAIL=${CONTINUE_ON_FAIL:-0}
# CATALYST_PE (fork checkout to drive, default: models/pypsa-earth above this script), CATALYST_RUN (command prefix for
# python / snakemake, default `pixi run`) and SNAKEMAKE_EXTRA (appended to every snakemake call): used by
# baseline/run_overnight.sh to drive the v0.9.0 worktree with the main fork's environment and an --allowed-rules list
export RUN="${CATALYST_RUN:-pixi run}" SNAKEMAKE_EXTRA="${SNAKEMAKE_EXTRA:-}"
NET_WAITS=${NET_WAITS:-24}   # network outages before any rule ran: up to 24 x 300 s = 2 h of waiting, not counted as attempts
NETWORK_RULES='retrieve_databundle_light|download_osm_data|build_cutout|retrieve_cost_data|build_shapes|build_powerplants|retrieve_validation_data'
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PATH="$HOME/.pixi/bin:$HOME/.local/bin:$PATH"
# Memory cap. Here: a systemd user scope of MEM_MAX around every command. Inside a Slurm job (cluster/run.sbatch) there
# is no user session to open a scope in and the job's own limit (--mem, enforced by Slurm's cgroup) is the cap: the
# commands run bare, MEM_MAX only reports that limit, and "SCOPE memory.peak" is the peak of the job so far (all
# stages of the call), not of one stage.
if [ -n "${SLURM_JOB_ID:-}" ]; then
  SCOPE=(); SCOPE_STAGE=()
  mb=${SLURM_MEM_PER_NODE:-$(( ${SLURM_MEM_PER_CPU:-0} * ${SLURM_CPUS_PER_TASK:-1} ))}
  [ "$mb" -gt 0 ] && MEM_MAX="$(( mb / 1024 ))G"
else
  SCOPE=(systemd-run --user --scope --quiet --expand-environment=no -p "MemoryMax=$MEM_MAX" -p MemorySwapMax=0)
  SCOPE_STAGE=("${SCOPE[@]}" -p OOMPolicy=continue --); SCOPE+=(--)
fi

log() { echo "[$(date '+%F %T')] $*" | tee -a "$STATUS"; }
attempt_log() { tac "$slog" | sed "/######## \[$run\] attempt $attempt /q" | tac; }   # this attempt's part of the stage log
free_gb() { df -BG --output=avail "$PE" | tail -1 | tr -dc 0-9; }
mem_avail_gb() { awk '/MemAvailable/ {printf "%d", $2/1048576}' /proc/meminfo; }

has_config() {   # $1 = region: config.<R>.yaml exists; the v0.9.0 baseline also takes baseline/config.<R>.yaml (the US as one region)
  [ -f "$HERE/config.$1.yaml" ] || { [ "${CATALYST_BASELINE:-0}" = 1 ] && [ -f "$HERE/baseline/config.$1.yaml" ]; }
}

stage_kind() {   # $1 = stage name -> prenetwork | overlay | dashboard | unknown
  case "$1" in
    dashboard:*) echo dashboard ;;
    assumptions) echo assumptions ;;
    *) if has_config "$1"; then echo prenetwork
       elif [[ "$1" == *-* ]] && has_config "${1%-*}" && [ -f "$HERE/overlay.${1##*-}.yaml" ]; then echo overlay
       else echo unknown; fi ;;
  esac
}

link_resources() {   # $1 = base run, $2 = scenario run: share the expensive resources of the base run
  # resources/<run>/ is a real directory of symlinks to the base run's entries (shapes, osm, renewable_profiles,
  # powerplants, natura; not the cost tables and demand profiles, see below) except bus_regions/, which gets its own directory with symlinks to the
  # two build_bus_regions outputs only: simplify_network / cluster_network write busmaps and clustered regions
  # into bus_regions/, and a shared directory would let one scenario run invalidate the other (and the base run)
  # by rewriting those files with a newer mtime (happened 2026-09-20: IN-now re-solved after IN-zero).
  # networks/<run>/base.nc is hardlinked (same inode, same mtime) because base.nc is an input of the shared
  # resources; a fresh copy would make them all look outdated.
  local base="$1" run="$2" e
  if [ -L "resources/$run" ]; then rm "resources/$run"; log "[$run] resources/$run was a directory symlink -> replaced by per-entry links"; fi
  # cost tables and demand profiles depend on stage settings (palette cost overrides, currency, demand year): every
  # stage builds its own (a linked base-run file looks up to date to Snakemake; 2026-10-17 US-myopic lacked `sofc`)
  # resource_classes/ depends on the stage's clustered regions (like bus_regions/): never shared
  # statistics/ holds the stage's tables (demand year, envelope variant, palette costs; tables.smk): never shared
  for e in resources/"$run"/costs_* resources/"$run"/demand_profiles*.csv resources/"$run"/resource_classes resources/"$run"/statistics; do
    [ -L "$e" ] && rm "$e" && log "[$run] removed stage-specific link $e"
  done
  if [ ! -d "resources/$run" ]; then
    mkdir -p "resources/$run/bus_regions"
    for e in resources/"$base"/*; do
      e="$(basename "$e")"
      case "$e" in bus_regions|costs_*|demand_profiles*.csv|resource_classes|statistics) continue ;; esac
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

run_stage() {   # $1 = stage name (see header); HORIZON=<year> (pathway): target that horizon's solved network
  local run="$1" kind tag target slog rc attempt netwait wd rule
  kind=$(stage_kind "$run"); run="${run#dashboard:}"
  tag="$run"; [ "$kind" = dashboard ] && tag="dashboard_$run"
  slog="$LOGDIR/$tag.log"
  cd "$PE" || return 1
  # build config.yaml for this stage and derive its target (merge_config.py prints the target)
  target=$($RUN python "$HERE/merge_config.py" "$kind" "$run" "$PE/config.yaml" ${HORIZON:+"$HORIZON"} 2>>"$slog") || { log "[$run] merge_config.py failed, see $slog"; return 1; }
  cp "$PE/config.yaml" "$LOGDIR/config.$tag.yaml"
  # a document is re-edited, a pathway horizon may have a new market file: let Snakemake decide
  if [ -f "$target" ] && [ "$kind" != assumptions ] && [ -z "${HORIZON:-}" ]; then log "[$run] $target exists, skip"; return 0; fi
  if [ "$kind" = overlay ]; then link_resources "${run%-*}" "$run"; fi
  attempt=0; netwait=0
  while [ "$attempt" -lt 3 ]; do
    attempt=$((attempt + 1))
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
    # SCOPE_STAGE (defined at the top; empty inside a Slurm job). --expand-environment=no: systemd-run >= 259 expands
    # $VARIABLES in a scope's command line itself by default
    # (the bash -c script below starts with $RUN: 'Invalid environment variable name', rc 127; seen 2026-11-10)
    # the scope caps snakemake + the job + any workers; memory.peak is read from
    # inside the scope before it disappears. --rerun-triggers mtime input: never re-run a rule only
    # because its params/code provenance changed (NWE: retrieve_databundle_light wanted to re-run
    # over the read-only, shared data/ files although the bundle list was identical to the earlier stages)
    timeout --signal=TERM --kill-after=5m "$STAGE_TIMEOUT" \
      "${SCOPE_STAGE[@]}" \
      bash -c '$RUN snakemake "$1" -c1 -j1 --rerun-incomplete --rerun-triggers mtime input --set-resources build_shapes:mem_mb=2000 $SNAKEMAKE_EXTRA; rc=$?
               cg=/sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup)
               echo "SCOPE memory.peak=$(( $(cat $cg/memory.peak 2>/dev/null || echo 0) / 1048576 )) MiB events: $(tr "\n" " " < $cg/memory.events 2>/dev/null)"
               exit $rc' _ "$target" >> "$slog" 2>&1
    rc=$?
    kill "$wd" 2>/dev/null; wait "$wd" 2>/dev/null
    log "[$run] attempt $attempt finished rc=$rc; $(grep -o 'SCOPE memory.peak=.*' "$slog" | tail -1)"
    if [ -f "$target" ] && { [ -z "${HORIZON:-}" ] || [ "$rc" -eq 0 ]; }; then   # pathway: the target may predate this attempt
      log "[$run] SUCCESS $target ($(du -h "$target" | cut -f1)); free $(free_gb) GB"
      # resources/<run>/bus_regions/ must describe networks/<run>/ (busmap index/values, region names, clustered x/y =
      # member mean). 2026-09-20: the scenario runs shared resources/<R> through a directory symlink and rewrote the
      # base runs' busmaps and regions with those of another simplified network (US, BR, IN; README "Caveats").
      if [ "$kind" = prenetwork ] || [ "$kind" = overlay ]; then
        if $RUN python "$HERE/scripts/check_bus_regions.py" "$run" >> "$slog" 2>&1; then
          log "[$run] bus_regions/ consistent with networks/$run"
        else
          log "[$run] WARNING resources/$run/bus_regions/ does not describe networks/$run (check_bus_regions.py, see $slog)"
        fi
      fi
      return 0
    fi
    if [ "$rc" -eq 137 ] || attempt_log | grep -qE "SCOPE .*oom_kill [1-9]|MemoryError"; then
      log "[$run] OOM under the ${MEM_MAX} cap -> no retry, needs reconfiguration"; return 3; fi
    [ "$rc" -eq 124 ] && { log "[$run] stage timed out after $STAGE_TIMEOUT -> no retry"; return 4; }
    rule=$(attempt_log | grep -oP "Error in rule \K\w+" | tail -1)
    if echo "${rule:-}" | grep -qE "^($NETWORK_RULES)$"; then
      log "[$run] rule '$rule' failed (network/data rule) -> retry in 120 s"; sleep 120
    elif attempt_log | grep -qE "NameResolutionError|Temporary failure in name resolution|ConnectionError|Max retries exceeded"; then
      # Snakemake reads a remote file at DAG construction (raw.githubusercontent.com): a DNS outage fails the stage
      # before any rule runs (2026-11-12 19:40, JP-cfepool / JP-refpool)
      # an outage before any rule ran (no network at all, e.g. just after a resume from suspend) does not use up an
      # attempt, up to NET_WAITS waits (2026-11-13 17:58-18:13: NWE-now lost its three attempts to one outage)
      if [ -z "${rule:-}" ] && [ "$netwait" -lt "$NET_WAITS" ]; then netwait=$((netwait + 1)); attempt=$((attempt - 1)); fi
      log "[$run] network error (${rule:-before any rule}) -> retry in 300 s (attempt $attempt of 3 used, network wait $netwait of $NET_WAITS)"; sleep 300
    else
      log "[$run] rule '${rule:-?}' failed -> no retry (deterministic failure), see $slog"; return 1
    fi
  done
  log "[$run] GAVE UP after 3 attempts"; return 1
}

run_world() {   # world page over all solved networks, same memory scope as the stages
  local slog="$LOGDIR/world.log"
  cd "$PE" || return 1
  log "[world] plot_world.py -> results/catalyst/validation_world.png (cap ${MEM_MAX})"
  echo "######## [world] $(date) ########" >> "$slog"
  "${SCOPE[@]}" \
    $RUN python "$HERE/scripts/plot_world.py" -o results/catalyst/validation_world.png >> "$slog" 2>&1 \
    || { log "[world] FAILED, see $slog"; return 1; }
  log "[world] SUCCESS results/catalyst/validation_world.png"
}

run_pathway() {   # $1 = pathway:<scen>:<R1>,<R2>,... (see header)
  local spec="${1#pathway:}" scen r s i y ynext slog horizons=() stages=() regions=()
  scen="${spec%%:*}"; IFS=, read -ra regions <<< "${spec#*:}"
  [ -n "$scen" ] && [ ${#regions[@]} -gt 0 ] && [ "$spec" != "$scen" ] || { log "[pathway] usage: pathway:<scen>:<R1>,<R2>,..."; return 1; }
  for r in "${regions[@]}"; do
    s="$r-$scen"; [ "$(stage_kind "$s")" = overlay ] || { log "[pathway $scen] unknown stage $s"; return 1; }; stages+=("$s")
  done
  slog="$LOGDIR/pathway_$scen.log"
  cd "$PE" || return 1
  read -ra horizons <<< "$($RUN python "$HERE/merge_config.py" horizons "${stages[0]}" 2>>"$slog")"
  [ ${#horizons[@]} -gt 0 ] || { log "[pathway $scen] no planning horizons (merge_config.py horizons ${stages[0]}), see $slog"; return 1; }
  log "[pathway $scen] stages ${stages[*]}, horizons ${horizons[*]}${LEARNING_EXOGENOUS:+, exogenous $LEARNING_EXOGENOUS}"
  echo "######## [pathway $scen] $(date) ########" >> "$slog"
  $RUN python "$HERE/scripts/clear_market.py" init "$scen" "${horizons[0]}" "${stages[@]}" >> "$slog" 2>&1 \
    || { log "[pathway $scen] clear_market.py init FAILED, see $slog"; return 1; }
  for i in "${!horizons[@]}"; do
    y="${horizons[$i]}"
    for s in "${stages[@]}"; do
      HORIZON="$y" run_stage "$s" || { log "[pathway $scen] $s $y FAILED -> stop the pathway"; return 1; }
    done
    ynext="${horizons[$((i + 1))]:-}"
    [ -n "$ynext" ] || break
    # PATHWAY_UNTIL=<year>: stop after that horizon (e.g. the trunk of branched sensitivities)
    if [ -n "${PATHWAY_UNTIL:-}" ] && [ "$y" -ge "$PATHWAY_UNTIL" ]; then log "[pathway $scen] PATHWAY_UNTIL=$PATHWAY_UNTIL: stop after $y"; break; fi
    log "[pathway $scen] market step: builds of $y -> costs of $ynext"
    "${SCOPE[@]}" \
      $RUN python "$HERE/scripts/clear_market.py" step "$scen" "$y" "$ynext" "${stages[@]}" \
      ${LEARNING_EXOGENOUS:+--exogenous "$LEARNING_EXOGENOUS"} >> "$slog" 2>&1 \
      || { log "[pathway $scen] clear_market.py step $y FAILED, see $slog"; return 1; }
    log "[pathway $scen] $(grep -oE 'clear_market: (wrote .*|.* unchanged)$' "$slog" | tail -1)"
  done
  $RUN python "$HERE/scripts/plot_learning.py" "$scen" >> "$slog" 2>&1 \
    && log "[pathway $scen] SUCCESS, results/learning/$scen/learning.png" \
    || { log "[pathway $scen] plot_learning.py FAILED, see $slog"; return 1; }
}

stages=("$@"); [ ${#stages[@]} -eq 0 ] && stages=(prestage:USW USW USE)
log "######## run.sh start: ${stages[*]} (cap ${MEM_MAX}, continue_on_fail=${CONTINUE_ON_FAIL}) ########"
ma=$(mem_avail_gb); need=$(( ${MEM_MAX%G} + 2 ))
[ "$ma" -ge "$need" ] || log "WARNING: host MemAvailable ${ma} GB < cap ${MEM_MAX} + 2 GB; close other applications or the host OOM killer may act before the scope cap"
failed=()
for i in "${!stages[@]}"; do
  s="${stages[$i]}"
  case "$s" in
    prestage|prestage:*)
      cc="${s#prestage}"; cc="${cc#:}"
      [ -n "$cc" ] || { cc="${stages[$((i+1))]:-USW}"; cc="${cc%%-*}"; }
      bash "$HERE/prestage.sh" "$cc" || { log "prestage $cc FAILED -> stop"; exit 1; } ;;
    world)
      run_world || { [ "$CONTINUE_ON_FAIL" = 1 ] && failed+=("$s") || exit 1; } ;;
    pathway:*)
      run_pathway "$s" || { [ "$CONTINUE_ON_FAIL" = 1 ] && failed+=("$s") || exit 1; } ;;
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
