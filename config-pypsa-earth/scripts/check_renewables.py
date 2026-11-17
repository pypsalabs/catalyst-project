# SPDX-License-Identifier: CC0-1.0
"""
Check how wind and solar enter the model, without rerunning anything.

Reads what the `now` stages left on disk (resources/<R>/renewable_profiles/, resources/<R>-now/powerplants.csv,
resources/<R>-now/bus_regions/, resources/<R>-now/resource_classes/, networks/<R>-now/elec.nc and elec_s_<n>_ec.nc), the
tables the model reads (calibration/2024/generation.csv) and powerplantmatching's cached IRENASTAT. Existing networks,
resources and results are not touched. Writes to model-doc/build/renewables_check/:

    cf.csv          stage, country, group (wind, solar): fleet GW, capacity factor of the fleet with the unadjusted
                    profiles of build_renewable_profiles (cf_raw), observed capacity factor of the table (cf_target),
                    factor needed and factor applied (electricity: capacity_factor_targets, clip), capacity factor in the
                    network (cf_model), whether the clip binds
    cf_carrier.csv  stage, country, carrier (onwind, offwind-ac, offwind-dc, solar): fleet GW, cf_raw, cf_model
    capacity.csv    stage, country, carrier (onwind, offwind, solar): GW of the plant list that the rule places
                    (list_gw) and of wind plants without an Onshore / Offshore tag (untagged_gw, not placed), IRENA of the
                    v0.9.0 default year and of the year of statistics.yaml, GW in the network (model_gw), GW the options
                    describe (intended_gw), GW of v0.9.0 (v090_gw), GW spread evenly, GW of the list above the statistic
    weights.csv     stage, country, carrier: fleet capacity factor after clustering with the installed capacity as
                    weight (the network) and with the potential as weight (v0.9.0), recomputed from the same profiles
    classes.csv     stage, carrier, bus, class: potential GW, capacity factor of the class profile, fleet GW of the
                    class files; the cluster's single generator they replace (single_*: potential, capacity factor,
                    fleet, from elec_s_<n>.nc) and the class generators of the network (model_*, from elec_s_<n>_ec.nc)
    fleets/<R>.csv  the wind and solar generators of elec.nc with both capacity factors (intermediate, reused)
    eligibility_NWE.npz  a box of north-east Scotland on a 200 m grid (Mollweide): land-cover class, protected areas, sea
                    depth, the country, its offshore zone, the zone within 30 km of the coast, and the share of each cell that is eligible for each of
                    the four carriers, computed with atlite from the rule's rasters, codes and buffers (only on request)
    cutouts.csv     stage: cutout, modules, bounds, cells, hours, GB, near-duplicate longitudes of the file

Usage (from config-pypsa-earth; about 15 min, the US profiles are the slow part):
    ../models/pypsa-earth/.pixi/envs/default/bin/python scripts/check_renewables.py [cf capacity weights classes cutouts eligibility]
"""
import logging
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

import powerplantmatching as pm  # noqa: E402
import pypsa  # noqa: E402
import xarray as xr  # noqa: E402
import yaml  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORK = os.path.join(HERE, "..", "models", "pypsa-earth")
OUT = os.path.join(HERE, "model-doc", "build", "renewables_check")
GENERATION = os.path.join(HERE, "calibration", "2024", "generation.csv")
# "US" is the former single stage of the contiguous US (until 2026-11-17), whose runs are still on disk and whose config is
# baseline/config.US.yaml; the stages are USW and USE now (README "US West / US East"). This check moves to them once
# they are built; the national statistics it compares with then belong to the sum of the two.
STAGES = "US BR IN CN NWE SG IS CA RU OCE NAM SAM MEA EUR AFR ASI".split()   # every stage with a `now` solve
RESOLVED = "US BR IN CN NWE".split()                                           # the spatially resolved regions
CARRIERS = ["onwind", "offwind-ac", "offwind-dc", "solar"]
GROUPS = {"wind": ["onwind", "offwind-ac", "offwind-dc"], "solar": ["solar"]}  # capacity_factor_targets: groups
DEFAULT_YEAR = 2023                                                            # estimate_renewable_capacities: year of v0.9.0


