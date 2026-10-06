"""Global land grid with modelled rock temperature at the EGS cost-model depths.

Same physics and inputs as ../country-classification/geothermal_egs.py, on a
configurable grid and for several depths:

    T(z) = T_surface + q0 z / k - A z^2 / (2 k)

q0 from the Lucazeau (2019) 0.5 deg heat-flow map, T_surface from WorldClim 2.1,
k and A from config.yaml. Cells are labelled with the Natural Earth 50m
country (ISO3, name, continent, sub-region) and, for the USA and Australia,
the admin-1 unit (for the West/East and SWIS splits of the archetype work).
Ocean cells (no country polygon) are dropped.

Output: build/temperature_grid.nc, dims (cell, depth).
Standalone: python build_temperature_grid.py
"""

import importlib.util
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
import yaml
from scipy.interpolate import RegularGridInterpolator

HERE = Path(__file__).parent
if "snakemake" in globals():
    CFG = snakemake.config
    OUT = Path(snakemake.output[0])
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    OUT = HERE / "build" / "temperature_grid.nc"

DATA = (HERE / CFG["archetype_data_dir"]).resolve()
EARTH_RADIUS_KM = 6371.0


def load_egs_module():
    """The archetype pipeline's module, for its Natural Earth ISO3 patching
    and point-in-polygon labelling."""
    path = DATA.parent / "geothermal_egs.py"
    spec = importlib.util.spec_from_file_location("geothermal_egs", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["geothermal_egs"] = mod
    spec.loader.exec_module(mod)
    return mod


def heat_flow_interpolator():
    hf = xr.open_dataset(DATA / "lucazeau2019_heat_flux_0p5deg.nc")
    lat, lon, q = hf["LAT"].values, hf["LON"].values, hf["heat_flux"].values
    order = np.argsort(((lon + 180) % 360) - 180)
    lon_s = ((lon[order] + 180) % 360) - 180
    q_s = q[:, order]
    lon_pad = np.concatenate([[lon_s[-1] - 360], lon_s, [lon_s[0] + 360]])
    q_pad = np.concatenate([q_s[:, -1:], q_s, q_s[:, :1]], axis=1)
    return RegularGridInterpolator((lat, lon_pad), q_pad, bounds_error=False, fill_value=None)


def surface_temperature():
    ts = xr.open_dataset(DATA / "worldclim21_tavg_annual_10m.nc")["tavg"].sortby("lat")
    arr = ts.values.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        zonal = np.nanmean(arr, axis=1)
    zonal = pd.Series(zonal).interpolate(limit_direction="both").values
    nan = np.isnan(arr)
    arr[nan] = np.broadcast_to(zonal[:, None], arr.shape)[nan]
    return ts["lat"].values, ts["lon"].values, arr


def main():
    egs = load_egs_module()
    step = CFG["grid"]["step_deg"]
    depths = np.array(CFG["grid"]["depths_km"], dtype=float)
    k = CFG["thermal"]["conductivity_w_mk"]
    A = CFG["thermal"]["heat_production_w_m3"]

    lats = np.arange(-90 + step / 2, 90, step)
    lons = np.arange(-180 + step / 2, 180, step)
    lon_g, lat_g = np.meshgrid(lons, lats)
    lon_g, lat_g = lon_g.ravel(), lat_g.ravel()
    cells = pd.DataFrame({"lon": lon_g, "lat": lat_g})

    # country labels (drops the ocean)
    countries = gpd.read_file(DATA / "ne_50m_admin_0_countries" / "ne_50m_admin_0_countries.shp")
    countries["iso3"] = egs.natural_earth_iso3(countries)
    countries = countries.dropna(subset=["iso3"])
    countries = countries[~countries["iso3"].isin(CFG["grid"].get("exclude_iso3", []))].reset_index(drop=True)
    idx = egs.assign_cells(cells, countries.geometry, countries.index.astype(object))
    keep = idx.notna().values
    cells = cells[keep].reset_index(drop=True)
    meta = countries.loc[idx[keep].astype(int).values, ["iso3", "NAME", "CONTINENT", "SUBREGION"]]
    cells["iso3"] = meta["iso3"].values
    cells["country"] = meta["NAME"].values
    cells["continent"] = meta["CONTINENT"].values
    cells["subregion"] = meta["SUBREGION"].values
    print(f"{len(cells):,} land cells at {step} deg")

    # admin-1 for the sub-national splits
    adm1 = gpd.read_file(DATA / "ne_50m_admin_1_states_provinces" / "ne_50m_admin_1_states_provinces.shp")
    adm1 = adm1[adm1["adm0_a3"].isin(["USA", "AUS"])].reset_index(drop=True)
    code = adm1["iso_3166_2"].str.split("-").str[-1]
    lab = egs.assign_cells(cells, adm1.geometry, code.astype(object))
    cells["admin1"] = lab.fillna("").values
    # coastal cells inside the country polygon but outside every state polygon: nearest state
    us_au = cells["iso3"].isin(["USA", "AUS"]) & (cells["admin1"] == "")
    if us_au.any():
        from scipy.spatial import cKDTree
        done = cells[cells["iso3"].isin(["USA", "AUS"]) & (cells["admin1"] != "")]
        tree = cKDTree(done[["lon", "lat"]].values)
        _, j = tree.query(cells.loc[us_au, ["lon", "lat"]].values)
        cells.loc[us_au, "admin1"] = done["admin1"].values[j]

    # physics
    q = heat_flow_interpolator()(np.column_stack([cells["lat"], cells["lon"]]))
    tl, tn, tarr = surface_temperature()
    ilat = np.clip(np.searchsorted(tl, cells["lat"].values) - 1, 0, tarr.shape[0] - 1)
    ilon = np.clip(np.searchsorted(tn, cells["lon"].values) - 1, 0, tarr.shape[1] - 1)
    ts = tarr[ilat, ilon]
    z = depths[None, :] * 1000.0
    t_c = ts[:, None] + (q[:, None] * 1e-3) * z / k - A * z ** 2 / (2 * k)

    t_conduction = t_c.copy()
    source = np.full(len(cells), "conduction", dtype=object)
    if CFG["thermal"].get("conus_override"):
        from scipy.spatial import cKDTree
        ref = pd.read_csv(HERE / CFG["thermal"]["conus_reference"], low_memory=False)
        cols = [f"MEAN{str(d).replace('.', '_')}" for d in depths]
        missing = [c for c in cols if c not in ref]
        if missing:
            raise ValueError(f"CONUS reference lacks depths {missing}; depths must stay 2.5..6.5 km with the override on")
        ref = ref.dropna(subset=cols)
        us = np.flatnonzero((cells["iso3"] == "USA").values & (cells["lat"] < 50) & (cells["lon"] > -130))
        _, j = cKDTree(ref[["Latitude", "Longitude"]].values).query(cells.loc[us, ["lat", "lon"]].values)
        dist = np.hypot(ref["Latitude"].values[j] - cells.loc[us, "lat"].values, ref["Longitude"].values[j] - cells.loc[us, "lon"].values)
        hit = us[dist < 0.5]
        t_c[hit] = ref[cols].values[j[dist < 0.5]]
        source[hit] = "stanford_conus"
        print(f"  CONUS override: {len(hit):,} US cells take the Stanford thermal model")

    dlat = np.radians(step) * EARTH_RADIUS_KM
    dlon = np.radians(step) * EARTH_RADIUS_KM * np.cos(np.radians(cells["lat"].values))
    area = dlat * dlon

    ds = xr.Dataset(
        {
            "lon": ("cell", cells["lon"].values), "lat": ("cell", cells["lat"].values),
            "area_km2": ("cell", area),
            "iso3": ("cell", cells["iso3"].values.astype(str)),
            "country": ("cell", cells["country"].values.astype(str)),
            "continent": ("cell", cells["continent"].values.astype(str)),
            "subregion": ("cell", cells["subregion"].values.astype(str)),
            "admin1": ("cell", cells["admin1"].values.astype(str)),
            "heat_flow_mwm2": ("cell", q),
            "t_surface_c": ("cell", ts),
            "air_temp_k": ("cell", ts + 273.15),
            "t_c": (("cell", "depth"), t_c),
            "t_conduction_c": (("cell", "depth"), t_conduction),
            "t_source": ("cell", source.astype(str)),
        },
        coords={"cell": np.arange(len(cells)), "depth": depths},
        attrs={"grid_step_deg": step, "conductivity_w_mk": k, "heat_production_w_m3": A,
               "heat_flow": "Lucazeau 2019 (de Lavergne & Maisonnave 2024 regridding, 0.5 deg)",
               "surface_temperature": "WorldClim 2.1 annual mean tavg 1970-2000, 10 arcmin",
               "polygons": "Natural Earth 50m admin-0 / admin-1"},
    )
    ds["t_c"].attrs["long_name"] = "rock temperature at depth used downstream (conduction, or Stanford model where t_source says so)"
    ds["t_conduction_c"].attrs["long_name"] = "rock temperature at depth, steady-state conduction everywhere"
    ds["depth"].attrs["units"] = "km"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(OUT)
    for d in depths:
        share = (t_c[:, list(depths).index(d)] >= 150).mean()
        print(f"  >= 150 C at {d} km: {share:5.1%} of land cells")


if __name__ == "__main__" or "snakemake" in globals():
    main()
