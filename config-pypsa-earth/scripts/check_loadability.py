# SPDX-License-Identifier: CC0-1.0
"""
Length of the AC circuits of the spatially resolved regions, what the loadability limit of long circuits does to them
and how the capacity across borders compares with published transfer capacities, without rerunning anything.

PyPSA-Earth gives every AC line the thermal rating of its conductors times `lines: s_max_pu`, whatever its length.
The fork option `lines: loadability` limits every circuit of the base network by the St. Clair curve at its own
length instead (scripts/prepare_network.py, set_line_loadability). This script calls that function of the fork (one
implementation) in memory on the clustered network of every region, with the base network and the two bus maps the
rule reads and the region's `lines: s_max_pu`, and writes what the figures of the model doc's grid section draw.
Existing networks, resources and results are not touched. Writes to model-doc/build/loadability/:

    lines_<R>.csv       one row per clustered AC line: ends, length, thermal rating, sum over its circuits of thermal
                        rating, SIL and loadability, usable share before / after
    circuits_<R>.csv    one row per AC circuit of the base network: length, thermal rating, SIL, loadability, voltage,
                        between two clusters or not
    summary.csv         one row per region: circuit and line lengths (capacity-weighted), share of capacity the
                        loadability limits, security margin, sum of line limits before / after, per GW of peak load
    curve.csv           the curve: length, multiples of SIL, usable share of the thermal rating per line type
    transfer.csv        one row per border with a published transfer capacity (data/validation/transfer_capacities/):
                        the base network's AC circuits and HVDC links across it (by the state or country of each bus,
                        so independent of the clustering) at their thermal rating, at the default margin, with the
                        loadability, with the region's margin; the same as the clustered model sees it; the published
                        figure (Europe: also that of the reference grid of 2030)

Networks read (a base run where it holds the clustered network, else its `now` stage, which shares the base network):
USW, USE, BR, CN, IN-now, NWE-now.

Usage (from config-pypsa-earth): ../models/pypsa-earth/.pixi/envs/default/bin/python scripts/check_loadability.py [REGION ...]
"""
import argparse
import glob
import logging
import os
import re
import sys
import warnings

import numpy as np
import pandas as pd
import yaml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORK = os.path.join(HERE, "..", "models", "pypsa-earth")
OUT = os.path.join(HERE, "model-doc", "build", "loadability")
REGIONS = {  # region: (name, run that holds networks/<run>/elec_s_<N>.nc)
    "USW": ("US West", "USW"),
    "USE": ("US East", "USE"),
    "BR": ("Brazil", "BR"),
    "IN": ("India", "IN-now"),
    "CN": ("China", "CN"),
    "NWE": ("North-West Europe", "NWE-now"),
}
TRANSFER = os.path.join(HERE, "data", "validation", "transfer_capacities")
INDIA_GRIDS = os.path.join(HERE, "data", "validation", "india_regional_grids.csv")
DEFAULT_MARGIN = yaml.safe_load(open(os.path.join(FORK, "config.default.yaml")))["lines"]["s_max_pu"]


def weighted_quantile(values, weights, q=0.5):
    v, w = np.asarray(values, float), np.asarray(weights, float)
    keep = np.isfinite(v) & (w > 0)
    v, w = v[keep], w[keep]
    if not len(v):
        return np.nan
    order = np.argsort(v)
    c = np.cumsum(w[order])
    return float(v[order][np.searchsorted(c, q * c[-1])])


def margin_of(key):
    """`lines: s_max_pu` of the region: its config, else statistics.yaml, else the fork's default."""
    margin = DEFAULT_MARGIN
    for fn in ["statistics.yaml", f"config.{key}.yaml"]:
        cfg = yaml.safe_load(open(os.path.join(HERE, fn)))
        margin = (cfg.get("lines") or {}).get("s_max_pu", margin)
    return float(margin)


def read(run):
    """Clustered network, base network, the bus maps from base bus to cluster and the number of clusters of a run."""
    import pypsa

    nets = [f for f in glob.glob(os.path.join(FORK, "networks", run, "elec_s_*.nc")) if re.search(r"elec_s_\d+\.nc$", f)]
    assert len(nets) == 1, (run, nets)
    clusters = re.search(r"elec_s_(\d+)\.nc$", nets[0]).group(1)
    reg = os.path.join(FORK, "resources", run, "bus_regions")
    busmaps = [pd.read_csv(os.path.join(reg, f), index_col=0, dtype=str).squeeze("columns")
               for f in ["busmap_elec_s.csv", f"busmap_elec_s_{clusters}.csv"]]
    return pypsa.Network(nets[0]), pypsa.Network(os.path.join(FORK, "networks", run, "base.nc")), busmaps, clusters


