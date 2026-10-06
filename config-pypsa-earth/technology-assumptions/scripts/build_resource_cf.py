"""Annual mean capacity factor of solar PV and onshore wind on a global 0.5 degree grid.

Input: the model.energy weather octants of models/octants (ERA5, weather year 2011; see
.claude/skills/compile-figures for the download), eight per technology, each a 90 x 90 degree
box of 181 x 181 points with hourly "specific generation" (per-unit output) as (time, dim_0),
dim_0 = row-major over latitude then longitude (grid of priam-myopic's first_network.py).
Output: data/resource_cf_<year>.nc, variable cf(tech, y, x) with y = -90..90 and
x = -180..180 in 0.5 degree steps. Neighbouring octants share their edge row / column; the
later octant overwrites the shared points.

The output is small (~2 MB) and kept in data/, so the document builds without the octants.

Standalone:  python scripts/build_resource_cf.py [--octants ../../models/octants] [--year 2011] [-o data/resource_cf_2011.nc]
"""

import argparse
from pathlib import Path

import numpy as np
import xarray as xr

TOP = Path(__file__).resolve().parents[1]
TECHS = {"solar": "solar-utility", "onwind": "onwind"}   # octant file tag -> technology key of the CSV
MESH = 0.5
N = int(90 / MESH) + 1   # points per octant edge
TIME_CHUNK = 730         # hours read at once: 730 x 32761 float32 = 96 MB


def octant_mean(path):
    """Mean over time of one octant file, as a (lat, lon) array of N x N."""
    with xr.open_dataset(path) as ds:
        da = ds["specific generation"]
        total = np.zeros(da.sizes["dim_0"], dtype="float64")
        for t0 in range(0, da.sizes["time"], TIME_CHUNK):
            total += da.isel(time=slice(t0, t0 + TIME_CHUNK)).values.sum(axis=0, dtype="float64")
        return (total / da.sizes["time"]).reshape(N, N)


def build(octants, year):
    x = np.round(np.arange(-180, 180 + MESH / 2, MESH), 2)
    y = np.round(np.arange(-90, 90 + MESH / 2, MESH), 2)
    cf = np.full((len(TECHS), len(y), len(x)), np.nan, dtype="float32")
    for k, tag in enumerate(TECHS):
        for quadrant in range(4):
            for hemisphere in range(2):
                f = Path(octants) / f"octant-{year}-{quadrant}-{hemisphere}-{tag}.nc"
                m = octant_mean(f)
                i0, j0 = quadrant * (N - 1), hemisphere * (N - 1)   # lon and lat offsets in the global grid
                cf[k, j0:j0 + N, i0:i0 + N] = m
                print(f"{f.name}: mean {np.nanmean(m):.3f}, max {np.nanmax(m):.3f}")
    return xr.Dataset({"cf": (("tech", "y", "x"), cf)},
                      coords={"tech": list(TECHS.values()), "y": y, "x": x},
                      attrs={"source": f"model.energy ERA5 octants, weather year {year}",
                             "description": "annual mean capacity factor (per unit)"})


def main():
    if "snakemake" in globals():
        octants, year, out = snakemake.params.octants, snakemake.params.year, snakemake.output[0]
    else:
        p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
        p.add_argument("--octants", default=TOP / "../../models/octants")
        p.add_argument("--year", type=int, default=2011)
        p.add_argument("-o", "--out", default=None)
        a = p.parse_args()
        octants, year = a.octants, a.year
        out = a.out or TOP / f"data/resource_cf_{year}.nc"
    ds = build(octants, year)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(out, encoding={"cf": {"zlib": True, "complevel": 4}})
    print(f"-> {out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
