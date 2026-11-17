#!/usr/bin/env python
# SPDX-License-Identifier: MIT
"""
Build the per-country statistics of one reference year in the formats of the fork options that read them where
each data vector enters the workflow (statistics.yaml wires them in; README "Calibration at the source").

    python config-pypsa-earth/scripts/build_calibration.py [--year 2024]

writes config-pypsa-earth/calibration/<year>/
    demand.csv            country, demand_twh            Ember demand -> load_options.annual_totals (build_demand_profiles)
    capacity.csv          country, group, gw             Ember capacity per fuel group -> electricity.powerplants_statistics
                                                         (build_powerplants; wind and solar come from IRENA, Ember's source);
                                                         biomass and geothermal from IRENA by technology (IRENA_GROUPS), and
                                                         a capacity too small for its generation back-filled
    generation.csv        country, group, twh, cf        Ember generation -> electricity.capacity_factor_targets (wind,
                                                         solar; add_electricity) and the energy bands (solve_network)
    hydro_generation.csv  country, twh                   Ember hydro -> renewable.hydro.normalization (custom)
    hydro_max_hours.csv   country, max_hours             GloHydroRes reservoir hours -> renewable.hydro.hydro_max_hours
    efficiency.csv        country, carrier, efficiency   fleet efficiency -> electricity.powerplants_efficiency
    envelope.csv          country, carrier, p_min_pu,    the operating envelope of the existing fleet with its sources:
                          p_max_pu, efficiency, source   inflexible fleet (nuclear, biomass, geothermal, oil) flat at the
                                                         Ember capacity factor, thermal availability caps and fleet
                                                         efficiencies (FLEET, coal / oil implied by Ember CO2), plus the
                                                         rows of envelope_overrides.csv
    envelope/{floor,nofloor}/<carrier>_<attr>.csv        envelope.csv as one country table per carrier and attribute ->
                          country, value                 conventional: <carrier>: existing: <attr> (add_electricity);
                                                         nofloor without floors on emitting carriers (Co2L and future years)
    net_imports.csv       country, net_imports_twh       Ember net imports -> net-import band (solve_network)
    renewable_capacities.csv  country, technology,       IRENA wind and solar capacity of <year> by technology (Onshore,
                          capacity_mw                    Offshore, PV, CSP), the numbers the fork reads itself with
                                                         `stats: irena` -> electricity.estimate_renewable_capacities
                                                         (stats: statistics; add_electricity)
and the hand-curated price tables:
    fuel_prices.csv  country, fuel, price   fuel_prices_<year>.csv + fuel_price_regions.csv, EUR x USD_PER_EUR (USD/MWh_th)
                                            -> costs.fuel_prices (add_electricity)
    co2_prices.csv   country, price         co2_prices_<year>.csv, EUR x USD_PER_EUR (USD/tCO2)
                                            -> co2.emission_prices_by_country (prepare_network)

    python config-pypsa-earth/scripts/build_calibration.py --check <solved network.nc> [...]

prints the residuals of solved networks against generation.csv: per country and fuel group the model's share of
generation vs Ember's, the capacity factors, and the rows that are more than 10 percentage points off (the
candidates for envelope_overrides.csv).

The tables of the stages that model a part of a country (US West, US East) are derived from these by
scripts/build_region_tables.py (calibration/<year>/regions/<region>/); run it after this script.

Ember data: config-pypsa-earth/data/validation/yearly_full_release_long_format.csv (gitignored download).
For each country the latest Ember year <= --year is used (Ukraine stops in 2023).
"""
import argparse
import os
import shutil

import country_converter as coco
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.dirname(HERE)
ROOT = os.path.dirname(CFG)
EMBER = os.path.join(CFG, "data", "validation", "yearly_full_release_long_format.csv")
ROW = os.path.join(CFG, "data", "row_countries.csv")
GLOHYDRORES = os.path.join(ROOT, "misc-quarter1", "geothermal", "data", "glohydrores_v1.csv")
CAL = os.path.join(CFG, "calibration")

