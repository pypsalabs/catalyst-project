# Global country features for SOW archetype mapping

`country_features.csv` — one row per country (193), scoring the archetype
dimensions named in the SOW §1.2 *Geographic scope*. Built for low-bandwidth
conditions: ~50 MB total downloads, all cached under `data/`.

Rebuild with Snakemake (the `Snakefile` maps `data/` → dataset → outputs):

```bash
S=../../models/priam-myopic/.pixi/envs/default/bin/snakemake
$S -c1          # build everything that is out of date
$S -n           # dry run: show what would rebuild and why
$S -c1 -R egs_cells   # force a rule (and everything downstream)
```

The DAG:

```
egs_cells        2× .nc + PB2002 → build/egs_cells.pkl  (0.1° EGS cell grid,
                 computed once, ~200 MB, env-pinned pandas pickle — delete
                 build/ after env upgrades)
build_features   data/* + cells  → build/features_national.csv (193 countries)
split_us         + EIA           → build/features_us.csv   (USA → USE/USW)
split_au         + OpenNEM       → build/features_au.csv   (AUS → AUN/AUW)
split_my         + handbook      → build/features_my.csv   (MYS → MYW/MYE)
merge_nwe        + borders       → country_features.csv    (ESP+PRT+FRA+DEU+BEL+NLD+LUX+GBR → NWE, FINAL)
classify         → country_archetypes.csv + land-grid-map/data/layers/rules-v1.js
dashboard        → country_atlas.html
```

`land-grid-map/` is the interactive front-end (its own git repository, deployed to Vercel,
ignored by this repo); `classify.py`, `cluster_tsne.py`, `build_regions.py` and
`prepare_population.py` write its data files, see `land-grid-map/README.md`.

Every script also runs standalone (`$P build_features.py` etc., same staged
paths under `build/`), for debugging a single stage.

## Archetype classification (`classify.py`, initial proposition)

Each of the 197 rows is assigned to one of the five archetypes defined in
`land-grid-map/data/archetypes.js` by an ordered decision tree — first match
wins: (R1) density ≥ 2000/km² → **dense** (city-states); (R2) geothermal
capacity ≥ 500 MW, or EGS share ≥ 0.15 with guards against nuclear/hydro/
dense grids → **geothermal** (checked before hydro so Iceland classifies
geothermal); (R3) hydro ≥ 40% → **hydro**; (R4) fossil ≥ 70% → **fossil**;
(R5) island or zero land borders, self-supplied, < 250 TWh → **islanded**;
(R6) density ≥ 200 + ≥ 4000 kWh/cap + PVOUT < 4.2, or nuclear ≥ 40% →
**dense**; (R7) fossil ≥ 50% → **fossil**; (R8) fallback to the highest
membership score. Each row also gets five continuous 0–1 scores,
`proximity` (score of the assigned archetype), `rule_fired`, and a
`size_tier` (micro/small/medium/large/giga by demand). Known quirk: Ireland classifies fossil, not the SOW's "islanded"
(GB interconnectors + 16% import share — the data is defensible). The
`rules-v1.js` output is a data version for the `land-grid-map` page
(sub-national grids collapse onto the national geometry via the
largest-demand row: USA=East, AUS=NEM, MYS=Peninsular).

## US interconnection split

The USA row is replaced by `USE` / `USW` (East, West), since the Eastern and
Western Interconnections are coupled by only a few GW of DC ties. ERCOT
(Texas) is folded into the East row: the archetype modelling works with one
US-East grid, so the earlier separate ERCOT row was dropped. Assignment is by
whole state from EIA 2024 state-level generation and capacity (WECC = WA OR
CA NV ID UT AZ NM CO WY MT; East = everything else incl. TX; the isolated
AK and HI grids are excluded and their share of the national figures dropped). Caveats: NM/MT straddle the seam; regional demand
is national demand apportioned by generation share; PVOUT values are Global
Solar Atlas map readings (approximate: West 4.8, East 4.0); protected-area
share stays national. Plate distance uses LA / NYC as anchor points — this
correctly puts US geothermal potential in the West only.

## Australia NEM/SWIS split

