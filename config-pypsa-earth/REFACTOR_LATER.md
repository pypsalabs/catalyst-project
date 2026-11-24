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
included: the base run is rebuilt from `build_bus_regions` on (bus regions per zone, so all profiles too), every stage from `add_electricity` on, and all are solved again.
Findings (2026-11-18):
- `subregion_shapes.geojson` is an output of `build_shapes`; re-running that rule rewrites all shape files, which are
  inputs of the OSM steps and of `build_powerplants`. For a run that exists the two subregion files are written by
  `scripts/write_subregion_shapes.py <run>` (the functions of `build_shapes`); a fresh build needs nothing.
- `apply_on` must stay `[cluster_network]`: in `simplify_network` the threshold `s_threshold_fetch_isolated` is a
  share of the "country" load, and the country is the zone at that point.
- `build_bus_regions` is keyed on `cluster_network` in the Snakefile, so the switch changes the bus regions of a
  base run too (Voronoi cells within a zone) and with them every profile: the rebuild of a region starts at
  `build_bus_regions`, not at `cluster_network` (found on 2026-11-19 in China's rebuild; the US West test was a
  stage of an existing base run and never rebuilt the regions). PyPSA-Earth handed that rule the country's sea
  areas instead of the subregions' (`retrieve_subregion`, `method: gadm`), so every zone lost its offshore
  regions; fixed in the fork on 2026-11-19 (upstream candidate, same in upstream main).
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

### I. 24/7 CFE buyers' share per country: what is left (noted 2026-11-19, list of 2026-11-22)

Since 2026-11-19 the buyers' share of demand is one value per country and horizon (`calibration/<year>/cfe_share.csv`
= min(20 %, scale x (data centres + 0.5 x other electricity use of RE100 members)); fork option
`catalyst: cfe: share: statistics`, commit 0127cc6c; evidence and builder in `misc-quarter1/datacentre-demand`, model
doc section "Demand for 24/7 Carbon-Free Electricity"). Open, in the order in which it should be done:

**Not yet tested end to end**

- **No stage has been solved with the table.** Done: the buyer loads on two prenetworks (table of 1 % = scalar 1 %,
  demand unchanged, one share per country), a dry run of `MA-cfe` 2030, the config check. Owed: Morocco one node to
  2035 and Singapore to 2030 through a throwaway overlay with its own learning market (so `results/learning/cfe*`
  stay as they are). Singapore is the one to watch: a buyer with 12.4 % of the demand of a land-constrained node may
  be infeasible. The solves could not run on 2026-11-19 / 22 because a China chain held the fork's Snakemake lock.
- **Dry runs with a free `config.yaml`.** The dry runs were made with the stage config layered over the running
  chain's config; the one of `MA-ref` stopped on a missing envelope table for oil, most likely from that layering,
  not confirmed. Repeat both when no chain runs.
