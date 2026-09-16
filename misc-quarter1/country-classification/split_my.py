"""Split the Malaysia row of country_features.csv into Peninsular and Borneo.

Peninsular Malaysia and Sabah+Sarawak (Malaysian Borneo) are two entirely
separate power systems - no interconnector exists or is under construction.
The national row blends two opposite archetypes: the Peninsula (~80% of
demand) is a coal/gas grid with only peaking hydro, while Sarawak is
hydro-dominated (Bakun/Murum run near-baseload for smelters) and exports
to Indonesian Borneo - a clean-firm-rich grid attracting energy-intensive
industry. The national 17.5% hydro share belongs almost entirely to Borneo.

Anchors: per-grid installed capacity from the Energy Commission's Malaysia
Energy Statistics Handbook 2023 (31 Dec 2021 table, data/ PDF); Borneo
generation from Sarawak Energy / IHA (hydro ~25 TWh ~ 73% of ~34 TWh, 2022)
and SESB/state reports for Sabah (~6.3 TWh, >80% gas), remainder split by
capacity x typical CFs. The Peninsular row is the national Ember row minus
Borneo, so year vintages mix (Ember 2025 vs ~2021-23) - screening grade.

Inputs (data/): Malaysia_Energy_Statistics_Handbook_2023.pdf (source of the
hardcoded capacities), ne_50m_admin_0_countries (EGS polygon split at 106E).

Run via `snakemake -c1` (rule split_my) or standalone after split_au.py:
  models/priam-myopic/.pixi/envs/default/bin/python split_my.py
Reads build/features_au.csv, writes build/features_my.csv (MYS row -> MYW +
MYE rows); merge_nwe.py then writes the final country_features.csv.
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
    IN = _HERE / "build" / "features_au.csv"
    OUT = _HERE / "build" / "features_my.csv"
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


# Borneo (MYE = Sabah + Sarawak + Labuan) generation, TWh:
#   Sarawak ~34 TWh (2022): hydro 25.0 (IHA/Sarawak Energy: 73%, Bakun and
#   Murum run near-baseload for the Samalaju smelters), coal 6.0, gas 3.5,
#   diesel 0.2, biomass 0.2 - the non-hydro split follows capacity x CF.
#   Sabah ~6.3 TWh (2023, SESB/state reports, >80% gas): gas 5.0,
#   diesel/MFO 0.55, hydro 0.35, biomass/biogas 0.25, solar 0.15.
MYE_GEN_TWH = {"coal": 6.0, "gas": 8.5, "other_fossil": 0.75, "hydro": 25.35,
               "solar": 0.15, "bioenergy": 0.45}

# Installed capacity, GW - Malaysia Energy Statistics Handbook 2023,
# "Installed Capacity as of 31 December 2021" (Sabah + Sarawak subtotals;
# diesel/MFO -> other_fossil, biomass+biogas+others -> bioenergy)
MYE_CAP_GW = {"coal": 1.104, "gas": 2.588, "other_fossil": 0.393,
              "hydro": 3.571, "solar": 0.114, "bioenergy": 0.242}

# DOSM 2024: Sabah 3.6 M + Sarawak 2.5 M + Labuan 0.1 M of 34.1 M national
MYE_POP_SHARE = 6.2 / 34.1
MYE_AREA_KM2 = 198_447   # Sabah 73,904 + Sarawak 124,450 + Labuan 91

REGIONS = {
    "MYW": {"iso2": "XP", "name": "Malaysia (Peninsular)",
            "capital": "Kuala Lumpur", "latitude": 3.14, "longitude": 101.69,
            # Global Solar Atlas map readings per footprint - approximate
            "pvout_kwh_per_kwp_day": 3.8,
            "n_land_borders": 1},   # Thailand (plus HVDC/HVAC ties to
                                    # Singapore and Thailand)
    "MYE": {"iso2": "XB", "name": "Malaysia (Borneo)", "capital": "Kuching",
            "latitude": 1.55, "longitude": 110.34,
            "pvout_kwh_per_kwp_day": 3.6,
            "n_land_borders": 2},   # Brunei, Indonesia (Sarawak exports a
                                    # little to West Kalimantan)
}

FUELS = ["coal", "gas", "other_fossil", "nuclear", "hydro", "wind",
         "solar", "bioenergy", "other_renewables"]

df = pd.read_csv(IN)
mys = df[df["iso3"] == "MYS"]
if mys.empty:
    raise SystemExit(f"No MYS row in {IN} - rerun build_features.py first.")
mys = mys.iloc[0]

gen_r = {"MYE": {f: MYE_GEN_TWH.get(f, 0.0) for f in FUELS}}
cap_r = {"MYE": {f: MYE_CAP_GW.get(f, 0.0) for f in FUELS}}
# Peninsular = national Ember minus Borneo (vintages mix - screening grade)
gen_r["MYW"] = {f: max(np.nan_to_num(mys[f"gen_{f}_twh"]) - gen_r["MYE"][f], 0.0)
                for f in FUELS}
cap_r["MYW"] = {f: max(np.nan_to_num(mys[f"cap_{f}_gw"]) - cap_r["MYE"][f], 0.0)
                for f in FUELS}

total_gen = {r: sum(gen_r[r].values()) for r in REGIONS}
gen_share = {r: total_gen[r] / sum(total_gen.values()) for r in REGIONS}
pop_share = {"MYE": MYE_POP_SHARE, "MYW": 1 - MYE_POP_SHARE}
area_km2 = {"MYE": MYE_AREA_KM2, "MYW": mys["land_area_km2"] - MYE_AREA_KM2}

plates = json.loads((DATA / "PB2002_boundaries.json").read_text())
vertices = np.array(
    [pt for f in plates["features"] for pt in f["geometry"]["coordinates"]])

# EGS features: the two footprints are ~5 deg of longitude apart, so split
# the country multipolygon at 106E (Peninsula < 106 < Borneo)
countries = gpd.read_file(DATA / "ne_50m_admin_0_countries")
parts = (countries[countries["ADM0_A3"] == "MYS"]
         .explode(index_parts=False).reset_index(drop=True))
labels = np.where(parts.geometry.centroid.x < 106, "MYW", "MYE")
egs = polygon_features(load_cells_cached(DATA, CELLS), parts.geometry, labels)

new_rows = []
for iso3, meta in REGIONS.items():
    share = gen_share[iso3]
    r = {c: np.nan for c in df.columns}
    r.update(meta)
    r["iso3"] = iso3
    r["ember_year"] = mys["ember_year"] if iso3 == "MYW" else 2023
    r["demand_twh"] = mys["demand_twh"] * share
    # both national ties (Thailand HVAC, Singapore HVDC) land on the
    # Peninsula; Sarawak's small export to Kalimantan is ignored
    r["net_imports_twh"] = mys["net_imports_twh"] if iso3 == "MYW" else 0.0
    r["net_import_share_pct"] = 100 * r["net_imports_twh"] / r["demand_twh"]
    r["population"] = mys["population"] * pop_share[iso3]
    r["population_year"] = mys["population_year"]
    r["population_source"] = mys["population_source"]
    r["demand_year"] = mys["demand_year"]
    r["demand_source"] = mys["demand_source"]
    r["demand_kwh_per_capita"] = r["demand_twh"] * 1e9 / r["population"]
    r["demand_un_twh"] = mys["demand_un_twh"] * share
    r["demand_un_year"] = mys["demand_un_year"]
    r["population_2050"] = mys["population_2050"] * pop_share[iso3]
    r["demand_twh_2050"] = mys["demand_twh_2050"] * share
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
    r["geothermal_capacity_mw"] = 0.0   # national is 0.1 MW; none operating
    r["plate_distance_km"] = haversine_km(
        meta["latitude"], meta["longitude"],
        vertices[:, 1], vertices[:, 0]).min()
    for col in FEATURE_COLUMNS + ["n_cells"]:
        r[col] = egs.at[iso3, col]
    r["geothermal_favourable"] = bool(
        is_favourable(r["geothermal_capacity_mw"], r["egs_suitable_share"]))
    r["is_island"] = False
    r["land_area_km2"] = area_km2[iso3]
    r["pop_density_per_km2"] = r["population"] / r["land_area_km2"]
    r["protected_area_pct"] = mys["protected_area_pct"]  # national value
    new_rows.append(r)

df = pd.concat([df[df["iso3"] != "MYS"], pd.DataFrame(new_rows)],
               ignore_index=True)
df.to_csv(OUT, index=False)

for r in new_rows:
    print(f"{r['iso3']}: demand {r['demand_twh']:.0f} TWh, "
          f"gen {r['total_generation_twh']:.0f} TWh, "
          f"fossil {r['share_fossil_pct']:.0f}%, "
          f"hydro {r['share_hydro_pct']:.1f}%, "
          f"solar CF {r['cf_solar_realized']:.2f}, "
          f"egs share {r['egs_suitable_share']:.2f}")