# Ember fuel -> calibration group (Hydro is handled through hydro.csv)
GROUPS = {
    "Coal": "coal",
    "Gas": "gas",
    "Other Fossil": "oil",
    "Nuclear": "nuclear",
    "Bioenergy": "biomass",
    "Other Renewables": "geothermal",
    "Wind": "wind",
    "Solar": "solar",
    "Hydro": "hydro",
}
# carriers that run flat at the observed capacity factor (not dispatched on price)
# "oil" is Ember's Other Fossil: industrial and refinery gases, waste heat and oil-fired CHP in Europe, crude / HFO
# baseload in the Gulf -- neither is dispatched on the fuel price
INFLEXIBLE = {"nuclear": ["nuclear"], "biomass": ["biomass"], "geothermal": ["geothermal"], "oil": ["oil"]}
# price-dispatched thermal plant: availability cap (planned + forced outages) and fleet-average efficiency of the
# *existing* fleet (technology-data carries new-build values: CCGT 0.57, coal 0.356, lignite 0.33). Fleet values:
# IEA / Ember / national statistics 2024 -- CCGT fleets 48-52 % (LHV, incl. older units and CHP), hard coal 36-39 %,
# lignite 36-40 % (German fleet), OCGT 33-38 %, oil steam / diesel 33-38 %.
FLEET = {
    "coal": dict(p_max_pu=0.9, efficiency=0.38),
    "lignite": dict(p_max_pu=0.9, efficiency=0.38),
    "CCGT": dict(p_max_pu=0.92, efficiency=0.50),
    "OCGT": dict(p_max_pu=0.92, efficiency=0.35),
    "oil": dict(p_max_pu=0.9, efficiency=0.35),   # cap for countries without an Ember oil row
}

# capacity of the biomass and geothermal groups from IRENA by technology, not from Ember: Ember's "Other Renewables"
# capacity holds IRENA's renewable municipal waste in countries that have some (US 0.89 GW, against 2.7 GW of
# geothermal; DE 1.06, NL 0.40 GW of "geothermal"), while Ember counts the waste's generation as Bioenergy, whose
# capacity leaves the waste out (CN 18.6 GW for 208 TWh). Marine energy goes with geothermal, as Ember's tidal
# generation does with its Other Renewables. Countries IRENA does not list keep Ember's value.
IRENA_GROUPS = {
    "biomass": ["Solid biofuels", "Renewable municipal waste", "Biogas", "Liquid biofuels"],
    "geothermal": ["Geothermal energy", "Marine energy"],
}

# capacity factor used to back-fill an Ember capacity row that is missing, zero or too small for its generation
# (capacity factor above 1): Ember has no "Other Renewables" capacity for e.g. IS, NZ, CR, NI, SV, whose geothermal is
# 15-30 % of generation, and Other Fossil capacity far below its generation in IR, EG, SY (dual-fuel plants counted as gas)
BACKFILL_CF = {"geothermal": 0.75, "biomass": 0.5, "oil": 0.3, "gas": 0.3, "coal": 0.5, "nuclear": 0.85,
               "wind": 0.28, "solar": 0.15, "hydro": 0.4}

# fleet efficiency implied by Ember's per-fuel CO2: the model's direct emissions are generation / efficiency x the
# technology-data intensity (gas 0.198, coal 0.336, oil 0.2571 tCO2/MWh_th), so the fleet efficiency that reproduces
# Ember's combustion accounting is intensity x generation / emissions (Gulf / CIS gas fleets are steam and simple-cycle
# units at 30-35 %, old coal fleets 28-33 %, Ember's lignite factor makes lignite fleets look less efficient still).
# Applied for fuels with > 0.5 TWh; clipped to the range.
# Gas is left out (fixed 2026-10-19): Ember's gas factors are life-cycle country factors (Jordaan et al. 2022, incl.
# upstream methane), so the implied efficiency read the upstream emissions as fuel burnt in the plant (US 0.37 against
# ~0.45 from EIA heat rates, AU / CA / SA 0.27); gas fleets take the FLEET values per carrier instead. Coal's factors
# (UNECE, by coal grade) carry a much smaller upstream share and give plausible fleets (0.35-0.41); oil is kept.
IMPLIED_EFFICIENCY = {"coal": (0.336, (0.25, 0.45), ["coal", "lignite"]), "oil": (0.2571, (0.25, 0.45), ["oil"])}
# envelope attributes written as country tables for the fork's `conventional:` block, and the emitting carriers that
# lose their floor in the nofloor variant (geothermal carries a 0.12 t/MWh_th intensity in technology-data)
ENVELOPE_ATTRS = ["p_min_pu", "p_max_pu"]
EMITTING = ["oil", "geothermal", "coal", "lignite", "CCGT", "OCGT"]

