"""Extract ten mutually uncorrelated wind / solar / demand sites from the PyPSA-Earth
stage networks (misc-quarter1/fourier).

Reads the clustered, unsolved `elec_s_50.nc` networks of the stage regions listed in
config.yaml (weather year 2013, 8760 hourly snapshots), builds a candidate pool of every
clustered bus that has an `onwind` and a `solar` generator plus a load, and greedily
selects `n_sites` buses whose weather-driven fluctuations are mutually uncorrelated:

* independence metric: Pearson correlation of the *anomaly band* -- daily-mean capacity
  factor minus a centred `anomaly_window_days` rolling mean -- so the shared diurnal and
  seasonal cycles (which the spectrum is supposed to show) do not count as correlation;
* greedy max-min: start from the largest load, repeatedly add the candidate whose worst
  |rho| (wind or solar anomaly) against the already selected set is smallest, at most
  `max_sites_per_region` per region; abort if the worst pair exceeds `max_abs_corr`.

Each site's series are shifted to local solar time (round(longitude / 15) h) so diurnal
peaks line up across continents; the spectra are shift-invariant.

Outputs
  build/profiles_sites.nc    time x series (site): cf_wind, cf_solar, demand_mw (local time)
  build/sites.csv            site, region, bus, x, y, admin-1 name, load_TWh, mean CFs, utc_offset_h
  build/site_correlation.csv wind / solar anomaly and hourly-wind correlation matrices

Standalone: python extract_profiles.py   (reads config.yaml next to the script)
"""

import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
import yaml

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("extract")

if "snakemake" in globals():
    CFG = snakemake.config  # noqa: F821
    _HERE = Path(snakemake.input.config).resolve().parent  # noqa: F821
    OUT_PROFILES = Path(snakemake.output.profiles)  # noqa: F821
    OUT_SITES = Path(snakemake.output.sites)  # noqa: F821
    OUT_CORR = Path(snakemake.output.correlation)  # noqa: F821
else:
    _HERE = Path(__file__).resolve().parent
    CFG = yaml.safe_load((_HERE / "config.yaml").read_text())
    OUT_PROFILES = _HERE / "build" / "profiles_sites.nc"
    OUT_SITES = _HERE / "build" / "sites.csv"
    OUT_CORR = _HERE / "build" / "site_correlation.csv"
OUT_PROFILES.parent.mkdir(parents=True, exist_ok=True)

import pypsa  # noqa: E402  (slow import; after the cheap argument handling)

SEL = CFG["selection"]
REGIONS = CFG["regions"]           # ordered mapping region -> {file, label}
NETWORKS_DIR = (_HERE / CFG["networks_dir"]).resolve()


def load_region(region: str, spec: dict) -> dict:
    """Per-bus hourly wind CF, solar CF and demand (MW) for one stage network."""
    path = NETWORKS_DIR / spec["file"]
    log.info("reading %s", path)
    n = pypsa.Network(str(path))
    pu = n.generators_t.p_max_pu
    gens = n.generators
    have = {}
    for carrier in ("onwind", "solar"):
        g = gens[(gens.carrier == carrier) & gens.index.isin(pu.columns)]
        have[carrier] = pd.Series(g.index, index=g.bus.values)     # bus -> generator name
    loads = n.loads_t.p_set.rename(columns=n.loads.bus.to_dict())
    buses = sorted(set(have["onwind"].index) & set(have["solar"].index) & set(loads.columns))
    cf_w = pu[have["onwind"].loc[buses].values].set_axis(buses, axis=1)
    cf_s = pu[have["solar"].loc[buses].values].set_axis(buses, axis=1)
    dem = loads[buses]
    xy = n.buses.loc[buses, ["x", "y"]]
    return dict(cf_wind=cf_w, cf_solar=cf_s, demand=dem, xy=xy, snapshots=n.snapshots)