def stage_file(stage):
    """config.<stage>.yaml, or the config of a former stage kept in baseline/ (US)."""
    fn = os.path.join(HERE, f"config.{stage}.yaml")
    return fn if os.path.exists(fn) else os.path.join(HERE, "baseline", f"config.{stage}.yaml")

def statistics():
    with open(os.path.join(HERE, "statistics.yaml")) as f:
        return yaml.safe_load(f)


def network(stage, name="elec.nc"):
    d = os.path.join(FORK, "networks", f"{stage}-now")
    if name != "elec.nc":   # the clustered files carry the number of clusters in their name
        name = next(f for f in sorted(os.listdir(d)) if f.startswith("elec_s_") and f.endswith(name))
    return pypsa.Network(os.path.join(d, name))


def raw_profiles(stage, carrier):
    """Mean of the unadjusted profile and the potential weight per base-network bus."""
    fn = os.path.join(FORK, "resources", stage, "renewable_profiles", f"profile_{carrier}.nc")
    if not os.path.exists(fn):
        return pd.DataFrame(columns=["cf", "weight"])
    with xr.open_dataset(fn) as ds:
        if ds.sizes["bus"] == 0:
            return pd.DataFrame(columns=["cf", "weight"])
        return pd.DataFrame({"cf": ds["profile"].mean("time").to_pandas(), "weight": ds["weight"].to_pandas()})


def fleet(stage):
    """Wind and solar generators of elec.nc: country, carrier, p_nom, cf_raw, cf_model, potential weight.

    Kept in fleets/<stage>.csv (reading the US and China profiles takes minutes); delete the file to read again."""
    cache = os.path.join(OUT, "fleets", f"{stage}.csv")
    if os.path.exists(cache):
        return pd.read_csv(cache, index_col=0, dtype={"bus": str})
    g = _fleet(stage)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    g.to_csv(cache)
    return g


def _fleet(stage):
    n = network(stage)
    g = n.generators[n.generators.carrier.isin(CARRIERS)][["bus", "carrier", "p_nom", "p_nom_max"]].copy()
    w = n.snapshot_weightings.generators
    g["cf_model"] = n.generators_t.p_max_pu[g.index].mul(w, axis=0).sum() / w.sum()
    g["country"] = g.bus.map(n.buses.country)
    g["cf_raw"], g["potential"] = np.nan, np.nan
    for c in CARRIERS:
        raw = raw_profiles(stage, c)
        i = g.index[g.carrier == c]
        g.loc[i, "cf_raw"] = raw.cf.reindex(g.loc[i, "bus"]).values
        g.loc[i, "potential"] = raw.weight.reindex(g.loc[i, "bus"]).values
    return g


def weighted(g, col, by):
    return (g[col] * g.p_nom).groupby([g[k] for k in by]).sum() / g.p_nom.groupby([g[k] for k in by]).sum()


def cf(fleets):
    cfg = statistics()["electricity"]["capacity_factor_targets"]
    lo, hi = cfg.get("clip", [0.6, 1.4])
    target = pd.read_csv(GENERATION, comment="#").set_index(["country", "group"]).cf
    rows, carrier_rows = [], []
    for stage, g in fleets.items():
        g = g[g.p_nom > 0].assign(group=lambda d: d.carrier.map({c: k for k, v in GROUPS.items() for c in v}))
        t = pd.DataFrame({"gw": g.p_nom.groupby([g.country, g.group]).sum() / 1e3,
                          "cf_raw": weighted(g, "cf_raw", ["country", "group"]),
                          "cf_model": weighted(g, "cf_model", ["country", "group"])})
        t["cf_target"] = [target.get(i, np.nan) for i in t.index]
        t["factor_needed"] = t.cf_target / t.cf_raw
        t["factor_applied"] = t.factor_needed.clip(lo, hi)
        t["clip_binds"] = np.where(t.factor_needed > hi, "upper", np.where(t.factor_needed < lo, "lower", ""))
        t.loc[t.cf_target.isna() | (t.cf_target <= 0), ["factor_needed", "factor_applied", "clip_binds"]] = [np.nan, np.nan, "no target"]
        rows.append(t.reset_index().assign(stage=stage))
        c = pd.DataFrame({"gw": g.p_nom.groupby([g.country, g.carrier]).sum() / 1e3,
                          "cf_raw": weighted(g, "cf_raw", ["country", "carrier"]),
                          "cf_model": weighted(g, "cf_model", ["country", "carrier"])})
        carrier_rows.append(c.reset_index().assign(stage=stage))
    out = pd.concat(rows).set_index(["stage", "country", "group"]).round(4)
    out.to_csv(os.path.join(OUT, "cf.csv"))
    pd.concat(carrier_rows).set_index(["stage", "country", "carrier"]).round(4).to_csv(os.path.join(OUT, "cf_carrier.csv"))
    return out