The AUS row is replaced by `AUN` / `AUW` (NEM, SWIS). The South West
Interconnected System around Perth has **zero** transmission ties to the
east-coast NEM — the SOW itself names "Australia's Western grid" as an
islanded-archetype exemplar — and it is a pure firming testbed: no hydro,
no nuclear, no import option, coal exit ~2029–30 (vs the NEM's ~5% Snowy /
Tasmania hydro). The SWIS row is anchored on AEMO WEM operational data via
OpenNEM (last complete calendar year, 2023, ~21 TWh incl. rooftop PV), NOT
WA state statistics — WA totals are roughly 2× the SWIS because of off-grid
mining gas (Pilbara/NWIS). The NEM row is the national Ember row minus the
SWIS, so it absorbs the NT grids and off-grid remnants (a few % of national
generation). Caveats: Ember national year (2025) vs WEM year (2023) differ;
SWIS rooftop capacity is a fixed 2.7 GW (AEMO ESOO) since the OpenNEM
facility registry covers utility plant only; population/area use the whole
of WA (the SWIS footprint is only its south-west corner); PVOUT values are
Global Solar Atlas map readings (NEM 4.5, SWIS 4.7); protected-area share
stays national.

## Malaysia Peninsular/Borneo split

The MYS row is replaced by `MYW` / `MYE` (Peninsular Malaysia; Sabah +
Sarawak). The two systems have **no** interconnector, existing or under
construction, and the national row blends opposite archetypes: the Peninsula
(~80% of demand) is a coal/gas grid with only peaking hydro (90% fossil
after the split), while Sarawak is hydro-dominated — Bakun/Murum run
near-baseload for the Samalaju smelters — and exports a little to Indonesian
Borneo (Borneo row: 62% hydro, 37% fossil). The national 17.5% hydro share
belongs almost entirely to Borneo. Anchors: per-grid installed capacity from
the Energy Commission's Malaysia Energy Statistics Handbook 2023 (31 Dec
2021 table); Borneo generation from Sarawak Energy / IHA (~34 TWh, 73%
hydro, 2022) and SESB/state reports for Sabah (~6.3 TWh, >80% gas); the
Peninsular row is the national Ember row minus Borneo. Caveats: vintages mix
(Ember 2025 national vs 2021 capacity / ~2022–23 Borneo generation); the
Borneo hydro CF of ~0.81 is real (smelter baseload), not an artefact; net
imports (Thailand/Singapore ties) are assigned wholly to the Peninsula; EGS
features split the country polygon at 106°E; protected-area share stays
national.

## North-West Europe merge