def anomaly(df: pd.DataFrame, window_days: int) -> pd.DataFrame:
    """Daily mean minus a centred rolling mean: the synoptic (weather-driven) band."""
    daily = df.resample("1D").mean()
    trend = daily.rolling(window_days, center=True, min_periods=window_days // 2).mean()
    return (daily - trend).dropna()


# ---------------------------------------------------------------- candidate pool
frames = {k: [] for k in ("cf_wind", "cf_solar", "demand")}
meta = []
for region, spec in REGIONS.items():
    d = load_region(region, spec)
    for k in frames:
        frames[k].append(d[k].add_prefix(f"{region}|"))
    m = d["xy"].copy()
    m.index = [f"{region}|{b}" for b in m.index]
    m["region"] = region
    m["bus"] = d["xy"].index
    meta.append(m)
cf_wind = pd.concat(frames["cf_wind"], axis=1)
cf_solar = pd.concat(frames["cf_solar"], axis=1)
demand = pd.concat(frames["demand"], axis=1)
meta = pd.concat(meta)
meta["load_twh"] = demand.sum() / 1e6
meta["mean_cf_wind"] = cf_wind.mean()
meta["mean_cf_solar"] = cf_solar.mean()
log.info("pool: %d buses with onwind + solar + load", len(meta))

ok = (
    (meta.mean_cf_wind >= SEL["min_mean_cf"]["wind"])
    & (meta.mean_cf_solar >= SEL["min_mean_cf"]["solar"])
    & (meta.load_twh >= SEL["min_load_twh"])
)
meta = meta[ok]
log.info("pool after resource / load screens: %d buses", len(meta))

# ---------------------------------------------------------------- correlation matrices
rho_w = anomaly(cf_wind[meta.index], SEL["anomaly_window_days"]).corr()
rho_s = anomaly(cf_solar[meta.index], SEL["anomaly_window_days"]).corr()
rho_wh = cf_wind[meta.index].corr()          # plain hourly wind CF, reported only
worst = np.maximum(rho_w.abs(), rho_s.abs())  # pairwise score: worst of the two technologies

# ---------------------------------------------------------------- greedy max-min selection
cap = SEL["max_sites_per_region"]
selected = [meta.load_twh.idxmax()]
while len(selected) < SEL["n_sites"]:
    counts = meta.loc[selected, "region"].value_counts()
    cands = [c for c in meta.index if c not in selected and counts.get(meta.at[c, "region"], 0) < cap]
    if not cands:
        raise SystemExit("candidate pool exhausted before n_sites reached; relax max_sites_per_region")
    score = worst.loc[cands, selected].max(axis=1)
    best = score.idxmin()
    log.info("  + %-14s worst |rho| to selected = %.3f  (%s, %.0f TWh, cf_w %.2f, cf_s %.2f)",
             best, score[best], meta.at[best, "region"], meta.at[best, "load_twh"],
             meta.at[best, "mean_cf_wind"], meta.at[best, "mean_cf_solar"])
    selected.append(best)

sub = worst.loc[selected, selected].values.copy()
np.fill_diagonal(sub, 0)
i, j = np.unravel_index(sub.argmax(), sub.shape)
log.info("worst pair: %s -- %s  |rho| = %.3f (wind %.3f, solar %.3f)", selected[i], selected[j], sub[i, j],
         rho_w.loc[selected[i], selected[j]], rho_s.loc[selected[i], selected[j]])
if sub.max() > SEL["max_abs_corr"]:
    raise SystemExit(
        f"selected sites are not independent enough: worst |rho| {sub.max():.3f} > "
        f"max_abs_corr {SEL['max_abs_corr']}; relax selection.max_abs_corr / max_sites_per_region"
    )

# ---------------------------------------------------------------- site names from Natural Earth
sites = meta.loc[selected].copy()
sites["utc_offset_h"] = np.round(sites.x / 15).astype(int)
pts = gpd.GeoDataFrame(sites[[]], geometry=gpd.points_from_xy(sites.x, sites.y), crs="EPSG:4326")
adm1 = gpd.read_file((_HERE / CFG["admin1_shapes"]).resolve())[["name", "geometry"]]
adm0 = gpd.read_file((_HERE / CFG["world_shapes"]).resolve())[["NAME", "geometry"]]
# no reprojection anywhere: PROJ data is absent in this env, plain lat/lon "within" is enough
j1 = gpd.sjoin(pts, adm1, how="left", predicate="within")
j0 = gpd.sjoin(pts, adm0, how="left", predicate="within")
sites["admin1"] = j1[~j1.index.duplicated()]["name"].reindex(sites.index)
sites["country"] = j0[~j0.index.duplicated()]["NAME"].reindex(sites.index)
place = sites.admin1.fillna(sites.country).fillna(sites.bus)   # admin-1 (missing for e.g. France) -> country -> bus
sites["site"] = [f"{REGIONS[r]['label']} · {p}" for r, p in zip(sites.region, place)]
for name, grp in sites.groupby("site"):                           # same place twice -> N / S by latitude
    if len(grp) > 1:
        ranked = grp.sort_values("y", ascending=False)
        for k, key in enumerate(ranked.index):
            sites.at[key, "site"] = f"{name} ({'N' if k == 0 else 'S' if k == len(ranked) - 1 else 'mid'})"
# order: config region order, then west -> east
order = {r: k for k, r in enumerate(REGIONS)}
sites = sites.sort_values(["region", "x"], key=lambda s: s.map(order) if s.name == "region" else s)
sites.index.name = "key"

# ---------------------------------------------------------------- local-time shift and write
time = cf_wind.index
def to_local(df: pd.DataFrame) -> np.ndarray:
    cols = []
    for key, off in sites.utc_offset_h.items():
        cols.append(np.roll(df[key].values, int(off)))   # local = UTC + offset -> values move later
    return np.column_stack(cols)

ds = xr.Dataset(
    {
        "cf_wind": (("time", "series"), to_local(cf_wind)),
        "cf_solar": (("time", "series"), to_local(cf_solar)),
        "demand_mw": (("time", "series"), to_local(demand)),
    },
    coords={"time": time.values, "series": sites.site.values},
    attrs={
        "description": "PyPSA-Earth clustered-bus hourly capacity factors and demand, weather year 2013, "
                       "shifted to local solar time (round(lon/15) h, circular over the year)",
        "networks": ", ".join(str(NETWORKS_DIR / s["file"]) for s in REGIONS.values()),
        "series_kind": "site",
        "legend_title": "Sites — lightness encodes this order in every row (light → dark)",
        "period_label": "2013, one line per site",
        "demand_note": "",
    },
)
ds.to_netcdf(OUT_PROFILES)
sites.to_csv(OUT_SITES, float_format="%.4f")

names = sites.site
corr = pd.concat(
    {
        "wind_anomaly": rho_w.loc[sites.index, sites.index].set_axis(names, axis=0).set_axis(names, axis=1),
        "solar_anomaly": rho_s.loc[sites.index, sites.index].set_axis(names, axis=0).set_axis(names, axis=1),
        "wind_hourly": rho_wh.loc[sites.index, sites.index].set_axis(names, axis=0).set_axis(names, axis=1),
    },
    names=["kind", "site"],
)
corr.to_csv(OUT_CORR, float_format="%.3f")

with pd.option_context("display.width", 200, "display.max_columns", 20):
    log.info("\n%s", sites[["site", "region", "bus", "x", "y", "load_twh", "mean_cf_wind", "mean_cf_solar", "utc_offset_h"]]
             .to_string(index=False))
log.info("wrote %s, %s, %s", OUT_PROFILES, OUT_SITES, OUT_CORR)
