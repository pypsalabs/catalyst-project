#!/usr/bin/env python
# SPDX-License-Identifier: MIT
"""
Market zone of every clustered bus of a run: the table statistics/market_zones.csv (columns bus, zone) that the
fork's 24/7 CFE buyers are matched by (fork option catalyst: cfe: zones: statistics; tables.smk rule
catalyst_market_zones).

    cd models/pypsa-earth && pixi run python ../../config-pypsa-earth/scripts/build_market_zones.py --run BR [--out f.csv]
    ... --simplified networks/BR/elec_s.nc --busmap resources/BR/bus_regions/busmap_elec_s_50.csv \
        --gadm resources/BR/shapes/gadm_shapes.geojson --out resources/BR/statistics/market_zones.csv

The zones are defined in data/market_zones/market_zones.csv by GADM level-1 unit or by country (README "Market
zones"). A clustered bus is not inside one unit: its zone is the zone that holds most of the cluster's load, i.e.
  1. every bus of the simplified network (elec_s.nc) gets the GADM unit that contains it (the nearest one for a bus
     off the shapes) and through it a zone; a country without rows in the table is one zone, its country code;
  2. the mean load of the simplified buses is summed per cluster (busmap) and zone;
  3. the cluster takes the zone with the largest sum (the most buses where a cluster has no load).
Rows of the table whose key is the name of a clustered bus pin that bus (tests only).

The report says how good this is: the share of load in clusters assigned to a zone other than its own, the zones
of a single cluster (matching there is node matching) and the zones of the table that no cluster got.
"""
import argparse
import glob
import os
import re
import sys

import pandas as pd
import xarray as xr

HERE = os.path.dirname(os.path.abspath(__file__))
TABLE = os.path.join(os.path.dirname(HERE), "data", "market_zones", "market_zones.csv")
ZONE_ID = re.compile(r"^[A-Za-z0-9_]+$")


def read_definitions(path=TABLE):
    """{key: zone} of the curated table; zone identifiers are checked."""
    d = pd.read_csv(path, comment="#", dtype=str)
    bad = d.loc[~d.zone.str.match(ZONE_ID), "zone"].unique()
    if len(bad):
        raise ValueError(f"{path}: zone identifiers take letters, digits and underscore only: {list(bad)}")
    if d.key.duplicated().any():
        raise ValueError(f"{path}: duplicate keys {list(d.key[d.key.duplicated()])}")
    return d.set_index("key").zone


def simplified_buses(path):
    """x, y, country and mean load (MW) of the AC buses of the simplified network."""
    with xr.open_dataset(path) as ds:
        b = pd.DataFrame({c: ds[f"buses_{c}"].values for c in ["x", "y", "country"]},
                         index=ds["buses_i"].values.astype(str))
        load = pd.Series(ds["loads_t_p_set"].mean("snapshots").values, ds["loads_t_p_set_i"].values.astype(str))
        load_bus = pd.Series(ds["loads_bus"].values.astype(str), ds["loads_i"].values.astype(str))
    b["country"] = b.country.astype(str)
    b["load"] = load.groupby(load_bus.reindex(load.index)).sum().reindex(b.index).fillna(0.0)
    return b


def unit_of_buses(b, gadm_path):
    """GADM level-1 id of every bus: the unit that contains it, else the nearest one of its country."""
    import geopandas as gpd

    g = gpd.read_file(gadm_path)[["GADM_ID", "country", "geometry"]].to_crs(3857)
    pts = gpd.GeoDataFrame(b[["country"]], geometry=gpd.points_from_xy(b.x, b.y), crs=4326).to_crs(3857)
    out = pd.Series(index=b.index, dtype=object)
    for c, p in pts.groupby("country"):
        gc = g[g.country == c]
        if gc.empty:
            continue
        j = gpd.sjoin_nearest(p[["geometry"]], gc[["GADM_ID", "geometry"]], how="left")
        out[p.index] = j[~j.index.duplicated()].GADM_ID.reindex(p.index)
    return out