- A fix after these tests means amending 0127cc6c (not pushed): the hash is cited in the README ("24/7 CFE
  catalyst") and in `model-doc/doc/sections/cfe_demand.tex`.

**Choices to revisit (all in `misc-quarter1/datacentre-demand/config.yaml`, `buyer_share`)**

- **Scale** is 1.0. Decided: bring it down to the 24/7 CFE supply that can plausibly come online by 2030; that
  check is not made (`misc-quarter1/technology-suppliers` holds the pipelines to compare with).
- **Cap** of 20 % of a country's demand: the level was set without a source, after "do the capping". It binds on
  Ireland in every horizon and on Denmark from 2045; 15 % would start to bind on the United States in 2050.
- **Weight** 0.5 on the other use of RE100 members: a choice.
- **Growth after 2030**: every country's data-centre demand grows like the world total of the `trend` variant. No
  country has a path of its own (India stays flat at 1.5 % because its demand grows as fast; Ireland sits at the cap).

**Data that is thin or does not add up**

- **Country values against the IEA's regions.** The country values sum to 161 TWh in Europe (IEA 114) and 179 TWh
  in Asia Pacific outside China (IEA 101). A country without a value still takes the full regional share, so e.g.
  Pakistan gets 1.4 %. Matters for the rest-of-world runs; a rule (remainder of the region, or a lower fallback) is
  undecided.
- **No national value found**: Belgium (elia.be refuses automated requests; 3.2 TWh today and 27.3 TWh by 2034
  seen in search results only), Austria, Czechia, Luxembourg, Taiwan, New Zealand, South Africa, Morocco.
- **No 2030 value in TWh read at the source**: Ireland (EirGrid's share only), Netherlands, Poland, Brazil, South
  Korea. **Read in a press report only**: Singapore, South Korea, Poland.
- **Found and not in use**, my judgement: Netherlands 15 % in 2030 (a bank's note on the grid operators'
  scenarios), India 57 TWh in 2030 (S&P Global through a news site).
- **Japan 2030** is a sum of two sources (Wood Mackenzie's 2024 value + OCCTO's increment), marked DERIVED.
- **Rows not checked one by one**: of the 84 country rows of the second research round six were compared with the
  downloaded documents; the 188 rows of the first round and the per-company rows of `data/buyers.csv` were checked
  for structure and totals only. Check a row before its number goes on a slide.
- **RE100 part**: held at its 2024 share of demand; the 77 of 557 TWh without a market breakdown are spread like
  the rest; the five data-centre operators' 92 TWh are taken out by data-centre use, not by their own regional
  reports.
- **Demand pathway**: the buyers' share is a share of a demand pathway that does not carry data-centre growth as an
  item (model US demand +416 TWh from 2024 to 2030, LBNL's data centres alone +457 TWh).
- **Licence**: `data/iea_table_a4.csv` is from an annex under CC BY-NC-SA 4.0; check before the data are released
  under CC BY 4.0.

**Below the country**

- **US West / US East** both take the national 9.6 % (2030). Data centres are not spread evenly over the states
  (Virginia, Texas, Arizona, Oregon); EPRI and LBNL publish state tables. A table per half would go into
  `calibration/<year>/regions/<R>/cfe_share.csv` and is picked up by `tables.smk` without a fork change.
- **Market zones** (Ireland's zone, Virginia in PJM, Chinese provinces): a share per zone needs the fork to key the
  table by zone as well as by country. Within a country the buyer sits at every bus in proportion to the load.

**Runs and documents**

- **No CFE pathway has the new share**: every CFE result on disk (Japan branches, pooled test regions, Morocco
  tests) was solved with the uniform 1 % (2030) to 10 % (2050). Reruns are launched by Lukas.
- **Model doc**: `build/model_doc.pdf` was compiled with the rule's `latexmk` command by hand. A full
  `snakemake -s modeldoc.smk` re-renders about twenty older figures whose inputs changed, some from the China
  networks that were being rebuilt. The new section points to the Demand subsection for the demand pathway, which
  is still "to be written".
- **Not pushed**: fork commit 0127cc6c and the parent commits of this work.

### J. Demand placed inside a country: India, Brazil, North-West Europe (noted 2026-11-23, US done 2026-11-24)

China and the two US regions take their state / province shares from the table `calibration/2024/demand_shares.csv`
(fork option `load_options: subnational_shares`), and every region places a unit's load by population
(`load_options: population_within_units`; README "Demand placement"). Open:

- **India and Brazil**: state shares from statistics (India: CEA; Brazil: EPE) as rows of the same table. First the
  read-only check (`scripts/check_demand_placement.py`); decided 2026-11-24: after the US result is confirmed.
- **North-West Europe**: the units are large (England is one), population inside them is now used; whether the
  weights of the units (GDP and population) are off has not been checked against national statistics per region.
- **Shares over time**: constant over the horizons in every region.

### E, rest. Each US half's own demand shape (noted 2026-11-17, time shift done 2026-11-23)

The two US stages use the national hourly series moved in time (README "US West / US East"). Open: the daily and
seasonal pattern of each half from EIA-930 (hourly demand per balancing authority, from 2015; needs a rule to apply
it to the 2013 series of the model).

## Questions to ask before a sweep is planned

**To the agent that plans a sweep: put the open questions listed here to the maintainer in the planning step, before the plan
is finalised. Do not pick an answer yourself and do not bury them in the plan.**

- **Item A, what the asymmetric factors are relative to.** The measured factors are relative to the middle third of
  the US fleet; the model applies them to each country's fleet efficiency (a mean over the whole fleet). With
  asymmetric factors the three tranches no longer average to the fleet efficiency (OCGT: (0.89 + 1 + 1.18) / 3 =
  1.02), so the fuel burnt at equal dispatch shifts. Either rescale the factors per carrier so that the fleet
  efficiency is kept, or accept the shift.
- **Item A, number of tranches.** Three equal thirds as now, or more (the table could carry quintiles)?
- **Item F, which regions get clusters per market zone.** US East is the candidate (15 % of load in a cluster of
  another zone); is the re-solve of every stage worth it for US West (6 %) and Brazil (4 %)? And does Denmark need a
  second cluster so that DK1 and DK2 exist apart (one cluster today)? North-West Europe cannot take the switch as
  it is (zones made of whole countries, Germany + Luxembourg).
- **Item F, China's 18 single-cluster provinces.** With 50 clusters over 28 zones, 18 provinces are one node and are
  matched by node. More clusters, or regional grids as zones for the small provinces, or accept it?


## Dropped

- **D. Onshore wind counts every forest as eligible land** (noted 2026-11-16, dropped by the maintainer on 2026-11-22):
  not needed, the forest sites are poor resources and the good ones are not used up. Measured on 2026-11-16: 99.5 % of
  Brazil's rainforest potential lies in cells with a capacity factor below 0.2, and the 2050 screening run uses 0.6 %
  of Brazil's potential. The one region where onshore wind is tight is North-West Europe (42 % of the potential used,
  120 of 246 class generators at their limit, 40 % of the potential on forest), where wind in managed forest is common
  practice. The letters of the other items are kept.

## Done: item H, cap on grid build-out (2026-11-23)

Decided by the maintainer: the central case is what the grids have delivered (US 1, North-West Europe 1, Brazil 2,
India 3, China 4 % per year on line volume from 2024), plans are a sensitivity; one cap per region and horizon on AC
lines and HVDC links together; the 2050 screening runs get the cap at its 2050 value. Fork option
`lines: expansion_limit` (f374de79), rates from `data/grid_expansion/grid_expansion.csv`. Record and tests: README
"Grid build-out". Not done: no pathway and no other `zero` run is solved with it; no plan-rate run; no ceiling per
corridor, no lead times.

## Done on 2026-11-23: items C, E (time shift), J (China)

- **C.** The scaled-down wind and solar plant list reaches the generators (fork 9d6a937b). Networks on disk predate it.
- **E.** Time shift of the national load series per US half (fork 8f290c58): West 1.77 h later, East 0.39 h earlier.
  The measured shapes stay open (above).
- **J.** China's demand per province from published shares (fork 563658d5), China rebuilt and re-solved; decided:
  China only for now, shares constant over the horizons.

## Done on 2026-11-24: demand placement in the US, population inside a unit, frozen grid in the 2024 runs

- **J, US part.** US states' shares from EIA retail sales of 2024 (rows of `calibration/2024/demand_shares.csv`,
  `scripts/build_demand_shares.py`; `subnational_shares: true` in `config.USW.yaml` / `config.USE.yaml`).
- **Population inside a unit** (fork option `load_options: population_within_units`, rule `build_region_population`;
  on in `statistics.yaml` for every stage). Changes the clusters of every multi-node region: all of them need a
  rebuild from the demand step on.
- **2024 runs with a frozen grid** (`overlay.now.yaml`: `ll: [v1.0]`, before `copt`). The solved networks are now
  named `..._lv1.0_3h.nc`; `model-doc/modeldoc.smk` and two model-doc scripts still name `results/NWE-now/...lcopt_3h.nc`
  and need the new name once NWE is re-solved.
- **Isolated buses**: the links that attach them carried a ramp limit of zero, which fixed their flow for the year
  (shedding at 8 buses of US East, 2 of US West, 1 of Brazil in every solve since September); fixed in
  `calibrate_network.attach_isolated_buses`.

## Done: item G, long AC lines (2026-11-23)

Decided by the maintainer on 2026-11-23, after published transfer capacities were collected for the US, Brazil,
Europe and India (`data/validation/transfer_capacities/`):

- **The rule:** fork option `lines: loadability` (commit e3b61211, a switch, off by default, upstream candidate; on in
  `statistics.yaml` for every stage). Every AC circuit of the base network carries at most `k(L) x SIL` where that is
  below its thermal rating, `k(L)` = the St. Clair curve at the circuit's own length; summed per clustered line. A
  first version took the distance between cluster centres as the length; it halved the capacity between US regions,
  which at 0.7 of the thermal rating was within 1.3 times NERC's transfer capabilities, and was dropped.
- **A security margin of 0.4 for every region** (`lines: s_max_pu` in `statistics.yaml`; PyPSA-Earth: 0.7): the
  margins at which the border circuits carry the published capacity are US West 0.60, US East 0.41, Brazil 0.40,
  India 0.35, North-West Europe 0.26 (2024) or 0.39 (reference grid of 2030); one value for all, China included,
  instead of regional values.
- Record, numbers and the India test: README "Loadability of long AC circuits"; model doc, Grid Data.
- Not done: no region but India is re-solved. Item H's last column must be measured again. The India derating test
  files were deleted on 2026-11-23 (its table is kept in the README).

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
