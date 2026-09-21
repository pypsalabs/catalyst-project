# SPDX-License-Identifier: CC0-1.0
"""
Crop an atlite cutout (netCDF) to a lon/lat box and optionally a time window, streaming through dask so a
27 GB continental file can be cut on a laptop under an 8 GB memory cap.

    pixi run python ../../config-pypsa-earth/crop_cutout.py SRC OUT --x X0 X1 --y Y0 Y1 [--time T0 T1]

Keeps every data variable and attribute (module, prepared_features, dx, dy, chunksize_time), so the result is a
valid cutout for the fork's build_renewable_profiles. Used for China (from the pypsa-earth Asia cutout) instead of
a 3-6 h CDS build; see config-pypsa-earth/README.md. Refuses to overwrite an existing OUT.

Repairs one defect of the pypsa-earth continental cutouts on the way: east of ~128 E the Asia file carries pairs of
near-identical longitudes (128.1 and 128.10001, 41 pairs in total), of which one column is entirely NaN - the
artefact of merging two ERA5 tiles. Such columns would become NaN wind/solar profiles over north-east China, so for
every group of coordinates closer than dx/10 only the column that holds data is kept, and the coordinates are
rounded back onto the regular grid. Selection is turned into contiguous index runs: a fancy index would make the
netCDF backend read the file element-wise (minutes -> hours).
"""
import argparse
import os
import sys
import time

import dask
import numpy as np
import xarray as xr


def probe_var(ds, dim):
    """A data variable to test for all-NaN slices: smallest one that has `dim` and a time axis."""
    cand = [v for v in ds.data_vars if dim in ds[v].dims and "time" in ds[v].dims]
    return min(cand, key=lambda v: ds[v].size) if cand else None


def keep_indices(ds, dim, tol):
    """Indices along `dim` to keep: one per group of coordinates closer than `tol`, the one holding data."""
    vals = ds[dim].values
    groups = [[0]]
    for i in range(1, len(vals)):
        if abs(vals[i] - vals[i - 1]) < tol:
            groups[-1].append(i)
        else:
            groups.append([i])
    if all(len(g) == 1 for g in groups):
        return None
    pv = probe_var(ds, dim)
    probe = ds[pv].isel(time=0).load() if pv else None
    keep = []
    for g in groups:
        if len(g) == 1 or probe is None:
            keep.append(g[0])
            continue
        nan_frac = {i: float(np.isnan(probe.isel({dim: i}).values).mean()) for i in g}
        best = min(g, key=lambda i: nan_frac[i])
        dropped = [i for i in g if i != best]
        print(f"{dim}: {vals[g]} -> keep index {best} ({vals[best]:.5f}, NaN {nan_frac[best]:.0%}), "
              f"drop {[f'{vals[i]:.5f} (NaN {nan_frac[i]:.0%})' for i in dropped]}", flush=True)
        keep.append(best)
    return keep


def runs(idx):
    """Contiguous [start, stop) runs covering the sorted index list."""
    out, start, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i == prev + 1:
            prev = i
        else:
            out.append((start, prev + 1))
            start = prev = i
    out.append((start, prev + 1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--x", nargs=2, type=float, required=True, metavar=("X0", "X1"))
    ap.add_argument("--y", nargs=2, type=float, required=True, metavar=("Y0", "Y1"))
    ap.add_argument("--time", nargs=2, metavar=("T0", "T1"), help="ISO timestamps, inclusive")
    ap.add_argument("--chunk-time", type=int, default=None, help="dask chunk along time (default: file attr chunksize_time or 100)")
    a = ap.parse_args()
    if os.path.exists(a.out):
        sys.exit(f"{a.out} exists, refusing to overwrite")

    t0 = time.time()
    ds = xr.open_dataset(a.src)
    ct = a.chunk_time or int(ds.attrs.get("chunksize_time", 100))
    ds = ds.chunk({"time": ct})     # before any concat: xr.concat on non-dask arrays materialises the whole slab
    x0, x1 = sorted(a.x)
    y0, y1 = sorted(a.y)
    xsl = slice(x0, x1) if float(ds.x[0]) <= float(ds.x[-1]) else slice(x1, x0)
    ysl = slice(y0, y1) if float(ds.y[0]) <= float(ds.y[-1]) else slice(y1, y0)
    sub = ds.sel(x=xsl, y=ysl)                      # contiguous box first: cheap, sequential reads
    if a.time:
        sub = sub.sel(time=slice(a.time[0], a.time[1]))
    if min(sub.sizes["x"], sub.sizes["y"], sub.sizes["time"]) == 0:
        sys.exit(f"empty selection: sizes {dict(sub.sizes)}")

    for dim in ("x", "y"):
        step = float(ds.attrs.get("d" + dim, 0)) or float(np.median(np.abs(np.diff(sub[dim].values))))
        keep = keep_indices(sub, dim, tol=step / 10)
        if keep is None:
            continue
        sub = xr.concat([sub.isel({dim: slice(s, e)}) for s, e in runs(keep)], dim=dim, data_vars="minimal")
        sub = sub.assign_coords({dim: np.round(sub[dim].values, 4)})
    sub = sub.chunk({"time": ct})     # re-chunk after the concat (pieces differ in x)

    sub.attrs = dict(ds.attrs)
    sub.attrs["chunksize_time"] = ct
    sub.attrs["history"] = (ds.attrs.get("history", "") + f"; cropped by config-pypsa-earth/crop_cutout.py from "
                            f"{os.path.basename(a.src)} x[{x0},{x1}] y[{y0},{y1}]"
                            + (f" time[{a.time[0]},{a.time[1]}]" if a.time else "")).strip("; ")
    enc = {}
    for v in sub.data_vars:
        e = {"zlib": False}
        if np.issubdtype(sub[v].dtype, np.floating):
            e["dtype"] = "float32"
        if "time" in sub[v].dims:
            e["chunksizes"] = tuple(min(ct, sub.sizes[d]) if d == "time" else sub.sizes[d] for d in sub[v].dims)
        enc[v] = e
    dx = np.unique(np.round(np.diff(sub.x.values), 4))
    dy = np.unique(np.round(np.diff(sub.y.values), 4))
    print(f"{a.src} -> {a.out}: x {float(sub.x[0])}..{float(sub.x[-1])} ({sub.sizes['x']}, steps {dx}), "
          f"y {float(sub.y[0])}..{float(sub.y[-1])} ({sub.sizes['y']}, steps {dy}), "
          f"time {str(sub.time.values[0])[:13]}..{str(sub.time.values[-1])[:13]} ({sub.sizes['time']}), "
          f"vars {list(sub.data_vars)}", flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tmp = a.out + ".part"
    with dask.config.set(scheduler="synchronous"):
        sub.to_netcdf(tmp, engine="netcdf4", encoding=enc)
    os.replace(tmp, a.out)
    print(f"done: {os.path.getsize(a.out) / 1e9:.2f} GB in {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
