"""Global land grid with rock temperature at the EGS cost-model depths.

Everywhere a steady-state 1-D conduction estimate, the physics of ../country-classification/geothermal_egs.py on a
configurable grid and for several depths:

    T(z) = T_surface + q0 z / k - A z^2 / (2 k)

q0 from build/heat_flow.nc (build_heat_flow.py: Lucazeau 2019, optionally sharpened with the IHFC 2024 points,
config thermal.heat_flow), T_surface from WorldClim 2.1, k and A from config.yaml. Where a reference temperature
model exists it replaces the estimate (config thermal.references, first one wins): the Stanford model over CONUS,
the Limberger 3-D model over Europe; `t_source` records which. Cells are labelled with the Natural Earth 50m
country (ISO3, name, continent, sub-region), for the USA and Australia with the admin-1 unit (for the West/East and
SWIS splits of the archetype work), and flagged `remote_territory` when they sit on a small blob of land far from
the country's main land (config grid.remote_territory). Ocean cells (no country polygon) are dropped.

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

HERE = Path(__file__).parent
if "snakemake" in globals():
    CFG = snakemake.config
    HF = Path(snakemake.input.heat_flow)
    OUT = Path(snakemake.output[0])
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    HF = HERE / "build" / "heat_flow.nc"
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


def conduction(t_surface, q_mwm2, depths_km, k, A):
    """Steady-state 1-D conduction, T(z) = T_s + q0 z / k - A z^2 / (2 k); (cell, depth) array in degC."""
    z = np.asarray(depths_km, dtype=float)[None, :] * 1000.0
    return t_surface[:, None] + (q_mwm2[:, None] * 1e-3) * z / k - A * z ** 2 / (2 * k)


def _unit(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


def _chord(km):
    return 2 * np.sin(km / (2 * EARTH_RADIUS_KM))


def remote_territory(cells, area, step, spec):
    """True for cells on land blobs (8-connected cells of one country) smaller than max_area_km2 that no chain of
    blobs, each within min_distance_km of the next, links to the country's largest blob or to a large blob."""
    from scipy.ndimage import label
    from scipy.spatial import cKDTree
    nlat, nlon = int(round(180 / step)), int(round(360 / step))
    i = np.clip(np.floor((cells["lat"].values + 90) / step).astype(int), 0, nlat - 1)
    k = np.floor((cells["lon"].values + 180) / step).astype(int) % nlon
    xyz = _unit(cells["lat"].values, cells["lon"].values)
    reach = _chord(spec["min_distance_km"])
    flag = np.zeros(len(cells), bool)
    for iso, idx in cells.groupby("iso3").indices.items():
        if len(idx) < 2:
            continue
        r0, r1, c0, c1 = i[idx].min(), i[idx].max(), k[idx].min(), k[idx].max()
        sub = np.zeros((r1 - r0 + 1, c1 - c0 + 1), bool)
        sub[i[idx] - r0, k[idx] - c0] = True
        lab, nb = label(sub, structure=np.ones((3, 3)))
        if nb < 2:
            continue
        blob = lab[i[idx] - r0, k[idx] - c0] - 1          # blobs split at the antimeridian re-link at distance ~0
        barea = np.bincount(blob, weights=area[idx], minlength=nb)
        linked = barea >= spec["max_area_km2"]
        linked[np.argmax(barea)] = True
        while True:
            tree = cKDTree(xyz[idx[linked[blob]]])
            new = [b for b in np.flatnonzero(~linked)
                   if np.isfinite(tree.query(xyz[idx[blob == b]], distance_upper_bound=reach)[0]).any()]
            if not new:
                break
            linked[new] = True
        flag[idx[~linked[blob]]] = True
    named = cells.loc[flag].groupby("country").size().sort_values(ascending=False)
    print(f"  remote territories: {flag.sum():,} cells, {area[flag].sum() / 1e3:,.0f} thousand km2 "
          f"({', '.join(f'{c} {n}' for c, n in named.head(8).items())}, ...)")
    return flag


