"""Demand per province of China, model over published, before and after the provincial shares (Demand).

Reads build/demand_placement/CN_before.csv and CN_after.csv, written by ../scripts/check_demand_placement.py
(read-only) on the China run before and after `load_options: subnational_shares`; the second file may be missing.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_demand_placement.py
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

HERE = Path(snakemake.scriptdir) if "snakemake" in globals() else Path(__file__).resolve().parent
TOP = HERE.parent
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

DATA = TOP / "build/demand_placement"
SHORT = {"Nei Mongol": "Inner Mongolia", "Xinjiang Uygur": "Xinjiang", "Ningxia Hui": "Ningxia", "Xizang": "Tibet"}


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--data", type=Path, default=DATA)
    p.add_argument("--out", default=None)
    a = p.parse_args([] if "snakemake" in globals() else None)
    if "snakemake" in globals():
        a.data, a.out = Path(snakemake.input.before).parent, str(snakemake.output[0])
    out = Path(a.out or TOP / "build/figures/demand_placement.pdf")

    st.use()
    before = pd.read_csv(a.data / "CN_before.csv", index_col=0)
    after = pd.read_csv(a.data / "CN_after.csv", index_col=0) if (a.data / "CN_after.csv").exists() else None
    d = before.sort_values("share_published", ascending=False)
    half = (len(d) + 1) // 2
    fig, axes = plt.subplots(1, 2, layout="none", figsize=(6.3, 3.9), sharex=True)
    plt.subplots_adjust(left=0.19, right=0.985, top=0.85, bottom=0.11, wspace=0.62)
    for ax, part in zip(axes, [d.iloc[:half], d.iloc[half:]]):
        y = half - 1 - np.arange(len(part))   # both columns start at the top
        ax.axvline(1.0, color=st.TEXT, lw=0.8, zorder=1)
        if after is not None:
            for yy, k in zip(y, part.index):
                ax.plot([part.ratio[k], after.ratio[k]], [yy, yy], color=st.FAINT, lw=1.0, zorder=2, solid_capstyle="butt")
            ax.scatter(after.ratio.reindex(part.index), y, s=16, color=st.BLUE, linewidths=0, zorder=4)
        ax.scatter(part.ratio, y, s=16, color=st.NEUTRAL, linewidths=0, zorder=3)
        share = 100 * part.share_published
        ax.set_yticks(y, [f"{SHORT.get(n, n)}  {s:.1f} %" for n, s in zip(part.name, share)], fontsize=6.6)
        ax.set_ylim(-0.7, half - 0.3)
        ax.set_xscale("log")
        ax.set_xlim(0.22, 5)
        ax.set_xticks([0.25, 0.5, 1, 2, 4], ["0.25", "0.5", "1", "2", "4"])
        ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
        ax.grid(axis="x", visible=True)
        ax.grid(axis="y", visible=False)
        ax.tick_params(labelsize=6.8)
        ax.set_xlabel("Demand in the model over published", fontsize=7)
    fig.text(0.02, 0.965, "Demand per province of China, model over published (province and its published share of national demand)",
             fontsize=7.8, fontweight="bold", color=st.TEXT, va="center")
    handles = [Line2D([], [], marker="o", ls="", ms=4.5, color=st.NEUTRAL, label="distributed by GDP and population")]
    if after is not None:
        handles.append(Line2D([], [], marker="o", ls="", ms=4.5, color=st.BLUE, label="with the provincial shares"))
    fig.legend(handles=handles, loc="center left", bbox_to_anchor=(0.012, 0.915), ncol=2, fontsize=6.7, frameon=False, columnspacing=1.6,
               handletextpad=0.3)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=300)
    fig.set_layout_engine("none")
    fig.savefig(out.with_suffix(".png"), dpi=200)
    print(f"-> {out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
