"""Figures: world map of reactor sites by status, and cost per kW of the
projects with a published estimate.

Inputs   build/nuclear_sites.csv, build/project_costs.csv, build/nea_benchmarks.csv
Outputs  figures/nuclear_sites_map.png     operating / construction / planned sites, size = MW
         figures/nuclear_cost_per_kw.png   USD2024/kW by project, initial vs latest, coloured by family
         figures/nuclear_cost_strip.png    one strip: USD2024/kW, colour = region, shape = reactor type, area = MW
Standalone: python plot_maps.py
"""

from pathlib import Path

import geopandas as gpd
import matplotlib
import matplotlib.patheffects
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from matplotlib.lines import Line2D
from matplotlib.transforms import blended_transform_factory

HERE = Path(__file__).parent
if "snakemake" in globals():
    CFG = snakemake.config
    SITES, COSTS, NEA = (Path(snakemake.input[k]) for k in ("sites", "costs", "nea"))
    OUT_MAP, OUT_COST, OUT_STRIP = Path(snakemake.output.map), Path(snakemake.output.cost), Path(snakemake.output.strip)
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    SITES, COSTS, NEA = HERE / "build/nuclear_sites.csv", HERE / "build/project_costs.csv", HERE / "build/nea_benchmarks.csv"
    OUT_MAP, OUT_COST = HERE / "figures/nuclear_sites_map.png", HERE / "figures/nuclear_cost_per_kw.png"
    OUT_STRIP = HERE / "figures/nuclear_cost_strip.png"

GEN_COLOR = {"lwr-large": "#444444", "lwr-smr": "#4c72b0", "gen4": "#c44e52", "phwr": "#55a868",
             "fusion": "#da8bc3", "unknown": "#aaaaaa"}
GEN_LABEL = {"lwr-large": "large LWR (Gen II/III+)", "lwr-smr": "light-water SMR", "gen4": "Gen IV (label gives coolant)",
             "phwr": "PHWR", "fusion": "fusion", "unknown": "type unknown"}
GEN4_TAG = {"htgr": "HTGR", "fast": "fast, Na/Pb", "msr": "molten salt", "fhr": "fluoride salt"}
STATUS_MARK = {"built": dict(marker="o", fill=True, label="built"),
               "construction": dict(marker="^", fill=True, label="under construction"),
               "planned": dict(marker="o", fill=False, label="planned (pre-construction / announced)"),
               "cancelled": dict(marker="x", fill=True, label="cancelled")}


def gen_of(families):
    fams = families.split("/")
    if any(f in GEN4_TAG for f in fams):
        return "gen4"
    for f in ("lwr-smr", "lwr-large", "phwr", "fusion"):
        if f in fams:
            return f
    return "unknown"


