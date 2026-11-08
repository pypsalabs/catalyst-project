"""Cheapest EGS LCOE in each of the largest power systems: figures/egs_country_lcoe.{png,pdf}.

One bar per country, height = the lowest LCOE of its feasible cells (build/egs_potential.csv, cheapest depth,
remote territories excluded), coloured with the classes and colormap of panel d of egs_maps (plot_maps.py), for
the `country_lcoe.n` largest power systems by 2024 electricity demand (Ember, as ranked in
../../config-pypsa-earth/data/row_countries.csv), largest on the left.

The US is three systems: West (the 11 WECC states of config regions.USW), ERCOT (Texas) and East (the other
states without Alaska and Hawaii, which belong to neither interconnection). Ember's US demand is split by the
states' 2024 net generation (EIA, ../country-classification/data/annual_generation_state.csv), the convention of
../country-classification/split_us.py. Caveats: generation, not load (California imports, the Southwest exports);
ERCOT is approximated by the whole of Texas (El Paso and the Panhandle are not in ERCOT).

Outputs  figures/egs_country_lcoe.{png,pdf}, build/egs_country_lcoe.csv
Standalone: python plot_country_lcoe.py
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from matplotlib.colors import BoundaryNorm
from matplotlib.cm import ScalarMappable

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(next(p for p in HERE.resolve().parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import iconstyle as ic  # noqa: E402
from plot_maps import LCOE_BINS, TWILIGHT, classed  # noqa: E402

if "snakemake" in globals():
    CFG = snakemake.config
    POT, DEMAND, EIA = (Path(snakemake.input[k]) for k in ("potential", "demand", "eia"))
    OUT_CSV, FIGS = Path(snakemake.output.csv), [Path(f) for f in snakemake.output.figs]
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    c = CFG["country_lcoe"]
    POT, DEMAND, EIA = HERE / "build" / "egs_potential.csv", HERE / c["demand"], HERE / c["eia_generation"]
    OUT_CSV = HERE / "build" / "egs_country_lcoe.csv"
    FIGS = [HERE / "figures" / f"egs_country_lcoe.{f}" for f in CFG["plotting"]["formats"]]

US_EXCLUDED = {"AK", "HI"}
US_PARTS = {"USW": "US West", "ERCOT": "US ERCOT", "USE": "US East"}


def us_part(state, west):
    if state in US_EXCLUDED:
        return None
    return "USW" if state in west else "ERCOT" if state == "TX" else "USE"


def us_shares(west):
    g = pd.read_csv(EIA, skiprows=1)
    g.columns = ["year", "state", "producer", "fuel", "mwh"]
    g["state"] = g["state"].str.strip()
    g = g[(g["year"] == g["year"].max()) & (g["producer"] == "Total Electric Power Industry") & (g["fuel"] == "Total")
          & g["state"].str.len().eq(2) & (g["state"] != "US")]
    mwh = pd.to_numeric(g["mwh"].astype(str).str.replace(",", ""), errors="coerce")
    by = mwh.groupby(g["state"].map(lambda s: us_part(s, west)).values).sum()
    return by / mwh.sum()                      # shares of the national total: AK/HI's part is dropped


def main():
    west = set(CFG["regions"]["USW"]["admin1_codes"])
    pot = pd.read_csv(POT, dtype={"admin1": str, "iso3": str}, low_memory=False)
    pot = pot[~pot["remote_territory"]]
    us = pot["iso3"] == "USA"
    pot.loc[us, "iso3"] = pot.loc[us, "admin1"].map(lambda s: us_part(s, west))
    pot = pot.dropna(subset=["iso3"])
    best = pot.loc[pot.groupby("iso3")["lcoe_usd_per_mwh"].idxmin(),
                   ["iso3", "country", "lcoe_usd_per_mwh", "capex_usd_per_kw", "depth_km", "t_reservoir_c", "lon", "lat"]]
    best = best.set_index("iso3")

    dem = pd.read_csv(DEMAND)[["iso3", "name", "demand_twh"]].set_index("iso3")
    shares = us_shares(west)
    for k in US_PARTS:
        dem.loc[k] = [US_PARTS[k], dem.at["USA", "demand_twh"] * shares[k]]
    dem = dem.drop("USA").sort_values("demand_twh", ascending=False).head(CFG["country_lcoe"]["n"])
    tab = dem.join(best, how="left")
    tab["label"] = [US_PARTS.get(i, c if isinstance(c, str) else n) for i, c, n in zip(tab.index, tab["country"], tab["name"])]
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    tab.drop(columns="name").to_csv(OUT_CSV, float_format="%.5g")
    print(tab[["label", "demand_twh", "lcoe_usd_per_mwh", "capex_usd_per_kw", "depth_km", "t_reservoir_c"]].round(1).to_string())

    ic.use()
    cmap = classed("twilight", len(LCOE_BINS) - 1, span=TWILIGHT)
    norm = BoundaryNorm(LCOE_BINS, len(LCOE_BINS) - 1)
    fig, ax = plt.subplots(figsize=(max(9.6, 0.42 * len(tab) + 1.2), 4.2))
    x = np.arange(len(tab))
    h = tab["lcoe_usd_per_mwh"].values
    ok = np.isfinite(h)
    ic.bars(ax, x[ok], h[ok], color=[cmap(norm(v)) for v in h[ok]])
    for xi in x[~ok]:
        ax.annotate("no cell\n≥ 150 °C", (xi, 0), xytext=(0, 4), textcoords="offset points", ha="center", va="bottom",
                    fontsize=6.5, color=ic.MUTED)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{l}\n{d:,.0f} TWh" for l, d in zip(tab["label"], tab["demand_twh"])],
                       rotation=55, ha="right", rotation_mode="anchor", fontsize=7)
    ax.set_xlim(-0.6, len(tab) - 0.4)
    ax.set_ylim(0, max(np.nanmax(h) * 1.12, 100))
    ax.set_title(f"Cheapest EGS LCOE per power system, USD{CFG['base_currency_year']}/MWh")
    cax = fig.add_axes([0.905, 0.42, 0.012, 0.45])
    cb = fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), cax=cax, ticks=LCOE_BINS)
    cb.outline.set_linewidth(ic.SEAM)
    cb.outline.set_edgecolor(ic.INK)
    cb.ax.tick_params(labelsize=6.5, length=2, colors=ic.MUTED)
    cb.set_label("map classes (egs_maps d)", fontsize=6.5, color=ic.MUTED)
    fig.subplots_adjust(left=0.06, right=0.89, top=0.9, bottom=0.30)
    ic.ground(ax)
    for f in FIGS:
        f.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(f, dpi=CFG["plotting"]["dpi"])
    plt.close(fig)


if __name__ == "__main__" or "snakemake" in globals():
    main()