def stanford_conus(cells, depths, spec):
    """Stanford thermal model (Aljubran & Horne 2024) at the nearest candidate project area within 0.5 deg."""
    from scipy.spatial import cKDTree
    ref = pd.read_csv(HERE / spec["file"], low_memory=False)
    cols = [f"MEAN{str(d).replace('.', '_')}" for d in depths]
    missing = [c for c in cols if c not in ref]
    if missing:
        raise ValueError(f"CONUS reference lacks depths {missing}; depths must stay 2.5..6.5 km with it enabled")
    ref = ref.dropna(subset=cols)
    out = np.full((len(cells), len(depths)), np.nan)
    us = np.flatnonzero((cells["iso3"] == "USA").values & (cells["lat"] < 50) & (cells["lon"] > -130))
    _, j = cKDTree(ref[["Latitude", "Longitude"]].values).query(cells.loc[us, ["lat", "lon"]].values)
    dist = np.hypot(ref["Latitude"].values[j] - cells.loc[us, "lat"].values, ref["Longitude"].values[j] - cells.loc[us, "lon"].values)
    out[us[dist < 0.5]] = ref[cols].values[j[dist < 0.5]]
    return out


def limberger_europe(cells, depths, spec):
    """Limberger 3-D temperature model of Europe: linear in depth to the fitted depths, then the mean of the voxel
    columns whose centre falls in each grid cell; cells without a column (coast slivers) take the nearest one
    within fill_km. Only cells of the configured domain."""
    from scipy.spatial import cKDTree
    step = CFG["grid"]["step_deg"]
    vox = xr.open_dataset(HERE / spec["file"])["temperature"]
    t = vox.interp(depth_m=np.asarray(depths, dtype=float) * 1000.0).values          # (depth, y, x)
    x, y = np.meshgrid(vox["x"].values, vox["y"].values)
    r = 6378137.0                                                                      # EPSG:3857 sphere
    lon = np.degrees(x / r).ravel()
    lat = np.degrees(2 * np.arctan(np.exp(y / r)) - np.pi / 2).ravel()
    t = t.reshape(len(depths), -1).T
    ok = np.isfinite(t).all(axis=1)
    lon, lat, t = lon[ok], lat[ok], t[ok]
    key = lambda la, lo: np.floor((la + 90) / step).astype(np.int64) * 100000 + np.floor((lo + 180) / step).astype(np.int64)
    means = pd.DataFrame(t).groupby(key(lat, lon)).mean()
    out = np.full((len(cells), len(depths)), np.nan)
    dom = ((cells["continent"].isin(spec.get("continents", [])) | cells["iso3"].isin(spec.get("extra_iso3", [])))
           & ~cells["iso3"].isin(spec.get("exclude_iso3", []))).values
    ck = key(cells["lat"].values, cells["lon"].values)
    has = dom & np.isin(ck, means.index.values)
    out[has] = means.loc[ck[has]].values
    gap = np.flatnonzero(dom & ~has)
    d, j = cKDTree(_unit(lat, lon)).query(_unit(cells["lat"].values[gap], cells["lon"].values[gap]),
                                          distance_upper_bound=_chord(spec["fill_km"]))
    fill = np.isfinite(d)
    out[gap[fill]] = t[j[fill]]
    print(f"  limberger_europe: {has.sum():,} cells from their own columns, {fill.sum():,} filled from a column "
          f"within {spec['fill_km']} km, {(~fill).sum():,} domain cells without data")
    return out


