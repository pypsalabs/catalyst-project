"""Fuel burnt per MWh of electricity by the existing fleet: PyPSA-Earth v0.9.0 against the fleet efficiencies.

(a) Per carrier: the value of the cost table (v0.9.0; plants without an efficiency of their own) against the fleet
    efficiency of calibration/2024/efficiency.csv per modelled country (dot area = the country's capacity of the carrier,
    one scale for all rows; countries without an own value take the default row `*`). The capacity statistic has one
    coal group; it is split into hard coal and lignite by the plant list's lignite share (lignite_gw of
    build/fleet_check/world.csv, written by ../scripts/check_fleet.py), as the model splits it.
(b) Per region: fuel burnt per MWh of fossil electricity, weighted with Ember's 2024 generation (calibration/2024/
    generation.csv), before and after; gas at the CCGT values, coal generation split by the same lignite share. Plant-level
    efficiencies (under 3 % of the thermal capacity outside North-West Europe) and the efficiency tranches are left out.
Tables only, no network is read.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_fleet_efficiency.py
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
CAL = TOP.parent / "calibration/2024"
FORK = TOP.parent.parent / "models/pypsa-earth"
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

# panel (a): row label -> carrier (efficiency table, cost table, colour); capacity from the group of CAPACITY
ROWS = {"hard coal": "coal", "lignite": "lignite", "oil": "oil", "CCGT": "CCGT", "OCGT": "OCGT"}
SIZE = 0.12          # marker area (pt^2) per GW, one scale for every row
MIN_SIZE = 3.0       # smallest marker, so that countries with a few MW stay visible
SIZE_KEY = [10, 100, 1000]   # GW in the size legend
# panel (b): Ember group -> carrier of the efficiency table and of the cost table
GROUP = {"coal": "coal", "gas": "CCGT", "oil": "oil"}
NWE = ["AT", "BE", "CH", "CZ", "DE", "DK", "FR", "GB", "IE", "LU", "NL", "PL"]
REGIONS = {"US": ["US"], "China": ["CN"], "India": ["IN"], "NW Europe": NWE, "Brazil": ["BR"]}


def fleet(eff, country, carrier):
    return eff.get((country, carrier), eff[("*", carrier)])


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--efficiency", default=CAL / "efficiency.csv")
    p.add_argument("--generation", default=CAL / "generation.csv")
    p.add_argument("--capacity", default=CAL / "capacity.csv")
    p.add_argument("--costs", default=FORK / "resources/US-now/costs_2025.csv")
    p.add_argument("--row-countries", default=TOP.parent / "data/row_countries.csv")
    p.add_argument("--world", default=TOP / "build/fleet_check/world.csv")
    p.add_argument("--out", default=TOP / "build/figures/fleet_efficiency.pdf")
    if "snakemake" in globals():
        i = snakemake.input
        a = p.parse_args(["--efficiency", i.efficiency, "--generation", i.generation, "--capacity", i.capacity,
                          "--costs", i.costs, "--row-countries", i.row_countries, "--world", i.world,
                          "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    eff = pd.read_csv(a.efficiency).set_index(["country", "carrier"]).efficiency
    costs = pd.read_csv(a.costs).query("parameter == 'efficiency'").set_index("technology").value
    cap = pd.read_csv(a.capacity).set_index(["country", "group"]).gw
    rc = pd.read_csv(a.row_countries, keep_default_na=False)
    modelled = sorted(rc.iso2[rc.status.isin(["modelled", "archetype"])])

    gen = pd.read_csv(a.generation)
    gen = gen[gen.group.isin(GROUP) & gen.country.isin(modelled) & (gen.twh > 0)].copy()
    w = pd.read_csv(a.world).query("group == 'coal' and plant_list_gw > 0").set_index("country")
    lignite = (w.lignite_gw / w.plant_list_gw).groupby(level=0).first()   # share of the coal group
    share = lambda c: float(lignite.get(c, 0.0))   # noqa: E731
    gw = {}
    for c in modelled:
        coal = cap.get((c, "coal"), 0.0)
        gw[(c, "coal")], gw[(c, "lignite")], gw[(c, "oil")] = coal * (1 - share(c)), coal * share(c), cap.get((c, "oil"), 0.0)

    gen["after"] = gen.twh / [fleet(eff, c, GROUP[g]) for c, g in zip(gen.country, gen.group)]
    gen["before"] = gen.twh / gen.group.map(GROUP).map(costs)
    coal = gen.group == "coal"   # v0.9.0 burns lignite at its own, lower efficiency
    sh = gen.loc[coal, "country"].map(share)
    gen.loc[coal, "before"] = gen.loc[coal, "twh"] * ((1 - sh) / costs["coal"] + sh / costs["lignite"])

    st.use()
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(6.3, 4.6), sharex=True, gridspec_kw=dict(height_ratios=[5, 6]))

    # (a) per carrier
    rng = np.random.default_rng(0)
    for k, (row, carrier) in enumerate(ROWS.items()):
        y = len(ROWS) - 1 - k
        ax.plot([1 / costs[carrier]] * 2, [y - 0.4, y + 0.4], color=st.NEUTRAL, lw=2.2, solid_capstyle="butt", zorder=2)
        if carrier in ("CCGT", "OCGT"):
            x = 1 / fleet(eff, "*", carrier)
            ax.scatter([x], [y], s=28, color=st.FUEL[carrier], linewidth=0, zorder=3)
            ax.annotate("everywhere", (x, y), xytext=(6, 0), textcoords="offset points", va="center", fontsize=6.5,
                        color=st.TICK)
            continue
        cs = [c for c in modelled if gw[(c, carrier)] > 0]
        v = np.array([1 / fleet(eff, c, carrier) for c in cs])
        g = np.array([gw[(c, carrier)] for c in cs])
        ax.scatter(v, y + rng.uniform(-0.22, 0.22, len(v)), s=MIN_SIZE + SIZE * g, color=st.FUEL[carrier], alpha=0.8,
                   linewidth=0, zorder=3)
    ax.set_yticks(range(len(ROWS)), list(ROWS)[::-1])
    ax.set_ylim(-0.6, len(ROWS) - 0.4)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True, ls=(0, (3, 3)), lw=0.5, color=st.GRID)   # dashed, to read the top rows against the x-axis
    ax.set_title("(a) Per carrier and country", loc="left")
    ax.legend(handles=[plt.scatter([], [], s=MIN_SIZE + SIZE * v, color=st.NEUTRAL, linewidth=0) for v in SIZE_KEY],
              labels=[f"{v:,} GW" for v in SIZE_KEY], title="Capacity", loc="upper left", ncol=len(SIZE_KEY),
              fontsize=6.5, title_fontsize=6.5, frameon=True, facecolor="white", edgecolor="none", framealpha=1, handletextpad=0.2, columnspacing=1.0, borderaxespad=0.2)

    # (b) per region, weighted with the 2024 generation
    regions = {**REGIONS, f"all {len(modelled)} modelled countries": modelled}
    for k, (name, cs) in enumerate(regions.items()):
        y = len(regions) - 1 - k
        d = gen[gen.country.isin(cs)][["twh", "before", "after"]].sum()
        x0, x1 = d.before / d.twh, d.after / d.twh
        bx.plot([x0, x1], [y, y], color=st.FAINT, lw=1.0, zorder=1)
        bx.scatter([x0], [y], s=30, facecolor="white", edgecolor=st.TICK, linewidth=1.0, zorder=3)
        bx.scatter([x1], [y], s=30, color=st.TEXT, linewidth=0, zorder=3)
        bx.annotate(f"{d.after / d.before - 1:+.1%} fuel".replace("-", "\u2212"), (max(x0, x1), y), xytext=(7, 0), textcoords="offset points",
                    va="center", fontsize=6.5, color=st.TEXT)
    bx.set_yticks(range(len(regions)), list(regions)[::-1])
    bx.set_ylim(-0.6, len(regions) - 0.4)
    bx.grid(axis="y", visible=False)
    bx.grid(axis="x", visible=True, ls=(0, (3, 3)), lw=0.5, color=st.GRID)   # dashed, to read the top rows against the x-axis
    bx.set_title("(b) All fossil generation of 2024, per region", loc="left")
    bx.set_xlabel("Fuel burnt per MWh of electricity, MWh (thermal)")
    bx.set_xlim(1.6, 3.25)

    fig.legend(handles=[plt.Line2D([], [], color=st.NEUTRAL, lw=2.2),
                        plt.Line2D([], [], marker="o", ls="none", mfc="white", mec=st.TICK, ms=5),
                        plt.Line2D([], [], marker="o", ls="none", mfc=st.TEXT, mec="none", ms=5)],
               labels=["PyPSA-Earth v0.9.0, per carrier", "v0.9.0, per region", "fleet efficiencies (this commit)"],
               loc="lower center", ncol=3, fontsize=6.5, handletextpad=0.4, columnspacing=1.4)
    fig.get_layout_engine().set(rect=(0, 0.06, 1, 0.94))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