def build(simplified, busmap, gadm, table=TABLE):
    zones = read_definitions(table)
    b = simplified_buses(simplified)
    clusters = pd.read_csv(busmap, index_col=0, dtype=str).squeeze("columns")
    clusters.index = clusters.index.astype(str)
    b["cluster"] = clusters.reindex(b.index)
    b = b[b.cluster.notna()]
    b["unit"] = unit_of_buses(b, gadm)

    gadm_countries = {k.split(".")[0] for k in zones.index if "." in k}
    by_unit = b.unit.map(zones)
    missing = sorted(set(b.unit[b.country.isin(gadm_countries) & by_unit.isna()].dropna()))
    if missing:
        raise ValueError(f"{table}: a country with GADM rows must be covered completely; no row for {missing}")
    by_country = b.country.map(zones)
    b["zone"] = by_unit.where(b.country.isin(gadm_countries), by_country).fillna(b.country)

    load = b.groupby(["cluster", "zone"]).load.sum().unstack(fill_value=0.0)
    count = b.groupby(["cluster", "zone"]).size().unstack(fill_value=0)
    weight = load.where(load.sum(axis=1) > 0, count, axis=0)
    out = pd.DataFrame({"zone": weight.idxmax(axis=1)})
    out["load_mw"] = load.sum(axis=1)
    out["own_zone_load_share"] = (weight.max(axis=1) / weight.sum(axis=1)).round(3)
    out.index.name = "bus"

    pins = zones[[k for k in zones.index if "." not in k and not re.fullmatch(r"[A-Z]{2}", k)]]   # bus names
    matched = pins.index.intersection(out.index)
    if len(matched) and len(matched) < len(pins):   # a table with pins is a test table of one run
        raise ValueError(f"{table}: bus keys that are not clustered buses of this run: {list(pins.index.difference(out.index))}")
    for k in matched:
        out.loc[k, ["zone", "own_zone_load_share"]] = [pins[k], 1.0]

    import geopandas as gpd

    here = set(gpd.read_file(gadm, ignore_geometry=True).GADM_ID) | set(b.country)   # units and countries of this run
    return out, sorted(set(zones[zones.index.intersection(list(here))]) - set(out.zone))


def report(run, out, unused):
    total = out.load_mw.sum()
    misplaced = float((out.load_mw * (1 - out.own_zone_load_share)).sum() / total) if total else 0.0
    z = out.groupby("zone").agg(buses=("zone", "size"), load_gw=("load_mw", lambda s: s.sum() / 1e3))
    single = list(z.index[z.buses == 1])
    print(f"{run}: {len(out)} clustered buses in {len(z)} zones; {misplaced:.1%} of load lies in a cluster assigned to "
          f"another zone; {len(single)} zones with one bus (node matching there)")
    print("   " + ", ".join(f"{k} {int(r.buses)} ({r.load_gw:.0f} GW)" for k, r in z.sort_values("load_gw", ascending=False).iterrows()))
    worst = out[out.own_zone_load_share < 0.75].sort_values("own_zone_load_share")
    if len(worst):
        print("   clusters with less than 75 % of their load in their zone: "
              + ", ".join(f"{k} -> {r.zone} ({r.own_zone_load_share:.0%})" for k, r in worst.iterrows()))
    if unused:
        print(f"   zones of the table without a clustered bus: {', '.join(unused)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--run", help="run name: the standard paths of networks/<run>/ and resources/<run>/ (cwd = fork root)")
    p.add_argument("--simplified"); p.add_argument("--busmap"); p.add_argument("--gadm")
    p.add_argument("--table", default=TABLE); p.add_argument("--out")
    a = p.parse_args()
    if a.run:
        a.simplified = a.simplified or f"networks/{a.run}/elec_s.nc"
        a.gadm = a.gadm or f"resources/{a.run}/shapes/gadm_shapes.geojson"
        if not a.busmap:
            found = sorted(glob.glob(f"resources/{a.run}/bus_regions/busmap_elec_s_[0-9]*.csv"))
            if len(found) != 1:
                sys.exit(f"--busmap needed: {len(found)} clustered busmaps in resources/{a.run}/bus_regions/")
            a.busmap = found[0]
    if not (a.simplified and a.busmap and a.gadm):
        p.error("--run, or --simplified, --busmap and --gadm")
    out, unused = build(a.simplified, a.busmap, a.gadm, a.table)
    report(a.run or os.path.basename(os.path.dirname(a.simplified)), out, unused)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        out.to_csv(a.out)
