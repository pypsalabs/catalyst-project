"""The existing fleet against national statistics (Existing Fleet, check).

Left: capacity of the statistic the plant list is scaled to, relative to the national statistic, per country and fuel group.
Right: fleet efficiency of the model against national heat rates (EIA, CEC).
Reads build/fleet_check/{national,efficiency}.csv, written by ../scripts/check_fleet.py (read-only, no model rerun).

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_fleet_check.py
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

HERE = Path(snakemake.scriptdir) if "snakemake" in globals() else Path(__file__).resolve().parent
TOP = HERE.parent
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import iconstyle as ic  # noqa: E402

COUNTRIES = {"US": "US", "CN": "China", "IN": "India", "BR": "Brazil", "DE": "Germany", "GB": "UK", "FR": "France"}
GROUPS = {"coal": "coal", "gas": "gas", "oil": "oil", "nuclear": "nuclear", "biomass": "biomass", "geothermal": "geothermal"}
MARKERS = {"coal": "o", "gas": "s", "oil": "D", "nuclear": "^", "biomass": "v", "geothermal": "P"}
XMAX = 1.6


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--national", default=TOP / "build/fleet_check/national.csv")
    p.add_argument("--efficiency", default=TOP / "build/fleet_check/efficiency.csv")
    p.add_argument("--out", default=TOP / "build/figures/fleet_check.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--national", str(snakemake.input.national), "--efficiency", str(snakemake.input.efficiency),
                          "--out", str(snakemake.output[0])])
    else:
        a = p.parse_args()

    nat = pd.read_csv(a.national)
    eff = pd.read_csv(a.efficiency).dropna(subset=["model"])

    ic.use()
    fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(6.3, 2.9), gridspec_kw=dict(width_ratios=[1.15, 1]))
    plt.subplots_adjust(left=0.1, right=0.98, top=0.86, bottom=0.24, wspace=0.55)

    # (a) one row per country, one marker per fuel group; ratios beyond the axis sit at its edge with their value
    y = {c: i for i, c in enumerate(list(COUNTRIES)[::-1])}
    ax0.axvspan(0.9, 1.1, color=ic.PALE, zorder=0, lw=0)
    ax0.axvline(1, color=ic.INK, lw=ic.MARK, zorder=1)
    for k, (group, colour) in enumerate(zip(GROUPS, ic.CATEGORICAL)):
        d = nat[nat.group == group]
        off = (k - 2.5) * 0.09
        for r in d.itertuples():
            x = min(r.ratio, XMAX)
            ax0.plot(x, y[r.country] + off, marker=MARKERS[group], ms=4.2, color=colour, mec=ic.INK, mew=0.5, ls="none", zorder=3)
            if r.ratio > XMAX:
                ax0.annotate(f"{r.ratio:.0f}$\\times$", (XMAX, y[r.country] + off), xytext=(-4, 0), textcoords="offset points",
                             ha="right", va="center", fontsize=6)
    ax0.set_yticks(list(y.values()), [COUNTRIES[c] for c in y], fontsize=7)
    ax0.set_xlim(0.5, XMAX + 0.02)
    ax0.set_ylim(-0.6, len(y) - 0.4)
    ax0.grid(axis="y", visible=False)
    ax0.set_title("(a) model capacity / national statistic", loc="left", fontsize=7.5)
    ax0.legend(handles=[Line2D([], [], marker=MARKERS[g], color=c, mec=ic.INK, mew=0.5, ls="none", ms=4.2, label=GROUPS[g])
                        for g, c in zip(GROUPS, ic.CATEGORICAL)],
               loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=6, fontsize=6, handletextpad=0.2, columnspacing=0.7, frameon=False)

    # (b) national fleet efficiency against the model's
    labels = [f"{COUNTRIES[r.country]} {r.label}" for r in eff.itertuples()]
    yy = np.arange(len(eff))[::-1]
    h = 0.36
    ax1.barh(yy + h / 2, eff.efficiency, height=h, color=ic.AMBER, edgecolor=ic.INK, linewidth=ic.MARK * 0.6, zorder=2)
    ax1.barh(yy - h / 2, eff.model, height=h, color=ic.BLUE, edgecolor=ic.INK, linewidth=ic.MARK * 0.6, zorder=2)
    ax1.set_yticks(yy, labels, fontsize=7)
    ax1.set_xlim(0, 0.6)
    ax1.set_ylim(-0.6, len(eff) - 0.4)
    ax1.grid(axis="x", color=ic.PALE)
    ax1.grid(axis="y", visible=False)
    ax1.spines["bottom"].set_visible(False)
    ax1.set_title("(b) fleet efficiency, net, LHV", loc="left", fontsize=7.5)
    ax1.legend(handles=[Patch(facecolor=c, edgecolor=ic.INK, linewidth=ic.MARK, label=l) for c, l in [(ic.AMBER, "national"), (ic.BLUE, "model")]],
               loc="upper center", bbox_to_anchor=(0.4, -0.15), ncol=2, fontsize=6, frameon=False)
    ic.ground(ax1, axis="y")

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=300)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
