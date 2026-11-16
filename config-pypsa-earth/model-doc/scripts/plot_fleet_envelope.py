"""The operating envelope of today's fleet: minimum and maximum output per country and carrier.

(a) Nuclear, every country with a reactor: the band from p_min_pu to p_max_pu of the existing generators.
(b) Biomass, geothermal and oil: p_max_pu per country (dot area = the country's capacity of the statistic); coal, lignite,
    CCGT and OCGT have one availability for all countries and no minimum output.
Reads calibration/2024/envelope/floor/<carrier>_{p_min,p_max}_pu.csv (the tables of the `now` stage, written by
../scripts/build_calibration.py) and calibration/2024/capacity.csv.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_fleet_envelope.py
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
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

FLAT = ["biomass", "geothermal", "oil"]
PRICE = {"coal": "coal and lignite", "CCGT": "CCGT and OCGT"}
MARK = {"JP": "Japan", "FR": "France", "US": "US", "CN": "China"}


def table(env, carrier, attr, countries=None):
    """Per-country values of a table, for the modelled countries; `countries=None` returns the default row `*`."""
    t = pd.read_csv(Path(env) / f"{carrier}_{attr}.csv", index_col=0).value
    return t.loc["*"] if countries is None else t[t.index.isin(countries)]


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--envelope", default=CAL / "envelope/floor")
    p.add_argument("--capacity", default=CAL / "capacity.csv")
    p.add_argument("--row-countries", default=TOP.parent / "data/row_countries.csv")
    p.add_argument("--out", default=TOP / "build/figures/fleet_envelope.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--envelope", str(Path(snakemake.input.tables[0]).parent), "--capacity", snakemake.input.capacity,
                          "--row-countries", snakemake.input.row_countries,
                          "--out", snakemake.output[0]])
    else:
        a = p.parse_args()
    cap = pd.read_csv(a.capacity).set_index(["country", "group"]).gw
    rc = pd.read_csv(a.row_countries, keep_default_na=False)
    modelled = set(rc.iso2[rc.status.isin(["modelled", "archetype"])])

    st.use()
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(6.3, 3.6), gridspec_kw=dict(width_ratios=[1, 1.25]))

    lo, hi = table(a.envelope, "nuclear", "p_min_pu", modelled), table(a.envelope, "nuclear", "p_max_pu", modelled)
    hi = hi.sort_values()
    y = np.arange(len(hi))
    ax.barh(y, hi - lo.reindex(hi.index), left=lo.reindex(hi.index), height=0.62, color=st.FUEL["nuclear"], linewidth=0)
    ax.set_yticks(y, hi.index, fontsize=5.5)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.set_xlim(0, 1.02)
    ax.set_ylim(-0.7, len(hi) - 0.3)
    for c, name in MARK.items():
        if name and c in hi.index:
            ax.annotate(name, (lo[c], y[hi.index.get_loc(c)]), xytext=(-3, 0), textcoords="offset points", ha="right",
                        va="center", fontsize=6.5, color=st.TEXT)
    ax.set_title("(a) Nuclear: minimum to maximum output", loc="left")
    ax.set_xlabel("Share of installed capacity")

    rows = FLAT + list(PRICE)
    rng = np.random.default_rng(0)
    for i, carrier in enumerate(rows):
        yi = len(rows) - 1 - i
        if carrier in PRICE:
            v = table(a.envelope, carrier, "p_max_pu")
            bx.scatter([v], [yi], s=30, color=st.FUEL[carrier], linewidth=0, zorder=3)
            bx.annotate(f"{v:.2f} everywhere, no minimum", (v, yi), xytext=(-6, 0), textcoords="offset points",
                        ha="right", va="center", fontsize=6.5, color=st.TICK)
            continue
        v = table(a.envelope, carrier, "p_max_pu", modelled)
        gw = np.array([cap.get((c, carrier), 0.0) for c in v.index])
        bx.scatter(v.values, yi + rng.uniform(-0.28, 0.28, len(v)), s=4 + 60 * np.sqrt(gw / max(gw.max(), 1e-9)),
                   color=st.FUEL[carrier], alpha=0.75, linewidth=0, zorder=3)
        bx.annotate(f"{len(v)} countries", (1.0, yi + 0.42), ha="right", fontsize=6, color=st.TICK)
    bx.set_yticks(range(len(rows)), [PRICE.get(r, r) for r in rows][::-1])
    bx.grid(axis="y", visible=False)
    bx.grid(axis="x", visible=True)
    bx.set_xlim(0, 1.02)
    bx.set_ylim(-0.6, len(rows) - 0.3)
    bx.set_title("(b) Maximum output", loc="left")
    bx.set_xlabel("Share of installed capacity")

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
