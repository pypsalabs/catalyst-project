# SPDX-License-Identifier: CC0-1.0
"""
Check the existing fleet of the spatially resolved regions and the capacity statistics, without rerunning anything.

Rebuilds in memory what build_powerplants makes of powerplantmatching's matched plant list (the cached
matched_data_red.csv under ~/.local/share/powerplantmatching/data/out/, the file build_powerplants wrote for the region),
with the fork default of the `now` stages (decommissioning years filled from lifetimes, plants with DateOut < 2022 or
DateIn > 2023 dropped) and with reported retirement dates only (to tell which plants the filled years drop), and
scales both to calibration/2024/capacity.csv with the fork's own harmonise_to_statistics. Compares the capacity statistics
with Ember's own rows (capacity too small for the generation) and with national statistics (data/validation/fleet_national.csv)
and national fleet efficiencies. Existing networks, resources and results are not touched. Writes to model-doc/build/fleet_check/:

    groups.csv        region, group: plant list (both date treatments), statistic, share of the statistic at synthetic sites
    dropped_<R>.csv   plants dropped only by filled (not reported) retirement dates, largest first
    gas.csv           region: GW of CCGT and OCGT, and their mean efficiency, with the default gas mapping and with
                      electricity.gas_technology_mapping of statistics.yaml
    ember_rows.csv    country, group: Ember capacity, generation, capacity factor, the previous and the current table's capacity
    national.csv      country, group: the table's capacity against a national statistic
    efficiency.csv    country, carrier: the fleet efficiency of the table against a national statistic
                      (data/validation/fleet_efficiency_national.csv)
    world.csv         country, group: plant list of the `now` stages and the statistic, for every modelled country (all
                      sixteen stages; hydro left out); lignite_gw = the coal group's lignite in the plant list (the model
                      splits the group into the carriers coal and lignite by the plant list's fuel type)
    sources.csv       stage, fuel, sources: plants and GW of powerplantmatching's matched list (every status it keeps) by
                      the set of source databases that report the plant
    fields.csv        stage, fuel: share of the matched list's capacity that reports a commissioning year, a decommissioning
                      year, an efficiency
    retirements.csv   region, group, year: GW of the 2024 fleet still in operation (decommissioning year after the year),
                      scaled to the statistic, with missing years filled from the cost table's lifetimes (pathway
                      stages) and from powerplantmatching's (fork default)

Usage (from config-pypsa-earth): ../models/pypsa-earth/.pixi/envs/default/bin/python scripts/check_fleet.py
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORK = os.path.join(HERE, "..", "models", "pypsa-earth")
sys.path.insert(0, os.path.join(FORK, "scripts"))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import powerplantmatching  # noqa: E402,F401  (registers the .powerplant accessor)
import yaml  # noqa: E402
from _helpers import two_digits_2_name_country  # noqa: E402
from build_calibration import BACKFILL_CF, ember, fuel_table  # noqa: E402
from build_powerplants import (  # noqa: E402
    fill_decommissioning_years_from_costs,
    harmonise_to_statistics,
    replace_natural_gas_technology,
)

OUT = os.path.join(HERE, "model-doc", "build", "fleet_check")
PM_OUT = os.path.expanduser("~/.local/share/powerplantmatching/data/out")
CAPACITY = os.path.join(HERE, "calibration", "2024", "capacity.csv")
NATIONAL = os.path.join(HERE, "data", "validation", "fleet_national.csv")
NATIONAL_EFFICIENCY = os.path.join(HERE, "data", "validation", "fleet_efficiency_national.csv")
REGIONS = {"US": ["US"], "BR": ["BR"], "IN": ["IN"], "CN": ["CN"], "NWE": "IE GB FR BE NL LU DE DK CH AT CZ PL".split()}
REFERENCE_YEAR = 2024
NOW_FILTER = "(DateOut >= 2022 or DateOut != DateOut) and (DateIn <= 2023 or DateIn != DateIn)"  # fork default, the `now` stages
REPORTED_FILTER = "(DateOut >= 2022 or DateOut != DateOut)"  # overlay.myopic.yaml
GROUPS = yaml.safe_load(open(os.path.join(FORK, "config.default.yaml")))["electricity"]["powerplants_statistics"]["groups"]
GAS_MAPPING = yaml.safe_load(open(os.path.join(HERE, "statistics.yaml")))["electricity"].get("gas_technology_mapping", {})
EFFICIENCY = os.path.join(HERE, "calibration", "2024", "efficiency.csv")
COSTS = os.path.join(FORK, "resources", "US-now", "costs_2025_elec.csv")  # cost table of the pathway's base year: lifetimes
DEFAULT_LIFETIME = yaml.safe_load(open(os.path.join(FORK, "config.default.yaml")))["costs"]["fill_values"]["lifetime"]


def matched(codes):
    """powerplantmatching's final plant list for these countries: the newest cached matched_data_red.csv whose countries are
    exactly theirs."""
    names = {two_digits_2_name_country(c) for c in codes}
    found = []
    for fn in glob.glob(os.path.join(PM_OUT, "*", "matched_data_red.csv")):
        countries = set(pd.read_csv(fn, usecols=["Country"]).Country.dropna())
        if countries == names:
            found.append(fn)
    if not found:
        raise FileNotFoundError(f"no cached powerplantmatching list for {sorted(names)}")
    fn = max(found, key=os.path.getmtime)
    return pd.read_csv(fn, index_col=0), names


def group_of(ppl):
    g = pd.Series(np.nan, index=ppl.index, dtype=object)
    for group, spec in GROUPS.items():
        spec = spec if isinstance(spec, dict) else {"fueltypes": spec}
        b = ppl.Fueltype.isin(spec["fueltypes"])
        if spec.get("exclude_technologies"):
            b &= ~ppl.Technology.isin(spec["exclude_technologies"])
        g[b] = group
    return g


def plant_list(raw, names, fill_dateout, query, gas_mapping=GAS_MAPPING, lifetimes="powerplantmatching"):
    """The plant list as build_powerplants makes it before the statistics (no custom plants in any stage); missing
    decommissioning years filled with powerplantmatching's lifetimes (the fork default, the `now` stages), with the
    cost table's (`electricity: powerplants_lifetimes: costs`, the pathway stages), or not at all (fill_dateout False:
    reported years only, to tell which plants a filled year drops)."""
    ppl = raw.copy()
    reported = ppl.DateOut.notna()
    if fill_dateout and lifetimes == "costs":
        ppl = fill_decommissioning_years_from_costs(ppl, pd.read_csv(COSTS, index_col=0), DEFAULT_LIFETIME)
    elif fill_dateout:
        ppl = ppl.powerplant.fill_missing_decommissioning_years()
    else:
        ppl = ppl.powerplant.fill_missing_commissioning_years()
    ppl["reported_dateout"] = reported
    ppl = ppl[ppl.Country.isin(names)].query(query)
    return ppl.powerplant.convert_country_to_alpha2().pipe(replace_natural_gas_technology, gas_mapping)


def region(r):
    raw, names = matched(REGIONS[r])
    now = plant_list(raw, names, True, NOW_FILTER)
    reported = plant_list(raw, names, False, REPORTED_FILTER)
    reported = reported[~(pd.to_numeric(reported.DateIn, errors="coerce") > REFERENCE_YEAR)]
    scaled = harmonise_to_statistics(now.copy(), CAPACITY, GROUPS, REFERENCE_YEAR)

    # plants the `now` filter drops only because of a filled decommissioning year
    dropped = reported.loc[reported.index.difference(now.index)]
    dropped = dropped[(pd.to_numeric(dropped.DateIn, errors="coerce") <= 2023) | dropped.DateIn.isna()]
    dropped = dropped.assign(group=group_of(dropped)).dropna(subset=["group"])
    dropped[["Name", "Fueltype", "Technology", "Country", "Capacity", "DateIn", "group", "lat", "lon"]].sort_values(
        "Capacity", ascending=False).to_csv(os.path.join(OUT, f"dropped_{r}.csv"), index=False, float_format="%.1f")

    stats = pd.read_csv(CAPACITY).set_index(["country", "group"]).gw
    stats = stats[stats.index.get_level_values(0).isin(REGIONS[r])].groupby(level=1).sum()
    synthetic = scaled[scaled.Name.astype(str).str.endswith(" statistics")]
    rows = []
    for group in GROUPS:
        if group == "hydro":
            continue
        gw = lambda df: df.Capacity[group_of(df) == group].sum() / 1e3
        rows.append(dict(
            region=r, group=group,
            plant_list_now_gw=gw(now), plant_list_reported_gw=gw(reported),
            dropped_by_filled_dates_gw=dropped.Capacity[dropped.group == group].sum() / 1e3,
            statistic_gw=stats.get(group, np.nan), model_gw=gw(scaled),
            synthetic_gw=gw(synthetic),
        ))

    # gas units by carrier with the fork's default mapping and with electricity.gas_technology_mapping, and the fleet
    # efficiency they get (capacity-weighted, calibration/2024/efficiency.csv as add_electricity reads it)
    table = pd.read_csv(EFFICIENCY).set_index(["country", "carrier"]).efficiency
    eff = lambda c, k: table.get((c, k), table.get(("*", k), np.nan))
    default = harmonise_to_statistics(plant_list(raw, names, True, NOW_FILTER, {}), CAPACITY, GROUPS, REFERENCE_YEAR)
    gas = []
    for variant, df in [("default", default), ("mapping", scaled)]:
        g = df[df.Fueltype.isin(["CCGT", "OCGT"])]
        e = np.array([eff(c, k) for c, k in zip(g.Country, g.Fueltype)])
        gas.append(dict(region=r, variant=variant, ccgt_gw=g.Capacity[g.Fueltype == "CCGT"].sum() / 1e3,
                        ocgt_gw=g.Capacity[g.Fueltype == "OCGT"].sum() / 1e3,
                        efficiency=float((e * g.Capacity).sum() / g.Capacity.sum())))
    return rows, gas


def ember_rows():
    """Ember's capacity per country and group against its generation, and the capacity the table now carries."""
    e, _, _ = ember(REFERENCE_YEAR)
    gen = fuel_table(e, "Electricity generation", "TWh")
    cap = fuel_table(e, "Capacity", "GW").reindex(gen.index).fillna(0.0)
    table = pd.read_csv(CAPACITY).set_index(["country", "group"]).gw
    t = pd.DataFrame({"ember_gw": cap, "twh": gen, "table_gw": table.reindex(gen.index)})
    t["typical_cf"] = t.index.get_level_values(1).map(BACKFILL_CF)
    # the table before 2026-11-04: Ember's capacity, back-filled at the typical capacity factor only where it was zero
    t["previous_gw"] = t.ember_gw.where(t.ember_gw > 0, t.twh / (8.76 * t.typical_cf))
    t["ember_cf"] = t.twh / (t.ember_gw * 8.76)
    t["previous_cf"] = t.twh / (t.previous_gw * 8.76)
    t["table_cf"] = t.twh / (t.table_gw * 8.76)
    # generation the capacity cannot deliver even at full output
    t["unreachable_twh"] = (t.twh - t.previous_gw * 8.76).clip(lower=0.0)
    return t[t.twh > 0]


