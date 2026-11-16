"""Check of the HVDC capacities against the project list (Grid Data, adjustments).

Left: the France-Great Britain links as OpenStreetMap draws them, one colour per project. Right: capacity per cross-border
pair in North-West Europe: the clustered network without corrections, the corrections and the operating projects, the
last two from build/grid_check/borders_NWE.csv (../scripts/check_grid.py, read-only). build/hvdc_check.csv holds the numbers
per pair and the sums per region (the "before" networks are the archived solves of results/archive/<R>-now-oldcalib).
The uncorrected networks are the `now` solves of 2026-10-20, archived before the rebuild of 2026-11-08
(results/archive/<R>-now-20261020; links are not extendable there, so their capacity is the prenetwork's);
networks/<R>/base.nc, read for the base-network columns of the region rows, is the rebuilt one.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_hvdc_check.py
"""

import argparse
import ast
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import xarray as xr

HERE = Path(snakemake.scriptdir) if "snakemake" in globals() else Path(__file__).resolve().parent
TOP = HERE.parent
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

FORK = TOP / "../../models/pypsa-earth"
REGIONS = {"US": ["US"], "BR": ["BR"], "IN": ["IN"], "CN": ["CN"], "NWE": "IE GB FR BE NL LU DE DK CH AT CZ PL".split()}
PROJECTS = {"IFA 2000": st.ORANGE, "ElecLink": st.GREEN, "IFA2": st.BLUE}
BOX = (-2.2, 3.0, 49.0, 51.6)


def dc_links(fn):
    """DC links of a network: bus0, bus1, p_nom (MW), length (km)."""
    ds = xr.open_dataset(fn)
    df = pd.DataFrame({"bus0": ds.links_bus0.values.astype(str), "bus1": ds.links_bus1.values.astype(str),
                       "carrier": ds.links_carrier.values.astype(str), "p_nom": ds.links_p_nom.values,
                       "length": ds.links_length.values})
    return df[df.carrier == "DC"]


def operating(projects, countries):
    """Projects in service by 2024 with both terminals in the region; the list's status lags, so the year decides."""
    p = projects[projects.country1.isin(countries) & projects.country2.isin(countries)]
    return p[(p.year <= 2024) & (p.status != "decommissioned")]


def pair_table(after, borders):
    a, b = after.bus0.str[:2], after.bus1.str[:2]
    cross = after[a != b]
    now = cross.groupby(["-".join(sorted(x)) for x in zip(cross.bus0.str[:2], cross.bus1.str[:2])]).p_nom.sum() / 1e3
    b = pd.read_csv(borders, index_col=0)
    t = pd.DataFrame({"now": now, "corrected": b.corrected_sum, "list": b.listed}).fillna(0.0)
    return t.sort_values("list")


def region_table(forks, projects):
    rows = []
    for r, countries in REGIONS.items():
        new = dc_links(forks["after"][r])
        base = dc_links(forks["base"][r])
        p = operating(projects, countries)
        rows.append({"region": r, "before_gw": dc_links(forks["before"][r]).p_nom.sum() / 1e3, "after_gw": new.p_nom.sum() / 1e3,
                     "list_gw": p.p_nom_mw.sum() / 1e3, "links": len(new), "projects": len(p), "base_links": len(base),
                     "base_km": base.length.sum(), "rating_km_weighted_gw": (base.p_nom * base.length).sum() / base.length.sum() / 1e3,
                     "list_mean_gw": p.p_nom_mw.mean() / 1e3, "after_gwkm": (new.p_nom * new.length).sum() / 1e3})
    return pd.DataFrame(rows)


