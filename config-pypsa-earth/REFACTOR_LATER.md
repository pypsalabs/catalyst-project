# Deferred refactors of the fork (do in one sweep, not piecemeal)

Changes that are known to be needed but too cumbersome to do one at a time. Collect them here and do them together,
ideally in the same sweep as a full model rerun (see "Why one sweep" in the entries). Add an entry when you find
another one; do not fix a single item on its own.

Pointer to this file: `CLAUDE.md` (Conventions), so every agent session in this repo sees it.

## Open items

Add new items here (problem, target, what has to change with it, why it belongs in a sweep), and put anything an item
leaves undecided under "Questions to ask before a sweep is planned".

### A. Tranche factors come from a table, not from numbers in the config (noted 2026-11-16)

**Problem.** `calibration: efficiency_spread` in `statistics.yaml` holds five numbers typed in by hand from
`data/validation/efficiency_spread.csv` (rounded to two digits; only `scripts/build_efficiency_spread.py --check`,
run by hand, notices a drift). It is the only adjustment of the fleet whose data sits in the config; every other one
is a switch whose rule reads `resources/<run>/statistics/<name>.csv`.
Second defect, same code: the model spreads the tranches symmetrically, `(1 - s), 1, (1 + s)`, but the measured
thirds are not symmetric (worst / best third relative to the middle one: CCGT 0.92 / 1.08, coal 0.91 / 1.08,
OCGT 0.89 / 1.18, oil 0.84 / 1.12, lignite 0.97 / 1.05; the model uses 0.86 / 1.14 for OCGT and oil).

**Target.** The spread is always per carrier: there is no single value for all carriers, neither as a number in the
config nor as a fallback in the code (decided 2026-11-16). The option becomes a plain switch (`efficiency_spread:
true`); a carrier without a row in the table is not split. `prepare_network` takes
`resources/<run>/statistics/efficiency_spread.csv` as an input; `tables.smk` writes it from
`data/validation/efficiency_spread.csv`. The table carries one factor per tranche and carrier (`factor_low`,
`factor_high`, the middle one), so the measured asymmetry enters and nothing is rounded by hand.

**The commit "efficiency spread of the tranches per carrier" (`fd2f4ba8`) is removed with it** (asked 2026-11-16):
it is redundant as a commit of its own, because the split should have been per carrier from the start. No commit of
the final history introduces a single spread for all carriers and then generalises it; the tranche paragraph of the
model doc loses its third commit and the sentence on it.

**History (decided 2026-11-16): folded into the first tranche commit (`25c6e095`)**, so that commit is per carrier
and table-driven from the start. This rewrites the 40 commits after it (third rewrite of the fork history: backup
branch, old-to-new hash map, new hashes in the model doc and README, force-push on an explicit go).

**Changes with it.** Fork: `split_tranches` in `scripts/calibrate_network.py`, `Snakefile`, `config.default.yaml`,
`doc/configtables/calibration.csv` (which still calls the option a float, wrong since the per-carrier commit).
Project: `tables.smk`, `statistics.yaml`, `scripts/build_efficiency_spread.py` (`--check` goes), `check_sources.py`.
Model doc: tranche paragraph, Table `tab:fleetspread`, YAML block `tranches`, the three commit sentences.

**Why in a sweep.** Changes every `now`, `zero` and pathway network (prepare_network and everything after it) and
touches the tranche commits of the fork.

### B. Model doc: remove the subsection "Check against real metrics" of Existing Fleet (noted 2026-11-16)

**Problem / target.** The subsubsection `sec:fleet-check` at the end of `model-doc/doc/sections/fleet.tex` (plant
list against the capacity statistic, plants dropped by filled retirement years, national capacity and heat-rate
statistics, "What stays unvalidated") is to be removed. Asked for by the maintainer; reason not recorded.

**Decided 2026-11-16.**
- "What stays unvalidated", the list at the end of the subsection, goes too.
- The two figures (`fig:fleetcheck`, `fig:fleetdropped`) and their scripts and rules are deleted
  (`model-doc/scripts/plot_fleet_check.py`, `plot_fleet_dropped.py`, rules `modeldoc_fleet_check`,
  `modeldoc_fleet_dropped`, their `modeldoc_pdf` inputs). `scripts/check_fleet.py` itself stays: it also writes the
  tables of other figures (sources, vintage, retirements, plant-list tables).
- The four sentences earlier in the section that point to `sec:fleet-check` for their evidence (intro of
  "Adjustments", gas-mapping paragraph twice, plant-list scaling) get the one number each needs written into the
  sentence; the references go.
