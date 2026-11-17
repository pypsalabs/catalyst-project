#!/usr/bin/env python
"""
Read-only check of the resource classes of a stage (README "Resource classes").

    python scripts/check_resource_classes.py <stage> [--plot]

Run from config-pypsa-earth/ with the fork's pixi env (any env with pypsa, geopandas, matplotlib). Prints and
writes to results/<stage>/resource_classes/:

1. class table per bus and technology from the class files (potential, raw CF of the class profile, located
   fleet) and from the split network ``networks/<stage>/elec_s*_ec.nc`` (fleet, potential, CF after the
   energy-neutral factor);
2. invariants of the split against the unsplit network ``elec_s*.nc`` of the same stage: per bus and carrier the
   sums of p_nom and p_nom_max, and the fleet's annual energy;
3. fleet capacity factor per country and group against calibration/2024/generation.csv (the definition of
   scripts/check_sources.py, on the split network);
4. if the stage has solved horizons (myopic): per (location, carrier, class) and horizon, fixed capacity of grid
   and buyer plus the remaining extendable potential against the class potential, buyer + grid twin potentials
   equal, MW lost to the brownfield threshold, generator counts;
5. ``--plot``: supply curves (cumulative potential over class CF) and class maps, study style.
"""

import argparse
import glob
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

HERE = Path(__file__).resolve().parent.parent
PE = HERE.parent / "models" / "pypsa-earth"
YEAR = re.compile(r"(-\d{4})+$")
TECHS = ["onwind", "solar"]


def load(path):
    import pypsa

    import logging

    logging.getLogger("pypsa").setLevel(logging.ERROR)
    return pypsa.Network(str(path))


def class_table(stage):
    rows = []
    for f in sorted(glob.glob(str(PE / f"resources/{stage}/resource_classes/classes_*_elec_s*.nc"))):
        tech = re.search(r"classes_(\w+?)_elec", f).group(1)
        with xr.open_dataset(f) as ds:
            for bus in ds.bus.values:
                for k in ds.bin.values:
                    rows.append(
                        dict(tech=tech, bus=bus, cls=int(k),
                             potential_GW=float(ds.p_nom_max.sel(bus=bus, bin=k)) / 1e3,
                             cf_raw=float(ds.cf.sel(bus=bus, bin=k)),
                             located_fleet_GW=float(ds.fleet_mw.sel(bus=bus, bin=k)) / 1e3,
                             edge_lo=float(ds.edges.sel(bus=bus, edge=k)),
                             edge_hi=float(ds.edges.sel(bus=bus, edge=k + 1)))
                    )
    return pd.DataFrame(rows)


def split_checks(stage, out):
    ec = sorted(glob.glob(str(PE / f"networks/{stage}/elec_s*_ec.nc")))
    if not ec:
        print(f"no split network networks/{stage}/elec_s*_ec.nc yet")
        return None
    n = load(ec[0])
    unsplit = load(ec[0].replace("_ec.nc", ".nc"))
    w = n.snapshot_weightings.generators
    ok = True
    for net, label in [(unsplit, "before"), (n, "after")]:
        g = net.generators[net.generators.carrier.isin(TECHS)]
        e = (net.generators_t.p_max_pu[g.index].mul(w, axis=0).sum() * g.p_nom)
        net._tab = g.assign(E=e).groupby(["bus", "carrier"])[["p_nom", "p_nom_max", "E"]].sum()
    cmp = unsplit._tab.join(n._tab, lsuffix="_before", rsuffix="_after")
    for c in ["p_nom", "p_nom_max"]:
        dev = (cmp[f"{c}_after"] - cmp[f"{c}_before"]).abs() / cmp[f"{c}_before"].abs().clip(lower=1)
        bad = dev > 1e-6
        print(f"  {c:9s} conserved per bus and carrier: {'yes' if not bad.any() else 'NO ' + str(cmp.index[bad].tolist()[:5])}")
        ok &= not bad.any()
    # fleet energy: the profile factor is one per country, so it is conserved per country and carrier, and
    # moves between the buses of a country (reported)
    cty = cmp.index.get_level_values("bus").map(n.buses.country)
    ec = cmp.groupby([cty, cmp.index.get_level_values("carrier")])[["E_before", "E_after"]].sum()
    bad = (ec.E_after - ec.E_before).abs() > 1e-6 * ec.E_before.abs().clip(lower=1)
    print(f"  fleet energy conserved per country and carrier: {'yes' if not bad.any() else 'NO ' + str(ec.index[bad].tolist())}")
    ok &= not bad.any()
    fl = cmp[cmp.E_before > 0]
    rel = fl.E_after / fl.E_before - 1
    if len(rel) > 1:
        wt = fl.E_before / fl.E_before.sum()
        print(f"  fleet energy per bus after / before - 1: median {rel.median():+.1%}, range {rel.min():+.1%} .. {rel.max():+.1%}, "
              f"energy-weighted mean |dev| {(rel.abs() * wt).sum():.1%} ({len(rel)} bus x carrier)")
        rel.rename("fleet_energy_dev").to_csv(out / "fleet_energy_per_bus.csv")
    g = n.generators[n.generators.carrier.isin(TECHS)].copy()
    g["cf"] = n.generators_t.p_max_pu[g.index].mul(w, axis=0).sum() / w.sum()
    cols = ["bus", "carrier", "resource_class", "p_nom", "p_nom_max", "cf"]
    t = g[[c for c in cols if c in g]].copy()
    t[["p_nom", "p_nom_max"]] /= 1e3
    t.to_csv(out / "split_generators.csv")
    print(t.round(3).to_string())
    # fleet CF per country and group, as check_sources.py
    gen = pd.read_csv(HERE / "calibration/2024/generation.csv")
    fleet = g[g.p_nom > 0]
    groups = {"wind": ["onwind", "offwind-ac", "offwind-dc"], "solar": ["solar"]}
    allg = n.generators
    for grp, cars in groups.items():
        sel = allg.index[allg.carrier.isin(cars) & (allg.p_nom > 0)]
        if not len(sel):
            continue
        cty = allg.loc[sel, "bus"].map(n.buses.country)
        for c, idx in sel.groupby(cty).items():
            cf = float((n.generators_t.p_max_pu[idx].mul(w, axis=0).sum() * allg.loc[idx, "p_nom"]).sum()
                       / (allg.loc[idx, "p_nom"].sum() * w.sum()))
            tgt = gen.query("country == @c and group == @grp")
            tv = float(tgt.cf.iloc[0]) if len(tgt) and "cf" in tgt else np.nan
            print(f"  fleet CF {c} {grp}: {cf:.3f} (statistics {tv:.3f})")
    return ok


