"""Ten sites x ten weather years: hourly wind and solar capacity factors from ERA5 point weather at a
stencil of cells around each PyPSA-Earth site (Open-Meteo cache, see sample_points.py and
retrieve_weather.py), averaged over the stencil and calibrated to the site's bus-aggregated 2013
profile (misc-quarter1/fourier).

  wind    per point: 100 m wind speed x factor s through the years' power curve; mean over the points.
          s is one scalar per site (bisection) such that the 2013 stencil-mean wind CF equals the 2013
          mean of the PyPSA-Earth bus profile (ERA5 100 m speed vs atlite's hub-height / V112 treatment
          and the potential-weighted area aggregate).
  solar   per point: the years' fixed-tilt PV model at the point's coordinates; mean over the points,
          times one factor k per site matching the 2013 bus mean (k is close to 1).
  demand  the site's own 2013 profile from profiles_sites.nc, reused in every weather year.

The calibration year is reported, not stored as a weather year. All series in local solar time
(sites.csv utc_offset_h, as profiles_sites.nc), leap days dropped, nominal calendar.

Outputs
  build/profiles_siteyears.nc    time x series ("<site> · <year>"): cf_wind, cf_solar, demand_mw; coords site, year
  build/siteyears.csv            per series: site, year, bus, x, y, mean CFs, load, factors, n_points
  build/siteyears_calibration.csv per site: factors and 2013 statistics of the stencil mean vs the bus (raw, calibrated)
  build/siteyears_2013.nc        time x site: bus, raw and calibrated 2013 series (for the validation figure)

Standalone: python build_siteyears.py
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import yaml
from scipy.optimize import brentq

from convert import NOMINAL, drop_leap, solar_cf, wind_cf

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("siteyears")

if "snakemake" in globals():
    CFG = snakemake.config  # noqa: F821
    _HERE = Path(snakemake.input.config).resolve().parent  # noqa: F821
    POINTS = Path(snakemake.input.points)  # noqa: F821
    SITES = Path(snakemake.input.sites)  # noqa: F821
    PROFILES = Path(snakemake.input.profiles)  # noqa: F821
    OUT_PROFILES = Path(snakemake.output.profiles)  # noqa: F821
    OUT_TABLE = Path(snakemake.output.table)  # noqa: F821
    OUT_CAL = Path(snakemake.output.calibration)  # noqa: F821
    OUT_VAL = Path(snakemake.output.validation)  # noqa: F821
else:
    _HERE = Path(__file__).resolve().parent
    CFG = yaml.safe_load((_HERE / "config.yaml").read_text())
    POINTS = _HERE / "build" / "siteyears_points.csv"
    SITES = _HERE / "build" / "sites.csv"
    PROFILES = _HERE / "build" / "profiles_sites.nc"
    OUT_PROFILES = _HERE / "build" / "profiles_siteyears.nc"
    OUT_TABLE = _HERE / "build" / "siteyears.csv"
    OUT_CAL = _HERE / "build" / "siteyears_calibration.csv"
    OUT_VAL = _HERE / "build" / "siteyears_2013.nc"
OUT_PROFILES.parent.mkdir(parents=True, exist_ok=True)
CACHE = _HERE / "data" / "openmeteo"

SY = CFG["siteyears"]
Y = CFG["years"]                       # power curve and PV model shared with the Northern-Germany years
CAL_YEAR = SY["calibration_year"]
YEARS = list(range(SY["first"], SY["last"] + 1))
ALL_YEARS = sorted(set(YEARS) | {CAL_YEAR})

points = pd.read_csv(POINTS)
sites = pd.read_csv(SITES).set_index("key")
bus = xr.open_dataset(PROFILES)


def weather(lat: float, lon: float, year: int) -> pd.DataFrame:
    return drop_leap(pd.read_csv(CACHE / f"pt_{lat:.2f}_{lon:.2f}_{year}.csv", index_col=0, parse_dates=True))


def stats(ref: np.ndarray, x: np.ndarray) -> dict:
    """2013 agreement of a stencil series `x` with the bus series `ref` (both local time)."""
    daily = lambda v: v.reshape(365, 24).mean(axis=1)  # noqa: E731
    return {
        "mean": x.mean(), "r_hourly": np.corrcoef(ref, x)[0, 1], "r_daily": np.corrcoef(daily(ref), daily(x))[0, 1],
        "rmse": np.sqrt(np.mean((ref - x) ** 2)), "std_ratio": x.std() / ref.std(), "calm_share": (x < 0.05).mean(),
    }


cf_w, cf_s, dem, rows, cal_rows, val = {}, {}, {}, [], [], {}
for key, s in sites.iterrows():
    pts = points[points.key == key]
    off = int(s.utc_offset_h)
    ws = {y: np.column_stack([weather(p.lat, p.lon, y).ws100.values for p in pts.itertuples()]) for y in ALL_YEARS}
    sol = {y: np.column_stack([solar_cf(weather(p.lat, p.lon, y), p.lat, p.lon, Y["pv"]) for p in pts.itertuples()]) for y in ALL_YEARS}
    ref_w = bus.cf_wind.sel(series=s.site).values
    ref_s = bus.cf_solar.sel(series=s.site).values

    # --- calibration on the overlap year (stencil mean, rolled to local time like the bus profile)
    def stencil_wind(factor: float, year: int) -> np.ndarray:
        return np.roll(wind_cf(factor * ws[year], Y["wind_turbine"]).mean(axis=1), off)

    def stencil_solar(year: int) -> np.ndarray:
        return np.roll(sol[year].mean(axis=1), off)

    raw_w, raw_s = stencil_wind(1.0, CAL_YEAR), stencil_solar(CAL_YEAR)
    if SY["calibration"]["wind"] == "speed":
        s_w = brentq(lambda f: stencil_wind(f, CAL_YEAR).mean() - ref_w.mean(), 0.5, 2.0, xtol=1e-5)
    else:
        raise ValueError(SY["calibration"]["wind"])
    if SY["calibration"]["solar"] == "cf":
        k_s = ref_s.mean() / raw_s.mean()
    else:
        raise ValueError(SY["calibration"]["solar"])
    cal_w, cal_s = stencil_wind(s_w, CAL_YEAR), np.clip(k_s * raw_s, 0, 1)
    val[s.site] = dict(bus_wind=ref_w, raw_wind=raw_w, cal_wind=cal_w, bus_solar=ref_s, raw_solar=raw_s, cal_solar=cal_s)
    rec = {"key": key, "site": s.site, "bus": s.bus, "n_points": len(pts), "wind_speed_factor": s_w, "solar_factor": k_s,
           "bus_mean_wind": ref_w.mean(), "bus_mean_solar": ref_s.mean()}
    for tech, ref, raw, cal in (("wind", ref_w, raw_w, cal_w), ("solar", ref_s, raw_s, cal_s)):
        rec[f"bus_calm_share_{tech}"] = (ref < 0.05).mean()
        for tag, x in (("raw", raw), ("cal", cal)):
            rec.update({f"{tag}_{k}_{tech}": v for k, v in stats(ref, x).items()})
    cal_rows.append(rec)
    log.info("%-24s s_wind %.3f (raw cf %.3f -> %.3f, r %.2f, std ratio %.2f)  k_solar %.3f (raw %.3f -> %.3f, r %.2f)",
             s.site, s_w, raw_w.mean(), cal_w.mean(), rec["cal_r_hourly_wind"], rec["cal_std_ratio_wind"],
             k_s, raw_s.mean(), cal_s.mean(), rec["cal_r_hourly_solar"])

    # --- the weather years
    demand = bus.demand_mw.sel(series=s.site).values
    for y in YEARS:
        name = f"{s.site} · {y}"
        cf_w[name] = stencil_wind(s_w, y)
        cf_s[name] = np.clip(k_s * stencil_solar(y), 0, 1)
        dem[name] = demand
        rows.append({"series": name, "key": key, "site": s.site, "year": y, "region": s.region, "bus": s.bus, "x": s.x, "y": s.y,
                     "utc_offset_h": off, "mean_cf_wind": cf_w[name].mean(), "mean_cf_solar": cf_s[name].mean(),
                     "load_twh": demand.sum() / 1e6, "wind_speed_factor": s_w, "solar_factor": k_s, "n_points": len(pts)})

table = pd.DataFrame(rows)
cal = pd.DataFrame(cal_rows).set_index("site")
names = table.series.tolist()
ds = xr.Dataset(
    {
        "cf_wind": (("time", "series"), np.column_stack([cf_w[n] for n in names])),
        "cf_solar": (("time", "series"), np.column_stack([cf_s[n] for n in names])),
        "demand_mw": (("time", "series"), np.column_stack([dem[n] for n in names])),
    },
    coords={"time": NOMINAL.values, "series": names, "site": ("series", table.site.values), "year": ("series", table.year.values)},
    attrs={
        "series_kind": "siteyear",
        "description": f"ERA5 point weather (Open-Meteo) at a {SY['stencil']['n']}x{SY['stencil']['n']} stencil of cells "
                       f"({SY['stencil']['spacing_deg']} deg spacing) around each PyPSA-Earth site, converted to capacity "
                       f"factors, averaged over the stencil and calibrated to the site's bus-aggregated {CAL_YEAR} profile "
                       "(wind: 100 m wind-speed factor; solar: capacity-factor factor); demand = the site's 2013 profile in "
                       "every year; local solar time; leap days dropped; nominal calendar",
        "legend_title": "Sites x weather years",
        "period_label": f"{YEARS[0]}–{YEARS[-1]}, ten sites",
        "demand_note": "same 2013 profile in every year",
    },
)
assert ds.cf_wind.shape == (8760, len(sites) * len(YEARS)) and not ds.isnull().any().to_array().any()
ds.to_netcdf(OUT_PROFILES)
table.to_csv(OUT_TABLE, index=False, float_format="%.4f")
cal.to_csv(OUT_CAL, float_format="%.4f")
xr.Dataset(
    {v: (("time", "site"), np.column_stack([val[s][v] for s in cal.index])) for v in next(iter(val.values()))},
    coords={"time": NOMINAL.values, "site": cal.index.values},
    attrs={"description": f"{CAL_YEAR}: PyPSA-Earth bus profile vs the stencil mean, raw and calibrated, local time"},
).to_netcdf(OUT_VAL)
with pd.option_context("display.width", 250, "display.max_columns", 30):
    log.info("\n%s", cal[["wind_speed_factor", "raw_mean_wind", "bus_mean_wind", "raw_r_hourly_wind", "cal_r_hourly_wind", "cal_std_ratio_wind",
                          "solar_factor", "raw_mean_solar", "cal_r_hourly_solar", "cal_std_ratio_solar"]].round(3).to_string())
log.info("wrote %s (%d series), %s, %s, %s", OUT_PROFILES, len(names), OUT_TABLE, OUT_CAL, OUT_VAL)