USABLE_RESERVOIR = 0.5  # share of the gross reservoir energy (rho g V head) taken as usable
MAX_HOURS_CAP = 3000.0


def ember(year):
    """Ember rows of the latest year <= year per country: (TWh / GW frame, mtCO2 frame, latest year)."""
    e = pd.read_csv(EMBER, low_memory=False)
    e = e[e.Unit.isin(["TWh", "GW", "mtCO2"]) & (e.Year <= year) & e["ISO 3 code"].notna()]
    iso2 = pd.read_csv(ROW).set_index("iso3").iso2
    e = e[e["ISO 3 code"].isin(iso2.index)].copy()
    e["country"] = e["ISO 3 code"].map(iso2)
    latest = e[e.Unit != "mtCO2"].groupby("country").Year.max()
    e = e[e.Year == e.country.map(latest)]
    return e[e.Unit != "mtCO2"], e[e.Unit == "mtCO2"], latest


def fuel_table(e, category, unit):
    d = e[(e.Category == category) & (e.Subcategory == "Fuel") & (e.Unit == unit)]
    d = d[d.Variable.isin(GROUPS)]
    t = d.groupby(["country", d.Variable.map(GROUPS)]).Value.sum()
    t.index.names = ["country", "group"]
    return t


def irena_table(latest):
    """IRENA capacity (GW) of the IRENA_GROUPS per country, in the country's Ember year; every group of a country IRENA lists
    gets a row (0 where IRENA has none of its technologies). Read through powerplantmatching, the same IRENASTAT file the
    fork uses for wind and solar."""
    import powerplantmatching as pm

    d = pm.data.IRENASTAT(raw=True)
    d = d[d["Data Type"].str.contains("Capacity")]
    names = d["Country/area"].replace("Congo (the)", "Congo")
    iso2 = dict(zip(names.unique(), coco.CountryConverter().convert(list(names.unique()), to="ISO2", not_found=None)))
    d = d.assign(country=names.map(iso2))
    d = d[d.country.isin(latest.index) & (d.Year == d.country.map(latest))]
    group = {tech: g for g, techs in IRENA_GROUPS.items() for tech in techs}
    t = d[d.Technology.isin(group)].groupby(["country", d.Technology.map(group)])["Electricity statistics"].sum() / 1e3
    t = t.unstack().reindex(index=sorted(d.country.unique()), columns=list(IRENA_GROUPS)).fillna(0.0).stack()
    t.index.names = ["country", "group"]
    return t


WIND_SOLAR = ["Onshore", "Offshore", "PV", "CSP"]   # IRENA technologies, the keys of the fork's technology_mapping


def renewable_capacities(year):
    """IRENA wind and solar capacity (MW) per country and technology in `year`: powerplantmatching's IRENASTAT frame,
    read and summed exactly as the fork's add_electricity does with `estimate_renewable_capacities: stats: irena`."""
    import powerplantmatching as pm

    d = pm.data.IRENASTAT().powerplant.convert_country_to_alpha2()
    d = d[(d.Year == year) & d.Technology.isin(WIND_SOLAR) & d.Country.notna()]
    t = d.groupby(["Country", "Technology"]).Capacity.sum().rename("capacity_mw").round(1)
    t.index.names = ["country", "technology"]
    return t