The rows of Spain, Portugal, France, Germany, Belgium, the Netherlands,
Luxembourg and the UK are replaced by one `NWE` row (`merge_nwe.py`): the
region is modelled as a single PyPSA network (the representative of the
renewables-constrained, high-density archetype), so it is classified,
clustered and drawn as one grid. Sums: population, demand, 2050 projections,
generation and capacity by fuel, land area, geothermal capacity and net
imports (intra-group flows cancel, so the members' net imports add up to
the group's, −2.4 % of demand). Per-capita demand, import share, generation
shares, realized CFs and density are recomputed from the sums; EGS features
are recomputed over the union polygon (clipped to Europe, French overseas
departments dropped); land borders count non-member neighbours (11);
protected-area share and PV yield are land-area weighted. In the k-means
cross-check the clusters are fitted on the national rows
(`build/features_my.csv`) and the `NWE` row is then folded into its nearest
cluster (dense, where five of its eight members already sat), so the world
clustering does not depend on the modelling-region choice.

## Feature → source mapping

| SOW dimension | Columns | Source |
|---|---|---|
| Renewable resource quality | `pvout_kwh_per_kwp_day` (practical PV potential); `cf_solar_realized`, `cf_wind_realized` | Solargis/World Bank country ranking (2020); Ember generation ÷ capacity |
| Land/acceptance constraints | `pop_density_per_km2`, `protected_area_pct`, `land_area_km2` | World Bank WDI API |
| Clean firm availability | `share_hydro_pct`; `geothermal_capacity_mw`; `egs_suitable_share`, `t5km_p90_c`, `heat_flow_mean_mwm2`, `plate_share_300km`, `geothermal_favourable`; `plate_distance_km` (legacy) | Ember; OWID (IRENA); Lucazeau (2019) heat flow + WorldClim 2.1 surface temperature on Natural Earth 50m polygons (`geothermal_egs.py`); PB2002 plate boundaries |
| Brownfield generation mix | `share_*_pct`, `gen_*_twh`, `cap_*_gw` per fuel | Ember yearly release (latest year per country, see `ember_year`) |
| Degree of interconnection | `net_import_share_pct`, `n_land_borders`, `is_island` | Ember; GeoDataSource borders |
| Demand volume | `demand_twh`, `demand_year`, `demand_source`; `demand_kwh_per_capita`; `population`, `population_year` | Ember (fallback: UN Energy Statistics gross demand; Monaco/San Marino: France/Italy per-capita proxy); World Bank SP.POP.TOTL (2025) |
| Expected 2050 demand | `population_2050`, `demand_kwh_per_capita_2050`, `demand_twh_2050` | World Bank population projections (UN WPP medium, source 40); per-capita heuristic: max(1.4 × today, geometric mean of today and 6000 kWh/cap) — electrification floor plus halfway convergence for developing countries. A screening heuristic, not a scenario; calibrates to India ~4.9k, China ~13k, US ~6.2k TWh |
| Cross-check | `demand_un_twh`, `demand_un_year` | UN Energy Statistics gross demand (ELGA), all countries |

## Data files (`data/`)

Files above ~1 MB that merely redistribute public datasets are listed in
`data/.gitignore` and not committed (140 MB together): the Ember release, the
GPW population grid, the EIA state tables, the UN balance, the WorldClim and
Lucazeau rasters, the Natural Earth shapefiles and the Malaysia handbook.
Fetch them from the sources below into `data/` before running the workflow.

- `yearly_full_release_long_format.csv` — Ember Yearly Electricity Data (49 MB)
- `solargis_pvpotential_countryranking_2020_data.xlsx` (+ LibreOffice CSV
  extracts) — [World Bank Data Catalog](https://datacatalog.worldbank.org/dataset/global-photovoltaic-power-potential-country)
- `wdi_*.json` — World Bank WDI API, most recent non-empty value
  (`SP.POP.TOTL` = population, 2025 for all countries)
- `un_energy_electricity_balance.csv` — UN Energy Statistics Database
  ([data.un.org](http://data.un.org/Data.aspx?d=EDATA&f=cmID%3AEL), commodity EL)
  for transactions gross production (EL01), imports (EL03), exports (EL04),
  final consumption (EL12) and gross demand (ELGA), all years, GWh. Downloaded
  per transaction because the bulk export is capped at 100k rows (cuts off
  alphabetically at "Jersey").
- `installed-geothermal-capacity.csv` — Our World in Data grapher (IRENA)
- `lucazeau2019_heat_flux_0p5deg.nc` — Lucazeau (2019, doi:10.1029/2019GC008389)
  global heat-flow map (0.5°, similarity-method interpolation of ~70k
  measurements), as redistributed on a regular grid by de Lavergne &
  Maisonnave (2024), SEANOE doi:10.17882/103233, CC-BY-4.0 (file
  `geothermal_forcing_regular.nc`; Wiley's own supplement is bot-blocked)
- `worldclim21_tavg_annual_10m.nc` — mean of the 12 WorldClim 2.1 10-arcmin
  monthly `tavg` rasters (1970–2000), built with PIL from `wc2.1_10m_tavg.zip`
- `ne_50m_admin_0_countries/`, `ne_50m_admin_1_states_provinces/` — Natural
  Earth 50m polygons (naciscdn.org), used for area-share features and the
  US/AU state splits
- `PB2002_boundaries.json` — Bird (2003) plate boundaries, fraxen/tectonicplates
- `GEODATASOURCE-COUNTRY-BORDERS.CSV` — land-border pairs
- `wem_energy.json` — OpenNEM monthly energy by fuel tech for the WEM/SWIS
  (`data.opennem.org.au/v3/stats/au/WEM/energy/all.json`, 50 kB)
- `au_facilities.json` — OpenNEM facility registry (WEM operating capacity
  by fuel tech, 380 kB)
- `Malaysia_Energy_Statistics_Handbook_2023.pdf` — Energy Commission
  (Suruhanjaya Tenaga), per-grid installed capacity as of 31 Dec 2021 (8 MB)
- `iso3166.csv` — ISO-3166 code mapping (lukes/ISO-3166)
- `country_coords.csv` — copy of priam-myopic `data/countries.csv` (capitals)

## Known caveats (screening-grade, fix before the report)

- **Realized CFs** conflate resource quality with fleet age and curtailment;
  wind CF is NaN where capacity < 0.1 GW (115 countries). Upgrade: Global Wind
  Atlas country means, or atlite/ERA5 as in WP1.
- **Geothermal resource** (`geothermal_egs.py`): `egs_suitable_share` is the
  share of land area with modelled T(5 km) ≥ 200 °C, from
  T = T_surf + q·z/k − A·z²/2k (Lucazeau 2019 heat flow q, WorldClim surface
  temperature, k = 2.5 W/m/K, A = 1 µW/m³), evaluated on a 0.1° grid inside
  Natural Earth polygons and area-weighted (cos lat). 5 km is today's
  drilling reach (IEA Future of Geothermal 2024); 200 °C is the industry's
  high-enthalpy threshold rather than the 150 °C binary-cycle minimum of
  Aghahosseini & Breyer 2020. Sensitivity: 150 °C admits ~31% of global land
  (median country share 0.46, tropical countries on modest heat flow score
  0.8–1.0), 175 °C ~10%, 200 °C ~4% (quartiles 0.00/0.01/0.07, p90 0.28).
  Leaders at 200 °C: Iceland 0.88, Serbia 0.60 (Pannonian), Japan 0.36, Chile
  0.28, Philippines 0.28, Hungary 0.27, Indonesia 0.24, Mexico 0.21, US West
  0.14. `t5km_p90_c` (90th-percentile T at 5 km) is the continuous quality
  ranking. `geothermal_favourable` = share ≥ 0.10 OR > 10 MW installed; the
  capacity clause is load-bearing because the 0.5° map cannot resolve narrow
  volcanic provinces — New Zealand, Kenya and Italy score only 0.04–0.07 on
  area despite world-class fields. Caveats: the Lucazeau map is an
  interpolation and is smooth in data-poor regions (Paraguay's 0.15 is a
  sparse Chaco-basin artefact); conductivity and heat production are global
  constants (sedimentary basins with k ≈ 2 run hotter); microstates without
  a 0.1° cell centre (Monaco, Maldives, Nauru, Tuvalu) take the nearest cell
  (`n_cells` = 0); the SWIS uses the whole of Western Australia.
  `plate_distance_km` (capital-to-boundary) is kept for continuity only —
  `plate_share_300km` is the polygon-based replacement.
- **Net-import share** understates interconnection for balanced traders
  (gross flows would be better); Ember lumps geothermal generation into
  "Other Renewables", so geothermal *generation* is not broken out — only
  capacity via OWID.
- **Demand fallbacks**: 7 microstates missing from Ember (AND ALB FSM LIE
  MHL PLW TUV) take UN gross demand (2024); Monaco and San Marino are folded
  into France/Italy in every source, so they get the neighbour's per-capita
  demand × population (`demand_source = proxy_*`). Ember vs UN gross demand
  agree within ±15% for most countries (median ratio 1.05; Ember includes
  losses), but the UN series is broken for a few (Bahrain negative, Guatemala,
  Zimbabwe, Botswana far too low) — `demand_un_twh` is a cross-check only,
  never used where Ember exists. Solargis PVOUT is NaN for 3 (incl. Iceland,
  excluded from their evaluation).
- **Population** is World Bank 2025 for every row; US regions apportion it by
  state population share (2013 census estimates, `state-population.csv`).

## Techno-economic baseline

`../technology-costs/` is a separate Snakemake workflow that compiles 2025
capex/opex/LCOE assumptions for the SOW technology palette from
PyPSA/technology-data plus referenced gap-fills, and plots them against
observed project costs. See `../technology-costs/README.md`.

## Slides

The kickoff beamer deck is `../../beamer/2026-09-08/` (decks are named by
meeting date, theme copied from `../../beamer/theme/`). The 16:9 renders from
`../technology-costs/figures/slides/` are copied into it by hand, and
`snakemake -c1` there builds `slides.pdf`. Its map,
archetype-list and share-bar images are rendered from `land-grid-map/index.html`
by `screenshot_map.py` (headless Chrome, `?shot=` export mode of the page) as a
rule of that Snakefile, so a change to the front-end or its data reaches the
slides on the next `snakemake -c1`; `python screenshot_map.py OUTDIR` also runs
standalone.
