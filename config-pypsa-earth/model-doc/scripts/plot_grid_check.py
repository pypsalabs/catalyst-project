"""Grid against real project and network metrics, uncorrected vs corrected grid (Grid Data, adjustments).

Left: HVDC capacity x length relative to the listed projects in service. Right: AC circuit km against published totals.
Reads build/grid_check/{summary,ac_summary}.csv, written by ../scripts/check_grid.py (read-only, no model rerun).

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_grid_check.py
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

HERE = Path(snakemake.scriptdir) if "snakemake" in globals() else Path(__file__).resolve().parent
TOP = HERE.parent
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import iconstyle as ic  # noqa: E402

REGIONS = {"US": "US", "BR": "Brazil", "IN": "India", "CN": "China", "NWE": "NW Europe"}
AREAS = {"IN": "India", "DE": "Germany", "BR": "Brazil"}


def bars(ax, labels, series, h):
    y = np.arange(len(labels))[::-1]
    n = len(series)
    for k, (values, colour) in enumerate(series):
        ax.barh(y + (n - 1 - 2 * k) * h / 2, values, height=h, color=colour, edgecolor=ic.INK, linewidth=ic.MARK * 0.6, zorder=2)
    ax.set_yticks(y, labels, fontsize=7)
    ax.set_ylim(-0.6, len(labels) - 0.4)
    ax.grid(axis="x", color=ic.PALE)
    ax.grid(axis="y", visible=False)
    ax.spines["bottom"].set_visible(False)
    return y


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--summary", default=TOP / "build/grid_check/summary.csv")
    p.add_argument("--ac", default=TOP / "build/grid_check/ac_summary.csv")
    p.add_argument("--out", default=TOP / "build/figures/grid_check.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--summary", str(snakemake.input.summary), "--ac", str(snakemake.input.ac), "--out", str(snakemake.output[0])])
    else:
        a = p.parse_args()

    s = pd.read_csv(a.summary).set_index("region").loc[list(REGIONS)]
    ac = pd.read_csv(a.ac).set_index("area").loc[list(AREAS)]

    ic.use()
    fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(6.3, 2.5))
    plt.subplots_adjust(left=0.1, right=0.97, top=0.82, bottom=0.11, wspace=0.32)

    bars(ax0, list(REGIONS.values()), [(s.gwkm_current_mercator / s.gwkm_listed, ic.STEEL_L), (s.gwkm_corrected / s.gwkm_listed, ic.BLUE)], 0.36)
    ax0.axvline(1, color=ic.INK, lw=ic.MARK, zorder=3)
    ax0.set_xlim(0, 4)
    ax0.set_title("(a) HVDC GW km, relative to the list", loc="left", fontsize=7.5)
    ic.legend_squares(ax0, [(ic.STEEL_L, "uncorrected"), (ic.BLUE, "corrected")], on_title_line=False, loc="lower right", anchor=(1.0, 0.0))
    ic.ground(ax0, axis="y")

    y = bars(ax1, list(AREAS.values()), [(ac.network / 1e3, ic.STEEL_L), (ac.corrected / 1e3, ic.BLUE), (ac.published / 1e3, ic.AMBER)], 0.26)
    # Brazil's published value is of 2020; the marker is the +28 % that the same source projects for 2024
    ax1.plot([ac.published["BR"] * 1.28 / 1e3], [y[list(AREAS).index("BR")] - 0.26], marker="D", ms=3.5, color=ic.AMBER, mec=ic.INK, mew=0.6, zorder=4, ls="none")
    ax1.set_title("(b) AC lines, thousand circuit km", loc="left", fontsize=7.5)
    ax1.legend(handles=[Patch(facecolor=c, edgecolor=ic.INK, linewidth=ic.MARK, label=l) for c, l in [(ic.STEEL_L, "uncorrected"), (ic.BLUE, "corrected"), (ic.AMBER, "published")]],
               loc="center right", bbox_to_anchor=(1.0, 0.5))
    ic.ground(ax1, axis="y")

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=300)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