def flat_envelope(cf):
    """(p_min_pu, p_max_pu) of a carrier that runs flat at the capacity factor cf."""
    return round(min(cf, 0.95) * 0.85, 3), round(min(cf * 1.05, 1.0), 3)


def demand_table(e):
    d = e[(e.Category == "Electricity demand") & (e.Unit == "TWh") & (e.Variable == "Demand")]
    return d.groupby("country").Value.sum().rename("demand_twh")


def reservoir_hours():
    g = pd.read_csv(GLOHYDRORES, low_memory=False)
    g["iso2"] = coco.CountryConverter().pandas_convert(g.country, to="ISO2", not_found=None)
    g["e_twh"] = 1000 * 9.81 * g.res_vol_km3 * 1e9 * g.head_m / 3.6e9 / 1e6 * USABLE_RESERVOIR
    sto = g[g.plant_type == "STO"].groupby("iso2").capacity_mw.sum()
    e = g.groupby("iso2").e_twh.sum()
    h = (e * 1e6 / sto).dropna().clip(lower=6.0, upper=MAX_HOURS_CAP)
    return h.rename("max_hours")


USD_PER_EUR = {2024: 1.0824}  # ECB annual average; the hand-curated price tables are in EUR, the model runs in USD


def prices(year, out):
    """Fuel and CO2 price tables in USD of the year (the currency of technology_assumptions.csv and of the model)."""
    fx = USD_PER_EUR[year]
    regions = pd.read_csv(os.path.join(CAL, "fuel_price_regions.csv"), comment="#")
    fuel = pd.read_csv(os.path.join(CAL, f"fuel_prices_{year}.csv"), comment="#")
    rows = [dict(country="*", fuel=r.fuel, price=round(r.price * fx, 2), region=r.region)
            for r in fuel[fuel.region == "default"].itertuples()]
    for r in regions.itertuples():
        for f in fuel[fuel.region == r.region].itertuples():
            rows.append(dict(country=r.country, fuel=f.fuel, price=round(f.price * fx, 2), region=r.region))
    note = f"# USD{year}: the EUR values of {{name}} x {fx} (ECB {year} average USD per EUR)\n"
    with open(os.path.join(out, "fuel_prices.csv"), "w") as f:
        f.write(note.format(name=f"fuel_prices_{year}.csv") + "# price in USD/MWh_th\n")
        pd.DataFrame(rows).to_csv(f, index=False)
    co2 = pd.read_csv(os.path.join(CAL, f"co2_prices_{year}.csv"), comment="#")
    co2["price"] = (co2["price"] * fx).round(1)
    with open(os.path.join(out, "co2_prices.csv"), "w") as f:
        f.write(note.format(name=f"co2_prices_{year}.csv") + "# price in USD/tCO2\n")
        co2.to_csv(f, index=False)


