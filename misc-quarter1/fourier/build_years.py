"""Ten weather years at one place: hourly wind and solar capacity factors from ERA5 point weather
(Open-Meteo cache, see retrieve_weather.py) plus the site's PyPSA-Earth demand profile
(misc-quarter1/fourier).

  wind   100 m wind speed through the configured power curve (single turbine, no fleet smoothing)
  solar  fixed-tilt, equator-facing plane-of-array irradiance from GHI / DNI / DHI with a compact
         solar-position routine (NOAA-style), cell-temperature derating, system efficiency
  demand hourly p_set of the nearest clustered bus of the site's stage network (2013), reused
         for every weather year (the point is weather variability, not demand variability)

Leap days are dropped so every year has 8760 hours; all series are shifted to local solar
time (round(lon/15) h) and stored on a nominal non-leap calendar.

Outputs
  build/profiles_years.nc        time x series(year): cf_wind, cf_solar, demand_mw
  build/years.csv                per year: mean CFs, annual demand, worst anomaly |rho| to other years
  build/years_correlation.csv    cross-year correlation of the wind / solar anomaly bands

Standalone: python build_years.py
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import yaml

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("years")

if "snakemake" in globals():
    CFG = snakemake.config  # noqa: F821
    _HERE = Path(snakemake.input.config).resolve().parent  # noqa: F821
    WEATHER = [Path(p) for p in snakemake.input.weather]  # noqa: F821
    NETWORK = Path(snakemake.input.network)  # noqa: F821
    OUT_PROFILES = Path(snakemake.output.profiles)  # noqa: F821
    OUT_YEARS = Path(snakemake.output.years)  # noqa: F821
    OUT_CORR = Path(snakemake.output.correlation)  # noqa: F821
else:
    _HERE = Path(__file__).resolve().parent
    CFG = yaml.safe_load((_HERE / "config.yaml").read_text())
    Y = CFG["years"]
    WEATHER = [_HERE / "data" / "openmeteo" / f"{Y['site']['key']}_{y}.csv" for y in range(Y["first"], Y["last"] + 1)]
    NETWORK = (_HERE / CFG["networks_dir"] / CFG["regions"][Y["site"]["region"]]["file"]).resolve()
    OUT_PROFILES = _HERE / "build" / "profiles_years.nc"
    OUT_YEARS = _HERE / "build" / "years.csv"
    OUT_CORR = _HERE / "build" / "years_correlation.csv"
OUT_PROFILES.parent.mkdir(parents=True, exist_ok=True)

Y = CFG["years"]
SITE = Y["site"]
LAT, LON = SITE["lat"], SITE["lon"]
UTC_OFFSET = int(round(LON / 15))
NOMINAL = pd.date_range("2013-01-01", periods=8760, freq="h")     # non-leap calendar for the common axis


# ---------------------------------------------------------------- conversion models
def wind_cf(ws: np.ndarray) -> np.ndarray:
    t = Y["wind_turbine"]
    return np.interp(ws, t["speed"], t["power"], left=0.0, right=0.0)


def solar_position(times: pd.DatetimeIndex, lat: float, lon: float):
    """Solar zenith and azimuth (deg) for UTC times; NOAA spreadsheet formulas (approx. 0.1 deg)."""
    jd = times.to_julian_date().values
    jc = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
    m = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    e = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    mr = np.radians(m)
    c = np.sin(mr) * (1.914602 - jc * (0.004817 + 0.000014 * jc)) + np.sin(2 * mr) * (0.019993 - 0.000101 * jc) + np.sin(3 * mr) * 0.000289
    true_long = l0 + c
    app_long = true_long - 0.00569 - 0.00478 * np.sin(np.radians(125.04 - 1934.136 * jc))
    obliq = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
    obliq_corr = obliq + 0.00256 * np.cos(np.radians(125.04 - 1934.136 * jc))
    decl = np.degrees(np.arcsin(np.sin(np.radians(obliq_corr)) * np.sin(np.radians(app_long))))
    y = np.tan(np.radians(obliq_corr / 2)) ** 2
    eot = 4 * np.degrees(
        y * np.sin(2 * np.radians(l0)) - 2 * e * np.sin(mr) + 4 * e * y * np.sin(mr) * np.cos(2 * np.radians(l0))
        - 0.5 * y * y * np.sin(4 * np.radians(l0)) - 1.25 * e * e * np.sin(2 * mr)
    )  # minutes
    minutes = (times.hour * 60 + times.minute + times.second / 60).values
    tst = (minutes + eot + 4 * lon) % 1440
    ha = np.where(tst / 4 < 0, tst / 4 + 180, tst / 4 - 180)
    latr, declr, har = np.radians(lat), np.radians(decl), np.radians(ha)
    cos_zen = np.sin(latr) * np.sin(declr) + np.cos(latr) * np.cos(declr) * np.cos(har)
    zen = np.degrees(np.arccos(np.clip(cos_zen, -1, 1)))
    az = np.degrees(np.arccos(np.clip(((np.sin(latr) * np.cos(np.radians(zen))) - np.sin(declr))
                                      / (np.cos(latr) * np.sin(np.radians(zen)) + 1e-12), -1, 1)))
    az = np.where(ha > 0, (az + 180) % 360, (540 - az) % 360)
    return zen, az


def solar_cf(w: pd.DataFrame) -> np.ndarray:
    """Fixed-tilt PV capacity factor from GHI/DNI/DHI (W/m2, preceding-hour means) and T2m."""
    p = Y["pv"]
    zen, az = solar_position(w.index - pd.Timedelta(minutes=30), LAT, LON)   # hour-centred sun position
    tilt = np.radians(p["tilt_deg"])
    surf_az = np.radians(180.0 if LAT >= 0 else 0.0)                          # equator-facing
    zr, azr = np.radians(zen), np.radians(az)
    cos_aoi = np.cos(zr) * np.cos(tilt) + np.sin(zr) * np.sin(tilt) * np.cos(azr - surf_az)
    cos_aoi = np.clip(cos_aoi, 0, None) * (zen < 90)
    poa = w.dni.values * cos_aoi + w.dhi.values * (1 + np.cos(tilt)) / 2 + w.ghi.values * p["albedo"] * (1 - np.cos(tilt)) / 2
    t_cell = w.t2m.values + poa * (p["noct_c"] - 20) / 800
    cf = poa / 1000 * (1 + p["temp_coeff"] * (t_cell - 25)) * p["system_efficiency"]
    return np.clip(cf, 0, 1)


def anomaly(df: pd.DataFrame, window_days: int) -> pd.DataFrame:
    daily = df.resample("1D").mean()
    trend = daily.rolling(window_days, center=True, min_periods=window_days // 2).mean()
    return (daily - trend).dropna()


# ---------------------------------------------------------------- weather years -> capacity factors
cf_w, cf_s = {}, {}
for path in WEATHER:
    w = pd.read_csv(path, index_col=0, parse_dates=True)
    w = w[~((w.index.month == 2) & (w.index.day == 29))]
    year = w.index[0].year
    assert len(w) == 8760, (path, len(w))
    cf_w[year] = np.roll(wind_cf(w.ws100.values), UTC_OFFSET)
    cf_s[year] = np.roll(solar_cf(w), UTC_OFFSET)
    log.info("%s  mean cf wind %.3f  solar %.3f  (ws100 mean %.1f m/s, GHI mean %.0f W/m2)",
             year, cf_w[year].mean(), cf_s[year].mean(), w.ws100.mean(), w.ghi.mean())
cf_w = pd.DataFrame(cf_w, index=NOMINAL)
cf_s = pd.DataFrame(cf_s, index=NOMINAL)

# ---------------------------------------------------------------- demand from the nearest stage bus
import pypsa  # noqa: E402

n = pypsa.Network(str(NETWORK))
ac = n.buses[n.buses.carrier == "AC"]
loads = n.loads_t.p_set.rename(columns=n.loads.bus.to_dict())
ac = ac[ac.index.isin(loads.columns)]
bus = ((ac.x - LON) ** 2 + (ac.y - LAT) ** 2).idxmin()
dem_bus = np.roll(loads[bus].values, UTC_OFFSET)
log.info("demand from bus %s at (%.2f, %.2f), %.1f TWh/a", bus, ac.at[bus, "x"], ac.at[bus, "y"], dem_bus.sum() / 1e6)
demand = pd.DataFrame({y: dem_bus for y in cf_w.columns}, index=NOMINAL)

# ---------------------------------------------------------------- cross-year independence (for the record)
win = CFG["selection"]["anomaly_window_days"]
rho_w, rho_s = anomaly(cf_w, win).corr(), anomaly(cf_s, win).corr()
worst = np.maximum(rho_w.abs(), rho_s.abs()).values.copy()
np.fill_diagonal(worst, 0)
log.info("worst cross-year anomaly |rho| = %.3f", worst.max())

years = pd.DataFrame({
    "mean_cf_wind": cf_w.mean(), "mean_cf_solar": cf_s.mean(), "load_twh": demand.sum() / 1e6,
    "worst_abs_rho": worst.max(axis=1),
}).rename_axis("year")
labels = [str(y) for y in cf_w.columns]
ds = xr.Dataset(
    {
        "cf_wind": (("time", "series"), cf_w.values),
        "cf_solar": (("time", "series"), cf_s.values),
        "demand_mw": (("time", "series"), demand.values),
    },
    coords={"time": NOMINAL.values, "series": labels},
    attrs={
        "series_kind": "year",
        "site": SITE["name"],
        "description": f"ERA5 point weather (Open-Meteo) at {SITE['name']} converted to capacity factors; demand "
                       f"= PyPSA-Earth bus {bus} 2013 profile in every year; local time (UTC{UTC_OFFSET:+d}); "
                       "leap days dropped; nominal calendar",
        "legend_title": f"Weather years at {SITE['name']} — lightness encodes this order in every row (light → dark)",
        "period_label": f"{labels[0]}–{labels[-1]}, one line per year",
        "demand_note": "same 2013 profile in every year",
    },
)
ds.to_netcdf(OUT_PROFILES)
years.to_csv(OUT_YEARS, float_format="%.4f")
pd.concat({"wind_anomaly": rho_w, "solar_anomaly": rho_s}, names=["kind", "year"]).to_csv(OUT_CORR, float_format="%.3f")
log.info("\n%s", years.to_string())
log.info("wrote %s, %s, %s", OUT_PROFILES, OUT_YEARS, OUT_CORR)
