#!/usr/bin/env python
# SPDX-License-Identifier: MIT
"""
Statistics of the stages that model a part of a country (README "US West / US East").

Every statistics table is keyed by country, and a stage that models a part of one keeps the country code (US West and US
East are both `countries: [US]`; GADM, OSM, powerplantmatching and the demand series know no other key). Such a stage
names its part with `catalyst: tables: region: <KEY>` and tables.smk then replaces the country's rows of a table by the
rows of calibration/<year>/regions/<KEY>/<table>.csv, where that file exists. This script writes those files:

    python config-pypsa-earth/scripts/build_region_tables.py [--year 2024]

after scripts/build_calibration.py and scripts/build_demand_pathway.py, whose national tables it splits. The national
tables are not changed. The part is the list of GADM level-1 units of the stage config (build_shape_options:
gadm_subset), the same list that cuts the shapes, so the network and its statistics have one boundary.

A part's value is the national value x the part's share of the country in a sub-national statistic. For the US these
are EIA's state tables of 2024 (data/validation/eia/state/, gitignored downloads from eia.gov/electricity/data/state):

    capacity.csv, generation.csv,   share of existcapacity_annual.csv (nameplate MW) / annual_generation_state.csv (MWh),
    hydro_generation.csv            "Total Electric Power Industry", per fuel group (EIA_FUELS)
    renewable_capacities.csv        IRENA x the wind / solar capacity share; offshore wind by coast (OFFSHORE)
    demand.csv (every year)         share of retail sales, HS861 2010-.xlsx
    hydro_max_hours.csv             GloHydroRes plants inside the part's units (the national formula)
    envelope/<variant>/             flat carriers at the part's capacity factor (as build_calibration.py)
    demand_shift.csv                hours by which the part's load runs later than the country's hourly series
                                    (load_options: time_shift): the part's offset to UTC against the country's, both
                                    weighted with the states' retail sales (UTC_OFFSET)

Alaska and Hawaii are in the national statistics but in no part: the parts add up to the contiguous share of each row
(printed). The shares are of utility-scale plants; small-scale solar is not in EIA's state tables. Efficiencies, fuel
and CO2 prices and net imports have no regional table: the national rows apply.
"""
import argparse
import glob
import os
import sqlite3

import numpy as np
import pandas as pd
import yaml

import build_calibration as bc

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.dirname(HERE)
ROOT = os.path.dirname(CFG)
CAL = bc.CAL
EIA = os.path.join(CFG, "data", "validation", "eia", "state")
GADM = os.path.join(ROOT, "models", "pypsa-earth", "data", "gadm", "gadm41_{iso3}", "gadm41_{iso3}.gpkg")
ISO3 = {"US": "USA"}

# calibration group -> EIA "ENERGY SOURCE" (generation) and "Fuel Source" (capacity) of the state tables. Ember's Other
# Fossil is petroleum and other gases; EIA's "Other" (batteries, purchased steam; negative in some states) is left out
EIA_FUELS = {
    "coal": (["Coal"], ["Coal"]),
    "gas": (["Natural Gas"], ["Natural Gas"]),
    "oil": (["Petroleum", "Other Gases"], ["Petroleum", "Other Gases"]),
    "nuclear": (["Nuclear"], ["Nuclear"]),
    "biomass": (["Wood and Wood Derived Fuels", "Other Biomass"], ["Wood and Wood Derived Fuels", "Other Biomass"]),
    "geothermal": (["Geothermal"], ["Geothermal"]),
    "wind": (["Wind"], ["Wind"]),
    "solar": (["Solar Thermal and Photovoltaic"], ["Solar Thermal and Photovoltaic"]),
    "hydro": (["Hydroelectric Conventional"], ["Hydroelectric"]),
}
# IRENA technology -> group whose capacity share splits it; offshore wind is not in the state tables by coast, so the
# share is that of the states with a plant in operation in 2024 (Block Island RI, South Fork NY, Vineyard Wind MA, CVOW VA)
TECHNOLOGY_GROUP = {"Onshore": "wind", "PV": "solar", "CSP": "solar"}
OFFSHORE = ["RI", "NY", "MA", "VA"]
PRODUCER = "Total Electric Power Industry"


