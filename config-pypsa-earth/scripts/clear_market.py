# SPDX-License-Identifier: CC0-1.0
"""
Learning market step between planning horizons (SOW, WP3: "after each investment year, markets for advanced
technologies are cleared across all archetypes").

    cd models/pypsa-earth
    pixi run python ../../config-pypsa-earth/scripts/clear_market.py init <market> <year0>
    pixi run python ../../config-pypsa-earth/scripts/clear_market.py step <market> <Y> <Ynext> <stage> [<stage> ...]
                                                                          [--exogenous <csv>]

The market <market> is the overlay suffix (all `<R>-myopic` stages form the market `myopic`); its state lives in
results/learning/<market>/market_<year>.csv, one file per planning horizon, read by the palette costs of that year
(technology-assumptions/assumptions.smk, rule palette_costs, through catalyst.learning_market).

market_<Y>.csv = the state at the start of horizon Y: per learning pool and component (technology-assumptions/
scripts/palette.py, learning_pools) the reference capacity Q0, the cumulative capacity Q after the builds of all
horizons before Y, and the cost factor of horizon Y

    factor = max(Q / Q0, 1) ** log2(1 - learning rate)          (Wright's law; no floor, never above 1)

- Q0 = existing_gw + pipeline_gw of the pool row (x duration_h for energy-learning rows; decision 2026-10-14: the
  CSV CAPEX is the cost of the projects being built now), reference_gw_2 for a second component when set (EGS
  surface plant: global binary geothermal).
- New capacity of horizon Y = extendable assets of the solved networks of every stage of the pathway,
  p_nom_opt - p_nom_min, counted where p_nom_opt >= existing_capacities.threshold_capacity (what the next horizon
  carries over), per CSV row through its carriers (Generator, incl. supply-curve tranches; StorageUnit x max_hours
  for energy-learning rows); rows of one pool add up (sofc-cc -> sofc). Only modelled builds count (no scaling to
  the world, decision 2026-10-14); the header records the stages and their share of 2024 world demand. Committed
  plants (fixed, build year in the future) are not counted: they are in Q0 through pipeline_gw. Retirements do
  not reduce Q.
- `--exogenous <csv>` (columns technology, year, gw) adds deployment outside the model in horizon `year` (gw of
  power; x duration_h for energy-learning rows): a test hook, and the hook for procurement volumes.

A file is rewritten only when its content changes: an identical rewrite would make Snakemake re-run every later
horizon of every stage (run.sh uses --rerun-triggers mtime input).
"""
import io
import math
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "technology-assumptions", "scripts"))
import merge_config  # noqa: E402
import palette  # noqa: E402

DEMAND = os.path.join(HERE, "..", "calibration", "2024", "demand.csv")


def path(market, year):
    return os.path.join("results", "learning", market, f"market_{year}.csv")


def capex_ref(row, comp):
    """CAPEX of a component at the reference (USD/kW, or USD/kWh for energy), and its unit."""
    if comp["unit"] == "GWh":
        return palette.num(row, "capex_energy_usd_kwh") * comp["share"], "USD/kWh"
    return palette.num(row, "capex_power_usd_kw") * comp["share"], "USD/kW"


def factor(cumulative, reference, rate):
    return max(cumulative / reference, 1.0) ** math.log2(1.0 - rate)


def initial(rows):
    """Market frame at the reference: cumulative = Q0, factor 1."""
    by_key = {r["technology"]: r for r in rows}
    out = []
    for pool, p in palette.learning_pools(rows).items():
        for c in p["components"]:
            ref, unit = capex_ref(by_key[pool], c)
            out.append(dict(pool=pool, component=c["component"], members=" ".join(p["members"]), unit=c["unit"],
                            learning_rate=c["rate"], capex_share=round(c["share"], 6),
                            reference_capacity=c["reference"], new_capacity=0.0, cumulative_capacity=c["reference"],
                            doublings=0.0, factor=1.0, capex_ref=round(ref, 4), capex=round(ref, 4), capex_unit=unit))
    return pd.DataFrame(out)


def builds(n, rows, threshold):
    """{technology: {"GW": new power, "GWh": new energy}} of the extendable assets of a solved network."""
    out = {}
    for r in rows:
        mw = mwh = 0.0
        for comp in ("Generator", "StorageUnit"):
            df = n.df(comp)
            ext = df[df.carrier.isin(palette.carriers(r)) & df.p_nom_extendable & (df.p_nom_opt >= threshold)]
            new = (ext.p_nom_opt - ext.p_nom_min).clip(lower=0.0)
            mw += new.sum()
            if comp == "StorageUnit":
                mwh += (new * ext.max_hours).sum()
        out[r["technology"]] = {"GW": mw / 1e3, "GWh": mwh / 1e3}
    return out


