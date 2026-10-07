"""Download one year of hourly ERA5 point weather from the Open-Meteo archive API
(misc-quarter1/weather-years). Cached as data/openmeteo/<key>_<year>.csv, UTC:

  time, ws100 (m/s at 100 m), ghi, dni, dhi (W/m2, mean of the preceding hour), t2m (degC)

Used by two rules: the Northern-Germany years (key northern-germany, Open-Meteo's default
`cell_selection=land`) and the site-years stencil points (key pt_<lat>_<lon>, `nearest`, so
the returned ERA5 cell is exactly the requested 0.25-degree cell centre).

Quota (free tier): 600 calls/min, 5,000/h, 10,000/day, one point-year of five hourly variables
weighs 13 calls. A "Daily" limit error stops the run with a message (rerun the next day; cached
files are skipped); "Minutely"/"Hourly" limits wait for the next boundary.

Standalone: python retrieve_weather.py <key> <lat> <lon> <year> [cell_selection]
"""

import sys
import time
from pathlib import Path

import pandas as pd
import requests

if "snakemake" in globals():
    LAT, LON, YEAR = snakemake.params.lat, snakemake.params.lon, int(snakemake.wildcards.year)  # noqa: F821
    CELL = snakemake.params.get("cell_selection", "land")  # noqa: F821
    OUT = Path(snakemake.output[0])  # noqa: F821
else:
    key, LAT, LON, YEAR = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4])
    CELL = sys.argv[5] if len(sys.argv) > 5 else "land"
    OUT = Path(__file__).resolve().parent / "data" / "openmeteo" / f"{key}_{YEAR}.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

if OUT.exists() and OUT.stat().st_size > 100_000:
    print("cached", OUT)
    sys.exit(0)

URL = "https://archive-api.open-meteo.com/v1/archive"
params = dict(
    latitude=LAT, longitude=LON, start_date=f"{YEAR}-01-01", end_date=f"{YEAR}-12-31",
    hourly="wind_speed_100m,shortwave_radiation,direct_normal_irradiance,diffuse_radiation,temperature_2m",
    models="era5", timezone="UTC", wind_speed_unit="ms", cell_selection=CELL,
)
for attempt in range(8):
    try:
        r = requests.get(URL, params=params, timeout=120)
    except requests.RequestException as e:                  # connection reset, timeout: retry
        print(f"attempt {attempt + 1}: {e}")
        time.sleep(10 * (attempt + 1))
        continue
    if r.ok:
        try:
            js = r.json()                                   # a 200 with an empty / HTML body happens under load: retry
            break
        except ValueError:
            print(f"attempt {attempt + 1}: HTTP 200 without JSON ({r.text[:60]!r})")
            time.sleep(10 * (attempt + 1))
            continue
    try:
        reason = r.json().get("reason", "")
    except ValueError:
        reason = r.text[:200]
    print(f"attempt {attempt + 1}: HTTP {r.status_code} {reason}")
    if "Daily" in reason:
        raise SystemExit("Open-Meteo daily quota exhausted: rerun the workflow tomorrow (cached years are skipped)")
    now = time.time()
    if "Hourly" in reason:
        time.sleep(3600 - now % 3600 + 5)
    elif "Minutely" in reason:
        time.sleep(60 - now % 60 + 2)
    else:
        time.sleep(10 * (attempt + 1))
else:
    raise SystemExit(f"Open-Meteo request failed for ({LAT}, {LON}) {YEAR}")

if CELL == "nearest":
    assert abs(js["latitude"] - LAT) < 0.01 and abs(js["longitude"] - LON) < 0.01, (js["latitude"], js["longitude"], LAT, LON)
h = js["hourly"]
df = pd.DataFrame(
    {"ws100": h["wind_speed_100m"], "ghi": h["shortwave_radiation"], "dni": h["direct_normal_irradiance"],
     "dhi": h["diffuse_radiation"], "t2m": h["temperature_2m"]},
    index=pd.to_datetime(h["time"]),
).rename_axis("time")
assert len(df) in (8760, 8784), len(df)
assert not df.isna().any().any(), f"NaN in {df.isna().sum().to_dict()}"
df.to_csv(OUT, float_format="%.3f")
print("wrote", OUT, len(df), "rows; ERA5 cell", js["latitude"], js["longitude"])
