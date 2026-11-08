"""Two HVDC entries of OpenStreetMap: one whose name can be matched to a project, one where it cannot (Grid Data, adjustments).

Real tags of two +-800 kV ways in resources/CN/osm/raw/all_raw_lines.csv, each with its route on a map. Tags in Chinese script are
left out because the plot font lacks them: the first way also has name = its Chinese name.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_osm_entries.py
"""

import argparse
import ast
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(snakemake.scriptdir) if "snakemake" in globals() else Path(__file__).resolve().parent
TOP = HERE.parent
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import iconstyle as ic  # noqa: E402

FORK = TOP / "../../models/pypsa-earth"
COUNTRIES = TOP / "../../misc-quarter1/country-classification/data/ne_50m_admin_0_countries/ne_50m_admin_0_countries.shp"
MATCHED = (626927231, 616665124)   # HVDC Xilin Hot - Taizhou
UNMATCHED = (1485073621,)
SHOW = ["power", "voltage", "frequency", "cables", "wires", "name:en", "note"]


def tags_of(row):
    extra = json.loads(row.other_tags) if isinstance(row.other_tags, str) else {}
    out = {}
    for key in SHOW:
        value = row.get(f"tags.{key}", np.nan)
        if pd.isna(value):
            value = extra.get(f"tags.{key}")
        if value is not None:
            out[key] = str(value).removesuffix(".0")
    return out


def card(ax, way, tags, verdict, ok):
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.text(0, 0.98, f"way {way}", fontsize=7.5, color=ic.INK, va="top", fontweight=ic.EMPH)
    y = 0.86
    for key, value in tags.items():
        strong = key == "name:en"
        ax.text(0.0, y, key, fontsize=6.8, family="monospace", color=ic.MUTED if hasattr(ic, "MUTED") else ic.INK, va="top")
        ax.text(0.24, y, value, fontsize=6.8, family="monospace", color=ic.INK, va="top", fontweight="bold" if strong else "normal")
        y -= 0.1
    if not ok:
        ax.text(0.0, y, "name:en", fontsize=6.8, family="monospace", color=ic.RED, va="top")
        ax.text(0.24, y, "(none)", fontsize=6.8, family="monospace", color=ic.RED, va="top", fontweight="bold")
    ax.text(0, 0.0, verdict, fontsize=7, color=ic.INK, va="bottom", linespacing=1.3)


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--raw", default=FORK / "resources/CN/osm/raw/all_raw_lines.csv")
    p.add_argument("--countries", default=COUNTRIES)
    p.add_argument("--out", default=TOP / "build/figures/osm_entries.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--raw", str(snakemake.input.raw), "--countries", str(snakemake.input.countries), "--out", str(snakemake.output[0])])
    else:
        a = p.parse_args()

    raw = pd.read_csv(a.raw, low_memory=False)
    dc = raw[pd.to_numeric(raw["tags.frequency"], errors="coerce").eq(0) & (pd.to_numeric(raw["tags.voltage"], errors="coerce") >= 200000)]
    path = lambda row: np.array(ast.literal_eval(row.lonlat))
    china = gpd.read_file(a.countries)
    china = china[china.ISO_A2_EH == "CN"]

    ic.use()
    fig = plt.figure(figsize=(6.3, 4.0))
    grid = fig.add_gridspec(2, 2, height_ratios=[1.15, 1], left=0.02, right=0.98, top=0.93, bottom=0.02, wspace=0.1, hspace=0.04)
    cases = [(MATCHED, ic.BLUE, "(a) The name can be matched", True,
              "Name found in the project table:\nXilin Hot - Taizhou, 10 GW, 1,620 km"),
             (UNMATCHED, ic.AMBER, "(b) The name cannot be matched", False,
              "No name, so no row to look up:\nonly voltage and geometry are known")]
    for k, (ids, colour, title, ok, verdict) in enumerate(cases):
        ax = fig.add_subplot(grid[0, k])
        china.plot(ax=ax, color=ic.PALE, edgecolor=ic.STEEL, linewidth=0.4, zorder=1)
        for _, row in dc.iterrows():
            xy = path(row)
            ax.plot(xy[:, 0], xy[:, 1], color=ic.STEEL, lw=0.35, zorder=2)
        for _, row in dc[dc.id.isin(ids)].iterrows():
            xy = path(row)
            ax.plot(xy[:, 0], xy[:, 1], color=colour, lw=2.0, solid_capstyle="round", zorder=3)
        ax.set_xlim(73, 135)
        ax.set_ylim(18, 54)
        ax.set_aspect(1.25)
        ax.set_axis_off()
        ax.set_title(title, loc="left", fontsize=7.5, pad=2)
        first = dc[dc.id == ids[0]].iloc[0]
        card(fig.add_subplot(grid[1, k]), ids[0], tags_of(first), verdict, ok)

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=300)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
