"""Merge the twelve countries of config-pypsa-earth/config.NWE.yaml into one grid row, NWE.

The modelled representative of the renewables-constrained, high-density
archetype is North-West Europe as a whole, not a single country:
Ireland, the UK, France, Benelux, Germany, Denmark, Switzerland, Austria, Czechia and Poland (the `countries` list of config-pypsa-earth/config.NWE.yaml) are one
synchronous / HVDC-coupled market region (GB and Ireland are tied to the
continent by DC interconnectors) and are modelled as one PyPSA network. This
script replaces their twelve national rows of country_features.csv with a
single NWE row so that the classifier,
the k-means cross-check and the map treat the region as one grid, in the
same way the split scripts treat US East / West.

Aggregation:
  sums       population, demand, 2050 projections, generation and capacity
             by fuel, land area, geothermal capacity, net imports (the
             members' net imports sum to the group's net imports because
             intra-group flows cancel)
  derived    per-capita demand, import share, generation shares, realized
             capacity factors and density are recomputed from the sums
  EGS        recomputed from the 0.1 deg cell grid over the union of the
             twelve Natural Earth polygons (clipped to Europe, so the French
             overseas departments drop out)
  borders    land borders with countries outside the group (GeoDataSource)
  means      protected-area share and PV yield are land-area weighted

Run via `snakemake -c1` (rule merge_nwe) or standalone after split_my.py:
  models/priam-myopic/.pixi/envs/default/bin/python merge_nwe.py
Reads build/features_my.csv, writes the FINAL country_features.csv.
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box
from shapely.ops import unary_union

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
    IN = _HERE / "build" / "features_my.csv"
    OUT = _HERE / "country_features.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

MEMBERS = ["IRL", "GBR", "FRA", "BEL", "NLD", "LUX", "DEU", "DNK", "CHE", "AUT", "CZE", "POL"]   # config-pypsa-earth/config.NWE.yaml
EUROPE_BOX = box(-15, 41, 25, 62)   # Ireland to eastern Poland, Corsica to Shetland; drops overseas France
META = {"iso3": "NWE", "iso2": "XW", "name": "North-West Europe",
        "capital": "Brussels", "latitude": 48.5, "longitude": 3.0}

FUELS = ["coal", "gas", "other_fossil", "nuclear", "hydro", "wind",
         "solar", "bioenergy", "other_renewables"]
SUM_COLS = (["population", "demand_twh", "demand_un_twh", "population_2050",
             "demand_twh_2050", "net_imports_twh", "total_generation_twh",
             "land_area_km2", "geothermal_capacity_mw"]
            + [f"gen_{f}_twh" for f in FUELS] + [f"cap_{f}_gw" for f in FUELS])
AREA_MEAN_COLS = ["protected_area_pct", "pvout_kwh_per_kwp_day"]

df = pd.read_csv(IN)
m = df[df["iso3"].isin(MEMBERS)]
missing = set(MEMBERS) - set(m["iso3"])
if missing:
    raise SystemExit(f"rows missing in {IN}: {sorted(missing)} - rerun build_features.py first.")

r = {c: np.nan for c in df.columns}
r.update(META)
for c in SUM_COLS:
    r[c] = float(m[c].fillna(0).sum())
w = m["land_area_km2"].fillna(0)
for c in AREA_MEAN_COLS:
    r[c] = float((m[c] * w).sum() / w.sum())
for c in ["ember_year", "demand_year", "population_year", "demand_un_year"]:
    r[c] = m[c].max()
for c in ["population_source", "demand_source"]:
    r[c] = m[c].mode().iloc[0]

r["demand_kwh_per_capita"] = r["demand_twh"] * 1e9 / r["population"]
r["demand_kwh_per_capita_2050"] = r["demand_twh_2050"] * 1e9 / r["population_2050"]
r["net_import_share_pct"] = 100 * r["net_imports_twh"] / r["demand_twh"]
r["pop_density_per_km2"] = r["population"] / r["land_area_km2"]
for fuel in ["coal", "gas", "other_fossil", "nuclear", "hydro", "wind", "solar"]:
    r[f"share_{fuel}_pct"] = 100 * r[f"gen_{fuel}_twh"] / r["total_generation_twh"]
r["share_fossil_pct"] = (r["share_coal_pct"] + r["share_gas_pct"]
                         + r["share_other_fossil_pct"])
for fuel in ["solar", "wind"]:
    r[f"cf_{fuel}_realized"] = (
        r[f"gen_{fuel}_twh"] * 1000 / (r[f"cap_{fuel}_gw"] * 8760)
        if r[f"cap_{fuel}_gw"] > 0.1 else np.nan)
r["plate_distance_km"] = float(m["plate_distance_km"].min())
r["is_island"] = False

# land borders with non-members (GeoDataSource lists both directions)
borders = pd.read_csv(DATA / "GEODATASOURCE-COUNTRY-BORDERS.CSV").dropna(subset=["country_border_code"])
iso2 = set(m["iso2"])
ext = borders[borders["country_code"].isin(iso2) & ~borders["country_border_code"].isin(iso2)]
r["n_land_borders"] = int(ext["country_border_code"].nunique())

# EGS features over the union polygon
countries = gpd.read_file(DATA / "ne_50m_admin_0_countries")
geom = unary_union(countries[countries["ADM0_A3"].isin(MEMBERS)].geometry.values).intersection(EUROPE_BOX)
egs = polygon_features(load_cells_cached(DATA, CELLS), gpd.GeoSeries([geom]), ["NWE"])
for col in FEATURE_COLUMNS + ["n_cells"]:
    r[col] = egs.at["NWE", col]
r["geothermal_favourable"] = bool(
    is_favourable(r["geothermal_capacity_mw"], r["egs_suitable_share"]))

df = pd.concat([df[~df["iso3"].isin(MEMBERS)], pd.DataFrame([r])], ignore_index=True)
df.to_csv(OUT, index=False)

print(f"NWE: {len(MEMBERS)} members -> demand {r['demand_twh']:.0f} TWh "
      f"(2050: {r['demand_twh_2050']:.0f}), pop {r['population'] / 1e6:.0f} M, "
      f"{r['pop_density_per_km2']:.0f} /km2, {r['demand_kwh_per_capita']:.0f} kWh/cap, "
      f"imports {r['net_import_share_pct']:.1f}%, fossil {r['share_fossil_pct']:.0f}%, "
      f"nuclear {r['share_nuclear_pct']:.0f}%, hydro {r['share_hydro_pct']:.0f}%, "
      f"pvout {r['pvout_kwh_per_kwp_day']:.2f}, egs share {r['egs_suitable_share']:.2f}, "
      f"T5km p90 {r['t5km_p90_c']:.0f} C, {r['n_land_borders']} external borders")
