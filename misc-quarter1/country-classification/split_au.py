"""Split the Australia row of country_features.csv into NEM and SWIS.

The South West Interconnected System (SWIS, around Perth) has zero
transmission ties to the National Electricity Market on the east coast -
the SOW itself names "Australia's Western grid" as an exemplar of the
islanded archetype. The SWIS is a pure firming-tech testbed: no hydro, no
nuclear, no import option, coal exit scheduled ~2029-30.

The SWIS row is anchored on AEMO WEM operational data via OpenNEM (last
complete calendar year), NOT on WA state statistics - WA totals include
large off-grid mining gas (Pilbara/NWIS) that roughly doubles the state
versus the actual SWIS. The NEM row is the national Ember row minus the
SWIS, so it also absorbs the NT grids and off-grid mining remnants
(a few % of national generation) - noted caveat.

Inputs (data/): wem_energy.json (OpenNEM monthly energy by fuel tech,
au.wem.*), au_facilities.json (OpenNEM facility registry, WEM operating
capacity by fuel tech).

Run via `snakemake -c1` (rule split_au) or standalone after split_us.py:
  models/priam-myopic/.pixi/envs/default/bin/python split_au.py
Reads build/features_us.csv, writes build/features_au.csv
(AUS row -> AUN + AUW rows).
"""

import datetime
import json
from collections import defaultdict
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
    IN = _HERE / "build" / "features_us.csv"
    OUT = _HERE / "build" / "features_au.csv"
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

FUELTECH_MAP = {
    "coal_black": "coal",
    "gas_ccgt": "gas",
    "gas_ocgt": "gas",
    "distillate": "other_fossil",
    "bioenergy_biogas": "bioenergy",
    "bioenergy_biomass": "bioenergy",
    "solar_utility": "solar",
    "solar_rooftop": "solar",
    "wind": "wind",
    # battery_discharging is storage throughput, not generation - skip
}

# AEMO 2023 ESOO: ~2.7 GW distributed PV in the SWIS. The OpenNEM facility
# registry only covers utility plant, but its rooftop *generation* series is
# included above, so capacity must match for a sane realized CF.
SWIS_ROOFTOP_GW = 2.7

# ABS national accounts Dec 2024: WA 3.05 M of 27.34 M. Pilbara off-grid
# population is negligible, so WA share ~= SWIS share.
WA_POP_SHARE = 3.05 / 27.34
WA_AREA_KM2 = 2_527_013  # whole state - vastly overstates the SWIS footprint

REGIONS = {
    "AUN": {"iso2": "XN", "name": "Australia (NEM)", "capital": "Sydney",
            "latitude": -33.87, "longitude": 151.21,
            # Global Solar Atlas map readings per footprint - approximate
            "pvout_kwh_per_kwp_day": 4.5,
            "n_land_borders": 0},
    "AUW": {"iso2": "XW", "name": "Australia (SWIS)", "capital": "Perth",
            "latitude": -31.95, "longitude": 115.86,
            "pvout_kwh_per_kwp_day": 4.7,
            "n_land_borders": 0},
}

FUELS = ["coal", "gas", "other_fossil", "nuclear", "hydro", "wind",
         "solar", "bioenergy", "other_renewables"]


def load_wem_generation():
    """Monthly OpenNEM WEM energy -> bucket TWh for the last complete year."""
    d = json.loads((DATA / "wem_energy.json").read_text())
    monthly = defaultdict(lambda: defaultdict(float))  # year -> bucket
    months_seen = defaultdict(set)
    for s in d["data"]:
        if s["type"] != "energy":
            continue
        bucket = FUELTECH_MAP.get(s["fuel_tech"])
        if bucket is None:
            continue
        start = datetime.date.fromisoformat(s["history"]["start"][:10])
        y, m = start.year, start.month
        for v in s["history"]["data"]:
            if v is not None:
                monthly[y][bucket] += v
            months_seen[y].add(m)
            m += 1
            if m == 13:
                m, y = 1, y + 1
    year = max(y for y, ms in months_seen.items() if len(ms) == 12)
    return {b: gwh / 1000 for b, gwh in monthly[year].items()}, year


def load_wem_capacity():
    """Operating WEM units from the OpenNEM facility registry -> bucket GW."""
    f = json.loads((DATA / "au_facilities.json").read_text())
    cap = defaultdict(float)
    for feat in f["features"]:
        p = feat["properties"]
        if str(p.get("network")).upper() != "WEM":
            continue
        for u in p.get("duid_data", []):
            if str(u.get("status")).lower() not in ("operating", "operational"):
                continue
            bucket = FUELTECH_MAP.get(u.get("fuel_tech"))
            if bucket:
                cap[bucket] += (u.get("capacity_registered") or 0) / 1000
    cap["solar"] += SWIS_ROOFTOP_GW
    return dict(cap)


df = pd.read_csv(IN)
aus = df[df["iso3"] == "AUS"]
if aus.empty:
    raise SystemExit(f"No AUS row in {IN} - rerun build_features.py first.")
aus = aus.iloc[0]

wem_gen, wem_year = load_wem_generation()
wem_cap = load_wem_capacity()