def channel_ways(raw_files):
    """The named HVDC ways of the three France-Great Britain projects in OpenStreetMap."""
    ways = []
    for fn in raw_files:
        r = pd.read_csv(fn, low_memory=False, usecols=["id", "lonlat", "tags.name", "tags.frequency"])
        r = r[pd.to_numeric(r["tags.frequency"], errors="coerce") == 0].dropna(subset=["tags.name"])
        r = r.assign(project=r["tags.name"].str.replace(r" bipole \d$", "", regex=True))
        r = r[r.project.isin(PROJECTS)]
        ways += [(name, np.array(ast.literal_eval(ll))) for name, ll in zip(r.project, r["lonlat"])]
    return ways


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--projects", default=TOP / "../data/hvdc/hvdc_projects.csv")
    p.add_argument("--borders", default=TOP / "build/grid_check/borders_NWE.csv")
    p.add_argument("--countries", default=TOP / "../../misc-quarter1/country-classification/data/ne_50m_admin_0_countries/ne_50m_admin_0_countries.shp")
    p.add_argument("--out", default=TOP / "build/figures/hvdc_check.pdf")
    p.add_argument("--table", default=TOP / "build/hvdc_check.csv")
    if "snakemake" in globals():
        a = p.parse_args(["--projects", str(snakemake.input.projects), "--countries", str(snakemake.input.countries), "--borders", str(snakemake.input.borders),
                          "--out", str(snakemake.output.fig), "--table", str(snakemake.output.table)])
    else:
        a = p.parse_args()

    projects = pd.read_csv(a.projects, comment="#")
    forks = {"after": {r: FORK / f"results/archive/{r}-now-20261020/networks/elec_s_50_ec_lcopt_3h.nc" for r in REGIONS},
             "before": {r: FORK / f"results/archive/{r}-now-oldcalib/networks/elec_s_50_ec_lcopt_3h.nc" for r in REGIONS},
             "base": {r: FORK / f"networks/{r}/base.nc" for r in REGIONS}}
    pairs = pair_table(dc_links(forks["after"]["NWE"]), a.borders)
    regions = region_table(forks, projects)
    ways = channel_ways([FORK / f"resources/NWE/osm/raw/all_raw_{k}.csv" for k in ["cables", "lines"]])

    st.use()
    fig, (ax0, ax1) = plt.subplots(1, 2, layout="none", figsize=(6.3, 2.75), gridspec_kw={"width_ratios": [1.0, 1.05]})
    plt.subplots_adjust(left=0.015, right=0.97, top=0.88, bottom=0.1, wspace=0.2)

    world = gpd.read_file(a.countries)
    world.plot(ax=ax0, color=st.LAND, edgecolor="#bdbdbd", linewidth=0.4, zorder=1)
    for name, xy in ways:
        ax0.plot(xy[:, 0], xy[:, 1], color=PROJECTS[name], lw=1.5, solid_capstyle="round", zorder=3)
    ax0.set_xlim(BOX[:2])
    ax0.set_ylim(BOX[2:])
    ax0.set_aspect(1 / np.cos(np.deg2rad(50.3)))
    ax0.set_xticks([])
    ax0.set_yticks([])
    ax0.grid(False)
    for s in ax0.spines.values():
        s.set_visible(True)
        s.set_color("#bdbdbd")
        s.set_linewidth(0.5)
    ax0.set_title("(a) France–GB HVDC links in OpenStreetMap", loc="left", fontsize=7.5)
    st.legend_squares(ax0, [(c, n) for n, c in PROJECTS.items()], loc="upper left", bbox_to_anchor=(0.0, 1.0), fontsize=6.5)

    y = np.arange(len(pairs))
    h = 0.27
    for k, (col, colour) in enumerate([("list", st.ORANGE), ("corrected", st.BLUE), ("now", st.NEUTRAL)]):
        ax1.barh(y + (k - 1) * h, pairs[col], height=h, color=colour, linewidth=0, zorder=2)
    for yi, (_, r) in zip(y, pairs.iterrows()):
        ax1.text(max(r["now"], r["corrected"]) + 0.12, yi, f"{r['corrected']:.1f}", va="center", fontsize=6.2, color=st.TEXT)
    ax1.set_yticks(y, [s.replace("-", "–") for s in pairs.index], fontsize=7)
    ax1.set_ylim(-0.6, len(pairs) - 0.4)
    ax1.set_xlim(0, 9)
    ax1.grid(axis="x", visible=True)
    ax1.grid(axis="y", visible=False)
    ax1.set_title("(b) Cross-border HVDC capacity, GW", loc="left", fontsize=7.5)
    ax1.legend(handles=[Patch(facecolor=c, linewidth=0, label=l) for c, l in [(st.NEUTRAL, "model, before correction"), (st.BLUE, "model, after correction"), (st.ORANGE, "operating projects")]],
               loc="center right", bbox_to_anchor=(1.0, 0.5))

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=300)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    out = pd.concat([pairs.reset_index(names="pair").assign(table="pair"), regions.assign(table="region")])
    out.to_csv(a.table, index=False, float_format="%.2f")
    print(pairs.round(2).to_string(), "\n", regions.round(2).to_string(), f"\nways {len(ways)}\n-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
