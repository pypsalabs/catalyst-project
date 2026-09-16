"""Geothermal resource features from the Lucazeau (2019) global heat-flow map.

The single scalar we want per country is the share of its land area where
enhanced geothermal systems (EGS) could run a high-enthalpy power plant with
today's drilling: modelled rock temperature at 5 km depth >= 200 degC. 5 km
is the reach of current drilling (IEA Future of Geothermal 2024); 200 degC
is the industry's working threshold for flash / high-efficiency power rather
than the 150 degC binary-cycle minimum used by Aghahosseini & Breyer 2020.
At 150 degC ~31% of global land qualified and warm-surface tropical countries
on modest heat flow (Nigeria, Cambodia, the Gulf) scored 0.8-1.0; at 200 degC
only ~4% of land qualifies and the survivors are the recognisable
high-enthalpy provinces (Iceland, Japan, Chile, Philippines, Indonesia,
Mexico, Pannonian basin, Ethiopia, Turkiye, US West).

Temperature at depth is a steady-state 1-D conduction estimate:

    T(z) = T_surface + q0 * z / k - A * z^2 / (2 k)

with q0 the surface heat flow (Lucazeau 2019, 0.5 deg grid), T_surface the
WorldClim 2.1 annual mean air temperature, k = 2.5 W/m/K a typical crustal
conductivity and A = 1 uW/m^3 upper-crust radiogenic heat production (a 5 degC
correction at 5 km). At T_surface = 10 degC the cutoff corresponds to
q0 >= ~72 mW/m^2, against a continental mean of 67 mW/m^2.

Everything is evaluated on a 0.1 deg global grid of cell centres, each cell
weighted by cos(latitude) so shares are true area shares. Cells are assigned
to polygons (Natural Earth 50m countries or states) by point-in-polygon, so
large countries are handled correctly (the US scores on the West, Australia
on the Cooper Basin, Brazil low on its cold craton).

Data (data/):
  lucazeau2019_heat_flux_0p5deg.nc  - Lucazeau (2019) heat flow, as regridded
        to a regular 0.5 deg grid by de Lavergne & Maisonnave (2024), SEANOE
        doi:10.17882/103233 (CC-BY-4.0), file geothermal_forcing_regular.nc
  worldclim21_tavg_annual_10m.nc    - mean of the 12 WorldClim 2.1 10-arcmin
        monthly tavg rasters (1970-2000)
  PB2002_boundaries.json            - Bird (2003) plate boundaries
"""

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from scipy.interpolate import RegularGridInterpolator
from scipy.spatial import cKDTree
from shapely import contains_xy, prepare

EARTH_RADIUS_KM = 6371.0

GRID_STEP_DEG = 0.1
DEPTH_M = 5000.0
T_CUTOFF_C = 200.0
CONDUCTIVITY_W_MK = 2.5
HEAT_PRODUCTION_W_M3 = 1.0e-6
PLATE_RADIUS_KM = 300.0

FEATURE_COLUMNS = [
    "egs_suitable_share", "t5km_p90_c", "heat_flow_mean_mwm2",
    "plate_share_300km",
]

# screening flag ("has geothermal potential" camp): at least a tenth of the
# land is above 200 degC at 5 km, or a hydrothermal field is already
# producing. The capacity clause matters at this cutoff: the 0.5 deg heat-flow
# map cannot resolve narrow volcanic provinces, so New Zealand (Taupo), Kenya
# (rift) and Italy (Larderello) score only 0.04-0.07 on area share despite
# world-class fields. With T_CUTOFF_C = 200 the country-share quartiles are
# 0.00 / 0.01 / 0.07 and the 90th percentile 0.28, so 0.10 flags ~50 rows.
EGS_SHARE_FAVOURABLE = 0.10
CAPACITY_FAVOURABLE_MW = 10.0


def is_favourable(capacity_mw, egs_suitable_share):
    return ((np.asarray(capacity_mw) > CAPACITY_FAVOURABLE_MW)
            | (np.asarray(egs_suitable_share) >= EGS_SHARE_FAVOURABLE))