def main(year):
    out = os.path.join(CAL, str(year))
    os.makedirs(out, exist_ok=True)
    e, emissions, latest = ember(year)
    gen = fuel_table(e, "Electricity generation", "TWh")
    cap = fuel_table(e, "Capacity", "GW")
    dem = demand_table(e)

    irena = irena_table(latest)
    cap = cap.reindex(cap.index.union(gen.index).union(irena.index), fill_value=0.0)
    cap[irena.index] = irena
    # back-fill capacity where Ember has generation but no capacity, or less than the generation needs (capacity factor > 1)
    for key, twh in gen.items():
        if twh > 0 and cap.get(key, 0.0) * 8.76 < twh:
            old = cap.get(key, 0.0)
            cap[key] = twh / (8.76 * BACKFILL_CF[key[1]])
            print(f"capacity back-filled: {key[0]} {key[1]} {old:.2f} -> {cap[key]:.2f} GW from {twh:.2f} TWh")
    dem.round(3).reset_index().to_csv(os.path.join(out, "demand.csv"), index=False)
    cap.rename("gw").round(4).reset_index().to_csv(os.path.join(out, "capacity.csv"), index=False)
    cf = (gen / (cap.reindex(gen.index) * 8.76)).rename("cf")
    pd.concat([gen.rename("twh").round(3), cf.round(3)], axis=1).reset_index().to_csv(
        os.path.join(out, "generation.csv"), index=False
    )

    hydro = gen.xs("hydro", level="group").rename("twh").round(3)
    hydro.reset_index().to_csv(os.path.join(out, "hydro_generation.csv"), index=False)
    max_hours = reservoir_hours().reindex(hydro.index).round(0).dropna()
    max_hours.reset_index().rename(columns={"index": "country"}).to_csv(
        os.path.join(out, "hydro_max_hours.csv"), index=False)

    imports = e[(e.Category == "Electricity imports") & (e.Unit == "TWh") & (e.Variable == "Net Imports")]
    imports.groupby("country").Value.sum().rename("net_imports_twh").round(3).reset_index().to_csv(
        os.path.join(out, "net_imports.csv"), index=False
    )

    renewable_capacities(year).reset_index().to_csv(os.path.join(out, "renewable_capacities.csv"), index=False)

    rows = [dict(country="*", carrier=c, p_min_pu=np.nan, p_max_pu=v["p_max_pu"], efficiency=v["efficiency"],
                 source="thermal availability and fleet efficiency") for c, v in FLEET.items()]
    for group, carriers in INFLEXIBLE.items():
        for (c, g), v in cf.items():
            if g != group or not np.isfinite(v) or v <= 0:
                continue
            for carrier in carriers:
                p_min_pu, p_max_pu = flat_envelope(v)
                rows.append(dict(country=c, carrier=carrier, p_min_pu=p_min_pu, p_max_pu=p_max_pu, efficiency=np.nan,
                                 source=f"ember_cf_{latest[c]} flat"))
    co2 = fuel_table(emissions, "Power sector emissions", "mtCO2")
    n_implied = 0
    for (c, fuel), mt in co2.items():
        if fuel not in IMPLIED_EFFICIENCY or mt <= 0:
            continue
        twh = gen.get((c, fuel), 0.0)
        if twh <= 0.5:
            continue
        intensity, (lo, hi), carriers = IMPLIED_EFFICIENCY[fuel]
        eff = float(np.clip(intensity * twh / mt, lo, hi))
        for carrier in carriers:
            rows.append(dict(country=c, carrier=carrier, p_min_pu=np.nan, p_max_pu=FLEET[carrier]["p_max_pu"],
                             efficiency=round(eff, 3), source=f"efficiency implied by Ember {fuel} CO2 {latest[c]}"))
        n_implied += 1
    print(f"{n_implied} implied fleet efficiencies")
    env = pd.DataFrame(rows)
    # one row per (country, carrier): first non-empty value per attribute, sources joined
    env = env.groupby(["country", "carrier"], as_index=False, sort=False).agg(
        {"p_min_pu": "first", "p_max_pu": "first", "efficiency": "first", "source": lambda x: "; ".join(x)})
    overrides = os.path.join(CAL, "envelope_overrides.csv")
    if os.path.exists(overrides):
        o = pd.read_csv(overrides, comment="#")
        env = pd.concat([env[~env.set_index(["country", "carrier"]).index.isin(
            o.set_index(["country", "carrier"]).index)], o])
    env.to_csv(os.path.join(out, "envelope.csv"), index=False)
    env[["country", "carrier", "efficiency"]].dropna().to_csv(os.path.join(out, "efficiency.csv"), index=False)
    # one table per carrier and attribute for conventional: <carrier>: existing: <attr>; the nofloor variant (runs with
    # a CO2 cap, future years) has no must-run floor on carriers that emit, which would be infeasible under Co2L0
    nofloor = env.copy()
    nofloor.loc[nofloor.carrier.isin(EMITTING), "p_min_pu"] = np.nan
    for variant, table in [("floor", env), ("nofloor", nofloor)]:
        d = os.path.join(out, "envelope", variant)
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
        for carrier in sorted(set(FLEET) | {c for cs in INFLEXIBLE.values() for c in cs}):
            for attr in ENVELOPE_ATTRS:
                v = table[table.carrier == carrier].set_index("country")[attr].dropna()
                if len(v):
                    v.rename("value").reset_index().to_csv(os.path.join(d, f"{carrier}_{attr}.csv"), index=False)

    prices(year, out)
    print(f"{out}: {len(dem)} countries, Ember years {latest.min()}-{latest.max()}; "
          f"{len(max_hours)} countries with reservoir hours; {len(env)} envelope rows")