# Standard-time offset to UTC of the time zone that holds most of a state's people (the contiguous states and DC).
# States cut by a zone border are counted with their larger part (ASSUMPTION: Florida, Indiana, Kentucky and Michigan
# as Eastern; Tennessee, Kansas, Nebraska, the Dakotas and Texas as Central; Idaho as Mountain; Oregon as Pacific).
UTC_OFFSET = {**dict.fromkeys("CA WA OR NV".split(), -8), **dict.fromkeys("AZ UT CO NM ID MT WY".split(), -7),
              **dict.fromkeys("AL TN MS LA AR MO IA MN WI IL TX OK KS NE SD ND".split(), -6),
              **dict.fromkeys("ME NH VT MA RI CT NY NJ PA DE MD DC VA WV NC SC GA FL OH MI IN KY".split(), -5)}


def demand_shift(year):
    """{region key: hours by which its load runs later than the series of all parts together}."""
    sales, offset = eia_sales(year), pd.Series(UTC_OFFSET, dtype=float)
    parts = {key: [unit_codes(country)[i] for i in ids] for key, (country, ids) in region_stages().items()}
    mean = lambda states: float((sales.reindex(states) * offset.reindex(states)).sum() / sales.reindex(states).sum())
    everything = mean([s for states in parts.values() for s in states])
    return {key: round(everything - mean(states), 2) for key, states in parts.items()}


def region_stages():
    """{region key: (country, [GADM ids])} of the stage configs with catalyst: tables: region."""
    out = {}
    for fn in sorted(glob.glob(os.path.join(CFG, "config.*.yaml"))):
        cfg = yaml.safe_load(open(fn)) or {}
        key = ((cfg.get("catalyst") or {}).get("tables") or {}).get("region")
        if not key:
            continue
        if len(cfg["countries"]) != 1:
            raise ValueError(f"{fn}: a stage with catalyst.tables.region models a part of one country")
        ids = (cfg.get("build_shape_options") or {}).get("gadm_subset")
        if not ids:
            raise ValueError(f"{fn}: catalyst.tables.region needs build_shape_options.gadm_subset")
        if out.setdefault(key, (cfg["countries"][0], sorted(ids))) != (cfg["countries"][0], sorted(ids)):
            raise ValueError(f"region {key} is defined differently by two stage configs")
    return out


def unit_codes(country):
    """{GADM id as in gadm_shapes ("US.5_1"): postal code ("CA")} of the country's level-1 units (GADM's HASC_1)."""
    with sqlite3.connect(GADM.format(iso3=ISO3[country])) as db:
        rows = db.execute("SELECT GID_1, HASC_1 FROM ADM_ADM_1").fetchall()
    return {country + gid[3:]: hasc.split(".")[1] for gid, hasc in rows}


def eia_generation(year):
    d = pd.read_csv(os.path.join(EIA, "annual_generation_state.csv"), skiprows=1, thousands=",")
    d.columns = ["year", "state", "producer", "source", "mwh"]
    d = d[(d.year == year) & (d.producer == PRODUCER) & (d.state.str.len() == 2)]
    return d.groupby(["state", "source"]).mwh.sum()


def eia_capacity(year):
    d = pd.read_csv(os.path.join(EIA, "existcapacity_annual.csv"), skiprows=1, thousands=",")
    d = d.rename(columns={"Year": "year", "State Code": "state", "Producer Type": "producer", "Fuel Source": "source",
                          "Nameplate Capacity (Megawatts)": "mw"})
    d = d[(d.year == year) & (d.producer == PRODUCER) & (d.state.str.len() == 2) & (d.state != "US")]
    return d.groupby(["state", "source"]).mw.sum()