def plot_map(sites):
    world = gpd.read_file((HERE / CFG["archetype_data_dir"] / "ne_50m_admin_0_countries"
                           / "ne_50m_admin_0_countries.shp").resolve())
    s = sites[sites.status_group.isin(["operating", "construction", "planned"])].copy()
    s["gen"] = s["families"].map(gen_of)
    s["st"] = s["status_group"].replace({"operating": "built"})
    # marker area ~ MW; small-reactor sites (SMR, Gen IV) get a floor so that they stay visible
    floor = np.where(s.gen.isin(["gen4", "lwr-smr"]), 400, 20)
    s["size"] = np.sqrt(s.capacity_mw.clip(lower=floor)) * 1.6
    fig, ax = plt.subplots(figsize=(16, 7.4))
    world.plot(ax=ax, color="#efede6", edgecolor="white", linewidth=0.4)
    # draw order: planned (hollow) first, then built, then construction, Gen IV last so it stays visible
    for st in ("planned", "built", "construction"):
        for gen in ("lwr-large", "phwr", "unknown", "fusion", "lwr-smr", "gen4"):
            p = s[s.st.eq(st) & s.gen.eq(gen)]
            m = STATUS_MARK[st]
            c = GEN_COLOR[gen]
            strong = gen in ("gen4", "lwr-smr")
            ax.scatter(p.lon, p.lat, s=p["size"] * (1.3 if m["marker"] == "^" else 1), marker=m["marker"],
                       facecolor=c if m["fill"] else "none", edgecolor=c if not m["fill"] else "white",
                       linewidth=(1.6 if strong else 1.0) if not m["fill"] else 0.3,
                       alpha=0.95 if strong else (0.85 if m["fill"] else 0.9), zorder=4 if strong else 3)
    ax.set_xlim(-170, 180)
    ax.set_ylim(-58, 80)
    ax.set_aspect("equal")
    ax.set_axis_off()
    tot = s.groupby("gen")["capacity_mw"].sum() / 1e3
    h_gen = [Line2D([], [], marker="s", linestyle="", color=GEN_COLOR[g], markersize=8,
                    label=f"{GEN_LABEL[g].split(' (')[0]}: {tot.get(g, 0):.0f} GW") for g in GEN_COLOR if g in set(s.gen)]
    tot_st = s.groupby("st")["capacity_mw"].sum() / 1e3
    h_st = [Line2D([], [], marker=m["marker"], linestyle="", markerfacecolor="0.3" if m["fill"] else "white",
                   markeredgecolor="0.3", markeredgewidth=1.2, markersize=8,
                   label=f"{m['label']}: {tot_st.get(st, 0):.0f} GW") for st, m in STATUS_MARK.items() if st in set(s.st)]
    size_handles = [Line2D([], [], marker="o", linestyle="", color="#777777", markersize=np.sqrt(np.sqrt(mw) * 1.6),
                           label=f"{mw:,} MW") for mw in (300, 1200, 4800)]
    size_handles.append(Line2D([], [], linestyle="", label="SMR / Gen IV sites: at least 400 MW-size"))
    leg1 = ax.legend(handles=h_gen, loc="lower left", bbox_to_anchor=(0.0, 0.0), frameon=False, fontsize=10,
                     title="reactor generation (colour)", title_fontsize=10)
    ax.add_artist(leg1)
    leg2 = ax.legend(handles=h_st, loc="lower left", bbox_to_anchor=(0.2, 0.0), frameon=False, fontsize=10,
                     title="status (marker)", title_fontsize=10)
    ax.add_artist(leg2)
    ax.legend(handles=size_handles, loc="lower right", bbox_to_anchor=(0.98, 0.02), frameon=False, fontsize=10,
              title="site capacity", title_fontsize=10, labelspacing=1.2)
    ax.set_title("Nuclear power sites: operating, under construction and planned, by reactor generation "
                 "(Global Energy Monitor, Global Nuclear Power Tracker, August 2026)", fontsize=12, loc="left")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.95, bottom=0.01)
    OUT_MAP.parent.mkdir(exist_ok=True)
    fig.savefig(OUT_MAP, dpi=170)