def pair_of(bus0, bus1):
    return pd.Series(np.where(bus0 < bus1, bus0 + " " + bus1, bus1 + " " + bus0), bus0.index)


def region(key, pn):
    name, run = REGIONS[key]
    n, base, busmaps, clusters = read(run)
    margin = margin_of(key)
    n.lines["s_max_pu"] = margin   # as prepare_network does (set_line_s_max_pu) before the loadability
    df = pn.set_line_loadability(n, base, busmaps)
    for end in ["0", "1"]:
        bus = n.lines["bus" + end].reindex(df.index)
        df["bus" + end] = bus
        df["x" + end], df["y" + end] = bus.map(n.buses.x), bus.map(n.buses.y)
    df["margin"] = margin
    df["limit_default"] = DEFAULT_MARGIN * df.s_nom   # PyPSA-Earth as it comes
    df["limit_after"] = df.s_max_pu * df.s_nom
    df.index.name = "line"
    df.round(4).to_csv(os.path.join(OUT, f"lines_{key}.csv"))

    cluster = pd.Series(base.buses.index, base.buses.index)
    for m in busmaps:
        cluster = cluster.map(m.rename(index=str))
    c = base.lines[(base.lines.carrier != "DC") & (base.lines.s_nom > 0)]
    c0, c1 = c.bus0.map(cluster), c.bus1.map(cluster)
    between = c0.notna() & c1.notna() & (c0 != c1)
    types = base.line_types
    zc = np.sqrt(types.x_per_length / (2 * np.pi * types.f_nom * types.c_per_length * 1e-9))
    sil = c.v_nom**2 / c["type"].map(zc) * c.num_parallel
    circuits = pd.DataFrame({"bus0": c.bus0, "bus1": c.bus1, "length": c.length, "s_nom": c.s_nom, "v_nom": c.v_nom,
                             "type": c["type"], "num_parallel": c.num_parallel, "between_clusters": between, "sil": sil,
                             "loadable": np.minimum(c.s_nom, pn.st_clair(c.length) * sil),
                             "pair": pair_of(c0, c1).where(between)})
    circuits.index.name = "circuit"
    circuits.drop(columns=["bus0", "bus1", "pair"]).round(3).to_csv(os.path.join(OUT, f"circuits_{key}.csv"))

    peak = float(n.loads_t.p_set.sum(axis=1).max())
    b = circuits[circuits.between_clusters]
    row = {
        "region": key, "name": name, "run": run, "clusters": len(n.buses[n.buses.carrier == "AC"]), "lines": len(df),
        "circuits": len(circuits), "circuits_between_clusters": len(b),
        "circuit_km_median": weighted_quantile(circuits.length, circuits.s_nom),
        "circuit_between_km_median": weighted_quantile(b.length, b.s_nom),
        "circuit_between_km_p90": weighted_quantile(b.length, b.s_nom, 0.9),
        "line_km_median": weighted_quantile(df.length, df.s_nom),
        "capacity_limited_share": float(b.s_nom[b.loadable < b.s_nom].sum() / b.s_nom.sum()),
        "loadable_share": float(b.loadable.sum() / b.s_nom.sum()),
        "margin": margin,
        "s_max_pu_after": float(np.average(df.s_max_pu, weights=df.s_nom)),
        "thermal_gw": df.s_nom.sum() / 1e3, "limit_default_gw": df.limit_default.sum() / 1e3, "limit_after_gw": df.limit_after.sum() / 1e3,
        "peak_load_gw": peak / 1e3,
        "limit_per_peak_default": df.limit_default.sum() / peak, "limit_per_peak_after": df.limit_after.sum() / peak,
    }
    print(f"{key}: circuits between clusters {row['circuit_between_km_median']:.0f} km (median by capacity; 90 % below "
          f"{row['circuit_between_km_p90']:.0f} km; clustered lines {row['line_km_median']:.0f} km), "
          f"{row['capacity_limited_share']:.0%} of their capacity limited by loadability, loadable share "
          f"{row['loadable_share']:.2f}, margin {margin}: usable share {DEFAULT_MARGIN} -> {row['s_max_pu_after']:.2f}, "
          f"limits per GW of peak load {row['limit_per_peak_default']:.2f} -> {row['limit_per_peak_after']:.2f}")
    return row, transfer(key, run, base, circuits, df, cluster, margin)