STAGES = "US BR IN CN NWE SG IS CA RU OCE NAM SAM MEA EUR AFR ASI".split()   # every stage with a `now` solve
FUELS = {  # matched-list fuel type -> fuel of the sources figure
    "Hard Coal": "coal", "Lignite": "coal", "Natural Gas": "gas", "Oil": "oil", "Nuclear": "nuclear",
    "Solid Biomass": "biomass", "Biogas": "biomass", "Waste": "biomass", "Bioenergy": "biomass", "Geothermal": "geothermal",
    "Hydro": "hydro", "Wind": "wind", "Solar": "solar"}


def stage_countries(stage):
    return yaml.safe_load(open(os.path.join(HERE, f"config.{stage}.yaml")))["countries"]


def world():
    """Plant list of the `now` stages against the statistic, per country and group, for every modelled country."""
    rows = []
    stats = pd.read_csv(CAPACITY).set_index(["country", "group"]).gw
    for s in STAGES:
        raw, names = matched(stage_countries(s))
        now = plant_list(raw, names, True, NOW_FILTER)
        now["group"] = group_of(now)
        gw = now.groupby(["Country", "group"]).Capacity.sum() / 1e3
        lignite = now[now.Fueltype == "Lignite"].groupby("Country").Capacity.sum() / 1e3
        for c in stage_countries(s):
            for group in GROUPS:
                if group != "hydro":
                    rows.append(dict(stage=s, country=c, group=group, plant_list_gw=gw.get((c, group), 0.0),
                                     statistic_gw=stats.get((c, group), np.nan),
                                     lignite_gw=lignite.get(c, 0.0) if group == "coal" else 0.0))
    return pd.DataFrame(rows)