MODEL_GROUPS = {"coal": "coal", "lignite": "coal", "CCGT": "gas", "OCGT": "gas", "oil": "oil", "nuclear": "nuclear",
                "biomass": "biomass", "geothermal": "geothermal", "onwind": "wind", "offwind-ac": "wind",
                "offwind-dc": "wind", "solar": "solar", "ror": "hydro", "hydro": "hydro", "load shedding": "shed"}


def check(networks, year, threshold=10.0):
    import pypsa

    gen = pd.read_csv(os.path.join(CAL, str(year), "generation.csv")).set_index(["country", "group"])
    cap = pd.read_csv(os.path.join(CAL, str(year), "capacity.csv")).set_index(["country", "group"]).gw
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    flagged = []
    for fn in networks:
        n = pypsa.Network(fn)
        w = n.snapshot_weightings.generators
        g = n.generators.assign(country=n.generators.bus.map(n.buses.country), group=n.generators.carrier.map(MODEL_GROUPS))
        su = n.storage_units.assign(country=n.storage_units.bus.map(n.buses.country), group=n.storage_units.carrier.map(MODEL_GROUPS))
        twh = pd.concat([
            (n.generators_t.p.mul(w, axis=0).sum() / 1e6).groupby([g.country, g.group]).sum(),
            (n.storage_units_t.p_dispatch.mul(w, axis=0).sum() / 1e6).groupby([su.country, su.group]).sum(),
        ]).groupby(level=[0, 1]).sum()
        gw = pd.concat([g.p_nom_opt.groupby([g.country, g.group]).sum(), su.p_nom_opt.groupby([su.country, su.group]).sum()]).groupby(level=[0, 1]).sum() / 1e3
        for c in sorted(g.country.dropna().unique()):
            m = twh.xs(c, level=0).drop("shed", errors="ignore")
            shed = twh.get((c, "shed"), 0.0)
            e = gen.xs(c, level=0).twh if c in gen.index.get_level_values(0) else pd.Series(dtype=float)
            t = pd.DataFrame({"model_twh": m, "ember_twh": e.reindex(m.index.union(e.index))}).fillna(0.0)
            t["model_%"] = 100 * t.model_twh / t.model_twh.sum()
            t["ember_%"] = 100 * t.ember_twh / t.ember_twh.sum()
            t["diff_pp"] = t["model_%"] - t["ember_%"]
            t["model_gw"] = gw.xs(c, level=0).reindex(t.index)
            t["model_cf"] = t.model_twh / (t.model_gw * 8.76)
            t["ember_cf"] = t.ember_twh / (cap.xs(c, level=0).reindex(t.index) * 8.76)
            print(f"\n== {os.path.basename(os.path.dirname(os.path.dirname(fn)))} {c}: model {t.model_twh.sum():.0f} TWh, "
                  f"Ember {t.ember_twh.sum():.0f} TWh, shed {shed:.2f} TWh")
            print(t.round(2).to_string())
            for grp, r in t[t.diff_pp.abs() > threshold].iterrows():
                flagged.append(dict(country=c, group=grp, diff_pp=round(r.diff_pp, 1), model_cf=round(r.model_cf, 2), ember_cf=round(r.ember_cf, 2)))
    print(f"\n== rows off by more than {threshold} pp:")
    print(pd.DataFrame(flagged).to_string(index=False) if flagged else "none")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--year", type=int, default=2024)
    p.add_argument("--check", nargs="*", metavar="NETWORK", help="solved networks to compare with generation.csv")
    a = p.parse_args()
    if a.check:
        check(a.check, a.year)
    else:
        main(a.year)
