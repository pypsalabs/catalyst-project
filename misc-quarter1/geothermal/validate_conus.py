"""Check the conduction temperature model against the CONUS temperature-at-depth
data used by Ricks & Jenkins (2025): 81,757 candidate project areas (~88 km²)
with mean temperature at 2.5 / 3.5 / 4.5 / 5.5 / 6.5 km from the Stanford
thermal model (Aljubran & Horne 2024, ML/physics estimate calibrated on
bottom-hole temperatures).

Each CPA is matched to the nearest cell of build/temperature_grid.nc.
Outputs  build/validation_conus.csv   bias, RMSE, correlation per depth
         figures/validation_conus.{png,pdf}
Standalone: python validate_conus.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
import yaml
from scipy.spatial import cKDTree

HERE = Path(__file__).parent
if "snakemake" in globals():
    CFG = snakemake.config
    GRID, REF = Path(snakemake.input.grid), Path(snakemake.input.ref)
    OUT_CSV = Path(snakemake.output.csv)
    FIGS = [Path(f) for f in snakemake.output.figs]
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    GRID = HERE / "build" / "temperature_grid.nc"
    REF = HERE / "data/ricks2025/Costing_and_Supply_Curves/geothermal_lcoe_conus_15_zone_geothermal_Stanford.csv"
    OUT_CSV = HERE / "build" / "validation_conus.csv"
    FIGS = [HERE / "figures" / f"validation_conus.{f}" for f in CFG["plotting"]["formats"]]

INK, MUTED, GRID_C = "#1f1f1f", "#6b6b6b", "#dcdcdc"


def main():
    g = xr.open_dataset(GRID)
    us = g.where(g["iso3"] == "USA", drop=True)
    ref = pd.read_csv(REF, low_memory=False)
    tree = cKDTree(np.column_stack([us["lat"].values, us["lon"].values]))
    dist, j = tree.query(ref[["Latitude", "Longitude"]].values)
    ok = dist < CFG["grid"]["step_deg"]
    depths = list(us["depth"].values)
    # one-parameter fit of the conductivity (A fixed): T - Ts = (q z - A z^2/2) / k
    q = us["heat_flow_mwm2"].values[j[ok]] * 1e-3
    ts = us["t_surface_c"].values[j[ok]]
    A = CFG["thermal"]["heat_production_w_m3"]
    xs, ys = [], []
    for d in depths:
        z = d * 1000
        t = ref.loc[ok, f"MEAN{str(d).replace('.', '_')}"].values
        m = np.isfinite(t)
        xs.append(q[m] * z - A * z ** 2 / 2)
        ys.append(t[m] - ts[m])
    x, y = np.concatenate(xs), np.concatenate(ys)
    k_fit = float((x * x).sum() / (x * y).sum())
    print(f"conductivity in use {CFG['thermal']['conductivity_w_mk']} W/m/K; least-squares fit to CONUS: {k_fit:.2f} W/m/K")
    rows = []
    fig, axes = plt.subplots(1, len(depths), figsize=(3.2 * len(depths), 3.6), sharex=True, sharey=True)
    for ax, d in zip(axes, depths):
        col = f"MEAN{str(d).replace('.', '_')}"
        x = ref.loc[ok, col].values
        y = us["t_conduction_c"].values[j[ok], depths.index(d)]
        m = np.isfinite(x) & np.isfinite(y)
        x, y = x[m], y[m]
        r = np.corrcoef(x, y)[0, 1]
        rows.append({"depth_km": d, "n": int(m.sum()), "bias_c": float(np.mean(y - x)),
                     "rmse_c": float(np.sqrt(np.mean((y - x) ** 2))), "r": float(r),
                     "share_ge_150_reference": float((x >= 150).mean()), "share_ge_150_model": float((y >= 150).mean())})
        ax.hexbin(x, y, gridsize=45, bins="log", cmap="Blues", mincnt=1, linewidths=0)
        lim = (0, 420)
        ax.plot(lim, lim, color=MUTED, lw=0.8, ls="--")
        ax.set_xlim(lim); ax.set_ylim(lim)
        ax.set_title(f"{d} km", fontsize=10, color=INK)
        ax.text(0.04, 0.96, f"bias {rows[-1]['bias_c']:+.0f} °C\nRMSE {rows[-1]['rmse_c']:.0f} °C\nr = {r:.2f}",
                transform=ax.transAxes, va="top", fontsize=8, color=INK)
        ax.set_xlabel("Stanford model (°C)", fontsize=9, color=MUTED)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(labelsize=8, colors=MUTED)
    axes[0].set_ylabel("this conduction model (°C)", fontsize=9, color=MUTED)
    fig.suptitle("Rock temperature at depth, CONUS: 1-D conduction on Lucazeau heat flow vs the Stanford thermal model "
                 f"(n = {int(ok.sum()):,} candidate areas)", fontsize=10, color=INK)
    fig.tight_layout()
    for f in FIGS:
        f.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(f, dpi=CFG["plotting"]["dpi"])
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    res = pd.DataFrame(rows)
    res["conductivity_w_mk_used"] = CFG["thermal"]["conductivity_w_mk"]
    res["conductivity_w_mk_fit"] = k_fit
    res.to_csv(OUT_CSV, index=False, float_format="%.4g")
    print(pd.DataFrame(rows).round(2).to_string(index=False))


if __name__ == "__main__" or "snakemake" in globals():
    main()
