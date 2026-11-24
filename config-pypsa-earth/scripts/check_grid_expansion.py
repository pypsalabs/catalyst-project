# SPDX-License-Identifier: CC0-1.0
"""
The cap on grid build-out in solved networks: allowance, what was built, whether the cap binds.

Read-only. For every solved network given (or found for the stages given), the transmission volume (capacity x length
of AC lines and HVDC links) of the existing grid and after the optimisation, the limit of the global constraint
`lv_limit` (fork option lines: expansion_limit, set from data/grid_expansion/grid_expansion.csv by merge_config.py)
and its shadow price. Writes model-doc/build/grid_expansion/solved.csv.

Usage (from config-pypsa-earth):
    ../models/pypsa-earth/.pixi/envs/default/bin/python scripts/check_grid_expansion.py IN-zero NWE-zero [path.nc ...]
"""
import glob
import logging
import os
import sys
import warnings

import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORK = os.path.join(HERE, "..", "models", "pypsa-earth")
OUT = os.path.join(HERE, "model-doc", "build", "grid_expansion")


def networks(arg):
    if arg.endswith(".nc"):
        return [arg]
    return sorted(glob.glob(os.path.join(FORK, "results", arg, "networks", "*.nc")))


def row(fn):
    import pypsa

    n = pypsa.Network(fn)
    dc = n.links[n.links.carrier == "DC"]
    ac0, ac1 = n.lines.s_nom @ n.lines.length, n.lines.s_nom_opt @ n.lines.length
    dc0, dc1 = dc.p_nom @ dc.length, dc.p_nom_opt @ dc.length
    out = {"network": os.path.relpath(fn, FORK), "ac_twkm": ac0 / 1e6, "hvdc_twkm": dc0 / 1e6,
           "ac_built_x": ac1 / ac0 if ac0 else float("nan"), "hvdc_built_x": dc1 / dc0 if dc0 else float("nan"),
           "built_x": (ac1 + dc1) / (ac0 + dc0), "ac_built_gw": (n.lines.s_nom_opt - n.lines.s_nom).sum() / 1e3,
           "hvdc_built_gw": (dc.p_nom_opt - dc.p_nom).sum() / 1e3, "objective_bn": n.objective / 1e9}
    if "lv_limit" in n.global_constraints.index:
        g = n.global_constraints.loc["lv_limit"]
        out.update(allowed_x=g.constant / (ac0 + dc0), shadow_price=g.mu, binds=bool(ac1 + dc1 >= 0.999 * g.constant))
    return out


def main():
    warnings.filterwarnings("ignore")
    logging.getLogger("pypsa").setLevel(logging.ERROR)
    files = [f for a in sys.argv[1:] for f in networks(a)]
    if not files:
        sys.exit(__doc__)
    t = pd.DataFrame([row(f) for f in files])
    os.makedirs(OUT, exist_ok=True)
    t.round(4).to_csv(os.path.join(OUT, "solved.csv"), index=False)
    pd.set_option("display.width", 250)
    print(t.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
