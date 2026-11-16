# SPDX-License-Identifier: CC0-1.0
"""
Check that the 2024 statistics arrived where each data vector enters the workflow (calibration at the source,
statistics.yaml): per stage and country the built resources and the network after add_electricity are compared with
the tables of calibration/<year>/.

    cd models/pypsa-earth
    pixi run python ../../config-pypsa-earth/scripts/check_sources.py <stage> [<stage> ...]

Checks (relative tolerance 1 %, absolute 0.01 TWh / 0.01 GW):
- demand        resources/<stage>/demand_profiles.csv per country = load_options.annual_totals
- plants        resources/<stage>/powerplants.csv per country and fuel group (plants after the reference year left
                out) = electricity.powerplants_statistics
- hydro         renewable_profiles/profile_hydro.nc (turbines) per country, reservoirs x dispatch_efficiency
                (generation equivalent) = renewable.hydro.normalization file
- elec.nc       wind / solar capacity factor of the existing fleet against capacity_factor_targets (information:
                the factor is clipped); every existing conventional generator has an efficiency and a marginal cost
Prints one table per stage and exits non-zero when a check fails.
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd
import pypsa
import xarray as xr
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import merge_config  # noqa: E402

warnings.filterwarnings("ignore")
REL, ABS = 0.01, 0.01
with open("config.default.yaml") as f:  # the fork's defaults (run from models/pypsa-earth)
    DEFAULTS = yaml.safe_load(f)


def kind_of(stage):
    return "overlay" if "-" in stage else "prenetwork"


def close(a, b, abs_tol=ABS):
    return abs(a - b) <= max(REL * abs(b), abs_tol)


def check(stage):
    cfg = merge_config.stage_config(kind_of(stage), stage)
    res = f"resources/{stage}"
    rows = []
    n = pypsa.Network(f"networks/{stage}/base.nc")
    bus_country = n.buses.country

    # the tables the rules read (written per run by tables.smk)
    table_of = lambda name: f"{res}/statistics/{name}.csv"  # noqa: E731

    # demand
    if cfg["load_options"].get("annual_totals") and os.path.exists(f"{res}/demand_profiles.csv"):
        totals = pd.read_csv(table_of("demand"), comment="#").set_index("country").demand_twh
        d = pd.read_csv(f"{res}/demand_profiles.csv", index_col=0)
        twh = d.sum().groupby(d.columns.map(lambda b: bus_country.get(b, b))).sum() / 1e6
        for c, v in twh.items():
            if c in totals:
                rows.append(("demand", c, "TWh", v, totals[c], close(v, totals[c])))

    # plant list
    stats = cfg["electricity"].get("powerplants_statistics") or {}
    if stats.get("enable") and os.path.exists(f"{res}/powerplants.csv"):
        table = pd.read_csv(table_of("capacity"), comment="#").set_index(["country", "group"]).gw
        ppl = pd.read_csv(f"{res}/powerplants.csv", index_col=0)
        ref = stats.get("reference_year")
        if ref:
            ppl = ppl[~(pd.to_numeric(ppl.DateIn, errors="coerce") > ref)]
        groups = stats.get("groups") or DEFAULTS["electricity"]["powerplants_statistics"]["groups"]
        for group, spec in groups.items():
            spec = spec if isinstance(spec, dict) else {"fueltypes": spec}
            sel = ppl.Fueltype.isin(spec["fueltypes"])
            if spec.get("exclude_technologies"):
                sel &= ~ppl.Technology.isin(spec["exclude_technologies"])
            gw = ppl[sel].groupby("Country").Capacity.sum() / 1e3
            for c in set(ppl.Country):
                if (c, group) in table.index:
                    target, v = table[(c, group)], gw.get(c, 0.0)
                    ok = close(v, target) or (v == 0 and spec.get("add") is False)
                    rows.append((f"plants {group}", c, "GW", v, target, ok))

    # hydro energy
    norm = (cfg["renewable"].get("hydro") or {}).get("normalization") or {}
    fn = f"{res}/renewable_profiles/profile_hydro.nc"
    if norm.get("method") == "custom" and os.path.exists(fn):
        target = pd.read_csv(table_of("hydro_generation"), comment="#").set_index("country").twh
        with xr.open_dataarray(fn) as inflow:
            if inflow.sizes.get("plant", 0):
                ppl = pd.read_csv(f"{res}/powerplants.csv", index_col=0)
                annual = (inflow.mean("time") * 8760 / 1e6).to_pandas()
                annual.index = annual.index.astype(int)
                # the statistic is generation: reservoir inflow is generation / dispatch_efficiency
                eff = norm.get("dispatch_efficiency", 1.0) if norm.get("distribute") == "capacity" else 1.0
                reservoir = ppl.Technology.reindex(annual.index).eq("Reservoir")
                annual = annual.where(~reservoir, annual * eff)
                country = ppl.Country.reindex(annual.index)
                for c, v in annual.groupby(country.values).sum().items():
                    if c in target:
                        rows.append(("hydro", c, "TWh", v, target[c], close(v, target[c])))

    # network after add_electricity
    fn = f"networks/{stage}/elec.nc"
    if os.path.exists(fn):
        e = pypsa.Network(fn)
        g = e.generators
        country = g.bus.map(e.buses.country)
        cft = dict(DEFAULTS["electricity"]["capacity_factor_targets"],
                   **(cfg["electricity"].get("capacity_factor_targets") or {}))
        if cft.get("enable"):
            t = pd.read_csv(table_of("generation"), comment="#").set_index(["country", "group"]).cf
            w = e.snapshot_weightings.generators
            for group, carriers in cft["groups"].items():
                sel = g.index[g.carrier.isin(carriers) & (g.p_nom > 0)]
                for c, idx in sel.groupby(country[sel]).items():
                    if (c, group) not in t.index or not t[(c, group)] > 0:
                        continue
                    p = g.loc[idx, "p_nom"]
                    cf = e.generators_t.p_max_pu[idx].mul(p, axis=1).mul(w, axis=0).sum().sum() / (p.sum() * w.sum())
                    # information only: the factor is limited to the clip and profiles to 1
                    rows.append((f"cf {group} (info)", c, "-", cf, t[(c, group)], True))
        conv = g[~g.p_nom_extendable & g.carrier.isin(["coal", "lignite", "CCGT", "OCGT", "oil", "nuclear", "biomass"])]
        rows.append(("efficiency set", "all", "n", conv.efficiency.notna().sum(), len(conv),
                     conv.efficiency.notna().all() and (conv.efficiency > 0).all()))
        rows.append(("marginal cost set", "all", "n", conv.marginal_cost.notna().sum(), len(conv),
                     conv.marginal_cost.notna().all()))
    df = pd.DataFrame(rows, columns=["check", "country", "unit", "model", "target", "ok"])
    return df


if __name__ == "__main__":
    failed = False
    for stage in sys.argv[1:]:
        df = check(stage)
        bad = df[~df.ok]
        print(f"== {stage}: {len(df)} checks, {len(bad)} failed")
        summary = df.groupby("check").agg(n=("ok", "size"), failed=("ok", lambda x: (~x).sum()),
                                          model=("model", "sum"), target=("target", "sum"))
        print(summary.round(2).to_string())
        if len(bad):
            print(bad.round(3).to_string(index=False))
            failed = True
    sys.exit(1 if failed else 0)