def eia_sales(year):
    d = pd.read_excel(os.path.join(EIA, "HS861 2010-.xlsx"), sheet_name="Total Electric Industry", header=None)
    sector = d.iloc[0].ffill()
    col = [i for i in d.columns if sector[i] == "TOTAL" and d.iloc[1, i] == "Sales"]
    if len(col) != 1:
        raise ValueError("HS861: no single TOTAL / Sales column")
    t = d.iloc[3:, [0, 1, col[0]]]
    t.columns = ["year", "state", "mwh"]
    t = t[(pd.to_numeric(t.year, errors="coerce") == year) & (t.state.astype(str).str.len() == 2) & (t.state != "US")]
    return t.set_index("state").mwh.astype(float)


def shares(year, states):
    """Share of the country in the given states: (per group for capacity, per group for generation, demand)."""
    gen, cap, sales = eia_generation(year), eia_capacity(year), eia_sales(year)

    def group_share(table, sources):
        t = table[table.index.get_level_values("source").isin(sources)].groupby("state").sum()
        return t.reindex(states).sum() / t.sum()

    cap_share = pd.Series({g: group_share(cap, c) for g, (_, c) in EIA_FUELS.items()})
    gen_share = pd.Series({g: group_share(gen, s) for g, (s, _) in EIA_FUELS.items()})
    return cap_share, gen_share, sales.reindex(states).sum() / sales.sum()


def reservoir_hours(country, states):
    """build_calibration.reservoir_hours for the plants of the country inside the given units."""
    import geopandas as gpd

    g = pd.read_csv(bc.GLOHYDRORES, low_memory=False)
    names = {n: bc.coco.CountryConverter().convert(n, to="ISO2", not_found=None) for n in g.country.unique()}
    g = g[g.country.map(names) == country]
    units = gpd.read_file(GADM.format(iso3=ISO3[country]), layer="ADM_ADM_1")[["HASC_1", "geometry"]]
    units = units[units.HASC_1.str.split(".").str[1].isin(states)]
    pts = gpd.GeoDataFrame(g, geometry=gpd.points_from_xy(g.plant_lon, g.plant_lat), crs=units.crs)
    g = gpd.sjoin(pts, units, predicate="within")
    e_twh = (1000 * 9.81 * g.res_vol_km3 * 1e9 * g.head_m / 3.6e9 / 1e6 * bc.USABLE_RESERVOIR).sum()
    sto_mw = g[g.plant_type == "STO"].capacity_mw.sum()
    return float(np.clip(e_twh * 1e6 / sto_mw, 6.0, bc.MAX_HOURS_CAP))


def write(df, *parts):
    fn = os.path.join(*parts)
    os.makedirs(os.path.dirname(fn), exist_ok=True)
    df.to_csv(fn, index=False)


