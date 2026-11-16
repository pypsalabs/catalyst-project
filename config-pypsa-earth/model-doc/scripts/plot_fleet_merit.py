"""The merit order of Germany's thermal fleet: standard procedure against the model.

(a) Standard procedure: one step per carrier, technology-data's new-build efficiency, one world price per fuel, no CO2
    price (marginal_cost of resources/NWE-now/costs_2025_elec.csv), on the model's capacity per carrier.
(b) The model: every fuel-burning generator of the solved `now` network in Germany (results/NWE-now), with the fleet
    efficiencies, the country's fuel and CO2 prices and the three efficiency tranches; one step per generator.
Both in USD2024 per MWh of electricity.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_fleet_merit.py
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import pypsa

TOP = Path(__file__).resolve().parents[1]
FORK = TOP.parent.parent / "models/pypsa-earth"
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

CARRIERS = ["geothermal", "biomass", "lignite", "coal", "CCGT", "OCGT", "oil"]
COUNTRY = "DE"


def steps(ax, df):
    """Bars of width p_nom (GW) and height marginal cost, sorted by cost."""
    df = df.sort_values("mc")
    x = 0.0
    for _, r in df.iterrows():
        ax.bar(x, r.mc, width=r.gw, align="edge", color=st.FUEL[r.carrier], linewidth=0)
        x += r.gw
    return x


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--network", default=FORK / "results/NWE-now/networks/elec_s_50_ec_lcopt_3h.nc")
    p.add_argument("--costs", default=FORK / "resources/NWE-now/costs_2025_elec.csv")
    p.add_argument("--out", default=TOP / "build/figures/fleet_merit.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--network", snakemake.input.network, "--costs", snakemake.input.costs, "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    n = pypsa.Network(str(a.network))
    g = n.generators[(n.generators.bus.map(n.buses.country) == COUNTRY) & n.generators.carrier.isin(CARRIERS)]
    model = pd.DataFrame({"carrier": g.carrier, "gw": g.p_nom / 1e3, "mc": g.marginal_cost})
    model = model[model.gw > 0.01]
    model = model[model.carrier.map(model.groupby("carrier").gw.sum()) > 0.1]   # Germany's 0.04 GW of geothermal is not visible
    costs = pd.read_csv(a.costs, index_col=0)
    standard = model.groupby("carrier").gw.sum().to_frame().reset_index()
    standard["mc"] = standard.carrier.map(costs.marginal_cost)

    st.use()
    fig, axes = plt.subplots(1, 2, figsize=(6.3, 2.7), sharey=True)
    for ax, df, title in [(axes[0], standard, "(a) PyPSA-Earth default"), (axes[1], model, "(b) With the adjustments")]:
        total = steps(ax, df)
        ax.set_xlim(0, total * 1.02)
        ax.set_title(title, loc="left")
        ax.set_xlabel("Cumulative capacity, GW")
    axes[0].annotate("Marginal cost, USD2024 per MWh", (0, 1.13), xycoords="axes fraction", fontsize=6.5, color=st.TICK).set_in_layout(False)
    present = [c for c in CARRIERS if c in set(model.carrier)]
    st.legend_squares(axes[0], [(st.FUEL[c], c) for c in present], loc="upper left", fontsize=6.5)
    fig.get_layout_engine().set(rect=(0, 0, 1, 0.93))   # room for the axis label above the titles
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(standard.round(1).to_string(), f"\n{len(model)} generators -> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