REFERENCES = {"stanford_conus": stanford_conus, "limberger_europe": limberger_europe}


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

    dlat = np.radians(step) * EARTH_RADIUS_KM
    dlon = np.radians(step) * EARTH_RADIUS_KM * np.cos(np.radians(cells["lat"].values))
    area = dlat * dlon
    remote = remote_territory(cells, area, step, CFG["grid"]["remote_territory"])

    # physics: conduction on the configured heat flow, and on plain Lucazeau for the comparison
    hf = xr.open_dataset(HF)
    hi = np.clip(np.floor((cells["lat"].values + 90) / step).astype(int), 0, hf.sizes["lat"] - 1)
    hk = np.floor((cells["lon"].values + 180) / step).astype(int) % hf.sizes["lon"]
    if not (np.allclose(hf["lat"].values[hi], cells["lat"]) and np.allclose(hf["lon"].values[hk], cells["lon"])):
        raise ValueError("heat-flow grid and land cells are not aligned (grid.step_deg changed?)")
    q_luc = hf["q_lucazeau"].values[hi, hk].astype(float)
    q_ghfdb = hf["q_ghfdb_residual"].values[hi, hk].astype(float)
    q = hf[f"q_{CFG['thermal']['heat_flow']}"].values[hi, hk].astype(float)
    tl, tn, tarr = surface_temperature()
    ilat = np.clip(np.searchsorted(tl, cells["lat"].values) - 1, 0, tarr.shape[0] - 1)
    ilon = np.clip(np.searchsorted(tn, cells["lon"].values) - 1, 0, tarr.shape[1] - 1)
    ts = tarr[ilat, ilon]
    t_c = conduction(ts, q, depths, k, A)
    t_conduction = t_c.copy()

    # reference models replace the conduction estimate where they exist, first one in config order wins
    source = np.full(len(cells), "conduction", dtype=object)
    t_ref = {}
    for name, spec in CFG["thermal"]["references"].items():
        if not spec.get("enabled", True):
            continue
        t = REFERENCES[name](cells, depths, spec)
        t_ref[name] = t
        hit = np.isfinite(t).all(axis=1) & (source == "conduction")
        t_c[hit] = t[hit]
        source[hit] = name
        print(f"  {name}: {hit.sum():,} cells take the reference model")

    ds = xr.Dataset(
        {
            "lon": ("cell", cells["lon"].values), "lat": ("cell", cells["lat"].values),
            "area_km2": ("cell", area),
            "iso3": ("cell", cells["iso3"].values.astype(str)),
            "country": ("cell", cells["country"].values.astype(str)),
            "continent": ("cell", cells["continent"].values.astype(str)),
            "subregion": ("cell", cells["subregion"].values.astype(str)),
            "admin1": ("cell", cells["admin1"].values.astype(str)),
            "remote_territory": ("cell", remote.astype("int8")),
            "heat_flow_mwm2": ("cell", q),
            "heat_flow_lucazeau_mwm2": ("cell", q_luc),
            "heat_flow_ghfdb_mwm2": ("cell", q_ghfdb),
            "t_surface_c": ("cell", ts),
            "air_temp_k": ("cell", ts + 273.15),
            "t_c": (("cell", "depth"), t_c),
            "t_conduction_c": (("cell", "depth"), t_conduction),
            "t_conduction_lucazeau_c": (("cell", "depth"), conduction(ts, q_luc, depths, k, A)),
            "t_source": ("cell", source.astype(str)),
            **{f"t_ref_{n}_c": (("cell", "depth"), t) for n, t in t_ref.items()},
        },
        coords={"cell": np.arange(len(cells)), "depth": depths},
        attrs={"grid_step_deg": step, "conductivity_w_mk": k, "heat_production_w_m3": A,
               "heat_flow": f"{CFG['thermal']['heat_flow']} (build_heat_flow.py: {hf.attrs['lucazeau']}; "
                            f"residuals from {hf.attrs['ghfdb']}, length {hf.attrs['length_km']:g} km, shrinkage {hf.attrs['shrinkage']:g})",
               "references": ", ".join(t_ref),
               "surface_temperature": "WorldClim 2.1 annual mean tavg 1970-2000, 10 arcmin",
               "polygons": "Natural Earth 50m admin-0 / admin-1"},
    )
    ds["t_c"].attrs["long_name"] = "rock temperature at depth used downstream (conduction, or the reference model named in t_source)"
    ds["t_conduction_c"].attrs["long_name"] = "rock temperature at depth, steady-state conduction on heat_flow_mwm2 everywhere"
    ds["t_conduction_lucazeau_c"].attrs["long_name"] = "the same on plain Lucazeau heat flow (the pre-2026-10-09 estimate)"
    ds["heat_flow_ghfdb_mwm2"].attrs["long_name"] = "Lucazeau sharpened with the IHFC 2024 points (build_heat_flow.py), for validation"
    ds["remote_territory"].attrs["long_name"] = "1 = land blob not linked to the country's main land (config grid.remote_territory)"
    for n in t_ref:
        ds[f"t_ref_{n}_c"].attrs["long_name"] = f"reference model {n} where it exists (NaN elsewhere), before precedence"
    ds["depth"].attrs["units"] = "km"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(OUT)
    for d in depths:
        share = (t_c[:, list(depths).index(d)] >= 150).mean()
        print(f"  >= 150 C at {d} km: {share:5.1%} of land cells")


if __name__ == "__main__" or "snakemake" in globals():
    main()