def plot_costs(costs, nea):
    col = [c for c in costs.columns if c.endswith("_per_kw")][0]
    d = costs[costs[col].notna() & costs["category"].isin(["new-build", "programme"])].copy()
    fam = d["family"].fillna("unknown")
    d["gen"] = np.where(fam.isin(GEN4_TAG), "gen4", fam.where(fam.isin(GEN_COLOR), "unknown"))
    d["label"] = (d["project"].str.replace(" nuclear power plant", "", regex=False)
                  .str.replace(" nuclear power station", "", regex=False) + ", " + d["country"])
    d.loc[d.gen.eq("gen4"), "label"] += " [" + fam[d.gen.eq("gen4")].map(GEN4_TAG) + "]"
    # one row per project: the latest figure with the initial one as a tail
    latest = d[d.estimate_kind.isin(["latest", "final"])].sort_values(col).drop_duplicates("label", keep="last")
    initial = d[d.estimate_kind.eq("initial")].sort_values(col).drop_duplicates("label", keep="first").set_index("label")
    only_initial = initial[~initial.index.isin(latest["label"])].reset_index()
    rows = pd.concat([latest, only_initial]).sort_values(col, ascending=False).reset_index(drop=True)
    half = int(np.ceil(len(rows) / 2))
    panels = [rows.iloc[:half], rows.iloc[half:]]
    fig, axes = plt.subplots(1, 2, figsize=(15, 0.26 * half + 2.4))
    bench = nea[nea[col].notna() & nea["technology"].str.contains("new build|EPR|ALWR|VVER|LWR", regex=True)
                & nea["source"].str.contains("Projected Costs")]
    for ax, part in zip(axes, panels):
        part = part.reset_index(drop=True)
        for i, r in part.iterrows():
            c = GEN_COLOR[r["gen"]]
            m = STATUS_MARK[r["units_status"]]
            is_latest = r["estimate_kind"] != "initial"
            if is_latest and r["label"] in initial.index:
                x0 = initial.loc[r["label"], col]
                ax.plot([x0, r[col]], [i, i], color=c, linewidth=1.2, alpha=0.6)
                ax.scatter(x0, i, marker="|", color=c, s=80)
            ax.scatter(r[col], i, marker=m["marker"], s=70 if m["marker"] == "^" else 55,
                       facecolor=c if m["fill"] else "white", edgecolor=c, linewidth=1.4, zorder=3)
        ax.set_yticks(np.arange(len(part)))
        ax.set_yticklabels(part["label"], fontsize=8)
        for tick, g in zip(ax.get_yticklabels(), part["gen"]):
            tick.set_color(GEN_COLOR[g])
        ax.set_ylim(len(part) - 0.5, -0.5)
        ax.set_xscale("log")
        ax.set_xlim(900, 40000)
        ax.set_xticks([1000, 2000, 5000, 10000, 20000])
        ax.set_xticklabels(["1,000", "2,000", "5,000", "10,000", "20,000"])
        ax.set_xlabel(f"{col.replace('_per_kw', '').upper()} per kW covered")
        ax.grid(True, axis="x", which="both", color="0.85", linewidth=0.5)
        ax.spines[["top", "right"]].set_visible(False)
        for _, b in bench.iterrows():
            ax.axvline(b[col], color="0.6", linestyle=":", linewidth=0.8)
    gens = [g for g in GEN_COLOR if g in set(rows["gen"])]
    h_gen = [Line2D([], [], marker="s", linestyle="", color=GEN_COLOR[g], label=GEN_LABEL[g]) for g in gens]
    h_status = [Line2D([], [], marker=m["marker"], linestyle="", markerfacecolor="0.3" if m["fill"] else "white",
                       markeredgecolor="0.3", markeredgewidth=1.4, markersize=8, label=m["label"])
                for m in STATUS_MARK.values()]
    h_other = [Line2D([], [], marker="|", linestyle="-", color="0.4", label="initial estimate → latest / final"),
               Line2D([], [], linestyle=":", color="0.6", label="IEA/NEA Projected Costs 2020, overnight by country")]
    leg1 = axes[1].legend(handles=h_gen, loc="lower right", bbox_to_anchor=(1, 0.16), fontsize=8, frameon=False,
                          title="reactor generation (colour)", title_fontsize=8)
    axes[1].add_artist(leg1)
    axes[1].legend(handles=h_status + h_other, loc="lower right", fontsize=8, frameon=False,
                   title="project status (marker)", title_fontsize=8)
    fig.suptitle("Published nuclear project costs per kW: new build with a public figure (basis varies: overnight, total incl. "
                 "financing, contract or budget; see data/project_costs.csv)", fontsize=10, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    fig.savefig(OUT_COST, dpi=170)


# Okabe-Ito based (colour-blind safe); no red, which is reserved for the model-input lines
REGION_COLOR = {"China / India": "#E69F00", "Russia (domestic)": "#CC79A7", "South Korea (domestic)": "#009E73",
                "Rosatom export": "#56B4E9", "KHNP / CNNC export": "#C9A66B", "other": "#B5B5B5",
                "Europe / N. America / Japan": "#3B4B5C",
                "Europe / N. America / Japan: large LWR": "#3B4B5C",
                "Europe / N. America / Japan: light-water SMR": "#0072B2",
                "Europe / N. America / Japan: Gen IV": "#7B61A8"}
REGION_LABEL = {"Europe / N. America / Japan": "West", "Europe / N. America / Japan: large LWR": "West, large LWR (+ PHWR)",
                "Europe / N. America / Japan: light-water SMR": "West, light-water SMR",
                "Europe / N. America / Japan: Gen IV": "West, Gen IV"}
TYPE_MARK = {"lwr-large": ("o", "large LWR"), "lwr-smr": ("s", "light-water SMR"), "gen4": ("D", "Gen IV"),
             "phwr": ("^", "PHWR"), "fusion": ("*", "fusion"), "unknown": ("X", "type unknown")}


def plot_strip(costs):
    """One project per point: best available figure (final > latest > initial)."""
    col = [c for c in costs.columns if c.endswith("_per_kw")][0]
    d = costs[costs[col].notna() & costs["category"].isin(["new-build", "programme"])].copy()
    d["rank"] = d["estimate_kind"].map({"final": 0, "latest": 1, "initial": 2})
    d = d.sort_values(["rank", col], ascending=[True, False]).drop_duplicates("project")
    fam = d["family"].fillna("unknown")
    d["type"] = np.where(fam.isin(GEN4_TAG), "gen4", fam.where(fam.isin(TYPE_MARK), "unknown"))
    d = d[~d["type"].isin(["fusion", "unknown"])]
    region_of = {c: r for r, cs in CFG["cost_regions"].items() for c in cs}
    d["region"] = d["country"].map(region_of).fillna("other")
    d = d[~d["region"].isin(CFG.get("strip_exclude", []))]
    type_label = {"lwr-large": "large LWR", "phwr": "large LWR", "lwr-smr": "light-water SMR", "gen4": "Gen IV"}
    split = d["region"].isin(CFG.get("strip_split_by_type", []))
    d["group"] = np.where(split, d["region"] + ": " + d["type"].map(type_label), d["region"])
    rng = np.random.default_rng(7)
    d["x"] = rng.uniform(-1, 1, len(d))
    # drift factor per region from same-scope initial -> latest/final pairs (real USD)
    full = costs[costs["category"].isin(["new-build", "programme"])].copy()
    full["region"] = full["country"].map(region_of).fillna("other")
    key = ["project", "capacity_mw_covered"]
    ini = full[full.estimate_kind.eq("initial")].groupby(key)[col].min()
    lat = full[full.estimate_kind.isin(["latest", "final"])].groupby(key)[col].max()
    pairs = (lat / ini).dropna().rename("ratio").reset_index().merge(full.drop_duplicates("project")[["project", "region"]])
    stats = pairs.groupby("region")["ratio"].agg(["median", "count"])
    pooled = float(pairs["ratio"].median())
    drift, drift_note = {}, {}
    for r in REGION_COLOR:
        if r in stats.index and stats.loc[r, "count"] >= CFG["drift_min_pairs"]:
            drift[r] = float(stats.loc[r, "median"])
            drift_note[r] = f"×{drift[r]:.2f}"
        else:
            n = int(stats.loc[r, "count"]) if r in stats.index else 0
            drift[r] = pooled
            drift_note[r] = f"×{pooled:.2f}, pooled"
    # the marker sits at the expected final cost: the drift factor is latest / initial, so it is
    # applied to initial-kind figures only; a latest figure is a revised ex-ante number and stays
    d["exante"] = d[col].where(d.estimate_kind.eq("initial"))
    d["y"] = np.where(d.estimate_kind.eq("initial"), d[col] * d["region"].map(drift), d[col])
    # marker area proportional to MW covered (scatter's `s` is an area), with a floor so that
    # 100-300 MW units keep a readable shape
    d["size"] = (d["capacity_mw_covered"].clip(upper=5000) / 5000 * 26 ** 2).clip(lower=4.5 ** 2)

    plt.rcParams.update({"font.size": 13, "axes.labelsize": 14, "ytick.labelsize": 13, "legend.fontsize": 12.5,
                         "legend.title_fontsize": 13})
    # one panel; the legends sit side by side in a band above it, the model-input labels in a margin to its right
    fig = plt.figure(figsize=(12.5, 8.6))
    ax = fig.add_axes([0.085, 0.035, 0.71, 0.745])
    for t, (marker, _) in TYPE_MARK.items():
        for r, c in REGION_COLOR.items():
            p = d[d.type.eq(t) & d.group.eq(r)]
            if len(p):
                ax.scatter(p.x, p.y, s=p["size"], marker=marker, facecolor=c, edgecolor="white",
                           linewidth=0.8, alpha=0.9, zorder=3)
                q = p[p.exante.notna() & (p.exante != p.y)]
                ax.vlines(q.x, q.exante, q.y, color=c, linewidth=0.9, alpha=0.7, zorder=2)
                ax.scatter(q.x, q.exante, marker="_", s=30, color=c, linewidth=0.9, alpha=0.7, zorder=2)
    # a few named points
    names = {"Hinkley Point": "Hinkley Point C", "Alvin W Vogtle": "Vogtle 3-4", "Flamanville": "Flamanville 3",
             "Darlington New": "Darlington BWRX-300", "Kemmerer": "Natrium", "Olkiluoto": "Olkiluoto 3",
             "Barakah": "Barakah", "Akkuyu": "Akkuyu", "Kudankulam": "Kudankulam 3-6", "Saeul": "Shin-Kori 3-4",
             "Sanmen": "Sanmen 3-4", "Rajasthan": "Rajasthan 7-8", "Kalpakkam": "PFBR", "Paks": "Paks II",
             "CFPP": "NuScale CFPP", "Sizewell": "Sizewell C", "Dukovany": "Dukovany 5-6", "El Dabaa": "El Dabaa",
             "Rooppur": "Rooppur", "Leningrad": "Leningrad 7-8", "Seversk": "BREST-300"}
    for _, r in d.iterrows():
        key = r["project"].replace(" nuclear power plant", "").replace(" nuclear power station", "")
        if key in names:
            off = 4 + np.sqrt(r["size"]) / 2                 # clear of the marker, whatever its size
            right = {"Vogtle 3-4": True, "Kudankulam 3-6": False}.get(names[key], r.x < 0.55)   # crowded spots by hand
            ax.annotate(names[key], (r.x, r.y), xytext=(off if right else -off, 0), textcoords="offset points",
                        fontsize=11, ha="left" if right else "right", va="center", color="0.3", zorder=6,
                        path_effects=[matplotlib.patheffects.withStroke(linewidth=2.5, foreground="white")])
    ax.set_yscale("log")
    ax.set_ylim(1200, 40000)
    ax.set_yticks([1500, 2000, 3000, 5000, 10000, 20000, 30000])
    ax.set_yticklabels(["1,500", "2,000", "3,000", "5,000", "10,000", "20,000", "30,000"])
    ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_ylabel(f"Expected final cost [{col.replace('_per_kw', '').upper()}/kW]")
    ax.set_xlim(-1.2, 1.2)
    ax.set_xticks([])
    ax.grid(True, axis="y", which="major", color="0.9", linewidth=0.7)
    ax.spines[["top", "right", "bottom"]].set_visible(False)
    ax.spines["left"].set_color("0.5")
    ax.tick_params(axis="y", colors="0.25")
    # the model's CAPEX per nuclear bin (technology_assumptions.csv): a dashed line in the colour of the group it
    # stands for, labelled over several lines in the right margin
    mi = CFG.get("model_inputs")
    if mi:
        ta = pd.read_csv((HERE / mi["csv"]).resolve(), dtype=str, keep_default_na=False).set_index("technology")
        for key, row in mi["rows"].items():
            v = float(ta.at[key, "capex_power_usd_kw"])
            c = REGION_COLOR[row["group"]]
            ax.axhline(v, color=c, linestyle=(0, (6, 3)), linewidth=2.0, zorder=2.5)
            ax.text(1.015, v, f"Model input\n{row['label']}:\n{v:,.0f}", transform=blended_transform_factory(ax.transAxes, ax.transData),
                    color=c, fontsize=13, fontweight="bold", va="center", ha="left", linespacing=1.25, clip_on=False)
    counts = d.group.value_counts()
    h_reg = [Line2D([], [], marker="o", linestyle="", color=c, markersize=12, label=f"{REGION_LABEL.get(r, r)} ({counts.get(r, 0)})")
             for r, c in REGION_COLOR.items() if counts.get(r, 0)]
    h_typ = [Line2D([], [], marker=m, linestyle="", color="0.45", markersize=12, label=lab)
             for t, (m, lab) in TYPE_MARK.items() if t in set(d.type)]
    h_size = [Line2D([], [], marker="o", linestyle="", color="0.6", markersize=max(np.sqrt(mw / 5000) * 26, 4.5),
                     label=f"{mw:,} MW") for mw in (300, 1200, 2400, 4800)]
    h_typ.append(Line2D([], [], marker="_", linestyle="-", color="0.4", markersize=8, label="initial estimate →\nexpected final cost"))
    kw = dict(loc="upper left", frameon=False, alignment="left", borderaxespad=0.0, handletextpad=0.5)
    for handles, title, x in ((h_reg, "Region (projects)", 0.085), (h_typ, "Reactor type", 0.44), (h_size, "Capacity covered", 0.69)):
        fig.add_artist(fig.legend(handles=handles, title=title, bbox_to_anchor=(x, 0.985), labelspacing=0.55, **kw))
    fig.savefig(OUT_STRIP, dpi=170)


def main():
    sites = pd.read_csv(SITES)
    plot_map(sites)
    costs = pd.read_csv(COSTS)
    nea = pd.read_csv(NEA)
    plot_costs(costs, nea)
    plot_strip(costs)


if __name__ == "__main__":
    main()
