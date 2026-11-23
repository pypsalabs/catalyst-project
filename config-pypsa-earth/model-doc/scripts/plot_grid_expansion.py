"""Allowed build-out of the transmission grid per region, 2024-2050, against what was delivered and what plans ask (Grid Data).

One panel per region: the grid relative to 2024, as the cap lets it grow with the delivered rate (the model's
central case) and with the plan rate (the sensitivity), the growth of the last decade and the published plan figures.
Also writes build/grid_expansion.tex, the table of rates and allowances (a tabular for doc/sections/grid.tex).
Reads ../data/grid_expansion/{grid_expansion,published}.csv; nothing of the model.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_grid_expansion.py
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

DATA = TOP.parent / "data/grid_expansion"
PANELS = [("US", "US West and US East", "USW"), ("NWE", "North-West Europe", "NWE"), ("BR", "Brazil", "BR"), ("IN", "India", "IN"), ("CN", "China", "CN")]
REF = 2024
# the decade of growth drawn as history, and the plan figures drawn as points: (region, what starts with)
HISTORY = {"US": "high-voltage transmission capacity", "NWE": "transmission grid of the European Union", "BR": "transmission lines",
           "IN": "transmission lines", "CN": "west-to-east transmission capacity"}


def ratio(row):
    return row.value / row.value_ref if pd.notna(row.value_ref) else row.value


def table(rates, out):
    rows = []
    for r in rates.itertuples():
        cap = [(1 + r.rate_delivered) ** (y - REF) for y in (2030, 2040, 2050)]
        rows.append(rf"    {r.name} & {100 * r.rate_delivered:g}\,\% & " + " & ".join(f"{c:.2f}" for c in cap)
                    + rf" & {100 * r.rate_plan:g}\,\% & {(1 + r.rate_plan) ** (2050 - REF):.2f} \\")
    head = [r"\begin{tabular}{lrrrrrr}", r"    \toprule",
            r"    & \multicolumn{4}{c}{delivered (central case)} & \multicolumn{2}{c}{plans (sensitivity)} " + "\\\\",
            r"    \cmidrule(lr){2-5} \cmidrule(lr){6-7}", r"    Region & rate & 2030 & 2040 & 2050 & rate & 2050 " + "\\\\", r"    \midrule"]
    out.write_text("\n".join(head + rows + [r"    \bottomrule", r"\end{tabular}"]) + "\n")


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--out", default=None)
    a = p.parse_args([] if "snakemake" in globals() else None)
    out = Path(snakemake.output.figure if "snakemake" in globals() else a.out or TOP / "build/figures/grid_expansion.pdf")

    st.use()
    rates = pd.read_csv(DATA / "grid_expansion.csv", comment="#")
    pub = pd.read_csv(DATA / "published.csv", comment="#")
    table(rates, out.parent.parent / "grid_expansion.tex")

    fig, axes = plt.subplots(1, 5, layout="none", figsize=(6.3, 2.75), sharey=True)
    plt.subplots_adjust(left=0.055, right=0.99, top=0.76, bottom=0.12, wspace=0.1)
    years = np.arange(REF, 2051)
    for ax, (key, name, stage) in zip(axes, PANELS):
        r = rates.set_index("region").loc[stage]
        d = pub[pub.region == key]
        h = d[(d.kind == "delivered") & d.what.str.startswith(HISTORY[key])].iloc[0]
        g = ratio(h) ** (1 / (h.year - h.year_ref))   # growth per year of the drawn decade
        back = np.arange(2014, REF + 1)
        ax.plot(back, g ** (back - REF), color=st.NEUTRAL, lw=1.6, zorder=2, solid_capstyle="butt")
        ax.plot(years, (1 + r.rate_plan) ** (years - REF), color=st.BLUE, lw=1.0, ls=(0, (3, 2)), zorder=3)
        ax.plot(years, (1 + r.rate_delivered) ** (years - REF), color=st.BLUE, lw=1.8, zorder=4)
        plan = d[d.kind == "plan"]
        y = np.array([ratio(x) * g ** (x.year_ref - REF) for x in plan.itertuples()])   # anchored on the history line at its base year
        ax.scatter(plan.year, y, s=13, facecolor="white", edgecolor=st.TEXT, linewidths=0.8, zorder=5)
        ax.set_title(name, loc="left", fontsize=7.2, pad=3)
        ax.text(2049.5, (1 + r.rate_delivered) ** 26 - 0.1, f"{(1 + r.rate_delivered) ** 26:.1f}", fontsize=6.8, ha="right", va="top",
                color=st.BLUE, fontweight="bold")
        ax.text(2015, 3.12, f"{100 * r.rate_delivered:g} %/yr", fontsize=6.8, color=st.BLUE, va="top", fontweight="bold")
        ax.text(2015, 2.9, f"plans: {100 * r.rate_plan:g} %/yr", fontsize=6.4, color=st.TICK, va="top")
        ax.set_xlim(2014, 2051)
        ax.set_ylim(0.5, 3.2)
        ax.set_yticks([1, 2, 3])
        ax.set_xticks([2024, 2040], ["2024", "2040"])
        ax.tick_params(labelsize=6.6)
    fig.text(0.055, 0.955, "Transmission grid relative to 2024: the cap on build-out, what was delivered, what plans ask", fontsize=8,
             fontweight="bold", color=st.TEXT, va="center")
    handles = [Line2D([], [], color=st.BLUE, lw=1.8, label="cap, delivered rate (central case)"),
               Line2D([], [], color=st.BLUE, lw=1.0, ls=(0, (3, 2)), label="cap, plan rate"),
               Line2D([], [], color=st.NEUTRAL, lw=1.6, label="last decade"),
               Line2D([], [], marker="o", ls="", ms=3.8, markerfacecolor="white", markeredgecolor=st.TEXT, markeredgewidth=0.8, label="published plans")]
    fig.legend(handles=handles, loc="center left", bbox_to_anchor=(0.045, 0.885), ncol=4, fontsize=6.5, frameon=False, columnspacing=1.4,
               handletextpad=0.5, handlelength=1.6)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=300)
    fig.set_layout_engine("none")
    fig.savefig(out.with_suffix(".png"), dpi=200)
    print(f"-> {out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
