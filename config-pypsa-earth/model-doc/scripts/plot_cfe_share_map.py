"""World map of the share of electricity demand that may procure 24/7 CFE in 2030, per modelled country (Demand for 24/7 CFE).

Colour: the share of the model's table (calibration/2030/cfe_share.csv = data centres + a part of the other electricity
use of RE100 members). Countries whose data-centre demand comes from a value of their own carry a dark outline; the
others take their IEA region's. Country shapes, clip boxes and the not-modelled countries as in the grid map.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_cfe_share_map.py
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.colors import BoundaryNorm

TOP = Path(__file__).resolve().parents[1]
STUDY = TOP.parent
sys.path.insert(0, str(TOP / "scripts"))
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402
from plot_grid_map import COUNTRIES, classify, world_by_class  # noqa: E402

BOUNDS = [0, 0.5, 1, 2, 3, 5, 7.5, 10, 15, 35]     # % of demand


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--share", default=STUDY / "calibration/2030/cfe_share.csv")
    p.add_argument("--row-countries", default=STUDY / "data/row_countries.csv")
    p.add_argument("--configs", default=STUDY)
    p.add_argument("--countries", default=COUNTRIES)
    p.add_argument("--out", default=TOP / "build/figures/cfe_share_map.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--share", snakemake.input.share, "--row-countries", snakemake.input.row_countries,
                          "--configs", str(Path(snakemake.input.configs[0]).parent), "--countries", snakemake.input.countries,
                          "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    t = pd.read_csv(a.share, keep_default_na=False).set_index("country")
    grid, boxes = classify(a.row_countries, Path(a.configs))
    world = world_by_class(a.countries, {c: "modelled" for c in grid}, boxes)
    modelled = world.grid == "modelled"
    world["share"] = (100 * pd.to_numeric(world.iso.map(t.share))).where(modelled)
    world["own"] = world.iso.isin(t.index[t.basis != "region"]) & modelled

    st.use()
    cmap = plt.get_cmap("YlGnBu", len(BOUNDS) - 1)
    norm = BoundaryNorm(BOUNDS, cmap.N)
    fig = plt.figure(figsize=(6.3, 3.35), layout="none")
    ax = fig.add_axes([0, 0.13, 1, 0.8])
    st.map_axes(ax)
    world[world.share.isna()].plot(ax=ax, color=st.LAND, edgecolor="white", linewidth=0.3)
    data = world[world.share.notna()]
    data.plot(ax=ax, column="share", cmap=cmap, norm=norm, edgecolor="white", linewidth=0.3)
    data[data.own].plot(ax=ax, facecolor="none", edgecolor=st.TEXT, linewidth=0.5)
    ax.set_aspect("equal")
    x0, y0, x1, y1 = world.total_bounds
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_title("Demand that may procure 24/7 CFE in 2030", loc="left", fontsize=8.5, x=0.02)
    cax = fig.add_axes([0.3, 0.075, 0.4, 0.022])
    st.colorbar(fig, plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax, "share of the country's electricity demand, %",
                ticks=BOUNDS[:-1], fmt="%g")
    lax = fig.add_axes([0.72, 0.03, 0.27, 0.1])
    lax.set_axis_off()
    lax.plot([0.05, 0.13, 0.13, 0.05, 0.05], [0.42, 0.42, 0.72, 0.72, 0.42], color=st.TEXT, linewidth=0.6)
    lax.text(0.17, 0.57, "data centres from a country value", fontsize=6.5, va="center", color=st.LABEL)
    lax.set_xlim(0, 1)
    lax.set_ylim(0, 1)

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(f"{int(data.own.sum())} shapes with a country value, share {data.share.min():.2f} to {data.share.max():.1f} % -> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
