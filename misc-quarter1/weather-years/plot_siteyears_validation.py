"""Validation figure of the site-years calibration (misc-quarter1/weather-years): for every site the 2013
duration curves of the PyPSA-Earth bus profile against the stencil mean, raw and calibrated, wind and
solar, with the hourly correlation and the standard-deviation ratio of the calibrated series.

Standalone: python plot_siteyears_validation.py
"""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import xarray as xr
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

if "snakemake" in globals():
    CFG = snakemake.config  # noqa: F821
    VAL = Path(snakemake.input.validation)  # noqa: F821
    CAL = Path(snakemake.input.calibration)  # noqa: F821
    OUTS = [Path(p) for p in snakemake.output]  # noqa: F821
else:
    _HERE = Path(__file__).resolve().parent
    CFG = yaml.safe_load((_HERE / "config.yaml").read_text())
    VAL = _HERE / "build" / "siteyears_2013.nc"
    CAL = _HERE / "build" / "siteyears_calibration.csv"
    OUTS = [_HERE / "figures" / f"siteyears_validation.{f}" for f in CFG["plotting"]["formats"]]

ds = xr.open_dataset(VAL)
cal = pd.read_csv(CAL).set_index(["site", "resource"])
col = CFG["colours"]
sites = list(ds.site.values)
ncol = 5
nrow = int(np.ceil(len(sites) / ncol))
fig, axes = plt.subplots(nrow, ncol, figsize=(3.4 * ncol, 3.0 * nrow), sharex=True, sharey=True)
hours = np.arange(8760) / 8760 * 100
for ax, site in zip(axes.flat, sites):
    for tech in ("wind", "solar"):
        for var, ls, lw, label in (("bus", "-", 1.6, "PyPSA-Earth bus"), ("raw", ":", 1.0, "stencil mean, raw"), ("cal", "--", 1.2, "stencil mean, calibrated")):
            v = ds[f"{var}_{tech}"].sel(site=site).values
            if np.isnan(v).all():
                continue                                   # hand-placed resource point: no bus profile
            ax.plot(hours, np.sort(v)[::-1], ls, color=col[tech], lw=lw, label=f"{tech}: {label}")
    w, so = cal.loc[(site, "wind")], cal.loc[(site, "solar")]
    fmt = lambda r, name: (f"{name} r {r.cal_r_hourly:.2f}, σ ratio {r.cal_std_ratio:.2f}, f {r.factor:.2f}" if not np.isnan(r.cal_r_hourly)  # noqa: E731
                           else f"{name} {r.location}: target {r.target_cf:.2f}, f {r.factor:.2f}" if not np.isnan(r.target_cf) else f"{name} {r.location}: raw")
    ax.text(0.98, 0.97, f"{fmt(w, 'wind')}\n{fmt(so, 'solar')}", transform=ax.transAxes, ha="right", va="top", fontsize=7.5)
    ax.set_title(site, fontsize=9)
    ax.set_ylim(0, 1)
    ax.grid(alpha=0.3)
for ax in axes.flat[len(sites):]:
    ax.axis("off")
for ax in axes[-1]:
    ax.set_xlabel("share of hours [%]")
for ax in axes[:, 0]:
    ax.set_ylabel("capacity factor")
handles, labels = axes.flat[0].get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=8, frameon=False, bbox_to_anchor=(0.5, -0.01))
year = int(ds.attrs["description"].split(":")[0])
fig.suptitle(f"Site-years calibration check, {year}: duration curves of the resource bus's PyPSA-Earth profile vs the ERA5 stencil mean "
             "(wind: speed factor f on the 100 m wind; solar: factor f on the capacity factor; hand-placed points have no bus)", fontsize=10)
fig.tight_layout(rect=(0, 0.05, 1, 0.96))
for out in OUTS:
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=CFG["plotting"]["dpi"], bbox_inches="tight")
print("wrote", *OUTS)
