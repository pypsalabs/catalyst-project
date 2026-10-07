"""2013 bus profiles of the hand-picked sites from the PyPSA-Earth stage networks (misc-quarter1/weather-years).

For every site in config.yaml `sites`: the hourly load of the site bus (sum of the loads at it) and, for each
resource (`wind`, `solar`), the bus-aggregated capacity factor of the resource bus (p_max_pu of the generators at
that bus, p_nom_max-weighted where there are several; in the clustered networks one per carrier and bus, already
the potential-weighted aggregate of the cluster region). A resource given as a hand-placed `point` has no bus
profile: its 2013 series is NaN here and build_siteyears.py calibrates it to `target_cf` (wind) or not at all.
Series are shifted to the local solar time of the site (round(longitude / 15) h, circular over the year).

Outputs
  build/profiles_sites.nc  time x series (site): cf_wind, cf_solar (resource buses), demand_mw (site bus), 2013, local time
  build/sites.csv          per site: key, site, region, country, run, bus, x, y (site bus), point_x, point_y (site location),
                           utc_offset_h, load_twh, and per resource r in (wind, solar): r_run, r_bus, r_name, r_x, r_y,
                           r_target_cf, mean_cf_r (2013 bus profile, NaN for a point)

Standalone: python extract_bus_profiles.py
"""

import logging
from pathlib import Path

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
else:
    _HERE = Path(__file__).resolve().parent
    CFG = yaml.safe_load((_HERE / "config.yaml").read_text())
    OUT_PROFILES = _HERE / "build" / "profiles_sites.nc"
    OUT_SITES = _HERE / "build" / "sites.csv"
OUT_PROFILES.parent.mkdir(parents=True, exist_ok=True)

import pypsa  # noqa: E402  (slow import)

NETWORKS_DIR = (_HERE / CFG["networks_dir"]).resolve()
SITES = CFG["sites"]
CARRIER = {"wind": "onwind", "solar": "solar"}
networks = {}


def network(run: str) -> pypsa.Network:
    if run not in networks:
        path = NETWORKS_DIR / CFG["runs"][run]
        log.info("reading %s", path)
        networks[run] = pypsa.Network(str(path))
    return networks[run]


def bus_cf(n: pypsa.Network, bus: str, carrier: str) -> pd.Series:
    pu = n.generators_t.p_max_pu
    g = n.generators[(n.generators.bus == bus) & (n.generators.carrier == carrier) & n.generators.index.isin(pu.columns)]
    if g.empty:
        raise SystemExit(f"bus {bus}: no {carrier} generator with a p_max_pu series")
    w = g["p_nom_max"].replace(0, np.nan).fillna(1.0)
    return (pu[g.index] * w.values).sum(axis=1) / w.sum()


rows, series = [], {}
for key, s in SITES.items():
    n = network(s["run"])
    bus = str(s["bus"])
    if bus not in n.buses.index:
        raise SystemExit(f"{key}: bus {bus!r} not in {s['run']}")
    x, y = float(n.buses.at[bus, "x"]), float(n.buses.at[bus, "y"])
    pt = s.get("point") or {}
    px, py = float(pt.get("lon", x)), float(pt.get("lat", y))
    off = int(np.round(px / 15))
    loads = n.loads[n.loads.bus == bus]
    if loads.empty:
        raise SystemExit(f"{key}: no load at bus {bus}")
    demand = n.loads_t.p_set[loads.index].sum(axis=1)
    time = demand.index
    rec = dict(key=key, site=s["site"], region=s["region"], country=s["country"], run=s["run"], bus=bus, x=x, y=y,
               point_x=px, point_y=py, utc_offset_h=off, load_twh=demand.sum() / 1e6)
    prof = {"demand_mw": demand.values}
    for r in ("wind", "solar"):
        spec = s.get(r) or {"run": s["run"], "bus": bus, "name": "site bus"}
        if "bus" in spec:
            nr = network(spec["run"])
            rbus = str(spec["bus"])
            if rbus not in nr.buses.index:
                raise SystemExit(f"{key} {r}: bus {rbus!r} not in {spec['run']}")
            cf = bus_cf(nr, rbus, CARRIER[r])
            rec.update({f"{r}_run": spec["run"], f"{r}_bus": rbus, f"{r}_x": float(nr.buses.at[rbus, "x"]), f"{r}_y": float(nr.buses.at[rbus, "y"]),
                        f"{r}_target_cf": np.nan, f"mean_cf_{r}": float(cf.mean())})
            prof[f"cf_{r}"] = cf.values
        else:
            rec.update({f"{r}_run": "", f"{r}_bus": "", f"{r}_x": float(spec["point"]["lon"]), f"{r}_y": float(spec["point"]["lat"]),
                        f"{r}_target_cf": float(spec.get("target_cf", np.nan)), f"mean_cf_{r}": np.nan})
            prof[f"cf_{r}"] = np.full(len(time), np.nan)
        rec[f"{r}_name"] = spec.get("name", "")
    series[s["site"]] = {k: np.roll(v, off) for k, v in prof.items()}   # local = UTC + offset
    rows.append(rec)
sites = pd.DataFrame(rows).set_index("key")
names = sites.site.tolist()
ds = xr.Dataset(
    {v: (("time", "series"), np.column_stack([series[s][v] for s in names])) for v in ("cf_wind", "cf_solar", "demand_mw")},
    coords={"time": time.values, "series": names},
    attrs={
        "description": "PyPSA-Earth clustered-bus hourly profiles, weather year 2013, local solar time of the site "
                       "(round(lon/15) h, circular over the year): demand of the site bus, wind / solar capacity factors "
                       "of the site's procurable resource buses (NaN for hand-placed resource points)",
        "networks": ", ".join(str(NETWORKS_DIR / CFG["runs"][r]) for r in networks),
        "series_kind": "site", "legend_title": "Sites", "period_label": "2013, one line per site", "demand_note": "",
    },
)
ds.to_netcdf(OUT_PROFILES)
sites.to_csv(OUT_SITES, float_format="%.4f")
with pd.option_context("display.width", 250, "display.max_columns", 30):
    log.info("\n%s", sites[["site", "bus", "load_twh", "wind_bus", "wind_name", "mean_cf_wind", "wind_target_cf", "solar_bus", "solar_name", "mean_cf_solar"]].to_string())
log.info("wrote %s, %s", OUT_PROFILES, OUT_SITES)
