"""Split the US row of country_features.csv into East and West.

The Eastern and Western Interconnections are coupled by only a few GW of DC
ties, so for interconnection-sensitive archetype mapping the US is two grids,
not one country. ERCOT (Texas) is folded into the East row: one US-East grid
is what the archetype modelling works with.

Assignment is by whole state: West = the 11 WECC states (WA OR CA NV ID UT AZ
NM CO WY MT); East = everything else incl. TX. Alaska and Hawaii are isolated
grids outside both interconnections and are excluded: their share of the
national figures is dropped, not redistributed. Caveat: NM/MT straddle the
seam - fine at screening grade.

Inputs (data/): EIA annual_generation_state.csv and existcapacity_annual.csv
(2024, Total Electric Power Industry), jakevdp state-population/state-areas.

Run via `snakemake -c1` (rule split_us) or standalone after build_features.py:
  models/priam-myopic/.pixi/envs/default/bin/python split_us.py
Reads build/features_national.csv, writes build/features_us.csv
(USA row -> USE + USW rows).
"""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from geothermal_egs import (FEATURE_COLUMNS, is_favourable, load_cells_cached,
                            polygon_features)

if "snakemake" in globals():
    DATA = Path(snakemake.params.data_dir)
    CELLS = Path(snakemake.input.cells)
    IN = Path(snakemake.input.features)
    OUT = Path(snakemake.output[0])
else:
    _HERE = Path(__file__).parent
    DATA = _HERE / "data"
    CELLS = _HERE / "build" / "egs_cells.pkl"
    IN = _HERE / "build" / "features_national.csv"
    OUT = _HERE / "build" / "features_us.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

EARTH_RADIUS_KM = 6371.0


