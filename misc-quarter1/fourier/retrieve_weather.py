"""Download one year of hourly ERA5 point weather from the Open-Meteo archive API
(misc-quarter1/fourier). Cached as data/openmeteo/<site>_<year>.csv, UTC:

  time, ws100 (m/s at 100 m), ghi, dni, dhi (W/m2, mean of the preceding hour), t2m (degC)

Standalone: python retrieve_weather.py <key> <lat> <lon> <year>
"""

import sys
import time
from pathlib import Path

import pandas as pd
import requests

if "snakemake" in globals():
    LAT, LON, YEAR = snakemake.params.lat, snakemake.params.lon, int(snakemake.wildcards.year)  # noqa: F821
    OUT = Path(snakemake.output[0])  # noqa: F821
else:
    key, LAT, LON, YEAR = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4])
    OUT = Path(__file__).resolve().parent / "data" / "openmeteo" / f"{key}_{YEAR}.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

if OUT.exists() and OUT.stat().st_size > 100_000:
    print("cached", OUT)
    sys.exit(0)

URL = "https://archive-api.open-meteo.com/v1/archive"
params = dict(
    latitude=LAT, longitude=LON, start_date=f"{YEAR}-01-01", end_date=f"{YEAR}-12-31",
    hourly="wind_speed_100m,shortwave_radiation,direct_normal_irradiance,diffuse_radiation,temperature_2m",
    models="era5", timezone="UTC", wind_speed_unit="ms",
)
for attempt in range(5):
    r = requests.get(URL, params=params, timeout=120)
    if r.ok:
        break
    print(f"attempt {attempt + 1}: HTTP {r.status_code} {r.text[:200]}")
    time.sleep(10 * (attempt + 1))
else:
    raise SystemExit(f"Open-Meteo request failed for {YEAR}")

h = r.json()["hourly"]
df = pd.DataFrame(
    {"ws100": h["wind_speed_100m"], "ghi": h["shortwave_radiation"], "dni": h["direct_normal_irradiance"],
     "dhi": h["diffuse_radiation"], "t2m": h["temperature_2m"]},
    index=pd.to_datetime(h["time"]),
).rename_axis("time")
assert len(df) in (8760, 8784), len(df)
df.to_csv(OUT, float_format="%.3f")
print("wrote", OUT, len(df), "rows")
