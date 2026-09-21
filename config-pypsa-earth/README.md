# `config-pypsa-earth/` — how the PyPSA-Earth soft fork is run (CONUS, Brazil, India, Singapore and North-West/Central Europe prenetworks + screening solves, WP1 pipeline test)

Builds **power-only PyPSA-Earth models up to the `prepare_network` output** ("prenetwork",
not solved), one country (or country group) per stage, as the end-to-end exercise of the global data pipeline the
SOW prescribes (SOW §methodology: PyPSA-Earth soft fork, atlite/ERA5 feed-in). Done: the
contiguous United States (`US`, 2026-09-16), Brazil (`BR`, the hydro-rich archetype,
2026-09-17) India (`IN`, the fossil-heavy archetype next to US East, 2026-09-18) and Singapore (`SG`, the islanded
archetype of the kickoff slides, 2026-09-18, a single node); North-West and Central Europe (`NWE`, twelve
countries, the dense / renewables-constrained archetype, 2026-09-19) is the first multi-country stage and
reuses the PyPSA-Eur 2013 cutout found on this machine. Since 2026-09-19 the same driver also solves two
screening scenarios per region ("current system" and "carbon-neutral", see the last section) and renders one
validation dashboard per region. Everything runs under three constraints: **≤ 8 GB RAM for the whole
process tree, no Snakemake parallelism (`-c1 -j1`), and a bounded disk footprint**.

The model code lives in `models/pypsa-earth` (gitignored here): a clone of the soft fork
`pypsalabs/catalyst-pypsa-earth` (GitHub fork of `pypsa-meets-earth/pypsa-earth`; remote `origin`
is the fork, `upstream` is pypsa-meets-earth), branch **`catalyst`** = tag v0.9.0 plus nine small
patches (`git log v0.9.0..catalyst`). Commit subjects carry an upstream tag: `(upstream candidate)` marks a bug fix to
propose to pypsa-meets-earth, `(no relevance 4 upstream)` a fork-only change:

| patch | why |
|---|---|
| `build_shapes`: optional `build_shape_options.clip_bbox` | clips country/offshore/GADM shapes to a box. Alaska's Aleutians cross the antimeridian, so its bounding box in the 100 m exclusion raster spans the globe; this is what OOM-killed the full-US `build_renewable_profiles` (20–24 GB) in July 2026. |
| `download_osm_data`: honour `download_osm_data_nprocesses` | earth-osm otherwise parses the PBF with `cpu_count-1` = 15 workers. |
| `retrieve_databundle_light`: `wget -c` for Zenodo | the 6.5 GB `bundle_data_earth.zip` resumes instead of restarting. |
| `build_cutout`: `monthly_requests=True, concurrent_requests=False` | small, sequential CDS requests. |
| `base_network`: drop branch WKT geometry before the netCDF export | netCDF stores strings fixed-width: one 59k-character line geometry made `base.nc` load as ~10 GB (`process_cost_data` was OOM-killed). Geometries stay in `resources/base_network/*.geojson`. |
| `build_demand_profiles`: population-only fallback when shapes carry no `gdp` | `gdp_method: false` otherwise raises `KeyError: 'gdp'`. |
| `simplify_network`: memory-lean one-port aggregation (`_helpers.aggregateoneport_lean`) | PyPSA's `aggregateoneport` expands each time series to a dense (snapshots × components) frame and copies it ~5 times (selection, weighting, transposed groupby, concat); with 13k per-bus profile columns over 8760 h (1.3 GB network) `simplify_links` peaked above 8 GB. The lean version evaluates the linear strategies as one sparse matrix product on the existing series (peak ≈ network + one result); verified equal to PyPSA to 1e-10 on the smoke network. Candidate for PyPSA itself. |
| `simplify_network`: absorb the DC buses left after `simplify_links` (`absorb_dc_buses`) | OSM-derived HVDC data leaves DC buses that `simplify_links` cannot fold (converter stations that also carry load or generators, cable stubs ending at a DC bus without a converter, isolated substations tagged DC). Each is its own sub-network and claims a cluster: the first NWE run had 18 DC buses among its 50 "clusters" and only 32 AC nodes. Every remaining DC bus is mapped onto the AC bus of its B2B converter, else onto the nearest AC bus of the same country; the converters become self-loops and are dropped, the DC links connect AC buses directly. |
| `base_network`: tolerate an empty lines table | a country with no OSM line above `threshold_voltage` (Singapore: the 230 / 400 kV cables are underground and unmapped) imports zero lines; PyPSA then has no `under_construction` / `v_nom` column and the rule raised `KeyError`. Two guards. |

## Files

- `config.US-smoke.yaml` — stage A: January 2013, run name `US-smoke`, cutout `cutout-2013-era5-conus-jan`.
- `config.US.yaml` — stage B: full year 2013, run name `US`, cutout `cutout-2013-era5-conus`.
- `config.BR-smoke.yaml`, `config.BR.yaml` — the same pair for Brazil (`countries: [BR]`, cutouts
  `cutout-2013-era5-brazil[-jan]` over `x [-74.5, -31.0] y [-34.5, 6.0]`, `clip_bbox` the same box,
  `threshold_voltage: 200000` = the ONS "Rede Básica"); see the Brazil caveats below.
- `config.IN-smoke.yaml`, `config.IN.yaml` — the same pair for India (`countries: [IN]`, cutouts
  `cutout-2013-era5-india[-jan]` over `x [65.5, 98.0] y [4.5, 37.5]` = GADM India plus the mainland EEZ,
  `clip_bbox` the same box, `threshold_voltage: 200000` keeps 765 / 400 / 220 kV); see the India section below.
- `config.SG-smoke.yaml`, `config.SG.yaml` — Singapore (`countries: [SG]`, cutouts `cutout-2013-era5-singapore[-jan]`
  over `x [103.0, 104.7] y [0.6, 2.0]`, 6 × 5 cells, no hydro, `clusters: [1]` with
  `cluster_options.simplify_network.p_threshold_merge_isolated: 1000000` and `p_threshold_drop_isolated: false`
  so the isolated substations merge into one bus); see the Singapore section below.
- `config.NWE.yaml` — North-West and Central Europe, a single stage (`countries: [AT, BE, CH, CZ, DE, DK, FR, GB,
  IE, LU, NL, PL]`, 50 clusters, `threshold_voltage: 200000` = 220 / 275 / 380 / 400 kV, `clip_bbox [-12, 41, 25, 61.5]`,
  cutout `europe-2013-sarah3-era5` = the PyPSA-Eur cutout hardlinked into `cutouts/`, `build_cutout: false`);
  no `-smoke` pair because nothing is built via CDS; see the Europe section below.
- `config.CN-smoke.yaml`, `config.CN.yaml` — China (`countries: [CN]`, 50 clusters, `threshold_voltage: 200000`
  = 220 / 330 / 500 / 750 / 1000 kV, `clip_bbox [73.5, 15.0, 135.0, 54.0]`, cutouts `cutout-2013-era5-china[-jan]`
  **cropped from the pypsa-earth Asia cutout** with `crop_cutout.py` instead of built via CDS, `build_cutout: false`,
  plus `s_threshold_fetch_isolated: 0.05` as for NWE); see the China section below.
- `crop_cutout.py` — cut an existing atlite cutout down to a lon/lat box (and optionally a time window),
  streaming through dask under a memory cap: `pixi run python ../../config-pypsa-earth/crop_cutout.py SRC OUT
  --x 73.5 135.0 --y 15.0 54.0 [--time T0 T1]`. Written for China; it also repairs the NaN-column defect of the
  continental pypsa-earth cutouts (see the China section).