# not imported from build_features: importing that module re-runs the whole
# build and overwrites the split CSV this script post-processes
def haversine_km(lat1, lon1, lats2, lons2):
    lat1, lon1 = np.radians(lat1), np.radians(lon1)
    lats2, lons2 = np.radians(lats2), np.radians(lons2)
    a = (np.sin((lats2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lats2) * np.sin((lons2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))

WEST_STATES = {"WA", "OR", "CA", "NV", "ID", "UT", "AZ", "NM", "CO", "WY",
               "MT"}
EXCLUDED_STATES = {"AK", "HI"}   # isolated grids, part of neither interconnection


def assign_region(state):
    # ERCOT (TX) is kept with the East: one US-East grid for the archetype work
    if state in EXCLUDED_STATES:
        return None
    return "USW" if state in WEST_STATES else "USE"

FUEL_MAP = {
    "Coal": "coal",
    "Natural Gas": "gas",
    "Petroleum": "other_fossil",
    "Other Gases": "other_fossil",
    "Other": "other_fossil",
    "Nuclear": "nuclear",
    "Hydroelectric Conventional": "hydro",   # generation file
    "Hydroelectric": "hydro",                # capacity file
    "Wind": "wind",
    "Solar Thermal and Photovoltaic": "solar",
    "Wood and Wood Derived Fuels": "bioenergy",
    "Other Biomass": "bioenergy",
    "Geothermal": "other_renewables",
}

REGIONS = {
    "USW": {"iso2": "UW", "name": "United States (West)", "capital": "Los Angeles",
            "latitude": 34.05, "longitude": -118.24,
            # Global Solar Atlas map readings per footprint - approximate
            "pvout_kwh_per_kwp_day": 4.8,
            "n_land_borders": 2},   # Canada, Mexico
    "USE": {"iso2": "UE", "name": "United States (East)", "capital": "New York",
            "latitude": 40.71, "longitude": -74.01,
            "pvout_kwh_per_kwp_day": 4.0,
            "n_land_borders": 2},   # Canada, Mexico (TX)
}


def load_eia_generation():
    gen = pd.read_csv(DATA / "annual_generation_state.csv", skiprows=1)
    gen.columns = ["year", "state", "producer", "fuel", "mwh"]
    gen["state"] = gen["state"].str.strip()
    gen = gen[(gen["year"] == gen["year"].max())
              & (gen["producer"] == "Total Electric Power Industry")
              & gen["state"].str.len().eq(2)
              & (gen["state"] != "US")]
    gen["mwh"] = pd.to_numeric(gen["mwh"].astype(str).str.replace(",", ""),
                               errors="coerce")
    gen["region"] = gen["state"].map(assign_region)
    gen["bucket"] = gen["fuel"].map(FUEL_MAP)
    return gen, int(gen["year"].max())


def load_eia_capacity():
    cap = pd.read_csv(DATA / "existcapacity_annual.csv", skiprows=1)
    cap.columns = ["year", "state", "producer", "fuel", "generators",
                   "facilities", "nameplate_mw", "summer_mw"]
    cap["year"] = pd.to_numeric(cap["year"], errors="coerce")
    cap["state"] = cap["state"].str.strip()
    cap = cap[(cap["year"] == cap["year"].max())
              & (cap["producer"] == "Total Electric Power Industry")
              & (cap["state"] != "US")]
    cap["summer_mw"] = pd.to_numeric(
        cap["summer_mw"].astype(str).str.replace(",", ""), errors="coerce")
    cap["region"] = cap["state"].map(assign_region)
    cap["bucket"] = cap["fuel"].map(FUEL_MAP)
    return cap


df = pd.read_csv(IN)
us = df[df["iso3"] == "USA"]
if us.empty:
    raise SystemExit(f"No USA row in {IN} - rerun build_features.py first.")
us = us.iloc[0]

gen, eia_year = load_eia_generation()
cap = load_eia_capacity()

gen_r = (gen.dropna(subset=["bucket"])
         .groupby(["region", "bucket"])["mwh"].sum().unstack(fill_value=0) / 1e6)
cap_r = (cap.dropna(subset=["bucket"])
         .groupby(["region", "bucket"])["summer_mw"].sum().unstack(fill_value=0)
         / 1e3)
geo_mw = (cap[cap["fuel"] == "Geothermal"]
          .groupby("region")["summer_mw"].sum())
total_gen = gen_r.sum(axis=1)
# shares of the national total incl. AK/HI, so the excluded grids' part is dropped
gen_share = total_gen / (gen.dropna(subset=["bucket"])["mwh"].sum() / 1e6)

pop = pd.read_csv(DATA / "state-population.csv")
pop = pop[(pop["ages"] == "total") & (pop["year"] == pop["year"].max())
          & pop["state/region"].str.len().eq(2)]
pop["region"] = pop["state/region"].map(assign_region)
pop_share = pop.groupby("region")["population"].sum() / pop["population"].sum()

areas = pd.read_csv(DATA / "state-areas.csv")
STATE_ABBREV = dict(zip(pop["state/region"],
                        pop["state/region"]))  # abbrevs already
# state-areas.csv uses full names; map via a static abbrev table
ABBREV = {
 "Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA",
 "Colorado":"CO","Connecticut":"CT","Delaware":"DE","Florida":"FL","Georgia":"GA",
 "Hawaii":"HI","Idaho":"ID","Illinois":"IL","Indiana":"IN","Iowa":"IA",
 "Kansas":"KS","Kentucky":"KY","Louisiana":"LA","Maine":"ME","Maryland":"MD",
 "Massachusetts":"MA","Michigan":"MI","Minnesota":"MN","Mississippi":"MS",
 "Missouri":"MO","Montana":"MT","Nebraska":"NE","Nevada":"NV",
 "New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM","New York":"NY",
 "North Carolina":"NC","North Dakota":"ND","Ohio":"OH","Oklahoma":"OK",
 "Oregon":"OR","Pennsylvania":"PA","Rhode Island":"RI","South Carolina":"SC",
 "South Dakota":"SD","Tennessee":"TN","Texas":"TX","Utah":"UT","Vermont":"VT",
 "Virginia":"VA","Washington":"WA","West Virginia":"WV","Wisconsin":"WI",
 "Wyoming":"WY","District of Columbia":"DC"}
areas["abbrev"] = areas["state"].map(ABBREV)
areas = areas[~areas["abbrev"].isin(EXCLUDED_STATES)].dropna(subset=["abbrev"])
areas["region"] = areas["abbrev"].map(assign_region)
area_km2 = areas.groupby("region")["area (sq. mi)"].sum() * 2.58999

plates = json.loads((DATA / "PB2002_boundaries.json").read_text())
vertices = np.array(
    [pt for f in plates["features"] for pt in f["geometry"]["coordinates"]])

# EGS-suitable land share etc. per interconnection, from state polygons
states = gpd.read_file(DATA / "ne_50m_admin_1_states_provinces")
states = states[(states["adm0_a3"] == "USA") & ~states["postal"].isin(EXCLUDED_STATES)]
egs = polygon_features(load_cells_cached(DATA, CELLS), states.geometry,
                       states["postal"].map(assign_region))

new_rows = []
for iso3, meta in REGIONS.items():
    share = gen_share[iso3]
    pshare = pop_share[iso3]
    r = {c: np.nan for c in df.columns}
    r.update(meta)
    r["iso3"] = iso3
    r["ember_year"] = eia_year
    r["demand_twh"] = us["demand_twh"] * share
    r["net_imports_twh"] = us["net_imports_twh"] * share
    r["net_import_share_pct"] = us["net_import_share_pct"]
    r["population"] = us["population"] * pshare
    r["population_year"] = us["population_year"]
    r["population_source"] = us["population_source"]
    r["demand_year"] = us["demand_year"]
    r["demand_source"] = us["demand_source"]
    r["demand_kwh_per_capita"] = r["demand_twh"] * 1e9 / r["population"]
    r["demand_un_twh"] = us["demand_un_twh"] * share
    r["demand_un_year"] = us["demand_un_year"]
    r["population_2050"] = us["population_2050"] * pshare
    r["demand_twh_2050"] = us["demand_twh_2050"] * share
    r["demand_kwh_per_capita_2050"] = (r["demand_twh_2050"] * 1e9
                                       / r["population_2050"])
    r["total_generation_twh"] = total_gen[iso3]
    for fuel in ["coal", "gas", "other_fossil", "nuclear", "hydro", "wind",
                 "solar", "bioenergy", "other_renewables"]:
        r[f"gen_{fuel}_twh"] = gen_r.at[iso3, fuel] if fuel in gen_r else 0.0
        r[f"cap_{fuel}_gw"] = cap_r.at[iso3, fuel] if fuel in cap_r else 0.0
    for fuel in ["coal", "gas", "other_fossil", "nuclear", "hydro", "wind",
                 "solar"]:
        r[f"share_{fuel}_pct"] = 100 * r[f"gen_{fuel}_twh"] / r["total_generation_twh"]
    r["share_fossil_pct"] = (r["share_coal_pct"] + r["share_gas_pct"]
                             + r["share_other_fossil_pct"])
    for fuel in ["solar", "wind"]:
        r[f"cf_{fuel}_realized"] = (
            r[f"gen_{fuel}_twh"] * 1000 / (r[f"cap_{fuel}_gw"] * 8760)
            if r[f"cap_{fuel}_gw"] > 0.1 else np.nan)
    r["geothermal_capacity_mw"] = geo_mw.get(iso3, 0.0)
    r["plate_distance_km"] = haversine_km(
        meta["latitude"], meta["longitude"],
        vertices[:, 1], vertices[:, 0]).min()
    for col in FEATURE_COLUMNS + ["n_cells"]:
        r[col] = egs.at[iso3, col]
    r["geothermal_favourable"] = bool(
        is_favourable(r["geothermal_capacity_mw"], r["egs_suitable_share"]))
    # Thin DC ties between the three interconnections are ignored; land
    # borders count only the external neighbour each footprint touches.
    r["is_island"] = False
    r["land_area_km2"] = area_km2[iso3]
    r["pop_density_per_km2"] = r["population"] / r["land_area_km2"]
    r["protected_area_pct"] = us["protected_area_pct"]  # national value
    new_rows.append(r)

df = pd.concat([df[df["iso3"] != "USA"], pd.DataFrame(new_rows)],
               ignore_index=True)
df.to_csv(OUT, index=False)

for r in new_rows:
    print(f"{r['iso3']}: demand {r['demand_twh']:.0f} TWh, "
          f"gen {r['total_generation_twh']:.0f} TWh, "
          f"fossil {r['share_fossil_pct']:.0f}%, "
          f"geothermal {r['geothermal_capacity_mw']:.0f} MW, "
          f"EGS share {r['egs_suitable_share']:.2f}, "
          f"wind CF {r['cf_wind_realized']:.2f}, "
          f"solar CF {r['cf_solar_realized']:.2f}")
