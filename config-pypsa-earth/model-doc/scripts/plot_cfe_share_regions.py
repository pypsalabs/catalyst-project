"""The 24/7 CFE buyers' share of demand in the modelled regions: its two parts in 2030 and its path to 2050 (Demand for 24/7 CFE).

Left: per archetype region, the countries of North-West Europe and the one-node test regions, the share of 2030 split
into data centres and the part of the other electricity use of RE100 members that is counted; the line marks the uniform
1 % used before. Right: the share per horizon for the archetype regions (demand-weighted over a region's countries)
against the uniform path used before. Reads calibration/<year>/cfe_share.csv and demand.csv.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_cfe_share_regions.py
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
STUDY = TOP.parent
sys.path.insert(0, str(TOP / "scripts"))
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402
from plot_cfe_datacentres import end_labels  # noqa: E402

HORIZONS = [2030, 2035, 2040, 2045, 2050]
REGIONS = {"United States": ["US"], "China": ["CN"], "India": ["IN"], "Brazil": ["BR"], "Singapore": ["SG"],
           "North-West Europe": ["IE", "GB", "FR", "BE", "NL", "LU", "DE", "DK", "CH", "AT", "CZ", "PL"]}
TESTS = {"Japan": ["JP"], "New Zealand": ["NZ"], "South Africa": ["ZA"], "Morocco": ["MA"]}
COLOUR = {"United States": st.BLUE, "China": st.VERMILLION, "India": st.ORANGE, "Brazil": st.GREEN,
          "Singapore": st.PINK, "North-West Europe": st.SKY}
BEFORE = {2030: 0.01, 2050: 0.10}      # the uniform share used until 2026-11-19
DC, RE = st.BLUE, st.ORANGE


def tables(calibration):
    out = {}
    for y in HORIZONS:
        t = pd.read_csv(Path(calibration) / str(y) / "cfe_share.csv", keep_default_na=False).set_index("country")
        t["demand"] = pd.read_csv(Path(calibration) / str(y) / "demand.csv", keep_default_na=False).set_index("country").demand_twh
        out[y] = t
    return out


def weighted(t, countries, col):
    t = t.loc[countries]
    return 100 * (t[col] * t.demand).sum() / t.demand.sum()


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--calibration", default=STUDY / "calibration")
    p.add_argument("--names", default=STUDY / "data/row_countries.csv")
    p.add_argument("--out", default=TOP / "build/figures/cfe_share_regions.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--calibration", str(Path(snakemake.input.tables[0]).parents[1]), "--names", snakemake.input.names,
                          "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    t = tables(a.calibration)
    first = t[HORIZONS[0]]
    names = pd.read_csv(a.names, keep_default_na=False).set_index("iso2").name.replace(
        {"United Kingdom of Great Britain and Northern Ireland": "United Kingdom"})
    nwe = sorted(REGIONS["North-West Europe"], key=lambda c: -first.share[c])
    rows = ([(r, c, True) for r, c in REGIONS.items()] + [("   " + names.get(c, c), [c], False) for c in nwe]
            + [(r, c, True) for r, c in TESTS.items()])
    gaps = {len(REGIONS) + len(nwe)}             # a gap before the test regions

    st.use()
    fig = plt.figure(figsize=(6.3, 4.1), layout="none")
    ax = fig.add_axes([0.2, 0.1, 0.34, 0.82])
    bx = fig.add_axes([0.625, 0.1, 0.165, 0.82])

    y, ypos = 0.0, []
    for i in range(len(rows)):
        y -= 1.45 if i in gaps else 1.0
        ypos.append(y)
    for (label, countries, bold), yy in zip(rows, ypos):
        total, dc = weighted(first, countries, "share"), weighted(first, countries, "datacentres")
        ax.barh(yy, dc, height=0.62, color=DC, linewidth=0)
        ax.barh(yy, total - dc, left=dc, height=0.62, color=RE, linewidth=0)
        cap = " (capped)" if len(countries) == 1 and str(first.capped[countries[0]]) == "True" else ""
        ax.text(total, yy, f" {total:.1f}{cap}", va="center", ha="left", fontsize=6.5, color=st.TEXT)
        ax.text(-0.6, yy, label.strip(), va="center", ha="right", fontsize=7 if bold else 6.5,
                color=st.TEXT if bold else st.TICK, fontweight="bold" if bold else "regular")
    ax.axvline(100 * BEFORE[2030], color=st.TEXT, linewidth=0.7, linestyle=(0, (2, 2)))
    ax.annotate("uniform 1 % before", (100 * BEFORE[2030], ypos[0] + 0.75), xytext=(3, 0), textcoords="offset points",
                fontsize=6.5, color=st.TICK, va="center")
    ax.set_yticks([])
    ax.set_ylim(ypos[-1] - 0.7, ypos[0] + 1.1)
    ax.set_xlim(0, 1.12 * max(weighted(first, c, "share") for _, c, _ in rows))
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.tick_params(labelsize=7)
    ax.set_title("24/7 CFE buyers in 2030, % of demand", loc="left", fontsize=8.5, x=-0.52)
    st.legend_squares(ax, [(DC, "data centres"), (RE, "RE100 members, other use (half)")], loc="lower right", fontsize=6.5)

    for r, countries in REGIONS.items():
        v = [weighted(t[y], countries, "share") for y in HORIZONS]
        bx.plot(HORIZONS, v, color=COLOUR[r], linewidth=1.4, marker="o", markersize=2.5)
    before = np.interp(HORIZONS, list(BEFORE), [100 * v for v in BEFORE.values()])
    bx.plot(HORIZONS, before, color=st.NEUTRAL, linewidth=1.4, linestyle=(0, (4, 1.6)))
    bx.set_ylim(0, None)
    end_labels(bx, HORIZONS[-1], [(f"{r} {weighted(t[HORIZONS[-1]], c, 'share'):.1f}", weighted(t[HORIZONS[-1]], c, "share"),
                                   COLOUR[r]) for r, c in REGIONS.items()] + [("uniform, before 10.0", before[-1], st.TICK)],
               0.055, 2.2)
    bx.set_xlim(HORIZONS[0], HORIZONS[-1])
    bx.set_xticks(HORIZONS[::2])
    bx.tick_params(labelsize=7)
    bx.set_title("Path to 2050, % of demand", loc="left", fontsize=8.5)

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print({r: round(weighted(first, c, "share"), 2) for r, c in {**REGIONS, **TESTS}.items()}, f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
