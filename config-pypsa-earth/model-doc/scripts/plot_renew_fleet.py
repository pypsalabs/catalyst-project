"""Installed solar, onshore and offshore wind capacity of the countries with the largest fleets (Renewables & Weather).

Grouped bars per country: the capacity of the three technologies in the 2024 networks (networks/<R>-now/elec.nc). Reads
build/renewables_check/capacity.csv, written by ../scripts/check_renewables.py (read-only, no model rerun).

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_renew_fleet.py
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

CARRIERS = {"solar": ("Solar", st.YELLOW), "onwind": ("Onshore wind", st.SKY), "offwind": ("Offshore wind", st.BLUE)}
NAMES = {"CN": "China", "US": "US", "IN": "India", "DE": "Germany", "JP": "Japan", "BR": "Brazil", "ES": "Spain", "GB": "UK",
         "FR": "France", "IT": "Italy", "AU": "Australia", "KR": "South Korea", "CA": "Canada", "SE": "Sweden",
         "NL": "Netherlands", "TR": "Türkiye", "PL": "Poland", "VN": "Vietnam", "MX": "Mexico"}
TOP_N = 12


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--capacity", default=TOP / "build/renewables_check/capacity.csv")
    p.add_argument("--out", default=TOP / "build/figures/renew_fleet.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--capacity", snakemake.input.capacity, "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    d = pd.read_csv(a.capacity).pivot_table(index="country", columns="carrier", values="model_gw", aggfunc="sum").fillna(0.0)
    total = d.sum()
    d = d.loc[d.sum(axis=1).sort_values(ascending=False).index[:TOP_N], list(CARRIERS)]

    st.use()
    fig, ax = plt.subplots(figsize=(6.3, 3.6))
    x = np.arange(len(d))
    w = 0.27
    for i, (c, (label, colour)) in enumerate(CARRIERS.items()):
        ax.bar(x + (i - 1) * w, d[c], width=w, color=colour, linewidth=0, label=f"{label} ({total[c]:,.0f} GW in all modelled countries)")
        for xi, v in zip(x, d[c]):
            if v >= 1:
                ax.annotate(f"{v:,.0f}", (xi + (i - 1) * w, v), xytext=(0, 2), textcoords="offset points", ha="center",
                            va="bottom", fontsize=5.5, color=st.TEXT)
    ax.set_xticks(x, [NAMES.get(c, c) for c in d.index], fontsize=6.3)
    ax.set_ylabel("Installed capacity in the 2024 networks, GW")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper right", fontsize=7)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(d.round(1).to_string(), f"\nshare of the top {TOP_N}: {d.sum().sum() / total.sum():.1%} -> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
