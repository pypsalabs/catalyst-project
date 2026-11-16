"""Commissioning years of the existing fleet in the five spatially resolved regions, in the model's five-year bands.

GW of the plant list of each region's `now` stage (resources/<R>-now/powerplants.csv, already scaled to the statistic) by
commissioning year, in the bands of existing_capacities.grouping_years_power that add_electricity groups the plants by,
per carrier; hydropower, wind and solar left out.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_fleet_vintage.py
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
FORK = TOP.parent.parent / "models/pypsa-earth"
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

REGIONS = {"US": "US", "CN": "China", "IN": "India", "NWE": "NW Europe", "BR": "Brazil"}
CARRIERS = {"Hard Coal": "coal", "Lignite": "lignite", "CCGT": "CCGT", "OCGT": "OCGT", "Oil": "oil", "Nuclear": "nuclear",
            "Solid Biomass": "biomass", "Biogas": "biomass", "Waste": "biomass", "Bioenergy": "biomass", "Geothermal": "geothermal"}
ORDER = ["coal", "lignite", "CCGT", "OCGT", "oil", "nuclear", "biomass", "geothermal"]
BANDS = list(range(1960, 2030, 5))   # grouping_years_power up to the reference year: a plant joins the first band year >= DateIn


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--plants", nargs="+", default=[FORK / f"resources/{r}-now/powerplants.csv" for r in REGIONS])
    p.add_argument("--out", default=TOP / "build/figures/fleet_vintage.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--plants", *snakemake.input.plants, "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    st.use()
    fig, axes = plt.subplots(1, len(REGIONS), figsize=(6.3, 2.6), sharex=True)
    for ax, (r, name), fn in zip(axes, REGIONS.items(), a.plants):
        ppl = pd.read_csv(fn, index_col=0)
        ppl["carrier"] = ppl.Fueltype.map(CARRIERS)
        ppl = ppl.dropna(subset=["carrier"])
        band = np.digitize(ppl.DateIn.fillna(ppl.DateIn.mean()), BANDS, right=True).clip(0, len(BANDS) - 1)
        t = ppl.Capacity.groupby([band, ppl.carrier]).sum().unstack().reindex(index=range(len(BANDS)), columns=ORDER).fillna(0) / 1e3
        x = np.arange(len(BANDS))
        bottom = np.zeros(len(BANDS))
        for c in ORDER:
            ax.bar(x, t[c], bottom=bottom, width=0.82, color=st.FUEL[c], linewidth=0)
            bottom += t[c].values
        ax.set_title(name, loc="left")
        ax.set_xticks([0, 6, 12], ["≤1960", "1990", "2020"])
        ax.tick_params(axis="y", labelsize=6.5)
        ax.set_xlim(-0.7, len(BANDS) - 0.3)
    axes[0].annotate("Capacity by commissioning period, GW", (0, 1.13), xycoords="axes fraction", fontsize=6.5, color=st.TICK).set_in_layout(False)
    fig.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=st.FUEL[c], linewidth=0) for c in ORDER], labels=ORDER,
               loc="lower center", ncol=len(ORDER), fontsize=6.5, handlelength=0.9, handleheight=0.9, handletextpad=0.4,
               columnspacing=1.0, bbox_to_anchor=(0.5, -0.02))
    fig.get_layout_engine().set(rect=(0, 0.07, 1, 0.86))   # (left, bottom, width, height): legend below, axis label above
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