def main(year):
    national = {name: pd.read_csv(os.path.join(CAL, str(year), f"{name}.csv"))
                for name in ["capacity", "generation", "hydro_generation", "renewable_capacities"]}
    report = []
    shift = demand_shift(year)
    for key, (country, ids) in region_stages().items():
        codes = unit_codes(country)
        states = [codes[i] for i in ids]
        cap_share, gen_share, demand_share = shares(year, states)
        out = os.path.join(CAL, str(year), "regions", key)

        cap = national["capacity"][national["capacity"].country == country].copy()
        gen = national["generation"][national["generation"].country == country].copy()
        cap["gw"] = cap.gw * cap.group.map(cap_share)
        gen["twh"] = gen.twh * gen.group.map(gen_share)
        cap, gen = cap.set_index("group"), gen.set_index("group")
        for group in gen.index:      # the national rule: a capacity too small for its generation is back-filled
            if gen.twh[group] > 0 and cap.gw.get(group, 0.0) * 8.76 < gen.twh[group]:
                old = cap.gw.get(group, 0.0)
                cap.loc[group, ["country", "gw"]] = country, gen.twh[group] / (8.76 * bc.BACKFILL_CF[group])
                print(f"{key}: capacity back-filled: {group} {old:.2f} -> {cap.gw[group]:.2f} GW from {gen.twh[group]:.2f} TWh")
        gen["cf"] = (gen.twh / (cap.gw.reindex(gen.index) * 8.76)).round(3)
        write(cap.reset_index()[["country", "group", "gw"]].round(4), out, "capacity.csv")
        write(gen.reset_index()[["country", "group", "twh", "cf"]].round(3), out, "generation.csv")
        write(pd.DataFrame({"country": [country], "twh": [round(gen.twh["hydro"], 3)]}), out, "hydro_generation.csv")
        write(pd.DataFrame({"country": [country], "max_hours": [round(reservoir_hours(country, states))]}), out,
              "hydro_max_hours.csv")
        write(pd.DataFrame({"country": [country], "shift_hours": [shift[key]]}), out, "demand_shift.csv")

        ren = national["renewable_capacities"][national["renewable_capacities"].country == country].copy()
        offshore = eia_capacity(year)
        offshore = offshore[offshore.index.get_level_values("source") == "Wind"].groupby("state").sum().reindex(OFFSHORE)
        factor = ren.technology.map(TECHNOLOGY_GROUP).map(cap_share)
        factor[ren.technology == "Offshore"] = offshore.reindex(states).sum() / offshore.sum()
        ren["capacity_mw"] = (ren.capacity_mw * factor).round(1)
        write(ren, out, "renewable_capacities.csv")

        for variant in ["floor", "nofloor"]:
            d = os.path.join(out, "envelope", variant)
            for f in glob.glob(os.path.join(d, "*.csv")):
                os.remove(f)
            for group, carriers in bc.INFLEXIBLE.items():
                cf = gen.cf.get(group, np.nan)
                if not np.isfinite(cf) or cf <= 0:
                    continue
                for carrier in carriers:
                    for attr, value in zip(bc.ENVELOPE_ATTRS, bc.flat_envelope(cf)):
                        if attr == "p_min_pu" and variant == "nofloor" and carrier in bc.EMITTING:
                            continue
                        if os.path.exists(os.path.join(CAL, str(year), "envelope", variant, f"{carrier}_{attr}.csv")):
                            write(pd.DataFrame({"country": [country], "value": [value]}), d, f"{carrier}_{attr}.csv")

        for fn in sorted(glob.glob(os.path.join(CAL, "[0-9]" * 4, "demand.csv"))):   # the calibration year and the horizons
            dem = pd.read_csv(fn)
            dem = dem[dem.country == country].copy()
            dem["demand_twh"] = (dem.demand_twh * demand_share).round(3)
            write(dem, os.path.dirname(fn), "regions", key, "demand.csv")

        report.append(pd.concat([cap.gw.rename(lambda g: f"capacity {g}, GW"), gen.twh.rename(lambda g: f"generation {g}, TWh"),
                                 ren.set_index("technology").capacity_mw.rename(lambda t: f"IRENA {t}, MW"),
                                 pd.Series({"demand, TWh": pd.read_csv(os.path.join(out, "demand.csv")).demand_twh.sum(),
                                            "reservoir hours": pd.read_csv(os.path.join(out, "hydro_max_hours.csv")).max_hours.sum()})
                                 ]).rename(key))
        print(f"{key}: {country}, {len(states)} units ({' '.join(sorted(states))}), demand share {demand_share:.3f} -> {out}")

    if report:
        t = pd.concat(report, axis=1)
        nat = pd.concat([
            national["capacity"].query("country == @country").set_index("group").gw.rename(lambda g: f"capacity {g}, GW"),
            national["generation"].query("country == @country").set_index("group").twh.rename(lambda g: f"generation {g}, TWh"),
            national["renewable_capacities"].query("country == @country").set_index("technology").capacity_mw.rename(lambda x: f"IRENA {x}, MW"),
            pd.Series({"demand, TWh": pd.read_csv(os.path.join(CAL, str(year), "demand.csv")).query("country == @country").demand_twh.sum()}),
        ])
        t["national"] = nat
        t["parts / national"] = (t.drop(columns="national").sum(axis=1) / t.national).round(3)
        pd.set_option("display.width", 200)
        print(t.round(2).to_string())


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--year", type=int, default=2024)
    main(p.parse_args().year)