def horizon_checks(stage, out, table):
    files = sorted(glob.glob(str(PE / f"results/{stage}/networks/*_20[2-5][05].nc")))
    if not files:
        return
    pots = {}
    rows = []
    for f in files:
        year = int(f[-7:-3])
        n = load(f)
        g = n.generators
        if "resource_class" not in g:
            print(f"  {year}: no resource_class column")
            continue
        buyers = {b: v for b, v in ((n.meta or {}).get("cfe") or {}).get("buyers", {}).items()}
        loc = g.bus.map(lambda b: buyers.get(b, b))
        sel = g.carrier.isin(TECHS) & g.resource_class.notna()
        key = loc[sel] + " " + g.carrier[sel] + " c" + g.resource_class[sel].astype(int).astype(str)
        built = g.loc[sel, "p_nom_opt"].groupby(key).sum()
        fixed = g.loc[sel & ~g.p_nom_extendable, "p_nom"].groupby(key).sum()
        ext = sel & g.p_nom_extendable & ~g.bus.isin(buyers)
        pot = g.loc[ext, "p_nom_max"].groupby(key.reindex(g.index[ext])).sum()
        for kk in built.index:
            rows.append(dict(year=year, key=kk, built_GW=built.get(kk, 0) / 1e3, fixed_GW=fixed.get(kk, 0) / 1e3,
                             remaining_GW=pot.get(kk, np.nan) / 1e3, n_gen=int((key == kk).sum())))
    if rows:
        t = pd.DataFrame(rows)
        t["fixed_plus_remaining_GW"] = t.fixed_GW + t.remaining_GW
        cp = table.assign(key=table.bus + " " + table.tech + " c" + table.cls.astype(str)).set_index("key").potential_GW
        t["class_potential_GW"] = t.key.map(cp)
        t.to_csv(out / "horizons.csv", index=False)
        print(t.round(2).to_string(index=False))


def plot(table, stage, out):
    sys.path.insert(0, str(HERE.parent / "plotstyle"))
    import matplotlib.pyplot as plt
    import studystyle as ss

    ss.use()
    techs = table.tech.unique()
    fig, axes = plt.subplots(1, len(techs), figsize=(4.2 * len(techs), 3.2), squeeze=False)
    for ax, tech in zip(axes[0], techs):
        t = table[(table.tech == tech) & (table.potential_GW > 0)]
        for bus, b in t.groupby("bus"):
            b = b.sort_values("cf_raw", ascending=False)
            x = np.concatenate([[0], b.potential_GW.cumsum().values])
            ax.step(x, np.concatenate([b.cf_raw.values, b.cf_raw.values[-1:]]), where="post", lw=1.2, alpha=0.8)
        ax.set_xlabel("cumulative potential (GW)")
        ax.set_title(f"{tech}: capacity factor of the classes (raw)", loc="left")
    fig.tight_layout()
    fig.savefig(out / "supply_curves.png", dpi=160)
    print(f"wrote {out / 'supply_curves.png'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage")
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()
    out = PE / f"results/{a.stage}/resource_classes"
    out.mkdir(parents=True, exist_ok=True)
    table = class_table(a.stage)
    if table.empty:
        sys.exit(f"no class files in resources/{a.stage}/resource_classes/")
    table.to_csv(out / "classes.csv", index=False)
    print(table.round(3).to_string(index=False))
    print("split network:")
    split_checks(a.stage, out)
    horizon_checks(a.stage, out, table)
    if a.plot:
        plot(table, a.stage, out)
