"""World map of how far the plant list stood from the capacity statistic it is scaled to (first figure of Existing Fleet).

Per modelled country: the thermal, nuclear, biomass and geothermal capacity of the statistic (calibration/2024/capacity.csv)
over that of powerplantmatching's plant list as the `now` stages filter it, both without hydropower. Right: the same two
totals over all modelled countries, per fuel group. Reads build/fleet_check/world.csv, written by ../scripts/check_fleet.py
(read-only, no model rerun); country shapes, clip boxes and the not-modelled countries as in the grid map (plot_grid_map.py).

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_fleet_map.py
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

TOP = Path(__file__).resolve().parents[1]
STUDY = TOP.parent
sys.path.insert(0, str(TOP / "scripts"))
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402
from plot_grid_map import COUNTRIES, classify, world_by_class  # noqa: E402

CLASSES = [  # key, upper bound of statistic / plant list, colour, legend label
    ("down2", 0.67, "#2166ac", "database ≥ 1.5 × statistic"),
    ("down", 0.9, "#92c5de", "database 10–50 % above statistic"),
    ("ok", 1.1, "#bdbdbd", "database within ±10 % of statistic"),
    ("up", 1.5, "#f4a582", "database 10–33 % below statistic"),
    ("up2", np.inf, "#b2182b", "database ≥ 33 % below, or no plants"),
]
GROUPS = {"coal": "Coal", "gas": "Gas", "oil": "Oil", "nuclear": "Nuclear", "biomass": "Biomass", "geothermal": "Geothermal"}


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--world", default=TOP / "build/fleet_check/world.csv")
    p.add_argument("--row-countries", default=STUDY / "data/row_countries.csv")
    p.add_argument("--configs", default=STUDY)
    p.add_argument("--countries", default=COUNTRIES)
    p.add_argument("--out", default=TOP / "build/figures/fleet_map.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--world", snakemake.input.world, "--row-countries", snakemake.input.row_countries,
                          "--configs", str(Path(snakemake.input.configs[0]).parent), "--countries", snakemake.input.countries,
                          "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    w = pd.read_csv(a.world)
    t = w.groupby("country")[["plant_list_gw", "statistic_gw"]].sum()
    ratio = (t.statistic_gw / t.plant_list_gw).replace(np.inf, 1e9).fillna(1.0)
    bins = [0] + [c[1] for c in CLASSES]
    cls = pd.cut(ratio, bins, labels=[c[0] for c in CLASSES], right=False).astype(str)
    grid, boxes = classify(a.row_countries, Path(a.configs))
    world = world_by_class(a.countries, {c: cls.get(c, "ok") for c in grid}, boxes)

    st.use()
    fig = plt.figure(figsize=(6.3, 3.0), layout="none")
    ax = fig.add_axes([0, 0.16, 0.7, 0.8])
    st.map_axes(ax)
    world[world.grid == "none"].plot(ax=ax, color=st.LAND, edgecolor="white", linewidth=0.3)
    for key, _, colour, _ in CLASSES:
        part = world[world.grid == key]
        if len(part):
            part.plot(ax=ax, color=colour, edgecolor="white", linewidth=0.3)
    ax.set_aspect("equal")
    x0, y0, x1, y1 = world.total_bounds
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_title("Capacity in the plant database relative to national statistics", loc="left", fontsize=8.5)
    counts = cls.reindex(list(grid)).fillna("ok").value_counts()
    lax = fig.add_axes([0.0, 0.0, 0.7, 0.14])
    lax.set_axis_off()
    st.legend_squares(lax, [(c, f"{label} ({counts.get(k, 0)})") for k, _, c, label in CLASSES] + [(st.LAND, "not modelled")],
                      loc="center", ncol=2, fontsize=6.5, columnspacing=1.2)

    # totals over the modelled countries per fuel group
    bx = fig.add_axes([0.8, 0.2, 0.18, 0.66])
    tot = w.groupby("group")[["plant_list_gw", "statistic_gw"]].sum().reindex(list(GROUPS))
    y = np.arange(len(GROUPS))[::-1]
    h = 0.36
    bx.barh(y + h / 2, tot.plant_list_gw, height=h, color=st.NEUTRAL, linewidth=0)
    bx.barh(y - h / 2, tot.statistic_gw, height=h, color=[st.FUEL[g] for g in GROUPS], linewidth=0)
    for yi, v in zip(y, tot.statistic_gw):
        bx.annotate(f"{v:,.0f}", (v, yi - h / 2), xytext=(3, 0), textcoords="offset points", va="center", fontsize=6.5, color=st.TEXT)
    bx.set_yticks(y, list(GROUPS.values()))
    bx.grid(axis="y", visible=False)
    bx.grid(axis="x", visible=True)
    bx.set_xlim(0, tot.max().max() * 1.3)
    bx.tick_params(axis="x", labelsize=6.5)
    bx.set_title("Total, GW", loc="left", fontsize=8.5)
    st.legend_squares(bx, [(st.NEUTRAL, "plant database"), ("#555555", "national statistics")], loc="upper left",
                      bbox_to_anchor=(0, -0.08), ncol=1, fontsize=6.5)

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(counts.to_dict(), f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