def irena(year, countries):
    """GW per country and model carrier (offshore wind as one carrier), as get_irena_targets_for_carrier reads it."""
    mapping = statistics()["electricity"]["estimate_renewable_capacities"]["technology_mapping"]
    carrier = {tech: ("offwind" if v[0].startswith("offwind") else v[0]) for tech, v in mapping.items()}
    d = pm.data.IRENASTAT().powerplant.convert_country_to_alpha2()
    d = d[(d.Year == year) & d.Technology.isin(carrier) & d.Country.isin(countries)]
    return d.Capacity.groupby([d.Country, d.Technology.map(carrier)]).sum() / 1e3


def capacity(fleets):
    """Plant list, statistic and network per country and carrier, read as attach_wind_and_solar reads them."""
    cfg = statistics()["electricity"]["estimate_renewable_capacities"]
    year = cfg["year"]
    rows = []
    for stage, g in fleets.items():
        countries = sorted(g.country.dropna().unique())
        ppl = pd.read_csv(os.path.join(FORK, "resources", f"{stage}-now", "powerplants.csv"), index_col=0)
        ppl = ppl.powerplant.convert_country_to_alpha2()
        ppl = ppl[ppl.Fueltype.isin(["Wind", "Solar"])]
        # the rule places wind plants tagged Onshore / Offshore and every solar plant; other wind plants are not placed
        car = np.where(ppl.Fueltype == "Solar", "solar", np.where(ppl.Technology == "Offshore", "offwind",
                       np.where(ppl.Technology == "Onshore", "onwind", "untagged")))
        by = ppl.Capacity.groupby([ppl.Country.values, car]).sum() / 1e3
        g = g.assign(carrier=g.carrier.str.replace(r"-(ac|dc)$", "", regex=True))
        t = pd.DataFrame({"model_gw": g.p_nom.groupby([g.country, g.carrier]).sum() / 1e3,
                          "buses": g.bus.groupby([g.country, g.carrier]).nunique()})
        t["list_gw"] = by.reindex(t.index).fillna(0.0)
        t["untagged_gw"] = [by.get((c, "untagged"), 0.0) if k == "onwind" else 0.0 for c, k in t.index]
        t[f"irena_{DEFAULT_YEAR}_gw"] = irena(DEFAULT_YEAR, countries).reindex(t.index).fillna(0.0)
        stat = irena(year, countries).reindex(t.index).fillna(0.0)
        t[f"irena_{year}_gw"] = stat
        # what the options describe: the statistic where there is one (list above it scaled down, gap below it filled)
        t["intended_gw"] = np.where(stat > 0, stat, t.list_gw) if cfg.get("scale_down") else np.maximum(stat, t.list_gw)
        t["v090_gw"] = np.maximum(t[f"irena_{DEFAULT_YEAR}_gw"], t.list_gw)      # v0.9.0: gap to IRENA of its year filled
        t["spread_gw"] = (stat - t.list_gw).clip(lower=0.0)                      # gap, spread evenly over the buses
        t["above_statistic_gw"] = (t.list_gw - stat).clip(lower=0.0).where(stat > 0, 0.0)
        rows.append(t.rename_axis(["country", "carrier"]).reset_index().assign(stage=stage))
    out = pd.concat(rows).set_index(["stage", "country", "carrier"]).round(4)
    out.to_csv(os.path.join(OUT, "capacity.csv"))
    return out


