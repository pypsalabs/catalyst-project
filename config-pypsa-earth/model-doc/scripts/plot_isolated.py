"""What happens to the isolated pieces of the OSM grid in China, India and North-West Europe (Grid Data, adjustments).

Recomputes, on the network before simplification (networks/<R>-now/elec.nc), the steps of simplify_network.py with
p_threshold_merge_isolated: false:
  1. drop_isolated_networks      AC sub-networks with mean load below 20 MW are deleted (p_threshold_drop_isolated)
  2. merge_into_network          per country, every sub-network other than the backbone (largest share) and below
                                 s_threshold_fetch_isolated = 5 % of the national load is mapped bus by bus onto the
                                 nearest backbone bus of the country; a sub-network across a border is never joined
fates(merge=True) adds the default merge_isolated_networks between the two (sub-networks below 300 MW become ONE bus per
country at the mean position of their buses), which scripts/check_grid.py compares against.
Sub-networks are AC only (lines and transformers): an area tied to the rest by HVDC alone is its own sub-network. DC
buses are left out (the fork's absorb_dc_buses maps them onto AC buses first). Mean load from loads_t.p_set.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_isolated.py [--out build/figures/isolated.pdf]
"""

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.sparse as sp
import xarray as xr
from matplotlib.collections import LineCollection
from scipy.sparse.csgraph import connected_components

HERE = Path(snakemake.scriptdir) if "snakemake" in globals() else Path(__file__).resolve().parent
TOP = HERE.parent
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import iconstyle as ic  # noqa: E402

FORK = TOP / "../../models/pypsa-earth"
REGIONS = {"IN": "India", "CN": "China", "NWE": "North-West Europe"}
DROP, MERGE, FETCH = 20.0, 300.0, 0.05
FATES = [  # key, colour, legend label
    ("backbone", ic.STEEL, "backbone"),
    ("separate", ic.BLUE, "own sub-network (5 % of load or more, or across a border)"),
    ("fetched", ic.AMBER, "joined to nearest backbone bus"),
    ("dropped", ic.INK, "dropped (below 20 MW)"),
]
COLOUR = {k: c for k, c, _ in FATES}