gen_r = {"AUW": {f: wem_gen.get(f, 0.0) for f in FUELS}}
cap_r = {"AUW": {f: wem_cap.get(f, 0.0) for f in FUELS}}
# NEM = national Ember minus SWIS (absorbs NT + off-grid mining remnants).
# Ember year and WEM year differ by a year or two - screening grade.
gen_r["AUN"] = {f: max(np.nan_to_num(aus[f"gen_{f}_twh"]) - gen_r["AUW"][f], 0.0)
                for f in FUELS}
cap_r["AUN"] = {f: max(np.nan_to_num(aus[f"cap_{f}_gw"]) - cap_r["AUW"][f], 0.0)
                for f in FUELS}

total_gen = {r: sum(gen_r[r].values()) for r in REGIONS}
gen_share = {r: total_gen[r] / sum(total_gen.values()) for r in REGIONS}
pop_share = {"AUW": WA_POP_SHARE, "AUN": 1 - WA_POP_SHARE}
area_km2 = {"AUW": WA_AREA_KM2, "AUN": aus["land_area_km2"] - WA_AREA_KM2}

plates = json.loads((DATA / "PB2002_boundaries.json").read_text())
vertices = np.array(
    [pt for f in plates["features"] for pt in f["geometry"]["coordinates"]])

# EGS-suitable land share etc.: SWIS approximated by the whole of Western
# Australia (state polygon), NEM by the rest of the country
states = gpd.read_file(DATA / "ne_50m_admin_1_states_provinces")
states = states[states["adm0_a3"] == "AUS"]
egs = polygon_features(load_cells_cached(DATA, CELLS), states.geometry,
                       np.where(states["postal"] == "WA", "AUW", "AUN"))

new_rows = []
for iso3, meta in REGIONS.items():
    share = gen_share[iso3]
    r = {c: np.nan for c in df.columns}
    r.update(meta)
    r["iso3"] = iso3
    r["ember_year"] = wem_year if iso3 == "AUW" else aus["ember_year"]
    r["demand_twh"] = aus["demand_twh"] * share
    r["net_imports_twh"] = 0.0   # neither grid has an external tie
    r["net_import_share_pct"] = 0.0
    r["population"] = aus["population"] * pop_share[iso3]
    r["population_year"] = aus["population_year"]
    r["population_source"] = aus["population_source"]
    r["demand_year"] = aus["demand_year"]
    r["demand_source"] = aus["demand_source"]
    r["demand_kwh_per_capita"] = r["demand_twh"] * 1e9 / r["population"]
    r["demand_un_twh"] = aus["demand_un_twh"] * share
    r["demand_un_year"] = aus["demand_un_year"]
    r["population_2050"] = aus["population_2050"] * pop_share[iso3]
    r["demand_twh_2050"] = aus["demand_twh_2050"] * share
    r["demand_kwh_per_capita_2050"] = (r["demand_twh_2050"] * 1e9
                                       / r["population_2050"])
    r["total_generation_twh"] = total_gen[iso3]
    for fuel in FUELS:
        r[f"gen_{fuel}_twh"] = round(gen_r[iso3][fuel], 2)
        r[f"cap_{fuel}_gw"] = round(cap_r[iso3][fuel], 2)
    for fuel in ["coal", "gas", "other_fossil", "nuclear", "hydro", "wind",
                 "solar"]:
        r[f"share_{fuel}_pct"] = 100 * r[f"gen_{fuel}_twh"] / r["total_generation_twh"]
    r["share_fossil_pct"] = (r["share_coal_pct"] + r["share_gas_pct"]
                             + r["share_other_fossil_pct"])
    for fuel in ["solar", "wind"]:
        r[f"cf_{fuel}_realized"] = (
            r[f"gen_{fuel}_twh"] * 1000 / (r[f"cap_{fuel}_gw"] * 8760)
            if r[f"cap_{fuel}_gw"] > 0.1 else np.nan)
    r["geothermal_capacity_mw"] = aus["geothermal_capacity_mw"] if iso3 == "AUN" else 0.0
    r["plate_distance_km"] = haversine_km(
        meta["latitude"], meta["longitude"],
        vertices[:, 1], vertices[:, 0]).min()
    for col in FEATURE_COLUMNS + ["n_cells"]:
        r[col] = egs.at[iso3, col]
    r["geothermal_favourable"] = bool(
        is_favourable(r["geothermal_capacity_mw"], r["egs_suitable_share"]))
    r["is_island"] = True
    r["land_area_km2"] = area_km2[iso3]
    r["pop_density_per_km2"] = r["population"] / r["land_area_km2"]
    r["protected_area_pct"] = aus["protected_area_pct"]  # national value
    new_rows.append(r)

df = pd.concat([df[df["iso3"] != "AUS"], pd.DataFrame(new_rows)],
               ignore_index=True)
df.to_csv(OUT, index=False)

for r in new_rows:
    print(f"{r['iso3']}: demand {r['demand_twh']:.0f} TWh, "
          f"gen {r['total_generation_twh']:.0f} TWh, "
          f"fossil {r['share_fossil_pct']:.0f}%, "
          f"hydro {r['share_hydro_pct']:.1f}%, "
          f"wind CF {r['cf_wind_realized']:.2f}, "
          f"solar CF {r['cf_solar_realized']:.2f}, "
          f"plate {r['plate_distance_km']:.0f} km")
