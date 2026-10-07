"""One-node 100 % clean greenfield PyPSA network per site and weather year (misc-quarter1/toymodel-clean-procurement).

Bus `elec` with the demand of config `demand` (a constant 10 MW by default, or the site bus's 2013 load shape at that mean),
generators from the palette of config.yaml with the numbers of technology_assumptions.csv (techs.py):
solar and wind with the weather year's capacity factors, firm technologies dispatchable between `min_load`
(default 0) and a flat availability with a marginal cost (not forced baseload), EGS and hydrothermal as one capped generator per supply-curve tranche within the site radius.
Each storage technology gets its own bus with a Store (energy cost) and a charger / discharger Link pair
(round-trip losses on the charger, power cost on the discharger = delivered MW). Everything is extendable
from zero, nothing is fossil, load shedding is not allowed, stores are cyclic.

`extra_functionality`: charger p_nom == discharger p_nom; e_nom == fixed_hours x p_nom for fixed-duration
products (iron-air).

Standalone smoke test: python build_network.py <site key> <year>   (year 2013 = the bus profile itself)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd
import pypsa
import xarray as xr

from techs import annuity, check_coverage, components, load_assumptions, load_config, site_tranches

log = logging.getLogger("network")
HERE = Path(__file__).resolve().parent


def load_series(cfg: dict, site_key: str, year: int) -> tuple[dict, pd.DataFrame]:
    """The site row (sites.csv) and the weather-year frame with cf_wind, cf_solar and the configured demand_mw (8760 rows)."""
    sites = pd.read_csv(cfg["_dir"] / cfg["sites"]).set_index("key")
    site = sites.loc[site_key].to_dict()
    name = site["site"]
    if year == int(cfg.get("calibration_year", 2013)):     # the bus profile itself (smoke tests before the site-years exist)
        ds = xr.open_dataset(cfg["_dir"] / cfg["sites"].replace("sites.csv", "profiles_sites.nc"))
        series = name
    else:
        ds = xr.open_dataset(cfg["_dir"] / cfg["profiles"])
        series = f"{name} · {year}"
    df = ds.sel(series=series).to_dataframe()[["cf_wind", "cf_solar", "demand_mw"]]
    df.index = pd.date_range("2013-01-01", periods=len(df), freq="h")
    d = cfg["demand"]
    if d["kind"] == "flat":
        df["demand_mw"] = float(d["mw"])                                   # a constant load
    elif d["kind"] == "bus":
        df["demand_mw"] = df["demand_mw"] / df["demand_mw"].mean() * float(d["mw"])   # the bus shape at `mw` mean
    else:
        raise ValueError(f"demand.kind {d['kind']!r}")
    return site, df


def make_network(profile: pd.DataFrame, comps: pd.DataFrame, tranches: dict, rate: float) -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(profile.index)
    n.add("Bus", "elec", carrier="AC")
    n.add("Load", "demand", bus="elec", p_set=profile["demand_mw"])
    for tech, c in comps.iterrows():
        if c["model"] == "profile":
            n.add("Generator", tech, bus="elec", carrier=tech, p_nom_extendable=True,
                  p_max_pu=profile[PROFILE_OF[tech]].clip(lower=0, upper=1),
                  capital_cost=c["capital_cost_power"], marginal_cost=c["marginal_cost"])
        elif c["model"] == "firm":
            n.add("Generator", tech, bus="elec", carrier=tech, p_nom_extendable=True, p_max_pu=c["p_max_pu"],
                  p_min_pu=min(c["min_load"], c["p_max_pu"]), capital_cost=c["capital_cost_power"], marginal_cost=c["marginal_cost"])
        elif c["model"] == "tranches":
            table = tranches.get(tech)
            if table is None or table.empty:
                continue
            for _, t in table.iterrows():
                cost = 1e3 * (t["capex_total"] * annuity(rate, t["lifetime"]) + t["fom"])
                n.add("Generator", f"{tech} {t['tranche']}", bus="elec", carrier=tech, p_nom_extendable=True,
                      p_nom_max=t["p_nom_max"], p_max_pu=t["capacity_factor"], capital_cost=cost, marginal_cost=c["marginal_cost"])
        elif c["model"] == "storage":
            n.add("Bus", tech, carrier=tech)
            n.add("Store", f"{tech} store", bus=tech, carrier=tech, e_nom_extendable=True, e_cyclic=True,
                  capital_cost=c["capital_cost_energy"])
            n.add("Link", f"{tech} charger", bus0="elec", bus1=tech, carrier=tech, p_nom_extendable=True,
                  efficiency=c["efficiency"], capital_cost=0.0)
            n.add("Link", f"{tech} discharger", bus0=tech, bus1="elec", carrier=tech, p_nom_extendable=True,
                  efficiency=1.0, capital_cost=c["capital_cost_power"])
        else:
            raise ValueError(f"unknown model {c['model']} for {tech}")
    carriers = set(n.buses.carrier) | set(n.generators.carrier) | set(n.links.carrier) | set(n.stores.carrier)
    n.add("Carrier", sorted(carriers))
    n.comps = comps
    return n


PROFILE_OF = {}


def extra_functionality(n: pypsa.Network, snapshots) -> None:
    m = n.model
    p_nom, e_nom = m["Link-p_nom"], m["Store-e_nom"]
    for tech, c in n.comps.iterrows():
        if c["model"] != "storage":
            continue
        ch, dis = f"{tech} charger", f"{tech} discharger"
        m.add_constraints(p_nom.loc[ch] - p_nom.loc[dis] == 0, name=f"{tech}-symmetric-power")
        if not pd.isna(c["fixed_hours"]):
            m.add_constraints(e_nom.loc[f"{tech} store"] - float(c["fixed_hours"]) * p_nom.loc[dis] == 0, name=f"{tech}-fixed-duration")


def solve(n: pypsa.Network, cfg: dict) -> None:
    status, cond = n.optimize(solver_name=cfg["solver"]["name"], solver_options=cfg["solver"]["options"],
                              extra_functionality=extra_functionality)
    if status != "ok":
        raise RuntimeError(f"solver returned {status} / {cond}")


def summarise(n: pypsa.Network, comps: pd.DataFrame) -> pd.DataFrame:
    """One row per palette technology: built power (MW; discharger for storage), energy capacity (MWh), energy
    delivered to the bus (MWh), curtailment, costs, plus the annual demand."""
    w = n.snapshot_weightings.generators
    pmax = n.get_switchable_as_dense("Generator", "p_max_pu")
    out = []
    for tech, c in comps.iterrows():
        rec = {"tech": tech, "row": c["row"], "label": c["label"], "group": c["group"], "kind": c["kind"], "model": c["model"],
               "capex_power_used": c["capex_power"], "capex_energy_used": c["capex_energy"], "p_nom_mw": 0.0, "e_nom_mwh": 0.0,
               "energy_mwh": 0.0, "energy_in_mwh": 0.0, "curtailed_mwh": 0.0, "fixed_cost": 0.0, "var_cost": 0.0, "tranches": ""}
        if c["model"] in ("profile", "firm", "tranches"):
            gens = n.generators[n.generators.carrier == tech]
            if len(gens):
                p = n.generators_t.p[gens.index]
                rec["p_nom_mw"] = float(gens["p_nom_opt"].sum())
                rec["energy_mwh"] = float((p * w.values[:, None]).sum().sum())
                rec["fixed_cost"] = float((gens["capital_cost"] * gens["p_nom_opt"]).sum())
                rec["var_cost"] = float((p * w.values[:, None]).sum().sum() * c["marginal_cost"])
                rec["curtailed_mwh"] = float(((pmax[gens.index] * gens["p_nom_opt"] - p) * w.values[:, None]).sum().sum())
                if c["model"] == "tranches":
                    rec["capex_power_used"] = float((gens["capital_cost"] * gens["p_nom_opt"]).sum() / gens["p_nom_opt"].sum()) \
                        if gens["p_nom_opt"].sum() > 1e-6 else float("nan")   # USD/MW/yr actually paid, averaged over tranches
                    rec["tranches"] = "; ".join(f"{name.split(' ', 1)[1]}: {v:,.0f} MW" for name, v in gens["p_nom_opt"].items() if v > 1e-3)
        else:
            dis, ch, st = f"{tech} discharger", f"{tech} charger", f"{tech} store"
            rec["p_nom_mw"] = float(n.links.at[dis, "p_nom_opt"])
            rec["e_nom_mwh"] = float(n.stores.at[st, "e_nom_opt"])
            rec["energy_mwh"] = float((-n.links_t.p1[dis] * w).sum())
            rec["energy_in_mwh"] = float((n.links_t.p0[ch] * w).sum())
            rec["fixed_cost"] = float(n.links.at[dis, "capital_cost"] * rec["p_nom_mw"] + n.stores.at[st, "capital_cost"] * rec["e_nom_mwh"])
        out.append(rec)
    df = pd.DataFrame(out)
    df["system_cost"] = n.objective
    df["demand_mwh"] = float((n.loads_t.p_set["demand"] * w).sum())
    df["peak_mw"] = float(n.loads_t.p_set["demand"].max())
    df["lcoe_usd_mwh"] = df["system_cost"] / df["demand_mwh"]
    return df


def run(cfg: dict, site_key: str, year: int) -> pd.DataFrame:
    table = load_assumptions(cfg)
    check_coverage(cfg, table)
    site, profile = load_series(cfg, site_key, year)
    comps = components(cfg, table, site["country"])
    PROFILE_OF.update({t: s["profile"] for t, s in cfg["palette"].items() if s["model"] == "profile"})
    tranches = site_tranches(cfg, float(site["point_x"]), float(site["point_y"]))
    log.info("%s %d: %.1f TWh, peak %.0f MW, mean CF wind %.3f solar %.3f; tranches: %s", site["site"], year,
             profile.demand_mw.sum() / 1e6, profile.demand_mw.max(), profile.cf_wind.mean(), profile.cf_solar.mean(),
             {t: len(x) for t, x in tranches.items()})
    n = make_network(profile, comps, tranches, cfg["discount_rate"])
    solve(n, cfg)
    df = summarise(n, comps)
    df.insert(0, "year", year)
    df.insert(0, "site", site["site"])
    df.insert(0, "key", site_key)
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config()
    df = run(cfg, sys.argv[1] if len(sys.argv) > 1 else "us-idaho", int(sys.argv[2]) if len(sys.argv) > 2 else 2013)
    pd.set_option("display.width", 250)
    d = df.demand_mwh.iloc[0]
    show = df[["tech", "row", "p_nom_mw", "e_nom_mwh", "energy_mwh", "curtailed_mwh", "fixed_cost", "var_cost", "tranches"]].copy()
    show["gen_share_%"] = 100 * df.energy_mwh / d
    show["hours_of_mean_load"] = df.e_nom_mwh / (d / 8760)
    print(show.round(2).to_string())
    print(f"LCOE {df.lcoe_usd_mwh.iloc[0]:.1f} USD/MWh; (generation + discharge) / demand = {df.energy_mwh.sum() / d:.3f}")
