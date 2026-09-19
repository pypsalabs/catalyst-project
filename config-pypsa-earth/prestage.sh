#!/usr/bin/env bash
# Pre-stage the two largest downloads for a pypsa-earth stage so the
# workflow's own downloaders never handle them:
#   bash config-pypsa-earth/prestage.sh <CC>        (CC = US | BR | IN | SG | NWE; default US)
#   1. One Geofabrik <region>-latest.osm.pbf per extract of the stage (US 12 GB, BR 2.1 GB, IN 1.7 GB,
#      SG 0.25 GB via the MY-SG-BN extract, NWE twelve country extracts = 18.6 GB in total, one after
#      the other) -> osmium tags-filter to power features -> data/osm/pbf/<region>-latest.osm.pbf
#      (+ local .md5 so earth-osm accepts it with update=False). Each raw file deleted afterwards.
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
CC="${1:-US}"
case "$CC" in   # Geofabrik extracts per stage, space separated (earth-osm names each file <id>-latest.osm.pbf)
  US) GFS=north-america/us ;;
  BR) GFS=south-america/brazil ;;
  IN) GFS=asia/india ;;
  SG) GFS=asia/malaysia-singapore-brunei ;;   # Geofabrik bundles SG with MY and BN; clean_osm_data keeps only features inside the SG shape
  NWE) GFS="europe/ireland-and-northern-ireland europe/great-britain europe/france europe/belgium europe/netherlands europe/luxembourg
            europe/germany europe/denmark europe/poland europe/czech-republic europe/austria europe/switzerland" ;;   # NI comes with IE
  *) echo "prestage.sh: no Geofabrik mapping for '$CC' (add it to the case list)" >&2; exit 1 ;;
esac
BUNDLE_URL='https://zenodo.org/records/18033571/files/bundle_data_earth.zip?download=1'
RAW="$PE/data/osm/raw-pbf"; PBF="$PE/data/osm/pbf"
WGET="wget -c -q --tries=50 --waitretry=30 --retry-connrefused"

log() { echo "[$(date '+%F %T')] [prestage $CC] $*" | tee -a "$STATUS"; }
free_gb() { df -BG --output=avail "$PE" | tail -1 | tr -dc 0-9; }
disk_guard() { local f; f=$(free_gb); [ "$f" -ge "$MIN_FREE_GB" ] || { log "DISK LOW: ${f} GB free < ${MIN_FREE_GB} GB, abort"; exit 2; }; }
wait_for_wget() { # do not start a second wget on a file another wget is writing
  while pgrep -f "wget .*$1" >/dev/null 2>&1; do sleep 60; done; }
capped() { systemd-run --user --scope --quiet -p "MemoryMax=$MEM_MAX" -p MemorySwapMax=0 -- "$@"; }

cd "$PE" || exit 1
mkdir -p "$RAW" "$PBF"

# ---- 1. OSM ---------------------------------------------------------------
prestage_osm() {   # $1 = Geofabrik path (e.g. europe/germany); idempotent per extract
local GF="$1" STEM PBF_URL T OSM filt_ok rc
STEM="$(basename "$GF")-latest.osm.pbf"
PBF_URL="https://download.geofabrik.de/$GF-latest.osm.pbf"
if [ -s "$PBF/$STEM" ] && [ -s "$PBF/$STEM.md5" ]; then
  log "$STEM: filtered OSM pbf present ($(du -h "$PBF/$STEM" | cut -f1)), skip"
else
  disk_guard
  # compare hashes only: some Geofabrik md5 files name the dated file (germany-260918.osm.pbf), so md5sum -c cannot find it
  verify_raw() { [ -s "$RAW/$STEM" ] && [ -s "$RAW/$STEM.md5" ] && [ "$(md5sum < "$RAW/$STEM" | cut -d' ' -f1)" = "$(cut -d' ' -f1 "$RAW/$STEM.md5")" ]; }
  if verify_raw; then
    log "$STEM: raw PBF already verified, not touching it"
  else
    log "$STEM: waiting for / running raw PBF download"
    wait_for_wget $STEM
    # Geofabrik rotates the extract daily: fetch a fresh md5 and, if it differs from
    # the one a partial download was started against, restart instead of resuming.
    ( cd "$RAW" && rm -f $STEM.md5.new && wget -q --tries=20 --waitretry=30 -O $STEM.md5.new "$PBF_URL.md5" ) || { log "$STEM: md5 download failed"; return 1; }
    if [ -f "$RAW/$STEM.md5" ] && ! cmp -s "$RAW/$STEM.md5" "$RAW/$STEM.md5.new"; then
      log "$STEM: remote extract rotated since the partial download started -> restarting download"; rm -f "$RAW/$STEM"
    fi
    mv -f "$RAW/$STEM.md5.new" "$RAW/$STEM.md5"
    ( cd "$RAW" && $WGET "$PBF_URL" ) || { log "$STEM: raw PBF download failed"; return 1; }
    verify_raw || { log "$STEM: raw PBF md5 MISMATCH after download - removing raw file, re-run prestage"; rm -f "$RAW/$STEM" "$RAW/$STEM.md5"; return 1; }
  fi
  log "$STEM: raw PBF verified ($(du -h "$RAW/$STEM" | cut -f1)); osmium pre-filter (single process, ${MEM_MAX} cap)"
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
  capped $OSM tags-filter --overwrite --no-progress -o "$T/power4.osm.pbf" "$RAW/$STEM" nwr/power=substation,line,cable,generator >> "$LOGDIR/prestage.log" 2>&1 || filt_ok=0
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
  if [ $filt_ok -eq 1 ]; then
    # osmium getid exits 1 when some requested ids are absent from the input (Germany: 68 power=line
    # relations dropped by --omit-referenced) although the output is complete; only rc >= 2 is an error
    capped $OSM getid --overwrite --no-progress -f pbf -r -i "$T/keep_ids.txt" -o "$PBF/$STEM.tmp" "$T/power4.osm.pbf" >> "$LOGDIR/prestage.log" 2>&1
    rc=$?; { [ $rc -le 1 ] && [ -s "$PBF/$STEM.tmp" ]; } || filt_ok=0
  fi
  if [ $filt_ok -eq 1 ]; then
    mv "$PBF/$STEM.tmp" "$PBF/$STEM"
    ( cd "$PBF" && md5sum $STEM > $STEM.md5 )
    rm -rf "$T"
    log "$STEM: filtered pbf $(du -h "$PBF/$STEM" | cut -f1) ($($OSM fileinfo -e "$PBF/$STEM" 2>/dev/null | grep -E 'Number of (nodes|ways)' | tr -s ' \n' ' ')); deleting raw file"
    rm -f "$RAW/$STEM"
  else
    log "$STEM: osmium pre-filter FAILED, see logs/catalyst/prestage.log"; return 1
  fi
fi
return 0
}
for GF in $GFS; do prestage_osm "$GF" || exit 1; done

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