def zones_of(key, run, base):
    """Zone of every bus of the base network (a state, a market zone, a regional grid, a country) for the borders."""
    import build_market_zones as bmz

    b = base.buses[["x", "y", "country"]].copy()
    if key == "NWE":
        return b.country.replace({"GB": "UK"})   # the NTC table's code for Great Britain and Northern Ireland
    unit = bmz.unit_of_buses(b, os.path.join(FORK, "resources", run, "shapes", "gadm_shapes.geojson"))
    if key == "IN":
        return unit.map(bmz.read_definitions(INDIA_GRIDS))
    if key == "BR":
        return unit.map(bmz.read_definitions())
    names = pd.read_csv(bmz.TABLE, comment="#", dtype=str).set_index("key").name   # US: the state
    return unit.map(names)


def transfer(key, run, base, circuits, df, cluster, margin):
    """Capacity across the borders that have a published transfer capacity; rows of transfer.csv."""
    faces = pd.read_csv(os.path.join(TRANSFER, "interfaces.csv"), comment="#", dtype=str).fillna("")
    faces = faces[faces.region == key]
    ntc = pd.read_csv(os.path.join(TRANSFER, "ember_ntc_2024.csv"), comment="#")
    plan = pd.read_csv(os.path.join(TRANSFER, "ember_ntc_2030.csv"), comment="#").set_index("Border")
    plan = np.maximum(plan.NTC_F, plan.NTC_B)   # Europe's reference grid of 2030, the larger direction
    if faces.empty and key != "NWE":
        return []
    itcs = pd.read_csv(os.path.join(TRANSFER, "nerc_itcs_part1.csv"), comment="#")
    single = pd.read_csv(os.path.join(TRANSFER, "published.csv"), comment="#")
    single = single[single.region == key].set_index("interface").mw

    zone = zones_of(key, run, base)
    c = circuits.assign(z0=circuits.bus0.map(zone), z1=circuits.bus1.map(zone))
    dc = base.links[base.links.carrier == "DC"]
    dc = dc.assign(z0=dc.bus0.map(zone), z1=dc.bus1.map(zone))
    # as the clustered model sees it: a cluster belongs to the zone holding most of its base buses
    zcl = pd.DataFrame({"cluster": cluster, "zone": zone}).dropna().groupby("cluster").zone.agg(lambda v: v.value_counts().idxmax())
    m = pd.DataFrame({"z0": df.bus0.map(zcl), "z1": df.bus1.map(zcl), "default": df.limit_default, "after": df.limit_after})

    def across(d, a, b):
        if a == b == ["regional grids"]:
            return d[d.z0.notna() & d.z1.notna() & (d.z0 != d.z1)]
        return d[(d.z0.isin(a) & d.z1.isin(b)) | (d.z0.isin(b) & d.z1.isin(a))]

    def nerc(ids):
        hi = lo = 0.0
        for i in filter(None, ids.split("+")):
            v = itcs.loc[itcs.interface == i, ["summer_2024_mw", "winter_2024_25_mw"]].values.ravel()
            assert len(v), i
            hi, lo = hi + v.max(), lo + (v[v > 0].min() if (v > 0).any() else 0.0)
        return hi, lo

    todo = []
    for f in faces.itertuples():
        if f.published in single.index:
            hi = lo = float(single[f.published])
        else:
            hi, lo = nerc(f.published)
        todo.append((f.interface, f.side_a.split(";"), f.side_b.split(";"), hi + nerc(f.published_dc)[0], lo + nerc(f.published_dc)[0], f.hvdc == "add", np.nan))
    if key == "NWE":
        here = set(zone.dropna())
        for r in ntc.itertuples():
            if r.From in here and r.To in here and max(r.NTC_F, r.NTC_B) > 0:
                todo.append((r.Border, [r.From], [r.To], max(r.NTC_F, r.NTC_B), min(r.NTC_F, r.NTC_B), True, plan.get(r.Border, np.nan)))

    rows = []
    for label, a, b, hi, lo, add, later in todo:
        x, w = across(c, a, b), across(m, a, b)
        hvdc = across(dc, a, b).p_nom.sum() if add else 0.0
        rows.append({
            "region": key, "interface": label, "ac_circuits": int(x.num_parallel.sum()),
            "ac_km_median": weighted_quantile(x.length, x.s_nom), "ac_thermal_gw": x.s_nom.sum() / 1e3,
            "ac_sil_gw": x.sil.sum() / 1e3, "ac_inside_a_cluster_gw": x.s_nom[~x.between_clusters].sum() / 1e3,
            "ac_default_gw": DEFAULT_MARGIN * x.s_nom.sum() / 1e3, "ac_loadable_default_gw": DEFAULT_MARGIN * x.loadable.sum() / 1e3,
            "ac_after_gw": margin * x.loadable.sum() / 1e3, "hvdc_gw": hvdc / 1e3, "margin": margin,
            "published_gw": hi / 1e3, "published_low_gw": lo / 1e3, "published_2030_gw": later / 1e3,
            "clustered_lines": len(w), "clustered_default_gw": w.default.sum() / 1e3, "clustered_after_gw": w.after.sum() / 1e3,
        })
    t = pd.DataFrame(rows)
    k = t[t.ac_circuits > 0]
    if len(k):
        pub = k.published_gw.sum()
        print(f"   {len(k)} borders with AC circuits and a published capacity ({pub:.1f} GW with HVDC {k.hvdc_gw.sum():.1f} GW): "
              f"model / published at the default margin {(k.ac_default_gw.sum() + k.hvdc_gw.sum()) / pub:.2f}, with loadability "
              f"{(k.ac_loadable_default_gw.sum() + k.hvdc_gw.sum()) / pub:.2f}, with the region's margin {margin}: "
              f"{(k.ac_after_gw.sum() + k.hvdc_gw.sum()) / pub:.2f}; margin that matches "
              f"{DEFAULT_MARGIN * (pub - k.hvdc_gw.sum()) / k.ac_loadable_default_gw.sum():.2f}")
    return rows


