"""Shared weather -> capacity-factor conversion for the Open-Meteo based datasets of
misc-quarter1/weather-years (build_years.py, build_siteyears.py). Pure functions, no I/O.

  wind_cf          100 m wind speed through a piecewise-linear power curve (single turbine)
  solar_position   solar zenith / azimuth for UTC times (NOAA spreadsheet formulas, ~0.1 deg)
  solar_cf         fixed-tilt, equator-facing PV from GHI / DNI / DHI with cell-temperature derating
  anomaly          daily mean minus a centred rolling mean: the synoptic band used for independence checks
  drop_leap        remove Feb 29 so every weather year has 8760 hours
"""

import numpy as np
import pandas as pd

NOMINAL = pd.date_range("2013-01-01", periods=8760, freq="h")     # non-leap calendar for the common axis


def wind_cf(ws: np.ndarray, turbine: dict) -> np.ndarray:
    """Power fraction for wind speeds `ws` (m/s) from the curve {speed: [...], power: [...]}."""
    return np.interp(ws, turbine["speed"], turbine["power"], left=0.0, right=0.0)


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


def solar_cf(w: pd.DataFrame, lat: float, lon: float, pv: dict) -> np.ndarray:
    """Fixed-tilt PV capacity factor from GHI/DNI/DHI (W/m2, preceding-hour means) and T2m.

    `w` has a UTC DatetimeIndex and columns ghi, dni, dhi, t2m; `pv` = {tilt_deg, albedo,
    temp_coeff, noct_c, system_efficiency}.
    """
    zen, az = solar_position(w.index - pd.Timedelta(minutes=30), lat, lon)   # hour-centred sun position
    tilt = np.radians(pv["tilt_deg"])
    surf_az = np.radians(180.0 if lat >= 0 else 0.0)                          # equator-facing
    zr, azr = np.radians(zen), np.radians(az)
    cos_aoi = np.cos(zr) * np.cos(tilt) + np.sin(zr) * np.sin(tilt) * np.cos(azr - surf_az)
    cos_aoi = np.clip(cos_aoi, 0, None) * (zen < 90)
    poa = w.dni.values * cos_aoi + w.dhi.values * (1 + np.cos(tilt)) / 2 + w.ghi.values * pv["albedo"] * (1 - np.cos(tilt)) / 2
    t_cell = w.t2m.values + poa * (pv["noct_c"] - 20) / 800
    cf = poa / 1000 * (1 + pv["temp_coeff"] * (t_cell - 25)) * pv["system_efficiency"]
    return np.clip(cf, 0, 1)


def anomaly(df: pd.DataFrame, window_days: int) -> pd.DataFrame:
    """Daily mean minus a centred rolling mean: the synoptic (weather-driven) band."""
    daily = df.resample("1D").mean()
    trend = daily.rolling(window_days, center=True, min_periods=window_days // 2).mean()
    return (daily - trend).dropna()


def drop_leap(w: pd.DataFrame) -> pd.DataFrame:
    """Remove Feb 29 from one weather year; the result must have 8760 rows."""
    w = w[~((w.index.month == 2) & (w.index.day == 29))]
    assert len(w) == 8760, len(w)
    return w
