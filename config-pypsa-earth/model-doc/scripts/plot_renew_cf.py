"""Model against observed capacity factor of the wind and solar fleets, per country (Renewables & Weather).

One panel per group (wind = onshore and offshore, solar). x: the model capacity factor before the scaling = capacity factor of the
installed fleet with the profiles of build_renewable_profiles (ERA5 weather of 2013); y: the observed capacity factor of 2024 (calibration/2024/generation.csv);
marker area: fleet GW. The band is the range the profiles may be scaled by (electricity: capacity_factor_targets: clip);
countries outside it keep a gap after the scaling. Reads build/renewables_check/cf.csv, written by
../scripts/check_renewables.py (read-only, no model rerun).

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_renew_cf.py
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

CLIP = (0.6, 1.4)          # electricity: capacity_factor_targets: clip (fork default, not changed by the project)
GROUPS = {"wind": ("Wind", 0.55, st.BLUE), "solar": ("Solar", 0.32, st.BLUE)}
LABELS = {"wind": 12, "solar": 6}   # the largest fleets are labelled
SIZE_GW = {"wind": [10, 100, 500], "solar": [10, 100, 500]}
SCALE = 0.55               # marker area in points^2 per GW


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--cf", default=TOP / "build/renewables_check/cf.csv")
    p.add_argument("--out", default=TOP / "build/figures/renew_cf.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--cf", snakemake.input.cf, "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    d = pd.read_csv(a.cf)
    d = d[d.cf_target.notna() & (d.cf_target > 0) & (d.cf_raw > 0)]
    d["out"] = (d.factor_needed < CLIP[0]) | (d.factor_needed > CLIP[1])

    st.use()
    fig, axes = plt.subplots(1, 2, figsize=(6.3, 3.3))
    for ax, (group, (label, top, colour)) in zip(axes, GROUPS.items()):
        g = d[d.group == group].sort_values("gw", ascending=False)
        x = np.array([0, top])
        ax.fill_between(x, CLIP[0] * x, CLIP[1] * x, color="#efefef", linewidth=0, zorder=0)
        ax.plot(x, x, color=st.FAINT, linewidth=0.8, zorder=1)
        inside = g[~g.out]
        outside = g[g.out]
        ax.scatter(inside.cf_raw, inside.cf_target, s=inside.gw * SCALE + 3, color=colour, alpha=0.75, linewidths=0.3,
                   edgecolors="white", zorder=3)
        ax.scatter(outside.cf_raw, outside.cf_target.clip(upper=top), s=outside.gw * SCALE + 3, color=st.VERMILLION, alpha=0.85,
                   linewidths=0.3, edgecolors="white", zorder=4)
        for _, r in g.head(LABELS[group]).iterrows():
            if r.cf_target <= top:
                ax.annotate(r.country, (r.cf_raw, r.cf_target), xytext=(0, 0.5 * np.sqrt(r.gw * SCALE + 3) + 1.5),
                            textcoords="offset points", ha="center", va="bottom", fontsize=6, color=st.TEXT, zorder=5)
        ax.set_xlim(0, top)
        ax.set_ylim(0, top)
        ax.set_aspect("equal")
        ax.set_xlabel("Model capacity factor, before the scaling")
        ax.set_ylabel("Observed capacity factor, 2024")
        ax.set_title(label, loc="left", fontsize=8.5)
        ax.annotate("factor 1.4", (top / 1.4 * 0.98, top * 0.98), ha="right", va="top", fontsize=6, color=st.TICK, rotation=0)
        ax.annotate("factor 0.6", (top * 0.98, top * 0.6 * 0.98), ha="right", va="top", fontsize=6, color=st.TICK)
        hidden = int((g.cf_target > top).sum())
        n_out, gw_out = int(g.out.sum()), g.gw[g.out].sum()
        ax.annotate(f"{len(g)} countries, {g.gw.sum():,.0f} GW\noutside the band: {n_out}, {gw_out:,.0f} GW",
                    (0.03, 0.97), xycoords="axes fraction", va="top", fontsize=6.5, color=st.TICK)
        handles = [plt.scatter([], [], s=v * SCALE + 3, color="#9a9a9a", linewidths=0) for v in SIZE_GW[group]]
        ax.legend(handles, [f"{v} GW" for v in SIZE_GW[group]], loc="lower right", fontsize=6.5, labelspacing=0.9,
                  borderpad=0.6, handletextpad=0.8)
        print(group, len(g), "outside", n_out, round(gw_out, 1), "GW; above the axis:", hidden)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
