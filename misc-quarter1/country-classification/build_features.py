"""Assemble a per-country feature table for the SOW archetype dimensions.

Features (SOW §1.2 Geographic scope):
  1. renewable resource quality      -> PVOUT practical potential (Solargis) +
                                        realized wind/solar capacity factors (Ember)
  2. land/acceptance constraints     -> population density, protected-area share,
                                        land area (World Bank WDI)
  3. clean firm availability         -> hydro share (Ember), installed geothermal
                                        (OWID/IRENA), EGS-suitable land share
                                        (Lucazeau 2019 heat flow, T(5 km) >= 200 C),
                                        land share near a plate boundary
  4. brownfield generation mix       -> generation & capacity by fuel (Ember)
  5. degree of interconnection       -> net-import share of demand (Ember),
                                        number of land borders (GeoDataSource)
  6. demand volume                   -> annual demand TWh (Ember, UN Energy
                                        Statistics fallback), population
                                        (World Bank), demand per capita

Run via `snakemake -c1` (rule build_features) or standalone:
  models/priam-myopic/.pixi/envs/default/bin/python build_features.py
Output: build/features_national.csv (one row per ISO2 country; the split_*
scripts turn it into the final country_features.csv)
"""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from geothermal_egs import (FEATURE_COLUMNS, is_favourable, load_cells_cached,
                            natural_earth_iso3, point_features,
                            polygon_features)

if "snakemake" in globals():
    DATA = Path(snakemake.params.data_dir)
    CELLS = Path(snakemake.input.cells)
    OUT = Path(snakemake.output[0])
