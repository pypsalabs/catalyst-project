# `config-pypsa-earth/` — how the PyPSA-Earth soft fork is run (currently: CONUS prenetwork, WP1 pipeline test)

Builds a **power-only PyPSA-Earth model of the contiguous United States up to the
`prepare_network` output** ("prenetwork", not solved), as the first end-to-end exercise
of the global data pipeline the SOW prescribes (SOW §methodology: PyPSA-Earth soft fork,
atlite/ERA5 feed-in). Everything runs under three constraints: **≤ 8 GB RAM for the whole
process tree, no Snakemake parallelism (`-c1 -j1`), and a bounded disk footprint**.

The model code lives in `models/pypsa-earth` (gitignored here): a clone of
`pypsa-meets-earth/pypsa-earth`, branch **`catalyst`** = tag v0.9.0 plus four small patches
(`git log v0.9.0..catalyst`):

| patch | why |
|---|---|
| `build_shapes`: optional `build_shape_options.clip_bbox` | clips country/offshore/GADM shapes to a box. Alaska's Aleutians cross the antimeridian, so its bounding box in the 100 m exclusion raster spans the globe; this is what OOM-killed the full-US `build_renewable_profiles` (20–24 GB) in July 2026. |
| `download_osm_data`: honour `download_osm_data_nprocesses` | earth-osm otherwise parses the PBF with `cpu_count-1` = 15 workers. |
| `retrieve_databundle_light`: `wget -c` for Zenodo | the 6.5 GB `bundle_data_earth.zip` resumes instead of restarting. |
| `build_cutout`: `monthly_requests=True, concurrent_requests=False` | small, sequential CDS requests. |

## Files

- `config.US-smoke.yaml` — stage A: January 2013, run name `US-smoke`, cutout `cutout-2013-era5-conus-jan`.
- `config.US.yaml` — stage B: full year 2013, run name `US`, cutout `cutout-2013-era5-conus`.
  Both are diffs over `config.default.yaml` (Snakemake deep-merges `config.yaml`); the driver
  copies the active one to `models/pypsa-earth/config.yaml`. Common settings: `countries: [US]`,
  50 clusters, `simpl ""`, `ll copt`, `opts Co2L`, carriers solar/onwind/offwind-ac/offwind-dc/hydro,
  `clip_bbox [-125, 24, -66.5, 50]`, cutout bounds the same box at 0.3°, `gdp_method: false`,
  `atlite.nprocesses: 1`, `build_shape_options.nprocesses: 1`, no prebuilt cutout.
- `prestage.sh` — pre-downloads the two largest inputs outside the workflow: the 12 GB Geofabrik
  `us-latest.osm.pbf` is tag-filtered to `nwr/power` with `osmium tags-filter` (micromamba env
  `osmium`) into `data/osm/pbf/us-latest.osm.pbf` with a local `.md5`, so earth-osm (which reuses an
  existing PBF + local md5 when `update=False`) never touches the raw file; the raw file is deleted.
  `bundle_data_earth.zip` is fetched to `models/pypsa-earth/tempfile.zip`, which the patched rule resumes.
- `run_us.sh [prestage] [US-smoke] [US]` — the supervisor (default: all three, in order). Each stage runs
  `pixi run snakemake networks/<run>/elec_s_50_ec_lcopt_Co2L.nc -c1 -j1 --rerun-incomplete` inside
  `systemd-run --user --scope -p MemoryMax=8G -p MemorySwapMax=0` (a real cgroup cap; the kernel kills
  the offending job, Snakemake reports it), with BLAS/OMP threads pinned to 1, a 20 h wall-clock cap,
  a disk watchdog (stops below 15 GB free), and retries (3×, 120 s) only when a network/data rule
  failed — never after an OOM. Peak memory of the scope is written to the log (`SCOPE memory.peak=`).

Logs: `models/pypsa-earth/logs/catalyst/status.log` (one line per event), `<stage>.log` (full
Snakemake output), `prestage.log`, `driver.out`.

```bash
# from the repo root; detach so it survives the terminal
setsid nohup bash config-pypsa-earth/run_us.sh > models/pypsa-earth/logs/catalyst/driver.out 2>&1 &
tail -f models/pypsa-earth/logs/catalyst/status.log
# re-run a single stage (targets that exist are skipped; Snakemake resumes)
bash config-pypsa-earth/run_us.sh US
```

## Caveats (screening-grade run, not study results)

- **CONUS only**: Alaska, Hawaii and the Pacific territories are clipped away; the EEZ is cut to the
  same box, so offshore wind regions end at 125°W / 66.5°W.
- `gdp_method: false` — GADM regions carry population but no GDP (only used when clusters are
  distributed by GDP; we distribute by load).
- Cost data are the generic technology-data set (`costs.country_specific_data: ""`), not the US-specific
  ATB-derived one pypsa-earth also offers; the study's own cost baseline is in `misc-quarter1/technology-costs`.
- Weather year 2013 (pypsa-earth default), hourly, no time segmentation; demand from the SSP2-2.6
  GEGIS dataset; grid topology from OSM (`us-latest` of 2026-09-15, filtered to `power=*`).
- `cluster_network` needs a MIQP solver to distribute clusters over synchronous zones; Gurobi via
  `~/gurobi.lic` (scip in the env is the fallback).
- The full-US-including-Alaska model is not attempted; if it is needed later, `clip_bbox` can be
  dropped, but `build_renewable_profiles` then needs far more than 8 GB.
