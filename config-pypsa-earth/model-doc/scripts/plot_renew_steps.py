"""The standard procedure for wind and solar in three panels, drawn for onshore wind in north-west Europe (Renewables & Weather).

(a) eligible land: the share of each weather cell on which onshore wind may be built (potential of
    resources/NWE/renewable_profiles/profile_onwind.nc over cell area x capacity_per_sqkm); the box is the region of
    the land-eligibility figure (plot_renew_eligibility.py);
(b) weather: the mean capacity factor of 2013 of the cells with eligible land (cells_onwind.nc, the same atlite
    conversion as the profiles, per cell);
(c) what add_electricity receives: one generator per bus of the base network (networks/NWE/base.nc), its potential as
    marker area and the mean of its profile as colour.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_renew_steps.py [--out build/figures/renew_steps.pdf]
"""

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from pyproj import Transformer

HERE = Path(snakemake.scriptdir) if "snakemake" in globals() else Path(__file__).resolve().parent
TOP = HERE.parent
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

FORK = TOP / "../../models/pypsa-earth"
STAGE = "NWE"
DEFAULTS = dict(
    profile=FORK / f"resources/{STAGE}/renewable_profiles/profile_onwind.nc",
    cells=FORK / f"resources/{STAGE}/renewable_profiles/cells_onwind.nc",
    base=FORK / f"networks/{STAGE}/base.nc",
    shape=FORK / f"resources/{STAGE}/shapes/country_shapes.geojson",
    eligibility=TOP / f"build/renewables_check/eligibility_{STAGE}.npz",
)
CAPACITY_PER_SQKM = 3.0   # renewable: onwind: capacity_per_sqkm (fork default, not changed by the project)
R_EARTH = 6371.0
CF_MAX = 0.6
MARKER = 40                    # marker area of the bus with the largest potential, points^2
SIZE_GW = [2, 10]             # marker legend of panel (c)


