#!/usr/bin/env bash
# Pre-stage the two largest downloads for the CONUS pypsa-earth run so the
# workflow's own downloaders never handle them:
#   1. Geofabrik us-latest.osm.pbf (12 GB) -> osmium tags-filter to power features
#      -> data/osm/pbf/us-latest.osm.pbf (+ local .md5 so earth-osm accepts it
#      with update=False). Raw file deleted afterwards.
#   2. Zenodo bundle_data_earth.zip (6.5 GB) -> models/pypsa-earth/tempfile.zip;
#      the patched retrieve_databundle_light resumes/skips it with wget -c.
# Idempotent and resumable; safe to re-run. Never runs two wgets on one file.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PE="$(cd "$HERE/../../models/pypsa-earth" && pwd)"
LOGDIR="$PE/logs/catalyst"; mkdir -p "$LOGDIR"
STATUS="$LOGDIR/status.log"
MIN_FREE_GB=${MIN_FREE_GB:-20}
MEM_MAX=${MEM_MAX:-8G}
PBF_URL=https://download.geofabrik.de/north-america/us-latest.osm.pbf
BUNDLE_URL='https://zenodo.org/records/18033571/files/bundle_data_earth.zip?download=1'
RAW="$PE/data/osm/raw-pbf"; PBF="$PE/data/osm/pbf"
WGET="wget -c -q --tries=50 --waitretry=30 --retry-connrefused"

log() { echo "[$(date '+%F %T')] [prestage] $*" | tee -a "$STATUS"; }
free_gb() { df -BG --output=avail "$PE" | tail -1 | tr -dc 0-9; }
disk_guard() { local f; f=$(free_gb); [ "$f" -ge "$MIN_FREE_GB" ] || { log "DISK LOW: ${f} GB free < ${MIN_FREE_GB} GB, abort"; exit 2; }; }
wait_for_wget() { # do not start a second wget on a file another wget is writing
  while pgrep -f "wget .*$1" >/dev/null 2>&1; do sleep 60; done; }
capped() { systemd-run --user --scope --quiet -p "MemoryMax=$MEM_MAX" -p MemorySwapMax=0 -- "$@"; }

cd "$PE" || exit 1
mkdir -p "$RAW" "$PBF"

# ---- 1. OSM ---------------------------------------------------------------
if [ -s "$PBF/us-latest.osm.pbf" ] && [ -s "$PBF/us-latest.osm.pbf.md5" ]; then
  log "filtered OSM pbf present ($(du -h "$PBF/us-latest.osm.pbf" | cut -f1)), skip"
else
  disk_guard
  log "waiting for / running raw PBF download"
  wait_for_wget us-latest.osm.pbf
  ( cd "$RAW" && $WGET "$PBF_URL.md5" && $WGET "$PBF_URL" ) || { log "raw PBF download failed"; exit 1; }
  ( cd "$RAW" && md5sum -c --quiet us-latest.osm.pbf.md5 ) || { log "raw PBF md5 MISMATCH (Geofabrik rotated the file?) - removing raw file, re-run prestage"; rm -f "$RAW/us-latest.osm.pbf" "$RAW/us-latest.osm.pbf.md5"; exit 1; }
  log "raw PBF verified ($(du -h "$RAW/us-latest.osm.pbf" | cut -f1)); osmium tags-filter nwr/power (single process, ${MEM_MAX} cap)"
  rm -f "$PBF/us-latest.osm.pbf.tmp"
  if capped micromamba run -n osmium osmium tags-filter --overwrite --progress=false \
        -o "$PBF/us-latest.osm.pbf.tmp" -f pbf "$RAW/us-latest.osm.pbf" nwr/power >> "$LOGDIR/prestage.log" 2>&1; then
    mv "$PBF/us-latest.osm.pbf.tmp" "$PBF/us-latest.osm.pbf"
    ( cd "$PBF" && md5sum us-latest.osm.pbf > us-latest.osm.pbf.md5 )
    log "filtered pbf: $(du -h "$PBF/us-latest.osm.pbf" | cut -f1); deleting raw 12 GB file"
    rm -f "$RAW/us-latest.osm.pbf"
  else
    log "osmium tags-filter FAILED (rc=$?), see logs/catalyst/prestage.log"; exit 1
  fi
fi

# ---- 2. Zenodo bundle -----------------------------------------------------
if [ -d "$PE/data/gebco" ] && [ -d "$PE/data/copernicus" ]; then
  log "bundle_data_earth already extracted, skip"
else
  disk_guard
  log "waiting for / running bundle_data_earth.zip download"
  wait_for_wget tempfile.zip
  $WGET -O "$PE/tempfile.zip" "$BUNDLE_URL" || { log "bundle download failed (rc=$?), the workflow rule will resume it"; }
  if unzip -tq "$PE/tempfile.zip" >/dev/null 2>&1; then
    log "tempfile.zip complete and valid ($(du -h "$PE/tempfile.zip" | cut -f1)); retrieve_databundle_light will reuse it"
  else
    log "tempfile.zip incomplete/corrupt; removing so the workflow re-downloads"; rm -f "$PE/tempfile.zip"
  fi
fi
log "done; free $(free_gb) GB"
