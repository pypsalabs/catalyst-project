"""Myopic learning loop for one isolated system (misc-quarter1/pareto).

Round 0 solves the least-cost clean system at the 2025 baseline costs. After every round the
capacity built — scaled by the factor that makes the system a stand-in for a share of world
demand (config `learning_base`) — is added to each component's global cumulative deployment
and Wright's law gives the capex of the next round (techs.learned_capex); the next round is a
fresh greenfield optimisation at those costs. Learning is local: the system learns only from
what it built. Site-specific technologies (EGS, hydrothermal) learn through a cost factor on
their tranche costs.

Output: build/loop/<dataset>/<i>.csv, one row per (round, component).

Standalone: python run_loop.py <dataset> <series index>
"""

import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

if "snakemake" in globals():  # Snakemake runs a copy of this file; make the sibling modules importable
    sys.path.insert(0, str(Path(snakemake.input.config).resolve().parent))  # noqa: F821
from build_network import load_series, make_network, solve, summarise
from techs import learned_capex, load_components, load_config, reference_base, site_tranches, world_scale, world_shares

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("loop")

if "snakemake" in globals():
    CFG = load_config(snakemake.input.config)  # noqa: F821
    DATASET = snakemake.wildcards.dataset  # noqa: F821
    I = int(snakemake.wildcards.i)  # noqa: F821
    OUT = Path(snakemake.output[0])  # noqa: F821
    CFG["solver"]["options"]["Threads"] = snakemake.threads  # noqa: F821
else:
    CFG = load_config()
    DATASET = sys.argv[1] if len(sys.argv) > 1 else "sites"
    I = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    OUT = CFG["_dir"] / "build" / "loop" / DATASET / f"{I}.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)


def run(cfg: dict, dataset: str, i: int) -> pd.DataFrame:
    comps = load_components(cfg)
    name, profile = load_series(cfg, dataset, i)
    tranches = site_tranches(cfg, dataset, name)
    load_twh = profile["demand_mw"].sum() / 1e6
    shares = world_shares(cfg)
    cref = reference_base(comps)
    cumulative = cref.copy()
    capex = comps["capex0"].copy()
    log.info("%s/%d = %s: %.1f TWh; the sub-system stands for %s of world demand per round (%s counting)",
             dataset, i, name, load_twh, " / ".join(f"{x * 100:.0f} %" for x in shares), cfg["learning_base"].get("counting", "increment"))
    for tech, t in tranches.items():
        log.info("%s: %s", tech, "; ".join(f"{r.tranche} {r.p_nom_max / 1e3:,.1f} GW" for r in t.itertuples()) if not t.empty else "none within radius")

    frames = []
    for step in range(cfg["steps"]):
        t0 = time.time()
        n = make_network(profile, comps, capex, cfg["discount_rate"], tranches)
        solve(n, cfg)
        df = summarise(n, comps, capex).set_index(["tech", "component"])
        scale = world_scale(cfg, load_twh, step)
        cumulative = cumulative + df["built"] * scale
        capex_next = pd.Series(learned_capex(comps["capex0"], cumulative, cref, comps["learning_rate"]), index=comps.index)
        df["built_world"] = df["built"] * scale
        df["cumulative"] = cumulative
        df["cref"] = cref
        df["scale"] = scale
        df["share_of_world"] = shares[step]
        df["capex_next"] = capex_next
        df["doublings"] = np.log2(cumulative / cref)
        df["step"] = step
        frames.append(df.reset_index())
        top = df.sort_values("built", ascending=False).head(4)
        log.info("step %d (%.0f %% of the world, build counts x %.1f): LCOE %.1f USD/MWh (%.0fs); largest builds %s",
                 step, shares[step] * 100, scale, df["lcoe"].iloc[0], time.time() - t0,
                 ", ".join(f"{t}/{c} {b:,.0f} {u} ({d:.1f} doublings)" for (t, c), b, u, d
                           in zip(top.index, top["built"], comps.loc[top.index, "unit"], top["doublings"])))
        capex = capex_next

    out = pd.concat(frames, ignore_index=True)
    out.insert(0, "series", name)
    out.insert(0, "dataset", dataset)
    out["load_twh"] = load_twh
    for tech, t in tranches.items():                 # cheapest tranche per site, for the legend table
        out[f"cheapest_{tech}_usd_kw"] = t["capex_total"].min() if not t.empty else np.nan
    out["learning_rate"] = comps.loc[list(zip(out.tech, out.component)), "learning_rate"].values
    out["unit"] = comps.loc[list(zip(out.tech, out.component)), "unit"].values
    return out


if __name__ == "__main__":
    result = run(CFG, DATASET, I)
    result.to_csv(OUT, index=False)
    log.info("wrote %s", OUT)
