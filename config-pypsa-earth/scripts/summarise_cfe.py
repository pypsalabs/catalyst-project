# SPDX-License-Identifier: CC0-1.0
"""
Per planning horizon of a myopic stage (branches: the parent's networks in the shared horizons): advanced
capacities, the 24/7 CFE buyer's cost against the grid price, and the learning factors of the stage's market.

    cd models/pypsa-earth
    pixi run python ../../config-pypsa-earth/scripts/summarise_cfe.py <stage> [<stage> ...]

Writes results/learning/<scen>/summary.csv per stage <R>-<scen> (one row per horizon x technology, long format):
    year, stage, scen, technology, gw, gw_buyer, gwh, gwh_buyer          (advanced rows of technology_assumptions.csv;
                                                                         all vintages in the solved network)
and results/learning/<scen>/cfe.csv (one row per horizon x buyer: fork scripts/cfe.py summary(): cfe_score,
cost_per_mwh, grid_price_per_mwh, premium_per_mwh, ... in USD2024/MWh; plus the newly acquired part of the
horizon: demand_new_twh = the buyer's load growth since the horizon before, cost_new_per_mwh = annual cost of the
buyer assets built in this horizon / that growth, minus the buyer's export revenue per MWh of its whole load
(ASSUMPTION: every MWh of buyer load sells the same excess), premium_new_per_mwh = that minus the grid price) and results/learning/<scen>/factors.csv
(year, pool, component, factor, cumulative_capacity, unit) from the market files of the stage's horizons
(the parent market's for the shared ones), and results/learning/<scen>/mix.csv (year, carrier, kind, twh, twh_buyer:
kind "generation" = annual generation incl. hydro reservoir dispatch, kind "storage" = annual discharge of PHS,
batteries, iron-air, ... into the AC bus, energy that was generated before and so is counted twice in a sum over
both kinds; twh_buyer = the 24/7 CFE buyers' own plants).
"""
import os
import re
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "technology-assumptions", "scripts"))
import merge_config  # noqa: E402
import palette  # noqa: E402

BUYER = " CFE"   # fork scripts/cfe.py SUFFIX


def advanced_rows():
    return [r for r in palette.read() if r.get("group") == "advanced"]


def capacities(n, rows):
    out = []
    for r in rows:
        car = palette.carriers(r)
        gw = gwb = gwh = gwhb = 0.0
        for comp in ("Generator", "StorageUnit"):
            df = n.df(comp)
            d = df[df.carrier.isin(car)]
            buyer = d.bus.str.endswith(BUYER)
            gw += d.p_nom_opt.sum() / 1e3
            gwb += d.p_nom_opt[buyer].sum() / 1e3
            if comp == "StorageUnit":
                gwh += (d.p_nom_opt * d.max_hours).sum() / 1e3
                gwhb += (d.p_nom_opt * d.max_hours)[buyer].sum() / 1e3
        out.append(dict(technology=r["technology"], gw=gw, gw_buyer=gwb, gwh=gwh, gwh_buyer=gwhb))
    return out


def generation(n):
    """Annual supply per carrier (TWh), split into the 24/7 CFE buyers' own plants and the rest of the system.
    kind "generation": generators plus the dispatch of hydro reservoirs. kind "storage": what pure storage feeds
    back into an AC bus (storage units other than hydro; links from a store's bus to an AC bus, named after the
    store's bus carrier, e.g. battery)."""
    w = n.snapshot_weightings.generators
    g = n.generators
    e = n.generators_t.p.reindex(columns=g.index, fill_value=0.0).mul(w, axis=0).sum() / 1e6
    d = [pd.DataFrame(dict(carrier=g.carrier, kind="generation", buyer=g.bus.str.endswith(BUYER), twh=e))]
    su = n.storage_units
    if len(su):
        es = n.storage_units_t.p.reindex(columns=su.index, fill_value=0.0).clip(lower=0).mul(w, axis=0).sum() / 1e6
        kind = su.carrier.eq("hydro").map({True: "generation", False: "storage"})
        d.append(pd.DataFrame(dict(carrier=su.carrier, kind=kind, buyer=su.bus.str.endswith(BUYER), twh=es)))
    ln = n.links[(n.links.bus0.map(n.buses.carrier) != "AC") & (n.links.bus1.map(n.buses.carrier) == "AC")]
    if len(ln):
        el = -n.links_t.p1.reindex(columns=ln.index, fill_value=0.0).clip(upper=0).mul(w, axis=0).sum() / 1e6
        d.append(pd.DataFrame(dict(carrier=ln.bus0.map(n.buses.carrier), kind="storage",
                                   buyer=ln.bus1.str.endswith(BUYER), twh=el)))
    t = (pd.concat(d).groupby(["carrier", "kind", "buyer"]).twh.sum().unstack(fill_value=0.0)
         .reindex(columns=[False, True], fill_value=0.0))
    return [dict(carrier=c, kind=k, twh=float(r[False] + r[True]), twh_buyer=float(r[True]))
            for (c, k), r in t.iterrows()]


