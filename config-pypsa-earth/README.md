# `config-pypsa-earth/` — how the PyPSA-Earth soft fork is run (CONUS, Brazil, India, Singapore and North-West/Central Europe prenetworks, WP1 pipeline test)

Builds **power-only PyPSA-Earth models up to the `prepare_network` output** ("prenetwork",
not solved), one country (or country group) per stage, as the end-to-end exercise of the global data pipeline the
SOW prescribes (SOW §methodology: PyPSA-Earth soft fork, atlite/ERA5 feed-in). Done: the
contiguous United States (`US`, 2026-09-16), Brazil (`BR`, the hydro-rich archetype,
2026-09-17) India (`IN`, the fossil-heavy archetype next to US East, 2026-09-18) and Singapore (`SG`, the islanded
archetype of the kickoff slides, 2026-09-18, a single node); North-West and Central Europe (`NWE`, twelve
countries, the dense / renewables-constrained archetype, 2026-09-19) is the first multi-country stage and
reuses the PyPSA-Eur 2013 cutout found on this machine. Everything runs under three constraints: **≤ 8 GB RAM for the whole
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
- `run.sh [prestage:<CC>] [<stage> ...]` — the supervisor (default `prestage:US US-smoke US`; a stage is any
  `config.<stage>.yaml`, e.g. `prestage:BR BR-smoke BR`). Each stage runs
  `pixi run snakemake networks/<run>/elec_s_<clusters>_ec_lcopt_Co2L.nc -c1 -j1 --rerun-incomplete --rerun-triggers mtime input`
  (cluster count read from `scenario.clusters` of the stage config; rules re-run only for missing or outdated
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