def curve(pn):
    """The curve and the usable share of the thermal rating it leaves, per line type of the config's voltage levels."""
    import pypsa
    import yaml

    types = pypsa.Network().line_types
    ac_types = yaml.safe_load(open(os.path.join(FORK, "config.default.yaml")))["lines"]["ac_types"]
    km = np.unique(np.concatenate([np.geomspace(20, 2000, 400), [m * 1.609344 for m, _ in pn.ST_CLAIR]]))
    out = pd.DataFrame({"length_km": km, "sil_multiples": pn.st_clair(km)})
    for v in [220.0, 380.0, 750.0]:
        t = types.loc[ac_types[v]]
        sil = v**2 / np.sqrt(t.x_per_length / (2 * np.pi * t.f_nom * t.c_per_length * 1e-9))
        thermal = np.sqrt(3) * t.i_nom * v
        out[f"share_{int(v)}"] = np.minimum(1.0, out.sil_multiples * sil / thermal)
        print(f"   {ac_types[v]}: SIL {sil:.0f} MW, thermal {thermal:.0f} MVA per circuit, SIL / thermal {sil / thermal:.3f}")
    out["point"] = out.length_km.round(3).isin([round(m * 1.609344, 3) for m, _ in pn.ST_CLAIR])
    out.round(4).to_csv(os.path.join(OUT, "curve.csv"), index=False)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("regions", nargs="*", default=list(REGIONS))
    p.add_argument("--fork-scripts", default=os.path.join(FORK, "scripts"),
                   help="directory of the prepare_network.py to import (default: the fork's scripts)")
    a = p.parse_args()
    warnings.filterwarnings("ignore")
    logging.getLogger("pypsa").setLevel(logging.ERROR)
    sys.path[:0] = [a.fork_scripts, os.path.join(FORK, "scripts"), os.path.dirname(os.path.abspath(__file__))]
    import prepare_network as pn

    os.makedirs(OUT, exist_ok=True)
    done = [region(k, pn) for k in a.regions]
    for fn, rows in [("summary.csv", [r for r, _ in done]), ("transfer.csv", [r for _, t in done for r in t])]:
        fn = os.path.join(OUT, fn)
        if set(a.regions) != set(REGIONS) and os.path.exists(fn):   # a partial run keeps the other regions' rows
            old = pd.read_csv(fn)
            rows = old[~old.region.isin(a.regions)].to_dict("records") + rows
        s = pd.DataFrame(rows)
        s["order"] = s.region.map({k: i for i, k in enumerate(REGIONS)})
        s.sort_values("order", kind="stable").drop(columns="order").round(3).to_csv(fn, index=False)
    curve(pn)
    print(f"-> {OUT}")
