"""World maps of the model capacity factor of the wind and solar fleets relative to the observed one (Renewables & Weather).

Per modelled country and for wind (onshore and offshore together) and solar: the model capacity factor = the capacity
factor of the installed fleet with the profiles as build_renewable_profiles writes them (ERA5 weather of 2013, before
any adjustment of the fork), over the capacity factor observed in 2024 (calibration/2024/generation.csv). Right of each map: the fleet GW per class. Reads
build/renewables_check/cf.csv, written by ../scripts/check_renewables.py (read-only, no model rerun); country shapes,
clip boxes and the not-modelled countries as in the grid map (plot_grid_map.py).

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_renew_map.py
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
from plot_grid_map import COUNTRIES, classify, world_by_class  # noqa: E402

# key, upper bound of modelled / observed capacity factor, colour, label. The outer bounds are those of the clip of
# electricity: capacity_factor_targets (factor 0.6 .. 1.4 on the profile = ratio 1/0.6 .. 1/1.4)
CLASSES = [
    ("low2", 1 / 1.4, "#b2182b", "model below 0.71 × observed"),
    ("low", 0.9, "#f4a582", "model 10–29 % below observed"),
    ("ok", 1.1, "#bdbdbd", "model within ±10 % of observed"),
    ("high", 1 / 0.6, "#92c5de", "model 10–67 % above observed"),
    ("high2", np.inf, "#2166ac", "model above 1.67 × observed"),
]
NONE = ("nofleet", "#f6f1e3", "no fleet or no observed value")
GROUPS = {"wind": "Wind", "solar": "Solar"}


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--cf", default=TOP / "build/renewables_check/cf.csv")
    p.add_argument("--row-countries", default=STUDY / "data/row_countries.csv")
    p.add_argument("--configs", default=STUDY)
    p.add_argument("--countries", default=COUNTRIES)
    p.add_argument("--out", default=TOP / "build/figures/renew_map.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--cf", snakemake.input.cf, "--row-countries", snakemake.input.row_countries,
                          "--configs", str(Path(snakemake.input.configs[0]).parent), "--countries", snakemake.input.countries,
                          "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    d = pd.read_csv(a.cf)
    d = d[d.cf_target.notna() & (d.cf_target > 0) & (d.cf_raw > 0)]
    d["ratio"] = d.cf_raw / d.cf_target
    d["cls"] = pd.cut(d.ratio, [0] + [c[1] for c in CLASSES], labels=[c[0] for c in CLASSES], right=False).astype(str)
    grid, boxes = classify(a.row_countries, Path(a.configs))

    st.use()
    fig = plt.figure(figsize=(6.3, 5.5), layout="none")
    for i, (group, label) in enumerate(GROUPS.items()):
        g = d[d.group == group].set_index("country")
        world = world_by_class(a.countries, {c: g.cls.get(c, NONE[0]) for c in grid}, boxes)
        ax = fig.add_axes([0, 0.545 - 0.445 * i, 0.72, 0.415])
        st.map_axes(ax)
        world[world.grid == "none"].plot(ax=ax, color=st.LAND, edgecolor="white", linewidth=0.3)
        for key, colour in [(NONE[0], NONE[1])] + [(c[0], c[2]) for c in CLASSES]:
            part = world[world.grid == key]
            if len(part):
                part.plot(ax=ax, color=colour, edgecolor="white", linewidth=0.3)
        ax.set_aspect("equal")
        x0, y0, x1, y1 = world.total_bounds
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        fleet = (g.cf_raw * g.gw).sum() / g.gw.sum(), (g.cf_target * g.gw).sum() / g.gw.sum()
        ax.set_title(f"{label}: model capacity factor relative to the observed capacity factor", loc="left", fontsize=8.5)

        bx = fig.add_axes([0.80, 0.60 - 0.445 * i, 0.18, 0.27])
        gw = g.gw.groupby(g.cls).sum().reindex([c[0] for c in CLASSES]).fillna(0.0)
        y = np.arange(len(CLASSES))[::-1]
        bx.barh(y, gw.values, height=0.7, color=[c[2] for c in CLASSES], linewidth=0)
        for yi, v, n in zip(y, gw.values, g.cls.value_counts().reindex([c[0] for c in CLASSES]).fillna(0).astype(int)):
            bx.annotate(f"{v:,.0f}  ({n})", (v, yi), xytext=(3, 0), textcoords="offset points", va="center", fontsize=6.5, color=st.TEXT)
        bx.set_yticks([])
        bx.grid(axis="y", visible=False)
        bx.set_xlim(0, gw.max() * 1.55)
        bx.tick_params(axis="x", labelsize=6.5)
        bx.set_title("Fleet, GW (countries)", loc="left", fontsize=8)
        bx.annotate(f"all countries: model {fleet[0]:.3f},\nobserved {fleet[1]:.3f}", (0, -0.22), xycoords="axes fraction", va="top",
                    fontsize=6.5, color=st.TICK)
        print(group, gw.round(0).to_dict(), f"fleet {fleet[0]:.3f} observed {fleet[1]:.3f}")
    lax = fig.add_axes([0.0, 0.0, 0.72, 0.09])
    lax.set_axis_off()
    st.legend_squares(lax, [(c[2], c[3]) for c in CLASSES] + [(NONE[1], NONE[2]), (st.LAND, "not modelled")],
                      loc="center", ncol=3, fontsize=6.5, columnspacing=1.2)

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
