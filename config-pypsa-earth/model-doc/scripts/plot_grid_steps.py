"""The standard grid procedure in three panels, drawn for Brazil (Grid Data, standard procedure).

(a) raw OpenStreetMap: every power line and cable that earth-osm extracted (resources/BR/osm/raw), coloured by its highest
    tagged voltage, lines below the 200 kV threshold in light steel;
(b) base network after cleaning and building (networks/BR/base.nc): buses and lines from 200 kV, HVDC in red;
(c) clustered network of the optimisation (networks/BR-now/elec_s_50.nc): 50 buses, lines drawn with a width proportional
    to their capacity, the clustered onshore regions as background (their outlines only: the region files' bus names
    are permuted against the network's for BR, so no lookup by name);
(d), (e) the same close-up (Sao Paulo) twice on OpenStreetMap's own map tiles, for direct comparison: (d) the raw lines of
    (a), coloured as there, and the raw substations; (e) the base network of (b), its lines drawn straight from bus to
    bus in the same colours. The cleaning shows: lines below 200 kV gone, nearby substations merged into one bus per
    voltage, parallel lines into one line with several circuits. Tiles from tile.openstreetmap.org (tile usage policy: identifying user agent, local cache,
    attribution), cached in build/osm_tiles/.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_grid_steps.py [--out build/figures/grid_steps.pdf]
"""

import argparse
import io
import json
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

HERE = Path(snakemake.scriptdir) if "snakemake" in globals() else Path(__file__).resolve().parent
TOP = HERE.parent
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

FORK = TOP / "../../models/pypsa-earth"
DEFAULTS = dict(
    raw_lines=FORK / "resources/BR/osm/raw/all_raw_lines.csv",
    raw_cables=FORK / "resources/BR/osm/raw/all_raw_cables.csv",
    base=FORK / "networks/BR/base.nc",
    clustered=FORK / "networks/BR-now/elec_s_50.nc",
    regions=FORK / "resources/BR-now/bus_regions/regions_onshore_elec_s_50.geojson",
    shape=FORK / "resources/BR/shapes/country_shapes.geojson",
    raw_substations=FORK / "resources/BR/osm/raw/all_raw_substations.csv",
)
THRESHOLD_KV = 200
ZOOM = ("S\u00e3o Paulo", (-46.62, -23.62), 18, 11)   # one close-up for (d) and (e): name, centre, half side km, tile zoom
TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = "catalyst-model-doc/0.1 (PyPSA Labs methods document)"
R_EARTH = 6378137.0
# voltage classes (kV, upper bound exclusive) -> colour: one hue, light -> dark with voltage
CLASSES = [(300, "#8fb3d9", "200–299 kV"), (600, st.BLUE, "300–599 kV"), (np.inf, "#123a63", "600 kV and above")]
HVDC = st.VERMILLION
LOW = "#8593a1"   # lines below the threshold: a darker steel, visible on the pale land


def max_kv(tag):
    """Highest voltage of an OSM voltage tag ("500000;230000" -> 500), NaN if none."""
    vals = []
    for part in str(tag).replace(",", ";").split(";"):
        try:
            vals.append(float(part) / 1e3)
        except ValueError:
            pass
    return max(vals) if vals else np.nan


def colour(kv):
    if not kv >= THRESHOLD_KV:
        return LOW
    return next(c for hi, c, _ in CLASSES if kv < hi)


def raw_segments(fn):
    df = pd.read_csv(fn, usecols=["lonlat", "tags.voltage", "tags.frequency"], dtype=str)
    segs = [np.asarray(json.loads(s)) for s in df.lonlat]
    kv = df["tags.voltage"].map(max_kv).values
    dc = df["tags.frequency"].fillna("").str.strip().eq("0").values
    return segs, kv, dc


def network(fn):
    ds = xr.open_dataset(fn)
    xy = pd.DataFrame({"x": ds.buses_x.values, "y": ds.buses_y.values}, index=ds.buses_i.values)
    def seg(comp, mask=None):
        b0, b1 = ds[f"{comp}_bus0"].values, ds[f"{comp}_bus1"].values
        if mask is not None:
            b0, b1 = b0[mask], b1[mask]
        return np.stack([xy.loc[b0].values, xy.loc[b1].values], axis=1)
    return ds, xy, seg