def temperature_at_depth(heat_flow_mwm2, t_surface_c, depth_m=DEPTH_M):
    q = np.asarray(heat_flow_mwm2, dtype=float) * 1e-3
    return (t_surface_c + q * depth_m / CONDUCTIVITY_W_MK
            - HEAT_PRODUCTION_W_M3 * depth_m ** 2 / (2 * CONDUCTIVITY_W_MK))


def _unit_vectors(lat_deg, lon_deg):
    lat, lon = np.radians(lat_deg), np.radians(lon_deg)
    return np.column_stack([np.cos(lat) * np.cos(lon),
                            np.cos(lat) * np.sin(lon),
                            np.sin(lat)])


def _plate_boundary_points(path, spacing_deg=0.1):
    """Vertices of the PB2002 boundaries, densified along each segment."""
    features = json.loads(Path(path).read_text())["features"]
    pts = []
    for f in features:
        coords = np.array(f["geometry"]["coordinates"], dtype=float)
        for (x0, y0), (x1, y1) in zip(coords[:-1], coords[1:]):
            n = max(2, int(np.hypot(x1 - x0, y1 - y0) / spacing_deg) + 1)
            pts.append(np.column_stack([np.linspace(x0, x1, n),
                                        np.linspace(y0, y1, n)]))
    return np.vstack(pts)


def load_cells(data_dir):
    """Global 0.1 deg cell table: lon, lat, weight, heat flow, T at 5 km,
    distance to the nearest plate boundary."""
    data_dir = Path(data_dir)

    hf = xr.open_dataset(data_dir / "lucazeau2019_heat_flux_0p5deg.nc")
    lat_hf = hf["LAT"].values
    lon_hf = hf["LON"].values                     # 0.25 .. 359.75
    q = hf["heat_flux"].values                    # (lat, lon), mW/m^2
    # to -180..180 with one wrap column on each side for periodic bilinear
    order = np.argsort(((lon_hf + 180) % 360) - 180)
    lon_sorted = ((lon_hf[order] + 180) % 360) - 180
    q_sorted = q[:, order]
    lon_pad = np.concatenate([[lon_sorted[-1] - 360], lon_sorted,
                              [lon_sorted[0] + 360]])
    q_pad = np.concatenate([q_sorted[:, -1:], q_sorted, q_sorted[:, :1]],
                           axis=1)
    hf_interp = RegularGridInterpolator((lat_hf, lon_pad), q_pad,
                                        bounds_error=False, fill_value=None)

    ts = xr.open_dataset(data_dir / "worldclim21_tavg_annual_10m.nc")["tavg"]
    ts = ts.sortby("lat")
    t_arr = ts.values.copy()
    # ocean/no-data cells: fill with the zonal mean of valid land cells so
    # coastal 0.1 deg cells still get a sensible surface temperature
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN polar rows
        zonal = np.nanmean(t_arr, axis=1)
    zonal = pd.Series(zonal).interpolate(limit_direction="both").values
    nan = np.isnan(t_arr)
    t_arr[nan] = np.broadcast_to(zonal[:, None], t_arr.shape)[nan]

    lats = np.arange(-90 + GRID_STEP_DEG / 2, 90, GRID_STEP_DEG)
    lons = np.arange(-180 + GRID_STEP_DEG / 2, 180, GRID_STEP_DEG)
    lon_g, lat_g = np.meshgrid(lons, lats)
    lon_g, lat_g = lon_g.ravel(), lat_g.ravel()

    heat_flow = hf_interp(np.column_stack([lat_g, lon_g]))
    ilat = np.clip(np.searchsorted(ts["lat"].values, lat_g) - 1, 0,
                   t_arr.shape[0] - 1)
    ilon = np.clip(np.searchsorted(ts["lon"].values, lon_g) - 1, 0,
                   t_arr.shape[1] - 1)
    t_surface = t_arr[ilat, ilon]

    plates = _plate_boundary_points(data_dir / "PB2002_boundaries.json")
    tree = cKDTree(_unit_vectors(plates[:, 1], plates[:, 0]))
    chord, _ = tree.query(_unit_vectors(lat_g, lon_g), workers=-1)
    plate_km = 2 * EARTH_RADIUS_KM * np.arcsin(np.clip(chord / 2, 0, 1))

    return pd.DataFrame({
        "lon": lon_g, "lat": lat_g,
        "weight": np.cos(np.radians(lat_g)),
        "heat_flow_mwm2": heat_flow,
        "t_surface_c": t_surface,
        "t5km_c": temperature_at_depth(heat_flow, t_surface),
        "plate_km": plate_km,
    })


