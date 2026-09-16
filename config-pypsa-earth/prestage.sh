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
PE=""; d="$HERE"; while [ "$d" != "/" ]; do [ -d "$d/models/pypsa-earth" ] && { PE="$d/models/pypsa-earth"; break; }; d="$(dirname "$d")"; done
[ -n "$PE" ] || { echo "models/pypsa-earth not found above $HERE" >&2; exit 1; }
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
  verify_raw() { ( cd "$RAW" && md5sum -c --quiet us-latest.osm.pbf.md5 ) >/dev/null 2>&1; }
  if verify_raw; then
    log "raw PBF already verified, not touching it"
  else
    log "waiting for / running raw PBF download"
    wait_for_wget us-latest.osm.pbf
    # Geofabrik rotates the extract daily: fetch a fresh md5 and, if it differs from
    # the one a partial download was started against, restart instead of resuming.
    ( cd "$RAW" && rm -f us-latest.osm.pbf.md5.new && wget -q --tries=20 --waitretry=30 -O us-latest.osm.pbf.md5.new "$PBF_URL.md5" ) || { log "md5 download failed"; exit 1; }
    if [ -f "$RAW/us-latest.osm.pbf.md5" ] && ! cmp -s "$RAW/us-latest.osm.pbf.md5" "$RAW/us-latest.osm.pbf.md5.new"; then
      log "remote extract rotated since the partial download started -> restarting download"; rm -f "$RAW/us-latest.osm.pbf"
    fi
    mv -f "$RAW/us-latest.osm.pbf.md5.new" "$RAW/us-latest.osm.pbf.md5"
    ( cd "$RAW" && $WGET "$PBF_URL" ) || { log "raw PBF download failed"; exit 1; }
    verify_raw || { log "raw PBF md5 MISMATCH after download - removing raw file, re-run prestage"; rm -f "$RAW/us-latest.osm.pbf" "$RAW/us-latest.osm.pbf.md5"; exit 1; }
  fi
  log "raw PBF verified ($(du -h "$RAW/us-latest.osm.pbf" | cut -f1)); osmium pre-filter (single process, ${MEM_MAX} cap)"
  # earth-osm loads every node of the file into Python dicts (~800 B/node): the
  # full power=* extract of the US (18 M nodes, mostly solar-panel rows mapped as
  # power=generator and distribution poles) blows the 8 GB cap. Keep only what
  # clean_osm_data would keep anyway: line/cable ways with a voltage tag
  # >= threshold_voltage (51 kV), every substation, and generators whose
  # generator:output:electricity is given in MW (prepare_generators_df drops the
  # rest). Referenced nodes are resolved by osmium getid -r. Result: ~5.5 M nodes.
  T="$PBF/tmp"; rm -rf "$T"; mkdir -p "$T"
  OSM="micromamba run -n osmium osmium"
  filt_ok=1
  capped $OSM tags-filter --overwrite --no-progress -o "$T/power4.osm.pbf" "$RAW/us-latest.osm.pbf" nwr/power=substation,line,cable,generator >> "$LOGDIR/prestage.log" 2>&1 || filt_ok=0
  if [ $filt_ok -eq 1 ]; then
    $OSM tags-filter --overwrite --no-progress --omit-referenced -o "$T/tagged.osm.pbf" "$T/power4.osm.pbf" nwr/power=line,cable,substation,generator >> "$LOGDIR/prestage.log" 2>&1 \
    && $OSM cat --overwrite --no-progress -f opl -o "$T/tagged.opl" "$T/tagged.osm.pbf" >> "$LOGDIR/prestage.log" 2>&1 \
    && python3 - "$T/tagged.opl" "$T/keep_ids.txt" "${THRESHOLD_VOLTAGE:-51000}" >> "$LOGDIR/prestage.log" 2>&1 <<'EOF' || filt_ok=0
import re, sys
opl, out, thr = sys.argv[1], sys.argv[2], float(sys.argv[3])
num = re.compile(r"\d+(?:[.,]\d+)?")
def tag(tags, key):
    m = re.search(r"(?:^|,)" + re.escape(key) + r"=([^,]*)", tags)
    return None if m is None else m.group(1).replace("%20", " ").replace("%3b", ";").replace("%3B", ";")
keep, n = [], {"line": 0, "substation": 0, "generator": 0}
with open(opl) as f:
    for line in f:
        oid = line.split(" ", 1)[0]
        tags = line.split(" T", 1)[1].rstrip("\n") if " T" in line else ""
        power = tag(tags, "power")
        if power in ("line", "cable"):
            v = tag(tags, "voltage")
            if v is None: continue
            vals = [float(x.replace(",", ".")) for x in num.findall(v)]
            if "kv" in v.lower(): vals = [x * 1000 if x < 2000 else x for x in vals]
            if vals and max(vals) < thr: continue
            keep.append(oid); n["line"] += 1
        elif power == "substation":
            keep.append(oid); n["substation"] += 1
        elif power == "generator":
            o = tag(tags, "generator:output:electricity")
            if o and "MW" in o.upper():
                keep.append(oid); n["generator"] += 1
open(out, "w").write("\n".join(keep) + "\n")
print(f"prefilter keep: {n} (threshold {thr:.0f} V)")
EOF
  fi
  [ $filt_ok -eq 1 ] && capped $OSM getid --overwrite --no-progress -r -i "$T/keep_ids.txt" -o "$PBF/us-latest.osm.pbf.tmp" "$T/power4.osm.pbf" >> "$LOGDIR/prestage.log" 2>&1 || filt_ok=0
  if [ $filt_ok -eq 1 ]; then
    mv "$PBF/us-latest.osm.pbf.tmp" "$PBF/us-latest.osm.pbf"
    ( cd "$PBF" && md5sum us-latest.osm.pbf > us-latest.osm.pbf.md5 )
    rm -rf "$T"
    log "filtered pbf: $(du -h "$PBF/us-latest.osm.pbf" | cut -f1) ($($OSM fileinfo -e "$PBF/us-latest.osm.pbf" 2>/dev/null | grep -E 'Number of (nodes|ways)' | tr -s ' \n' ' ')); deleting raw 12 GB file"
    rm -f "$RAW/us-latest.osm.pbf"
  else
    log "osmium pre-filter FAILED, see logs/catalyst/prestage.log"; exit 1
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