def merc(lon, lat):
    """Web Mercator metres (EPSG:3857) of lon/lat degrees."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    return R_EARTH * np.deg2rad(lon), R_EARTH * np.log(np.tan(np.pi / 4 + np.deg2rad(lat) / 2))


def zoom_box(centre, half_km):
    """(x0, x1, y0, y1) in Web Mercator metres of a square of 2 x half_km on the ground."""
    cx, cy = merc(*centre)
    h = half_km * 1e3 / np.cos(np.deg2rad(centre[1]))
    return cx - h, cx + h, cy - h, cy + h


def basemap(ax, box, z, cache):
    """Stitch the OSM tiles of zoom z covering box (Web Mercator) into ax, lightened so the overlay reads."""
    import requests
    from PIL import Image

    n = 2 ** z
    size = 2 * np.pi * R_EARTH / n
    tx = lambda x: int((x + np.pi * R_EARTH) // size)
    ty = lambda y: int((np.pi * R_EARTH - y) // size)
    xs, ys = range(tx(box[0]), tx(box[1]) + 1), range(ty(box[3]), ty(box[2]) + 1)
    img = Image.new("RGB", (256 * len(xs), 256 * len(ys)))
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            fn = Path(cache) / str(z) / str(x) / f"{y}.png"
            if not fn.exists():
                r = requests.get(TILES.format(z=z, x=x, y=y), headers={"User-Agent": USER_AGENT}, timeout=30)
                r.raise_for_status()
                fn.parent.mkdir(parents=True, exist_ok=True)
                fn.write_bytes(r.content)
            img.paste(Image.open(fn).convert("RGB"), (256 * i, 256 * j))
    extent = (xs[0] * size - np.pi * R_EARTH, (xs[-1] + 1) * size - np.pi * R_EARTH,
              np.pi * R_EARTH - (ys[-1] + 1) * size, np.pi * R_EARTH - ys[0] * size)
    ax.imshow(np.asarray(img), extent=extent, interpolation="lanczos", zorder=0)
    ax.add_patch(Rectangle((extent[0], extent[2]), extent[1] - extent[0], extent[3] - extent[2], fc="white", alpha=0.55,
                           lw=0, zorder=0.5))


def raw_substations(fn):
    """Centroids (lon, lat) of OSM substations (nodes and polygons)."""
    df = pd.read_csv(fn, usecols=["lonlat"], dtype=str)
    out = []
    for s in df.lonlat:
        try:
            out.append(np.asarray(json.loads(s), float).reshape(-1, 2).mean(axis=0))
        except (ValueError, TypeError):
            pass
    return np.array(out)


def frame(ax, shape, title):
    shape.plot(ax=ax, color=st.LAND, edgecolor=st.TICK, linewidth=0.4, zorder=0)
    ax.set_title(title, fontsize=7.6, loc="left", pad=2, linespacing=1.3)
    ax.set_axis_off()
    ax.set_aspect(1 / np.cos(np.deg2rad(12)))


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    for key, val in DEFAULTS.items():
        p.add_argument(f"--{key.replace('_', '-')}", dest=key, default=val)
    p.add_argument("--out", default=TOP / "build/figures/grid_steps.pdf")
    p.add_argument("--tiles", default=TOP / "build/osm_tiles")
    if "snakemake" in globals():
        args = sum([[f"--{k.replace('_', '-')}", str(snakemake.input[k])] for k in DEFAULTS], [])
        a = p.parse_args(args + ["--out", str(snakemake.output[0]), "--tiles", str(snakemake.params.tiles)])
    else:
        a = p.parse_args()

    st.use()
    shape = gpd.read_file(a.shape)
    H = 6.35
    fig = plt.figure(layout="none", figsize=(6.3, H))
    top = 2.35 / H   # height of a top-row map
    axes = [fig.add_axes([k / 3 + 0.004, 1 - 0.42 / H - top, 1 / 3 - 0.008, top]) for k in range(3)]
    zaxes = [fig.add_axes([k / 2 + 0.01, 0.62 / H, 1 / 2 - 0.02, 2.75 / H]) for k in range(2)]

    # (a) raw OSM
    segs, kv, dc = [], [], []
    for fn in (a.raw_lines, a.raw_cables):
        s, k, d = raw_segments(fn)
        segs += s
        kv = np.r_[kv, k]
        dc = np.r_[dc, d]
    cols = [HVDC if d else colour(k) for k, d in zip(kv, dc)]
    order = np.argsort([0 if c == LOW else 1 for c in cols], kind="stable")   # low voltage underneath
    frame(axes[0], shape, f"(a) OpenStreetMap\n{len(segs):,} lines and cables")
    axes[0].add_collection(LineCollection([segs[i] for i in order], colors=[cols[i] for i in order],
                                          linewidths=[0.4 if cols[i] == LOW else 0.45 for i in order], zorder=2))

    # (b) base network
    ds, xy, seg = network(a.base)
    frame(axes[1], shape, f"(b) base network, from 200 kV\n{ds.sizes['buses_i']:,} buses, {ds.sizes['lines_i']:,} lines")
    axes[1].add_collection(LineCollection(seg("lines"), colors=[colour(v) for v in ds.lines_v_nom.values], linewidths=0.45, zorder=2))
    axes[1].add_collection(LineCollection(seg("links", ds.links_carrier.values == "DC"), colors=HVDC, linewidths=0.9, zorder=3))
    axes[1].scatter(xy.x, xy.y, s=0.6, color=st.TEXT, lw=0, zorder=4)

    # (c) clustered network
    ds, xy, seg = network(a.clustered)
    regions = gpd.read_file(a.regions)
    frame(axes[2], shape, f"(c) network of the optimisation\n{ds.sizes['buses_i']} buses, {ds.sizes['lines_i']} lines")
    regions.boundary.plot(ax=axes[2], color="#bdbdbd", linewidth=0.35, zorder=1)
    s_nom = ds.lines_s_nom.values
    axes[2].add_collection(LineCollection(seg("lines"), colors=st.BLUE, linewidths=0.4 + 2.6 * np.sqrt(s_nom / s_nom.max()),
                                          capstyle="round", zorder=2))
    dcm = ds.links_carrier.values == "DC"
    p_nom = ds.links_p_nom.values[dcm]
    axes[2].add_collection(LineCollection(seg("links", dcm), colors=HVDC, linewidths=0.4 + 2.6 * np.sqrt(p_nom / s_nom.max()),
                                          capstyle="round", zorder=3))
    axes[2].scatter(xy.x, xy.y, s=9, color="white", ec=st.TEXT, lw=0.6, zorder=4)

    x0, y0, x1, y1 = shape.total_bounds
    for ax in axes:
        ax.set_xlim(x0 - 0.5, x1 + 0.5)
        ax.set_ylim(y0 - 0.5, y1 + 0.5)

    # (d), (e): the same close-up, raw OSM (a) and base network (b), on OSM's map tiles
    ds, xy, seg = network(a.base)
    bpos = pd.DataFrame(np.c_[merc(xy.x.values, xy.y.values)], index=xy.index, columns=["x", "y"])
    dcm = ds.links_carrier.values == "DC"
    base_segs, base_cols = [], []
    for comp, mask, colours in (("lines", None, [colour(v) for v in ds.lines_v_nom.values]),
                                ("links", dcm, [HVDC] * int(dcm.sum()))):
        b0, b1 = ds[f"{comp}_bus0"].values, ds[f"{comp}_bus1"].values
        if mask is not None:
            b0, b1 = b0[mask], b1[mask]
        base_segs += list(np.stack([bpos.loc[b0].values, bpos.loc[b1].values], axis=1))
        base_cols += colours
    subs = raw_substations(a.raw_substations)
    sx, sy = merc(subs[:, 0], subs[:, 1])
    raw_m = [np.c_[merc(sg[:, 0], sg[:, 1])] for sg in segs]
    name, centre, half, z = ZOOM
    box = zoom_box(centre, half)
    inside = lambda X, Y: (X >= box[0]) & (X <= box[1]) & (Y >= box[2]) & (Y <= box[3])
    hit = sorted((i for i, m in enumerate(raw_m) if inside(m[:, 0], m[:, 1]).any()), key=lambda i: cols[i] != LOW)
    si = inside(sx, sy)
    bi = inside(bpos.x.values, bpos.y.values)
    nb = sum(inside(sg[:, 0], sg[:, 1]).any() for sg in base_segs)
    titles = [f"(d) {name}, {2 * half} \u00d7 {2 * half} km, OpenStreetMap\n{len(hit)} lines, {si.sum()} substations",
              f"(e) the same area in the base network\n{nb} lines, {bi.sum()} buses"]
    for k, (zax, title) in enumerate(zip(zaxes, titles)):
        basemap(zax, box, z, a.tiles)
        if k == 0:
            zax.add_collection(LineCollection([raw_m[i] for i in hit], colors=[cols[i] for i in hit],
                                              linewidths=[0.7 if cols[i] == LOW else 1.3 for i in hit], zorder=2))
            zax.scatter(sx[si], sy[si], s=9, marker="s", facecolor="none", ec=st.PINK, lw=0.7, zorder=3)
        else:
            zax.add_collection(LineCollection(base_segs, colors=base_cols, linewidths=1.3, zorder=2))
            zax.scatter(bpos.x[bi], bpos.y[bi], s=30, color="white", ec=st.TEXT, lw=1.2, zorder=5)
        zax.set_xlim(box[0], box[1])
        zax.set_ylim(box[2], box[3])
        zax.set_aspect("equal")
        zax.set_xticks([])
        zax.set_yticks([])
        zax.grid(False)
        for sp in zax.spines.values():
            sp.set_visible(True)
            sp.set_color(st.TEXT)
            sp.set_linewidth(0.6)
        zax.set_title(title, fontsize=7.6, loc="left", pad=3, linespacing=1.3)
        zax.text(0.99, 0.01, "\u00a9 OpenStreetMap contributors", transform=zax.transAxes, ha="right", va="bottom",
                 fontsize=5.4, color=st.TICK, zorder=7, bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))
    # where the close-up sits, in (a) and (b)
    lon0, lat0 = np.rad2deg(box[0] / R_EARTH), np.rad2deg(2 * np.arctan(np.exp(box[2] / R_EARTH)) - np.pi / 2)
    lon1, lat1 = np.rad2deg(box[1] / R_EARTH), np.rad2deg(2 * np.arctan(np.exp(box[3] / R_EARTH)) - np.pi / 2)
    pad = 0.35
    for ax, label in zip(axes[:2], "de"):
        ax.add_patch(Rectangle((lon0 - pad, lat0 - pad), lon1 - lon0 + 2 * pad, lat1 - lat0 + 2 * pad, fc="none",
                               ec=st.TEXT, lw=0.9, zorder=6))
        ax.text(lon0 - pad - 0.4, lat1 + pad, label, ha="right", va="top", fontsize=7, color=st.TEXT, zorder=6)

    lax = fig.add_axes([0, 0, 1, 0.5 / H])
    lax.set_axis_off()
    items = [(LOW, "below 200 kV (dropped)")] + [(c, lab) for _, c, lab in CLASSES] + [(HVDC, "HVDC")]
    handles = [Rectangle((0, 0), 1, 1, fc=c, ec="none", lw=0) for c, _ in items]
    handles += [Line2D([], [], ls="", marker="o", ms=5, mfc="white", mec=st.TEXT, mew=1.2),
                Line2D([], [], ls="", marker="s", ms=4, mfc="none", mec=st.PINK, mew=0.7)]
    labels = [l for _, l in items] + ["base network bus", "OSM substation"]
    lax.legend(handles, labels, loc="center", ncol=4, frameon=False, fontsize=7, columnspacing=1.2, handletextpad=0.5)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=400)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(f"raw {len(segs)}, -> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
