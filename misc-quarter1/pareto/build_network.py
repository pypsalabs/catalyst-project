"""One-node PyPSA network for an isolated clean system (misc-quarter1/pareto).

Buses: `elec` (the site), one bus per battery technology (Store + charger / discharger
Links, round-trip losses on the charger, capital cost on the discharger = delivered MW),
and `h2` (electrolyser Link, cavern Store, SOFC Link). Generators: solar and wind with the
site's capacity factors, SMR and Allam with a flat availability, and the site-specific
geothermal supply curve (one capped generator per EGS tranche, one for identified
hydrothermal systems) from misc-quarter1/geothermal. Everything is extendable from zero
(greenfield); load shedding is not allowed.

`extra_functionality` adds: charger p_nom == discharger p_nom for every battery, and
e_nom == fixed_hours x p_nom for a fixed-duration product (iron-air).

Standalone smoke test: python build_network.py [dataset] [series index]
"""

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa
import xarray as xr

from techs import annuity, fixed_cost_per_year, load_components, load_config, site_tranches

log = logging.getLogger("network")
HERE = Path(__file__).resolve().parent


def load_series(cfg: dict, dataset: str, i: int) -> tuple[str, pd.DataFrame]:
    """Return the series name and a frame with cf_wind, cf_solar, demand_mw (8760 rows)."""
    ds = xr.open_dataset(cfg["_dir"] / cfg["datasets"][dataset]["profiles"])
    name = str(ds.series.values[i])
    df = ds.sel(series=name).to_dataframe()[["cf_wind", "cf_solar", "demand_mw"]]
    df.index = pd.date_range("2013-01-01", periods=len(df), freq="h")
    return name, df


def make_network(profile: pd.DataFrame, comps: pd.DataFrame, capex: pd.Series, rate: float,
                 tranches: dict | None = None) -> pypsa.Network:
    """Build the network with the given per-component capex (USD/kW or USD/kWh; a factor for
    site-specific technologies, applied to their tranche costs)."""
    n = pypsa.Network()
    n.set_snapshots(profile.index)
    n.add("Bus", "elec", carrier="AC")
    n.add("Load", "demand", bus="elec", p_set=profile["demand_mw"])
    tranches = tranches or {}

    fixed = fixed_cost_per_year(capex.values, comps["fom_frac"].values, comps["lifetime"].values, rate)
    fixed = pd.Series(fixed, index=comps.index)

    for tech in comps.index.get_level_values("tech").unique():
        sub = comps.xs(tech, level="tech")
        types = set(sub["type"])
        if sub["site_specific"].iloc[0]:
            table = tranches.get(tech)
            if table is None or table.empty:
                continue
            plant_factor = capex.get((tech, "plant"), 1.0)
            well_factor = capex.get((tech, "wells"), 1.0)
            avail = sub["availability"].iloc[0]
            for _, t in table.iterrows():
                capex_kw = t["capex_plant"] * plant_factor + t["capex_well"] * well_factor
                cost = 1e3 * (capex_kw * annuity(rate, t["lifetime"]) + t["fom"])      # FOM absolute, does not learn
                n.add("Generator", f"{tech} {t['tranche']}", bus="elec", carrier=tech, p_nom_extendable=True,
                      p_nom_max=t["p_nom_max"], p_max_pu=min(avail, t["capacity_factor"]), capital_cost=cost, marginal_cost=0.0)
        elif types == {"generator"}:
            c = sub.iloc[0]
            if isinstance(c["cf"], str):
                pmax = profile[f"cf_{c['cf']}"].clip(lower=0, upper=1)
            else:
                pmax = c["availability"]
            n.add("Generator", tech, bus="elec", carrier=tech, p_nom_extendable=True, p_max_pu=pmax,
                  capital_cost=fixed[(tech, sub.index[0])], marginal_cost=c["marginal_cost"])
        elif types == {"storage_power", "storage_energy"}:
            power, energy = sub.loc["power"], sub.loc["energy"]
            n.add("Bus", tech, carrier=tech)
            n.add("Store", f"{tech} store", bus=tech, carrier=tech, e_nom_extendable=True, e_cyclic=True,
                  capital_cost=fixed[(tech, "energy")])
            n.add("Link", f"{tech} charger", bus0="elec", bus1=tech, carrier=tech, p_nom_extendable=True,
                  efficiency=power["round_trip_efficiency"], capital_cost=0.0)
            n.add("Link", f"{tech} discharger", bus0=tech, bus1="elec", carrier=tech, p_nom_extendable=True,
                  efficiency=1.0, capital_cost=fixed[(tech, "power")])
        else:  # generic links / stores (the H2 chain)
            for comp, c in sub.iterrows():
                if c["type"] == "store":
                    if c["bus"] not in n.buses.index:
                        n.add("Bus", c["bus"], carrier=c["bus"])
                    n.add("Store", f"{tech} {comp}", bus=c["bus"], carrier=tech, e_nom_extendable=True, e_cyclic=True,
                          capital_cost=fixed[(tech, comp)])
                elif c["type"] == "link":
                    for b in (c["bus0"], c["bus1"]):
                        if b not in n.buses.index:
                            n.add("Bus", b, carrier=b)
                    cost = fixed[(tech, comp)]
                    if c["cost_basis"] == "output":       # priced per MW out, p_nom is MW in
                        cost = cost * c["efficiency"]
                    n.add("Link", f"{tech} {comp}", bus0=c["bus0"], bus1=c["bus1"], carrier=tech, p_nom_extendable=True,
                          efficiency=c["efficiency"], capital_cost=cost)
                else:
                    raise ValueError(f"unexpected component type {c['type']} for {tech}/{comp}")
    carriers = set(n.buses.carrier) | set(n.generators.carrier) | set(n.links.carrier) | set(n.stores.carrier)
    n.add("Carrier", sorted(carriers))
    n.comps = comps  # keep for extra_functionality
    return n


