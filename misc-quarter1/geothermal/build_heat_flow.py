"""Surface heat flow on the regular grid: Lucazeau (2019) sharpened with the IHFC Global Heat Flow Database 2024.

The Lucazeau 0.5 deg map is a smooth similarity-based prediction; the database holds the measurements. Here the
measurements correct the map where they are dense and leave it alone where they are not:

  1. onshore locations of the database (parent level, `ghfdb.environments`), quality scores in `drop_scores`
     removed, q clipped to `q_clip` (convective hot spots are not the conductive background);
  2. median q per grid cell (de-clusters dense drilling areas), residual r = q_obs - q_Lucazeau at the cell;
  3. residual field r_hat = sum(w r) / (sum(w) + shrinkage), w = exp(-d^2 / 2 l^2): a Gaussian kernel average
     shrunk towards 0, so far from data r_hat -> 0 (Lucazeau) and near dense data it follows the measurements;
     computed as a separable Gaussian filter on the lat/lon raster (lon width scaled by 1/cos(lat));
  4. l and the shrinkage from spatial block cross-validation: 2 deg blocks in `cv_folds` folds, held-out RMSE
     against the measured cell medians, Lucazeau alone as the baseline. Lucazeau was itself fitted to an earlier
     release of these data, so its held-out score is optimistic and the comparison is conservative; the
     independent checks are the reference temperature models (validate_temperature.py).

Outputs  build/heat_flow.nc       (lat, lon): q_lucazeau, residual, q_ghfdb_residual, data_weight
         build/heat_flow_cv.csv   held-out RMSE / bias per (length scale, shrinkage) and of Lucazeau alone
Standalone: python build_heat_flow.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import yaml
from scipy.interpolate import RegularGridInterpolator
from scipy.ndimage import gaussian_filter1d

HERE = Path(__file__).parent
if "snakemake" in globals():
    CFG = snakemake.config
    OUT_NC, OUT_CV = Path(snakemake.output.nc), Path(snakemake.output.cv)
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    OUT_NC, OUT_CV = HERE / "build" / "heat_flow.nc", HERE / "build" / "heat_flow_cv.csv"

DATA = (HERE / CFG["archetype_data_dir"]).resolve()
KM_PER_DEG = 111.195
Q_FLOOR = 20.0     # mW/m2: below the lowest continental heat flow; guards the sum Lucazeau + residual
TRUNCATE = 3.0     # kernel cut-off in length scales


def lucazeau_interpolator():
    hf = xr.open_dataset(DATA / "lucazeau2019_heat_flux_0p5deg.nc")
    lat, lon, q = hf["LAT"].values, hf["LON"].values, hf["heat_flux"].values
    order = np.argsort(((lon + 180) % 360) - 180)
    lon_s = ((lon[order] + 180) % 360) - 180
    q_s = q[:, order]
    lon_pad = np.concatenate([[lon_s[-1] - 360], lon_s, [lon_s[0] + 360]])
    q_pad = np.concatenate([q_s[:, -1:], q_s, q_s[:, :1]], axis=1)
    return RegularGridInterpolator((lat, lon_pad), q_pad, bounds_error=False, fill_value=None)


def load_points(c):
    d = pd.read_csv(HERE / c["file"], sep="\t", skiprows=12, encoding="latin-1", low_memory=False)
    d = d.drop_duplicates("ID_parent")          # q is the parent-level (location) value, repeated per child
    env = d["environment"].astype(str).str.strip("[]").str.lower()
    d = d[env.isin([e.lower() for e in c["environments"]])]
    scores = d["Quality_Score_Parent"].astype(str).str.split(".", expand=True)
    bad = np.zeros(len(d), bool)
    for col in scores:
        bad |= scores[col].isin(c["drop_scores"]).values
    d = d[~bad]
    for col in ("q", "lat_NS", "long_EW"):
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=["q", "lat_NS", "long_EW"])
    d = d[(d["q"] > c["q_min"]) & d["lat_NS"].between(-90, 90) & d["long_EW"].between(-180, 180)]
    print(f"IHFC 2024: {len(d):,} onshore locations kept, {(d['q'] > c['q_clip']).sum():,} clipped at {c['q_clip']} mW/m2")
    return pd.DataFrame({"lat": d["lat_NS"].values, "lon": d["long_EW"].values, "q": np.minimum(d["q"].values, c["q_clip"])})


class Grid:
    def __init__(self, step):
        self.step = step
        self.lat = np.arange(-90 + step / 2, 90, step)
        self.lon = np.arange(-180 + step / 2, 180, step)
        self.shape = (len(self.lat), len(self.lon))

    def index(self, lat, lon):
        i = np.clip(np.floor((lat + 90) / self.step).astype(int), 0, self.shape[0] - 1)
        k = np.floor((lon + 180) / self.step).astype(int) % self.shape[1]
        return i, k

    def kernel_sums(self, i, k, values, length_km):
        """Unnormalised Gaussian kernel sums sum_j w_j v_j on the grid, w = exp(-d^2 / 2 l^2), for point values
        `values` at cells (i, k); separable approximation (lat first, then lon at each target row)."""
        a = np.zeros(self.shape)
        np.add.at(a, (i, k), values)
        s_lat = length_km / (self.step * KM_PER_DEG)
        a = gaussian_filter1d(a, s_lat, axis=0, mode="constant", truncate=TRUNCATE) * np.sqrt(2 * np.pi) * s_lat
        out = np.empty_like(a)
        for r, la in enumerate(self.lat):
            s_lon = min(s_lat / max(np.cos(np.radians(la)), 1e-3), self.shape[1] / (2 * TRUNCATE))
            out[r] = gaussian_filter1d(a[r], s_lon, mode="wrap", truncate=TRUNCATE) * np.sqrt(2 * np.pi) * s_lon
        return out


def residual_field(grid, i, k, r, length_km, shrinkage):
    s = grid.kernel_sums(i, k, r, length_km)
    w = grid.kernel_sums(i, k, np.ones_like(r), length_km)
    return s / (w + shrinkage), w


def cross_validate(grid, cells, c):
    blk = np.floor(cells["lat"] / c["cv_block_deg"]).astype(int) * 1000 + np.floor(cells["lon"] / c["cv_block_deg"]).astype(int)
    ub = np.unique(blk)
    fold_of = dict(zip(ub, np.random.default_rng(0).permutation(len(ub)) % c["cv_folds"]))
    fold = blk.map(fold_of).values
    i, k, r = cells["i"].values, cells["k"].values, cells["r"].values
    rows = []
    base = cells["q"].values - cells["q_luc"].values
    rows.append({"method": "lucazeau", "length_km": np.nan, "shrinkage": np.nan,
                 "rmse_mwm2": float(np.sqrt(np.mean(base ** 2))), "bias_mwm2": float(-base.mean()), "n_cells": len(cells)})
    for l in c["length_scales_km"]:
        pred = {lam: np.empty(len(cells)) for lam in c["shrinkages"]}
        for f in range(c["cv_folds"]):
            tr, te = fold != f, fold == f
            s = grid.kernel_sums(i[tr], k[tr], r[tr], l)
            w = grid.kernel_sums(i[tr], k[tr], np.ones(tr.sum()), l)
            for lam in c["shrinkages"]:
                pred[lam][te] = cells["q_luc"].values[te] + (s / (w + lam))[i[te], k[te]]
        for lam in c["shrinkages"]:
            err = np.maximum(pred[lam], Q_FLOOR) - cells["q"].values
            rows.append({"method": "ghfdb_residual", "length_km": l, "shrinkage": lam,
                         "rmse_mwm2": float(np.sqrt(np.mean(err ** 2))), "bias_mwm2": float(err.mean()), "n_cells": len(cells)})
    return pd.DataFrame(rows)


def main():
    c = CFG["ghfdb"]
    grid = Grid(CFG["grid"]["step_deg"])
    lat2, lon2 = np.meshgrid(grid.lat, grid.lon, indexing="ij")
    q_luc = lucazeau_interpolator()(np.column_stack([lat2.ravel(), lon2.ravel()])).reshape(grid.shape)

    pts = load_points(c)
    pts["i"], pts["k"] = grid.index(pts["lat"].values, pts["lon"].values)
    cells = pts.groupby(["i", "k"]).agg(q=("q", "median"), n=("q", "size")).reset_index()
    cells["lat"], cells["lon"] = grid.lat[cells["i"]], grid.lon[cells["k"]]
    cells["q_luc"] = q_luc[cells["i"], cells["k"]]
    cells["r"] = cells["q"] - cells["q_luc"]
    print(f"{len(cells):,} grid cells with data; median residual {cells['r'].median():+.1f} mW/m2, "
          f"MAD {np.median(np.abs(cells['r'] - cells['r'].median())):.1f}")

    cv = cross_validate(grid, cells, c)
    OUT_CV.parent.mkdir(parents=True, exist_ok=True)
    cv.to_csv(OUT_CV, index=False, float_format="%.4g")
    best = cv[cv["method"] == "ghfdb_residual"].sort_values("rmse_mwm2").iloc[0]
    print(cv.round(2).to_string(index=False))
    print(f"chosen: length {best['length_km']:.0f} km, shrinkage {best['shrinkage']:g} "
          f"(held-out RMSE {best['rmse_mwm2']:.1f} vs Lucazeau {cv['rmse_mwm2'].iloc[0]:.1f} mW/m2)")

    r_hat, w = residual_field(grid, cells["i"].values, cells["k"].values, cells["r"].values,
                              best["length_km"], best["shrinkage"])
    q_new = np.maximum(q_luc + r_hat, Q_FLOOR)
    ds = xr.Dataset(
        {"q_lucazeau": (("lat", "lon"), q_luc.astype("float32")),
         "residual": (("lat", "lon"), r_hat.astype("float32")),
         "q_ghfdb_residual": (("lat", "lon"), q_new.astype("float32")),
         "data_weight": (("lat", "lon"), w.astype("float32"))},
        coords={"lat": grid.lat, "lon": grid.lon},
        attrs={"units": "mW/m2", "length_km": float(best["length_km"]), "shrinkage": float(best["shrinkage"]),
               "lucazeau": "Lucazeau 2019 (de Lavergne & Maisonnave 2024 regridding, 0.5 deg), bilinear",
               "ghfdb": "IHFC Global Heat Flow Database Release 2024 v2026.03, doi:10.5880/fidgeo.2024.014, CC-BY-4.0",
               "n_data_cells": len(cells)},
    )
    ds["data_weight"].attrs["long_name"] = "sum of kernel weights of the data cells (effective number of nearby cells)"
    ds.to_netcdf(OUT_NC)


if __name__ == "__main__" or "snakemake" in globals():
    main()