- The grid section's twin, "Check against real project metrics" (`sec:grid-check`), stays.

**Changes with it.** `fleet.tex` and `modeldoc.smk` as above; bibliography entries cited only in the subsection;
the two "unvalidated" bullets written on 2026-11-16 (US tranche spread, nuclear 40-year lifetime) go with the list.

**Why here.** A change of the document only (no fork change, no rerun); listed here by request so it is done together
with the sweep, whose item A rewrites the same section.

### C. `scale_down` of the wind and solar plant list does not reach the network (found 2026-11-16)

**Problem.** Fork commit `d040060e` (`electricity: estimate_renewable_capacities: scale_down`) scales the plants of a
country down to the IRENA total where the list exceeds it, but in `attach_wind_and_solar`
(`scripts/add_electricity.py`) the capacities handed to the generators (`caps_final`) are copied from the plant list
*before* the scaling, so only the logged number and the gap fill see the scaled values. Found by
`scripts/check_renewables.py` (table `model-doc/build/renewables_check/capacity.csv`) and visible in the rule's own
log ("plant list scaled to the statistics (x0.84) ... gap filled = 18.16 GW" for India's solar, where no gap exists).
Effect in the networks of 2026-11-13: China onshore wind 510.9 GW against IRENA's 480.0, China offshore 55.5 against
41.3, India solar 115.7 against 97.6, GB offshore 18.9 against 15.9, NL offshore 6.8 against 4.7; about 69 GW in all.
The one-node runs are not affected (their fleet is the statistic). The observed capacity factors of these countries
are generation over the *statistic's* capacity, so the model generates more wind and solar there than observed.

**Target.** Hand the scaled capacities on (take the copy after the scaling, or scale both). Two lines.

**Changes with it.** Fork: `attach_wind_and_solar`. Model doc: the paragraph "Take installed wind and solar from
IRENA 2024 and scale the plant list down to it" in `model-doc/doc/sections/renewables.tex` states the defect and its
numbers; they go once it is fixed, and `check_renewables.py capacity` must then show no country above the statistic.

**Why in a sweep.** Changes `elec.nc` and everything after it for US (since 2026-11-17: USW, USE), CN, IN and NWE.

### D. Onshore wind counts every forest as eligible land, rainforest included (noted 2026-11-16)

**Problem.** `renewable: onwind: copernicus: grid_codes` of v0.9.0 holds all twelve forest classes of the Copernicus
map (111-126), at the full 3 MW/km2. Brazil's onshore potential is 17,100 GW, about half of it on forest and 5,300 GW
on closed evergreen broadleaf forest (code 112); no law bans wind in the Amazon biome outright, but the 80 % legal
reserve of the Forest Code, the conservation units and the indigenous lands leave no room for such a figure, and no
wind farm stands in a state of the North region (ABEEolica 2024).

**Measured effect (2026-11-16, read-only, from the `zero` screening networks and the cells files).** Small where the
forest is rainforest, because rainforest is not windy: 99.5 % of Brazil's code-112 potential lies in weather cells
with a capacity factor below 0.2, and the 2050 screening run builds only in classes above 0.3 (68 GW new, 0.6 % of
the potential used). With potential-weighted cluster profiles (v0.9.0) the forest pulled the profile of every
northern cluster down; the capacity weights and the resource classes of the fork removed that. Where the effect is
real is temperate forest: in NWE 40 % of the onshore potential stands on forest (18 % in the cells above 0.3), and
the 2050 screening run uses 42 % of the region's potential with 120 of 246 class generators at their limit. There,
wind in managed forest is common practice (Germany 11 % of capacity, Sweden, Finland, Scotland), so a blanket
exclusion would be wrong in the other direction. The same pattern holds for mountains (the Alps are eligible).

**Target (to be decided).** In rising order of effort: (1) drop code 112 (and 122) from `grid_codes` of onshore wind,
a config line, which also takes out non-tropical evergreen broadleaf forest; (2) a share per land-cover class instead
of all-or-nothing (Eurek et al. 2017 use 10 % for every forest class), a new fork option; (3) exclude primary /
unmanaged forest from a second raster: the forest-management map of Lesiv et al. 2022 (100 m, on the Copernicus grid,
class 11 = no signs of management; Zenodo 5115984, CC BY 4.0) or Intact Forest Landscapes; as an input of the rule
with a switch, not a path option.

**Why in a sweep.** Changes `build_renewable_profiles` for every stage (hours per multi-node region) and every
network after it. Model doc: the bullet on Brazil's potential in "Eligible land" of
`model-doc/doc/sections/renewables.tex` goes or changes with it.

### E. One hourly demand shape for US West and US East (noted 2026-11-17)

**Problem.** The fork has one synthetic hourly demand series per country (GEGIS, DemandCast as fallback), spread over
the buses by population and GDP. Since 2026-11-17 the US is two stages, `USW` and `USE` (README "US West / US East"),
both `countries: [US]`: each gets the national series, scaled to its annual demand
(`calibration/<year>/regions/<R>/demand.csv`). The US series is a blend of four time zones; the West's real load runs
2-3 hours behind the East's, and its evening peak falls later against its solar output than the model has it. The
former single `US` stage had the same error for its western buses.

**Target (to be decided).** A demand shape per half: (1) shift the national series by the half's mean offset to UTC
(no new data; keeps the blended shape); (2) hourly demand per interconnection or balancing authority from EIA-930
(public, from 2015, so not the model's weather year 2013: needs a rule for mapping it); (3) a regional run of the
synthetic demand model, if its inputs allow one. Whichever it is enters as a statistics table of the run and a switch
in `build_demand_profiles`, not as a path option.

**Changes with it.** Fork: `build_demand_profiles` (and `build_demand_profiles_horizon`). Parent:
`scripts/build_region_tables.py`, `tables.smk`, README, model doc (Demand).

**Why in a sweep.** Changes the demand profiles and every network after them for both US stages.

### F. Clusters per market zone for every multi-node region (noted 2026-11-18)

**Now:** the 24/7 CFE buyers are matched per market zone (`catalyst: cfe: zones: statistics`, README "Market zones").
The clusters are formed per country, so a cluster can lie across a zone border; `scripts/build_market_zones.py`
gives it the zone holding most of its load. Share of load in a cluster assigned to another zone on the networks of
2026-11-18: NWE 0.9 %, BR 3.6 %, USW 6.3 %, USE 15.4 %. China (23.7 %, three municipalities without a cluster) has
the switch `catalyst: cluster_by_zone: true` in `config.CN.yaml` (decided 2026-11-18); its networks take it at
their next rebuild, which is a full one (the China base run predates the sweep of 2026-11-16).

**Change:** set `catalyst: cluster_by_zone: true` in the other regions too. `merge_config.py` turns it into
PyPSA-Earth's `subregion` block (`method: gadm`, `define_by_gadm` = the zone definitions of
`data/market_zones/`, `apply_on: [cluster_network]`); `cluster_network` then clusters per (zone, sub_network).
The mechanism is in place and tested (README "Market zones": US West 2024 dispatch with clusters per zone, same
generation mix as before, every cluster inside one zone).

**Why deferred:** it changes the network of every scenario of the region, the validated `now` / `zero` networks
included: every stage is rebuilt from `cluster_network` on and solved again (the profiles are not rebuilt).
Findings (2026-11-18):
- `subregion_shapes.geojson` is an output of `build_shapes`; re-running that rule rewrites all shape files, which are
  inputs of the OSM steps and of `build_powerplants`. For a run that exists the two subregion files are written by
  `scripts/write_subregion_shapes.py <run>` (the functions of `build_shapes`); a fresh build needs nothing.
- `apply_on` must stay `[cluster_network]`: in `simplify_network` the threshold `s_threshold_fetch_isolated` is a
  share of the "country" load, and the country is the zone at that point; for `build_bus_regions` PyPSA-Earth hands
  over the country's sea areas instead of the subregions' (Snakefile `retrieve_subregion`, `method: gadm`), so the
  offshore regions of every subregion would be lost (same in upstream main; worth an upstream issue).
- The clusters go to the zones by load: US West 20 = CAISO 11, Southwest 6, Northwest 3 (by country: 6 / 9 / 5);
  China 50 = Southern market 7, Shandong 4, Jiangsu 4, three zones with 3, four with 2 and 18 provinces with a
  single cluster (Inner Mongolia, Xinjiang and Gansu among them), where zone matching is node matching.
- Bus names take the zone as prefix (`PJM0 3`); `country` is put back after clustering and no zone column survives,
  so the zone still comes from the table (then with every cluster inside one zone). The bus names in
  `misc-quarter1/weather-years/config.yaml` go stale.
- A zone of two countries (Germany + Luxembourg): after clustering `country` is reset from the cluster's
  coordinates, so Luxembourg would vanish from everything keyed on `country` (energy bands, net imports, CO2 price).
  Such zones cannot use this route.
- Only `distribute_cluster: load` works (our default); every (zone, sub_network) group needs at least one cluster.

**Questions:** see below.

## Questions to ask before a sweep is planned

**To the agent that plans a sweep: put the open questions listed here to the maintainer in the planning step, before the plan
is finalised. Do not pick an answer yourself and do not bury them in the plan.**

- **Item A, what the asymmetric factors are relative to.** The measured factors are relative to the middle third of
  the US fleet; the model applies them to each country's fleet efficiency (a mean over the whole fleet). With
  asymmetric factors the three tranches no longer average to the fleet efficiency (OCGT: (0.89 + 1 + 1.18) / 3 =
  1.02), so the fuel burnt at equal dispatch shifts. Either rescale the factors per carrier so that the fleet
  efficiency is kept, or accept the shift.
- **Item A, number of tranches.** Three equal thirds as now, or more (the table could carry quintiles)?
- **Item D, which rule for forest.** Drop the rainforest codes only, a reduced share on all forest, or a raster of
  unmanaged forest (see the three targets of item D)? And should a slope or elevation limit come with it?
- **Item E, which demand shape for the two US stages.** A time shift of the national series, EIA-930 data of another
  year, or a regional run of the demand model?
- **Item F, which regions get clusters per market zone.** US East is the candidate (15 % of load in a cluster of
  another zone); is the re-solve of every stage worth it for US West (6 %) and Brazil (4 %)? And does Denmark need a
  second cluster so that DK1 and DK2 exist apart (one cluster today)? North-West Europe cannot take the switch as
  it is (zones made of whole countries, Germany + Luxembourg).
- **Item F, China's 18 single-cluster provinces.** With 50 clusters over 28 zones, 18 provinces are one node and are
  matched by node. More clusters, or regional grids as zones for the small provinces, or accept it?

## Done: sweep of 2026-11-16

All three items below were done in one go (fork history rewritten once, model doc and README updated). **No full
model rerun has been made since**: every result older than the sweep uses the old retirement rule, the old tranche
spread and the old plant lists. The rerun is launched by hand.

Decisions taken for it (2026-11-16):
- plants already past their lifetime in 2024: PyPSA-Earth's default (dropped by the plant-list filter, the capacity
  statistic scaled onto the remaining plants);