def extra_functionality(n: pypsa.Network, snapshots) -> None:
    """Equal charger / discharger power; fixed duration where configured."""
    m = n.model
    p_nom = m["Link-p_nom"]
    e_nom = m["Store-e_nom"]
    comps = n.comps
    for tech in comps.index.get_level_values("tech").unique():
        sub = comps.xs(tech, level="tech")
        if set(sub["type"]) != {"storage_power", "storage_energy"}:
            continue
        ch, dis = f"{tech} charger", f"{tech} discharger"
        m.add_constraints(p_nom.loc[ch] - p_nom.loc[dis] == 0, name=f"{tech}-symmetric-power")
        hours = sub.loc["power", "fixed_hours"]
        if hours is not None and not pd.isna(hours):
            m.add_constraints(e_nom.loc[f"{tech} store"] - float(hours) * p_nom.loc[dis] == 0, name=f"{tech}-fixed-duration")


def solve(n: pypsa.Network, cfg: dict) -> None:
    status, cond = n.optimize(solver_name=cfg["solver"]["name"], solver_options=cfg["solver"]["options"],
                              extra_functionality=extra_functionality)
    if status != "ok":
        raise RuntimeError(f"solver returned {status} / {cond}")


def summarise(n: pypsa.Network, comps: pd.DataFrame, capex: pd.Series) -> pd.DataFrame:
    """Per component: built capacity (MW or MWh, output basis), energy served, costs.

    Site-specific technologies: `built` is the sum over tranches on every component; energy,
    costs and curtailment are booked on the `plant` component only; `tranches` lists the build.
    """
    w = n.snapshot_weightings.generators
    pmax = n.get_switchable_as_dense("Generator", "p_max_pu")
    out = []
    for (tech, comp), c in comps.iterrows():
        rec = {"tech": tech, "component": comp, "capex_used": capex[(tech, comp)], "var_cost": 0.0,
               "energy_in_mwh": 0.0, "curtailed_mwh": 0.0, "tranches": ""}
        if c["site_specific"]:
            gens = n.generators[n.generators.carrier == tech]
            rec["built"] = gens["p_nom_opt"].sum()
            rec["energy_served_mwh"] = rec["fixed_cost"] = 0.0
            if comp == "plant" and len(gens):
                rec["energy_served_mwh"] = (n.generators_t.p[gens.index] * w.values[:, None]).sum().sum()
                rec["fixed_cost"] = float((gens["capital_cost"] * gens["p_nom_opt"]).sum())
                available = pmax[gens.index] * gens["p_nom_opt"]
                rec["curtailed_mwh"] = ((available - n.generators_t.p[gens.index]) * w.values[:, None]).sum().sum()
                rec["tranches"] = "; ".join(f"{name.split(' ', 1)[1]}: {p:,.0f} MW" for name, p in gens["p_nom_opt"].items() if p > 1)
        elif c["type"] == "generator":
            rec["built"] = n.generators.at[tech, "p_nom_opt"]
            rec["energy_served_mwh"] = (n.generators_t.p[tech] * w).sum()
            rec["fixed_cost"] = n.generators.at[tech, "capital_cost"] * rec["built"]
            rec["var_cost"] = c["marginal_cost"] * rec["energy_served_mwh"]
            available = pmax[tech] * rec["built"]
            rec["curtailed_mwh"] = ((available - n.generators_t.p[tech]) * w).sum()
        elif c["type"] == "storage_power":
            name = f"{tech} discharger"
            rec["built"] = n.links.at[name, "p_nom_opt"]
            rec["energy_served_mwh"] = (-n.links_t.p1[name] * w).sum()
            rec["energy_in_mwh"] = (n.links_t.p0[f"{tech} charger"] * w).sum()
            rec["fixed_cost"] = n.links.at[name, "capital_cost"] * rec["built"]
        elif c["type"] == "storage_energy":
            name = f"{tech} store"
            rec["built"] = n.stores.at[name, "e_nom_opt"]
            rec["energy_served_mwh"] = 0.0
            rec["fixed_cost"] = n.stores.at[name, "capital_cost"] * rec["built"]
        elif c["type"] == "store":
            name = f"{tech} {comp}"
            rec["built"] = n.stores.at[name, "e_nom_opt"]
            rec["energy_served_mwh"] = 0.0
            rec["fixed_cost"] = n.stores.at[name, "capital_cost"] * rec["built"]
        elif c["type"] == "link":
            name = f"{tech} {comp}"
            p_nom = n.links.at[name, "p_nom_opt"]
            rec["built"] = p_nom * c["efficiency"] if c["cost_basis"] == "output" else p_nom
            delivered = (-n.links_t.p1[name] * w).sum()
            rec["energy_served_mwh"] = delivered if c["bus1"] == "elec" else 0.0
            rec["energy_in_mwh"] = (n.links_t.p0[name] * w).sum() if c["bus0"] == "elec" else 0.0
            rec["fixed_cost"] = n.links.at[name, "capital_cost"] * p_nom
        out.append(rec)
    df = pd.DataFrame(out)
    df["system_cost"] = n.objective
    df["demand_mwh"] = (n.loads_t.p_set["demand"] * w).sum()
    df["peak_mw"] = n.loads_t.p_set["demand"].max()
    df["lcoe"] = df["system_cost"] / df["demand_mwh"]
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    dataset = sys.argv[1] if len(sys.argv) > 1 else "sites"
    i = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    cfg = load_config()
    comps = load_components(cfg)
    name, profile = load_series(cfg, dataset, i)
    tranches = site_tranches(cfg, dataset, name)
    log.info("series %s: %.1f TWh, peak %.0f MW, mean CF wind %.3f solar %.3f", name, profile.demand_mw.sum() / 1e6,
             profile.demand_mw.max(), profile.cf_wind.mean(), profile.cf_solar.mean())
    for tech, t in tranches.items():
        log.info("%s tranches:\n%s", tech, t.round(1).to_string(index=False) if not t.empty else "  none")
    n = make_network(profile, comps, comps["capex0"], cfg["discount_rate"], tranches)
    solve(n, cfg)
    df = summarise(n, comps, comps["capex0"])
    pd.set_option("display.width", 250)
    print(df[["tech", "component", "capex_used", "built", "energy_served_mwh", "fixed_cost", "var_cost", "curtailed_mwh", "tranches"]].round(1).to_string())
    print(f"LCOE {df.lcoe.iloc[0]:.1f} USD/MWh; generation+discharge / demand = {df.energy_served_mwh.sum() / df.demand_mwh.iloc[0]:.3f}")
