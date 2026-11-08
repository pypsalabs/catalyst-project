"""Check the conduction temperature model against the two reference temperature models, and calibrate k.

References (config thermal.references, read from build/temperature_grid.nc as t_ref_<name>_c):
  stanford_conus     Stanford thermal model over CONUS (Aljubran & Horne 2024, ML/physics on bottom-hole temperatures),
                     nearest Ricks & Jenkins candidate project area per cell
  limberger_europe   Limberger 3-D model of Europe (Limberger et al. 2014, measured temperatures + crustal conduction)

Per reference and depth: bias, RMSE, correlation and share >= 150 C of the conduction estimate on plain Lucazeau
heat flow and on the IHFC-sharpened heat flow. Calibration: the one-parameter least-squares conductivity
(A fixed), T - Ts = (q z - A z^2 / 2) / k, fitted on each reference and on both, and the transfer test (fit on one,
score on the other) that is the only evidence for the rest of the world, where no reference exists.

Outputs  build/validation_temperature.csv     metrics per reference x heat flow x conductivity x depth
         figures/validation_temperature.{png,pdf}   hexbins, one row per reference, configured heat flow and k
         figures/europe_temperature_diff.{png,pdf}  Limberger minus conduction at 4.5 km (and the seam at its edge)
Standalone: python validate_temperature.py
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
import yaml

HERE = Path(__file__).parent
sys.path.insert(0, str(next(p for p in HERE.resolve().parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import iconstyle as ic  # noqa: E402

if "snakemake" in globals():
    CFG = snakemake.config
    GRID = Path(snakemake.input.grid)
    OUT_CSV = Path(snakemake.output.csv)
    FIGS = [Path(f) for f in snakemake.output.figs]
    DIFF = [Path(f) for f in snakemake.output.diff]
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    GRID = HERE / "build" / "temperature_grid.nc"
    OUT_CSV = HERE / "build" / "validation_temperature.csv"
    FIGS = [HERE / "figures" / f"validation_temperature.{f}" for f in CFG["plotting"]["formats"]]
    DIFF = [HERE / "figures" / f"europe_temperature_diff.{f}" for f in CFG["plotting"]["formats"]]

LABEL = {"stanford_conus": "CONUS, Stanford model", "limberger_europe": "Europe, Limberger model"}
HEAT_FLOW = {"lucazeau": "heat_flow_lucazeau_mwm2", "ghfdb_residual": "heat_flow_ghfdb_mwm2"}


def conduction(ts, q, depths, k, A):
    z = np.asarray(depths)[None, :] * 1000.0
    return ts[:, None] + (q[:, None] * 1e-3) * z / k - A * z ** 2 / (2 * k)


def k_fit(ts, q, t_ref, depths, A):
    """Least-squares k of T - Ts = x / k with x = q z - A z^2 / 2, over all cells and depths."""
    z = np.asarray(depths)[None, :] * 1000.0
    x = (q[:, None] * 1e-3) * z - A * z ** 2 / 2
    y = t_ref - ts[:, None]
    m = np.isfinite(y)
    return float((x[m] ** 2).sum() / (x[m] * y[m]).sum())


def metrics(model, ref, depths):
    rows = []
    for j, d in enumerate(depths):
        x, y = ref[:, j], model[:, j]
        m = np.isfinite(x) & np.isfinite(y)
        x, y = x[m], y[m]
        rows.append({"depth_km": d, "n": int(m.sum()), "bias_c": float(np.mean(y - x)),
                     "rmse_c": float(np.sqrt(np.mean((y - x) ** 2))), "r": float(np.corrcoef(x, y)[0, 1]),
                     "share_ge_150_reference": float((x >= 150).mean()), "share_ge_150_model": float((y >= 150).mean())})
    return rows


def main():
    g = xr.open_dataset(GRID)
    depths = list(g["depth"].values)
    A = CFG["thermal"]["heat_production_w_m3"]
    k_cfg = CFG["thermal"]["conductivity_w_mk"]
    ts_all = g["t_surface_c"].values
    refs = [n for n in LABEL if f"t_ref_{n}_c" in g]
    sel = {n: np.isfinite(g[f"t_ref_{n}_c"].values).all(axis=1) & (g["remote_territory"].values == 0) for n in refs}

    rows, kfits = [], {}
    for hf, var in HEAT_FLOW.items():
        q_all = g[var].values
        fits = {n: k_fit(ts_all[sel[n]], q_all[sel[n]], g[f"t_ref_{n}_c"].values[sel[n]], depths, A) for n in refs}
        both = np.logical_or.reduce([sel[n] for n in refs])
        t_ref_both = np.where(sel[refs[0]][:, None], g[f"t_ref_{refs[0]}_c"].values, g[f"t_ref_{refs[-1]}_c"].values)
        fits["joint"] = k_fit(ts_all[both], q_all[both], t_ref_both[both], depths, A)
        kfits[hf] = fits
        for n in refs:
            m = sel[n]
            ks = {"config": k_cfg, "own_fit": fits[n], "joint_fit": fits["joint"],
                  **{f"fit_on_{o}": fits[o] for o in refs if o != n}}
            for kname, k in ks.items():
                model = conduction(ts_all[m], q_all[m], depths, k, A)
                for r in metrics(model, g[f"t_ref_{n}_c"].values[m], depths):
                    rows.append({"reference": n, "heat_flow": hf, "k_source": kname, "k_w_mk": k, **r})
    res = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT_CSV, index=False, float_format="%.4g")
    pd.set_option("display.width", 200)
    print("conductivity fits (W/m/K):", {h: {n: round(v, 3) for n, v in f.items()} for h, f in kfits.items()})
    print(res.groupby(["reference", "heat_flow", "k_source"])[["k_w_mk", "bias_c", "rmse_c", "r"]].mean().round(2).to_string())

    # hexbins at the configured heat flow and k
    ic.use()
    hf_cfg = CFG["thermal"]["heat_flow"]
    fig, axes = plt.subplots(len(refs), len(depths), figsize=(2.1 * len(depths), 2.3 * len(refs)), squeeze=False,
                             sharex=True, sharey=True)
    for a, n in zip(axes, refs):
        m = sel[n]
        other = [h for h in HEAT_FLOW if h != hf_cfg][0]
        model = conduction(ts_all[m], g[HEAT_FLOW[hf_cfg]].values[m], depths, k_cfg, A)
        ref = g[f"t_ref_{n}_c"].values[m]
        base = conduction(ts_all[m], g[HEAT_FLOW[other]].values[m], depths, k_cfg, A)
        for j, (ax, d) in enumerate(zip(a, depths)):
            ok = np.isfinite(ref[:, j])
            x, y = ref[ok, j], model[ok, j]
            ax.hexbin(x, y, gridsize=40, bins="log", cmap="Blues", mincnt=1, linewidths=0)
            ax.plot((0, 450), (0, 450), color=ic.INK, lw=ic.SEAM, ls=(0, (3, 2)))
            ax.set_xlim(0, 450); ax.set_ylim(0, 450)
            xb = base[ok, j]
            ax.text(0.04, 0.96, f"bias {np.mean(y - x):+.0f} °C ({np.mean(xb - x):+.0f})\n"
                                f"RMSE {np.sqrt(np.mean((y - x) ** 2)):.0f} °C ({np.sqrt(np.mean((xb - x) ** 2)):.0f})\n"
                                f"r = {np.corrcoef(x, y)[0, 1]:.2f} ({np.corrcoef(x, xb)[0, 1]:.2f})",
                    transform=ax.transAxes, va="top", fontsize=6.5, color=ic.INK)
            ax.set_title(f"{LABEL[n]}, {d:g} km" if j == 0 else f"{d:g} km", loc="left")
            ax.grid(False)
            if ax in axes[-1]:
                ax.set_xlabel("reference model (°C)")
        a[0].set_ylabel("conduction estimate (°C)")
    fig.suptitle(f"Rock temperature at depth: 1-D conduction (heat flow {hf_cfg}, k = {k_cfg} W/m/K) vs the reference "
                 f"models; in brackets on heat flow {other}", x=0.01, ha="left", color=ic.INK)
    fig.tight_layout()
    for f in FIGS:
        f.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(f, dpi=CFG["plotting"]["dpi"])
    plt.close(fig)

    # Europe: Limberger minus conduction at 4.5 km; cells outside the model show the conduction-only area in grey
    if "limberger_europe" in refs:
        j = depths.index(4.5)
        lon, lat = g["lon"].values, g["lat"].values
        box = (lon > -26) & (lon < 46) & (lat > 33) & (lat < 72)
        lim = g["t_ref_limberger_europe_c"].values[:, j]
        diff = lim - g["t_conduction_lucazeau_c"].values[:, j]
        fig, axs = plt.subplots(1, 2, figsize=(11, 5.0))
        step = CFG["grid"]["step_deg"]
        ii = np.floor((lat - 33) / step).astype(int)
        kk = np.floor((lon + 26) / step).astype(int)
        shape = (int(round(39 / step)), int(round(72 / step)))
        for ax, val, cmap, vmin, vmax, title in (
                (axs[0], lim, "inferno", 50, 250, "Limberger model, T at 4.5 km (°C)"),
                (axs[1], diff, "RdBu_r", -120, 120, "Limberger minus conduction on Lucazeau at 4.5 km (°C)")):
            land, ras = np.zeros(shape), np.full(shape, np.nan)
            land[ii[box], kk[box]] = 1
            ras[ii[box], kk[box]] = val[box]
            ext = (-26, 46, 33, 72)
            ax.imshow(np.where(land > 0, 1.0, np.nan), origin="lower", extent=ext, cmap="Greys", vmin=0, vmax=5,
                      interpolation="nearest")
            sc = ax.imshow(ras, origin="lower", extent=ext, cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
            fig.colorbar(sc, ax=ax, shrink=0.7)
            ax.set_title(title, loc="left")
            ax.set_xlim(-26, 46); ax.set_ylim(33, 72); ax.set_aspect(1 / np.cos(np.radians(52)))
            ax.grid(False)
            for s in ax.spines.values():
                s.set_visible(False)
            ax.set_xticks([]); ax.set_yticks([])
        fig.tight_layout()
        for f in DIFF:
            fig.savefig(f, dpi=CFG["plotting"]["dpi"])
        plt.close(fig)


if __name__ == "__main__" or "snakemake" in globals():
    main()
