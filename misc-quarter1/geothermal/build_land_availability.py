"""Land available for EGS per 0.25 deg cell, with the exclusions PyPSA-Earth applies to onshore wind.

The rules and data are those of the soft fork (models/pypsa-earth), read from its config.default.yaml
(`renewable.onwind`, no stage config overrides them) so that EGS and wind share one land-use logic:
  - Copernicus Global Land Cover LC100 2019 (100 m): only the onwind `grid_codes` count as available
    (forests, shrubs, herbaceous vegetation, cropland, bare / sparse vegetation, moss and lichen;
    urban, water, wetland, snow / ice and sea do not);
  - `distance` (1,000 m) from the `distance_grid_codes` (50 = urban) is excluded as well;
  - protected areas: the fork's prebuilt global natura.tiff (WDPA, 1/24 deg) is excluded (`natura: true`).
For each 0.25 deg cell the script returns the share of its full area that is available (and, for information,
the land-cover share alone and the protected share). It replaces the flat 20 % resource derating of
Ricks & Jenkins (2025) in build_egs_potential.py. The urban buffer is a rectangle of +-distance in both
directions (atlite buffers by a circle), so it excludes slightly more.

Runs in an environment with rasterio (micromamba env pypsa-demand, config `rasterio_python`); the
priam-myopic env of the rest of this workflow has none. Reads the 1.7 GB raster in 0.25 deg strips,
in parallel; ~10 min on 4 cores.

Standalone: python build_land_availability.py --config config.yaml -o build/land_availability.nc [-j 4]
"""

import argparse
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import rasterio
import xarray as xr
import yaml
from rasterio.windows import Window
from scipy.ndimage import maximum_filter1d

HERE = Path(__file__).parent
STEP = 0.25
EARTH_M_PER_DEG = 111_320.0
S = {}   # per-worker settings (set by init)


def init(settings):
    S.update(settings)


def strip(i):
    """Available / land-cover / protected shares of the 1440 cells of strip i (from the raster's top edge)."""
    with rasterio.open(S["lc"]) as src:
        npx = S["npx"]
        row0 = i * npx
        ry = S["ry"]
        r0, r1 = max(row0 - ry, 0), min(row0 + npx + ry, src.height)
        a = src.read(1, window=Window(0, r0, src.width, r1 - r0))
    lat = S["top"] - (i + 0.5) * STEP
    urban = np.isin(a, S["dist_codes"]).view(np.uint8)
    if urban.any():
        rx = int(np.ceil(S["distance"] / (S["px_deg"] * EARTH_M_PER_DEG * max(np.cos(np.radians(lat)), 0.05))))
        near = maximum_filter1d(maximum_filter1d(urban, 2 * ry + 1, axis=0), 2 * rx + 1, axis=1).astype(bool)
    else:
        near = np.zeros(a.shape, bool)
    core = slice(row0 - r0, row0 - r0 + npx)
    ok = np.isin(a[core], S["grid_codes"]) & ~near[core]
    # protected areas: natura rows of this strip, upsampled to the land-cover pixels
    with rasterio.open(S["natura"]) as nat:
        f = S["nat_px"]                              # natura rows per strip
        n0 = int(round((90 - (S["top"] - i * STEP)) / nat.res[1]))
        prot = nat.read(1, window=Window(0, n0, nat.width, f)) > 0.5
    prot = np.repeat(np.repeat(prot, npx // f, axis=0), a.shape[1] // prot.shape[1], axis=1)
    if prot.shape[1] != a.shape[1]:
        raise ValueError(f"natura {prot.shape} vs land cover {a.shape} do not align")
    ncell = a.shape[1] // npx
    share = lambda m: m.reshape(npx, ncell, npx).mean(axis=(0, 2), dtype=np.float64).astype(np.float32)
    return share(ok & ~prot), share(ok), share(prot)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=HERE / "config.yaml")
    ap.add_argument("-o", "--out", default=HERE / "build" / "land_availability.nc")
    ap.add_argument("-j", "--jobs", type=int, default=4)
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text())["land_availability"]
    base = Path(args.config).resolve().parent
    fork = yaml.safe_load((base / cfg["pypsa_earth_config"]).read_text())["renewable"][cfg["technology"]]
    lc_path, nat_path = (base / cfg["copernicus"]).resolve(), (base / cfg["natura"]).resolve()
    with rasterio.open(lc_path) as src, rasterio.open(nat_path) as nat:
        px = src.res[0]
        npx = int(round(STEP / px))
        assert abs(npx * px - STEP) < 1e-9 and abs(src.bounds.left + 180) < 1e-6, "land cover not aligned to 0.25 deg"
        top, nstrip, ncell = round(src.bounds.top, 6), src.height // npx, src.width // npx
        nat_px = int(round(STEP / nat.res[1]))
        assert abs(nat.bounds.top - 90) < 1e-6 and abs(nat.bounds.left + 180) < 1e-6, "natura not global"
    cop = fork["copernicus"]
    settings = {"lc": str(lc_path), "natura": str(nat_path), "npx": npx, "top": top, "px_deg": px, "nat_px": nat_px,
                "grid_codes": cop["grid_codes"], "dist_codes": cop.get("distance_grid_codes", []),
                "distance": float(cop.get("distance", 0)), "ry": int(np.ceil(float(cop.get("distance", 0)) / (px * EARTH_M_PER_DEG)))}
    if not fork.get("natura", False):
        raise ValueError("the fork's onwind does not exclude natura; adapt this script")
    with Pool(args.jobs, initializer=init, initargs=(settings,)) as pool:
        res = pool.map(strip, range(nstrip), chunksize=4)
    avail, lc, prot = (np.stack([r[k] for r in res]) for k in range(3))
    lat = top - (np.arange(nstrip) + 0.5) * STEP
    lon = -180 + (np.arange(ncell) + 0.5) * STEP
    ds = xr.Dataset({"available_fraction": (("lat", "lon"), avail), "landcover_fraction": (("lat", "lon"), lc),
                     "protected_fraction": (("lat", "lon"), prot)}, coords={"lat": lat, "lon": lon})
    ds.attrs.update({"source": f"PyPSA-Earth renewable.{cfg['technology']} exclusions ({cfg['pypsa_earth_config']}): "
                               f"Copernicus LC100 2019 grid codes {cop['grid_codes']}, {settings['distance']:.0f} m from "
                               f"codes {settings['dist_codes']}, natura.tiff (WDPA) excluded",
                     "note": "share of the full 0.25 deg cell area; outside the land-cover extent (north of 80 N, "
                             "south of 60 S) no value"})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(args.out)
    land = lc > 0
    print(f"{nstrip} x {ncell} cells -> {args.out}; mean available share over cells with any eligible land "
          f"{avail[land].mean():.1%} (land cover alone {lc[land].mean():.1%}, protected {prot[land].mean():.1%})")


if __name__ == "__main__":
    main()
