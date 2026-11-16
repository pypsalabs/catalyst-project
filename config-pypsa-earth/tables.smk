# SPDX-License-Identifier: CC0-1.0
#
# The tables of the fork's statistics options, per run (included in every stage config through custom_rules by
# merge_config.py).
#
# The fork's options are switches (`load_options: annual_totals: true`, `electricity: powerplants_statistics: enable`,
# `costs: fuel_prices: true`, ...); its rules read the tables from resources/<run>/statistics/<name>.csv (STATISTICS in
# the fork's Snakefile). This rule fills that directory from the project's tables, so the wiring of every file is here
# and not in a config value:
#
#   calibration/<year>/<name>.csv            demand, capacity, efficiency, generation, hydro_generation,
#                                            hydro_max_hours, fuel_prices, co2_prices, net_imports
#   calibration/<demand_year>/demand.csv     demand of a run with another demand year (overlay.zero: 2050)
#   calibration/<horizon>/demand.csv         demand_<horizon>: the demand of a planning horizon (myopic)
#   calibration/<year>/envelope/<variant>/   conventional_<carrier>_<attr>: the operating envelope of the existing fleet
#   data/hvdc/                               dc_ratings, dc_projects
#   misc-quarter1/geothermal/build/          supply_curve_egs: the EGS potential per cell
#
# The year and the variant are plain values of the stage config:
#   catalyst: tables: {year: 2024, demand_year: 2024}     (defaults)
#   catalyst: envelope: floor | nofloor                   (default floor)
# The palette's cost rows (cost_overrides_<year>.csv) are written by technology-assumptions/assumptions.smk.
#
# Files are copied with their modification time: a table is as old as its source, so that outputs shared between runs
# (run.sh link_resources: base.nc, renewable profiles, ...) do not look outdated against a fresh copy.

import re
from shutil import copy2

_CATALYST = config.get("catalyst") or {}
_TABLES = _CATALYST.get("tables") or {}
_HERE = "../../config-pypsa-earth"   # relative to the fork root, like the custom_rules paths
_YEAR = _TABLES.get("year", 2024)
_CAL = f"{_HERE}/calibration"
_ENVELOPE = f"{_CAL}/{_YEAR}/envelope/{_CATALYST.get('envelope', 'floor')}"
_SOURCES = {
    "demand": f"{_CAL}/{_TABLES.get('demand_year', _YEAR)}/demand.csv",
    **{
        name: f"{_CAL}/{_YEAR}/{name}.csv"
        for name in ["capacity", "efficiency", "generation", "hydro_generation", "hydro_max_hours", "fuel_prices",
                     "co2_prices", "net_imports"]
    },
    "dc_ratings": f"{_HERE}/data/hvdc/hvdc_ratings.csv",
    "dc_projects": f"{_HERE}/data/hvdc/hvdc_project_table.csv",
    "supply_curve_egs": "../../misc-quarter1/geothermal/build/egs_potential.csv",
}


def _catalyst_table(w):
    if w.table in _SOURCES:
        return _SOURCES[w.table]
    horizon = re.fullmatch(r"demand_(\d{4})", w.table)
    if horizon:
        return f"{_CAL}/{horizon.group(1)}/demand.csv"
    return f"{_ENVELOPE}/{w.table[len('conventional_'):]}.csv"


rule catalyst_statistics:
    input:
        _catalyst_table,
    output:
        STATISTICS + "{table}.csv",
    wildcard_constraints:
        table="|".join(sorted(_SOURCES)) + r"|demand_\d{4}|conventional_[A-Za-z]+_p_(min|max)_pu",
    run:
        copy2(input[0], output[0])


ruleorder: catalyst_statistics > copy_statistics