def fates(fn, merge=False):
    """Buses (x, y, country, load, fate), lines (bus0, bus1) and the merged node per country."""
    ds = xr.open_dataset(fn)
    buses = pd.DataFrame({"x": ds.buses_x.values, "y": ds.buses_y.values, "country": ds.buses_country.values,
                          "carrier": ds.buses_carrier.values}, index=ds.buses_i.values)
    buses = buses[buses.carrier != "DC"]
    idx = pd.Series(np.arange(len(buses)), buses.index)
    edges = []
    for c in ("lines", "transformers"):
        if f"{c}_bus0" in ds:
            b0, b1 = ds[f"{c}_bus0"].values, ds[f"{c}_bus1"].values
            ok = np.isin(b0, buses.index) & np.isin(b1, buses.index)
            edges.append(np.c_[b0[ok], b1[ok]])
    edges = np.vstack(edges)
    a = sp.coo_matrix((np.ones(len(edges)), (idx[edges[:, 0]].values, idx[edges[:, 1]].values)), shape=(len(buses),) * 2)
    buses["sub"] = connected_components(a, directed=False)[1]
    load = ds.loads_t_p_set.mean("snapshots").to_series()
    load = load.groupby(pd.Series(ds.loads_bus.values, ds.loads_i.values).reindex(load.index).values).sum()
    buses["load"] = load.reindex(buses.index).fillna(0.0)

    sub_load = buses.groupby("sub").load.sum()
    sub_countries = buses.groupby("sub").country.nunique()
    buses["fate"] = ""
    buses.loc[buses["sub"].map(sub_load) < DROP, "fate"] = "dropped"
    merged = {}
    for c, d in buses[buses.fate == ""].groupby("country"):
        nat = d.load.sum()
        share = d.groupby("sub").load.sum() / nat
        backbone = share.idxmax()
        small = d[d["sub"].map(sub_load) < MERGE] if merge else d.iloc[:0]
        small = small[small["sub"] != backbone]
        rest = d[(d["sub"] != backbone) & ~d.index.isin(small.index)]
        buses.loc[d.index[d["sub"] == backbone], "fate"] = "backbone"
        if len(small):
            m_share = small.load.sum() / nat
            merged[c] = dict(x=small.x.mean(), y=small.y.mean(), load=small.load.sum(), share=m_share,
                             fetched=m_share < FETCH)
            buses.loc[small.index, "fate"] = "merged"
        for s, ds_ in rest.groupby("sub"):
            multi = sub_countries[s] > 1
            buses.loc[ds_.index, "fate"] = "separate" if (multi or share[s] >= FETCH) else "fetched"
    lines = pd.DataFrame(edges, columns=["bus0", "bus1"])
    return buses, lines, merged


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--networks", nargs="+", default=[FORK / f"networks/{r}-now/elec.nc" for r in REGIONS])
    p.add_argument("--shapes", nargs="+", default=[FORK / f"resources/{r}/shapes/country_shapes.geojson" for r in REGIONS])
    p.add_argument("--out", default=TOP / "build/figures/isolated.pdf")
    p.add_argument("--table", default=None)
    if "snakemake" in globals():
        a = p.parse_args(["--networks", *map(str, snakemake.input.networks), "--shapes", *map(str, snakemake.input.shapes),
                          "--out", str(snakemake.output.fig), "--table", str(snakemake.output.table)])
    else:
        a = p.parse_args()

    ic.use()
    fig, axes = plt.subplots(1, 3, figsize=(6.3, 2.7), gridspec_kw=dict(width_ratios=[1.0, 1.25, 0.95], wspace=0.06))
    plt.subplots_adjust(left=0.0, right=1.0, top=0.86, bottom=0.17)
    summary = []
    for ax, (r, name), fn, shp in zip(axes, REGIONS.items(), a.networks, a.shapes):
        buses, lines, merged = fates(fn)
        shape = gpd.read_file(shp)
        shape.plot(ax=ax, color=ic.PALE, edgecolor=ic.MUTED, linewidth=0.3, zorder=0)
        xy = buses[["x", "y"]]
        lines = lines[lines.bus0.isin(xy.index) & lines.bus1.isin(xy.index)]
        f0 = buses.fate.reindex(lines.bus0).values
        for key, colour, _ in FATES:
            sel = lines[f0 == key]
            segs = np.stack([xy.loc[sel.bus0].values, xy.loc[sel.bus1].values], axis=1) if len(sel) else []
            ax.add_collection(LineCollection(segs, colors=colour, linewidths=0.25 if key == "backbone" else 0.7,
                                             zorder=1 if key == "backbone" else 3))
            b = buses[buses.fate == key]
            if key != "backbone":
                ax.scatter(b.x, b.y, s=1.5 if key != "dropped" else 2.5, color=colour, lw=0 if key != "dropped" else 0.5,
                           marker="o" if key != "dropped" else "x", zorder=4)
        counts = buses.drop_duplicates("sub").fate.value_counts()
        summary.append(dict(region=r, **counts.to_dict()))
        frag = buses[buses.fate == "fetched"].groupby(["country", "sub"]).load.sum()
        print(r, "largest joined share per country", (frag.groupby("country").max() / buses.groupby("country").load.sum()).round(4).dropna().to_dict())
        print(r, "separate", buses[buses.fate == "separate"].groupby("sub").agg(c=("country", "first"), n=("country", "size"), mw=("load", "sum")).round(0).to_dict("records"))
        pos = ax.get_position()
        fig.text(pos.x0 + 0.01, 0.97, f"{name}\n{buses['sub'].nunique()} AC sub-networks", fontsize=7.6, va="top",
                 linespacing=1.3, color=ic.INK)
        x0, y0, x1, y1 = shape.total_bounds
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.set_aspect(1 / np.cos(np.deg2rad((y0 + y1) / 2)))
        ax.set_axis_off()
        print(r, counts.to_dict())
    lax = fig.add_axes([0, 0, 1, 0.15])
    lax.set_axis_off()
    squares = [plt.Rectangle((0, 0), 1, 1, fc=c, ec=ic.INK, lw=ic.MARK) for _, c, _ in FATES]
    lax.legend(handles=squares, labels=[lab for _, _, lab in FATES],
               loc="center", bbox_to_anchor=(0.5, 0.45), ncol=2, frameon=False, columnspacing=1.0, handletextpad=0.4, fontsize=6.6)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=400)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    if a.table:
        pd.DataFrame(summary).to_csv(a.table, index=False)
    print(pd.DataFrame(summary).to_string(index=False), f"\n-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
