"""World map of the weather cutouts the runs read (Renewables & Weather, standard procedure).

One rectangle per cutout file (its longitude / latitude box), coloured by where the file comes from and labelled with the
runs that read it; the modelled countries shaded. Drawn in plain longitude / latitude, in which the boxes are rectangles.
Reads build/renewables_check/cutouts.csv, written by ../scripts/check_renewables.py (read-only, no model rerun).

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_renew_cutouts.py
"""

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Rectangle

TOP = Path(__file__).resolve().parents[1]
STUDY = TOP.parent
sys.path.insert(0, str(TOP / "scripts"))
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402
from plot_grid_map import ALIASES, COUNTRIES, NAMES, classify  # noqa: E402

RUNS = {"US": "US", "BR": "Brazil", "IN": "India", "CN": "China", "NWE": "Europe", "SG": "Singapore", "IS": "Iceland",
        "CA": "North America", "RU": "Russia", "OCE": "Oceania", "NAM": "North America", "SAM": "South America",
        "MEA": "Middle East", "EUR": "Europe", "AFR": "Africa", "ASI": "Asia"}
# where a file that the workflow did not build comes from (the configs' comments on enable: build_cutout)
PREBUILT = {"europe-2013-sarah3-era5": "eur", "cutout-2013-era5-china": "cut"}
ORIGIN = {"built": (st.VERMILLION, "built for this project (ERA5)"),
          "earth": (st.BLUE, "prebuilt by PyPSA-Earth (ERA5)"),
          "eur": (st.GREEN, "prebuilt by PyPSA-Eur (ERA5, solar radiation from SARAH-3)"),
          "cut": (st.ORANGE, "cut out of PyPSA-Earth's file for Asia (ERA5)")}
# label anchor per cutout: corner of its box (default upper left, inside)
ANCHOR = {"cutout-2013-era5-asia": ("right", "bottom"), "cutout-2013-era5-oceania": ("right", "bottom"),
          "cutout-2013-era5-westasia": ("left", "bottom"), "cutout-2013-era5-china": ("right", "top"),
          "cutout-2013-era5-india": ("left", "bottom"), "cutout-2013-era5-conus": ("left", "bottom"),
          "cutout-2013-era5-singapore": ("left", "above"), "cutout-2013-era5-iceland": ("left", "above"),
          "europe-2013-sarah3-era5": ("left", "bottom"), "cutout-2013-era5-africa": ("left", "bottom")}


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--cutouts", default=TOP / "build/renewables_check/cutouts.csv")
    p.add_argument("--row-countries", default=STUDY / "data/row_countries.csv")
    p.add_argument("--configs", default=STUDY)
    p.add_argument("--countries", default=COUNTRIES)
    p.add_argument("--out", default=TOP / "build/figures/renew_cutouts.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--cutouts", snakemake.input.cutouts, "--row-countries", snakemake.input.row_countries,
                          "--configs", str(Path(snakemake.input.configs[0]).parent), "--countries", snakemake.input.countries,
                          "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    d = pd.read_csv(a.cutouts)
    d["origin"] = [PREBUILT.get(c, "built" if b else "earth") for c, b in zip(d.cutout, d.build_cutout)]
    modelled, _ = classify(a.row_countries, Path(a.configs))
    world = gpd.read_file(a.countries)
    world = world[world.CONTINENT != "Antarctica"]
    world["iso"] = world.ISO_A2_EH.where(world.ISO_A2_EH != "-99", world.NAME.map(NAMES)).replace(ALIASES)

    st.use()
    fig = plt.figure(figsize=(6.3, 3.45), layout="none")
    ax = fig.add_axes([0.0, 0.13, 1.0, 0.87])
    st.map_axes(ax)
    world[~world.iso.isin(modelled)].plot(ax=ax, color=st.LAND, edgecolor="white", linewidth=0.25)
    world[world.iso.isin(modelled)].plot(ax=ax, color="#d2d2d2", edgecolor="white", linewidth=0.25)
    ax.set_xlim(-180, 180)
    ax.set_ylim(-62, 84)
    ax.set_aspect(1.25)
    boxes = d.drop_duplicates("cutout").assign(area=lambda t: (t.x1 - t.x0) * (t.y1 - t.y0)).sort_values("area", ascending=False)
    for _, r in boxes.iterrows():
        colour = ORIGIN[r.origin][0]
        h = r.dx / 2
        x0, x1, y0, y1 = r.x0 - h, r.x1 + h, r.y0 - h, r.y1 + h
        small = (x1 - x0) < 4
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor=colour, linewidth=0.9, zorder=5))
        runs = list(dict.fromkeys(RUNS[s] for s in d.stage[d.cutout == r.cutout]))
        ha, va = ANCHOR.get(r.cutout, ("left", "top"))
        x = x0 + 1.2 if ha == "left" else x1 - 1.2
        y = {"top": y1 - 1.5, "bottom": y0 + 1.5, "above": y1 + 1.5}[va]
        ax.text(x, y, ", ".join(runs), ha=ha, va={"top": "top", "bottom": "bottom", "above": "bottom"}[va], fontsize=6,
                color=colour, fontweight="bold", zorder=6,
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.75, pad=0.6) if not small else None)
    lax = fig.add_axes([0.0, 0.0, 1.0, 0.12])
    lax.set_axis_off()
    handles = [plt.Line2D([], [], color=c, linewidth=1.2) for c, _ in ORIGIN.values()]
    handles.append(plt.Rectangle((0, 0), 1, 1, color="#d2d2d2", linewidth=0))
    lax.legend(handles, [label for _, label in ORIGIN.values()] + ["modelled countries"], loc="center", ncol=2, fontsize=6.5,
               handlelength=1.4, columnspacing=1.6)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=220)
    print(boxes[["cutout", "origin", "x0", "x1", "y0", "y1"]].to_string(index=False), f"\n-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
