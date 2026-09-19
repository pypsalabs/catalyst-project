# SPDX-License-Identifier: CC0-1.0
"""
Sanity check + map for a Catalyst pypsa-earth prenetwork.

    cd models/pypsa-earth && pixi run python ../../config-pypsa-earth/check_network.py <run>

<run> is a stage name (US, US-smoke, BR, ...); the clip box and renewable carriers are read from
config-pypsa-earth/config.<run>.yaml. Prints one line per check and writes
models/pypsa-earth/results/catalyst/<run>_map.png (line width ~ s_nom, red dots ~ annual load).
Must run inside the pixi env (`pixi run`) so PROJ/cartopy find their data.
"""
import os
import sys

import matplotlib
import numpy as np
import pandas as pd
import pypsa
import yaml

matplotlib.use("Agg")
import cartopy.crs as ccrs  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
run = sys.argv[1]
cfg = yaml.safe_load(open(os.path.join(HERE, f"config.{run}.yaml")))
clusters = cfg["scenario"]["clusters"][0]
bbox = cfg.get("build_shape_options", {}).get("clip_bbox")
vre = [c for c in cfg["electricity"]["renewable_carriers"] if c != "hydro"]

pe = HERE
while not os.path.isdir(os.path.join(pe, "models", "pypsa-earth")):
    pe = os.path.dirname(pe)
pe = os.path.join(pe, "models", "pypsa-earth")
n = pypsa.Network(os.path.join(pe, f"networks/{run}/elec_s_{clusters}_ec_lcopt_Co2L.nc"))

ac = n.buses[n.buses.carrier == "AC"]
print("snapshots", len(n.snapshots), n.snapshots[0], "->", n.snapshots[-1])
print("buses total", len(n.buses), "AC", len(ac),
      "x", round(ac.x.min(), 2), round(ac.x.max(), 2), "y", round(ac.y.min(), 2), round(ac.y.max(), 2))
if bbox:
    inside = ac.x.between(bbox[0], bbox[2]) & ac.y.between(bbox[1], bbox[3])
    print("AC buses inside clip_bbox", int(inside.sum()), "of", len(ac))
if "country" in ac and ac.country.nunique() > 1:
    print("AC buses per country", ac.country.value_counts().to_dict())
print("lines", len(n.lines), "s_nom GW", round(n.lines.s_nom.sum() / 1e3), "links", len(n.links),
      "link carriers", n.links.carrier.value_counts().to_dict(),
      "DC link p_nom GW", round(n.links.loc[n.links.carrier == "DC", "p_nom"].sum() / 1e3, 1))
print("global constraints", n.global_constraints.index.tolist())
pmp = n.generators_t.p_max_pu
for c in vre:
    g = n.generators.index[n.generators.carrier == c].intersection(pmp.columns)
    if len(g) == 0:
        print(f"{c}: NO profiles")
        continue
    print(f"{c}: {len(g)} profiles, mean CF {pmp[g].mean().mean():.3f}, "
          f"max bus CF {pmp[g].mean().max():.3f}, p_nom_max GW {n.generators.loc[g, 'p_nom_max'].sum() / 1e3:.0f}")
su = n.storage_units
inflow = n.storage_units_t.inflow
hours = len(n.snapshots)
print("storage units", su.carrier.value_counts().to_dict(), "with inflow", len(inflow.columns),
      f"inflow TWh over {hours} h", round(inflow.sum().sum() / 1e6, 1),
      "hydro p_nom GW", round(su.loc[su.carrier == "hydro", "p_nom"].sum() / 1e3, 1),
      "max_hours", su.loc[su.carrier == "hydro", "max_hours"].describe()[["min", "50%", "max"]].round(1).to_dict())
conv = n.generators[~n.generators.p_nom_extendable].groupby("carrier").p_nom.sum().div(1e3).round(1)
print("existing capacity GW", conv.to_dict())
load = n.loads_t.p_set
tot = load.sum(axis=1)
print("load: mean GW", round(tot.mean() / 1e3), "peak GW", round(tot.max() / 1e3),
      f"TWh over {hours} h", round(load.sum().sum() / 1e6, 1))
print("nan check: p_max_pu", int(pmp.isna().sum().sum()), "load", int(load.isna().sum().sum()),
      "inflow", int(inflow.isna().sum().sum()))
print("sub-networks", n.buses.sub_network.nunique() if "sub_network" in n.buses else "n/a")

fig, ax = plt.subplots(figsize=(11, 9), subplot_kw={"projection": ccrs.PlateCarree()})
pad = 1.0
bnd = ([bbox[0] - pad, bbox[2] + pad, bbox[1] - pad, bbox[3] + pad] if bbox else
       [ac.x.min() - 2, ac.x.max() + 2, ac.y.min() - 2, ac.y.max() + 2])
n.plot(ax=ax, bus_sizes=0.0, line_widths=n.lines.s_nom / 4e3, link_widths=0.4, line_colors="0.4",
       link_colors="tab:purple", geomap=True, boundaries=bnd)
ls = load.sum().groupby(n.loads.bus).sum().reindex(n.buses.index).fillna(0)
ax.scatter(n.buses.x, n.buses.y, s=ls / ls.max() * 600, c="tab:red", alpha=0.6, zorder=5,
           transform=ccrs.PlateCarree())
ax.set_title(f"{run}: {len(ac)} AC buses, {len(n.lines)} lines ({n.lines.s_nom.sum() / 1e3:.0f} GW), "
             f"{hours} snapshots; red = load")
out = os.path.join(pe, f"results/catalyst/{run}_map.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
fig.savefig(out, dpi=120, bbox_inches="tight")
print("map written", out)