def cell_area(y, dy, dx):
    """km2 of a dx x dy degree cell centred at latitude y."""
    lo, hi = np.deg2rad(y - dy / 2), np.deg2rad(y + dy / 2)
    return R_EARTH**2 * np.deg2rad(dx) * (np.sin(hi) - np.sin(lo))


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    for k, v in DEFAULTS.items():
        p.add_argument(f"--{k}", default=v)
    p.add_argument("--out", default=TOP / "build/figures/renew_steps.pdf")
    if "snakemake" in globals():
        a = p.parse_args([x for k in DEFAULTS for x in (f"--{k}", snakemake.input[k])] + ["--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    shape = gpd.read_file(a.shape)
    with xr.open_dataset(a.profile) as ds:
        potential = ds["potential"].load()
        bus_cf = ds["profile"].mean("time").to_pandas()
        bus_potential = ds["p_nom_max"].to_pandas()
    dx = float(np.median(np.diff(potential.x)))
    dy = float(np.median(np.diff(potential.y)))
    area = xr.DataArray(cell_area(potential.y.values, dy, dx), coords=[potential.y])
    share = (potential / (CAPACITY_PER_SQKM * area)).clip(0, 1)
    with xr.open_dataset(a.cells) as ds:
        cx, cy, ccf, cmw = (ds[v].values for v in ["x", "y", "cf", "mw"])
    with xr.open_dataset(a.base) as ds:
        bx = dict(zip(ds["buses_i"].values.astype(str), ds["buses_x"].values))
        by = dict(zip(ds["buses_i"].values.astype(str), ds["buses_y"].values))

    st.use()
    fig = plt.figure(layout="none", figsize=(6.3, 2.75))
    x0, y0, x1, y1 = shape.total_bounds
    pad = 0.6
    axes = [fig.add_axes([0.005 + i * 0.335, 0.17, 0.32, 0.72]) for i in range(3)]
    for ax, title in zip(axes, ["(a) Eligible land", "(b) Weather of 2013", "(c) Generators handed to the model"]):
        st.map_axes(ax)
        shape.plot(ax=ax, color=st.LAND, edgecolor="none")
        shape.boundary.plot(ax=ax, color="#9a9a9a", linewidth=0.4, zorder=4)
        ax.set_xlim(x0 - pad, x1 + pad)
        ax.set_ylim(y0 - pad, y1 + pad)
        ax.set_aspect(1 / np.cos(np.deg2rad((y0 + y1) / 2)))
        ax.set_title(title, loc="left", fontsize=8)

    extent = [float(potential.x.min()) - dx / 2, float(potential.x.max()) + dx / 2,
              float(potential.y.min()) - dy / 2, float(potential.y.max()) + dy / 2]
    left, right, bottom, top = np.load(a.eligibility)["extent"]      # the box of the land-eligibility figure (Mollweide)
    to_deg = Transformer.from_crs("ESRI:54009", "EPSG:4326", always_xy=True)
    corners = [to_deg.transform(x, y) for x, y in [(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)]]
    axes[0].plot(*zip(*corners), color="#111111", linewidth=0.8, zorder=5)
    m0 = axes[0].imshow(np.where(share.values > 0, share.values, np.nan), extent=extent, origin="lower", cmap="Greens",
                        vmin=0, vmax=1, zorder=2, interpolation="nearest", aspect="auto")
    grid = np.full(potential.shape, np.nan)
    ix = np.rint((cx - float(potential.x.min())) / dx).astype(int)
    iy = np.rint((cy - float(potential.y.min())) / dy).astype(int)
    ok = (ix >= 0) & (ix < grid.shape[1]) & (iy >= 0) & (iy < grid.shape[0]) & (cmw > 0)
    grid[iy[ok], ix[ok]] = ccf[ok]
    m1 = axes[1].imshow(grid, extent=extent, origin="lower", cmap="viridis", vmin=0, vmax=CF_MAX, zorder=2,
                        interpolation="nearest", aspect="auto")
    buses = [b for b in bus_cf.index.astype(str) if b in bx]
    size = MARKER * bus_potential.reindex(bus_cf.index).values / bus_potential.max()
    order = np.argsort(-size)
    axes[2].scatter(np.array([bx[b] for b in buses])[order], np.array([by[b] for b in buses])[order], s=size[order] + 0.3,
                    c=bus_cf.values[order], cmap="viridis", vmin=0, vmax=CF_MAX, linewidths=0.15, edgecolors="white", zorder=3)

    for ax in axes:                                   # imshow resets the aspect
        ax.set_aspect(1 / np.cos(np.deg2rad((y0 + y1) / 2)))
        ax.set_anchor("N")
    st.colorbar(fig, m0, fig.add_axes([0.03, 0.105, 0.27, 0.022]), "Share of the cell's area that is eligible",
                ticks=[0, 0.5, 1], fmt="{x:.1f}")
    st.colorbar(fig, m1, fig.add_axes([0.365, 0.105, 0.27, 0.022]), "Mean capacity factor", ticks=[0, 0.3, 0.6])
    st.colorbar(fig, m1, fig.add_axes([0.69, 0.105, 0.15, 0.022]), "Mean capacity factor", ticks=[0, 0.3, 0.6])
    lax = fig.add_axes([0.87, 0.0, 0.13, 0.17])
    lax.set_axis_off()
    lax.set_xlim(0, 1)
    lax.set_ylim(0, 1)
    for i, gw in enumerate(SIZE_GW):
        lax.scatter(0.12, 0.72 - 0.42 * i, s=MARKER * gw * 1e3 / bus_potential.max() + 0.3, color="#8a8a8a", linewidths=0)
        lax.text(0.3, 0.72 - 0.42 * i, f"{gw} GW", va="center", fontsize=6.5, color=st.TEXT)

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=220)
    print(f"buses {len(buses)}, potential {bus_potential.sum() / 1e3:,.0f} GW, eligible cells {int(ok.sum())}, "
          f"largest bus {bus_potential.max() / 1e3:,.0f} GW -> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
