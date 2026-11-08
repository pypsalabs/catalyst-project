#!/usr/bin/env bash
# Before/after comparison, BEFORE side: prepare resources/<R>/ of the v0.9.0 worktree (models/pypsa-earth-baseline) so that
# its <R>-now / <R>-zero stages rebuild only what the catalyst patches change, without recomputing shapes, OSM or the
# wind / solar profiles (hours per region).
#   bash config-pypsa-earth/baseline/prep_region.sh <R> [--check]     (--check: steps 1-5 only, no powerplants / hydro)
# Steps (each logged as "[prep <R>]" in the baseline logs/catalyst/status.log):
#   1. hardlink (cp -al: own directory entries, shared inodes) the patch-independent entries of the main run's
#      resources/<R>/: shapes/, osm/, base_network/ (build_osm_network outputs), natura.tiff, bus_regions/regions_*.geojson,
#      renewable_profiles/profile_{onwind,offwind-ac,offwind-dc,solar}.nc. Snakemake replaces outputs by unlinking them, so
#      the main files can never change; this script never touches a hardlinked file.
#   2. networks/<R>/base.nc rebuilt by v0.9.0 base_network (HVDC links at the default rating: the only patch effect there)
#   3. gate: same buses (index, x, y) as the main base.nc, else the linked regions and profiles would not describe it
#   4. the new base.nc (own inode) gets the mtime of the main base.nc, which is older than the linked regions / profiles
#   5. gate: the dry run for powerplants.csv (+ profile_hydro.nc) may contain build_powerplants and the hydro profile only
#   6. build them (powerplantmatching as it comes; hydro normalised the upstream way) under the memory cap
# Environment: CATALYST_PE (worktree), CATALYST_MAIN (main fork), CATALYST_RUN, MEM_MAX, as set by run_overnight.sh.
set -u
R="$1"; CHECK="${2:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; CFG="$(dirname "$HERE")"
B="${CATALYST_PE:?}"; M="${CATALYST_MAIN:?}"; RUN="${CATALYST_RUN:?}"; MEM_MAX="${MEM_MAX:-20G}"
STATUS="$B/logs/catalyst/status.log"; SLOG="$B/logs/catalyst/prep_$R.log"; mkdir -p "$B/logs/catalyst"
log() { echo "[$(date '+%F %T')] [prep $R] $*" | tee -a "$STATUS"; }
capped() { systemd-run --user --scope --quiet -p "MemoryMax=$MEM_MAX" -p MemorySwapMax=0 -p OOMPolicy=continue -- "$@"; }
OPTS=(-c1 -j1 --rerun-incomplete --rerun-triggers mtime input)   # after the targets (--rerun-triggers takes a list)
cd "$B" || exit 1
echo "######## [prep $R] $(date) ########" >> "$SLOG"

targets=("resources/$R/powerplants.csv")
[ -f "$M/resources/$R/renewable_profiles/profile_hydro.nc" ] && targets+=("resources/$R/renewable_profiles/profile_hydro.nc")
if [ -z "$CHECK" ] && ls "${targets[@]}" >/dev/null 2>&1; then log "done before (${targets[*]} exist), skip"; exit 0; fi

# 1. hardlinks
mkdir -p "resources/$R/bus_regions" "resources/$R/renewable_profiles" "networks/$R"
for e in shapes osm base_network natura.tiff bus_regions/regions_onshore.geojson bus_regions/regions_offshore.geojson \
         renewable_profiles/profile_onwind.nc renewable_profiles/profile_offwind-ac.nc \
         renewable_profiles/profile_offwind-dc.nc renewable_profiles/profile_solar.nc; do
  src="$M/resources/$R/$e"
  [ -e "$src" ] || continue
  [ -L "$src" ] && { log "ABORT: $src is a symlink (expected a real file / directory)"; exit 1; }
  [ -e "resources/$R/$e" ] || cp -al "$src" "resources/$R/$e"
done
log "hardlinked shapes, osm, base_network, natura, regions and wind/solar profiles from the main run"

# 2. base.nc (v0.9.0 base_network); config of the prenetwork stage
$RUN python "$CFG/merge_config.py" prenetwork "$R" "$B/config.yaml" >> "$SLOG" 2>&1 || { log "ABORT: merge_config.py failed, see $SLOG"; exit 1; }
cp config.yaml "logs/catalyst/config.prep_$R.yaml"
if [ ! -f "networks/$R/base.nc" ]; then
  capped $RUN snakemake "networks/$R/base.nc" "${OPTS[@]}" --allowed-rules base_network >> "$SLOG" 2>&1 \
    || { log "ABORT: base_network failed, see $SLOG"; exit 1; }
fi

# 3. same buses as the main base.nc
$RUN python - "networks/$R/base.nc" "$M/networks/$R/base.nc" >> "$SLOG" 2>&1 <<'EOF' || { log "ABORT: buses of base.nc differ from the main run (regions / profiles not reusable), see $SLOG"; exit 1; }
import sys
import numpy as np
import xarray as xr
a, b = (xr.open_dataset(f) for f in sys.argv[1:3])
same = (np.array_equal(a.buses_i.values, b.buses_i.values) and np.allclose(a.buses_x.values, b.buses_x.values)
        and np.allclose(a.buses_y.values, b.buses_y.values))
dc = lambda d: float(d.links_p_nom.values[d.links_carrier.values == "DC"].sum()) / 1e3 if "links_p_nom" in d else 0.0
print(f"buses {a.sizes['buses_i']} vs {b.sizes['buses_i']}, same: {same}; DC link capacity {dc(a):.1f} GW (v0.9.0) vs {dc(b):.1f} GW (main)")
sys.exit(0 if same else 1)
EOF
log "$(tail -1 "$SLOG")"

# 4. mtime of the main base.nc (only ever on the worktree's own file)
[ "$(stat -c %h "networks/$R/base.nc")" = 1 ] || { log "ABORT: networks/$R/base.nc has several links, not touching it"; exit 1; }
touch -d "@$(stat -c %Y "$M/networks/$R/base.nc")" "networks/$R/base.nc"

# 5. dry run: build_powerplants and the hydro profile only
dry=$($RUN snakemake "${targets[@]}" "${OPTS[@]}" -n 2>&1); echo "$dry" >> "$SLOG"
bad=$(echo "$dry" | grep -oP '^(local)?rule \K\w+' | sort -u | grep -vxE 'build_powerplants|build_renewable_profiles')
badprof=$(echo "$dry" | grep -oP 'profile_\K[\w-]+(?=\.nc)' | sort -u | grep -vx hydro)
if [ -n "$bad$badprof" ]; then log "ABORT: dry run would also run: ${bad//$'\n'/ } ${badprof:+profiles: ${badprof//$'\n'/ }}"; exit 1; fi
log "dry run ok: $(echo "$dry" | grep -oP '^(local)?rule \K\w+' | sort | uniq -c | tr -s ' \n' ' ')"
[ -n "$CHECK" ] && exit 0

# 6. build
log "building ${targets[*]} (cap $MEM_MAX)"
capped $RUN snakemake "${targets[@]}" "${OPTS[@]}" --allowed-rules build_powerplants build_renewable_profiles >> "$SLOG" 2>&1 \
  || { log "FAILED: powerplants / hydro, see $SLOG"; exit 1; }
log "SUCCESS ${targets[*]}"
