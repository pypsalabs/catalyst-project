"""Ten sites x ten weather years: hourly wind and solar capacity factors from ERA5 point weather at a stencil of
cells around each site's wind and solar resource locations (Open-Meteo cache, see sample_points.py and
retrieve_weather.py), averaged over the stencil and calibrated to the resource bus's 2013 profile
(misc-quarter1/weather-years).

  wind    per point: 100 m wind speed x factor s through the years' power curve; mean over the points. s is one
          scalar per resource location (bisection within `speed_factor_range`) such that the 2013 stencil-mean
          wind CF equals the 2013 mean of the resource bus profile (ERA5 100 m speed vs atlite's hub-height / V112
          treatment and the potential-weighted area aggregate), or the location's `target_cf` for a hand-placed
          point (documented fleet capacity factor); s = 1 when there is neither.
  solar   per point: the years' fixed-tilt PV model at the point's coordinates; mean over the points, times one
          factor k per location matching the 2013 bus mean (k is close to 1; k = 1 for a hand-placed point).
  demand  the site bus's 2013 profile from profiles_sites.nc, reused in every weather year.

A missing point-year file (Open-Meteo quota) is skipped: the stencil mean is taken over the available points and
`n_points_min` records it. All series in local solar time (sites.csv utc_offset_h, as profiles_sites.nc), leap
days dropped, nominal calendar. The calibration year is reported, not stored as a weather year.

Outputs
  build/profiles_siteyears.nc    time x series ("<site> · <year>"): cf_wind, cf_solar, demand_mw; coords site, year
  build/siteyears.csv            per series: site, year, bus, x, y, mean CFs, load, factors, n_points_min
  build/siteyears_calibration.csv per site and resource: factor, target and 2013 statistics of the stencil mean vs the bus
  build/siteyears_2013.nc        time x site: bus, raw and calibrated 2013 series (for the validation figure; bus NaN for points)

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
LO, HI = SY["calibration"].get("speed_factor_range", [0.5, 2.5])

points = pd.read_csv(POINTS)
sites = pd.read_csv(SITES).set_index("key")
bus = xr.open_dataset(PROFILES)

# breadth-first downloads: keep only the weather years for which every stencil has at least one cached point
# (the calibration year must be complete enough everywhere); snakemake's rule asks for all files, the standalone
# run builds what is there
cells = points[["lat", "lon"]].drop_duplicates()
def _cached(y):
    return {(la, lo) for la, lo in cells.itertuples(index=False) if (CACHE / f"pt_{la:.2f}_{lo:.2f}_{y}.csv").exists()}
have = {y: _cached(y) for y in ALL_YEARS}
def _year_ok(y):
    return all(any((p.lat, p.lon) in have[y] for p in g.itertuples()) for _, g in points.groupby(["key", "resource"]))
if not _year_ok(CAL_YEAR):
    raise SystemExit(f"calibration year {CAL_YEAR} lacks every stencil point for some location")
skipped = [y for y in YEARS if not _year_ok(y)]
YEARS = [y for y in YEARS if _year_ok(y)]
ALL_YEARS = sorted(set(YEARS) | {CAL_YEAR})
if skipped:
    log.warning("weather years without cached points at some location, left out of the dataset: %s", skipped)
if not YEARS:
    raise SystemExit("no complete weather year in the cache")


def weather(lat: float, lon: float, year: int) -> pd.DataFrame | None:
    f = CACHE / f"pt_{lat:.2f}_{lon:.2f}_{year}.csv"
    if not f.exists():
        log.warning("missing point-year %s: stencil mean over the other points", f.name)
        return None
    return drop_leap(pd.read_csv(f, index_col=0, parse_dates=True))


def stats(ref: np.ndarray, x: np.ndarray) -> dict:
    """2013 agreement of a stencil series `x` with the bus series `ref` (both local time); NaN without a bus."""
    if np.isnan(ref).all():
        return {"mean": x.mean(), "r_hourly": np.nan, "r_daily": np.nan, "rmse": np.nan, "std_ratio": np.nan, "calm_share": (x < 0.05).mean()}
    daily = lambda v: v.reshape(365, 24).mean(axis=1)  # noqa: E731
    return {
        "mean": x.mean(), "r_hourly": np.corrcoef(ref, x)[0, 1], "r_daily": np.corrcoef(daily(ref), daily(x))[0, 1],
        "rmse": np.sqrt(np.mean((ref - x) ** 2)), "std_ratio": x.std() / ref.std(), "calm_share": (x < 0.05).mean(),
    }


cf, rows, cal_rows, val = {"wind": {}, "solar": {}}, [], [], {}
for key, s in sites.iterrows():
    off = int(s.utc_offset_h)
    n_min = {y: 10 ** 6 for y in YEARS}
    for r in ("wind", "solar"):
        pts = points[(points.key == key) & (points.resource == r)]
        wx = {y: [(p, weather(p.lat, p.lon, y)) for p in pts.itertuples()] for y in ALL_YEARS}
        n_pts = {y: sum(w is not None for _, w in wx[y]) for y in ALL_YEARS}
        if n_pts[CAL_YEAR] == 0 or any(n == 0 for n in n_pts.values()):
            raise SystemExit(f"{s.site} {r}: a year without any cached stencil point")
        for y in YEARS:
            n_min[y] = min(n_min[y], n_pts[y])
        ref = bus[f"cf_{r}"].sel(series=s.site).values
        target = float(s[f"{r}_target_cf"]) if not np.isnan(s[f"{r}_target_cf"]) else (float(np.nanmean(ref)) if not np.isnan(ref).all() else np.nan)
        if r == "wind":
            ws = {y: np.column_stack([w.ws100.values for _, w in wx[y] if w is not None]) for y in ALL_YEARS}
            stencil = lambda f, y: np.roll(wind_cf(f * ws[y], Y["wind_turbine"]).mean(axis=1), off)  # noqa: E731
            raw = stencil(1.0, CAL_YEAR)
            if np.isnan(target):
                factor = 1.0
            else:
                try:
                    factor = brentq(lambda f: stencil(f, CAL_YEAR).mean() - target, LO, HI, xtol=1e-5)
                except ValueError:
                    factor = LO if stencil(LO, CAL_YEAR).mean() > target else HI
                    log.warning("%s wind: target CF %.3f not reachable with a speed factor in [%.1f, %.1f]; using %.1f", s.site, target, LO, HI, factor)
            cal = stencil(factor, CAL_YEAR)
            series = {y: stencil(factor, y) for y in YEARS}
        else:
            sol = {y: np.column_stack([solar_cf(w, p.lat, p.lon, Y["pv"]) for p, w in wx[y] if w is not None]) for y in ALL_YEARS}
            stencil = lambda y: np.roll(sol[y].mean(axis=1), off)  # noqa: E731
            raw = stencil(CAL_YEAR)
            factor = 1.0 if np.isnan(target) else target / raw.mean()
            cal = np.clip(factor * raw, 0, 1)
            series = {y: np.clip(factor * stencil(y), 0, 1) for y in YEARS}
        for y in YEARS:
            cf[r][f"{s.site} · {y}"] = series[y]
        val.setdefault(s.site, {}).update({f"bus_{r}": ref, f"raw_{r}": raw, f"cal_{r}": cal})
        rec = {"key": key, "site": s.site, "resource": r, "location": s[f"{r}_name"], "bus": s[f"{r}_bus"], "x": s[f"{r}_x"], "y": s[f"{r}_y"],
               "n_points": n_pts[CAL_YEAR], "factor": factor, "target_cf": target, "bus_mean": float(np.nanmean(ref)) if not np.isnan(ref).all() else np.nan}
        for tag, x in (("raw", raw), ("cal", cal)):
            rec.update({f"{tag}_{k}": v for k, v in stats(ref, x).items()})
        cal_rows.append(rec)
        log.info("%-20s %-5s %-22s factor %.3f (raw cf %.3f -> %.3f, target %.3f, r %.2f, std ratio %.2f)", s.site, r, s[f"{r}_name"],
                 factor, raw.mean(), cal.mean(), target, rec["cal_r_hourly"], rec["cal_std_ratio"])
    demand = bus.demand_mw.sel(series=s.site).values
    for y in YEARS:
        name = f"{s.site} · {y}"
        rows.append({"series": name, "key": key, "site": s.site, "year": y, "region": s.region, "bus": s.bus, "x": s.x, "y": s.y,
                     "utc_offset_h": off, "mean_cf_wind": cf["wind"][name].mean(), "mean_cf_solar": cf["solar"][name].mean(),
                     "load_twh": demand.sum() / 1e6, "n_points_min": n_min[y]})
    for y in YEARS:
        cf.setdefault("demand", {})[f"{s.site} · {y}"] = demand

table = pd.DataFrame(rows)
cal = pd.DataFrame(cal_rows)
names = table.series.tolist()
ds = xr.Dataset(
    {
        "cf_wind": (("time", "series"), np.column_stack([cf["wind"][n] for n in names])),
        "cf_solar": (("time", "series"), np.column_stack([cf["solar"][n] for n in names])),
        "demand_mw": (("time", "series"), np.column_stack([cf["demand"][n] for n in names])),
    },
    coords={"time": NOMINAL.values, "series": names, "site": ("series", table.site.values), "year": ("series", table.year.values)},
    attrs={
        "series_kind": "siteyear",
        "description": f"ERA5 point weather (Open-Meteo) at a {SY['stencil']['n']}x{SY['stencil']['n']} stencil of cells "
                       f"({SY['stencil']['spacing_deg']} deg spacing) around each site's procurable wind and solar resource "
                       f"locations, converted to capacity factors, averaged over the stencil and calibrated to the resource "
                       f"bus's {CAL_YEAR} profile (wind: 100 m wind-speed factor; solar: capacity-factor factor; hand-placed points: "
                       "wind to a documented fleet CF, solar raw); demand = the site bus's 2013 profile in every year; local solar "
                       "time; leap days dropped; nominal calendar",
        "legend_title": "Sites x weather years", "period_label": f"{YEARS[0]}–{YEARS[-1]}, ten sites",
        "demand_note": "same 2013 profile in every year",
    },
)
assert ds.cf_wind.shape == (8760, len(sites) * len(YEARS)) and not ds.isnull().any().to_array().any()
ds.attrs["years"] = ", ".join(str(y) for y in YEARS)
ds.to_netcdf(OUT_PROFILES)
table.to_csv(OUT_TABLE, index=False, float_format="%.4f")
cal.to_csv(OUT_CAL, index=False, float_format="%.4f")
xr.Dataset(
    {v: (("time", "site"), np.column_stack([val[s][v] for s in sites.site])) for v in next(iter(val.values()))},
    coords={"time": NOMINAL.values, "site": sites.site.values},
    attrs={"description": f"{CAL_YEAR}: resource bus profile vs the stencil mean, raw and calibrated, local time (bus NaN for hand-placed points)"},
).to_netcdf(OUT_VAL)
with pd.option_context("display.width", 250, "display.max_columns", 30):
    log.info("\n%s", cal[["site", "resource", "location", "factor", "raw_mean", "target_cf", "cal_mean", "cal_r_hourly", "cal_std_ratio"]].round(3).to_string(index=False))
log.info("wrote %s (%d series), %s, %s, %s", OUT_PROFILES, len(names), OUT_TABLE, OUT_CAL, OUT_VAL)