def sources():
    """The matched list by fuel and by the set of databases that report each plant, and the fields it fills."""
    rows, fields = [], []
    for s in STAGES:
        raw, _ = matched(stage_countries(s))
        raw = raw.assign(fuel=raw.Fueltype.map(FUELS).fillna("other"),
                         sources=raw.projectID.astype(str).str.findall(r"'(\w+)':").map(lambda k: "+".join(sorted(set(k)))))
        g = raw.groupby(["fuel", "sources"]).Capacity.agg(["size", "sum"]).reset_index()
        rows.append(g.rename(columns={"size": "plants", "sum": "gw"}).assign(stage=s, gw=lambda d: d.gw / 1e3))
        for fuel, d in raw.groupby("fuel"):
            w = d.Capacity / d.Capacity.sum()
            fields.append(dict(stage=s, fuel=fuel, gw=d.Capacity.sum() / 1e3, plants=len(d),
                               datein=float(w[d.DateIn.notna()].sum()), dateout=float(w[d.DateOut.notna()].sum()),
                               efficiency=float(w[d.Efficiency.notna()].sum())))
    return pd.concat(rows)[["stage", "fuel", "sources", "plants", "gw"]], pd.DataFrame(fields)


def retirements(years=range(REFERENCE_YEAR, 2051)):
    """GW of the region's 2024 fleet in operation per year: in 2024 every plant of the list, later a plant whose
    decommissioning year lies after the year (add_brownfield_elec retires an asset once build year + lifetime is
    reached). Two variants of filling a missing decommissioning year: `costs` = the cost table's lifetimes (the pathway
    stages, as PyPSA-Eur), `powerplantmatching` = its lifetimes per fuel type (the fork default). Both lists are scaled
    to the statistic like build_powerplants does; plants commissioned after 2024 are left out."""
    rows = []
    for r in REGIONS:
        raw, names = matched(REGIONS[r])
        for variant in ["costs", "powerplantmatching"]:
            ppl = plant_list(raw, names, True, REPORTED_FILTER, lifetimes=variant)
            ppl = ppl[~(pd.to_numeric(ppl.DateIn, errors="coerce") > REFERENCE_YEAR)]
            ppl = harmonise_to_statistics(ppl, CAPACITY, GROUPS, REFERENCE_YEAR)
            ppl["group"] = group_of(ppl)
            out = pd.to_numeric(ppl.DateOut, errors="coerce")
            for y in years:
                gw = ppl.Capacity[(out > y) | out.isna() | (y == REFERENCE_YEAR)].groupby(ppl.group).sum() / 1e3
                rows += [dict(region=r, variant=variant, group=g, year=y, gw=gw.get(g, 0.0)) for g in GROUPS if g != "hydro"]
    return pd.DataFrame(rows).pivot_table(index=["region", "group", "year"], columns="variant", values="gw").reset_index()


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    rows, gas = [], []
    for r in REGIONS:
        print(f"== {r}")
        a, b = region(r)
        rows += a
        gas += b
    world().to_csv(os.path.join(OUT, "world.csv"), index=False, float_format="%.6g")
    src, fields = sources()
    src.to_csv(os.path.join(OUT, "sources.csv"), index=False, float_format="%.6g")
    fields.to_csv(os.path.join(OUT, "fields.csv"), index=False, float_format="%.4g")
    retirements().to_csv(os.path.join(OUT, "retirements.csv"), index=False, float_format="%.6g")
    pd.DataFrame(gas).to_csv(os.path.join(OUT, "gas.csv"), index=False, float_format="%.4g")
    print(pd.DataFrame(gas).round(3).to_string(index=False))
    groups = pd.DataFrame(rows)
    groups.to_csv(os.path.join(OUT, "groups.csv"), index=False, float_format="%.4g")
    print(groups.round(2).to_string(index=False))

    t = ember_rows()
    t.reset_index().to_csv(os.path.join(OUT, "ember_rows.csv"), index=False, float_format="%.6g")
    bad = t[t.previous_cf > 1]
    print(f"\nprevious table, rows with capacity below generation: {len(bad)}, {bad.unreachable_twh.sum():.1f} TWh unreachable")
    print(bad.unreachable_twh.groupby(level=1).sum().round(1).to_string())
    print(f"table rows with capacity factor > 1: {(t.table_cf > 1).sum()}")

    if os.path.exists(NATIONAL):
        nat = pd.read_csv(NATIONAL, comment="#")
        table = pd.read_csv(CAPACITY).set_index(["country", "group"]).gw
        nat["table_gw"] = [table.get((c, g), 0.0) for c, g in zip(nat.country, nat.group)]
        nat["ratio"] = nat.table_gw / nat.national_gw
        nat.to_csv(os.path.join(OUT, "national.csv"), index=False, float_format="%.4g")
        print(nat[["country", "group", "national_gw", "table_gw", "ratio"]].round(2).to_string(index=False))

    if os.path.exists(NATIONAL_EFFICIENCY):
        e = pd.read_csv(NATIONAL_EFFICIENCY, comment="#")
        table = pd.read_csv(EFFICIENCY).set_index(["country", "carrier"]).efficiency
        e["model"] = [table.get((c, k), table.get(("*", k), np.nan)) for c, k in zip(e.country, e.carrier)]
        e.to_csv(os.path.join(OUT, "efficiency.csv"), index=False, float_format="%.4g")
        print(e[["country", "label", "kind", "efficiency", "model"]].to_string(index=False))