- `overlay.now.yaml`, `overlay.zero.yaml` — the two screening scenarios as small diffs applied *on top of* a stage
  config: `run.sh <R>-now` / `<R>-zero` deep-merges `config.<R>.yaml` with the overlay (`merge_config.py`, which also
  prints the stage target and writes the merged file to `models/pypsa-earth/config.yaml` and
  `logs/catalyst/config.<stage>.yaml`). `now`: `ll copt`, `opts 3h` (no CO2 constraint, 3-hourly averaging), `costs.year 2025`; `zero`:
  `opts Co2L0-3h` (CO2 limit 0), `costs.year 2050`; both `build_cutout: false`, Gurobi 8 threads and the validation rules
  below. Hourly was tried first (BR: 19.0 M rows × 9.3 M columns, OOM in Gurobi's presolve under the 12 GB cap);
  3-hourly is pypsa-earth's own default (`opts: [Co2L-3h]`). Everything else (countries, cutout, thresholds, clustering, default extendables) is the base stage's.
- `validation.smk` + `scripts/plot_validation.py` — the validation dashboard, wired into the fork through its
  `custom_rules` config key (path `../../config-pypsa-earth/validation.smk` relative to the fork root, so the fork
  itself is untouched): rule `plot_validation` draws one 16:9 block per solved network
  (`results/<run>/plots/validation_<stem>.png`), rule `validation_dashboard` one 16:9 page per region with the
  `now` block left and the `zero` block right (`results/catalyst/validation_<R>.png`). Ten tiles per block:
  generation mix, installed capacity (hatched = added by the optimiser), price statistics (load-weighted duration
  curve, band across buses, stats box top right, CO2 shadow price), annual demand per country + load shedding,
  a third row with CO2 by carrier, curtailment and the fuel prices the model assumes (the `fuel` column of the run's
  `costs_<year>_elec.csv`, EUR/MWh thermal, with published 2024 markers / 2050 outlook assumptions as dots), and a
  bottom row with system cost (existing-fleet annuity / new build / transmission / operation; the shedding penalty is
  listed but not added), summary tile and an untitled map of the clustered network (nodes sized by annual load, AC
  lines by optimised capacity, HVDC links purple; extent and grey fill = the run's `country_shapes.geojson`, i.e. the
  modelled connected part such as CONUS; cartopy 50m coastlines/borders). Generation, capacity and emission bars are grouped into validation
  carriers (gas = CCGT|OCGT, wind = on|offAC|offDC, ...; the segment order is in the tick label) and carry
  **validation dots** (one colour/marker per source, legend under the block title); the price tile shows
  published annual averages as dashed levels. Standalone:
  `pixi run python ../../config-pypsa-earth/scripts/plot_validation.py A.nc [B.nc] --points validation_points.csv -o out.png`.
- `scripts/build_validation.py` + `data/validation/` — the validation points (rules `retrieve_validation_data`,
  `build_validation_points` in `validation.smk` → `resources/catalyst/validation_points.csv`). Sources: Ember
  yearly data and European wholesale prices (downloaded), IRENA (the fork's databundle copy), the Energy Institute
  Statistical Review 2025 workbook (Cloudflare-gated, fetched once with a browser and kept in the repo), ECB annual FX,
  and `data/validation/manual_points.csv` with cited national statistics, prices and 2050 outlooks. See
  "Validation data" below.
- `check_network.py <run>` — sanity table + map for a finished stage
  (`cd models/pypsa-earth && pixi run python ../../config-pypsa-earth/check_network.py BR`);
  writes `results/catalyst/<run>_map.png`.
  All configs are diffs over `config.default.yaml` (Snakemake deep-merges `config.yaml`); the driver
  copies the active one to `models/pypsa-earth/config.yaml`. Common settings: `countries: [US]`,
  50 clusters, `simpl ""`, `ll copt`, `opts Co2L`, carriers solar/onwind/offwind-ac/offwind-dc/hydro,
  `clip_bbox [-125, 24, -66.5, 50]`, cutout bounds the same box at 0.3°,
  `osm.clean_osm_data.threshold_voltage: 200000` (the 230 kV+ backbone: 61k lines / 6.5k base buses;
  at the 51 kV default the US has 30k buses and the per-bus availability matrices in
  `build_renewable_profiles` need >8 GB), `gdp_method: standard` for stage B (`false` + the
  population fallback for the smoke stage, to avoid re-running the shape chain),
  `atlite.nprocesses: 1`, `build_shape_options.nprocesses: 1`, no prebuilt cutout.
- `prestage.sh <CC>` — pre-downloads the two largest inputs outside the workflow (one or more Geofabrik
  extracts per stage in a small case list: `US`, `BR`, `IN`, `SG`, `NWE` = twelve country extracts, 18.6 GB in
  total, filtered one after the other, each raw file deleted before the next download). The 12 GB Geofabrik `us-latest.osm.pbf` (2.1 GB for Brazil, 1.7 GB for India,
  0.25 GB for Singapore, which Geofabrik ships inside `malaysia-singapore-brunei`; pypsa-earth's `iso_to_geofk_dict` maps SG to it and
  `clean_osm_data` keeps only features inside the SG shape) is reduced with `osmium` (micromamba env `osmium`) to what `clean_osm_data` would
  keep anyway: line/cable ways with a voltage tag >= 51 kV, all substations, and generators whose
  `generator:output:electricity` is in MW (US OSM has ~1.9 M `power=generator` ways, mostly solar-panel
  rows in W/kW, and millions of poles; earth-osm holds every node in Python dicts at ~800 B each, so the
  full power extract with 18 M nodes blew the 8 GB cap). Result: 44 MB, 5.5 M nodes, written to
  `data/osm/pbf/us-latest.osm.pbf` with a local `.md5` so earth-osm (which reuses an existing PBF +
  local md5 when `update=False`) never touches the raw file; the raw file is deleted. A verified raw file
  is never resumed with `wget -c` (Geofabrik rotates the extract daily; resuming across a rotation
  corrupts it).
  `bundle_data_earth.zip` is fetched to `models/pypsa-earth/tempfile.zip`, which the patched rule resumes.
- `run.sh [prestage:<CC>] [<stage> ...]` — the supervisor (default `prestage:US US-smoke US`). Stage kinds: a bare
  `<stage>` builds the prenetwork of `config.<stage>.yaml` (`prestage:BR BR-smoke BR`); `<R>-now` / `<R>-zero` solve a
  screening scenario of region `R` (overlay merge, `resources/<R>-<scen>` symlinked to `resources/<R>` and
  `networks/<R>-<scen>/base.nc` hardlinked, so only `add_electricity` → `solve_network` → `plot_validation` run:
  3–5 min of rebuild plus the solve); `dashboard:<R>` renders the region page from the two solved networks.
  `CONTINUE_ON_FAIL=1` goes on with the next stage after a failure (overnight queues), `MEM_MAX` sets the cgroup cap
  (`8G` default, `12G`–`14G` for solves), `STAGE_TIMEOUT` the wall-clock cap per stage. Each stage runs
  `pixi run snakemake <target> -c1 -j1 --rerun-incomplete --rerun-triggers mtime input`
  (target derived from the first entry of every `scenario` list; rules re-run only for missing or outdated
  outputs, never because their params/code provenance changed: the NWE stage otherwise re-ran `retrieve_databundle_light`
  over the read-only shared `data/` files although the bundle list was unchanged; after a script or config change
  delete the affected outputs by hand) inside
  `systemd-run --user --scope -p MemoryMax=8G -p MemorySwapMax=0` (a real cgroup cap; the kernel kills
  the offending job, Snakemake reports it), with BLAS/OMP threads pinned to 1, a 20 h wall-clock cap,
  a disk watchdog (stops below 15 GB free), and retries (3×, 120 s) only when a network/data rule
  failed — never after an OOM. Peak memory of the scope is written to the log (`SCOPE memory.peak=`).
  The scope runs with `OOMPolicy=continue` so an OOM-killed job is reported by Snakemake instead of
  taking the whole scope down. Once a stage's cutout file exists the driver flips `build_cutout: false`
  in the generated `config.yaml` (pypsa-earth's `terminate_if_cutout_exists` otherwise aborts every
  later run of that stage). Scripts locate `models/pypsa-earth` by walking up from their own directory.

Logs: `models/pypsa-earth/logs/catalyst/status.log` (one line per event), `<stage>.log` (full
Snakemake output), `prestage.log`, `driver.out`.

```bash
# from the repo root; detach so it survives the terminal, and keep the laptop awake while locked
setsid nohup systemd-inhibit --what=handle-lid-switch:sleep:idle --who=catalyst --why="pypsa-earth run" \
  bash config-pypsa-earth/run.sh prestage:BR BR-smoke BR > models/pypsa-earth/logs/catalyst/driver.out 2>&1 &
tail -f models/pypsa-earth/logs/catalyst/status.log
# re-run a single stage (targets that exist are skipped; Snakemake resumes)
bash config-pypsa-earth/run.sh US
# screening solves + dashboards for all regions, overnight, going on after a failed stage
CONTINUE_ON_FAIL=1 MEM_MAX=12G STAGE_TIMEOUT=4h setsid nohup systemd-inhibit --what=handle-lid-switch:sleep:idle \
  --who=catalyst --why="screening solves" bash config-pypsa-earth/run.sh SG-now SG-zero dashboard:SG BR-now BR-zero dashboard:BR \
  IN-now IN-zero dashboard:IN NWE-now NWE-zero dashboard:NWE US-now US-zero dashboard:US > models/pypsa-earth/logs/catalyst/driver.out 2>&1 &
(nohup eog models/pypsa-earth/results/catalyst/validation_*.png >/dev/null 2>&1 &)
```

## Caveats (screening-grade run, not study results)

- **CONUS only**: Alaska, Hawaii and the Pacific territories are clipped away; the EEZ is cut to the
  same box, so offshore wind regions end at 125°W / 66.5°W.
- **>= 230 kV backbone only** (`threshold_voltage: 200000`), the PyPSA-Eur convention (220 kV). Lowering
  to 100 kV gives 20k base buses and needs a memory-lean availability matrix (chunked float32/sparse) to
  fit 8 GB; not done.
- Demand is the SSP2-2.6 **2030** projection of the GEGIS dataset (pypsa-earth default
  `load_options`), ~590 GW mean in January, above today's ~470 GW; distributed to buses by 0.6 GDP +
  0.4 population (stage B) or population only (smoke stage).
- Run history (2026-09-16): stage A took ~6 h wall clock including four fixes found on the way (osmium
  flag, OSM pre-filter scope, fixed-width geometry strings, GDP column, voltage threshold); peak
  memory of the successful stage-A run 5.9 GB. Stage B (full 2013) ran 16:38–21:37: build_cutout
  ~3 h (12 sequential monthly CDS requests, 5.0 GB), the five profile rules ~35 min, one OOM in
  `simplify_network` (fixed by the lean-aggregation patch, relaunch 21:34, done 3 min later);
  process peak < 6 GB (the scope's 8 GB `memory.peak` is reclaimable page cache from writing the
  1.1 GB `elec_s.nc`, zero `oom_kill` events). Result `networks/US/elec_s_50_ec_lcopt_Co2L.nc`
  (19 MB): 47 AC buses, 80 lines / 825 GW, 8760 snapshots, 49 solar + 49 onwind + 19 + 19 offwind
  profiles (mean CF 0.15 / 0.21 / 0.32 / 0.33), 42 hydro units with 208 TWh inflow, load 4,649 TWh
  (mean 531 GW, peak 695 GW). Map: `results/catalyst/US_map.png`. Intermediate files
  `networks/US/elec.nc` (1.4 GB) and `elec_s.nc` (1.1 GB) can be deleted if disk gets tight.
- Cost data are the generic technology-data set (`costs.country_specific_data: ""`), not the US-specific
  ATB-derived one pypsa-earth also offers; the study's own cost baseline is in `misc-quarter1/technology-costs`.
- Weather year 2013 (pypsa-earth default), hourly, no time segmentation; demand from the SSP2-2.6
  GEGIS dataset; grid topology from OSM (`us-latest` of 2026-09-15, filtered to `power=*`).
- `cluster_network` needs a MIQP solver to distribute clusters over synchronous zones; Gurobi via
  `~/gurobi.lic` (scip in the env is the fallback).
- The full-US-including-Alaska model is not attempted; if it is needed later, `clip_bbox` can be
  dropped, but `build_renewable_profiles` then needs far more than 8 GB.

## Brazil (stages `BR-smoke`, `BR`)

Same recipe as CONUS: 230 kV+ backbone (`threshold_voltage: 200000`, which is how ONS defines the
Rede Básica; 138 kV subtransmission is absent, so isolated 138 kV pockets become stubs or are dropped
by the `p_threshold_drop_isolated` 20 MW / `p_threshold_merge_isolated` 300 MW defaults), 50 clusters,
weather year 2013, carriers solar / onwind / offwind-ac / offwind-dc / hydro, cutout built via CDS
(0.3°, `x [-74.5, -31.0] y [-34.5, 6.0]`, 145 × 135 cells ≈ 5.5 GB). `clip_bbox` uses the same box:
mainland Brazil and Fernando de Noronha stay, the EEZ lobes around Trindade / Martim Vaz and
St Peter & Paul (out to 26°W) are dropped, so offshore regions end at 31°W.

- Hydro is atlite runoff over HydroBASINS level 6 (`hybas_sa`) rescaled to IRENA 2023 generation × 1.1
  (pypsa-earth default), with reservoir energy from `hydro_max_hours_default` 6 h unless
  powerplantmatching supplies it. That is far too small for Brazil's multi-year reservoirs; a WP2 fix with
  ONS reservoir data is needed before the myopic runs. Flagged here, not solved.
- Demand: GEGIS SSP2-2.6 2030 projection, GDP + population weighted; generic technology-data costs.
- Brazil is one synchronous system (SIN) plus small isolated systems in the North; the cluster
  distribution MIQP (Gurobi) handles the sub-networks.
- The July 2026 artefacts in `models/networks/` (`Brazil.config.yaml`, v0.8.0, 400flex clusters at 51 kV;
  `Brazil.giant.html`, 392 nodes / 820 lines) are not inputs to this run. Their popup totals serve as an
  order-of-magnitude cross-check: peak load 118 GW, onwind p_nom_max 17.0 TW, solar 13.6 TW,
  offwind-ac 0.33 TW, offwind-dc 0.62 TW.
- No biomass, although `biomass` is in the default `conventional_carriers` and
  `resources/BR/powerplants.csv` holds 403 solid-biomass plants (13.5 GW, mostly bagasse) plus 0.2 GW
  biogas: `add_electricity` maps the powerplantmatching fuel type `Bioenergy` to `biomass`, but the
  powerplantmatching version in the pixi env labels them `Solid Biomass` / `Biogas`, so they are
  silently dropped (same would happen for the US). The existing fleet in the prenetwork is therefore
  CCGT 20.6, oil 8.5, coal 3.4, nuclear 2.0 (Angra 1+2) and ror 40 GW. Upstream-candidate fix for the
  fork (extend the fuel-type map in `add_electricity.py`); needed before WP2.
- Wind capacity factors are raw ERA5 at 0.3° without bias correction: the best cluster (Rio Grande do
  Norte / Ceará coast) reaches a 0.32 annual mean, real wind farms there report 0.45+; the country
  mean over all 49 clusters (0.09) is dragged down by the Amazon and interior. Seasonality is right
  (0.07 Jan–Jun, 0.14 Aug–Sep). A WP1 validation against ONS generation data is still to do.
- Run history (2026-09-17): prestage 10:59–11:03 (2.1 GB `brazil-latest.osm.pbf` → 6.7 MB filtered,
  1.0 M nodes / 24 k ways; one fix, `osmium getid -f pbf`). Stage A (`BR-smoke`, January) 11:03–11:38,
  scope peak 6.9 GB, zero `oom_kill`. Stage B (`BR`, full 2013) 11:38–16:33: `build_cutout` 4.5 h
  (12 sequential monthly CDS requests, queue-bound, 5.3 GB), then the whole chain from
  `build_bus_regions` to `prepare_network` in 21 min (profiles 15 min, simplify + cluster < 1 min at
  1,127 base buses); scope `memory.peak` 7.8 GB with zero `oom_kill` (as for the US, mostly page cache
  from the cutout write). Result `networks/BR/elec_s_50_ec_lcopt_Co2L.nc` (18 MB): 43 AC buses (the
  MIQP gives fewer than 50 because of the isolated systems), 80 lines / 621 GW, 9 DC + 6 B2B links,
  one sub-network, 8760 snapshots, 49 solar + 49 onwind + 16 + 16 offwind profiles (mean CF 0.15 /
  0.09 / 0.27 / 0.30; onwind max-bus 0.32, offwind-dc max-bus 0.57), 39 reservoir units 75.6 GW
  with 361 TWh inflow plus 34 ror generators 40 GW / 82 TWh (443 TWh hydro in total ≈ IRENA 2023
  × 1.1; wet-season peak Feb 61 TWh, dry-season trough Nov 15 TWh), load 777 TWh (mean 89 GW, peak
  119 GW; today ~600 TWh, so the 2030 projection adds ~30 %). Potentials: onwind 17.1 TW, solar
  13.7 TW, offwind-ac 327 GW, offwind-dc 625 GW, within 1 % of the July popups. Map:
  `results/catalyst/BR_map.png`. Intermediate `networks/BR/elec.nc` and `elec_s.nc` can be deleted if
  disk gets tight; the cutout `cutouts/cutout-2013-era5-brazil.nc` (5.3 GB) should be kept.

## India (stages `IN-smoke`, `IN`)

Same recipe as Brazil; the July artefact `models/networks/India.giant.html` (392 nodes at 51 kV,
v0.8.0) is again only a cross-check, there is no `India*.nc`.

- Grid: `threshold_voltage: 200000` keeps 765 / 400 / 220 kV (220 kV is the top intra-state level;
  132 / 110 / 66 kV subtransmission is left out). Base network 4,067 buses / 5,244 lines
  (3,328 × 220 kV, 1,537 × 400 kV, 320 × 765 kV) + 64 HVDC links, between Brazil (1.1 k) and the
  US (6.5 k), so the 8 GB cap is not an issue. One synchronous system (the Northeast is tied in
  through the Siliguri corridor); 14 DC + 5 B2B links survive clustering.
- Cutout / clip box `[65.5, 4.5, 98.0, 37.5]` = GADM India (incl. Andaman & Nicobar and
  Lakshadweep) plus the mainland EEZ. The Andaman EEZ polygon has no `ISO_TER1` and is dropped by
  `build_shapes` regardless; the islands themselves stay in the country shape and fold into a
  mainland Voronoi cell (tiny load and potential, no separate bus at 220 kV). 12 k cells, 3.6 GB.
- **Hydro is only half usable, a structural pypsa-earth limitation, not a bug.** The normalised
  runoff (`profile_hydro.nc`, 315 plants) sums to 178 TWh ≈ IRENA 2023 (161 TWh) × 1.1, but the
  network holds 44 TWh reservoir inflow + 41 TWh run-of-river energy. Runoff is apportioned to
  plants by capacity within HydroBASINS and India's ror fleet (20 GW, Himalaya and Western Ghats)
  gets 141 TWh of monsoon inflow; `add_electricity` caps ror `p_max_pu` at 1 and 100 TWh vanish
  (14 % of ror plant-hours sit at the cap). The reservoirs keep their inflow, but with
  `hydro_max_hours_default` 6 h and monsoon inflow peaks at 13 × p_nom most of it will spill in
  a solve. Brazil's runoff is flatter, so the same mechanism cost it little (443 vs ~470 TWh).
  Needs the WP2 hydro treatment (ONS / CEA reservoir data, ror-vs-reservoir split by inflow
  seasonality) before either archetype is used for results.
- **PHS storage units have `max_hours = 0`** (7 units, 5.7 GW; the US network has 17 units,
  23.7 GW with the same defect): powerplantmatching gives no storage hours, `add_electricity` only
  replaces `0` by `PHS_max_hours` but the value is NaN, and `simplify_network` turns NaN into 0.
  Upstream-candidate one-liner (`fillna(PHS_max_hours)`), to be added to the fork with the biomass
  fix; both change every existing network, so they are held back until the fork is pushed.
- Powerplant labels: coal 250 GW (real ~ 220 GW incl. captive), lignite 9.5, CCGT 32, nuclear 12.1
  (real 7.5 GW; planned units counted), and **oil 50.8 GW where India's diesel fleet is < 1 GW**,
  most likely gas or captive units tagged "Oil" in the GPD/GEO sources (the July map had the
  same 51 GW). Biomass: 143 solid-biomass plants, 3 GW, silently dropped as in the other runs.
  Existing solar 116 GW in the plant list vs IRENA target 73 GW (2023); onwind 44 GW matches IRENA.
- Wind CFs are raw ERA5 0.3° without bias correction (onwind mean 0.11, best cluster Gujarat coast
  0.22 and Jaisalmer 0.21 where real farms reach 0.30–0.35); seasonality is right (monsoon
  Jun–Aug 0.19–0.22, winter 0.05–0.06). Solar 0.15 with the monsoon dip (0.10 in July).
- Run history (2026-09-17/18): prestage 18:06–18:08 (1.7 GB `india-latest.osm.pbf` → 12 MB
  filtered, 1.7 M nodes / 54 k ways). Stage A (`IN-smoke`, January) 18:08–19:07, January cutout
  37 min in the CDS queue, scope peak 6.6 GB, zero `oom_kill`. Stage B (`IN`, full 2013)
  19:07–01:31: `build_cutout` 19:10–01:06 (6 h, queue-bound), then `build_powerplants` to
  `prepare_network` in 25 min (profiles 17 min, simplify + cluster 2 min at 4,067 base buses);
  scope `memory.peak` 6.6 GB, zero `oom_kill`. Result `networks/IN/elec_s_50_ec_lcopt_Co2L.nc`
  (16 MB): 45 AC buses, 75 lines / 1,979 GW, 14 DC + 5 B2B links, one sub-network, 8760
  snapshots, 47 solar + 47 onwind + 15 + 15 offwind profiles (mean CF 0.15 / 0.11 / 0.20 / 0.25;
  offwind-dc max-bus 0.52), 30 reservoir units 24.0 GW + 7 PHS 5.7 GW + 26 ror generators 24.0 GW
  (see the hydro bullet), load 1,889 TWh (mean 216 GW, peak 302 GW in May; today ~1,600 TWh).
  Potentials: onwind 5.7 TW, solar 10.4 TW, offwind-ac 273 GW, offwind-dc 174 GW, within 12 % of
  the July popups (5.1 / 9.8 TW, 257 / 173 GW; different cluster count and threshold). Map:
  `results/catalyst/IN_map.png`. Deletable if disk gets tight: `networks/IN/elec.nc` (738 MB) and
  `elec_s.nc` (516 MB); keep `cutouts/cutout-2013-era5-india.nc` (3.6 GB).

## Singapore (stages `SG-smoke`, `SG`)

The islanded representative of the kickoff slides (display-only there; the rule-based layer uses
Australia's SWIS). No July artefact exists for it. The result is deliberately **one node**:

- **OSM has no Singapore transmission lines.** Inside the country the extract holds 24 substations
  tagged 230 or 400 kV (SP PowerGrid's transmission levels) but only two 230 kV cable segments
  (4 km); the grid is underground and unmapped. The 275 / 132 kV lines in the same bounding box are
  Johor's (Malaysia). `clean_osm_data` at `threshold_voltage: 200000` therefore yields 7 buses,
  2 transformers, 0 lines; every bus is its own sub-network. Rather than 5–10 disconnected islands,
  the SG configs raise `p_threshold_merge_isolated` above the national load (and switch the 20 MW
  `p_threshold_drop_isolated` off, which would otherwise drop unpopulated buses together with their
  plants, e.g. Jurong Island), so `simplify_network` merges everything into one bus and
  `clusters: [1]`. For a 720 km² city-state on one synchronous system this is also the right
  representation for capacity expansion; `run.sh` now reads the cluster count from the stage
  config instead of hard-coding 50. Two `KeyError`s on the empty lines table in `base_network` are
  the eighth fork patch (upstream candidate).
- **Singapore is not in earth-osm's index on its own** (Geofabrik ships `malaysia-singapore-brunei`,
  index code `MY`); pypsa-earth's `iso_to_geofk_dict` maps `SG` to `MY`, so `download_osm_data`
  works unchanged and `prestage.sh` filters the shared 251 MB extract (17 s).
- **Powerplants:** CCGT 11.1 GW (9 plants; EMA reports ~10.5 GW CCGT / cogeneration, 83 % of the
  licensed 12.6 GW), plus `oil` 5.2 GW that is largely wrong: Pulau Seraya 2,250 MW oil steam
  (retired in stages, `DateOut` 2028 in the database), "Powerseraya Pulau Seraya CCGT Cogen"
  1,477 MW labelled oil steam turbine, Tuas 600 MW steam (retired). Real oil-fired steam capacity is
  below 0.5 GW. Biogas 80 + solid biomass 160 + waste-to-energy 200 MW are dropped by the
  `carrier_dict` gap already noted for Brazil and India. Existing solar in the database is 244 MW
  against ~1.4 GWp installed 2024 (EMA), irrelevant for the prenetwork (extendable carrier).
- **Resource:** solar mean CF 0.134 (ERA5, no monthly pattern to speak of, 0.11–0.17), onwind
  0.047 and offwind-ac 0.061, offwind-dc none: Singapore has no wind resource, as expected. Solar
  potential 1.45 GW after the land-availability exclusion, which is a coincidence rather than a
  number to use: Singapore's solar is rooftop and floating (EMA target 2 GWp by 2030), which the
  atlite land-use logic does not represent. Onwind potential 38 MW, offwind-ac 1.29 GW in the
  Strait (unbuildable shipping lanes; also to be overridden in WP2).
- **Load:** 66.4 TWh (GEGIS SSP2-2.6 2030), mean 7.6 GW, peak 9.9 GW (13 May 10:00), minimum
  5.2 GW. EMA 2023: 57.4 TWh, peak 7.9 GW, so the projection is +16 % on energy and +26 % on peak.
- **Run history** (2026-09-18): prestage 12:16 (17 s). Stage A (`SG-smoke`, January) 12:18–13:05 incl.
  two `base_network` failures on the empty lines table (patched 13:00, chain to `elec_s.nc` re-run
  by hand in 3 min, driver relaunched); January cutout 12:32–13:00 (935 KB); scope peak 1.2 GB.
  Stage B (`SG`, full 2013) 13:05–18:52: `build_cutout` 13:05–18:48 (5 h 43 min, twelve monthly
  CDS requests for a 10 MB file, entirely queue-bound), then `build_powerplants` to
  `prepare_network` in 4 min; scope `memory.peak` 1.5 GB, zero `oom_kill`. Result
  `networks/SG/elec_s_1_ec_lcopt_Co2L.nc` (792 KB): 1 AC bus + H2 and battery store buses, 0 lines,
  8760 snapshots, four VRE profiles, one sub-network. Map: `results/catalyst/SG_map.png` (one dot).
  Nothing worth deleting; keep `cutouts/cutout-2013-era5-singapore.nc` (10 MB).

## North-West and Central Europe (stage `NWE`)

Twelve countries in one network (`AT BE CH CZ DE DK FR GB IE LU NL PL`), the dense / renewables-constrained
archetype (SOW §1.2, archetype 1), 50 clusters, weather year 2013, built 2026-09-19. The first multi-country stage.

- **Cutout reused, nothing built via CDS.** `cutouts/europe-2013-sarah3-era5.nc` is a hardlink (same
  filesystem, no disk cost, survives a cache eviction) to the PyPSA-Eur cutout v1.0 found in
  `~/.cache/snakemake-pypsa-eur/data.pypsa.org/workflows/cutout/v1.0/` (6.6 GB, x −12..40.8, y 33..72, 0.3°,
  ERA5 wind / temperature / runoff plus **SARAH-3 satellite solar**, `module ['era5', 'sarah']`; opens with the
  fork's atlite 0.4.1). Therefore no `-smoke` stage: `build_renewable_profiles` computes over the whole cutout
  year regardless of the snapshots, so a January stage would have cost almost as much as the full year.
  Other cutouts on the machine (`~/Desktop/code/input_files/europe-2024-sarah3-era5.nc`, weather year 2024;
  the continental pypsa-earth cutouts in `~/Desktop/earth/pypsa-earth/cutouts/`, none covering Western
  Europe) were not suitable.
- **OSM**: twelve Geofabrik extracts (IE incl. Northern Ireland 0.4 GB, GB 2.1, FR 4.8, BE 0.7, NL 1.3, LU 0.05, DE 4.6,
  DK 0.5, PL 2.0, CZ 0.9, AT 0.8, CH 0.5 = 18.6 GB), filtered one after the other by `prestage.sh NWE` to 107 MB
  in 44 min (14:03–14:47 incl. two restarts). Two prestage fixes came out of it: Geofabrik's Germany md5 file
  names the dated extract (`germany-260918.osm.pbf`), so the check now compares hashes instead of `md5sum -c`;
  and `osmium getid` exits 1 when some requested ids are absent (68 `power=line` relations dropped by
  `--omit-referenced`) although its output is complete, so only rc ≥ 2 counts as a failure.
  `threshold_voltage: 200000` keeps 220 / 275 / 380 / 400 kV; Denmark's 150 / 132 kV and the 110 / 132 kV grids of
  IE, GB and the continent are left out. Base network: 3,497 AC + 135 DC buses, 4,372 lines, 148 DC links,
  65 B2B converters; 29 AC sub-networks (continent 2,881 buses, GB 508, IE + NI 72, the rest 1–5-bus pockets).
- **Topology fixes needed for a multi-country OSM network** (both now in place): (1) the ninth fork patch
  absorbs the 18 DC buses that survived `simplify_links` (see the patch table; without it 18 of the 50
  clusters were DC converter buses and only 32 AC nodes remained); (2)
  `cluster_options.simplify_network.s_threshold_fetch_isolated: 0.05` merges isolated AC fragments below 5 %
  of the national load (seven single-bus pockets of 20–1,350 MW mean load in DE, FR, GB, DK, PL, CH, IE,
  unmapped 220 kV connections) into the nearest backbone bus of their country instead of each claiming a
  cluster. GB and IE (+ NI) count as backbones and stay separate synchronous areas.
- **Result** `networks/NWE/elec_s_50_ec_lcopt_Co2L.nc` (18 MB): 50 AC buses (DE 14, FR 12, GB 9, PL 4, NL 3,
  BE 2, AT / CH / CZ / DK / IE / LU 1), three synchronous areas (continent incl. DK, GB, IE + NI), 94 lines
  (1,023 GW aggregated s_nom, all 380 kV after simplification), 14 HVDC links (70 GW), 8,760 snapshots,
  no NaNs. Map `results/catalyst/NWE_map.png`.
- **Cross-checks**: load 2,206 TWh (DE 623, FR 528, GB 369, PL 170, NL 123, BE 93, AT 79, CZ 75, CH 69, DK 37,
  IE 31, LU 9), mean 252 GW, peak 323 GW on 25 Jan 17:00, min 179 GW; ENTSO-E 2013 consumption of the twelve
  was ≈ 1,950 TWh, so the GEGIS SSP2-2.6 **2030** projection sits ≈ 13 % above 2013. Existing capacity (ppm, plants
  with `DateOut >= 2022`): nuclear 100.5 GW (FR 66, GB 11.2, DE 9.6, BE 6.2, CZ 4.2, CH 2.7; the German and part of
  the British and French units are retired since, ≈ 80 GW today), CCGT 104.5 (GB 38.7, DE 20.7, NL 15.0, FR 9.4),
  coal 64.4 (DE 25.0, PL 17.5, GB 7.9), lignite 43.7 (DE 21.8, PL 14.5, CZ 6.6; DE and PL look ≈ 4–5 GW high),
  oil 15.0, run-of-river 15.6 GW; reservoir hydro 23.8 GW (CH 9.0, FR 8.2, AT 4.8) with 88 TWh inflow
  (CH 31, AT 29, FR 17, GB 4, DE 3.5) and PHS 24 units. Capacity factors 2013: solar 0.087 (GB) – 0.12 (CH, FR),
  mean 0.097 (SARAH-3, fixed tilt); onwind DK 0.46, GB 0.43, IE 0.37, NL 0.34, BE 0.28, DE 0.24, PL 0.22, FR 0.18,
  AT 0.14, CH 0.03; offshore 0.37 (FR) – 0.50 (NL). Potentials after the Copernicus / natura exclusions: solar
  4,033 GW, onwind 1,295 GW, offwind-ac 394 GW, offwind-dc 560 GW.
- **Caveats** (on top of the general ones): HVDC capacities come from pypsa-earth's per-cable defaults and are
  3–5× the real ratings (FR–GB 19 GW in the model vs 4 GW; GB–IE 9.4 vs 1; DE–DK 7.8 vs ≈ 2.5; GB–BE 2.7 vs 1;
  BE–DE 5.6 vs 1; GB–DK 4.6 vs 1.4) — WP2 should override them with ENTSO-E NTC values, as it should the
  interconnectors to countries outside the set (ES, IT, NO, SE, SK, HU, SI, LT), which are absent. Corsica is
  an isolated OSM "DC" substation and is now attached to the nearest mainland bus. Hydro reservoirs carry the
  6 h `hydro_max_hours_default` (Alpine seasonal storage is not represented); French hydro inflow (17 TWh
  reservoir + run-of-river profiles) should be checked against RTE's ≈ 60 TWh. Fleet is the ≈ 2022 one, not
  2025 (German nuclear, part of the coal fleet). Demand is a 2030 projection.
- **Run history** (2026-09-19): prestage 14:03–14:47. Stage `NWE` first attempt 14:47 failed at DAG time
  (`retrieve_databundle_light` provenance re-run over write-protected files → `--rerun-triggers mtime input`
  in `run.sh`), second attempt 14:49–16:04 (75 min): build_shapes 5 min (12 GADM downloads), OSM chain 8 min,
  build_powerplants 20 min, renewable profiles 45 min (solar 20 min), simplify 1 min, cluster 20 s; scope
  peak 7.1 GB incl. page cache, largest rule RSS 3.0 GB (`build_shapes`, `solar`), zero OOM. Third attempt
  16:09–16:11 re-ran the four rules after `elec.nc` with the DC-bus patch and the fetch threshold
  (`elec_s*.nc` deleted by hand). Disk: 105 GB free afterwards; keep the hardlinked cutout.

## China (stages `CN-smoke`, `CN`; 2026-09-21)

The sixth region, and the first whose cutout was **not** built via CDS: the pypsa-earth Asia cutout already on
this machine covers all of China, so it was cropped instead (40 min instead of a 3-6 h CDS queue).

- **Cutout** `cutouts/cutout-2013-era5-china.nc` (11.4 GB) and `-china-jan.nc` (1.0 GB), cut from
  `~/Desktop/earth/pypsa-earth/cutouts/cutout-2013-era5-asia.nc` (27.7 GB, ERA5 2013, 0.3 deg, x 24.9..158.1,
  y -14.4..55.8) with `crop_cutout.py` to `x [73.5, 135.0] y [15.0, 54.0]` = 206 x 131 = 26,986 cells, 8,760 h.
  The Asia file carries 13 of the 15 variables the CDS-built cutouts have; the two missing ones
  (`wnd_shear_exp`, `dewpoint temperature`) are only read by atlite's `interpolation_method: "power"` and by the
  heat/sector conversions, neither of which this power-only fork uses. Verified before use: atlite reports
  `dx = dy = 0.3`, `prepared_features [height, wind, influx, temperature, runoff]`, and the wind/PV conversions
  return no NaNs (Inner Mongolia January CF 0.28 at 6.1 m/s mean, central-plains 0.06 at 3.4 m/s - the low-wind
  interior is real, not a defect).
- **Defect repaired while cropping** (the reason `crop_cutout.py` is more than an `xr.sel`): east of ~128 E the
  Asia cutout has 41 pairs of near-identical longitudes (128.1 *and* 128.10001, from two merged ERA5 tiles), and
  **one column of each pair is entirely NaN**. Ten of those pairs fall inside the China box, right across
  Heilongjiang and Jilin; left in place they would have produced NaN wind and solar profiles over north-east
  China, and the duplicate also made atlite read `dx = 0.286` instead of 0.3. The script keeps, per group of
  coordinates closer than dx/10, the column that holds data and rounds the grid back to 0.3 deg. Two performance
  traps found on the way and handled: `xr.concat` on non-dask arrays materialises the whole slab (chunk first, or
  the 8 GB cap kills the job with no message), and a fancy index over a netCDF dimension makes the backend read
  element-wise (contiguous index runs instead: 38 min rather than hours).
- **Scope:** GADM CHN is mainland + Hong Kong + Macau (`ADM_1` rows `CHN.HKG`, `CHN.MAC`) plus, under the default
  `contended_flag: set_by_country`, the contended polygons Z02/Z03/Z08 (Aksai Chin, Shaksgam, South Tibet) merged
  into CN. Taiwan is a separate GADM/Geofabrik/GEGIS entity and stays out. GEGIS gives Hong Kong zero demand.
- **OSM:** `asia/china-latest.osm.pbf` 1.60 GB raw -> 23 MB after the osmium prefilter (154,081 lines, 21,667
  substations, 1,527 generators at >= 51 kV; the densest of the six regions, US was 44 MB / 61k lines). At the
  200 kV threshold the base network has **13,549 buses and 21,049 lines** - twice the US - by voltage:
  220 kV 9,143, 500 kV 2,788, 330 kV 713, 800 kV 379, 750 kV 287, 1000 kV 172, 400 kV 40.
- **Caveat, UHV line types:** `electricity.voltages` (inherited) is `[132, 220, 300, 380, 500, 750]` and
  `lines.dc_types` only has 500 kV, so `base_network` snaps the 330 kV lines to the 380 kV type and the 800 /
  1000 kV ones to 750 kV, understating the capacity of exactly the corridors that move power from the west to the
  coast. Fixing it needs new entries in `lines.ac_types`/`dc_types`, i.e. a patch, so it is on the list rather
  than in this screening run.
- **Run history:** cutout crops 00:05-00:45 (January, 0.4 min of streaming) and 00:45-01:26 (full year, 38.5 min).
  prestage 01:26-01:41 (15 min: 1.6 GB download, osmium filter). Stage A (`CN-smoke`, January) 01:41-04:11
  (2 h 30 min), scope peak 9,500 MiB, zero OOM; the long rules were `build_powerplants` 74 min (powerplantmatching
  over ~4,200 Chinese plants, the longest single rule of any region), `build_renewable_profiles` onwind 26 min /
  5.4 GB and solar 21 min / 6.2 GB (the availability matrix is 13,549 buses x 26,986 cells, so it is heavier than
  the US *full-year* run), `build_shapes` 8 min / 4.6 GB (GADM CHN 79 MB + WorldPop CHN 626 MB downloaded),
  `build_osm_network` 7 min. Stage B (`CN`, full 2013) 04:11-06:49 (2 h 38 min), scope peak **11,643 MiB against
  the 12 GB cap**, still zero OOM: `build_powerplants` 80 min, solar profiles 22 min / **9.2 GB RSS** (the
  heaviest rule of all six regions), onwind 26 min / 6.6 GB, `add_electricity` 99 s / 7.1 GB, `build_shapes`
  3 min / 5.1 GB. Disk 69 GB free afterwards. **Do not run this stage under an 8 GB cap** and do not raise the
  cluster count without re-checking: the availability matrices scale with base buses x cutout cells, and China is
  the worst case of the six (2x the US buses, 1.6x the cells).

## Screening solves (stages `<R>-now`, `<R>-zero`, `dashboard:<R>`; 2026-09-19/20)

First look at how the five prenetworks behave *when solved as the model comes*, before anything is patched:
per region one **current-system** and one **carbon-neutral** run (weather 2013, the prenetwork topology,
**3-hourly**: the hourly 50-node LP does not fit the laptop, see below), rendered side by side on one 16:9 page per
region (`results/catalyst/validation_<R>.png`).

- **`now` = current system, brownfield expansion, no CO2 cap**: the ≈2022 powerplantmatching fleet + IRENA 2023
  wind/solar fixed (`p_nom_min`), the model's default extendables (solar, onshore/offshore wind, battery and H2
  stores, AC lines + HVDC via `ll copt`) at `costs_2025.csv`, no `Co2L` opt → no CO2 constraint.
- **`zero` = carbon-neutral, the way pypsa-earth does it by default**: same fleet and extendables, `opts Co2L0`
  (CO2 limit 0 → fossil units stay in the model but cannot run), `costs_2050.csv`, `ll copt`. No new firm clean
  technology, no imports, no biomass/CCS: only VRE + batteries + H2 storage + existing nuclear / hydro.
- Both inherit the defaults that shape the results: **GEGIS SSP2-2.6 2030 demand** (not 2024/25; `load_options`
  unchanged), load shedding at 100 kEUR/MWh at every bus (`solving.options.load_shedding: 100`), Gurobi barrier
  without crossover, `noisy_costs`, `clip_p_max_pu 0.01`, 6 h hydro reservoirs, HVDC per-cable defaults. The
  prenetwork files themselves still carry the European `co2.limit` 77.5 Mt as `CO2Limit` (opt `Co2L` with the
  default `co2.limit`); the screening runs replace that with no cap / a zero cap.
- **Mechanics**: `costs.year` is not a Snakemake wildcard but a config key baked into
  `resources/<run>/costs_<year>_elec.csv`, so each scenario is its own `run.name` (`<R>-now`, `<R>-zero`). To avoid
  rebuilding shapes, OSM, profiles, powerplants and demand (hours), `run.sh` makes `resources/<R>-<scen>/` a
  directory of symlinks to the base run's entries, with its **own `bus_regions/`** holding only symlinks to the
  two `build_bus_regions` outputs, and hardlinks `networks/<R>-<scen>/base.nc` (same inode, same mtime, so the
  shared resources stay newer than their inputs). A dry run then schedules only `retrieve/process_cost_data`,
  `add_electricity`, `simplify_network`, `cluster_network`, `add_extra_components`, `prepare_network`,
  `solve_network`, `plot_validation`. The first version used one directory symlink; `simplify_network` /
  `cluster_network` then rewrote the busmaps and clustered regions in the shared `bus_regions/`, and the sibling
  scenario (and the base prenetwork chain) looked outdated to Snakemake — `IN-now` was re-solved by a plot-only
  pass at 02:09 and its solved network deleted. Fixed by the per-run `bus_regions/` plus `snakemake --touch` of
  every intact target. Solver: `gurobi-default` (barrier, no crossover, `BarConvTol 1e-6`), 8 threads via the
  overlay. Deleting a scenario: `rm -r resources/<R>-<scen> networks/<R>-<scen> results/<R>-<scen>`.
- **OOM safety of the overnight queue**: `MEM_MAX=12G` cgroup cap with `MemorySwapMax=0` (a runaway solve is
  killed inside the scope instead of swapping), `CONTINUE_ON_FAIL=1` so an OOM/timeout/infeasible stage is
  logged and the next region starts, 4 h per stage, `-c1 -j1`, disk watchdog, small regions first. Check the
  `SCOPE memory.peak=` lines in `status.log` afterwards. The host had only 12 GB available at launch (desktop
  applications), hence the 12 GB cap and the `WARNING` line in the log.
- **Singapore pilot** (23:25, one node, both solves in 1 min): `now` dispatches 65 TWh of the 66 TWh demand
  from the 11 GW CCGT fleet, builds solar up to its 1.5 GW potential, 22.5 Mt CO2 (338 g/kWh), flat price
  47.7 EUR/MWh (= gas marginal cost), 4.6 bn EUR/a. `zero` is the expected failure mode of a one-node island
  without imports or firm clean supply: solar (1.45 GW potential) + offshore wind (1.3 GW) deliver 2 TWh and the
  model **sheds 64 TWh = 96 % of demand** in every hour at the 100 kEUR/MWh penalty (objective 6,400 bn EUR,
  CO2 shadow price 303 kEUR/t). Batteries/H2 are not built (nothing to store). SG needs the ASEAN imports /
  SMR / geothermal-import options of the study before a zero-carbon run means anything.
- **Hourly does not fit**: the first queue (23:29, hourly) built BR-now in 3 min and died in Gurobi's presolve at
  the 12 GB cap: 19.0 M rows × 9.3 M columns × 37 M nonzeros (linopy keeps its own copy of the model while Gurobi
  presolves). The fork's own `memory()` estimate for `solve_network` is 59 GB hourly / 20 GB 3-hourly at 50 clusters,
  i.e. hourly 50-node solves belong on the ZIB cluster (or need ≥ 25 GB free here). SG (one node) solved hourly in
  seconds: `results/SG-{now,zero}/plots/validation_*_lcopt_{,Co2L0}.png` are those hourly runs.
- **Run history** (2026-09-19/20): hourly queue 23:29–23:34 (SG ok, BR-now OOM, stopped by hand); 3-hourly queue
  23:34–02:08 for the ten solves and five pages, all `SUCCESS`, zero OOM events; a plot-only pass at 02:09 tripped
  over the shared `bus_regions/` (see Mechanics; IN-now re-solved 02:23–02:33 after the restructuring); final plot
  pass 02:36–02:39. Rebuild per scenario (cost data → prepare_network) 3–4 min; Gurobi barrier, 8 threads:

  | run | solve | scope peak | run | solve | scope peak |
  |---|---|---|---|---|---|
  | SG-now | 8 s | 1.3 GB | SG-zero | 8 s | 1.2 GB |
  | BR-now | 23 min | 9.1 GB | BR-zero | 22 min | 8.8 GB |
  | IN-now | 9 min | 9.5 GB | IN-zero | 22 min | 9.9 GB |
  | NWE-now | 9 min | 10.5 GB | NWE-zero | 26 min | 10.3 GB |
  | US-now | 9 min | 10.2 GB | US-zero | 13 min | 10.4 GB |
  | CN-now | 19 min | 11.6 GB | CN-zero | 28 min | 11.6 GB |

  3-hourly, 50 nodes: 6.3 M rows × 3.1 M columns (BR), 8–9 GB RSS in the solve rule, 9–10.5 GB scope peak, so
  the 12 GB cap has 1.5 GB of headroom; the four regions take 2.5 h in total. China (added 2026-09-21, queue
  01:26–07:39 including both prenetwork stages) is the tightest: 11.6 GB scope peak in both solves, i.e. 0.4 GB
  under the cap, because the fleet is large (1,310 GW of coal alone) and the zero run builds 5,211 GW of solar.
- **Validation data** (dots on the pages; 2026-09-20). One tidy table, `resources/catalyst/validation_points.csv`
  (columns region, country, scenario, quantity, carrier, value, unit, year, source_short, source, url, note), built by
  `scripts/build_validation.py` from bulk files and a hand-curated CSV. Rule of thumb applied: per quantity one
  national statistical source + Ember + one more (EI or IRENA) for `now`, two or three institutional 2050
  outlooks for `zero`, at most six sources per block so the legend stays one row. No temporal disaggregation:
  demand and prices are annual numbers only.

  | Region | `now` (actuals) | `zero` (2050 outlooks) |
  |---|---|---|
  | all | Ember 2025 (generation, capacity, demand, CO2 by fuel; life-cycle factors, so only coal/gas/oil/total are used), IRENA 2024 capacity, EI 2024 generation + wind/solar capacity; **fuel prices** EI 2024 markers per region (gas: Henry Hub / TTF / LNG China cif / West India Marker / JKM; coal: NAPP 6,900 / ARA 6,000 / South China 5,500 / Richards Bay 5,500 kcal/kg NAR; crude: WTI / Brent / Dubai) | **fuel prices** IEA WEO 2025 Table 2.3 STEPS and NZE 2050 (US, EU, China rows; Japan LNG as the Singapore proxy) and WEO 2024 APS 2050 for China |
  | US | EIA Electric Power Annual 2024 (generation, net summer capacity, total end use 4,110 TWh) + MER 11.6 power-sector CO2 by fuel; prices: ERCOT and PJM 2024 real-time load-weighted (SOM reports) | IEA WEO 2025 STEPS 2050, EIA AEO2025 Reference 2050, Princeton Net-Zero America E+ 2050 |
  | BR | EPE BEN 2025 (2024 generation by source, capacity incl. distributed PV, energy made available 763 TWh; thermal fuel split from Tabela 8.4), CCEE PLD 2024 SE/CO monthly mean, IEA WEO 2024 electricity+heat CO2 2023 | IEA WEO 2024 APS 2050, EPE PNE 2050 (demand: expansion / stagnation; capacity ranges) |
  | IN | CEA FY2024-25 (LTRAP 2026: capacity 31 Mar 2025, gross generation; energy requirement via CERC market report; CO2 Baseline Database v21 1,234 Mt), IEX day-ahead FY2024-25 average 4.47 INR/kWh | IEA WEO 2024 APS 2050, IEA WEO 2025 STEPS 2050, CEEW net-zero pathway (2050 capacity) |
  | SG | SingStat/EMA 2024 (generation, consumption), EMC NEMS market report 2024 (registered capacity, USEP 163 SGD/MWh) | EMA Energy 2050 Committee (solar potential 8.6 GWp; the report gives no TWh/GW mix), EMA demand outlook 2034 base/high |
  | CN | NEA 2024 power-industry statistics + NBS Statistical Communiqué 2024 (capacity and generation by type, 3,348.62 GW / 10,086.88 TWh) + CEC (coal 1,190 GW), NEA consumption 9,852.1 TWh, IEA WEO 2025 electricity+heat CO2 6,688 Mt; prices: Guangdong and Shandong day-ahead 2024 (0.347 / 0.316 CNY/kWh, converted at the ECB 2024 average 7.79 CNY/EUR) | IEA WEO 2024 APS 2050, Tsinghua ICCSD 1.5 °C 2050 (capacity and generation), CETO 2022 carbon-neutrality scenario 1 (capacity, 17,103 TWh consumption) |
  | NWE | national statistics 2024 = Eurostat nrg_bal_peh / nrg_cb_e (10 countries) + DUKES 2026 (GB) + SFOE (CH), per-country demand + region sums; Ember prices 2023 per country and demand-weighted (no GB) | ENTSO-E TYNDP 2024 Distributed Energy and Global Ambition 2050 (per-country market-model outputs summed; batteries/DSR excluded) |

  Not used, on purpose: IEA WEO EU27 rows for NWE (different region), IRENA generation (lags a year), EIA/IEA
  2024 actuals as a fourth US source, TYNDP marginal costs (scarcity artefacts), Singapore's grid emission factor
  (kg/kWh, not an absolute). IEA's free WEO dataset needs a login, so the WEO numbers were transcribed from the
  Annex A tables of the WEO 2024 / 2025 PDFs (URLs in the CSV). The Energy Institute workbook is behind a
  Cloudflare challenge (archive link `https://www.energyinst.org/__data/assets/excel_doc/0008/1656215/EI-Stats-Review-ALL-data.xlsx`).
  Prices in local currency are converted with the ECB annual average of the data year; the US model is CONUS while
  the statistics are national (AK + HI ≈ 1 %). Fuel prices are converted to EUR/MWh net calorific value in the
  builder: gas markers are per MMBtu gross (×1.108 GCV/NCV), crude at 1.615 MWh_NCV/bbl (5.8 MMBtu × 0.95), coal per
  tonne at the marker's kcal/kg NAR (× 0.001163 MWh/t); WEO 2050 values are in USD of 2024 (WEO 2025) or 2023
  (WEO 2024) and use that year's ECB rate (unit strings `USD2024/MMBtu`, `USD2024/t@6000kcal`, `USD2024/bbl` in
  `manual_points.csv`). Uranium and biomass have no published dot: the model's 3.4 / 7.4 EUR/MWh_th are shown alone.
- **What the pages show** (`results/catalyst/validation_<R>.png`, numbers per region; demand is GEGIS 2030):

  | region | demand TWh | now: CO2 Mt (g/kWh), price EUR/MWh, cost bn/a, main additions GW | zero: price, cost bn/a, CO2 shadow EUR/t, additions GW, curtailment |
  |---|---|---|---|
  | SG | 66 | 22.5 (338), 47.7, 4.6, solar 1 (at its potential) | sheds 96 % of demand, 1.6 bn + 6,400 bn penalty, 303 k, solar 1 + offwind 1, — |
  | BR | 777 | 51 (66), 65, 42.0, solar 76 + onwind 73 | 39, 39.6, 4,351, solar 405 + battery 129 GW / 728 GWh, 119 TWh (16 %) |
  | IN | 1,888 | 1,217 (645), 37, 175.8, solar 196 + battery 25 | 47, 187.8, 10,250, solar 1,357 + battery 389 GW / 2,750 GWh, 394 TWh |
  | NWE | 2,206 | 871 (395), 37, 192.4, onwind 14 | 80, 249.1, 39,867, onwind 339 + solar 332 + battery 151 GW / 2,557 GWh, 478 TWh (19 %) |
  | US | 4,649 | 1,877 (404), 47 excl. shedding, 374.6, solar 373 + onwind 50 | 58 excl. shedding, 418.8, 14,936, solar 2,293 + battery 795 GW / 5.5 TWh, 714 TWh (14 %) |
  | CN | 8,254 | 4,240 (514), 30, 783.1, solar 317 (no wind, no storage) | 46, 872.0, 5,650, solar 4,592 + offwind-dc 75 + onwind 22 + battery 1,924 GW / 11.0 TWh, 2,147 TWh (22 %) |

  Observations for the patch list: (1) every zero-carbon run is solar + batteries (+ wind in NWE/US); the H2
  store is built only in IN/US at a few hundred GWh and the model never touches nuclear extension, CCS, biomass
  or imports, so the CO2 shadow prices (4–40 kEUR/t) measure the cost of the last fossil kWh under those
  defaults, not a plausible abatement cost. (2) `now` already builds 70–370 GW of solar per region at 2025
  costs because the ≈2022 fleet cannot serve 2030 demand at the fuel prices in `costs_2025.csv`; a 2024/25
  validation needs observed demand (demcast or a `load_options.scale` per country) and the 2024 fleet. (3) US
  bus `US5 0` (western Massachusetts, 1.1 GW mean load) has no line or HVDC connection in the prenetwork and
  sheds 2.9 TWh in both scenarios; the fix is `s_threshold_fetch_isolated: 0.05` as for NWE (US config +
  re-run of simplify/cluster). (4) NWE `now`: 596 TWh nuclear (2022 fleet incl. the last German reactors),
  lignite 382 TWh, coal 388 TWh, 871 Mt; prices flat at fuel cost with no scarcity hours — the CO2 price of
  the ETS is absent (`co2.emission_price: 0`). (5) Hydro: BR reservoir + ror deliver 252 TWh vs ≈ 430 TWh
  observed (6 h reservoirs, inflow calibration). (6) Curtailment of 14–22 % in the zero runs and battery
  fleets of 2.5–11 TWh are the model's only flexibility; LDES / firm clean options of the study palette are
  exactly what is missing here. (7) China sharpens two of these. Its GEGIS 2030 demand (8,254 TWh) is **16 %
  below the actual 2024 consumption** (9,852 TWh, NEA), so the demand input is not merely un-calibrated but
  already historical - the single most important fix before any China result is quoted. And in `CN-zero` the
  existing nuclear fleet is squeezed from 554 TWh down to **63 TWh**: with 5,211 GW of solar and 11 TWh of
  batteries the system is over-supplied in most hours, and since curtailing zero-marginal-cost solar is cheaper
  than curtailing nuclear (uranium at a few EUR/MWh), the optimiser idles the clean firm capacity it already
  has. Any study conclusion about clean firm technologies has to deal with that mechanism explicitly.
  (8) China's fleet in the prenetwork is 10-16 % above the statistics (coal + lignite 1,310 GW vs 1,190 GW CEC,
  nuclear 70.7 GW vs 60.8 GW NEA) while hydro inflow (1,054 TWh/a) is ~26 % below observed hydro generation
  (1,426 TWh in 2024), the same inflow-calibration problem as Brazil.
  (9) Fuel prices are one global technology-data set in every region and both cost years (gas 24.6, coal 9.6,
  lignite 3.3, oil 52.9, uranium 3.4, biomass 7.4 EUR/MWh_th; `costs.country_specific_data` is empty). Against
  the 2024 markers that is gas 3× too dear for the US (Henry Hub 7.8) and ~35 % too cheap for Europe and Asian
  LNG importers (TTF 38, JKM 42, China LNG 39), coal roughly right for the US (8.9) and China (14.7 delivered)
  but 35 % low for ARA (14.8), oil 15 % high (Brent 46). The IEA 2050 assumptions sit below the model for
  every fuel except US gas (STEPS 16, NZE 7.7). Regional fuel prices are therefore a WP2 input, not a patch:
  the US `now` gas share (16 %) and Europe's coal-before-gas dispatch both follow directly from this table.
