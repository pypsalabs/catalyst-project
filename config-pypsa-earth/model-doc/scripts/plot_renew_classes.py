"""Resource classes of onshore wind: the potential by capacity factor, and where the fleet stands (Renewables & Weather).

(a) US onshore wind potential sorted from the best to the worst capacity factor: one generator per cluster region
    (networks/US-now/elec_s_50.nc) against five class generators per region (elec_s_50_ec.nc).
(b) Share of the installed onshore wind of each spatially resolved region in each of the five classes of its cluster
    region (class 1 = lowest capacity factors of the region, class 5 = highest).
Reads build/renewables_check/classes.csv, written by ../scripts/check_renewables.py (read-only, no model rerun).

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_renew_classes.py
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

REGIONS = {"US": "US", "BR": "Brazil", "IN": "India", "CN": "China", "NWE": "NW Europe"}
SHADES = ["#d6e6f2", "#a9cbe4", "#73a9d0", "#3d86bb", st.BLUE]   # class 1 (lowest capacity factors) .. class 5
STAGE, CARRIER = "US", "onwind"


def curve(gw, cf):
    """Step curve of capacity factor over cumulative potential, best first."""
    order = np.argsort(-cf)
    edges = np.concatenate([[0], np.cumsum(gw[order])])
    return edges, cf[order]


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--classes", default=TOP / "build/renewables_check/classes.csv")
    p.add_argument("--out", default=TOP / "build/figures/renew_classes.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--classes", snakemake.input.classes, "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    d = pd.read_csv(a.classes)
    d = d[d.carrier == CARRIER]
    u = d[d.stage == STAGE]
    single = u.drop_duplicates("bus")

    st.use()
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(6.3, 3.0), width_ratios=[1.25, 1])
    e, c = curve(single.single_potential_gw.values / 1e3, single.single_cf.values)
    ax.stairs(c, e, color=st.FAINT, linewidth=1.3, baseline=None, label=f"one generator per region ({len(single)})")
    k = u[u.model_potential_gw > 0]
    e, c = curve(k.model_potential_gw.values / 1e3, k.model_cf.values)
    ax.stairs(c, e, color=st.BLUE, linewidth=1.3, baseline=None, label=f"five classes per region ({len(k)})")
    ax.set_xlim(0, e[-1])
    ax.set_ylim(0, 0.55)
    ax.set_xlabel("Potential, cumulative from the best site, TW")
    ax.set_ylabel("Capacity factor")
    ax.set_title("(a) US onshore wind potential", loc="left", fontsize=8.5)
    ax.legend(loc="upper right", fontsize=7)

    share = d.groupby(["stage", "class"]).model_fleet_gw.sum().unstack().reindex(list(REGIONS))
    share = share.div(share.sum(axis=1), axis=0) * 100
    y = np.arange(len(REGIONS))[::-1]
    left = np.zeros(len(REGIONS))
    for k_, colour in enumerate(SHADES):
        v = share[k_].values
        bx.barh(y, v, left=left, height=0.62, color=colour, linewidth=0)
        for yi, li, vi in zip(y, left, v):
            if vi >= 8:
                bx.text(li + vi / 2, yi, f"{vi:.0f}", ha="center", va="center", fontsize=6.5, color="white" if k_ >= 3 else st.TEXT)
        left += v
    bx.set_yticks(y, list(REGIONS.values()))
    bx.set_xlim(0, 100)
    bx.grid(axis="y", visible=False)
    bx.set_xlabel("Share of installed onshore wind, %")
    bx.set_title("(b) Class in which the fleet stands", loc="left", fontsize=8.5)
    st.legend_squares(bx, [(c_, f"{i + 1}") for i, c_ in enumerate(SHADES)], loc="upper center", bbox_to_anchor=(0.5, -0.24),
                      ncol=5, fontsize=6.5, columnspacing=1.0, title="Class of the region (5 = best)", title_fontsize=6.5)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(share.round(1).to_string(), f"\n-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
