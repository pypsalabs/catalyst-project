#!/usr/bin/env bash
# Breadth-first, resumable fetch of the Open-Meteo point-years, each stage followed by a rebuild of the site-years
# dataset and a rerun of the toy model (misc-quarter1/weather-years). Stage k fetches the calibration year plus the
# first YEARS_PER_STAGE*k weather years for EVERY stencil cell, so every location can be run early with few years and
# the number of years grows over time. The free quota is 10,000 call weights per day; a run that hits the daily limit
# fails on that job, the loop sleeps an hour and tries again (one wasted request per attempt). Started with:
#   setsid nohup systemd-inhibit --what=handle-lid-switch:sleep:idle --who=catalyst --why="open-meteo fetch" \
#     bash fetch_and_rebuild.sh > logs/fetch_loop.out 2>&1 &
set -u
cd "$(dirname "$0")"
P=../../models/priam-myopic/.pixi/envs/default/bin/python
S=../../models/priam-myopic/.pixi/envs/default/bin/snakemake
YEARS_PER_STAGE=${YEARS_PER_STAGE:-3}

targets() {   # the point-year files of the calibration year and the first $1 weather years, for every stencil cell
    $P - "$1" <<'PY'
import sys, yaml, pandas as pd
cfg = yaml.safe_load(open("config.yaml"))["siteyears"]
n = int(sys.argv[1])
years = [cfg["calibration_year"]] + list(range(cfg["first"], cfg["last"] + 1))[:n]
pts = pd.read_csv("build/siteyears_points.csv")[["lat", "lon"]].drop_duplicates()
print(" ".join(f"data/openmeteo/pt_{la:.2f}_{lo:.2f}_{y}.csv" for la, lo in pts.itertuples(index=False) for y in years))
PY
}

fetch_until_done() {   # $@ = snakemake targets; retry hourly on the daily quota
    for attempt in $(seq 1 300); do
        echo "=== $(date -Is) fetch attempt $attempt ($# targets)"
        if $S -c1 --rerun-triggers=mtime "$@"; then return 0; fi
        sleep 3600
    done
    return 1
}

rebuild() {
    echo "=== $(date -Is) rebuilding the site-years dataset with the cached years"
    $P build_siteyears.py && $P plot_siteyears_validation.py && $P plot_sites_map.py || return 1
    echo "=== $(date -Is) rerunning the toy model"
    (cd ../toymodel-clean-procurement && $S -c12 --rerun-triggers=mtime) && echo "=== $(date -Is) toy model complete"
}

$S -c1 --rerun-triggers=mtime build/siteyears_points.csv || exit 1
NYEARS=$($P -c "import yaml; c=yaml.safe_load(open('config.yaml'))['siteyears']; print(c['last']-c['first']+1)")
n=$YEARS_PER_STAGE
while true; do
    # shellcheck disable=SC2046
    fetch_until_done $(targets "$n") || exit 1
    rebuild || exit 1
    if [ "$n" -ge "$NYEARS" ]; then echo "=== $(date -Is) all $NYEARS weather years fetched"; exit 0; fi
    n=$((n + YEARS_PER_STAGE)); [ "$n" -gt "$NYEARS" ] && n=$NYEARS
done
