"""Retirement of the incumbent fleet in the five spatially resolved regions, 2024-2050.

Stacked: GW of each region's 2024 fleet still in operation per year as the pathway runs retire it: a reported
retirement year, else commissioning year + the cost table's lifetime of the carrier (electricity: powerplants_lifetimes:
costs). Line: the same with powerplantmatching's lifetimes, PyPSA-Earth's default. Both scaled to the 2024 statistic; no
new builds. Reads build/fleet_check/retirements.csv, written by ../scripts/check_fleet.py (read-only, no model rerun).

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_fleet_retirements.py
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

TOP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

REGIONS = {"US": "US", "CN": "China", "IN": "India", "NWE": "NW Europe", "BR": "Brazil"}
GROUPS = ["coal", "gas", "oil", "nuclear", "biomass", "geothermal"]


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--retirements", default=TOP / "build/fleet_check/retirements.csv")
    p.add_argument("--out", default=TOP / "build/figures/fleet_retirements.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--retirements", snakemake.input[0], "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    r = pd.read_csv(a.retirements)
    st.use()
    fig, axes = plt.subplots(1, len(REGIONS), figsize=(6.3, 2.5), sharex=True)
    for ax, (reg, name) in zip(axes, REGIONS.items()):
        d = r[r.region == reg]
        rep = d.pivot(index="year", columns="group", values="costs").reindex(columns=GROUPS).fillna(0)
        fil = d.groupby("year").powerplantmatching.sum()
        ax.stackplot(rep.index, rep.T.values, colors=[st.FUEL[g] for g in GROUPS], linewidth=0)
        ax.plot(fil.index, fil.values, color=st.VERMILLION, lw=1.2, ls=(0, (3, 1.5)))
        last = rep.sum(axis=1)
        ax.annotate(f"{last.iloc[-1] / last.iloc[0]:.0%}", (2050, last.iloc[-1]), xytext=(0, 3), textcoords="offset points",
                    ha="right", va="bottom", fontsize=6.5, color=st.TEXT, zorder=5,
                    bbox=dict(facecolor="white", edgecolor="none", pad=0.6, alpha=0.9))   # readable on the dark fill
        ax.annotate(f"{fil.iloc[-1] / fil.iloc[0]:.0%}", (2050, fil.iloc[-1]), xytext=(0, 3), textcoords="offset points",
                    ha="right", va="bottom", fontsize=6.5, color=st.VERMILLION)
        ax.set_ylim(0, last.iloc[0] * 1.08)
        ax.set_xlim(2024, 2050)
        ax.set_xticks([2025, 2050])
        ax.set_title(name, loc="left")
        ax.tick_params(axis="y", labelsize=6.5)
    axes[0].annotate("Capacity still in operation, GW", (0, 1.13), xycoords="axes fraction", fontsize=6.5, color=st.TICK).set_in_layout(False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=st.FUEL[g], linewidth=0) for g in GROUPS]
    handles.append(plt.Line2D([], [], color=st.VERMILLION, lw=1.2, ls=(0, (3, 1.5))))
    fig.legend(handles=handles, labels=[*GROUPS, "all fuels, with PyPSA-Earth's default lifetimes"], loc="lower center", ncol=len(handles),
               fontsize=6.5, handlelength=1.2, handleheight=0.9, handletextpad=0.4, columnspacing=1.0, bbox_to_anchor=(0.5, -0.02))
    fig.get_layout_engine().set(rect=(0, 0.07, 1, 0.86))   # (left, bottom, width, height): legend below, axis label above
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
