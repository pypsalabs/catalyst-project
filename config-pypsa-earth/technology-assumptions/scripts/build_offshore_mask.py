"""Share of each 0.5 degree cell where the sea is shallow enough for offshore wind.

Input: the GEBCO 2025 bathymetry grid (15 arc seconds) of the PyPSA-Earth fork, models/pypsa-earth/data/gebco.
Output: data/offwind_shallow_share.nc, variable share(y, x) on the grid of data/resource_cf_<year>.nc
(y = -90..90, x = -180..180, 0.5 degree, each value the share of the 0.5 x 0.5 degree box around the point)
= share of GEBCO pixels with -MAX_DEPTH <= elevation < 0 m. MAX_DEPTH is the fork's offwind max_depth (50 m,
fixed-bottom foundations). The grid is read in latitude strips (120 rows x 86,400 = 20 MB each), so the 7 GB file
never sits in memory.

The output is small and kept in data/, so the document builds without GEBCO.

Standalone:  python scripts/build_offshore_mask.py [--gebco ../../models/pypsa-earth/data/gebco/GEBCO_2025_sub_ice.nc]
                                                   [--max-depth 50] [-o data/offwind_shallow_share.nc]
"""

import argparse
from pathlib import Path

import numpy as np
import xarray as xr

TOP = Path(__file__).resolve().parents[1]
MESH = 0.5
PX = 240                      # GEBCO pixels per degree
W = int(MESH * PX)            # pixels per cell edge (120)


def build(gebco, max_depth):
    x = np.round(np.arange(-180, 180 + MESH / 2, MESH), 2)
    y = np.round(np.arange(-90, 90 + MESH / 2, MESH), 2)
    share = np.zeros((len(y), len(x)), dtype="float32")
    with xr.open_dataset(gebco) as ds:
        elev = ds["elevation"]
        n_lat = elev.sizes["lat"]
        for j, yc in enumerate(y):
            r0, r1 = max(0, int((yc - MESH / 2 + 90) * PX)), min(n_lat, int((yc + MESH / 2 + 90) * PX))
            strip = elev.isel(lat=slice(r0, r1)).values
            # box around x = -180 + 0.5 i spans pixels [i W - W/2, i W + W/2): shift by W/2, then reshape
            strip = np.roll(strip, W // 2, axis=1).reshape(strip.shape[0], -1, W)
            shallow = ((strip >= -max_depth) & (strip < 0)).mean(axis=(0, 2))
            share[j, :-1] = shallow
            share[j, -1] = shallow[0]       # x = 180 is x = -180
    return xr.Dataset({"share": (("y", "x"), share)}, coords={"y": y, "x": x},
                      attrs={"source": "GEBCO 2025 grid (sub-ice topography), doi:10.5285/37c52e96-24ea-67ce-e063-7086abc0ea0f",
                             "description": f"share of the 0.5 degree box with sea depth 0-{max_depth} m"})


def main():
    if "snakemake" in globals():
        gebco, max_depth, out = snakemake.input[0], snakemake.params.max_depth, snakemake.output[0]
    else:
        p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
        p.add_argument("--gebco", default=TOP / "../../models/pypsa-earth/data/gebco/GEBCO_2025_sub_ice.nc")
        p.add_argument("--max-depth", type=float, default=50)
        p.add_argument("-o", "--out", default=TOP / "data/offwind_shallow_share.nc")
        a = p.parse_args()
        gebco, max_depth, out = a.gebco, a.max_depth, a.out
    ds = build(gebco, max_depth)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(out, encoding={"share": {"zlib": True, "complevel": 4}})
    print(f"cells with any shallow sea: {(ds.share > 0).sum().item():,}; -> {out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