- lifetimes: the cost table's, as PyPSA-Eur's pathway code (reported year first; coal, lignite, nuclear 40 years,
  gas and oil 25, biomass and geothermal 30), with the consequences known (33 % of the US fleet of 2024 left in 2030);
- retirement figure: filled dates only, in "Standard procedure" (the dashed line there is PyPSA-Earth's default
  lifetimes, not reported dates);
- tables per run, written by a rule; tranche spread from EIA plant data; history rewritten; rerun launched by hand.

### 1. Config options do not carry file paths

The Snakemake rule wires the files, the config only switches a feature on (a boolean, `enable: true`, or the keyword
`statistics`). Tables: `resources/<run>/statistics/<name>.csv` (fork: `STATISTICS`, default rule `copy_statistics`
from `data/statistics/`); in this project written by `tables.smk` from `calibration/<year>/`, `data/hvdc/` and the
EGS potential, the palette's cost rows by `technology-assumptions/assumptions.smk`. Year and variant are plain values
(`catalyst: tables: {year, demand_year}`, `catalyst: envelope`). Details: README "Where the statistics enter".
**Keep it that way: do not add a path-valued option to the fork.** Upstream's own path options
(`conventional: nuclear: p_max_pu: data/...csv`, `custom_powerplants: filepaths`, `agg_p_nom_limits: file`) were left.

### 2. Efficiency tranches: spread measured per carrier

`calibration: efficiency_spread: {coal: 0.08, lignite: 0.04, CCGT: 0.08, OCGT: 0.14, oil: 0.14}` in
`statistics.yaml`, from EIA-923 / EIA-860 for 2024 (`scripts/build_efficiency_spread.py`, `--check` compares the
config with `data/validation/efficiency_spread.csv`). Limits, stated in the model doc: US fleet applied to every
region; lignite rests on nine plants.

### 3. Retirement by lifetimes; the never-retire commit is gone

Fork option `electricity: powerplants_lifetimes: costs` (set in `overlay.myopic.yaml`); the commit "retire power
plants only at reported retirement dates" (`fill_missing_dateout`) is no longer in the history. Hydro never retires.
The `now` / `zero` stages keep PyPSA-Earth's default lifetimes (powerplantmatching's).
Left as is, to look at when the results of the rerun are in: nuclear retires after 40 years although many reactors
hold licences for 60 (model doc, "What stays unvalidated").