def weights(fleets):
    """Fleet capacity factor after clustering, with capacity weights (the network) and potential weights (v0.9.0)."""
    rows = []
    for stage in RESOLVED:
        g = fleets[stage].copy()
        d = os.path.join(FORK, "resources", f"{stage}-now", "bus_regions")
        s = pd.read_csv(os.path.join(d, "busmap_elec_s.csv"), index_col=0, dtype=str).squeeze()
        cl = next(f for f in sorted(os.listdir(d)) if f.startswith("busmap_elec_s_"))
        c = pd.read_csv(os.path.join(d, cl), index_col=0, dtype=str).squeeze()
        s.index, c.index = s.index.astype(str), c.index.astype(str)
        g["cluster"] = g.bus.astype(str).map(s).map(c)
        g = g.dropna(subset=["cluster", "cf_model"])
        key = [g.cluster, g.carrier]
        capacity_weight = g.p_nom + 1e-3 * g.potential.fillna(0.0) / g.potential.groupby(g.carrier).transform("max")
        cl = pd.DataFrame({"country": g.country.groupby(key).first(), "p_nom": g.p_nom.groupby(key).sum(),
                           "cf_capacity": (g.cf_model * capacity_weight).groupby(key).sum() / capacity_weight.groupby(key).sum(),
                           "cf_potential": (g.cf_model * g.potential).groupby(key).sum() / g.potential.groupby(key).sum()})
        cl = cl[cl.p_nom > 0].reset_index()
        k = [cl.country, cl.carrier]
        t = pd.DataFrame({"gw": cl.p_nom.groupby(k).sum() / 1e3,
                          "cf_capacity_weight": (cl.cf_capacity * cl.p_nom).groupby(k).sum() / cl.p_nom.groupby(k).sum(),
                          "cf_potential_weight": (cl.cf_potential * cl.p_nom).groupby(k).sum() / cl.p_nom.groupby(k).sum()})
        rows.append(t.reset_index().assign(stage=stage))
    out = pd.concat(rows).set_index(["stage", "country", "carrier"]).round(4)
    out.to_csv(os.path.join(OUT, "weights.csv"))
    return out


def classes():
    rows = []
    for stage in RESOLVED:
        d = os.path.join(FORK, "resources", f"{stage}-now", "resource_classes")
        files = sorted(f for f in os.listdir(os.path.join(FORK, "networks", f"{stage}-now")) if f.startswith("elec_s_"))
        clustered = min((f for f in files if f.count("_") == 2), key=len)             # elec_s_<n>.nc, before the classes
        before = pypsa.Network(os.path.join(FORK, "networks", f"{stage}-now", clustered))
        after = pypsa.Network(os.path.join(FORK, "networks", f"{stage}-now", clustered.replace(".nc", "_ec.nc")))
        w = before.snapshot_weightings.generators
        for carrier in ["onwind", "solar"]:
            fn = next((f for f in sorted(os.listdir(d)) if f.startswith(f"classes_{carrier}_")), None)
            if fn is None:
                continue
            with xr.open_dataset(os.path.join(d, fn)) as ds:
                t = pd.DataFrame({"potential_gw": ds["p_nom_max"].to_series() / 1e3, "cf": ds["cf"].to_series(),
                                  "fleet_gw": ds["fleet_mw"].to_series() / 1e3}).reset_index()
            b = before.generators[before.generators.carrier == carrier]
            single = pd.DataFrame({"single_potential_gw": b.p_nom_max / 1e3, "single_fleet_gw": b.p_nom / 1e3,
                                   "single_cf": before.generators_t.p_max_pu[b.index].mul(w, axis=0).sum() / w.sum()})
            single.index = b.bus.values
            t = t.join(single, on="bus")
            a = after.generators[(after.generators.carrier == carrier) & after.generators.resource_class.notna()]
            model = pd.DataFrame({"bus": a.bus.values, "bin": a.resource_class.astype(int).values,
                                  "model_potential_gw": a.p_nom_max.values / 1e3, "model_fleet_gw": a.p_nom.values / 1e3,
                                  "model_cf": (after.generators_t.p_max_pu[a.index].mul(w, axis=0).sum() / w.sum()).values})
            t = t.merge(model, on=["bus", "bin"], how="left")
            rows.append(t.assign(stage=stage, carrier=carrier))
    out = pd.concat(rows).rename(columns={"bin": "class"}).set_index(["stage", "carrier", "bus", "class"]).round(4)
    out.to_csv(os.path.join(OUT, "classes.csv"))
    return out


