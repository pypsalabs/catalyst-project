"""Stencil of ERA5 cells per resource location for the site-years dataset (misc-quarter1/weather-years).

For every site of build/sites.csv and each resource (wind, solar): an n x n lattice of points centred on the
resource location (sites.csv wind_x / wind_y, solar_x / solar_y: the resource bus coordinate or the hand-placed
point), each snapped to the nearest ERA5 cell centre (multiples of 0.25 degrees). Identical lattices (same
coordinates for both resources, or shared between sites) share their cached files. The cluster polygons of
PyPSA-Earth are deliberately not used (bus names permuted against the network for US, BR, IN). Open-Meteo's
`cell_selection=land` later moves a sea cell to the nearest land cell.

Output build/siteyears_points.csv: key, site, resource, point, lat, lon (one row per site, resource and point).

Standalone: python sample_points.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

if "snakemake" in globals():
    CFG = snakemake.config  # noqa: F821
    SITES = Path(snakemake.input.sites)  # noqa: F821
    OUT = Path(snakemake.output[0])  # noqa: F821
else:
    _HERE = Path(__file__).resolve().parent
    CFG = yaml.safe_load((_HERE / "config.yaml").read_text())
    SITES = _HERE / "build" / "sites.csv"
    OUT = _HERE / "build" / "siteyears_points.csv"

ST = CFG["siteyears"]["stencil"]
CELL = 0.25                                   # ERA5 grid of Open-Meteo's `models=era5`


def snap(v: float) -> float:
    return float(np.round(np.round(v / CELL) * CELL, 2))


sites = pd.read_csv(SITES)
offsets = (np.arange(ST["n"]) - (ST["n"] - 1) / 2) * ST["spacing_deg"]
rows = []
for _, s in sites.iterrows():
    for r in ("wind", "solar"):
        for k, (dy, dx) in enumerate((dy, dx) for dy in offsets for dx in offsets):
            rows.append(dict(key=s.key, site=s.site, resource=r, point=k, lat=snap(s[f"{r}_y"] + dy), lon=snap(s[f"{r}_x"] + dx)))
pts = pd.DataFrame(rows)
assert not pts.duplicated(["key", "resource", "lat", "lon"]).any(), "stencil spacing below the ERA5 cell size"
OUT.parent.mkdir(parents=True, exist_ok=True)
pts.to_csv(OUT, index=False, float_format="%.2f")
cells = pts[["lat", "lon"]].drop_duplicates()
print(f"{len(pts)} stencil points, {len(cells)} distinct cells, for {sites.shape[0]} sites -> {OUT}")
