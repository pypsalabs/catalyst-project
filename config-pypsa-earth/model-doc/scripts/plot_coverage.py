"""Coverage of the model: world map of the modelled countries and their share of world electricity demand (first figure
of the Model section).

Left, a world map: countries spatially resolved (several nodes), modelled as one node, or not modelled; the classes come
from plot_grid_map.classify (data/row_countries.csv and the stage configs), with the parts of a country outside its
stage's clip box drawn as not modelled. Right, a bar per class: its share of world electricity demand in 2024, from the
Ember demand column of data/row_countries.csv (all 214 countries and territories of Ember's yearly data).

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_coverage.py [--out build/figures/coverage.pdf]
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(snakemake.scriptdir) if "snakemake" in globals() else Path(__file__).resolve().parent
TOP = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import iconstyle as ic  # noqa: E402
from plot_grid_map import COUNTRIES, STUDY, classify, world_by_class  # noqa: E402

CLASSES = [  # key, colour, label (map legend and bar axis)
    ("resolved", ic.BLUE, "spatially resolved"),
    ("one", ic.TEAL, "one node"),
    ("none", "white", "not modelled"),
]


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--row-countries", default=STUDY / "data/row_countries.csv")
    p.add_argument("--configs", default=STUDY)
    p.add_argument("--countries", default=COUNTRIES)
    p.add_argument("--out", default=TOP / "build/figures/coverage.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--row-countries", snakemake.input.row_countries,
                          "--configs", str(Path(snakemake.input.configs[0]).parent),
                          "--countries", snakemake.input.countries, "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    grid, boxes = classify(a.row_countries, Path(a.configs))
    coverage = {c: "one" if g == "one" else "resolved" for c, g in grid.items()}
    world = world_by_class(a.countries, coverage, boxes)

    rc = pd.read_csv(a.row_countries, keep_default_na=False)
    demand = pd.to_numeric(rc.demand_twh, errors="coerce").fillna(0.0)
    share = demand.groupby(rc.iso2.map(coverage).fillna("none")).sum() / demand.sum() * 100

    ic.use()
    fig = plt.figure(figsize=(6.3, 2.75))
    ax = fig.add_axes([0.0, 0.10, 0.74, 0.90])
    ax.set_axis_off()
    for key, colour, _ in CLASSES:
        part = world[world.grid == key]
        part.plot(ax=ax, color=colour, edgecolor=ic.INK if key != "none" else ic.STEEL,
                  linewidth=0.32 if key != "none" else 0.25)
    x0, y0, x1, y1 = world.total_bounds
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    counts = pd.Series(coverage).value_counts()
    lax = fig.add_axes([0.0, 0.0, 0.74, 0.08])
    lax.set_axis_off()
    ic.legend_squares(lax, [(c, f"{lab} ({counts[k]} countries)" if k in counts else lab) for k, c, lab in CLASSES],
                      on_title_line=False, loc="center", anchor=(0.5, 0.5))

    bx = fig.add_axes([0.80, 0.24, 0.19, 0.62])
    keys = [k for k, _, _ in CLASSES]
    ic.bars(bx, range(len(keys)), [share.get(k, 0.0) for k in keys], color=[c for _, c, _ in CLASSES], width=0.66,
            fmt="{:.1f} %")
    bx.set_xticks(range(len(keys)), ["spatially\nresolved", "one\nnode", "not\nmodelled"], fontsize=6.8)
    bx.set_ylim(0, 100)
    bx.set_yticks([0, 25, 50, 75, 100])
    bx.set_title("Share of world\nelectricity demand, %", fontsize=7.4)
    bx.set_xlim(-0.6, len(keys) - 0.4)
    ic.ground(bx)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=300)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(share.round(2).to_dict(), f"world {demand.sum():,.0f} TWh -> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
