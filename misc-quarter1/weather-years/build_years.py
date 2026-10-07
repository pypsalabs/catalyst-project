"""Ten weather years at one place: hourly wind and solar capacity factors from ERA5 point weather
(Open-Meteo cache, see retrieve_weather.py; conversion functions in convert.py) plus the site's PyPSA-Earth demand profile
(misc-quarter1/weather-years).

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

from convert import NOMINAL, anomaly, drop_leap, solar_cf, wind_cf

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
    NETWORK = (_HERE / CFG["networks_dir"] / CFG["runs"][Y["site"]["run"]]).resolve()
    OUT_PROFILES = _HERE / "build" / "profiles_years.nc"
    OUT_YEARS = _HERE / "build" / "years.csv"
    OUT_CORR = _HERE / "build" / "years_correlation.csv"
OUT_PROFILES.parent.mkdir(parents=True, exist_ok=True)

Y = CFG["years"]
SITE = Y["site"]
LAT, LON = SITE["lat"], SITE["lon"]
UTC_OFFSET = int(round(LON / 15))


# ---------------------------------------------------------------- weather years -> capacity factors
cf_w, cf_s = {}, {}
for path in WEATHER:
    w = drop_leap(pd.read_csv(path, index_col=0, parse_dates=True))
    year = w.index[0].year
    cf_w[year] = np.roll(wind_cf(w.ws100.values, Y["wind_turbine"]), UTC_OFFSET)
    cf_s[year] = np.roll(solar_cf(w, LAT, LON, Y["pv"]), UTC_OFFSET)
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
win = Y["anomaly_window_days"]
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