def assign_cells(cells, geometries, labels):
    """Label each cell with the polygon containing it (NaN if none).
    Polygons are visited largest-first so small enclaves override."""
    out = np.full(len(cells), None, dtype=object)
    x, y = cells["lon"].values, cells["lat"].values
    order = np.argsort(-np.asarray([g.area for g in geometries]))
    geometries = list(geometries)
    labels = list(labels)
    for i in order:
        geom, label = geometries[i], labels[i]
        if geom is None or geom.is_empty or label is None:
            continue
        minx, miny, maxx, maxy = geom.bounds
        idx = np.flatnonzero((x >= minx) & (x <= maxx)
                             & (y >= miny) & (y <= maxy))
        if len(idx) == 0:
            continue
        prepare(geom)
        hit = contains_xy(geom, x[idx], y[idx])
        out[idx[hit]] = label
    return pd.Series(out, index=cells.index, name="label")


def aggregate(cells, labels):
    """Area-weighted features per label."""
    df = cells.assign(label=labels.values).dropna(subset=["label"])
    df["w_hot"] = df["weight"] * (df["t5km_c"] >= T_CUTOFF_C)
    df["w_plate"] = df["weight"] * (df["plate_km"] < PLATE_RADIUS_KM)
    df["w_hf"] = df["weight"] * df["heat_flow_mwm2"]
    g = df.groupby("label")
    sums = g[["weight", "w_hot", "w_plate", "w_hf"]].sum()

    def wp90(sub):
        s = sub.sort_values("t5km_c")
        cw = s["weight"].cumsum() / s["weight"].sum()
        return float(s["t5km_c"].values[np.searchsorted(cw, 0.9)])

    return pd.DataFrame({
        "egs_suitable_share": sums["w_hot"] / sums["weight"],
        "t5km_p90_c": g.apply(wp90, include_groups=False),
        "heat_flow_mean_mwm2": sums["w_hf"] / sums["weight"],
        "plate_share_300km": sums["w_plate"] / sums["weight"],
        "n_cells": g.size(),
    })


def polygon_features(cells, geometries, labels):
    return aggregate(cells, assign_cells(cells, geometries, labels))


def point_features(cells, lat, lon):
    """Fallback for polygons too small to hold a 0.1 deg cell centre: the
    nearest cell's values, expressed as 0/1 shares."""
    i = int(np.argmin((cells["lat"] - lat) ** 2 + (cells["lon"] - lon) ** 2))
    c = cells.iloc[i]
    return {
        "egs_suitable_share": float(c["t5km_c"] >= T_CUTOFF_C),
        "t5km_p90_c": float(c["t5km_c"]),
        "heat_flow_mean_mwm2": float(c["heat_flow_mwm2"]),
        "plate_share_300km": float(c["plate_km"] < PLATE_RADIUS_KM),
        "n_cells": 0,
    }


def natural_earth_iso3(countries):
    """ISO3 for the Natural Earth admin-0 table, patching its -99 entries."""
    iso = countries["ISO_A3"].where(countries["ISO_A3"] != "-99",
                                    countries["ISO_A3_EH"])
    iso = iso.where(iso != "-99", countries["ADM0_A3"])
    return iso.replace({"KOS": "XKX", "SOL": None, "CYN": None, "KAS": None,
                        "IOA": None, "ATC": None})


def load_cells_cached(data_dir, cache_path=None):
    """Read the precomputed cell table if present, else compute it fresh."""
    if cache_path is not None and Path(cache_path).exists():
        return pd.read_pickle(cache_path)
    return load_cells(data_dir)


# Snakemake entry point for rule egs_cells. Inert when this file is imported
# as a module: the `snakemake` object is injected only into the globals of the
# script a rule executes, never into modules that script imports.
if "snakemake" in globals():
    _out = Path(snakemake.output[0])
    _out.parent.mkdir(parents=True, exist_ok=True)
    load_cells(snakemake.params.data_dir).to_pickle(_out)
