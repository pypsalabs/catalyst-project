# Deferred refactors of the fork (do in one sweep, not piecemeal)

Changes that are known to be needed but too cumbersome to do one at a time. Collect them here and do them together,
ideally in the same sweep as a full model rerun (see "Why one sweep" in the entries). Add an entry when you find
another one; do not fix a single item on its own.

Pointer to this file: `CLAUDE.md` (Conventions), so every agent session in this repo sees it.

## Open items

None. Add new items here (problem, target, what has to change with it, why it belongs in a sweep), and put anything
an item leaves undecided under "Questions to ask before a sweep is planned".

## Questions to ask before a sweep is planned

**To the agent that plans a sweep: put the open questions listed here to the maintainer in the planning step, before the plan
is finalised. Do not pick an answer yourself and do not bury them in the plan.**

No open questions at the moment.

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
