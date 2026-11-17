"""Installed wind and solar capacity per country: plant list, statistics and the network (Renewables & Weather).

Per group (wind = onshore and offshore, solar) the largest fleets: the plant list as attach_wind_and_solar places it,
v0.9.0 (list, gap to IRENA of its default year spread over the buses), the network of the project, and IRENA of the
year the project reads as a marker. Reads build/renewables_check/capacity.csv, written by ../scripts/check_renewables.py
(read-only, no model rerun).

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_renew_capacity.py
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
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

GROUPS = {"wind": ("Wind", ["onwind", "offwind"]), "solar": ("Solar", ["solar"])}
NAMES = {"CN": "China", "US": "US", "IN": "India", "DE": "Germany", "JP": "Japan", "BR": "Brazil", "ES": "Spain", "GB": "UK",
         "FR": "France", "IT": "Italy", "AU": "Australia", "KR": "South Korea", "CA": "Canada", "SE": "Sweden", "NL": "Netherlands"}
TOP_N = 8
BARS = [("list_gw", "plant list", st.NEUTRAL), ("v090_gw", "v0.9.0", st.SKY), ("model_gw", "this project", st.BLUE)]


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--capacity", default=TOP / "build/renewables_check/capacity.csv")
    p.add_argument("--out", default=TOP / "build/figures/renew_capacity.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--capacity", snakemake.input.capacity, "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    d = pd.read_csv(a.capacity)
    year = next(int(c.split("_")[1]) for c in d.columns if c.startswith("irena_") and not c.startswith("irena_2023"))
    stat = f"irena_{year}_gw"
    st.use()
    fig, axes = plt.subplots(1, 2, figsize=(6.3, 3.4))
    for ax, (group, (label, carriers)) in zip(axes, GROUPS.items()):
        g = d[d.carrier.isin(carriers)].groupby("country")[[b[0] for b in BARS] + [stat]].sum()
        g = g.sort_values("model_gw", ascending=False).head(TOP_N)
        y = np.arange(len(g))[::-1]
        h = 0.26
        for i, (col, _, colour) in enumerate(BARS):
            ax.barh(y + h * (1 - i), g[col], height=h, color=colour, linewidth=0)
        ax.scatter(g[stat], y, marker="|", s=260, color=st.TEXT, linewidths=1.0, zorder=5)
        for yi, (c, r) in zip(y, g.iterrows()):
            ax.annotate(f"{r.model_gw:,.0f}", (max(r.model_gw, r[stat], r.list_gw, r.v090_gw), yi - h), xytext=(4, 0),
                        textcoords="offset points", va="center", fontsize=6.5, color=st.TEXT)
        ax.set_yticks(y, [NAMES.get(c, c) for c in g.index])
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", visible=True)
        ax.set_xlim(0, g.max().max() * 1.15)
        ax.set_title(f"{label}, GW", loc="left", fontsize=8.5)
        print(group, g.round(1).to_string())
    handles = [plt.Rectangle((0, 0), 1, 1, color=c, linewidth=0) for _, _, c in BARS]
    handles.append(plt.Line2D([], [], marker="|", color=st.TEXT, linestyle="none", markersize=9, markeredgewidth=1.0))
    fig.legend(handles, [b[1] for b in BARS] + [f"IRENA, end of {year}"], loc="lower center", ncol=4, fontsize=7,
               handlelength=1.0, handleheight=0.9, columnspacing=1.6)
    fig.get_layout_engine().set(rect=(0, 0.07, 1, 0.93))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
