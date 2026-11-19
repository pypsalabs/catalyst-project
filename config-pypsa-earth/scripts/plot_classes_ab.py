#!/usr/bin/env python
"""
A/B figure of the resource classes (README "Resource classes"): pathways without and with classes.

    python scripts/plot_classes_ab.py <R> [ref:refrc cfenorc:cferc]

Reads the solved myopic networks results/<R>-<scen>/networks/*_<year>.nc of each pair (without:with) and writes
results/learning/<R>-classes/{classes_ab.png,pdf,csv}: onshore wind GW and its capacity factor, EGS GW, the
grid's load-weighted price, the 24/7 CFE premium. Study style.
"""

import glob
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent.parent
PE = HERE.parent / "models" / "pypsa-earth"
sys.path.insert(0, str(HERE.parent / "plotstyle"))


def summarise(stage):
    import pypsa

    logging.getLogger("pypsa").setLevel(logging.ERROR)
    rows = []
    for f in sorted(glob.glob(str(PE / f"results/{stage}/networks/*_20[3-9][05].nc"))):
        n = pypsa.Network(f)
        g, w = n.generators, n.snapshot_weightings.generators
        wind = g.index[g.carrier == "onwind"]
        cap = g.groupby("carrier").p_nom_opt.sum() / 1e3
        loads = n.loads.index[~n.loads.bus.str.endswith(" CFE")]
        ld = n.loads_t.p[loads].mul(w, axis=0)
        price = float((ld.values * n.buses_t.marginal_price[n.loads.bus[loads]].values).sum() / ld.values.sum())
        s = list((((n.meta or {}).get("cfe") or {}).get("summary") or {}).values())
        rows.append(dict(
            stage=stage, year=int(f[-7:-3]), onwind_gw=cap.get("onwind", 0.0), egs_gw=cap.get("egs", 0.0),
            solar_gw=cap.get("solar", 0.0),
            onwind_cf=float(n.generators_t.p[wind].mul(w, axis=0).sum().sum() / (g.loc[wind, "p_nom_opt"].sum() * w.sum())),
            price=price,   # premium: the buyers' mean, weighted by their load (was the first buyer's only)
            premium=float(np.average([b.get("premium_per_mwh", np.nan) for b in s],
                                     weights=[b["demand_twh"] for b in s])) if s else np.nan,
        ))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import matplotlib.pyplot as plt
    import studystyle as st

    region = sys.argv[1]
    pairs = [p.split(":") for p in (sys.argv[2:] or ["ref:refrc", "cfenorc:cferc"])]
    out = PE / f"results/learning/{region}-classes"
    out.mkdir(parents=True, exist_ok=True)
    t = pd.concat([summarise(f"{region}-{s}") for p in pairs for s in p], ignore_index=True)
    t.to_csv(out / "classes_ab.csv", index=False)

    st.use()
    colour = {0: st.NEUTRAL, 1: st.TECH["egs"]}
    panels = [("onwind_gw", "Onshore wind, GW"), ("onwind_cf", "Onshore wind, capacity factor"),
              ("egs_gw", "EGS, GW"), ("price", "Grid price, USD per MWh"), ("premium", "24/7 CFE premium, USD per MWh")]
    fig, axes = plt.subplots(1, len(panels), figsize=(3.0 * len(panels), 2.9))
    for ax, (col, title) in zip(axes, panels):
        for i, (a, b) in enumerate(pairs):
            for scen, ls in [(a, "--"), (b, "-")]:
                d = t[t.stage == f"{region}-{scen}"].sort_values("year")
                if d[col].isna().all():
                    continue
                ax.plot(d.year, d[col], ls=ls, color=colour[i % 2] if i < 2 else None, marker="o", ms=3, lw=1.6)
        ax.set_title(title, loc="left", fontsize=9)
        ax.set_xticks([2030, 2040, 2050])
        ax.set_ylim(bottom=0)
    st.legend_squares(axes[0], [(colour[0], f"no CFE ({pairs[0][0]})"), (colour[1], f"24/7 CFE ({pairs[1][0]})")])
    axes[-1].plot([], [], "k--", lw=1.2, label="one class per region")
    axes[-1].plot([], [], "k-", lw=1.2, label="5 resource classes")
    axes[-1].legend(frameon=False, loc="lower right", fontsize=7)
    fig.suptitle(f"{region}: pathways without (dashed) and with (solid) resource classes for onshore wind and solar",
                 x=0.01, ha="left", fontsize=10, fontweight="bold")
    for ext in ["png", "pdf"]:
        fig.savefig(out / f"classes_ab.{ext}", dpi=170)
    print(t.round(3).to_string(index=False))
    print(f"wrote {out / 'classes_ab.png'}")
