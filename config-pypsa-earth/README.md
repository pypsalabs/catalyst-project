# `config-pypsa-earth/` — how the PyPSA-Earth soft fork is run (CONUS, Brazil, India, Singapore, North-West/Central Europe and China prenetworks + screening solves, WP1 pipeline test; plus 115 single-node rest-of-world countries, 99.5 % of world demand)

Builds **power-only PyPSA-Earth models up to the `prepare_network` output** ("prenetwork",
not solved), one country (or country group) per stage, as the end-to-end exercise of the global data pipeline the
SOW prescribes (SOW §methodology: PyPSA-Earth soft fork, atlite/ERA5 feed-in). Done: the
contiguous United States (`US`, 2026-09-16; since 2026-11-17 the two stages `USW` and `USE`, section "US West / US
East"), Brazil (`BR`, the hydro-rich archetype,
2026-09-17) India (`IN`, the fossil-heavy archetype next to US East, 2026-09-18) and Singapore (`SG`, the islanded
archetype of the kickoff slides, 2026-09-18, a single node); North-West and Central Europe (`NWE`, twelve
countries, the dense / renewables-constrained archetype, 2026-09-19) is the first multi-country stage and
reuses the PyPSA-Eur 2013 cutout found on this machine. Since 2026-09-19 the same driver also solves two
screening scenarios per region ("current system" and "carbon-neutral", see the last section) and renders one
validation dashboard per region. Everything runs under three constraints: **≤ 8 GB RAM for the whole
process tree, no Snakemake parallelism (`-c1 -j1`), and a bounded disk footprint**.

The model code lives in `models/pypsa-earth` (gitignored here): a clone of the soft fork
`pypsalabs/catalyst-pypsa-earth` (GitHub fork of `pypsa-meets-earth/pypsa-earth`; remote `origin`
is the fork, `upstream` is pypsa-meets-earth), branch **`catalyst`** = tag v0.9.0 plus 59
patches (`git log v0.9.0..catalyst`; the table lists the early ones, later ones are described in their sections). Commit subjects carry an upstream tag: `(upstream candidate)` marks a bug fix to
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
| `build_renewable_profiles`: drop the all-NaN near-duplicate longitudes of prebuilt cutouts (`drop_nan_duplicate_coords`) | the pypsa-earth 2013 cutouts `asia` and `oceania` hold, east of 128.1 °E, pairs of longitudes 1e-5° apart of which one column is NaN in every variable (41 and 70 pairs); any region reaching into them (JP, KR, eastern ID, AU, NZ) got NaN profiles. The duplicate is dropped on load (no second multi-GB copy on disk, unlike `crop_cutout.py`); no-op for clean cutouts. Rest of world, 2026-09-29. |
| `add_electricity`: map the powerplantmatching fuel types `Solid Biomass`, `Biogas`, `Waste` to the `biomass` carrier | powerplantmatching ≥ 0.6 split `Bioenergy` into these three labels; `load_powerplants` only mapped the old one, so every bioenergy plant fell out of the carrier set and no run had biomass at all (13.5 GW in Brazil, ≈10 GW in NWE, 6 GW in the US). Calibration, 2026-09-30. |
| `add_electricity`: the statistics-based wind/solar fleet is the expansion floor | `attach_wind_and_solar` put the IRENA-completed installed capacity into `p_nom` but left `p_nom_min` at the powerplantmatching share; an extendable generator ignores `p_nom`, so every `now` run rebuilt wind and solar from ≈0 (NWE onwind `p_nom` 91.8 GW, `p_nom_min` 0.33 GW). `p_nom_min` now carries the fleet times the documented `estimate_renewable_capacities.p_nom_min` factor; the `p_nom_max` factor of the same block is honoured. Calibration, 2026-09-30. |
| `calibrate_network.py` + hooks in `prepare_network` / `solve_network`: config-gated calibration of a clustered network to a reference year (`calibration:` block, off by default) | per-country csv tables for demand, installed capacity per fuel group, hydro energy and reservoir hours, wind/solar capacity factors, fuel and CO2 prices, must-run / availability / fleet-efficiency envelopes and annual net imports; `brownfield_only` freezes every capacity for a pure dispatch; `efficiency_spread` splits fuel-burning generators into tranches so a country's merit order is a staircase. Applied after clustering, so one iteration costs prepare + solve. See "Calibration to 2024" below. |
| `build_demand_profiles`: optional `load_options.fallback_source: demcast` | GEGIS SSP2-2.6 has all-zero series for HK, PR, LA, BT, PS, AF, UG, PG, ... (0.6 % of world demand). With the key, countries without load in `source` take the DemandCast series of `weather_year`; default `false`, archetype runs unaffected. Rest of world, 2026-09-29. |
| `simplify_network.simplify_links`: capacity and length of a merged HVDC chain (upstream candidate) | the merged link summed the `p_nom` of every segment and converter of the chain (`min(... i_links ...)` over all links instead of over each group of parallel edges), so its capacity grew with the number of OSM segments (China: 483 GW of clustered HVDC, one link 29.8 GW). Now parallel edges add up and the weakest group limits the chain; the length is the sum over the series. 2026-10-19. |
| `base_network`: `links.dc_ratings` (upstream candidate) | every OSM HVDC line became a link of `v_nom` x 1.638 kA (the one `lines.dc_types` cable type): 1.31 GW for a +-800 kV bipole. With the option an HVDC line is one bipole of the rating of its country and voltage from a csv, converters the summed rating of their lines. Default `false`. 2026-10-19. |
| `base_network`: `links.dc_projects`, `_dc_projects.py` (upstream candidate) | rating per HVDC project instead of per OSM way: PyPSA-Eur's `links_p_nom` method generalised to segments (terminals snap to the DC bus of the voltage, shortest route preferring unused links, each bus pair carries the rating once). Options `reference_year`, `unmatched`, `add_missing`. Default `false`, not in any stage. 2026-11-02. |
| `clean_osm_data`: `drop_duplicate_ids` (upstream candidate) | a cross-border way arrives once per country extract and became parallel lines (PyPSA-Eur's `_drop_duplicate_lines`). Default off, not in any stage. 2026-11-02. |
| `clean_osm_data`: `fix_indirect_circuits` (upstream candidate) | `fill_circuits` wrote cables instead of circuits for a way with several voltages and one total of cables: `voltage=230000;230000, cables=6, circuits=2` became 6 circuits. About 21 % of US and 22 % of NWE AC circuit km (with the duplicates). Default off, not in any stage. 2026-11-02. |
| `build_osm_network`: `geodesic_length` (upstream candidate) | lengths in Web Mercator are stretched by 1 / cos(latitude); HVDC links keep this through clustering. Default off, not in any stage. 2026-11-02. |

## Files

- `config.USW.yaml`, `config.USE.yaml` — US West and US East, full year 2013, cutout `cutout-2013-era5-conus` (shared);
  both `countries: [US]`, cut by state list (section "US West / US East"). The single stage `US` of 2026-09-16 (and its
  January smoke stage) is gone; its config is kept as `baseline/config.US.yaml` for the v0.9.0 baseline and for the
  read-only checks that still read the files of the former US runs.
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
  `logs/catalyst/config.<stage>.yaml`). `now` (since 2026-09-30): `calibration.enable` with `brownfield_only` = the 2024
  system dispatched, `ll v1.0`, `opts 3h` (no CO2 constraint, 3-hourly averaging), `costs.year 2025` for VOM /
  efficiencies (fuel prices come from the calibration tables); `zero`: the same calibration without `brownfield_only`
  and without CO2 prices, `ll copt`, `opts Co2L0-3h` (CO2 limit 0), `costs.year 2050`; both `build_cutout: false`,
  Gurobi 8 threads and the validation rules below. Hourly was tried first (BR: 19.0 M rows × 9.3 M columns, OOM in Gurobi's presolve under the 12 GB cap);
  3-hourly is pypsa-earth's own default (`opts: [Co2L-3h]`). Everything else (countries, cutout, thresholds, clustering, default extendables) is the base stage's.
- `calibration/` + `scripts/build_calibration.py` — the per-country tables of the reference year read by the fork's
  `calibration:` block (`calibration/2024/*.csv`, generated from Ember and GloHydroRes plus the hand-curated
  `fuel_prices_2024.csv`, `fuel_price_regions.csv`, `co2_prices_2024.csv`, `envelope_overrides.csv`); `--check
  <solved network>` prints the residuals per country and fuel. See "Calibration to 2024" at the end.
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
- `technology-assumptions/` — the model's techno-economic inputs in one place: `technology_assumptions.csv`
  (one row per technology: CAPEX, O&M, efficiency, lifetime, existing / pipeline GW, lead time, build limit,
  learning rate + basis, USD2024) and the justification document `build/technology_assumptions.pdf`, whose
  page-1 tables are generated from the CSV (`assumptions.smk`, rules `assumptions_table` / `assumptions_doc`)
  while each technology's subsection title carries a hand-typed CAPEX so that text and table drift visibly.
  `merge_config.py` puts `assumptions.smk` into `custom_rules` of every stage; `run.sh assumptions` builds
  the PDF (also standalone: `snakemake -s assumptions.smk -c1` in that directory). See its README.
- `scripts/check_bus_regions.py [<run> ...] [-v]` — verifies that `resources/<run>/bus_regions/` describes
  `networks/<run>/` (busmap index = simplified buses, busmap values = region names = clustered buses, clustered x/y =
  mean of the members, later networks contain the clustered buses; bus tables only, seconds per run); `run.sh` runs
  it after every prenetwork / scenario stage and logs a `WARNING` line on mismatch. Exit code 1 on mismatch. See
  "Caveats: bus_regions of the base runs".
- `baseline/` (`overlay.{now,zero}.yaml`, `common.yaml`, `prep_region.sh`, `run_overnight.sh`) +
  `scripts/plot_before_after.py` — the same global experiment on PyPSA-Earth v0.9.0 as it comes, and the before/after
  page; see "Before/after the patches".
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
- `run.sh [prestage:<CC>] [<stage> ...]` — the supervisor (default `prestage:USW USW USE`). Stage kinds: a bare
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
bash config-pypsa-earth/run.sh USW
# screening solves + dashboards for all regions, overnight, going on after a failed stage
CONTINUE_ON_FAIL=1 MEM_MAX=12G STAGE_TIMEOUT=4h setsid nohup systemd-inhibit --what=handle-lid-switch:sleep:idle \
  --who=catalyst --why="screening solves" bash config-pypsa-earth/run.sh SG-now SG-zero dashboard:SG BR-now BR-zero dashboard:BR \
  IN-now IN-zero dashboard:IN NWE-now NWE-zero dashboard:NWE USW-now USW-zero dashboard:USW USE-now USE-zero dashboard:USE > models/pypsa-earth/logs/catalyst/driver.out 2>&1 &
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

### Caveats: bus_regions of the base runs `US`, `BR`, `IN` are not those of their networks (2026-09-20)

`resources/<R>/bus_regions/{busmap_elec_s.csv, regions_*_elec_s.geojson, busmap_elec_s_50.csv, linemap_elec_s_50.csv,
regions_*_elec_s_50.geojson}` of the three base runs **do not describe `networks/<R>/elec_s.nc` / `elec_s_50.nc`**
(nor the `_ec` / prepared networks derived from them). Symptom: polygon `US0 28` of `regions_onshore_elec_s_50.geojson`
is Pennsylvania, bus `US0 28` of `networks/US/elec_s_50.nc` is Idaho; `busmap_elec_s_50.csv` has 4738 rows and clusters
`US0 0`–`US0 41`, `US1 0`–`US8 0`, the network has 4740 simplified buses behind clusters `US0 0`–`US0 39`,
`US1 0`–`US10 0`. It is **not a renaming**: the files were written for a different simplified network.

Cause (driver, not model code: `cluster_network.py` is unpatched and writes network, busmap and regions from one
`Clustering` object; pypsa 0.30.3 `get_clustering_from_busmap` keeps the busmap labels as bus names). On 2026-09-19/20
the first screening solves ran with `resources/<R>-now` / `<R>-zero` as a *directory symlink* to `resources/<R>`
(`status.log`: "[US-now] resources/US-now -> resources/US (symlink)"). Their `simplify_network` and `cluster_network`
therefore wrote into `resources/<R>/bus_regions/`. By then the fork had the DC-bus absorption patch of 2026-09-19 (the
two other `simplify_network` patches date from 2026-09-30, after these runs), so the scenario runs' simplified networks
differ from the base runs' of 2026-09-16/17/18: US 4738 vs 4740 buses (buses 2408/2410 DC and 2409 AC near 44.3 °N
71.9 °W and the DC bus 6259 on Long Island gone, AC buses 6258/6262 new there), BR 596 vs 603 (7 DC buses), IN 2253 vs
2258 (5 DC buses). Fewer single-bus sub-networks → a different
cluster count per `country+sub_network` → k-means labels that have nothing to do with the base run's. The base
`networks/<R>/elec_s_50*.nc` and the `_50` files were then `touch`ed at 02:20–02:21 (identical mtimes, contents
unchanged), which hid the mismatch from Snakemake's mtime trigger. `run.sh` gives every scenario run its own
`bus_regions/` since 2026-09-20 (`link_resources`), so `<R>-now` / `<R>-zero`, NWE (base run after the patch), CN, the
rest-of-world runs and every later run are self-consistent — `scripts/check_bus_regions.py` verifies all of them.

Consequences: anything that joins the base runs' `regions_onshore_elec_s_50.geojson` or `busmap_elec_s_50.csv` to
`networks/<R>/elec_s_50*.nc` by bus name assigns the wrong polygon / members for US, BR and IN (e.g. per-region
supply curves such as the planned geothermal ones, region choropleths of base-run results, the fourier site stencils of
`misc-quarter1/fourier`, which avoided the polygons after noticing the symptom). Not affected: the validation
dashboard (`plot_validation.py` reads the solved network and `country_shapes.geojson`, no regions), `check_network.py`
maps, the calibration (tables per country), and every scenario-run result. Rule: **use the regions / busmap of the same
run as the network** (`resources/US-now/bus_regions/` with `networks/US-now/` or `results/US-now/networks/`), and run
`check_bus_regions.py <run>` first. To repair the base runs rebuild them with the current `simplify_network`
(`rm networks/<R>/elec_s*.nc && bash config-pypsa-earth/run.sh <R>`; simplify + cluster + prepare ≈ 5–10 min per
region, the heavy stages are untouched) — the result then matches the scenario runs' bus set as well.

## US West / US East (stages `USW`, `USE`; 2026-11-17)

The contiguous United States were one stage `US` until 2026-11-17. The Western Interconnection and the rest of the
country are coupled by about 1.3 GW of back-to-back converters only, so they are two regions in the model, as they
already were in the archetype classification (`misc-quarter1/country-classification/split_us.py`: US West is the
geothermal-favourable archetype, US East the fossil-heavy brownfield one), in the geothermal supply curves and in the
weather-year sites.

**Definition.** Whole states, because the statistics are by state: `USW` = WA, OR, CA, NV, ID, UT, AZ, NM, CO, WY, MT;
`USE` = the other 37 contiguous states and DC, Texas included; Alaska and Hawaii in neither. 20 and 30 clusters (the
50 of the former stage; a tractability setting). No power is exchanged between the two: lines across the seam are
dropped and the back-to-back ties (which OSM does not have as links) are not modelled. The halves meet only in the
learning market (`run.sh pathway:<scen>:USW,USE,...`).

**Why it is not a config copy.** Both stages are `countries: [US]`: GADM, OSM, powerplantmatching, the demand series and
every statistics table know the country, not the half, and the fork keeps only two-letter codes. In the OSM network the
two halves are one AC component (6,340 of the 6,479 base buses of the former stage), so the seam is cut by geography.
What makes a stage a half:

| What | How | Where |
|---|---|---|
| land | fork option `build_shape_options: gadm_subset` (3148f537) = the GADM level-1 ids of the states: the country shape is their union, the GADM shapes are filtered to them | `config.<R>.yaml`; the list is the single source of the split |
| sea | `clip_bbox`: the box of `USW` ends at 101.5 W (Pacific EEZ only), that of `USE` starts at 107 W (Gulf and Atlantic only) | `config.<R>.yaml` |
| network, bus regions, wind / solar potential and profiles, EGS supply curves | follow the shapes: `clean_osm_data` drops substations outside them and lines with an end outside, the regions and potentials are built on what is left | nothing to set |
| plant list | fork option `electricity: powerplants_within_shapes: 10` (6b2e4dc7): plants more than 10 km outside the shapes are dropped. Without it every US plant is assigned to the nearest bus of the half (the former `US` stage placed the plants of Alaska and Hawaii on CONUS buses this way) | `config.<R>.yaml` |
| wind and solar totals | fork option `estimate_renewable_capacities: stats: statistics` (32e885de): the totals come from the table `renewable_capacities.csv` instead of powerplantmatching's national IRENA file (same numbers for every other stage) | `statistics.yaml` |
| statistics | `catalyst: tables: region: <R>`: `tables.smk` replaces the US rows of a table by the rows of `calibration/<year>/regions/<R>/<table>.csv` where that file exists | `config.<R>.yaml`, `tables.smk` |

