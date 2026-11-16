"""How broad the plant list is: capacity per fuel by the databases that report each plant, and the fields they fill.

(a) GW of powerplantmatching's matched list over the 132 modelled countries (every plant the list keeps, of any status),
    per fuel, split by the set of source databases behind each plant; the number of plants at the bar's end.
(b) Share of that capacity that reports a commissioning year, a decommissioning year and an efficiency.
Reads build/fleet_check/{sources,fields}.csv, written by ../scripts/check_fleet.py (read-only, no model rerun).

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_fleet_sources.py
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

FUELS = {"coal": "Coal", "gas": "Gas", "oil": "Oil", "nuclear": "Nuclear", "biomass": "Biomass", "geothermal": "Geothermal",
         "hydro": "Hydro", "wind": "Wind", "solar": "Solar"}
KINDS = [  # key, colour, legend label
    ("gem3", "#08306b", "in GEM, GPD and GEO"),
    ("gem2", "#2b6cb0", "in GEM and one other"),
    ("gem1", "#8fb8de", "in GEM only"),
    ("other", st.NEUTRAL, "in GPD or GEO, not GEM"),
]
FIELDS = [("datein", "commissioning year", st.BLUE), ("dateout", "decommissioning year", st.VERMILLION),
          ("efficiency", "efficiency", st.ORANGE)]


def kind(sources):
    s = set(sources.split("+")) - {"EESI"}   # the storage inventory adds no thermal plant of its own
    if "GEM" not in s:
        return "other"
    return {3: "gem3", 2: "gem2"}.get(len(s), "gem1")


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--sources", default=TOP / "build/fleet_check/sources.csv")
    p.add_argument("--fields", default=TOP / "build/fleet_check/fields.csv")
    p.add_argument("--out", default=TOP / "build/figures/fleet_sources.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--sources", snakemake.input.sources, "--fields", snakemake.input.fields, "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    s = pd.read_csv(a.sources, keep_default_na=False)
    s["kind"] = s.sources.map(kind)
    gw = s.pivot_table(index="fuel", columns="kind", values="gw", aggfunc="sum").reindex(list(FUELS)).fillna(0.0)
    plants = s.groupby("fuel").plants.sum().reindex(list(FUELS))
    f = pd.read_csv(a.fields)
    share = {k: (f[k] * f.gw).groupby(f.fuel).sum() / f.gw.groupby(f.fuel).sum() for k, _, _ in FIELDS}

    st.use()
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(6.3, 2.9), gridspec_kw=dict(width_ratios=[1.35, 1]), sharey=True)
    y = np.arange(len(FUELS))[::-1]
    left = np.zeros(len(FUELS))
    for k, colour, _ in KINDS:
        v = gw[k].values if k in gw else np.zeros(len(FUELS))
        ax.barh(y, v, left=left, height=0.62, color=colour, linewidth=0)
        left += v
    for yi, x, n in zip(y, left, plants):
        ax.annotate(f"{n:,.0f} plants", (x, yi), xytext=(3, 0), textcoords="offset points", va="center", fontsize=6.5, color=st.TICK)
    ax.set_yticks(y, list(FUELS.values()))
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.set_xlim(0, left.max() * 1.32)
    ax.set_title("(a) Capacity in the plant database by source, GW", loc="left")
    st.legend_squares(ax, [(c, l) for _, c, l in KINDS], loc="lower right", fontsize=6.5)

    for j, (k, label, colour) in enumerate(FIELDS):
        v = share[k].reindex(list(FUELS)).fillna(0.0) * 100
        bx.scatter(v, y + (1 - j) * 0.22, s=14, color=colour, linewidth=0, zorder=3, label=label)
    bx.set_xlim(-3, 103)
    bx.grid(axis="y", visible=False)
    bx.grid(axis="x", visible=True)
    bx.set_title("(b) Capacity with the field reported, %", loc="left")
    bx.legend(loc="center", fontsize=6.5, handletextpad=0.2, markerscale=1.0, borderaxespad=0)

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(gw.round(0).to_string(), f"\n-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