def coverage(stages):
    """Share of 2024 world demand (Ember, calibration/2024/demand.csv) in the countries of the stages."""
    d = pd.read_csv(DEMAND).set_index("country").demand_twh
    countries = {c for s in stages for c in merge_config.stage_config("overlay", s)["countries"]}
    return d.reindex(sorted(countries)).sum() / d.sum()


def write(df, header, out):
    """Write header + frame; only when the content changes. Returns True when written."""
    buf = io.StringIO()
    for line in header:
        buf.write(f"# {line}\n")
    df.to_csv(buf, index=False, float_format="%.6g")
    text = buf.getvalue()
    if os.path.exists(out) and open(out).read() == text:
        print(f"clear_market: {out} unchanged")
        return False
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(text)
    print(f"clear_market: wrote {out}")
    return True


def init(market, year0):
    df = initial(palette.read())
    write(df, [f"learning market '{market}': state at the start of horizon {year0} (reference, no builds yet)",
               "factor = max(cumulative / reference, 1) ** log2(1 - learning_rate); capex = capex_ref x factor",
               "written by config-pypsa-earth/scripts/clear_market.py; inputs: technology_assumptions.csv"],
          path(market, year0))
    return df


def step(market, year, year_next, stages, exogenous=None):
    import pypsa

    rows = palette.read()
    by_key = {r["technology"]: r for r in rows}
    pools = palette.learning_pools(rows)
    members = [by_key[t] for p in pools.values() for t in p["members"]]
    prev = pd.read_csv(path(market, year), comment="#")
    new = {s: {} for s in stages}
    for s in stages:
        cfg = merge_config.stage_config("overlay", s)
        threshold = (cfg.get("existing_capacities") or {}).get("threshold_capacity", 10)
        f = merge_config.solved_horizon(s, year)
        print(f"clear_market: reading {f}")
        new[s] = builds(pypsa.Network(f), members, threshold)
    exo = {}
    if exogenous:
        e = pd.read_csv(exogenous, comment="#")
        for t, g in e[e.year == int(year)].groupby("technology").gw.sum().items():
            exo[t] = g
    df = initial(rows).set_index(["pool", "component"])
    prev = prev.set_index(["pool", "component"])
    for (pool, comp), r in df.iterrows():
        unit = r.unit
        per_stage = {s: sum(new[s][t][unit] for t in pools[pool]["members"]) for s in stages}
        ex = sum(exo.get(t, 0.0) * (palette.num(by_key[t], "duration_h", 0.0) if unit == "GWh" else 1.0)
                 for t in pools[pool]["members"])
        added = sum(per_stage.values()) + ex
        cum = (prev.at[(pool, comp), "cumulative_capacity"] if (pool, comp) in prev.index else r.reference_capacity) + added
        fac = factor(cum, r.reference_capacity, r.learning_rate)
        for s, v in per_stage.items():
            df.at[(pool, comp), f"new_{s}"] = v
        df.at[(pool, comp), "new_exogenous"] = ex
        df.loc[(pool, comp), ["new_capacity", "cumulative_capacity", "doublings", "factor", "capex"]] = [
            added, cum, math.log2(max(cum / r.reference_capacity, 1.0)), fac, round(r.capex_ref * fac, 4)]
    df = df.reset_index()
    cov = coverage(stages)
    header = [f"learning market '{market}': state at the start of horizon {year_next}; new_* = builds of horizon {year}",
              f"stages: {' '.join(stages)} ({cov:.1%} of 2024 world electricity demand, Ember); only modelled builds count",
              "factor = max(cumulative / reference, 1) ** log2(1 - learning_rate); capex = capex_ref x factor",
              "written by config-pypsa-earth/scripts/clear_market.py; inputs: technology_assumptions.csv, the stages' "
              f"solved networks of {year}" + (f", exogenous deployment of {year} from {exogenous}" if exo else "")]
    # the exogenous file is named only where it adds capacity: a mention in other years would change those files
    # and make Snakemake re-run their horizons for nothing
    write(df, header, path(market, year_next))
    print(df[["pool", "component", "unit", "new_capacity", "cumulative_capacity", "doublings", "factor", "capex"]]
          .to_string(index=False))
    return df


if __name__ == "__main__":
    args = sys.argv[1:]
    exogenous = None
    if "--exogenous" in args:
        i = args.index("--exogenous")
        exogenous = args[i + 1]
        del args[i:i + 2]
    if args[:1] == ["init"]:
        init(args[1], int(args[2]))
    elif args[:1] == ["step"]:
        step(args[1], int(args[2]), int(args[3]), args[4:], exogenous)
    else:
        sys.exit(__doc__)