In memory (no run), the land and sea of the two halves add up exactly to those of the former stage (7,954 thousand km2
of land, 1,957 of sea), and of its 11,974 plants 3,048 fall in the West (271 GW), 8,693 in the East (994 GW), 262 in
neither (Alaska, Hawaii, one plant with a wrong longitude) and 29 (4.6 GW, plants within 10 km of the seam such as El
Paso's) in both. The 10 km are needed for plants on barrier islands, which are neither in the simplified country shape
nor in the offshore shape (St. Lucie, 1.9 GW of nuclear, was dropped at 0 km).

**Tables of a half** (`scripts/build_region_tables.py`, run after `build_calibration.py` and `build_demand_pathway.py`;
the national tables are not changed, so nothing that sums a table counts the US twice). A half's value is the national
value x the half's share of the country in EIA's state tables of 2024 (`data/validation/eia/state/`, gitignored
downloads from eia.gov/electricity/data/state: `annual_generation_state.csv`, `existcapacity_annual.csv`,
`HS861 2010-.xlsx`); Alaska and Hawaii drop out:

| Table | Value of a half | USW | USE | USW + USE over national |
|---|---|---|---|---|
| `demand.csv` (2024 and every horizon) | share of retail sales; the horizons take the US multiple for both | 784 TWh (17.8 %) | 3,604 TWh (81.8 %) | 0.996 |
| `capacity.csv`, `generation.csv`, `hydro_generation.csv` | share of nameplate capacity / of generation, per fuel group | coal 23 GW, gas 89, nuclear 7, hydro 53, geothermal 2.7 | coal 169 GW, gas 456, nuclear 90, hydro 31, geothermal 0 | 0.98 to 1.00, oil 0.91 (capacity) and 0.69 (generation): Hawaii and Alaska burn oil |
| `generation.csv` column `cf` (wind / solar targets) | from the two rows above | wind 0.314, solar 0.236 | wind 0.344, solar 0.174 | national 0.338, 0.195 |
| `renewable_capacities.csv` | IRENA x the wind / solar capacity share; offshore wind by the states that have some | onshore 32 GW, solar 60, offshore 0 | onshore 120 GW, solar 116, offshore 0.2 | 1.00 |
| `hydro_max_hours.csv` | GloHydroRes plants inside the half's states, the national formula | 1,464 h | 3,000 h (the cap; the Missouri reservoirs) | national 2,002 h |
| envelope tables (`p_min_pu`, `p_max_pu`) | carriers that run flat, at the half's capacity factor | nuclear 0.96, oil 0.27 | nuclear 0.92, oil 0.07 | |

No table per half, the national rows apply: fleet efficiencies, fuel prices, the CO2 price (0; California's and
Washington's carbon markets and RGGI stay out, as before) and the efficiency spread of the tranches.
`merge_config.stage_table(cfg, name)` returns a table as a stage sees it; `clear_market.py` (coverage: `USW` alone 2.5 %
of world demand, `USE` 11.7 %, both 14.2 %), `plot_world.py` (a row per half, its "Ember" bar = the US row split the
same way) and `build_validation.py` use it.

**Validation dots** (`build_validation.py`, `split_parts`): Ember's US values x the half's share (the numbers the half
is calibrated to), EIA's state tables summed over the half's states (the independent source; utility-scale plants,
demand = retail sales without losses), the fuel-price markers of the US unchanged. Prices are per market:
ERCOT and PJM real-time 2024 for `USE`, CAISO day-ahead 2024 (41 USD/MWh, CAISO only) for `USW`
(`manual_points.csv`). The national rows of `manual_points.csv` (EIA 2024, the 2050 outlooks in TWh and GW) describe the
whole country and are shown for neither half.

**Limits.**
- Whole states, not the seam: El Paso (West grid) is in `USE`; eastern New Mexico and eastern Montana (East grid) are
  in `USW`. ERCOT is not modelled apart: Texas is connected to the East by whatever lines OSM shows.
- One hourly demand shape for both halves: the fork has one synthetic series per country, scaled to each half's annual
  demand. The US series is a blend of four time zones; the West's real load runs 2-3 hours behind the East's
  (`REFACTOR_LATER.md` item E).
- The state shares are of utility-scale plants; small-scale solar is not in EIA's state tables (California's share of
  solar is understated by that).
- EIA's "Other" (batteries, purchased steam) is left out of the oil group's share.
- The v0.9.0 baseline (`baseline/`) cannot model a part of a country and keeps the US as one region
  (`baseline/config.US.yaml`); `plot_before_after.py` sums the two halves into one US row for the comparison.
- Not moved to the two stages yet: `scripts/check_grid.py`, `check_fleet.py`, `check_renewables.py` and the model-doc
  figures still read the files of the former `US` runs on disk; `misc-quarter1/weather-years` names buses of the
  archived 50-node US network.
- Of the former `US` runs, only what those scripts read is still on disk (4.3 GB: `resources/US` without its demand
  profiles, `resources/US-now`, `networks/US/base.nc`, `networks/US-now` without `elec_s.nc`, the solved results under
  `results/US-*` and `results/archive/US-*`, the clustered networks of `networks/archive/US-20261020`). Deleted on
  2026-11-17: the `US-smoke`, `US-zero` and `US-myopic` resources and networks, the per-bus demand profiles and the
  unclustered `elec.nc` / `elec_s.nc` that nothing reads. The North-America cutout stays: `NAM` and `CA` use it.

**To build** (launched 2026-11-17 16:00 as one chain with `MEM_MAX=16G`; 22 GB were free, and the whole US needed
10 to 16 GB of memory in its solves, so the default cap of 8 GB is too low):

```bash
bash config-pypsa-earth/run.sh prestage:USW USW USE
```

```bash
bash config-pypsa-earth/run.sh USW-now USW-zero dashboard:USW USE-now USE-zero dashboard:USE world
```

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
- **Caveats** (on top of the general ones): HVDC capacities came from pypsa-earth's per-cable defaults and were
  (until the fix of 2026-10-19, section "HVDC capacities") 3–5× the real ratings (FR–GB 19 GW in the model vs 4 GW; GB–IE 9.4 vs 1; DE–DK 7.8 vs ≈ 2.5; GB–BE 2.7 vs 1;
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
- **Line capacities (checked 2026-10-19):** AC types are taken at the nearest configured voltage
  (`electricity.voltages` [132, 220, 300, 380, 500, 750]) but `s_nom` uses each line's own voltage, so the 1000 kV
  lines get 7.2 GVA per circuit (5 GW at `s_max_pu` 0.7, about the design transfer of China's UHVAC lines) and the
  330 kV lines the 300 kV type (1.1 GVA): acceptable, no change. HVDC was wrong (and in every archetype, not just
  China): see "HVDC capacities" below.
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

## HVDC capacities (2026-10-19)

OpenStreetMap maps HVDC lines with their voltage but, on ways, without their rating (ratings sit on route relations,
which earth-osm does not export). PyPSA-Earth therefore gave every DC line the current of one 500 kV cable type
(`v_nom` x 1.638 kA: 1.31 GW at +-800 kV against 4-12 GW real), and `simplify_links` then summed all segments and
converters of a chain, so the clustered capacities were arbitrary (China 483 GW, India 74 GW, both ~2x the real fleets;
Belo Monte 5.9 instead of 8 GW; NWE interconnectors 3-5x their ratings). Two fork changes (patch table) and one study
table fix this:

- `scripts/build_hvdc_ratings.py` parses Wikipedia's "List of HVDC projects" (wikitext cached in `data/hvdc/`, fetched
  2026-10-19) plus `data/hvdc/manual.csv` (projects the list lacks: Changji-Guquan +-1100 kV 12 GW) into
  `data/hvdc/hvdc_ratings.csv`: the median design rating per country (either terminal) and pole voltage over all
  projects not decommissioned (the list's status colours lag years behind), and `*` rows = world median per voltage.
  E.g. CN 500 kV 3.0 GW, 800 kV 6.4 GW, 1100 kV 12 GW; IN 500 kV 2.5, 800 kV 6.0; BR 600 kV 3.15, 800 kV 4.0;
  US 500 kV 2.4; DE 525 kV 2.0 GW. Screening-grade: one source; a multi-bipole project listed with its total counts
  as one line; one OSM line = one bipole.
- `statistics.yaml` sets `links.dc_ratings` to that table for every stage.
- **Caveat, lines under construction:** OSM carries SuedLink's partly laid 525 kV cables (Brunsbuettel to Bavaria /
  Baden-Wuerttemberg, in service 2028) without a construction tag, so NWE may contain fragments of it in 2024.
- **Rebuild shortcut used on 2026-10-19:** `networks/<R>/base.nc` of US, BR, IN, NWE, CN was rebuilt with
  `--forcerun base_network --allowed-rules base_network` and given back its old mtime, because only the DC link
  capacities changed and none of the shared resources (bus regions, profiles, plants, demand) read them; the overlay
  hardlinks were removed so `run.sh` re-links them.

### Grid corrections and their check (2026-11-02, in the configs, not yet in any solved network)

The options above are on in `config.{US,BR,IN,CN,NWE}.yaml`, `p_threshold_merge_isolated: false` in IN, CN, NWE. Existing networks predate them and
`run.sh` will not rebuild them by itself (`--rerun-triggers mtime input`, and config values are no input): force the rebuild from `clean_osm_data` at the rerun. `scripts/check_grid.py`
applies them in memory to the existing networks and writes `model-doc/build/grid_check/` (about 10 min, read-only). Table:
`data/hvdc/hvdc_project_table.csv` = `build_hvdc_ratings.py --table` from the list, `links_p_nom.csv` (PyPSA-Eur's coordinates),
`project_corrections.csv` (hand-curated; `china_uhv_lines.csv`; coordinates approximate) and `osm_name_map.csv` (OSM way name -> project, hand-curated, including Chinese names). `hvdc_ratings.csv` is unchanged.
Matching is by way name first, read from the raw tables by way id without new Snakemake inputs, so that no rerun is triggered; note that earth-osm keeps many names and ratings in the column `other_tags`. Terminals pick the route, and continue through unnamed ways where needed.

| HVDC | US | BR | IN | CN | NWE |
|---|---|---|---|---|---|
| GW km now / listed | 1.50 | 1.05 | 1.12 | 1.08 | 3.62 |
| GW km corrected / listed | 0.98 | 1.01 | 0.99 | 0.95 | 0.76 |
| routes within 10 % of listed length | 6/7 | 6/6 | 9/9 | 25/32 | 7/20 |
| in-service projects found + added, of | 7 of 7 | 6 of 6 | 9 of 9 | 32+5 of 40 | 20+4 of 27 |

Seven of eight NWE borders within 10 % (France-GB 4.0 GW; Germany-Denmark is off by exactly SylWin1). Terminals alone gave CN 1.03 but about a quarter of named km on the wrong parallel line, which name-first removes. Rating tags (unused by the matching, 63 % of NWE km) agree on 22 of 26 links. NWE's 0.76 and its route score come from offshore export cables that OSM only partly maps. CN: four in-service lines are only partly named or connected (65-86 % of listed length); Baihetan-Jiangsu, Baihetan-Zhejiang and Hubei-Shanghai are added as straight links.
AC circuit km corrected vs published: India 461,800 / 466,560 (CEA, May 2024), Germany 32,600 / about 37,000, Brazil 173,500 / about 157,000 (projected
from ONS 2020); the network now holds 500,100, 79,800 and 181,900. No published total was found for the US or China.
Caveats: stored lengths of split lines are right but in Mercator, while their geometry may be that of the whole way, so `check_grid.py` uses the geometry only where the two agree;
`underwater_fraction` reads that same geometry and may be affected. Links added by `add_missing` have no geometry and get `underwater_fraction` 0. `reference_year` is one year, so myopic horizons would need more.
Effects on results are unknown. Merge fix (`p_threshold_merge_isolated: false`): structurally no isolated India pocket; shedding untested.

**India: how permissive the modelled grid is** (checked 2026-11-11 on the 50-node `IN-now` and `IN-zero` solves, which
predate the corrections above; buses mapped to the five regional grids by GADM state). Inter-regional AC lines sum to
475 GW of s_nom (333 GW after s_max_pu 0.7) plus 29 GW of inter-regional HVDC, against 120 GW of inter-regional
transmission capacity reported by CEA / MoP for mid-2025 (143 GW planned for 2027, 168 GW for 2032). The operational
limit is lower still: Grid-India's Northern Region import TTC was 20-26 GW in March 2025, while the model's corridors
into the North carry about 180 GW. In the 2024 dispatch the North imports 105 TWh net (real FY25: 36 TWh) and the
North-East imports 40 TWh (in reality an exporter); one of 118 lines is ever at its limit and nodal prices are equal
(load shedding sets one price everywhere). In the zero-carbon 2050 solve regional net imports peak at 83-138 GW per
region. Data on the real system: exchange congestion is small (CERC 2024-25: 0.48 % of cleared exchange volume lost to
congestion, regional prices nearly equal), but exchanges trade only the ATC left after long-term schedules; Ember
counts 2.3 TWh of solar curtailed May-Dec 2025, about 2-3 % of solar output, for system flexibility (coal minimum
load), not transmission; transmission curtailment is local, e.g. about 4 GW of Rajasthan projects on temporary
access, up to ~50 % at midday. So the model's inter-regional grid is 3x the rated and 5-9x the operational capacity.

## Screening solves (stages `<R>-now`, `<R>-zero`, `dashboard:<R>`; 2026-09-19/20)

*This section describes the out-of-the-box definition of `now` and `zero` used until 2026-09-30 and the results it
gave; since then both overlays start from the calibrated 2024 system of the last section ("Calibration to 2024"),
and `now` is a pure dispatch of it.*

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
  every intact target. **Own `renewable_profiles/` too (2026-11-18)**: `profile_hydro.nc` holds the inflows by
  row number of the plant list, and a pathway stage builds its own list (plants under construction, lifetimes
  from the cost table), whose rows are others. With the directory shared, the pathway stage rewrote the base run's
  file: after the test stage `USW-tzone` the next build of `USW-tsub` (base list) failed in `add_electricity` on run-of-river
  plants missing from the inflows, and of the 354 row numbers the two lists had in common none was the same
  plant, so a region without such a gap would have got the inflows of other plants without an error.
  `build_resource_cells` takes the plant list as well, so `cells_<tech>.nc` was rewritten too (same content, new
  time stamp: the base run's resource classes looked outdated). `run.sh` (`link_profiles`) now gives every stage
  its own directory: symlinks to the base run's wind and solar profiles, and for `profile_hydro.nc` and
  `cells_<tech>.nc` a hard link to the base run's only while the stage has the base run's plant list (Snakemake
  removes an output before rebuilding it, so a stage with its own list gets its own files). A stage directory of
  the old layout is converted when the stage is next run. Reach on 2026-11-18: the archetypes BR, CN, IN, NWE, USE
  and JP had one hydro list per region, nothing mixed; USW was restored (hydro profile and cells rebuilt from the
  base list, time stamps set back to before the base network of 2026-11-17, inflow 151.24 TWh as in that
  network); in MA and MA10 the base run's `profile_hydro.nc` is the one of the test stages `t*` of 2026-11-18
  (both base runs predate the sweep of 2026-11-16 and rebuild from `base_network` on at their next run, plant
  list and inflows included); in CA and OCE the file matches the `now` / `zero` stages and only the void myopic
  test stages of October do not match it.
  Solver: `gurobi-default` (barrier, no crossover, `BarConvTol 1e-6`), 8 threads via the
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

## Rest of world: single-node countries (stages `<G>`, `<G>-now`, `<G>-zero`, `world`; 2026-09-29/30)

Every country that is needed, on top of the six archetype regions, to pass **99.5 % of world electricity demand**,
modelled out of the box as **one islanded node**: no internal grid, no trade, the mix now and carbon-neutral. One page
for all of them, `results/catalyst/validation_world.{png,pdf,csv}` (copied to
`misc-quarter1/pypsa-earth-out-of-the-box-validation/figures/`), instead of a dashboard per region.

- **Selection** (`scripts/select_countries.py`, output `data/row_countries.csv`): Ember demand, latest year ≤ 2024
  (2025 covers only 91 countries), world = 30,919 TWh; the 17 archetype countries are 62.4 %; the rest is added by
  descending demand until 99.5 % — **115 countries, down to Jamaica (4.9 TWh), 99.51 %**. Skipped and replaced by the
  next in line: HK (49 TWh) and MO (6) have no GADM 4.1 file of their own (they are provinces of `gadm41_CHN`, i.e.
  inside the CN run, where GEGIS gives them zero load), XK (7) has no load series in GEGIS nor DemandCast. Alaska and
  Hawaii (the US run is CONUS) are the only other gap, ≈ 0.05 %.
- **Groups**: one pypsa-earth run per prebuilt cutout, the countries of a run sharing weather data and the OSM, GADM,
  WorldPop and demand pipeline: `EUR` (23, PyPSA-Eur cutout), `MEA` (18, `westasia`), `AFR` (23, `africa`), `ASI`
  (25, `asia`), `NAM` (12, `northamerica`), `SAM` (9, `southamerica`), `OCE` (AU + NZ, `oceania`), `RU`
  (`northeurasia`), `CA` (`northamerica`), `IS` (CDS build, 44 × 16 cells: no prebuilt cutout reaches Iceland). The
  continental cutouts are hardlinked from `~/Desktop/earth/pypsa-earth/cutouts/` by `prestage.sh`, which now also
  resolves the Geofabrik extracts of any group through earth-osm (multi-country extracts such as `gcc-states`,
  `haiti-and-domrep`, `central-america` for TT included). `config.<G>.yaml` is generated, do not edit by hand.
- **One node per country, native levers**: `clustering.alternative_clustering: true` + `gadm_layer_id: 0`.
  `build_bus_regions` then keeps one onshore region per GADM country shape (offshore regions stay per substation), so
  the renewable profiles, plants and the national load are computed per country, and `cluster_network` maps every
  AC bus of a country onto one (`busmap gadm_0_AC`) — islands and unmapped OSM fragments are lumped into it.
  `threshold_voltage` 100 kV (archetypes 200 kV) so that 110–150 kV systems (JM, CY, TT, …) have a bus at all; it
  costs nothing because the grid is collapsed. **Islanded**: `catalyst.extra_opts: ATKc` in the group config,
  prepended to the overlay opts by `merge_config.py` (`ATKc-3h`, `ATKc-Co2L0-3h`); `prepare_network` removes every
  cross-border line and link, the solved networks have zero lines. The overlay target of a single-node group is the
  solved network itself (no per-network validation page).
- **Russia and Canada** are the exception: atlite reads the 100 m Copernicus land-cover raster over each region's
  bounding box at native resolution (RU 160° × 37°, CA 90° × 32° → 3–6 × 10⁹ pixels), which no excluder resolution
  fixes. They use the archetype recipe instead — Voronoi regions per base bus at 200 kV, every isolated sub-network
  fetched into the backbone (`s_threshold_fetch_isolated: 1.0`), `clusters: [1]` (like SG) — plus
  `crs.area_crs: EPSG:6933` (cylindrical equal-area) because with Mollweide the padded bounding-box corner of 4 wide
  northern Voronoi cells of CA falls outside the projection's ellipse (`pad_extent` → NaN transform).
- **Demand**: GEGIS SSP2-2.6 2030 like the archetypes; where GEGIS is empty (PR, LA, BT, AF, UG, PS) the new
  `load_options.fallback_source: demcast` takes the DemandCast 2013 series (historical level, so LA 4 TWh vs 16 in
  Ember, BT 2 vs 12). Caveat found on the way: the GEGIS `Africa.nc` (what the fork reads) holds series for 19
  countries that its `.csv` twin leaves empty, some implausible — DJ 75 TWh, GQ 158, SZ 73, ML 19 against 0.8, 1.5,
  1.6, 5.5 in Ember; Mali is the only one in the modelled set. GEGIS is also far off for LB (5.0 × Ember), VE (1.8 ×),
  CM, LY, ZA, UA, YE, TT, SV (1.4–1.7 ×) and CG, KH (0.5 ×); demand-weighted over all 132 countries the model load is
  0.97 × Ember 2024 (median per country 1.05).
- **Fork patches added for this** (all `(upstream candidate)`, see the table at the top): NaN-column repair of the
  Asia/Oceania cutouts (JP, KR, AU, NZ had NaN profiles otherwise), DemandCast fallback, `excluder_resolution`
  (the group configs use 1000 m; at 100 m Argentina's whole-country mask alone OOM-killed the rule at 12 GB — and the
  one-worker `multiprocessing.Pool` then hung for 50 min, hence the in-process patch), the backbone exclusion in
  `merge_into_network` (with `s_threshold_fetch_isolated: 1.0` the backbone's own lines were deleted: RU came out of
  `simplify_network` as 1,946 one-bus sub-networks), and no bus merging across countries through transformers
  (Aldeadávila: PT's representative 220 kV bus was mapped onto the ES 400 kV bus and Portugal's 56 TWh landed in
  Spain, Portugal with no load at all). Eleven patches → sixteen.
- **Run** (2026-09-29 15:34 → 09-30 05:06, `CONTINUE_ON_FAIL=1 MEM_MAX=12G`, one 16-core laptop): prestage of all
  groups in parallel with the SAM pilot (≈ 40 GB of Geofabrik downloads, filtered to 60 MB), then
  `<G> <G>-now <G>-zero` per group and `world`. Prenetwork time is `build_renewable_profiles` reading the whole
  continental cutout per technology (5 passes); the solves are 1–5 min each (one node per country, 3-hourly).
  `memory.peak` reaches the 12 GB cap in the SAM/AFR/OCE/ASI prenetworks without an OOM kill: page cache of the
  18–28 GB cutout files counts against the scope, reclaimable (`max` events, no `oom`).

  | group | prenetwork | now | zero | group | prenetwork | now | zero |
  |---|---|---|---|---|---|---|---|
  | SAM | 66 min / 12.0 GB | 2 min / 2.2 GB | 1 min / 2.1 GB | OCE | 118 min / 12.0 GB | 1 min / 1.2 GB | 1 min / 1.1 GB |
  | MEA | 41 min / 9.1 GB | 2 min / 3.2 GB | 2 min / 3.4 GB | ASI | 162 min / 12.0 GB | 3 min / 4.5 GB | 3 min / 4.6 GB |
  | EUR | 91 min / 8.9 GB | 4 min / 4.5 GB | 4 min / 5.1 GB | RU | ≈ 55 min / 12.0 GB | 2 min / 3.8 GB | 2 min / 4.3 GB |
  | AFR | 44 min / 12.0 GB | 2 min / 3.7 GB | 2 min / 3.7 GB | CA | ≈ 45 min / 11.4 GB | 5 min / 2.0 GB | 5 min / 2.5 GB |
  | NAM | 24 min / 10.6 GB | 2 min / 2.5 GB | 2 min / 2.4 GB | IS | 165 min (CDS queue) / 2.0 GB | 1 min / 0.8 GB | 1 min / 0.8 GB |

  Failures on the way, each fixed by one of the patches above and re-run: SAM (OOM + hang, 100 m excluder), CA
  (Mollweide NaN), RU (backbone deleted), EUR re-run from `simplify_network` for Portugal.
- **What the world page shows** (`results/catalyst/validation_world.png`; per country (NWE as one row of 12) three 100 % bars: Ember actual,
  model now, model zero; the fossil share and the fossil CO2 in Mt right of the bars; `validation_world.csv` holds the
  numbers):
  1. Aggregate over the 132 countries (30.8 / 29.9 / 30.1 TWh × 10³ generation): Ember coal 34 gas 22 oil 3
     nuclear 9 hydro 14 wind 8 solar 7 %; model now coal 39 gas 13 nuclear 12 hydro 10 wind 11 solar 15 %; model zero
     wind 33 solar 53 hydro 10 nuclear 2 %, 1.6 % of demand shed.
  2. **Fossil share** now vs Ember: 46 of 132 countries within 10 pp, 79 within 20 pp; demand-weighted mean absolute
     deviation 12 pp, mean signed deviation −8.5 pp — the model is *cleaner* than reality because `now` builds solar
     and wind at 2025 costs with no CO2 cap (as in the archetype runs; see observation (2) above) and because gas is
     under-dispatched (13 % vs 22 %) at the single global fuel price. Largest misses among countries above 100 TWh:
     TW −48 pp, AR −42, IR −38, SA −37, IQ −36, EG −31, BD −26 (gas systems replaced by solar); ES +29, AU +25, DE +24,
     TR +21, PL +20, IT +20 (coal fleets of ≈ 2022 still dispatched, hydro/wind under-represented). Nuclear is right
     almost everywhere (123 within 10 pp, 2022 fleet incl. Germany's last reactors); hydro is low by 5.5 pp on average
     (VE −45, CR −40, CM −38, NP −38, SD −33, KG/TJ −31/−33: 6 h reservoirs + inflow calibration, as noted for BR).
  3. **Zero-carbon runs** are solar + wind + batteries everywhere (H2 stores only where land is scarce). 473 TWh
     (1.6 %) of demand is shed, concentrated in **islanded, land-constrained systems**: SG 96 %, BH 39, LB 37, IL 34,
     BN 34, PS 25, TW 23, MK 20, CY 17, KR 14, SV 14, QA 12, PR 10, IT 9, KW 9 — the systems that in reality rely on
     imports or on firm capacity the default palette does not contain. This is the islanded assumption showing, not a
     model error; it marks where the study's advanced-technology / import options matter most.
  4. **Power-sector CO2** (fossil combustion; Ember's "Fossil" aggregate vs the model's direct emissions, Mt next to
     the Ember and now bars, log-log scatter in the header): **14.1 Gt actual vs 12.8 Gt modelled** over the 132
     countries (−9 %). Per country the spread is wide — 16 of 126 within ±20 %, 49 within ±50 % — and it follows the
     dispatch biases of (2): the gas systems come out at a quarter to a half of their emissions (DZ 0.22 ×, AR 0.26,
     KW 0.29, IQ 0.30, IR 0.32, SA 0.36, EG 0.42; CA 0.55, MX 0.64, RU 0.66), the big coal systems roughly right (CN
     0.77, IN 0.86, US 1.14, JP 1.04, ID 1.07), the European and other lignite/coal fleets far too high (DE 2.6 ×,
     PL 2.4, ZA 1.8, IT 1.7, TR 1.6, AU 1.5, KR 1.5) — the ETS/carbon-price-free, single-fuel-price dispatch of the
     ≈ 2022 fleet. Ember's total power-sector figure is higher still (life-cycle factors for bioenergy, wind, solar,
     nuclear, hydro), which is why the fossil aggregate is the comparison.
  5. In `now` the model sheds only in NP 5 %, PR 5 %, LB 2 %, BT 1 % (DemandCast-scale loads on tiny OSM fleets).
  6. The per-country "grey line" (Ember demand | model load) makes the demand input the first thing to fix before any
     country result is quoted: GEGIS 2030 is a projection with the outliers listed above, DemandCast is the 2013 level.

## Calibration to 2024 (stages `<R>-now` / `<G>-now` re-run as a dispatch of the 2024 system; 2026-09-30)

The world page of the previous section showed the out-of-the-box `now` solves to be only broadly right:
demand-weighted mean absolute share errors coal 10.9 pp (too high), gas 11.7 pp (too low), solar 9.9 pp (too
high), hydro 3.6 pp (too low), fossil CO2 12.8 vs 14.1 Gt. A fleet-vs-dispatch check on the six archetype networks
(model GW / TWh / capacity factor per fuel against Ember 2024) showed that **the installed fleet was right and the
dispatch and the scenario definition were wrong**:

| # | cause | evidence |
|---|---|---|
| 1 | `now` was a brownfield *expansion* at 2025 costs, not a dispatch of the 2024 system, and — a fork bug fixed by the seventeenth patch — existing wind/solar from IRENA never became the `p_nom_min` of the extendable generators, so the optimiser rebuilt the VRE fleet from ≈0 | US solar 511 GW built vs 178 installed; BR wind 111 vs 33 GW; SA / IR / EG / IQ solar 33-37 % vs 0-3 %; Brazil spilled 172 of 361 TWh of hydro inflow |
| 2 | one global fuel price and no CO2 price: technology-data 2025 gives coal 30, lignite 13, CCGT 48 EUR/MWh, so coal ran before gas everywhere; with the EU ETS (≈65 EUR/t) or Henry Hub gas (≈7 EUR/MWh_th) the order flips, as it did in 2024 | coal CF 0.86-0.91 vs 0.38-0.40 in US, DE, PL, NL; gas CF 0.10-0.18 vs 0.28-0.39; NWE CO2 871 vs 400 Mt |
| 3 | biomass dropped (powerplantmatching's new fuel-type labels; sixteenth patch) | 0 % everywhere vs 7 % NWE, 8 % BR |
| 4 | stale retirements and fleet gaps in powerplantmatching (GB coal 7.9 GW vs 0, DE nuclear 9.6 GW vs 0, US gas 471 vs 546 GW, IN oil 51 vs 19 GW, Japan's idled reactors listed as operating) | GB coal 47 TWh vs 2, DE nuclear 74 vs 0, JP nuclear 24 % vs 8 % |
| 5 | demand from GEGIS SSP2 2030 / DemandCast 2013 rather than 2024 | CN 8254 vs 10070 TWh, NWE 2206 vs 1974, ZA 355 vs 246 |
| 6 | hydro reservoirs of 6 h (`data/hydro_capacities.csv` covers Africa only) and a natural-hydro fleet that powerplantmatching under-reports where pumped storage dominates (DE 0.66 vs 5.5 GW) | BR / CA / NO / CO / VE hydro 5-45 pp low |
| 7 | the *existing* fleet carried technology-data's *new-build* efficiencies (CCGT 57 %, coal 36 %, lignite 33 %) and one generator per bus and carrier, so the merit order was one step per fuel and switched all-or-nothing | with the ETS alone, DE / PL coal went to CF 0.01 and GB ran its CCGTs at CF 0.68 to export 138 TWh |
| 8 | cross-border capacity from OSM thermal ratings, 3-7 × the real NTCs (DE-PL 20 GW vs ≈3, FR-GB 19 GW DC vs 5) | model net imports DE 117 TWh (Ember 26), PL 100 (2), GB −138 (+33) |

**Is coal dispatchable or baseload?** In the model coal was fully flexible (no `p_min_pu`), but that was not the
error: without a CO2 price it sat at the *bottom* of the merit order and ran at CF 0.9, so a must-run floor would
have changed nothing. The flexibility assumption only becomes the second-order determinant once #2 is fixed —
with gas cheaper than coal, a single-efficiency coal fleet drops to CF ≈ 0 where the real one ran at 0.38 (CHP and
district heat, ancillary services, and a 33-46 % efficiency spread across vintages that makes coal-gas switching
gradual). That spread is now represented explicitly (#7: three efficiency tranches per generator); a must-run
floor per country and carrier is available in the same table (`p_min_pu`) but was not needed for the archetypes.

### Where the statistics enter (calibration at the source, since 2026-10-19)

Genuine defects are fixed at their source, one `(upstream candidate)` commit each (patches 16 and 17 in the table
above). The 2024 statistics themselves also enter **where each data vector enters the workflow**, through generic,
config-gated fork options (each documented in `models/pypsa-earth/config.default.yaml`, off by default) fed by the
per-country tables under **`config-pypsa-earth/calibration/2024/`**, which `scripts/build_calibration.py` derives from
Ember (`data/validation/yearly_full_release_long_format.csv`, latest year ≤ 2024 per country), IRENA (through
powerplantmatching), GloHydroRes and three hand-curated tables. **`statistics.yaml`** wires them in;
`merge_config.py` puts it under every stage config (`statistics.yaml` < `config.<R>.yaml` < `overlay.<scen>.yaml`).
Since 2026-11-15 each option of the table is its own fork commit (`git log --grep 'calibration at the source'`:
twelve option commits, the tranche marginal cost, and the removal of the superseded steps from
`calibrate_network.py`); before, one commit held them all.

**Options are switches, tables are rule inputs (2026-11-16).** No fork option carries a file path any more
(`REFACTOR_LATER.md`, item 1). An option is `true` / `enable: true` / the keyword `statistics`, and its rule reads
the table from **`resources/<run>/statistics/<name>.csv`** (`STATISTICS` in the fork's Snakefile; the fork's own rule
`copy_statistics` fills it from `data/statistics/`). In this project **`tables.smk`** (custom rule
`catalyst_statistics`, in every stage config) writes that directory: `demand`, `capacity`, `efficiency`,
`generation`, `hydro_generation`, `hydro_max_hours`, `fuel_prices`, `co2_prices`, `net_imports` from
`calibration/<year>/`, `demand_<horizon>` from `calibration/<horizon>/demand.csv`, `conventional_<carrier>_<attr>`
from `calibration/<year>/envelope/<variant>/`, `dc_ratings` and `dc_projects` from `data/hvdc/`,
`supply_curve_egs` from `misc-quarter1/geothermal/build/egs_potential.csv`; the palette's `cost_overrides_<year>`
come from `technology-assumptions/assumptions.smk`. Year and variant are plain values of the stage config:
`catalyst: tables: {year: 2024, demand_year: 2050}` (defaults 2024; `overlay.zero.yaml` sets the demand year) and
`catalyst: envelope: nofloor`. Tables are copied with their modification time, so shared outputs of the base run
do not look outdated, and `run.sh link_resources` never shares `statistics/` between stages. Checked on Singapore:
the 2024 prenetworks and the pathway's prepared, brownfield and solved networks of 2025 and 2030 are identical with
the old path-valued options and with the switches. In the table below, "fork option" is the switch and "table" the
source of the table.

| data vector | upstream source (first set) | where it now enters | fork option | table |
|---|---|---|---|---|
| annual demand | GEGIS SSP2-2.6 **2030** profiles (weather 2013) | `build_demand_profiles`: national series scaled before it is spread over the buses | `load_options.annual_totals` | `demand.csv` (Ember) |
| demand per myopic horizon | — | `build_demand_profiles_horizon` (same rule per year); `add_brownfield_elec` swaps the loads, aggregated through the busmaps | `load_options.horizon_totals` | `calibration/<year>/demand.csv` (demand pathway) |
| thermal, nuclear, geothermal, hydro capacity | powerplantmatching (GEO, GPD, GEM, EESI) | `build_powerplants`: plant list scaled per country and fuel group (location, vintage, retirement year kept); statistic 0 removes the group; a group without plants is added at the country's thermal sites ∝ capacity, with the site's commissioning year and no retirement year; plants after 2024 left out | `electricity.powerplants_statistics` | `capacity.csv` (Ember: GEM, IRENA) |
| wind and solar capacity | plant list, topped up to IRENA 2023 | `add_electricity` (`estimate_renewable_capacities`): IRENA **2024**, Ember's own source for them; plant list scaled **down** where above | `stats: irena`, `year: 2024`, `scale_down: true` | IRENASTAT (powerplantmatching) |
| wind and solar capacity factor | atlite ERA5 2013 | `add_electricity`, where profile and fleet first meet: profiles × target / fleet CF per country and group, ×0.6-1.4 | `electricity.capacity_factor_targets` | `generation.csv` (Ember) |
| hydro energy | atlite runoff, rescaled to IRENA 2023 × 1.1 | `build_renewable_profiles` hydro normalisation: Ember 2024 TWh, one capacity factor per country (each plant keeps its runoff profile; pumped storage left out); multiplier 1.0 | `normalization: {method: custom, distribute: capacity}` | `hydro_generation.csv` (Ember) |
| reservoir hours | `data/hydro_capacities.csv` (Africa) or 6 h | `add_electricity.attach_hydro` | `hydro_max_hours: statistics` | `hydro_max_hours.csv` (GloHydroRes) |
| plant efficiency | technology-data per carrier (new-build values); the plant list's own value was dropped | `add_electricity.load_powerplants`: the plant's efficiency, else the table, else technology-data; group and cluster means capacity-weighted | `electricity.powerplants_efficiency` | `efficiency.csv` (fleet values; coal / oil implied by Ember CO2, gas per carrier) |
| fuel prices | one global price per fuel (technology-data) | `add_electricity`, where the marginal cost is formed: VOM + fuel price of the plant's country / plant efficiency | `costs.fuel_prices`, `costs.fuel_map` | `fuel_prices.csv` |
| operating envelope (floor, availability) of today's fleet | none (nuclear: IAEA availability) | `add_electricity` `conventional:` per-country tables under `existing:` (new builds keep the palette's values); must-run ≤ 90 % of the lowest load | `conventional: <carrier>: existing:`, `electricity.must_run_cap`, `nuclear_p_max_pu: false` | `envelope/{floor,nofloor}/<carrier>_<attr>.csv` |
| CO2 price | none (`Ep` global) | `prepare_network`, where upstream adds emission prices | `co2.emission_prices_by_country` | `co2_prices.csv` |

What remains in `scripts/calibrate_network.py` (`calibration:` block, `prepare_network` / `solve_network`) acts on the
clustered network because it is a representation or a constraint, not data: the three efficiency tranches per
fuel-burning generator (the fuel part of the marginal cost follows each tranche; since 2026-11-16 the spread is
per carrier and measured, `calibration: efficiency_spread: {coal: 0.08, lignite: 0.04, CCGT: 0.08, OCGT: 0.14, oil:
0.14}` in `statistics.yaml` = the spread between the best and the worst third of the US fleet of 2024 from EIA-923 /
EIA-860, `scripts/build_efficiency_spread.py [--check]`, `data/validation/efficiency_spread.csv`; before, 0.15 for
every carrier, an assumption), the `brownfield_only` freeze of
the `now` dispatch, the net-import band and the soft coal / gas energy bands of `now`.

**Until 2026-10-19** all of this was one module that rewrote the clustered network in `prepare_network` (and the
demand again in `add_brownfield`), chosen because an iteration then cost minutes instead of a base-network rebuild.
It set several vectors two or three times (plants: powerplantmatching → Ember; wind / solar: plant list → IRENA 2023
→ Ember; hydro: runoff → IRENA × 1.1 → Ember; demand: GEGIS 2030 → Ember 2024 → horizon) and could not go upstream,
so it was replaced. The price: a change of the plant, hydro or demand tables rebuilds from `build_powerplants` /
`build_renewable_profiles` (hydro only) / `build_demand_profiles` on, a change of efficiencies, envelopes, fuel
prices or capacity-factor targets from `add_electricity` on.

`scripts/check_sources.py <stage> ...` checks the statistics where they arrive (demand profiles, plant list, hydro
inflow, efficiencies and marginal costs in `elec.nc`); `scripts/build_calibration.py --check <solved network> ...`
prints, per country and fuel, model vs Ember share, capacity factors and every row more than 10 pp off.

### Iterations on NWE (12 countries, 50 nodes; each ≈ 4 min)

1. **Prices, fleet, demand, hydro energy, flat inflexible carriers, brownfield-only.** Merit order flipped as
   intended, but all-or-nothing: DE coal 0.4 % of generation (Ember 21 %), PL coal 1 % (54 %), GB gas 50 % (30 %)
   with 138 TWh of exports; net imports DE +117 / PL +100 TWh against Ember +26 / +2 (causes #7 and #8).
2. **+ fleet efficiencies and three tranches, + net-import band.** DE coal 23.4 % (21.4), gas 15.6 (15.8), solar
   15.1 (15.0); PL coal 62.7 (54.3); FR nuclear 72 (68). Left: wind CF 0.45 in GB / 0.37 in IE / 0.38 in DK against
   0.30 / 0.27 / 0.31 observed (atlite without losses, weather year 2013), DE hydro 5.8 TWh of a 23.8 TWh inflow
   (0.66 GW natural hydro in powerplantmatching), oil 0 everywhere.
3. **+ wind/solar capacity-factor correction, hydro capacity to Ember, Other Fossil flat.** No country-fuel row is
   more than 10 pp off; DE is within 1.2 pp on every fuel (coal 21.7 vs 21.4 %, gas 14.7 vs 15.8, wind 28.9 vs 28.6,
   solar 15.1 vs 15.0, hydro 4.7 vs 4.8, oil 3.9 vs 4.1, biomass 10.9 vs 10.3), GB within 1.6 pp (gas 28.8 vs 30.4,
   wind 30.2 vs 29.3, nuclear 15.4 vs 14.3), AT within 2.5 pp, no load shedding anywhere.
4. **The other archetypes and the single-node groups** with the same tables: IN within 2.5 pp, CN coal +5 / gas −3,
   BR gas +6 / hydro −5, SG within 3; but US coal 3.8 % vs 14.9 % (the fleet runs self-scheduled and on regional PRB
   coal that a national price cannot see), and among the 115 single-node countries 20 country-fuel rows more than
   10 pp off, nearly all coal above its observed capacity factor where policy, contracts or fuel supply hold it back
   (KR 0.87 vs 0.53, JP, ID, PK, UZ, AU, CL) and, the other way round, geothermal absent where Ember reports its
   generation but no capacity (IS, NZ, CR, NI, SV). Also: hydro spilled where the atlite basin inflow of a plant
   exceeds what it can pass (US 108 of 196 TWh); the islanded groups went infeasible where the flat must-run of a
   heavy-fuel-oil island (CY) or a nuclear fleet (SK) exceeded the night load.
5. **+ annual energy bands, hydro at a uniform capacity factor per country, capacity back-fill, must-run
   safeguard, implied fleet efficiencies, `ll copt`.** An hourly cap on coal would starve the peaks, so the lever is
   an *annual* band per country and fuel group, added as a solve-time constraint like the net imports: coal and gas
   within ±10 % of Ember (no floor for countries whose generation exceeds their demand, none where the fleet cannot
   deliver it). The bands are **soft** — a slack variable priced at 200 EUR/MWh — because a hard cap on gas turned
   every shortfall elsewhere (hydro spill, curtailed wind) into load shedding (Brazil shed 45 TWh with hard bands). The country's hydro energy is spread over its plants in proportion to capacity; Ember capacity rows
   that are missing although the fuel generates are back-filled at a typical capacity factor; a country's must-run
   total is capped at 90 % of its minimum load; the fleet efficiencies of coal, gas and oil are the ones implied by
   Ember's per-fuel CO2 (intensity × generation / emissions, e.g. gas 0.28-0.35 in the Gulf and CIS, 0.46 in DE,
   0.37 in the US; coal 0.35-0.37) so the model's direct emissions follow Ember's accounting; and lines may be
   reinforced at cost (`ll copt`), because the OSM ratings × 0.7 leave some clusters structurally short of their
   load (a US cluster with 30 GW of load, 21 GW of plant and 3 GW of lines shed in every hour under `v1.0`).
   Buses without any line or link — islands of the raw OSM topology that survived clustering, 8 in the US and 10
   in India, 63 TWh of shedding in one Indian one — are attached to the nearest connected bus of their country by
   a lossless link in `brownfield_only` mode (with expansion they had built their own peakers).

### Result (2026-09-30, all 16 `-now` stages, world page `results/catalyst/validation_world.{png,pdf,csv}`)

Demand-weighted mean absolute error of the generation share per fuel over the 121 rows (132 countries), model
`now` vs Ember 2024, out of the box → calibrated: **coal 10.9 → 1.8 pp, gas 11.7 → 1.6 pp, solar 9.9 → 0.2,
hydro 3.6 → 1.2, wind 4.4 → 0.4, nuclear 2.8 → 0.5, oil 2.6 → 0.5, biomass 2.3 → 0.2**. Rows within 5 / 10 / 20 pp
of Ember's fossil share: 24 / 42 / 72 → 82 / 102 / 113. Fossil CO2 12.8 → 13.8 Gt against Ember's 14.1 (the rest is
the intensity convention: technology-data's 0.336 t/MWh_th for every coal vs Ember's fuel-specific factors, and the
clipping of implied efficiencies). Load shedding 0.26 % of world demand, all of it in single-node countries that
import a large share of their electricity or export most of it (AF 81 %, PS 73 %, BT 36 %, NP 34 %, HR 22 %, NI 22 %,
CM 18 %, UG 16 %, KH 16 %, EE 15 %, MN 15 %, KE 14 %, CR 12 %) — an islanded node cannot represent them, and their
`now` bars should be read as "domestic fleet only". Archetypes: US within 1.5 pp on every fuel (coal 13.3 vs
14.9 %, gas 44.1 vs 42.6, nuclear 18.6 vs 17.8, hydro 5.1 vs 5.4, wind 10.1 vs 10.3, solar 6.9 vs 6.9; shedding
0.1 %), NWE / DE within 0.7 pp, GB 2.3, IN 2.0 (shedding 1.2 %), CN coal +2.1, BR gas +5.6 / hydro −4.6 (the
reservoirs still spill 7 % of the inflow), SG 2.3. Country-fuel rows still more than 10 pp off after the calibration,
all in the single-node groups: AF, PS, LT, EE, LV, PT, HR, SY, LB, UY, HN (importers: gas or coal fills what imports
supply), LA, KG, KP, ZW, AO, SD, CD (hydro exporters or hydro below the Ember energy where the single node's capacity
factor is capped), SE wind −11 (2013 weather year), AM gas −11.

Not touched: the `-zero` scenario now starts from the same calibrated 2024 system (demand, fleet, hydro, prices,
envelopes; expansion allowed, no CO2 price) but its runs had not been repeated when this was written — see the
world page's notes box for the state of the `zero` bars.

### Fixed: emissions-implied gas efficiencies were biased low (found 2026-10-14, fixed 2026-10-19)

`build_calibration.py` sets the coal / gas / oil fleet efficiency to combustion intensity × Ember generation ÷ Ember
CO2 (iteration 5 above). Ember's CO2 is not measured: it is generation × emission factors, and per Ember's methodology
(files.ember-energy.org, "ember_electricity_data_methodology.pdf") those factors are **life-cycle** for the fossil
rows too: coal from UNECE (Gibon et al. 2022) blended by GEM coal grade, gas from Jordaan et al. 2022 country factors
incl. upstream methane. The upstream part is read as extra fuel burnt in the plant.

| country | Ember gas t/MWh_el | implied gas eff. | implied coal eff. |
|---|---|---|---|
| AU / CA / SA | 0.72-0.73 | 0.27 (clipped to 0.28) | 0.37-0.38 (AU, CA) |
| IN | 0.69 | 0.29 | 0.37 |
| BR | 0.60 | 0.33 | 0.39 |
| US | 0.54 | 0.37 (EIA heat rates: ≈ 0.45) | 0.35 |
| DE / PL | 0.41-0.43 | 0.46-0.49 | 0.35 |

- Coal comes out plausible; **gas is biased low and the bias varies by country** with Jordaan's leakage assumptions,
  so gas sits too high in the merit order relative to coal (≈ +20 % fuel cost per MWh_el in the US, more in AU/CA/IN).
- The `now` validation does not show it because the soft ±10 % energy bands pin coal and gas generation, and with
  generation pinned the model's CO2 equals Ember's by construction (circular). In the 16 solved `now` runs coal sits
  at the band cap in 40 of 66 country rows (11 at the floor), gas at the floor in 24 of 94 (33 at the cap): consistent
  with gas looking too expensive (KR, CN, IN, GB, PL, AU gas at the floor; ID, JP, TR, MX coal at the cap), not a proof
  (single national fuel prices push the same way). The large coal systems (CN, IN, ZA, DE) sit inside the band.
- The myopic and `zero` runs have no bands, so from 2030 the coal-gas split runs on these efficiencies alone.
- Ember's capacity is a separate source family from its generation (coal and/or gas from the GEM trackers, gross,
  > 50 MW, co-firing counted as gas; everything else IRENA), so the capacity factors in `envelope.csv` mix sources, and
  the coal / gas capacity targets share GEM with powerplantmatching (not an independent check).

**Fix (2026-10-19):** gas is no longer derived from emissions (`IMPLIED_EFFICIENCY` in `build_calibration.py` keeps
coal, lignite and oil); gas fleets take the per-carrier defaults of `efficiency.csv` (CCGT 0.50, OCGT 0.35). The
band-free comparison of old and new efficiencies was not run; the 2026-10-20 validation with bands shows one visible
consequence: Israel's coal (11.5 TWh in 2024) no longer runs, cheap domestic gas at realistic efficiency undercuts it
and the band is too soft to hold it (accepted for now, see "Validation of 2026-10-20" below).

### Validation of 2026-10-20 (calibration at the source, HVDC ratings, hydro as generation, capacity cluster weights)

All 16 `-now` stages (132 countries) solved; `check_sources.py` passes everywhere (demand, plant capacity per fuel
group, hydro energy exact). Worst fuel row per country vs Ember, demand-weighted: **2.3 pp** (old downstream
calibration 2.8 pp, calibration at the source before the two fixes below 3.0 pp). CN 0.7, US 1.5, IN 1.5, BR 0.9,
GB 2.9, JP 3.4 pp. Two fixes made during this validation:
- **Hydro inflow = generation** (`renewable.hydro.normalization.dispatch_efficiency`, fork): run-of-river inflow clipped
  at capacity after scaling (32 TWh were lost to clipping in Brazil), reservoir inflow / 0.9 (dispatch efficiency;
  26 TWh in Brazil). BR 10.4 -> 0.9 pp, VE 9.2 -> 0.4, NZ 5.5 -> 1.0, CO 5.5 -> 2.2.
- **Cluster weights by capacity** (`renewable.<tech>.cluster_weight: capacity`, fork): the profiles of merged buses
  were averaged by technical potential, so the fleet lost the capacity factor set in `add_electricity` (GB offshore
  0.32 -> 0.41, wind +6.8 pp). GB 6.8 -> 2.9 pp.

Accepted residuals (2026-10-20, revisit later):
- **Islanded exporters:** the rest-of-world groups solve each country as an island, so net exporters cannot export.
  With hydro now at its full energy, NO (net exports 18 TWh) and SE (33 TWh) curtail wind instead (NO wind CF 0.00,
  SE wind -11.7 pp, hydro +9 to +10 pp). A fix would be an export sink at the net-export value.
- **Israel coal** 0 instead of 11.5 TWh (gas fix above).
- **Wind profiles of several rest-of-world countries** are so far below Ember that the CF correction stops at its
  x1.4 clip (NAM summed CF 1.66 vs 3.61 over 11 countries; also SAM, ASI, EUR).
- Small systems with a fuel off by > 10 pp as before (LT, PT, SD, LB, PS, AF, ...: single national fuel price,
  islanding).

### Wind and solar check (2026-11-16)

`scripts/check_renewables.py` (read-only, a few minutes, nothing rerun) reads what the `now` stages left on disk and writes
`model-doc/build/renewables_check/`: per country the fleet capacity factor with the unadjusted ERA5-2013 profiles
against the observed one and the factor `capacity_factor_targets` applies (`cf.csv`); plant list, IRENA 2023 / 2024 and
the network's capacity (`capacity.csv`); the fleet capacity factor after clustering with capacity and with potential
weights (`weights.csv`); the resource classes (`classes.csv`); the cutouts (`cutouts.csv`). The model doc's section
"Renewables & Weather" takes its numbers and figures from these tables. Found with it: `scale_down` does not reach
the network (China onshore wind 511 GW against IRENA's 480, India solar 116 against 98; `REFACTOR_LATER.md`, item C).

### Fleet corrections and their check (2026-11-04, in the tables and configs, not yet in any solved network)

`scripts/check_fleet.py` (read-only, 10 s) rebuilds each region's plant list in memory from powerplantmatching's cached
`matched_data_red.csv`, scales it with the fork's `harmonise_to_statistics` and compares with Ember's own generation, national
statistics (`data/validation/fleet_national.csv`: EIA, CEC, CEA, EPE, Energy-Charts, DUKES, RTE) and national heat rates
(`data/validation/fleet_efficiency_national.csv`); it reproduces the `build_powerplants` logs of the existing networks exactly.
Output in `model-doc/build/fleet_check/`, written up in the model doc's Existing Fleet section. Found and fixed:
- **Ember's capacity too small for its generation** (29 rows, 148 TWh unreachable at full output): Ember's "Other Renewables"
  capacity holds IRENA's renewable municipal waste (US "geothermal" 0.89 GW vs 2.7, ID 0.02 vs 2.6, TR 0.06 vs 1.7; DE/NL/PL/BE
  geothermal that does not exist), its bioenergy capacity leaves the waste out (CN 18.6 GW for 208 TWh), and dual-fuel plants
  leave Other Fossil short (IR, EG, SY). `build_calibration.py` now takes biomass and geothermal from IRENA by technology
  (`IRENA_GROUPS`, via powerplantmatching's IRENASTAT) and back-fills every row with capacity factor > 1. `calibration/2024/`
  rebuilt (capacity, generation, envelope changed; the rest identical).
- **No existing OCGT anywhere**: powerplantmatching's GEM loader labels gas turbines and engines "Steam Turbine", which
  `build_powerplants` maps to CCGT (US: 0 OCGT although GEM lists 150 GW of gas turbines). New fork option
  `electricity: gas_technology_mapping` (fork commit 47e2cca4), set to `{Steam Turbine: OCGT}` in `statistics.yaml`:
  US 359 GW CCGT + 187 GW OCGT; EIA's tested heat rates match (CC 0.50, GT 0.345, steam 0.367 LHV).
- Open, documented only: the `now` filter with filled decommissioning years drops operating plants (Salem, Amos, Gavin, Drax)
  as well as closed ones (US: 106 GW coal, 163 GW gas); the statistic restores the totals at the other sites. Coal efficiencies
  implied by Ember CO2 are 6 % high in the US (0.354 vs EIA 0.333) and 9 % low in China (0.371 vs CEC 0.406).

Since 2026-11-11 the script also writes the inputs of the model doc's fleet figures (all read-only, about 1 min): `world.csv`
(plant list against statistic for all 132 countries), `sources.csv` / `fields.csv` (the matched list by reporting database and
the fields it fills), `retirements.csv` (the five regions' 2024 fleet in operation to 2050, reported against filled dates), and
coordinates in `dropped_<R>.csv`.

The new `capacity.csv` is newer than every `powerplants.csv`, so the next run of any stage rebuilds from `build_powerplants` on
(`--rerun-triggers mtime input`); the gas mapping itself is a parameter and would not trigger a rebuild on its own.

## Before/after the patches (`baseline/`; 2026-10-28)

What the fork changes buy, shown on the same global experiment: every stage of the 2026-10-20 validation (`now` and
`zero` of the 6 archetype regions and the 10 rest-of-world groups) solved once more with **PyPSA-Earth v0.9.0 as it
comes**, against the 2026-10-20 results of the fork (the "after", not re-run).

- **Code:** git worktree `models/pypsa-earth-baseline`, local branch `baseline-v0.9.0` = v0.9.0 + only the 12 patches
  without which the stages do not run on this laptop (`clip_bbox`, earth-osm single process, resumable bundle, monthly
  CDS, no WKT in `base.nc`, gdp fallback, lean aggregation, empty lines table, NaN cutout columns,
  `excluder_resolution`, in-process availability, backbone guard of `merge_into_network`). Not in it: everything else
  in the patch table (biomass labels, VRE `p_nom_min`, HVDC chains and `dc_ratings`, DC-bus absorption, cross-border
  transformers, calibration at the source, `calibrate_network.py`, the demand pathway, cluster weights).
  **Exception, China and Canada:** v0.9.0 cannot cluster them. `simplify_links` leaves stray DC buses (CN 115, CA 4), each
  its own sub-network, and `cluster_network` needs one cluster per sub-network: "Number of clusters must be 116 <=
  n_clusters" for CN's 50, "5 <=" for CA's single node (run of 2026-10-28/29). Those two regions were therefore solved on
  2026-10-29 with the DC-bus absorption patch (`caa0f116`) cherry-picked on top, deleted `networks/{CN,CA}-*/elec_s.nc`,
  and the patch reverted on the branch afterwards. Every other region is v0.9.0 + the 12 patches.
- **Config:** the stage configs `config.<R>.yaml` as they are; `merge_config.py` with `CATALYST_BASELINE=1` leaves out
  `statistics.yaml` and the technology-assumptions rules, takes `baseline/overlay.{now,zero}.yaml` (the out-of-the-box
  overlays of 2026-09-19, parent commit `fa6c511`: `now` = brownfield expansion at 2025 costs without a CO2 cap,
  `zero` = `Co2L0` at 2050 costs, both on GEGIS SSP2-2.6 2030 demand, since GEGIS has no 2050 file for North America and
  Oceania) and merges `baseline/common.yaml` on top (no retrieval into the shared `data/` and `cutouts/`).
- **Sharing without copies:** `baseline/prep_region.sh <R>` hardlinks the patch-independent resources of the main run
  (shapes, OSM, `build_osm_network` outputs, natura, onshore/offshore regions, wind and solar profiles), rebuilds
  `base.nc` with v0.9.0 and gates on identical buses (so the linked regions and profiles describe it), gives it the
  main `base.nc`'s mtime, gates on a dry run that may only contain `build_powerplants` and the hydro profile, then
  builds those. Checked 2026-10-28 for all 16 regions: buses identical, only the HVDC link ratings differ
  (v0.9.0 = v × 1.638 kA).
- **Driver:** `baseline/run_overnight.sh` (run.sh with `CATALYST_PE`, `CATALYST_RUN` = the main fork's environment,
  `SNAKEMAKE_EXTRA` = an `--allowed-rules` list) runs prep + `<R>-now <R>-zero` per region, the six dashboards and the
  world page in the worktree, then `scripts/plot_before_after.py` and `scripts/plot_world_before_after.py` (per country:
  Ember 2024 · 0.9.0 · with patches, from the two `validation_world.csv`) →
  `misc-quarter1/pypsa-earth-out-of-the-box-validation/figures/before-after/` (`before_after.{png,pdf,csv}`, the
  before pages in `before/`). At the end it reports any main-fork file newer than its start (expected: none).
  Launch and progress:
  ```bash
  setsid nohup systemd-inhibit --what=handle-lid-switch:sleep:idle --who=catalyst --why="pypsa-earth baseline run" env MEM_MAX=20G bash config-pypsa-earth/baseline/run_overnight.sh > models/pypsa-earth-baseline/logs/catalyst/driver.out 2>&1 &
  tail -f models/pypsa-earth-baseline/logs/catalyst/status.log
  ```
- **Remove:** `git -C models/pypsa-earth worktree remove --force ../pypsa-earth-baseline && git -C models/pypsa-earth
  branch -D baseline-v0.9.0` (the figures stay in `misc-quarter1/`).

## Demand pathway (future model years; 2026-10-04)

Out of the box the fork has no demand growth in the electricity-only workflow: the load is one GEGIS file chosen by
`load_options.prediction_year`, and since the calibration both `-now` and `-zero` rescaled it to Ember 2024. The
calibration step has no notion of a year; the year lives only in the table path. So future demand is one table per
model year, `calibration/<year>/demand.csv` for 2025, 2030, 2035, 2040, 2045 and 2050, written by
`scripts/build_demand_pathway.py` (plain pandas, any env):

    demand(country, y) = demand(country, 2024) × IEA multiple(WEO region of the country, y) ^ α

- **World level, a consensus of outlooks.** `data/demand_outlooks.csv` holds the reference-type scenario of each
  publisher, each figure checked against the publisher's own document. Every row becomes an annual growth rate over
  its own horizon; the consensus is the equal-weight mean.

  | Publisher | Outlook, scenario | Stated growth | p.a. | 2024 → 2050 |
  |---|---|---|---|---|
  | IEA | WEO 2025, Stated Policies | 27,290 → 49,657 TWh (2024–2050) | 2.33 % | ×1.82 |
  | BloombergNEF | NEO 2026, Economic Transition | +69 % (2025–2050) | 2.12 % | ×1.73 |
  | bp | Energy Outlook 2025, Current Trajectory | 30 → 58 thousand TWh (2023–2050) | 2.47 % | ×1.89 |
  | ExxonMobil | Global Outlook 2026 | +65 % by 2050 (base year assumed 2024) | 1.94 % | ×1.65 |
  | DNV | ETO 2025 | +120 % to 2060 (rate applied to 2050) | 2.21 % | ×1.77 |
  | **Consensus** | | | **2.22 %** | **×1.77** |

  Listed but excluded: EIA IEO 2023 (×1.50, pre-dates the data-centre revisions) and McKinsey GEP 2025 (no public
  world figure found). The spread of the five is ×1.65–1.89, about ±7 % around the consensus.
- **Regional pattern, IEA.** Only the IEA publishes a free regional table (WEO 2025, Table A.16,
  `data/weo25_table_a16.csv`), so regions keep the Stated Policies shape. Countries map to WEO regions after WEO
  Annex C; the table names the US, Brazil, the EU, Russia, China, India, Japan, Southeast Asia and Africa, every
  other country takes the remainder of its region (Europe less EU, North America less US, Eurasia less Russia, Asia
  Pacific less the four named, Central and South America less Brazil). The table has 2035 and 2050; other years are
  interpolated at a constant growth rate within 2024–2035 and 2035–2050.
- **α = 0.944** scales the regional growth so that the 2050 total over all countries equals the consensus. 2024
  stays fixed and the regional ordering is preserved.

World demand: 30,914 TWh (2024) → 31,775 (2025) → 36,512 (2030) → 42,078 (2035) → 45,828 (2040) → 50,003 (2045)
→ 54,661 (2050). Multiples per region and year are in `calibration/demand_pathway.csv`, e.g. 2050: US ×1.35,
China ×1.72, India ×2.75, Brazil ×1.63, EU ×1.66, Southeast Asia ×2.31, Africa ×2.75.

**Wiring.** `overlay.zero.yaml` reads `calibration/2050/demand.csv` (it already uses 2050 costs); `overlay.now.yaml`
stays on 2024. `calibrate_demand` in the fork rescales each country's load to `demand_twh` and ignores the other
columns, so only `prepare_network` and `solve_network` re-run. `run.sh` skips a stage whose target exists: delete
`results/<R>-zero/` (and `networks/<R>-zero/elec_s*_ec_l*.nc`) to re-solve with the new demand.

**Caveats.**
- One multiple per WEO region: Singapore grows like Southeast Asia (×2.31; EMA's own outlook to 2034 is ×1.2–1.6
  against ×1.56 here), every African country like the continent.
- Uniform scaling: the hourly shape and the split over buses stay those of the 2013 profile; electric vehicles,
  heat pumps and data centres would change the shape.
- Stated Policies includes announced policies, which the SOW's "no forward-looking national policies" rule would
  exclude; the IEA's Current Policies world total differs by 2 %.
- Only growth is taken from the outlooks, because demand definitions differ (the IEA excludes own use and losses,
  bp reports generation, Ember includes losses).
- Licences: the WEO table is CC BY-NC-SA 4.0 (a cited excerpt of ten rows); re-check before the public release.
- A fitted alternative (income elasticity + electrification layer) was tested first and rejected:
  `misc-quarter1/demand-projection/`.

### Pathway design: how demand, the myopic loop and learning fit together

The shared interface is the year. Demand, the myopic loop, the palette and the learning market are in place.

| Part | What a model year reads | Status |
|---|---|---|
| Demand | `calibration/<year>/demand.csv` | implemented |
| Myopic | the solved network of the previous year + the per-year tables | implemented (2026-10-04) |
| Palette | `technology-assumptions/technology_assumptions.csv` → cost rows per year + the stage config | implemented (2026-10-12, see "Technology palette" below) |
| Learning | `results/learning/<scen>/market_<year>.csv`, written by a market step between years across all regions of the pathway | implemented (2026-10-14, see "Learning market step" below) |

- **Myopic, electricity-only (2026-10-04).** Stage `<R>-myopic` = `config.<R>.yaml` + `overlay.myopic.yaml`
  (`foresight: myopic`, `planning_horizons: [2025, 2030, ..., 2050]`, no CO2 cap, 2024 CO2 prices). The fork got
  three patches: the land-use constraint without sector naming, the electricity-only myopic rules
  (`add_brownfield_elec`, `solve_network_myopic_elec`, target `solve_all_networks_myopic`; both upstream
  candidates) and `calibration.horizon_tables`. The chain up to `prepare_network` runs once and is calibrated to
  2024 as in `now` (expansion allowed); per horizon `add_brownfield_elec` then
  1. scales demand to `calibration/<year>/demand.csv` (`horizon_tables.demand`; fuel and CO2 price tables per
     year can be added the same way, none exist yet);
  2. moves extendable assets to the technology costs of the horizon (difference of the technology-data cost
     tables of the horizon and of `costs.year` = 2025);
  3. retires existing plants whose reported retirement year has passed and carries over what earlier horizons
     built, with fixed capacity; the land-use constraint takes that capacity off the remaining potential;
  4. solves 2025 without expansion (`existing_capacities.dispatch_only_horizons: [2025]`, fork patch
     2026-10-09): every extendable capacity is fixed at its lower bound, so 2025 is the dispatch of the
     calibrated 2024 fleet with 2025 demand (SOW: "a 2025 validation run, then capacity expansion"), and the
     first build decision is 2030.

  `run.sh` targets the solved network of the last horizon (`results/<R>-myopic/networks/<stem>_2050.nc`);
  the earlier ones are solved on the way and sit next to it. There is no dashboard for these stages yet.
  **Retirement rule since 2026-11-16** (`REFACTOR_LATER.md`, item 3; supersedes the rule of 2026-10-09 described in
  the rest of this paragraph): a reported retirement year is kept, a missing one is the commissioning year plus the
  lifetime of the technology in the cost table, as in PyPSA-Eur's `add_existing_baseyear` (coal, lignite, nuclear
  40 years, gas and oil 25, biomass and geothermal 30); hydro gets none and never retires. Fork option
  `electricity: powerplants_lifetimes: costs` (default `powerplantmatching`), set in `overlay.myopic.yaml`; the `now`
  and `zero` stages keep the default. A plant already past its lifetime is dropped by `powerplants_filter` and the
  capacity statistic is scaled onto the remaining plants. The reasoning: never retiring undated plants is the
  stronger policy assumption, and replacing retiring capacity is what the model is for. Consequence
  (`scripts/check_fleet.py`, `model-doc/build/fleet_check/retirements.csv`): 33 % of the US fleet of 2024 is left in
  2030 and 2 % in 2050 (gas 546 -> 194 GW, nuclear 97 -> 18 GW by 2030), 51 % / 2 % in NWE, 91 % / 34 % in China;
  with powerplantmatching's lifetimes 68 % / 13 %, 77 % / 13 %, 95 % / 62 %. The fork commit of the old rule
  (`fill_missing_dateout`) is gone from the history.
  Retirement rule of 2026-10-09 (superseded; SOW: "keep existing power generation capacity, announced retirements where
  they are firm and dated"): only a retirement year reported by the power plant data retires a plant. Such
  years come mostly from GEM's trackers ("Retired year" / "Planned retire"), a few from GEO, none from GPD. By
  default pypsa-earth invents one for every other plant (powerplantmatching's
  `fill_missing_decommissioning_years`, commissioning year + 45 years for coal, 50 nuclear, 100 hydro, 15
  geothermal ..., then `add_electricity` with the costs lifetime), so before the fix 100 % of plants carried
  a date and e.g. Canada's Darlington and Bruce reactors retired in the 2040s and Indian coal lost 101 GW by
  2050 (13 GW announced). Fork patch `existing_capacities.fill_missing_dateout: false` (upstream candidate)
  stops both fillings; undated plants get an infinite lifetime, and dated plants are grouped by their
  retirement year as well (`<bus> <carrier>-<grouping year>-<retirement year>`), so announced closures apply
  to them alone and survive clustering (a dated and an undated group of one vintage would otherwise merge into
  one undated generator at the cluster node). Capacity that the calibration adds from statistics is undated and never
  retires either. Still true: existing wind and solar have no vintages (one block per bus, carried from
  2025 with a 25-year lifetime, i.e. present through 2050); a reported year is taken as firm without a
  per-plant check, which lets stale dates through: GEO's duplicate "Bruce Canada 3-8" entries retire 2027-2036
  (2.6 GW of Canadian nuclear after calibration) although Bruce is being refurbished to 2064. Effect on the
  three small regions (fixed fleet in 2050, before -> after): Oceania coal 0.1 -> 5.2 GW, CCGT 4.0 -> 17.6 GW,
  geothermal 0 -> 1.1 GW (only Wairakei retires, 2031); Canada nuclear 0 -> 10.1 GW, CCGT 6.4 -> 26.0 GW;
  Singapore CCGT 6.2 -> 10.9 GW (no dated plant at all). With 2025 dispatch-only, the expansion held back in
  2025 lands in 2030 (Canada +113 GW, mostly solar and wind).
  Caveats:
  - The capacity, generation and net-import tables stay at 2024; the net-import band is therefore a 2024 volume
    in every horizon.
  - Until 2026-10-12 the extendable palette was pypsa-earth's default (wind, solar, battery, H2, and OCGT only
    where one exists), and Singapore left 0.4 TWh (2035) to 45 TWh (2050) of demand unserved because nothing
    firm could be built. The study palette is wired in since then ("Technology palette" below): Singapore now
    builds CCGT (11.6 → 24.7 GW by 2050, no shedding); the firm clean options exist but are dearer than gas at
    Singapore's 2024 prices without a CO₂ price pathway.
- **Learning (2026-10-14).** See "Learning market step" at the end of this README.

## Technology palette in the model (stages with `catalyst.palette: true`, i.e. `<R>-myopic`; 2026-10-12)

`technology-assumptions/technology_assumptions.csv` is the single source of what the model may build and at what
cost. Nothing is copied from it: `merge_config.py` derives the stage config from its columns at every run and the
fork reads a cost table derived from it at build time. Which technologies are included is a property of the CSV
(`in_default_mix`, `model`, `regions`), not of a config list.

**Columns → model** (`technology-assumptions/scripts/palette.py`, columns documented in the assumptions README):

| CSV | becomes |
|---|---|
| `model: profile` rows (solar, onshore, offshore wind) | `electricity.extendable_carriers.Generator` entries, profiles as before |
| `model: firm` rows (Gen IV, SOFC, SOFC-CC, CCGT, OCGT) | extendable generators at every AC bus (fork patch `electricity.extendable_carriers_buses: all`); `availability` / `min_load` → the fork's `conventional:` block (p_max_pu, p_min_pu) |
| `model: storage` with a per-kWh CAPEX only (iron-air) | `extendable_carriers.StorageUnit` + `max_hours` = `duration_h` |
| `model: storage` with per-kW and per-kWh CAPEX (Li-ion) | `extendable_carriers.Store` (store + charger/discharger links, free duration) |
| `model: tranches` (EGS) | `supply_curves.<carrier>` of the overlay is kept (dataset, bins, derate; fork patch, below) |
| `model: existing` (hydro, run-of-river, PHS, hydrothermal, biomass, both LWR bins) | cost rows only, no new builds; so H2 (not in the CSV) and new LWR (decision 2026-10-12) are not buildable |
| `regions` | the row applies where it names a country of the stage (`nuclear-lwr-cnin` in CN, IN; `nuclear-lwr-row` elsewhere) |
| `fuel`, `capture_rate` | CO₂ intensity (gas × (1 − capture): SOFC-CC emits 2.2 % of a gas plant's, priced by the CO₂ tables) and `calibration.fuel_map`, so SOFC gets the regional gas and CO₂ prices like CCGT |
| `color`, `label` | `plotting.tech_colors` / `nice_names` |

**Costs.** `assumptions.smk` rule `palette_costs` (`scripts/build_palette_costs.py`) writes
`resources/<stage>/palette/costs_<year>.csv` for every year the stage needs, in technology-data's long format;
the fork's `process_cost_data` merges it onto the retrieved technology-data table (fork patch `costs: overrides`,
upstream candidate) before units, currency and annuities are processed. Per row: investment (USD/kW), FOM as % of
CAPEX, VOM, efficiency, lifetime, fuel, CO₂ intensity; the names the fork looks up (`solar` and `solar-utility`
with `rooftop_share: 0`; `offwind`, `offwind-ac/-dc` with the station and connection adders zeroed because the
CSV's offshore CAPEX is all-in; `nuclear` from the applicable LWR bin; the `gas` fuel row, which `load_costs`
copies onto CCGT and OCGT); storage through the fork's `storage_techs` names (store row per kWh, (bi)charger per
kW, FOM split by CAPEX share, efficiency per direction except battery/li-ion where the fork square-roots the
round trip itself); EGS rows `egs`, `egs-drilling`, `egs-plant` (CAPEX split by `capex_share_2`). Years: mature
rows follow technology-data's investment path relative to 2025 (`techdata_trajectory`, decision 2026-10-12),
advanced rows take the factor of the learning market ("Learning market step" below), flat without one. The fork's `costs.marginal_cost` defaults
are emptied so the CSV VOM applies. Sanity (SG 2025 table, 7 %): Gen IV 1.36 M USD/MW/yr, SOFC-CC 0.91 M, iron-air
0.79 M per MW (100 h), CCGT 0.26 M; SOFC-CC co2_emissions 0.0044 t/MWh_th.

**Currency.** Every overlay stage runs in USD (`costs.output_currency: USD`): the CSV is USD2024 and the
calibration price tables (`calibration/2024/fuel_prices.csv`, `co2_prices.csv`) are written in USD2024 by
`scripts/build_calibration.py` (hand-curated EUR × 1.0824, ECB 2024 average). Technology-data rows that remain
in use (transmission; fuel rows the calibration overrides anyway) are EUR2020 converted by the fork's FX only,
without CPI: a known inconsistency on non-palette rows. The validation dots of `scripts/build_validation.py`
(prices) are still EUR; to be converted when the `now`/`zero` pages are refreshed.

**Committed projects (no new LWR, but what is under construction).** powerplantmatching loads the GEM trackers
with status `construction` (planned start year as DateIn) for every carrier; the fork's default
`powerplants_filter` dropped them (`DateIn <= 2023`). `overlay.myopic.yaml` keeps them
(`(DateOut >= 2022 or DateOut != DateOut)`, `grouping_years_power` to 2040) and the fork leaves a fixed asset out
of every horizon before its build year (fork patch `remove_not_yet_built`, upstream candidate; PyPSA honours
`build_year` only in multi-period runs); `calibration.reference_year: 2024` keeps them out of the 2024 capacity
calibration. Pre-construction and announced projects are not loaded by powerplantmatching and stay out.
Worldwide (GEM 2025): coal 275 GW, gas 215 GW, nuclear 91 GW under construction.

**EGS supply curves (fork patch `supply_curves`, upstream candidate).** `misc-quarter1/geothermal/build/egs_potential.csv`
(build that workflow first) has one row per 0.25° cell with the Ricks & Jenkins (2025) cost model's CAPEX split
(wellfield, plant), FOM, and `capacity_mw` = well-spacing density (5 laterals × 2.29 km × 0.24 km spacing →
1.07 km² per injector unit, 4–11 MW/km² net by reservoir temperature) × cell area × the onshore-wind land
exclusions of the fork (Copernicus grid codes, 1 km urban buffer, natura: the renewable area constraint). The
fork's rule `build_supply_curve` assigns the cells to the cluster regions, scales by `developable_share` 0.3
(ASSUMPTION: ~21 % of hot land overall, between Ricks & Jenkins' further 80 % derate for land acquisition and
subsurface barriers and Franzmann et al. 2025's ~25 %), bins them by CAPEX (`capex_bins`, cells above
20,000 $/kW dropped) and merges adjacent bins with the smallest combined capacity until at most 5 tranches per
region remain, so the cheap tail keeps a tranche of its own. Each tranche is one extendable generator
`<bus> egs t<k>` with the tranche's capacity, capacity-weighted CAPEX/FOM, and an hourly profile from the
cutout's air temperature: the geothermal workflow stores per cell the net output relative to the design point at
−20/−10/+10/+20 K (`t_design_c`, `ambient_*`, from the cost model's ambient correction, as Ricks & Jenkins derive
hourly capacity factors from hourly air temperature); the fork interpolates at the hourly deviation and
normalises to an annual mean of 1 so the annual CF stays 0.85, output above rating in cold hours included. In
myopic runs the tranche CAPEX components follow the `egs-drilling` / `egs-plant` rows between horizons and the
land-use constraint nets each tranche's earlier builds off its cap by name.

## Learning market step (`run.sh pathway:<scen>:<R1>,<R2>,...`; 2026-10-14)

SOW (WP3): after each investment year the markets for advanced technologies are cleared across the regions,
cumulative deployment sets the next year's investment costs (Wright's law). Each `<R>-myopic` stage is its own
Snakemake run, so the regions meet in `run.sh`: a **pathway** stage advances all of them one planning horizon at a
time and runs the market step in between.

```
run.sh pathway:myopic:SG,CA,OCE
  clear_market.py init  -> results/learning/myopic/market_2025.csv      (reference: factor 1)
  for Y in 2025, 2030, ..., 2050:
      every <R>-myopic: Snakemake target results/<R>-myopic/networks/<stem>_<Y>.nc
      clear_market.py step  (builds of Y in all stages) -> results/learning/myopic/market_<Y+5>.csv
  plot_learning.py -> results/learning/myopic/learning.png
```

- **Market = overlay.** `catalyst.learning: true` in `overlay.myopic.yaml`; all `<R>-myopic` stages of a
  pathway form the market `myopic` (merge_config.py sets `catalyst.learning_market`). The catalyst scenario gets
  its own overlay and with it its own market.
- **Pools** (`technology-assumptions/scripts/palette.py`, `learning_pools`): every advanced, buildable CSV row with
  a learning rate: Gen IV (plant, 10 %), iron-air (energy, 15 %), EGS (drilling 15 % on 67.5 % of the CAPEX,
  surface plant 10 % on 32.5 %), SOFC (plant, 30 %). SOFC-CC shares SOFC's pool (CSV column `learning_pool`):
  their builds add up and SOFC-CC's whole CAPEX, capture adder included, takes the pool factor (decision
  2026-10-14). VRFB and the CO2 battery are not in the default mix and do not learn.
- **Wright's law**: `factor = max(Q / Q0, 1) ** log2(1 − learning rate)`, `CAPEX = CSV CAPEX × factor`, no floor
  (decision 2026-10-14), never above 1. FOM is written as % of CAPEX and follows; VOM, fuel and efficiency do not
  learn.
- **Reference capacity Q0 = `existing_gw` + `pipeline_gw`** of the pool row (decision 2026-10-14): the CSV CAPEX is
  read as the cost of the projects being built now (Fervo Cape Station, Form Energy's first plants), learning
  starts with the model's own builds. Energy-learning rows in GWh (× `duration_h`). EGS surface plant: CSV column
  `reference_gw_2` = 4 GW, global binary geothermal (egs.tex), so the plant learns slowly on EGS builds.

  | pool | component | Q0 | rate | CSV CAPEX of the component |
  |---|---|---|---|---|
  | Gen IV | plant | 2.9 GW | 0.10 | 17,000 USD/kW |
  | iron-air | energy | 40.2 GWh | 0.15 | 75 USD/kWh |
  | EGS | drilling | 0.504 GW | 0.15 | 5,467.5 USD/kW |
  | EGS | plant | 4 GW | 0.10 | 2,632.5 USD/kW |
  | SOFC (+ SOFC-CC) | plant | 1.4 GW | 0.30 | 4,100 USD/kW (SOFC-CC 4,740) |

- **What counts** (`clear_market.py`): extendable assets of each stage's solved network of horizon Y,
  `p_nom_opt − p_nom_min` where `p_nom_opt` ≥ `threshold_capacity` (10 MW: what the next horizon carries over),
  per CSV row through its carriers (Generator incl. EGS tranches; StorageUnit × `max_hours` for iron-air). **Only
  modelled builds count**, no scaling to the world (decision 2026-10-14); the file header records the stages and
  their share of 2024 world demand. Committed plants (GEM construction status) are fixed, not extendable, so they
  are not counted: the pipeline is in Q0. Retirements do not reduce Q. Builds of Y set the costs of Y + 5.
- **How costs reach the model**: `market_<Y>.csv` is an input of the palette costs of year Y
  (`assumptions.smk`, rule `palette_costs`, for years after `costs.year`; the 2025 file is the reference of every
  horizon and never learns), `build_palette_costs.py` scales the advanced rows by their pool factor (EGS per
  component: `egs-drilling`, `egs-plant`), and the fork's `update_capital_costs` moves the extendable assets of the
  horizon by the difference to 2025. No fork change.
- **Resumable, minimal re-runs.** A pathway hands every horizon to Snakemake (`--rerun-triggers mtime input`);
  `clear_market.py` rewrites a market file only when its content changes, so a second call re-runs nothing,
  and a changed market file re-runs exactly the horizons from that year on in every stage.
- **Test hook**: `LEARNING_EXOGENOUS=<csv>` (columns technology, year, gw) adds deployment outside the model in a
  horizon (also the hook for procurement volumes of the catalyst scenario).
- **Not yet**: no global build-rate limit (`max_build_rate_gw_yr`, Gen IV 1 GW/yr): once a technology is cheapest
  nothing limits how fast the regions build it, and a joint limit needs an allocation across independently
  solved regions. The no-learning results of 2026-10-12 are kept in `results/archive/<R>-myopic-nolearning/`.

### Fixed: new fuel-burning plants without fuel or VOM cost (found and fixed 2026-11-08)

The country fuel prices of `add_electricity` (calibration at the source, fork 0261b769) passed the marginal cost
of the extendable conventional generators as a Series indexed `<bus> <carrier>` to `n.madd(..., suffix=" <carrier>")`.
PyPSA 0.30 aligns such a Series to the names *before* the suffix, so every new extendable conventional
generator got NaN, i.e. 0 in the solve plus the CO2 price: OCGT, CCGT and the palette's SOFC, SOFC-CC and Gen IV
(fuel and VOM free; the SG smoke test of the CFE buyer, SOFC-CC at 116 USD/MWh, was one of these). The screening clustering repaired it in the `-now` /
`-zero` stages (no extendable fossil in `zero` anyway, so the validation pages are unaffected), but the myopic
stages kept 0: the first JP-cfe solve of 2030 built 78 GW of new OCGT at 1 USD/MWh and ran it as baseload
(load-weighted price 16.7 USD/MWh, coal idle). **The learning test of 2026-10-19 (SG, CA, OCE) had the same free
new gas and is void**; the overnight re-run of 2026-11-08 rebuilds every network with the fix (fork
`add_electricity.py`: the Series is indexed by bus). The free-gas JP trunk is kept in
`results/archive/JP-cfe-freegas`.

### Learning spillover and branches (2026-11-08)

What the rest of the world builds is an assumption of the market, set per overlay:

- **`catalyst.learning_spillover`** (`clear_market.py`, `multiplier()`): unset = only modelled builds count (the rule
  above; the market files stay byte-identical, checked against the 2026-10-19 SG/CA/OCE files). Otherwise the
  modelled builds are multiplied by m before they enter Q: a number as given, `midpoint` = √(1/share), `extrapolate`
  = 1/share, share = the stages' share of 2024 world demand (header line 2). Exogenous deployment is not scaled. Extra
  columns `multiplier` and `new_extrapolated` (= (m − 1) × modelled, the builds assumed elsewhere). Japan alone:
  share 3.29 %, midpoint ×5.5, extrapolate ×30.4.
- **Overlay inheritance**: `inherit: <scen>` merges `overlay.<scen>.yaml` first (`merge_config.load_overlay`), so a
  sensitivity carries only what differs.
- **Branches**: `catalyst.branch: {from: <scen>, year: Y}` makes `<R>-<x>` share every horizon up to Y with
  `<R>-<scen>` (`catalyst.branch.parent_stage`). `merge_config.solved_horizon` returns the parent's file for those years
  and `horizons` only the later ones; the fork's `solved_previous_horizon_elec` (Snakefile, catalyst patch) starts
  the branch's first horizon from the parent's solved network of Y, wrapped in `ancient()`; `clear_market.py init`
  copies the parent's `market_<Y>.csv` and steps over the parent's networks of Y with the branch's multiplier.
  The trunk runs with `PATHWAY_UNTIL=Y` (run.sh stops after that horizon).
- **Plots**: `scripts/plot_branches.py <R> <scen>...` (with `scripts/summarise_cfe.py`): advanced power and energy
  capacity as stacked areas, learning factors, CFE premium, one panel or line per sensitivity, x = year →
  `results/learning/<R>-branches/{power,energy,learning,premium}.{png,pdf}` and the tables behind them.

## 24/7 CFE catalyst (overlay `cfe`; 2026-11-08)

SOW §1.3 S2: a share of regional demand commits to 24/7 CFE and picks its portfolio, advanced technologies included,
endogenously (SOW §1.1). After Riepin, Jenkins, Swezey & Brown (Joule 2025; `models/247-cfe`: `add_ci`,
`cfe_constraints`, `excess_constraints`, `calculate_grid_cfe`). Fork `scripts/cfe.py` (catalyst patch):

- **Buyer** (`add_cfe_buyer`, called in `add_brownfield.py` after the horizon's demand and before the vintages are named
  and last horizon's assets carried over): at every AC bus with load, bus `<bus> CFE` (location = the bus) with a
  flat load of `share` × the bus's mean load of the horizon, taken out of the bus's load; links `<bus> CFE import` /
  `export` (fixed, 1 TW); extendable twins of the bus's extendable assets whose carrier is in `clean_carriers`
  (generators incl. EGS tranches, storage units, the Li-ion store with charger / discharger), same carriers and
  costs, so the learning market counts the buyer's builds without change. From `start_year` (2030; 2025 is
  dispatch-only). Earlier buyer builds are carried over like any other asset.
- **Constraints** (`add_cfe_constraints`, in `extra_functionality`). The study's setting (`matching: zone`, no grid
  purchases; "Market zones" below): the buyers of a market zone are matched together, in every hour
  Σ_buyers export_t ≥ Σ_buyers import_t, so a buyer's shortfall is covered by the surplus of the other buyers of its
  zone and the power goes through the grid; excess Σ_t w_t (Σ_buyers export_t − import_t) ≤ excess_share × the zone's
  buyer load. With grid purchases (`grid_imports: true`, node matching, as 247-cfe): matching
  Σ_t w_t import_t (1 − grid_cfe_t) ≤ (1 − target) Σ_t w_t load_t per buyer (with the buyer bus's hourly balance this
  is 247-cfe's annual sum of hourly clean supply ≥ target × load) and excess Σ_t w_t export_t ≤ excess_share × load.
  Always: shared potentials, buyer twin + grid asset ≤ the grid asset's potential (VRE netted by location, EGS
  tranches by name, buyer builds included).
- **Grid CFE** (`grid_cfe`): clean share of the generation at the bus, buyer assets and pure storage left out
  (hydro reservoirs count as generation); clean = `clean_carriers` and carriers at or below `clean_threshold`
  tCO2/MWh_th. The previous horizon's solved network seeds the first solve, `iterations` (2) solves per horizon,
  each with the grid CFE of the one before (`solve_network`).
- **Results** in `n.meta["cfe"]` of every solved network: `buyers`, `zones`, `grid_cfe` (used in the last solve),
  `grid_cfe_result`, and two summaries (USD2024/MWh of buyer load). `summary_zones`, per market zone, is the one to
  read: `cost_per_mwh` = (annualised CAPEX of all buyer assets of the zone incl. earlier vintages + their marginal
  cost + the zone's settlement with the grid at nodal prices) / the zone's buyer demand; the settlement is split into
  `revenue_per_mwh` (net sales at the zone's price) and `congestion_per_mwh` (what moving power between the zone's
  buses costs); `transfer_twh` = energy matched across buses; `grid_price_per_mwh` = load-weighted price of the rest
  of the zone's demand; `premium_per_mwh` = the difference. `summary`, per buyer, has the same columns at one bus;
  under zone matching a buyer's cost contains what it pays to or receives from the other buyers of its zone, so only
  the demand-weighted mean over a zone means something (it equals the zone row). `scripts/summarise_cfe.py` writes
  both (`cfe_zones.csv`, `cfe.csv`).
- **Buyer share per country** (`catalyst.cfe.share: statistics`, decided 2026-11-19; fork commit 0127cc6c, not
  pushed): the share of a bus's load that the buyer takes is that of the bus's country in the horizon's table
  `calibration/<year>/cfe_share.csv` (through `tables.smk` as `statistics/cfe_share_<horizon>.csv`; columns country,
  share, datacentres, re100, basis, capped). The table = data centres + half of the other electricity use of RE100
  members, at most 20 % of a country's demand, scale 1.0 until it is brought down to the 24/7 CFE supply that can
  plausibly come online by 2030: 2030 United States 9.6 %, China 2.8 %, India 1.5 %, Brazil 1.3 %, Singapore 12.4 %,
  North-West Europe 5.2 % (Ireland 20 %, capped; France 2.4 %), Japan 6.5 %, Morocco 0.5 %; after 2030 it follows
  the data-centre trend (United States 15.4 % in 2050). Evidence, sources, caveats and the builder:
  `misc-quarter1/datacentre-demand` (`snakemake -c1 model_tables` rewrites the tables); model doc section "Demand
  for 24/7 Carbon-Free Electricity". US West and US East take the national value (REFACTOR_LATER.md item I).
  `merge_config.py` stops a stage whose countries have no row. A bus whose country has share 0 gets no buyer.
  **No CFE stage has been run with the table yet** (dry runs and a check of the buyer loads only; every CFE result
  on disk has the uniform share below).
- **Growing buyer share** (the share before 2026-11-19: `catalyst.cfe.share: {2030: 0.01, 2050: 0.10}`, decided
  2026-11-10; fork: `share` may be a `{year: share}` pathway, interpolated linearly, which still works): 1 % of
  demand in 2030, 3.25 / 5.5 / 7.75 % in 2035 / 2040 /
  2045, 10 % in 2050, instead of a flat 10 % from 2030. With a flat share the buyer bought once, in 2030, and its
  cost per MWh stayed the annuity of that unlearnt portfolio; now every horizon adds a cohort at that horizon's
  costs. Reported per horizon in `cfe.csv` (summarise_cfe.py): `demand_new_twh`, `cost_new_per_mwh` = annual cost
  of the buyer assets built in the horizon / the load growth, minus the export revenue per MWh of the whole buyer
  load (ASSUMPTION: every MWh of buyer load sells the same excess), `premium_new_per_mwh` = that minus the grid
  price. The flat-10 % Japan runs of 2026-11-08 are archived: tables and figures in
  `results/learning/JP-branches-flat10/`, solved networks in `results/archive/flat10/`; the result paragraph
  below describes those runs.
  Rerun 2026-11-10 (grid imports closed, one solve per horizon, 25 min for the trunk and three branches): 2030 the
  buyer (10.5 TWh) builds 1.43 GW of EGS, premium 16 USD/MWh; EGS in Japan 2050 = 90 GW (secluded), 94
  (midpoint), 99 (extrapolated), of which the buyer 16; EGS CAPEX factor 2050 0.42 / 0.30 / 0.21 (reference
  0.46); from 2035 the newly contracted part costs about the grid price (midpoint premium_new -3, -1, -1, -7
  USD/MWh; the sign depends on the export-revenue ASSUMPTION above); emissions 2040 midpoint 108 Mt vs 210 in
  the reference.
- **India as a second one-node test region** (stage `IN1`, `config.IN1.yaml`, 2026-11-10): India's 50-node inputs
  (`resources/IN`, `networks/IN/base.nc`) through per-entry links, clustered to one node; no prenetwork stage of its
  own. `run.sh pathway:ref:IN1`, `PATHWAY_UNTIL=2030 run.sh pathway:cfe:IN1`, `run.sh pathway:cfesec:IN1
  pathway:cfemid:IN1 pathway:cfeext:IN1`, `plot_branches.py IN1 ref cfesec cfemid cfeext` (tables and figures in
  `results/learning/IN1-branches/`): ~20 min for the reference, ~45 min for the trunk and branches; each stage
  writes ~0.5 GB of demand profiles per horizon (15 GB for the five stages). Result: no EGS and no Gen IV in any
  run (India's EGS is too dear); the buyers choose solar, wind and Li-ion, plus a little iron-air (0.02 GW in
  2030; 1 GW by 2045 only in the extrapolated branch, where its energy CAPEX falls to 0.42); premium of the
  newly contracted part 15 USD/MWh in 2030, 8 / 6 / 6 / 3 afterwards; emissions 2050 1,021 Mt against 1,035 in
  the reference (coal stays, CO2 price 2.2 USD/t). Caveat: the 2025 dispatch-only horizon sheds 11.7 TWh of load
  (0.5 %, up to 43 GW in 567 h: peak 336 GW against 215 GW of coal), so its average price is 8,400 USD/MWh.
  Why India differs from Japan (solved networks, 2026-11-10): not seasonality (India's monsoon dip is deeper,
  July solar / load 0.61 of the annual ratio against 0.74 in Japan's December, though India's wind is 2.2 x its
  mean in July), but (1) land: Japan's solar potential is 273 GW (~290 TWh, 28 % of demand) and is used up in
  2030, India builds 2,990 GW of ~10,000 by 2050; (2) cost: solar 36 USD/MWh (CF 0.166) against 48 (CF 0.123),
  first EGS tranche 123 USD/MWh for 24 GW against 97 for 102 GW; (3) India's solar is steadier (worst week 0.60 of
  the mean against 0.45), which one copper-plate node over a subcontinent flatters. India 2050: 1,680 TWh of
  battery discharge (5.0 TWh of batteries, 830 GW), about 30 % of generation.
- **Supply incl. storage** (`mix.csv` column `kind`, 2026-11-10): `summarise_cfe.py` writes the discharge of PHS,
  batteries and iron-air as rows of kind `storage` next to the generation rows; `plot_branches.py` keeps drawing
  generation only, the workflow artifact stacks both ("Supply", stored energy counted twice).
- **One market per overlay name, not per region** (`results/learning/<scen>/`): two independent test regions
  overwrite each other's market files. On 2026-11-10 Japan's were copied to `results/learning/_JP_2026-11-10/`
  before the India runs, India's then moved to `results/learning/_IN1_2026-11-10/` and Japan's put back
  (`cp -a`, mtimes kept), so `results/learning/{ref,cfe,cfesec,cfemid,cfeext}/` describe Japan again; rerunning
  an IN1 pathway needs India's files back in place first. A market folder per pathway would remove this.
- **Pooled learning over test regions** (overlays `cfepool` / `refpool`, `run_test_regions.sh`, 2026-11-10; run
  in the night to 2026-11-11, all five regions solved): one pathway call over all regions, `run.sh pathway:cfepool:JP,IN1,NZ,ZA,MA`. After every
  horizon `clear_market.py` adds up the advanced builds of all regions, extrapolates the sum to the rest of the world
  (x 1 / joint share of 2024 world demand: JP 3.29 + IN 6.58 + ZA 0.80 + MA 0.15 + NZ 0.14 = 10.95 %, x9.13) and
  every region takes the new costs into the next horizon. `cfepool` = `cfeext` under a name of its own (branch of
  `<R>-cfe` at 2030), `refpool` = `ref` with the same rule, so the two differ by the buyers alone. New one-node test
  regions `config.{NZ,ZA,MA}.yaml` (copies of `config.JP.yaml` on the Oceania / Africa cutouts, each still in its
  group as well). `run_test_regions.sh`: prenetworks of the new regions, trunk `cfe` until 2030 for the pool,
  `cfepool`, `refpool`, `plot_branches.py <R> refpool cfepool --out <R>-pool`. A region failing in any horizon stops
  its pathway for all (the others need its builds). The trunk market `results/learning/cfe/` is rewritten for the
  pool (same numbers, other header), so the 2030 trunk solves of JP and IN1 re-run once.
  First run (22:24 to 01:51, 3.5 h: prenetworks NZ 88 min, ZA 5, MA 4; trunk 15 min, `cfepool` 42, `refpool` 52;
  memory peak 15 GB in the prenetworks, 5 GB in the solves). EGS is the only technology that learns: 8,100 USD/kW falls to 4,603 by 2035 and 1,808 by 2050
  with buyers, and stays at 8,100 until 2035 (6,578 in 2040, 2,134 in 2050) without. EGS in 2040, GW with / without
  buyers: IN 113 / 0, JP 68 / 29, NZ 3.5 / 0, MA 1.0 / 0; South Africa builds no advanced technology in either. So
  one-node India takes EGS once Japan's buyers have paid for the first doublings (none in its single-region runs).
  Caveat: x9.13 with no global build-rate limit and no cost floor puts ~2,000 GW of EGS in the world by 2050 and the
  wellfield at 14 % of its first cost; the size of the effect is an upper bound, the direction is the finding.
- **Why EGS and no iron-air** (checked 2026-11-11 on Morocco, where the toy model
  `misc-quarter1/toymodel-clean-procurement` builds 1.4 to 4.3 MW of iron-air per 10 MW of load in every weather year).
  Iron-air costs the same in both models (75 USD/kWh, 100 h, 41 % round trip). Re-solves of the solved 2030 network
  (reference costs, nothing learned yet; buyer load a flat 65 MW) give iron-air on the buyer's side: as run 0 MW;
  excess sales closed 7.8 MW; the toy model's single-site wind and solar of 2020 / 2021 / 2015 instead of the
  country-wide 2013 profiles 26 / 14 / 0 MW; both 27 / 22 / 3.6 MW, which is the toy model's range. So (1) the
  one-node country pools wind and solar over all of Morocco in one weather year and has few multi-day gaps, (2) selling
  20 % excess makes overbuilt wind, solar and Li-ion cheaper than long storage, and only then (3) learning: the first
  buyers that pick an advanced technology are Japan's, they pick EGS, and 1.5 GW x 9.13 on a base of 0.5 GW is 4.8
  doublings (-43 % in one step), while India's 1.9 GWh of iron-air x 9.13 on 40 GWh is half a doubling (-8 %). In 2035
  EGS (x0.57) replaces wind, solar and Li-ion, not iron-air: with EGS switched off the buyer still builds no iron-air
  (31 MW per 259 MW of load once excess sales are closed as well).
  The same year with ten nodes (`config.MA10.yaml`, k-means on Voronoi regions, overlay `cfenode` = `cfe` with node
  matching and a market of its own; `run.sh MA10` then `PATHWAY_UNTIL=2030 run.sh pathway:cfenode:MA10`, 14 min in all): every buyer
  procures at its own node, and the ten buyers of 2030 build 12.6 MW of iron-air for the same 65 MW of load (1.9 MW
  per 10 MW; 8 of 10 nodes, none at the node with a wind CF of 0.46), with 399 MW of solar, 24 MW of wind and
  180 MW / 1.3 GWh of Li-ion; their cost is 107 USD/MWh against 93 at one node. Only 2025 and 2030 were solved.
  This run found a multi-node bug in the fork's `scripts/cfe.py` (`add_cfe_buyer` indexed the grown load table with
  the load list from before the first buyer; fixed, one-node runs unchanged).
  That pull is an artefact of the boundary: one buyer per node that procures only there is stricter than 24/7 CFE
  accounting, which matches within a bidding zone (Google, EnergyTag, the hydrogen hourly-matching rules). With
  zone matching (fork `catalyst.cfe.matching: zone`, 2026-11-11: buyers stay at their nodes, their import links are
  open, and the buyers of a zone together may not buy net from the grid in any hour; the power goes through the
  lines; the excess limit holds for the zone's net exports) the same run, `MA10-cfezone` to 2030, builds no
  iron-air: 290 MW solar, 40 MW wind, 143 MW / 1.0 GWh Li-ion, most of it at the windy Atlantic node (wind at CF
  0.46 instead of the country's pooled 0.28); the zone's cost is 74 USD/MWh (97 with node matching, 74 at one
  node; `summary_zones`). The grid hardly binds (nodal mean prices 59.8 to 60.4). So the iron-air of MA10-cfenode
  came from the per-node boundary, not from the grid.
  **Decided** (in the discussion of this Morocco test; written down 2026-11-18): the study matches per market
  zone, not per node, because one buyer per node that procures only there is unrealistically restrictive. Zone
  matching is the fork's default and the setting of `overlay.cfe.yaml` since 2026-11-18; overlay `cfenode` keeps the
  node boundary for this side test; the overlay `cfezone` is gone (it equals `cfe`; its MA10 results stay in
  `results/MA10-cfezone`, `results/learning/cfezone`). The one-node results are unaffected. Consequence for the
  multi-node archetypes: the buyers lean on the grid, so a grid that is too permissive makes 24/7 CFE too cheap
  (India: "India: how permissive the modelled grid is" above).
- **Market zones** (2026-11-18). The zone of a bus is its country by default; a region whose markets are not its
  countries sets `catalyst: cfe: zones: statistics` in its `config.<R>.yaml` and gets the table
  `statistics/market_zones.csv` (bus, zone), built per run by `tables.smk` rule `catalyst_market_zones` =
  `scripts/build_market_zones.py` from the definitions in `data/market_zones/market_zones.csv` (one row per GADM
  level-1 unit or country, every row with its source):

  | Region | Zones | Definition |
  |---|---|---|
  | US East | ERCOT, SPP, MISO, PJM, NYISO, ISO-NE, Southeast | whole states; a state goes to the market with the largest share of its generating capacity by balancing authority (EIA-860 2024); every eastern balancing authority outside a market counts as Southeast. Close: Missouri (SPP 0.39, MISO 0.36) |
  | US West | CAISO, Northwest (WA, OR, ID, MT), Southwest (NV, UT, AZ, NM, CO, WY) | ASSUMPTION: no organised market outside CAISO, the two groups are a choice |
  | Brazil | N, NE, SE/CO, S | the four submarkets; state list from a sector blog, not an official list; Distrito Federal and Roraima are ASSUMPTIONS |
  | China | the provinces; Guangdong, Guangxi, Yunnan, Guizhou and Hainan as one | provincial spot markets; Southern regional market with unified clearing, in formal operation since October 2026 (press reports) |
  | North-West Europe | bidding zones | countries, with Germany + Luxembourg, DK1 / DK2, Ireland + Northern Ireland |
  | India | one national zone (no table) | the exchanges clear nearly one price (CERC 2024-25: 0.48 % of volume lost to congestion); the five regional grids would be a data edit |

  A clustered bus is not inside one zone: it takes the zone that holds most of its load (simplified buses by GADM
  unit, summed per cluster). How good that is (builder report on the networks of 2026-11-18): share of load in a
  cluster assigned to another zone NWE 0.9 %, BR 3.6 %, USW 6.3 %, USE 15.4 %, CN 23.7 %. In China Beijing, Tianjin
  and Shanghai get no cluster and 11 zones are a single bus (node matching there); Denmark is one cluster, so DK1
  and DK2 cannot be told apart. For China the clustering is therefore redone per zone (next bullet); for the
  others the table stands, and clustering per zone is `REFACTOR_LATER.md` item F.
- **Clusters per market zone** (`catalyst: cluster_by_zone: true` in `config.<R>.yaml`; China, 2026-11-18).
  `merge_config.py` turns the switch into PyPSA-Earth's `subregion` block: `method: gadm`, `define_by_gadm` = the
  zones of the table (rows keyed by GADM unit, of the stage's countries and `gadm_subset`), `apply_on:
  [cluster_network]`. `cluster_network` then sets the zone as the "country" of every bus of the simplified
  network, distributes the clusters over the (zone, sub-network) groups by load (at least one each) and puts the
  country back afterwards; the clustered buses are named after the zone (`CAISO0 3`). PyPSA-Earth applies the
  subregions of `cluster_network` in `build_bus_regions` too (the rule is keyed on the same name), so in a base
  run the bus regions are Voronoi cells within a zone, on land and at sea, and the profiles are rebuilt on them;
  a stage of an existing base run (the US West test below) keeps the base run's regions and profiles. For the sea
  areas this needed a fork fix (2026-11-19, found by China's rebuild: the rule got the countries' sea areas where
  the zones' are looked up, every zone lost its offshore regions and the offshore wind profile failed; same in
  upstream main). Not applied to `simplify_network` (its isolated-network threshold is a share of the "country"
  load). `subregion_shapes.geojson` and `subregion_offshore.geojson` are written by
  `build_shapes`; for a run that exists `scripts/write_subregion_shapes.py <run>` writes it with the same
  functions, since re-running `build_shapes` would rebuild the whole run. Zones made of whole countries
  (Germany + Luxembourg) cannot use the switch (`merge_config.py` raises).
  *Test on US West* (2026-11-18, overlay `tsub` = `now` + the switch, 2024 dispatch; overlay and stage deleted
  on 2026-11-19, the zone shapes of US West stay in `resources/USW/shapes/`): 20 clusters = CAISO 11,
  Southwest 6, Northwest 3 (by country: 6 / 9 / 5), no load in a cluster of another zone (6.3 % before),
  objective 152.37 against 152.32 bn USD, generation by carrier within 0.3 TWh, lines at their limit 9 against 10
  of 30. *China*: the switch is set and the zone shapes are written, but no network has it yet: the China base run
  predates the sweep of 2026-11-16, so its next run rebuilds everything from `base_network` on, and every stage
  with it. What the clustering will give (the fork's `distribute_clusters` on the simplified network of today):
  Southern market 7 clusters, Shandong 4, Jiangsu 4, Henan, Sichuan, Hebei 3, Zhejiang, Hunan, Hubei, Liaoning 2,
  and 18 provinces a single cluster (Beijing, Tianjin and Shanghai now have one; so do Inner Mongolia, Xinjiang
  and Gansu), where zone matching is node matching.
- **Tests of zone matching** (2026-11-18; Morocco, buyer share 1 % in 2030 and 3.25 % in 2035; test overlays
  `tzone` = `cfe`, `tnode` = node matching, `tzone2` = two test zones North (4 buses) / South (6) pinned by bus in
  a test table, each with its own market; overlays, table, stages and markets deleted on 2026-11-19, the numbers
  below are the record):

  | Check | Result |
  |---|---|
  | one node (`MA`), 2030: zone and node matching are the same problem | objective 1.880212 bn USD in both, identical buyer capacities, zone row = buyer row |
  | ten nodes (`MA10`), 2030: node ≥ two zones ≥ one zone | objective 1.81936 ≥ 1.81274 ≥ 1.81113 bn USD |
  | the same in the second horizon (2035, buyer assets of 2030 carried over) | 1.81175 ≥ 1.78873 ≥ 1.78374 bn USD |
  | hourly net exports of every zone ≥ 0 | minimum 0.000 MW in all runs |
  | zone cost = demand-weighted cost of its buyers | equal in all runs |

  Cost of the 24/7 CFE supply in 2030 (USD2024/MWh of buyer load): one zone 69.6, two zones 72.4 (North 77.3,
  South 69.6), node matching 84.2 (72 to 100 by node); in 2035 63.0 / 64.6 / 75.3. Energy matched across buses of
  a zone: 0.37 of 0.57 TWh with one zone, 0.23 with two, none with node matching. Only node matching builds
  iron-air (4 MW in 2030, 10 MW in 2035). These levels are below the 74 / 97 of the run of 2026-11-11 above (same
  buyer share): that run had no resource classes (best wind and solar class now procurable on their own) and a
  grid price of 59 instead of 53 USD/MWh.

  US West to 2030 with its three zones (`USW-tzone`, 20 nodes, 3-hourly, zones from the table): solves, net
  exports of every zone ≥ 0 in every hour, cost 70.2 (Northwest), 75.6 (CAISO), 68.9 (Southwest) USD/MWh against a
  grid price of 40 to 41; 6.0 of 8.6 TWh of buyer load is matched across buses; solar, onshore wind and Li-ion
  only. **Size**: 11.2 million rows and 5.5 million columns (3.1 / 4.5 million after presolve), 41 minutes of
  barrier, and the memory use ran into the 13 GB cap of the test (89 throttling events, no kill), so what the solve
  needs is at least that. A 50-node region with CFE buyers does not fit this laptop (30 GB).
- **No purchases from the grid** (`catalyst.cfe.grid_imports: false`, decided 2026-11-10; fork option, default
  false): with node matching the import link is closed (`p_nom` 0), so the buyer's own portfolio covers every hour
  of its load; with zone matching it is open, but the zone as a whole never buys net (above). The 247-cfe
  matching constraint is not added, the grid CFE is no longer in the problem and each horizon is solved once
  (the grid CFE is still recorded for the summary). Neither grid purchases nor the iteration are in the SOW
  (§1.1 leaves the implementation open); both came with the 247-cfe design. `grid_imports: true` restores it
  (imports credited with the grid's hourly clean share, `iterations` solves). Sales of excess to the grid
  (`excess_share`) are unchanged. In the Japan runs of 2026-11-08 (imports open) the buyer imported
  ~0.0002 TWh/a of 105, so those results stand; `target` < 1 has no meaning without imports.
- **Settings** (`overlay.cfe.yaml`, decided 2026-11-08): 10 % of demand, target 1.0, excess ≤ 20 % (as the
  procurement paper), `clean_carriers` = the palette's clean rows; SOFC-CC counts as clean (2.2 % of the gas CO2
  left; ASSUMPTION, as in the toy model).
- **Caveats**: clusters straddle market-zone borders (shares under "Market zones"); zone matching has been solved
  on the ten-node Morocco only (tests of 2026-11-18 below), no archetype has a CFE pathway yet; with
  `grid_imports: true` the grid CFE is a parameter of each solve, not a variable (two iterations, as 247-cfe).
- **Smoke test** (2026-11-08, SG 2030 network of the myopic stage, 2 iterations): score 1.000, no imports, the
  buyer builds 0.96 GW of SOFC-CC at 116 USD/MWh against a grid price of 26 (premium 90). Void: that network had
  the free-fuel bug (section "Fixed: new fuel-burning plants without fuel or VOM cost").
- **Fix found on the way** (fork `prepare_network.enforce_autarky`, upstream candidate): with `ATKc` (every
  single-node rest-of-world group) the Li-ion charger / discharger links were removed as "cross-border", because the
  battery bus has no country before `sanitize_locations`, so no single-node run could build Li-ion before
  2026-11-08 (incl. the learning runs of 2026-10-16/19). The country of a bus without one is now its location's.

Japan test (stage `JP`, `config.JP.yaml`, one node; overlays `cfe`, `cfesec`, `cfemid`, `cfeext`):
```bash
bash config-pypsa-earth/run.sh prestage:JP JP
PATHWAY_UNTIL=2030 bash config-pypsa-earth/run.sh pathway:cfe:JP
bash config-pypsa-earth/run.sh pathway:cfesec:JP pathway:cfemid:JP pathway:cfeext:JP
cd models/pypsa-earth && pixi run python ../../config-pypsa-earth/scripts/plot_branches.py JP cfesec cfemid cfeext
```
Figures in `models/pypsa-earth/results/learning/JP-branches/` (power, energy, mix, learning, premium; tables
summary / cfe / factors / mix .csv). No-CFE reference: overlay `ref` (`run.sh pathway:ref:JP`, own market
`results/learning/ref/`).

**Result (2026-11-08, with the fuel-cost fix; 3-hourly, 2013 weather, CO2 price flat at 2.2 USD/t, no cap):**
- 2030: the buyer (105 TWh) builds 13.7 GW of EGS (tranches t0 + t1) plus 8.5 GW solar, 4.9 GW onshore and 2.1 GW
  offshore wind; score 1.000, excess at the 20 % cap, 96.4 USD/MWh vs a grid price of 75.4 (premium 21.0); grid
  CFE 0.49. Without the fix the same solve built 78 GW of new OCGT at 1 USD/MWh (grid price 16.7).
- Learning on the buyer's 13.7 GW (EGS drilling 4.8 doublings over Q0 = 0.5 GW) makes EGS cheap enough for the
  grid: EGS in Japan 2050 = 99 GW (secluded), 102 (midpoint), 102.5 (extrapolated), of which the buyer ~15;
  drilling factor 2050 0.30 / 0.20 / 0.13 (plant 0.63 / 0.48 / 0.37). Coal falls from 327 TWh (2030) to almost nothing by 2050, nuclear
  shrinks with dated retirements, EGS ~60 % of generation in 2050. No CO2 price path: this is learning economics
  alone (new EGS ~50 USD/MWh in 2035 vs ~55 running cost of existing coal).
- Premium rises to 41 (secluded) / 49 (midpoint, extrapolated) USD/MWh in 2050: the buyer keeps paying the
  annuity of its 2030 EGS at the unlearnt cost (~100 USD/MWh) while the grid price falls to 51-59.
- Generation 1,022 TWh in 2025 = Ember 2024 gross generation (1,016 TWh) x the demand pathway; Japanese
  consumption statistics (~900 TWh) exclude plant own use and grid losses.

## Resource classes (fork option `renewable: <tech>: resource_classes`; 2026-11-12)

**Why.** Without classes every clustered region offers ONE onshore-wind and ONE solar generator: the region's
average profile on its whole potential (Japan: 553 GW of onshore wind, every MW at CF 0.221). Good sites are not
scarce, and since `cluster_weight: capacity` new capacity in the multi-node regions even gets the fleet's profile on
the full potential. PyPSA-Eur (>= v2025.04, and pypsalabs/spain-datacenter-decree with 5 classes) splits each
region's potential into capacity-factor classes; this is the port.

**How (fork, commit "resource classes").** PyPSA-Eur builds its profiles after clustering; the fork builds them on
the base network and simplify / cluster merge every generator of a carrier at a bus, so the classes follow the route
of the EGS supply curves:
1. `build_resource_cells` (once per base run, `resources/<R>/renewable_profiles/cells_<tech>.nc`, shared with every
   stage like the profiles): one atlite pass over the cutout window of `build_renewable_profiles`, hourly CF of every
   cell with potential (and of every cell holding a plant). The eligible MW are the `potential (y, x)` of the profile
   file, so the land-exclusion rasters are not redone. Japan: onwind 6 min / 2.2 GB, solar 27 min / 2.6 GB.
2. `build_resource_classes` (per stage, `resources/<stage>/resource_classes/`, never shared, run.sh): cells split
   between the stage's clustered regions by area share; per region n equal-width bins of the cells' mean CF over the
   cells with potential (PyPSA-Eur bins over every touching cell, which can leave the top classes empty); class
   profile = cells' hourly CF weighted by MW x mean CF (the atlite layout, so one class reproduces
   `build_renewable_profiles` exactly, tested on Japan for onwind and solar: identical profile and potential); plants
   of `powerplants.csv` (wind: all non-offshore incl. technology Unknown; solar: all non-CSP; in operation by 2024)
   placed by coordinates in a region (nearest when outside all) and a class (by their cell's mean CF).
3. `add_extra_components` replaces `"<bus> <carrier>"` by `"<bus> <carrier> c<k>"` (column `resource_class`, class 0 =
   worst): the calibrated fleet in the shares of the located plants (no located plant: CF x potential, PyPSA-Eur's
   rule for statistics-only capacity, ASSUMPTION), parts below 10.5 MW folded into the largest (the brownfield
   threshold would drop them), potential split so the classes add up to the old one, and one factor per country on
   all class profiles so that the fleet keeps the energy of the calibrated generator (2024 dispatch unchanged by
   construction). Asserted in code: fleet, potential and fleet energy conserved per bus.
4. Myopic: the land-use constraint nets earlier builds per location AND class; capacity without class at a location
   with classes is an error (e.g. a branch whose parent ran without classes).

Fixed on the way (fork, own commit): the CFE buyer bus had no `location` (PyPSA drops the attribute), so the
buyer's wind and solar of earlier horizons were never netted from the grid's potential (JP-cfesec: 0.13 GW onwind in
2035; solar 0.34 GW above its 273 GW potential by 2050). The runs before 2026-11-12 carry this small error.

**Japan, five classes** (`scripts/check_resource_classes.py JP-nowrc --plot`; CF raw = from ERA5 / atlite, CF model =
after the energy-neutral factor; old: one generator at 0.221 / 0.123):

| class | onwind GW | CF raw | CF model | fleet GW | solar GW | CF raw | CF model | fleet GW |
|---|---|---|---|---|---|---|---|---|
| 0 | 260 | 0.091 | 0.078 | 0.72 | 37 | 0.121 | 0.112 | 3.3 |
| 1 | 200 | 0.178 | 0.152 | 2.03 | 75 | 0.127 | 0.118 | 23.8 |
| 2 | 55 | 0.290 | 0.248 | 1.54 | 100 | 0.133 | 0.123 | 38.3 |
| 3 | 27 | 0.397 | 0.340 | 0.72 | 48 | 0.139 | 0.129 | 18.9 |
| 4 | 10 | 0.502 | 0.430 | 0.56 | 12 | 0.145 | 0.134 | 5.3 |

The located wind fleet stands on cells with a raw CF of 0.258 but delivers 0.221 (statistics), so the factor is 0.856
for every class (before: 0.99 on the regional average): the best 10 GW are offered at 0.43, the bottom 260 GW at 0.08.
Solar spreads only +-10 % around its mean.

Caveats: classes resolve resource quality within a region, not connection distance or cost between sites; ERA5
cells (~30 km) smooth the best sites, and equal-width bins depend on a region's extremes; one calibration factor
per country scales all classes, the best one too (it corrects ERA5 + turbine model at the fleet's sites, whose
turbines are older than new ones); the cell file follows the `resource` settings of the base run (an overlay that
changes `resource` would need its own); offshore wind has no classes yet (per-class connection costs).

**Default since 2026-11-12 (evening).** `statistics.yaml` sets `resource_classes: 5` for onwind and solar, so every
stage built on it has classes. Switch them off per stage with `resource_classes: 1` (= no class rule in the DAG):
overlays `refnorc` / `cfenorc` = `ref` / `cfe` without classes, the A/B partners. The test overlays of the afternoon
(`nowrc`, `refrc`, `cferc`) were removed (they equal `now`, `ref`, `cfe` now); their stages
`JP-{nowrc,refrc,cferc}`, `IN-nowrc` stay on disk as the record of the A/B below. Rebuild:
`rerun_classes.sh` (pooled test-region pathways, then the global validation via `rerun_validation.sh` with
`ARCHETYPES=""`, old `-now` / `-zero` in `results/archive/<stage>-20261109`). Not rebuilt, so still without classes
and without the buyer fix: the `<G>-myopic` groups, the JP single-region branches (`JP-ref`, `JP-cfesec` / `cfemid` /
`cfeext`), `MA10`. Note for the comparison with the archive: the archetype `-now` stages of 2026-11-09 ran on wind /
solar profiles older than their `-zero` stages (the base runs re-built the profiles in between); the rebuild also
re-runs add_electricity on the current profiles.

**Pooled test regions with classes (2026-11-13, `rerun_classes.sh` step pool; also with the buyer fix).** The first
attempt of 2026-11-12 failed on a DNS outage at DAG construction (Snakemake reads a file from raw.githubusercontent.com;
run.sh now retries network errors); re-run 11:06-12:12. Against the run without classes of 2026-11-10/11
("Pooled learning over test regions"), EGS GW with / without buyers:

| | 2040 without classes | 2040 classes | 2050 classes |
|---|---|---|---|
| JP | 68 / 29 | 59 / 24 | 87 / 76 |
| IN1 | 113 / 0 | 24 / 0 | 125 / 24 |
| NZ | 3.5 / 0 | 2.0 / 0 | 4.1 / 3.1 |
| MA | 1.0 / 0 | 0 / 0 | 0 / 0 |

(ZA builds no advanced technology in either run.) EGS cost (drilling + plant, USD/kW) with buyers 4,665 in 2035 and
1,872 in 2050 (before 4,603 / 1,808), without buyers 6,578 in 2040 and 2,166 in 2050 (before 6,578 / 2,134): the
learning is nearly unchanged, because Japan's buyers build the same first GW. What changes is how much EGS the grids
take at the learned cost: one-node India takes a fifth of the EGS of 2040 (presumably its best wind and solar classes
fill the room, as in Japan; not yet checked class by class). The catalytic gap (with vs without buyers) stays, the ref pathway again one horizon
behind; its size shrinks as in the Japan A/B. Tables and figures: `results/learning/<R>-pool/`.

**Global validation with classes (2026-11-13 to 15, `rerun_classes.sh` step validation).** All 16 `-now` / `-zero`
stages re-solved (results of 11-09 in `results/archive/<stage>-20261109`), six dashboards (those of 11-10 in
`results/catalyst/archive-20261109/`), world page and before/after pages. Every stage's first run builds its cell
files (rest-of-world groups up to ~2 h, NAM). Comparison against the world table rebuilt from the archived 11-09
networks (`plot_world.py --fork <dir with results/ -> archive>`), 121 countries:
- `-now` reproduces the 2024 dispatch: world totals within 3 TWh per fuel (wind 2,490 vs 2,487 TWh, CO2 12.45 Gt in
  both), no country's fuel share moves by more than 0.2 pp. The classes are energy-neutral for the fleet as designed.
- `-zero` changes: wind 11.6 -> 12.8 PWh, solar 35.6 -> 34.3 PWh; 51 of 120 countries move > 5 pp. Most wind gained in
  China (2.8 -> 3.5 PWh), Saudi Arabia, Indonesia, Vietnam; Russia loses half (321 -> 152 TWh); US, India, Singapore
  barely change. Load shedding 555 -> 679 TWh, nearly all in South Korea (210 -> 270) and Taiwan (166 -> 230), the
  land-constrained cases: presumably the single profile weighted by MW x CF made the whole potential look more
  productive than its cells are on average (not checked cell by cell).
- before/after (v0.9.0 vs now, `figures/before-after/`): fossil-share MAE 1.46 pp, 104 of 121 countries within 10 pp.

Two driver gaps found on the way, fixed on 11-15: a network outage before any rule (DNS, e.g. right after resume
from suspend) cost NWE-now its three attempts on 11-13 (re-run after the others); run.sh now waits up to `NET_WAITS`
(24 x 300 s) for such outages without counting attempts. And run.sh skips a stage whose target exists, so the
dashboards of 11-10 had survived the archive step; rerun_validation.sh now archives `results/catalyst/validation_<R>.png`
with the results.

Checks:
```bash
cd config-pypsa-earth && ../models/pypsa-earth/.pixi/envs/default/bin/python scripts/check_resource_classes.py JP-cfepool --plot
../models/pypsa-earth/.pixi/envs/default/bin/python scripts/plot_classes_ab.py JP ref:refrc cfenorc:cferc   # the A/B record
```

**Result, Japan to 2050 (2026-11-12; `scripts/plot_classes_ab.py JP` -> `results/learning/JP-classes/classes_ab.{png,csv}`).**
A/B pairs: `ref` / `refrc` (no CFE) and `cfenorc` / `cferc` (24/7 CFE trunk to 2050, current `overlay.cfe.yaml`:
share 1 % -> 10 %, no grid imports, secluded learning; `cfenorc` was added because `JP-cfe` / `JP-cfesec` predate
parts of the 2026-11-10 changes of that overlay).
- 2024 dispatch unchanged (Japan and India-50, `build_calibration.py --check`: every row within 0.05 TWh).
- Bookkeeping (`check_resource_classes.py JP-cferc`): per class and horizon, fixed (grid + buyer) + remaining
  potential = class potential, no class overbuilt.
- Wind: without classes the reference builds 135 GW at CF 0.22; with classes 95 GW at CF 0.27-0.30 (classes 2-4,
  92 GW, are full by 2035; the 460 GW of classes 0-1 at CF 0.08-0.15 are never touched). 2030: 76 instead of 52 GW,
  gas -59 TWh, system cost of the horizon -8 %, grid price 72 instead of 78 USD/MWh.
- EGS and the catalytic effect: the buyer builds the same EGS with and without classes (1.3 GW in 2030, 16 GW by
  2050), so learning is about the same, but the grid follows less: EGS in Japan with CFE vs without CFE is +40 GW in
  2040 and +23 GW in 2050 with one class per region, +17 GW in 2040 and +1.5 GW in 2050 with classes. Cheap
  high-quality wind takes part of the room EGS filled when wind was only offered at the regional average. The
  CFE premium in 2030 rises from 16 to 23 USD/MWh, because the grid price falls while the buyer's cost does not.
- Run time: Japan pathway ~15 min either way; India-50 2024 dispatch 4 min with 497 instead of 100 wind / solar
  generators.