def cfe_module():
    """The fork's scripts/cfe.py (recomputes a buyer summary missing from n.meta, solves before 2026-11-08 20:00)."""
    sys.path.insert(0, os.path.join(os.getcwd(), "scripts"))
    import cfe
    return cfe


def market_of(stage, year):
    """Market name whose market_<year>.csv priced this stage's horizon (the parent's in shared horizons)."""
    cat = merge_config.stage_config("overlay", stage)["catalyst"]
    br = cat.get("branch")
    if br and int(year) <= br["year"]:
        return market_of(br["parent_stage"], year)
    return cat["scenario"]


def summarise(stage):
    import pypsa

    cfg = merge_config.stage_config("overlay", stage)
    scen = cfg["catalyst"]["scenario"]
    rows = advanced_rows()
    caps, cfe, fac, mix = [], [], [], []
    for y in cfg["scenario"]["planning_horizons"]:
        f = merge_config.solved_horizon(stage, y)
        if os.path.exists(f):
            n = pypsa.Network(f)
            caps += [dict(year=y, stage=stage, scen=scen, **c) for c in capacities(n, rows)]
            mix += [dict(year=y, stage=stage, scen=scen, **m) for m in generation(n)]
            meta = (n.meta or {}).get("cfe") or {}
            summ = meta.get("summary") or (cfe_module().summary(n) if meta.get("buyers") else {})
            for buyer, v in summ.items():
                v = {k: x for k, x in v.items() if not isinstance(x, dict)}
                cfe.append(dict(year=y, stage=stage, scen=scen, buyer=buyer, **v))
        m = os.path.join("results", "learning", market_of(stage, y), f"market_{y}.csv")
        if os.path.exists(m):
            d = pd.read_csv(m, comment="#")[["pool", "component", "unit", "factor", "cumulative_capacity"]]
            fac.append(d.assign(year=y, stage=stage, scen=scen))
    # the newly acquired part of each horizon (a buyer share that grows over the horizons, catalyst.cfe.share)
    prev = {}
    for r in sorted(cfe, key=lambda r: r["year"]):
        if r.get("cost_own_new") is None:
            continue   # solved before the fork recorded it
        grown = r["demand_twh"] - prev.get(r["buyer"], 0.0)
        prev[r["buyer"]] = r["demand_twh"]
        r["demand_new_twh"] = grown
        if grown > 1e-6:
            r["cost_new_per_mwh"] = r["cost_own_new"] / (grown * 1e6) - r["revenue_per_mwh"]
            r["premium_new_per_mwh"] = r["cost_new_per_mwh"] - r["grid_price_per_mwh"]
    out = os.path.join("results", "learning", scen)
    os.makedirs(out, exist_ok=True)
    tables = dict(summary=pd.DataFrame(caps), cfe=pd.DataFrame(cfe), mix=pd.DataFrame(mix),
                  factors=pd.concat(fac, ignore_index=True) if fac else pd.DataFrame())
    for name, df in tables.items():
        df.to_csv(os.path.join(out, f"{name}.csv"), index=False, float_format="%.6g")
    print(f"summarise_cfe: {stage} -> {out}/{{summary,cfe,factors,mix}}.csv "
          f"({len(set(c['year'] for c in caps))} horizons solved)")
    return tables


if __name__ == "__main__":
    for s in sys.argv[1:]:
        summarise(s)
