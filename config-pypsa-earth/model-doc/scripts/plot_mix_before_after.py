"""Electricity mix of 2024 per country: Ember against PyPSA-Earth v0.9.0 out of the box.

One pair of horizontal stacked bars per country (share of generation by fuel): Ember 2024 and the `now` solve of the
v0.9.0 baseline worktree (models/pypsa-earth-baseline, out-of-the-box overlay of 2026-09-19: brownfield expansion at 2025
costs, no CO2 cap, GEGIS 2030 demand). Ember from the validation_world.csv of the catalyst fork, the model from that of
the baseline (both written by scripts/plot_world.py); countries solved in both; no network is read.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_mix_before_after.py
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

TOP = Path(__file__).resolve().parents[1]
MODELS = TOP.parent.parent / "models"
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

FUELS = ["coal", "gas", "oil", "nuclear", "hydro", "wind", "solar", "biomass", "other"]
COUNTRIES = {"*": "all modelled countries", "CN": "China", "US": "US", "IN": "India", "NWE": "North-West Europe",
             "BR": "Brazil", "JP": "Japan", "SA": "Saudi Arabia", "ID": "Indonesia", "AU": "Australia", "ZA": "South Africa"}
ROWS = {"ember": "Ember 2024", "before": "v0.9.0"}


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--before", default=MODELS / "pypsa-earth-baseline/results/catalyst/validation_world.csv")
    p.add_argument("--after", default=MODELS / "pypsa-earth/results/catalyst/validation_world.csv", help="Ember rows")
    p.add_argument("--out", default=TOP / "build/figures/mix_before_after.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--before", snakemake.input.before, "--after", snakemake.input.after, "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    b, af = pd.read_csv(a.before), pd.read_csv(a.after)
    tables = {"ember": af[af.scen == "ember"], "before": b[b.scen == "now"]}
    common = set.intersection(*(set(t.country) for t in tables.values()))
    twh = {}
    for k, t in tables.items():
        t = t[t.country.isin(common)].set_index("country")[FUELS].clip(lower=0)
        twh[k] = pd.concat([t, t.sum().to_frame("*").T])
    share = {k: v.div(v.sum(axis=1), axis=0) * 100 for k, v in twh.items()}

    st.use()
    n = len(COUNTRIES)
    fig, ax = plt.subplots(figsize=(6.3, 5.6))
    gap, h = 3.5, 1.0
    yt, yl = [], []
    for i, (c, name) in enumerate(COUNTRIES.items()):
        top = (n - 1 - i) * gap
        for j, (k, label) in enumerate(ROWS.items()):
            y = top - j * h
            left = 0.0
            for f in FUELS:
                v = share[k].at[c, f]
                ax.barh(y, v, left=left, height=0.82 * h, color=st.FUEL[f], linewidth=0)
                if v >= 7:
                    dark = f in ("coal", "nuclear", "hydro", "biomass")
                    ax.text(left + v / 2, y, f"{v:.0f}", ha="center", va="center", fontsize=6,
                            color="white" if dark else st.TEXT)
                left += v
            yt.append(y)
            yl.append(label)
        ax.text(0, top + 0.62 * h, name if c != "*" else f"{name} ({len(common)})", ha="left", va="bottom",
                fontsize=7.5, fontweight="bold", color=st.TEXT, transform=ax.transData)
    ax.set_yticks(yt, yl, fontsize=6.5)
    ax.set_xlim(0, 100)
    ax.set_ylim(-h - 0.6, (n - 1) * gap + 1.6)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Share of generation, %")
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)

    fig.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=st.FUEL[f], linewidth=0) for f in FUELS], labels=FUELS,
               loc="lower center", ncol=len(FUELS), fontsize=6.5, handlelength=1.0, handleheight=0.9, handletextpad=0.4,
               columnspacing=0.9)
    fig.get_layout_engine().set(rect=(0, 0.045, 1, 0.955))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
