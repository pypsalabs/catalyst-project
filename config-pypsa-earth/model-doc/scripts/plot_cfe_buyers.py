"""Electricity use of RE100 members by group of companies, and corporate buyers against world demand (Demand for 24/7 CFE).

Left: RE100 members' reported consumption per data year, the named companies summed per group (a company counts from its
joining year), the rest as "other members". Right: RE100 members, all data centres (IEA), the four large technology
companies and the two with an hourly-matching goal as a share of world electricity demand (Ember). Reads
build/buyers_{stack,share}.csv of misc-quarter1/datacentre-demand and the groups of its config.yaml.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_cfe_buyers.py
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import yaml

TOP = Path(__file__).resolve().parents[1]
TOPIC = TOP.parents[1] / "misc-quarter1/datacentre-demand"
sys.path.insert(0, str(TOP / "scripts"))
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402
from plot_cfe_datacentres import end_labels  # noqa: E402

HUES = [st.BLUE, st.GREEN, st.ORANGE, st.PINK, st.SKY]
OTHER = "Other members"
LINES = {"RE100 members": st.TEXT, "All data centres": "#9e9e9e", "Four tech companies": st.BLUE,
         "Google and Microsoft": st.VERMILLION}


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--stack", default=TOPIC / "build/buyers_stack.csv")
    p.add_argument("--share", default=TOPIC / "build/buyers_share.csv")
    p.add_argument("--config", default=TOPIC / "config.yaml")
    p.add_argument("--out", default=TOP / "build/figures/cfe_buyers.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--stack", snakemake.input.stack, "--share", snakemake.input.share,
                          "--config", snakemake.input.config, "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    stack = pd.read_csv(a.stack, index_col="year")
    share = pd.read_csv(a.share, index_col="year")
    groups = yaml.safe_load(open(a.config))["buyers"]["groups"]
    by_group = pd.DataFrame({g: stack[members].sum(axis=1) for g, members in groups.items()})
    by_group[OTHER] = stack[OTHER]
    colour = dict(zip(groups, HUES)) | {OTHER: "#d4d4d4"}
    years = by_group.index

    st.use()
    fig = plt.figure(figsize=(6.3, 2.75), layout="none")
    ax = fig.add_axes([0.07, 0.1, 0.31, 0.78])
    bx = fig.add_axes([0.62, 0.1, 0.15, 0.78])

    ax.stackplot(years, by_group.T.values, colors=[colour[g] for g in by_group], linewidth=0.4, edgecolor="white")
    ax.set_ylim(0, 1.05 * by_group.sum(axis=1).max())
    top = by_group.cumsum(axis=1).iloc[-1]
    end_labels(ax, years.max(), [(f"{g} {by_group[g].iloc[-1]:.0f}", top[g] - by_group[g].iloc[-1] / 2, st.TEXT)
                                 for g in by_group], 0.06, 0.55)
    ax.set_title("RE100 members' electricity use, TWh per year", loc="left", fontsize=8.5)

    for k, c in LINES.items():
        s = share[k].dropna()
        bx.plot(s.index, s.values, color=c, linewidth=1.6 if k == "RE100 members" else 1.3)
    bx.set_ylim(0, None)
    bx.yaxis.set_major_locator(plt.MultipleLocator(0.5))
    bx.yaxis.set_major_formatter(lambda v, _: f"{v:g}")
    last = share.loc[years.max()]
    end_labels(bx, years.max(), [(f"{k} {last[k]:.2f}", last[k], c) for k, c in LINES.items()], 0.07, 0.55)
    bx.set_title("Share of world demand, %", loc="left", fontsize=8.5)
    for axis in (ax, bx):
        axis.set_xlim(years.min(), years.max())
        axis.set_xticks(range(int(years.min()), int(years.max()) + 1, 2))
        axis.tick_params(labelsize=7)

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(by_group.iloc[-1].round(1).to_dict(), f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
