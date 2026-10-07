"""Rank the buses of each stage network by mean 2013 onwind / solar capacity factor, with the admin-1 region of the
bus (Natural Earth) and, for the US, the interconnection (ERCOT = Texas, Western = states west of the Rockies, Eastern =
the rest), as the basis for choosing each site's "procurable" wind and solar resource locations in config.yaml
(misc-quarter1/weather-years). Output build/resource_ranking.csv; the choice itself is recorded by hand in config.yaml.

Standalone: python rank_resource_buses.py
"""

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

logging.disable(logging.WARNING)
HERE = Path(__file__).resolve().parent
CFG = yaml.safe_load((HERE / "config.yaml").read_text())
import pypsa  # noqa: E402

WESTERN = {"Washington", "Oregon", "California", "Nevada", "Idaho", "Montana", "Wyoming", "Utah", "Colorado", "Arizona", "New Mexico"}
adm1 = gpd.read_file((HERE / CFG["admin1_shapes"]).resolve())[["name", "geometry"]].rename(columns={"name": "adm1_name"})
rows = []
for run, f in CFG["runs"].items():
    n = pypsa.Network(str((HERE / CFG["networks_dir"] / f).resolve()))
    g = n.generators[n.generators.carrier.isin(["onwind", "solar"])]
    cf = n.generators_t.p_max_pu[g.index].mean()
    b = n.buses.loc[sorted(set(g.bus))].copy()
    pts = gpd.GeoDataFrame(b[[]], geometry=gpd.points_from_xy(b.x, b.y), crs="EPSG:4326")
    j = gpd.sjoin(pts, adm1, how="left", predicate="within")
    b["admin1"] = j[~j.index.duplicated()]["adm1_name"].reindex(b.index)
    load = n.loads_t.p_set.sum().groupby(n.loads.bus).sum() / 1e6
    for bus, r in b.iterrows():
        rec = {"run": run, "bus": bus, "country": r["country"], "admin1": r["admin1"], "x": r["x"], "y": r["y"], "load_twh": load.get(bus, 0.0)}
        for carrier, name in (("onwind", "wind"), ("solar", "solar")):
            gg = g[(g.bus == bus) & (g.carrier == carrier)]
            rec[f"cf_{name}"] = float(cf[gg.index].mean()) if len(gg) else np.nan
            rec[f"pot_{name}_gw"] = float(gg["p_nom_max"].sum() / 1e3) if len(gg) else 0.0
        if run == "US":
            rec["grid"] = "ERCOT" if r["admin1"] == "Texas" else ("Western" if r["admin1"] in WESTERN else "Eastern")
        else:
            rec["grid"] = r["country"]
        rows.append(rec)
df = pd.DataFrame(rows)
df.to_csv(HERE / "build" / "resource_ranking.csv", index=False, float_format="%.4f")
pd.set_option("display.width", 250)
for grid, sub in df.groupby("grid"):
    if grid not in ("ERCOT", "Western", "Eastern", "FR", "BR", "IN", "CN"):
        continue
    print(f"=== {grid}: best wind buses")
    print(sub.sort_values("cf_wind", ascending=False).head(4)[["bus", "admin1", "x", "y", "cf_wind", "pot_wind_gw", "cf_solar", "load_twh"]].round(3).to_string(index=False))
    print(f"--- {grid}: best solar buses")
    print(sub.sort_values("cf_solar", ascending=False).head(3)[["bus", "admin1", "x", "y", "cf_solar", "pot_solar_gw", "cf_wind", "load_twh"]].round(3).to_string(index=False))