ELIGIBILITY_STAGE = "NWE"                        # the run whose shapes and protected-area raster are read
ELIGIBILITY_BOX = (-3.0, 57.4, 260e3, 230e3)     # centre lon / lat and width / height [m]: north-east Scotland, Inverness to Aberdeen
AREA_CRS = "ESRI:54009"                          # crs: area_crs of the fork (Mollweide)


def eligibility(stage=ELIGIBILITY_STAGE, display=200):
    """Land eligibility of a box as build_renewable_profiles computes it (atlite, same rasters, codes and buffers)."""
    import functools

    import atlite
    import geopandas as gpd
    import rasterio
    from atlite.gis import shape_availability
    from rasterio.features import geometry_mask
    from rasterio.warp import Resampling, reproject
    from shapely.geometry import box as shapely_box

    with open(os.path.join(FORK, "config.default.yaml")) as f:
        renewable = yaml.safe_load(f)["renewable"]
    paths = dict(natura=os.path.join(FORK, "resources", stage, "natura.tiff"),
                 copernicus=os.path.join(FORK, "data/copernicus/PROBAV_LC100_global_v3.0.1_2019-nrt_Discrete-Classification-map_EPSG-4326.tif"),
                 gebco=os.path.join(FORK, "data/gebco/GEBCO_2025_sub_ice.nc"),
                 country=os.path.join(FORK, "resources", stage, "shapes/country_shapes.geojson"),
                 offshore=os.path.join(FORK, "resources", stage, "shapes/offshore_shapes.geojson"))
    lon, lat, width, height = ELIGIBILITY_BOX
    cx, cy = gpd.GeoSeries.from_xy([lon], [lat], crs=4326).to_crs(AREA_CRS).iloc[0].coords[0]
    geom = gpd.GeoSeries([shapely_box(cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)], crs=AREA_CRS)
    out = {}
    for tech in CARRIERS:
        cfg = renewable[tech]
        excluder = atlite.ExclusionContainer(crs=AREA_CRS, res=cfg.get("excluder_resolution", 100))
        if cfg.get("natura"):
            excluder.add_raster(paths["natura"], nodata=0, allow_no_overlap=True)
        cop = cfg["copernicus"]
        excluder.add_raster(paths["copernicus"], codes=cop["grid_codes"], invert=True, crs="EPSG:4326")
        if cop.get("distance", 0) > 0:
            excluder.add_raster(paths["copernicus"], codes=cop["distance_grid_codes"], buffer=cop["distance"], crs="EPSG:4326")
        if cfg.get("max_depth"):
            excluder.add_raster(paths["gebco"], codes=functools.partial(np.greater, -cfg["max_depth"]), crs="EPSG:4326", nodata=-1000)
        if cfg.get("min_shore_distance"):
            excluder.add_geometry(paths["country"], buffer=cfg["min_shore_distance"])
        if cfg.get("max_shore_distance"):
            excluder.add_geometry(paths["country"], buffer=cfg["max_shore_distance"], invert=True)
        masked, transform = shape_availability(geom, excluder)
        k = int(display / excluder.res)
        ny, nx = (masked.shape[0] // k) * k, (masked.shape[1] // k) * k
        out[f"eligible_{tech}"] = masked[:ny, :nx].reshape(ny // k, k, nx // k, k).mean(axis=(1, 3)).astype("float32")
        print(f"{tech}: {masked.mean():.1%} of the box eligible", flush=True)
    shape = out["eligible_onwind"].shape
    t = rasterio.Affine(display, 0, transform.c, 0, -display, transform.f)   # the display grid: `display` m cells
    for name, fn, resampling in [("landcover", paths["copernicus"], Resampling.mode), ("protected", paths["natura"], Resampling.nearest),
                                 ("depth", paths["gebco"], Resampling.bilinear)]:
        with rasterio.open(fn) as src:
            dst = np.zeros(shape, "float32")
            reproject(rasterio.band(src, 1), dst, dst_transform=t, dst_crs=AREA_CRS, resampling=resampling,
                      src_crs=src.crs or "EPSG:4326")
            out[name] = dst
    near = geom.buffer(60e3).iloc[0]                 # the shapes around the box, for the distance to the coast
    for name in ["country", "offshore"]:
        g = gpd.read_file(paths[name]).to_crs(AREA_CRS)
        out[name] = geometry_mask(g.geometry, shape, t, invert=True)
        if name == "country":                        # within max_shore_distance of the coast: the offwind-ac zone
            coast = g.geometry.intersection(near).buffer(renewable["offwind-ac"]["max_shore_distance"])
            out["near_shore"] = geometry_mask(coast, shape, t, invert=True)
    out["extent"] = np.array([t.c, t.c + shape[1] * display, t.f - shape[0] * display, t.f])   # left, right, bottom, top [m]
    np.savez_compressed(os.path.join(OUT, f"eligibility_{stage}.npz"), **out)
    codes, counts = np.unique(out["landcover"][out["country"]], return_counts=True)
    return pd.Series(counts / counts.sum(), codes.astype(int)).round(4)


def cutouts():
    rows = []
    for stage in STAGES:
        with open(stage_file(stage)) as f:
            cfg = yaml.safe_load(f)
        name = cfg["atlite"]["default"] if "default" in cfg.get("atlite", {}) else "cutout-2013-era5"
        spec = cfg["atlite"]["cutouts"][name]
        fn = os.path.join(FORK, "cutouts", name + ".nc")
        row = dict(stage=stage, cutout=name, build_cutout=bool(cfg.get("enable", {}).get("build_cutout", False)),
                   config_x=spec.get("x"), config_y=spec.get("y"), config_module=spec.get("module"))
        if os.path.exists(fn):
            with xr.open_dataset(fn) as ds:
                x, y = ds.x.values, ds.y.values
                step = np.median(np.diff(x))
                close = np.flatnonzero(np.diff(x) < step / 10)
                row.update(module=str(ds.attrs.get("module")), nx=len(x), ny=len(y), hours=ds.sizes["time"],
                           first_hour=str(ds.time.values[0])[:13], last_hour=str(ds.time.values[-1])[:13],
                           x0=x.min(), x1=x.max(), y0=y.min(), y1=y.max(), dx=round(float(step), 4),
                           gb=round(os.path.getsize(fn) / 1e9, 2), duplicate_longitudes=len(close),
                           first_duplicate=(round(float(x[close[0]]), 2) if len(close) else np.nan),
                           variables=len(ds.data_vars))
                if len(close):   # is one member of each pair empty? one hour of one variable is enough to tell
                    v = "wnd100m" if "wnd100m" in ds else list(ds.data_vars)[0]
                    a = ds[v].isel(time=0, x=np.r_[close, close + 1]).isnull().all("y").values
                    row["empty_duplicates"] = int(a.sum())
        rows.append(row)
    out = pd.DataFrame(rows).set_index("stage")
    out.to_csv(os.path.join(OUT, "cutouts.csv"))
    return out


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    todo = sys.argv[1:] or ["cf", "capacity", "weights", "classes", "cutouts"]
    pd.set_option("display.width", 250, "display.max_rows", 400)
    if "eligibility" in todo:
        print(eligibility().to_string())
    if "cutouts" in todo:
        print(cutouts().to_string())
    if "classes" in todo:
        c = classes()
        print(c.groupby(["stage", "carrier", "class"])[["potential_gw", "fleet_gw"]].sum().round(1).to_string())
    if {"cf", "capacity", "weights"} & set(todo):
        stages = RESOLVED if set(todo) & {"cf", "capacity", "weights"} == {"weights"} else STAGES
        fleets = {}
        for s in stages:
            fleets[s] = fleet(s)
            print(f"read {s}: {len(fleets[s])} generators", flush=True)
        if "cf" in todo:
            t = cf(fleets)
            print(t[t.gw > 5].to_string())
        if "capacity" in todo:
            t = capacity(fleets)
            print(t[t.model_gw > 10].to_string())
        if "weights" in todo:
            print(weights(fleets).to_string())
    print(f"-> {OUT}")