else:
    _HERE = Path(__file__).parent
    DATA = _HERE / "data"
    CELLS = _HERE / "build" / "egs_cells.pkl"
    OUT = _HERE / "build" / "features_national.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lon1, lats2, lons2):
    lat1, lon1 = np.radians(lat1), np.radians(lon1)
    lats2, lons2 = np.radians(lats2), np.radians(lons2)
    a = (
        np.sin((lats2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lats2) * np.sin((lons2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


# --- ISO mapping and coordinates -------------------------------------------

iso = pd.read_csv(DATA / "iso3166.csv")[["alpha-2", "alpha-3", "name"]].rename(
    columns={"alpha-2": "iso2", "alpha-3": "iso3"}
)

coords = pd.read_csv(DATA / "country_coords.csv").rename(
    columns={"population_2023": "population_priam"}
)[["iso2", "name", "population_priam", "capital", "latitude", "longitude"]]

base = coords.merge(iso[["iso2", "iso3"]], on="iso2", how="left").set_index("iso3")

# --- Ember: demand, mix, capacity, imports ----------------------------------

ember = pd.read_csv(
    DATA / "yearly_full_release_long_format.csv",
    usecols=["ISO 3 code", "Year", "Area type", "Category", "Subcategory",
             "Variable", "Unit", "Value"],
)
ember = ember[ember["Area type"] == "Country or economy"].rename(
    columns={"ISO 3 code": "iso3"}
)

demand = ember[(ember["Category"] == "Electricity demand")
               & (ember["Variable"] == "Demand")]
latest_year = demand.dropna(subset=["Value"]).groupby("iso3")["Year"].max()

rows = {}
for iso3, year in latest_year.items():
    snap = ember[(ember["iso3"] == iso3) & (ember["Year"] == year)]

    def val(category, variable, unit=None, sub=None):
        m = snap[(snap["Category"] == category) & (snap["Variable"] == variable)]
        if sub is not None:
            m = m[m["Subcategory"] == sub]
        if unit is not None:
            m = m[m["Unit"] == unit]
        return m["Value"].iloc[0] if len(m) else np.nan

    r = {"ember_year": int(year),
         "demand_twh": val("Electricity demand", "Demand"),
         "net_imports_twh": val("Electricity imports", "Net Imports"),
         "total_generation_twh": val("Electricity generation", "Total Generation",
                                     unit="TWh")}
    for fuel in ["Coal", "Gas", "Other Fossil", "Nuclear", "Hydro", "Wind",
                 "Solar", "Bioenergy", "Other Renewables"]:
        key = fuel.lower().replace(" ", "_")
        r[f"gen_{key}_twh"] = val("Electricity generation", fuel, unit="TWh",
                                  sub="Fuel")
        r[f"cap_{key}_gw"] = val("Capacity", fuel, unit="GW", sub="Fuel")
    rows[iso3] = r

em = pd.DataFrame.from_dict(rows, orient="index")
em.index.name = "iso3"

gen_total = em["total_generation_twh"]
for fuel in ["coal", "gas", "other_fossil", "nuclear", "hydro", "wind", "solar"]:
    em[f"share_{fuel}_pct"] = 100 * em[f"gen_{fuel}_twh"] / gen_total
em["share_fossil_pct"] = (em[["share_coal_pct", "share_gas_pct",
                              "share_other_fossil_pct"]].sum(axis=1))

# Realized capacity factors; conflates resource quality with fleet age and
# curtailment, so only a screening proxy.
for fuel in ["solar", "wind"]:
    em[f"cf_{fuel}_realized"] = (
        em[f"gen_{fuel}_twh"] * 1000 / (em[f"cap_{fuel}_gw"] * 8760)
    ).where(em[f"cap_{fuel}_gw"] > 0.1)  # tiny fleets give noisy CFs

em["net_import_share_pct"] = 100 * em["net_imports_twh"] / em["demand_twh"]

# --- Solargis PV practical potential ----------------------------------------

pv = pd.read_csv(
    DATA / "solargis_pvpotential_countryranking_2020_data-Country indicators.csv",
    header=1,
)
pv.columns = [c.replace("\n", " ").strip() for c in pv.columns]
pvout_col = next(c for c in pv.columns if "PVOUT" in c and "practical" in c)
pv = pv.rename(columns={"ISO_A3": "iso3", pvout_col: "pvout_kwh_per_kwp_day"})
pv = pv.set_index("iso3")[["pvout_kwh_per_kwp_day"]]
pv["pvout_kwh_per_kwp_day"] = pd.to_numeric(
    pv["pvout_kwh_per_kwp_day"], errors="coerce"
)

# --- World Bank WDI indicators ----------------------------------------------

def wdi(indicator, name):
    payload = json.loads((DATA / f"wdi_{indicator}.json").read_text())
    records = [
        {"iso3": d["countryiso3code"], name: d["value"]}
        for d in payload[1]
        if d["countryiso3code"] and d["value"] is not None
    ]
    return pd.DataFrame(records).set_index("iso3")

wdi_all = (
    wdi("EN.POP.DNST", "pop_density_per_km2")
    .join(wdi("ER.LND.PTLD.ZS", "protected_area_pct"), how="outer")
    .join(wdi("AG.LND.TOTL.K2", "land_area_km2"), how="outer")
)


def wdi_with_year(indicator, name):
    payload = json.loads((DATA / f"wdi_{indicator}.json").read_text())
    records = [
        {"iso3": d["countryiso3code"], name: d["value"],
         f"{name}_year": int(d["date"])}
        for d in payload[1]
        if d["countryiso3code"] and d["value"] is not None
    ]
    return pd.DataFrame(records).set_index("iso3")

wb_pop = wdi_with_year("SP.POP.TOTL", "population")

# --- UN Energy Statistics: gross electricity demand (fallback + cross-check) --

# data.un.org EDATA, commodity EL, transactions 01/019/03/04/12/GA, all
# countries incl. microstates that Ember lacks. Gross demand (ELGA) is the
# closest match to Ember's "Demand" (production + imports - exports).
UN_NAME_TO_ISO3 = {
    "Bolivia (Plur. State of)": "BOL", "Bonaire, St Eustatius, Saba": "BES",
    "British Virgin Islands": "VGB", "Central African Rep.": "CAF",
    "China, Hong Kong SAR": "HKG", "China, Macao SAR": "MAC",
    "Dem. Rep. of the Congo": "COD", "Faeroe Islands": "FRO",
    "Falkland Is. (Malvinas)": "FLK", "Iran (Islamic Rep. of)": "IRN",
    "Korea, Dem.Ppl's.Rep.": "PRK", "Kosovo": "XKX",
    "Lao People's Dem. Rep.": "LAO", "Micronesia (Fed. States of)": "FSM",
    "Netherlands (Kingd. of the)": "NLD", "Republic of Moldova": "MDA",
    "Saint Martin (French Part)": "MAF", "St. Helena and Depend.": "SHN",
    "St. Kitts-Nevis": "KNA", "St. Lucia": "LCA", "St. Pierre-Miquelon": "SPM",
    "St. Vincent-Grenadines": "VCT", "State of Palestine": "PSE",
    "United Kingdom": "GBR", "United Rep. of Tanzania": "TZA",
    "United States": "USA", "United States Virgin Is.": "VIR",
    "Venezuela (Bolivar. Rep.)": "VEN", "Wallis and Futuna Is.": "WLF",
}

un = pd.read_csv(DATA / "un_energy_electricity_balance.csv")
un["iso3"] = un["country"].map(
    {**dict(zip(iso["name"], iso["iso3"])), **UN_NAME_TO_ISO3}
)
un_demand = (
    un[(un["code"] == "ELGA") & un["iso3"].notna()]
    .sort_values("year").groupby("iso3").last()
)
un_demand = pd.DataFrame({
    "demand_un_twh": un_demand["gwh"] / 1000,
    "demand_un_year": un_demand["year"].astype(int),
})

# --- Geothermal: installed capacity + plate-boundary distance ----------------

geo = pd.read_csv(DATA / "installed-geothermal-capacity.csv")
geo = geo[~geo["Code"].astype(str).str.startswith("OWID")].dropna(subset=["Code"])
geo = (geo.sort_values("Year").groupby("Code").last()
       .rename(columns={"Geothermal (total)": "geothermal_capacity_mw"})
       [["geothermal_capacity_mw"]])
geo.index.name = "iso3"

plates = json.loads((DATA / "PB2002_boundaries.json").read_text())
vertices = np.array(
    [pt for f in plates["features"] for pt in f["geometry"]["coordinates"]]
)  # (n, 2) lon/lat
plate_lons, plate_lats = vertices[:, 0], vertices[:, 1]

# Distance from the capital: kept for continuity only; the area-share
# columns below are the resource metric.
base["plate_distance_km"] = [
    haversine_km(lat, lon, plate_lats, plate_lons).min()
    if np.isfinite(lat) else np.nan
    for lat, lon in zip(base["latitude"], base["longitude"])
]

# EGS resource: share of land area with T(5 km) >= 200 degC from the
# Lucazeau (2019) heat-flow map, evaluated on a 0.1 deg grid inside Natural
# Earth country polygons (see geothermal_egs.py). Also the share of land
# within 300 km of a plate boundary (hydrothermal proxy, polygon-based).
cells = load_cells_cached(DATA, CELLS)
ne = gpd.read_file(DATA / "ne_50m_admin_0_countries")
egs = polygon_features(cells, ne.geometry, natural_earth_iso3(ne))
egs = egs[egs.index.notna()]
egs = egs[~egs.index.duplicated()][FEATURE_COLUMNS + ["n_cells"]]
# microstates with no 0.1 deg cell centre inside their polygon: sample the
# nearest cell at the capital
missing = base.index.difference(egs.index)
egs = pd.concat([egs, pd.DataFrame(
    {iso3: point_features(cells, base.at[iso3, "latitude"],
                          base.at[iso3, "longitude"])
     for iso3 in missing if np.isfinite(base.at[iso3, "latitude"])}).T])
egs.index.name = "iso3"

# --- Land borders -------------------------------------------------------------

borders = pd.read_csv(DATA / "GEODATASOURCE-COUNTRY-BORDERS.CSV")
n_borders = (
    borders.dropna(subset=["country_border_code"])
    .groupby("country_code")["country_border_code"].nunique()
    .rename("n_land_borders")
)
base = base.join(n_borders, on="iso2")
base["n_land_borders"] = base["n_land_borders"].fillna(0).astype(int)
base["is_island"] = base["n_land_borders"] == 0

# --- Merge and derive ---------------------------------------------------------

df = (base.join(em).join(pv).join(wdi_all).join(geo).join(wb_pop)
      .join(un_demand))
df["geothermal_capacity_mw"] = df["geothermal_capacity_mw"].fillna(0.0)

# Population: World Bank SP.POP.TOTL, falling back to the priam-myopic table.
df["population_source"] = np.where(df["population"].notna(), "worldbank",
                                   "priam_table")
df["population"] = df["population"].fillna(df["population_priam"])
df = df.drop(columns=["population_priam"])

# Demand: Ember, else UN gross demand, else a neighbour per-capita proxy for
# the two microstates the UN folds into their neighbours' statistics.
DEMAND_PROXY_NEIGHBOUR = {"MCO": "FRA", "SMR": "ITA"}
df["demand_source"] = np.where(df["demand_twh"].notna(), "ember", None)
df["demand_year"] = df["ember_year"]
use_un = df["demand_twh"].isna() & df["demand_un_twh"].notna()
df.loc[use_un, "demand_twh"] = df.loc[use_un, "demand_un_twh"]
df.loc[use_un, "demand_year"] = df.loc[use_un, "demand_un_year"]
df.loc[use_un, "demand_source"] = "un_energy_stats"
for iso3, nb in DEMAND_PROXY_NEIGHBOUR.items():
    if iso3 in df.index and pd.isna(df.at[iso3, "demand_twh"]):
        per_cap = df.at[nb, "demand_twh"] / df.at[nb, "population"]
        df.at[iso3, "demand_twh"] = per_cap * df.at[iso3, "population"]
        df.at[iso3, "demand_year"] = df.at[nb, "demand_year"]
        df.at[iso3, "demand_source"] = f"proxy_{nb}_per_capita"
df["demand_kwh_per_capita"] = df["demand_twh"] * 1e9 / df["population"]

# Expected demand in 2050 - screening heuristic, not a scenario. Population
# from the World Bank population projections (UN WPP medium variant,
# source=40, data/wdi_SP.POP.TOTL.2050.json). Per-capita demand: everyone
# electrifies (x1.4 on today's use - transport, heat, industry), and poorer
# countries additionally converge halfway (geometric mean) toward a
# 6000 kWh/cap benchmark ~ today's advanced-economy median. Lands in the
# range of published outlooks: India ~4.9k TWh, China ~13k TWh (IEA APS
# ~15k), US ~6.2k TWh (IEA +40-60%).
df = df.join(wdi("SP.POP.TOTL.2050", "population_2050"))
df["population_2050"] = df["population_2050"].fillna(df["population"])
_pc = df["demand_kwh_per_capita"]
df["demand_kwh_per_capita_2050"] = np.maximum(1.4 * _pc,
                                              np.sqrt(_pc * 6000.0))
df["demand_twh_2050"] = (df["demand_kwh_per_capita_2050"]
                         * df["population_2050"] / 1e9)

# Screening flag for clean-firm geothermal: at least a tenth of the land
# is EGS-suitable, or a hydrothermal field is already producing (> 10 MW).
df = df.join(egs)
df["geothermal_favourable"] = is_favourable(df["geothermal_capacity_mw"],
                                            df["egs_suitable_share"])

df = df.reset_index().rename(columns={"index": "iso3"})
front = ["iso2", "iso3", "name", "capital",
         "population", "population_year", "population_source",
         "demand_twh", "demand_year", "demand_source", "demand_kwh_per_capita",
         "demand_un_twh", "demand_un_year", "ember_year",
         "population_2050", "demand_kwh_per_capita_2050", "demand_twh_2050",
         "pvout_kwh_per_kwp_day", "cf_solar_realized", "cf_wind_realized",
         "share_fossil_pct", "share_coal_pct", "share_gas_pct",
         "share_nuclear_pct", "share_hydro_pct", "share_wind_pct",
         "share_solar_pct",
         "geothermal_capacity_mw", "egs_suitable_share", "t5km_p90_c",
         "heat_flow_mean_mwm2", "plate_share_300km", "plate_distance_km",
         "geothermal_favourable",
         "net_import_share_pct", "n_land_borders", "is_island",
         "pop_density_per_km2", "protected_area_pct", "land_area_km2"]
df = df[front + [c for c in df.columns if c not in front]]
df.to_csv(OUT, index=False)

n_demand = df["demand_twh"].notna().sum()
print(f"{len(df)} countries, {n_demand} with demand data "
      f"({df['demand_source'].value_counts().to_dict()}) -> {OUT}")
