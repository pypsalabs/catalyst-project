"""Unsupervised cross-check of the rule-based archetypes: k-means + t-SNE.

Clusters the grids of country_features.csv into 5 groups from seven
engineered features (v2 - the first draft used signed import share and
hydro-only, which lumped US East / China / India into one dense-fossil blob
and stranded nuclear grids):

    autarky 0-1                     (1 at zero trade - highlights the LACK
                                     of import/export, not its direction)
    log10 population density        (land constraint)
    log10 expected 2050 kWh/capita  (wealth / demand volume, forward-looking)
    log2 demand growth to 2050      (India 1.24 vs US East 0.61 vs China 0.31
                                     - the axis that separates the giants)
    clean incumbent share           (hydro + nuclear % - gives France a home,
                                     pulls Canada toward the clean group;
                                     labelled "clean" not "clean-firm": for
                                     investment per tonne displaced the clean
                                     aspect matters more than the firm one)
    fossil share of generation      (brownfield)
    geothermal potential 0-1        (same scalar as classify.py: installed
                                     capacity / EGS share / T at 5 km)

K-means runs in the standardized 6-D feature space; t-SNE is used ONLY to
project that space to 2-D for the plot (clustering on t-SNE coordinates
directly is unstable). Micro grids (< 1 TWh demand) are excluded - they are
mostly data-poor islands and would smear the picture.

The k-means is fitted on the national rows (build/features_my.csv) so the
clusters do not depend on which countries are modelled together; the merged
North-West Europe row of country_features.csv (merge_nwe.py) is then folded
into its nearest cluster and replaces its members in the output.

Standalone experiment - deliberately NOT part of the Snakefile DAG, does not
touch country_features.csv or the rule-based classification (but needs the
pipeline's build/features_my.csv).

Run:  models/priam-myopic/.pixi/envs/default/bin/python cluster_tsne.py
Output: cluster_tsne.png + cluster memberships on stdout.
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.manifold import TSNE
from sklearn.preprocessing import StandardScaler

HERE = Path(__file__).parent
SEED = 0


def ramp(x, lo, hi):
    return np.clip((x - lo) / (hi - lo), 0.0, 1.0)


# The k-means is fitted on the NATIONAL rows (build/features_my.csv, the pipeline state before
# merge_nwe.py) so the world's cluster statistics do not depend on which countries are modelled
# together; the merged North-West Europe row of country_features.csv is folded in afterwards
# (nearest centroid) and replaces its eight members in everything displayed.
MERGED = {"NWE": ["ESP", "PRT", "FRA", "DEU", "BEL", "NLD", "LUX", "GBR"]}   # as in merge_nwe.py
NATIONAL = HERE / "build" / "features_my.csv"
if not NATIONAL.exists():
    raise SystemExit(f"{NATIONAL} missing - run the pipeline (snakemake -c1) first")

df = pd.read_csv(NATIONAL)
df = df[df["demand_twh"] >= 1].copy()          # drop micro grids


def make_feats(df):
    return pd.DataFrame({
        "autarky": 1 - ramp(df["net_import_share_pct"].fillna(0).abs(), 0, 20),
        "log_density": np.log10(df["pop_density_per_km2"].clip(lower=1)),
        "log_kwh_pc_2050": np.log10(df["demand_kwh_per_capita_2050"]),
        "demand_growth": np.log2(df["demand_twh_2050"] / df["demand_twh"]),
        "clean_firm_share": (df["share_hydro_pct"].fillna(0)
                             + df["share_nuclear_pct"].fillna(0)),
        "fossil_share": df["share_fossil_pct"].fillna(0),
        "geo_potential": (
            0.5 * np.maximum(ramp(np.log10(df["geothermal_capacity_mw"] + 1), 1, 3.3),
                             ramp(df["egs_suitable_share"], 0.05, 0.5))
            + 0.5 * ramp(df["t5km_p90_c"], 150, 300)),
    }, index=df.index)


feats = make_feats(df)
ok = feats.notna().all(axis=1)
feats, df = feats[ok], df[ok]

scaler = StandardScaler().fit(feats)
X = scaler.transform(feats)
# weight by expected 2050 demand: clusters partition TWh, not country count
# (unweighted, US East / China / India all collapse into one fossil blob
# because 45 mid-size fossil countries define that centroid)
km = KMeans(n_clusters=5, n_init=25, random_state=SEED).fit(
    X, sample_weight=df["demand_twh_2050"].values)
df["cluster"] = km.labels_

# stable-ish cluster naming: order clusters by mean fossil share
order = (feats.assign(c=km.labels_).groupby("c")["fossil_share"].mean()
         .sort_values(ascending=False).index)
rank = {c: i for i, c in enumerate(order)}
df["cluster"] = df["cluster"].map(rank)

# manual overrides, value = anchor grid whose cluster the key joins.
# IRN: heavily subsidized tariffs push consumption to ~3,900 kWh/cap, which
# reads as wealth and lands Iran in the dense-rich cluster; economically it
# belongs with the fast-growing fossil group (India et al.)
OVERRIDES = {"IRN": "IND"}
km_lab = km.labels_.copy()   # original labels, kept in sync for proximity
for o_iso3, o_anchor in OVERRIDES.items():
    p = np.flatnonzero(df["iso3"].values == o_iso3)
    a = np.flatnonzero(df["iso3"].values == o_anchor)
    df.iloc[p, df.columns.get_loc("cluster")] = df["cluster"].values[a[0]]
    km_lab[p] = km_lab[a[0]]

# fold the merged regions in: nearest centroid in z-space, members dropped
final = pd.read_csv(HERE / "country_features.csv")
mrow = final[final["iso3"].isin(MERGED)].copy()
mfeats = make_feats(mrow)
mX = scaler.transform(mfeats)
mlab = np.argmin(np.linalg.norm(mX[:, None, :] - km.cluster_centers_[None], axis=2), axis=1)
for i3, lab, mem in zip(mrow["iso3"], mlab, MERGED.values()):
    was = df[df["iso3"].isin(mem)].set_index("iso3")["cluster"]
    print(f"{i3} -> cluster {rank[lab]} (members were: "
          + ", ".join(f"{k} {v}" for k, v in was.items()) + ")")
members = [i for mem in MERGED.values() for i in mem]
keep = ~df["iso3"].isin(members).values
mrow["cluster"] = [rank[l] for l in mlab]
df = pd.concat([df[keep], mrow], ignore_index=True)
feats = pd.concat([feats[keep], mfeats], ignore_index=True)
X = np.vstack([X[keep], mX])
km_lab = np.concatenate([km_lab[keep], mlab])

xy = TSNE(n_components=2, perplexity=30, init="pca",
          random_state=SEED).fit_transform(X)

# same colours as the k_* archetypes in land-grid-map/data/archetypes.js, in CLUSTER_IDS order
COLORS = ["#DB2777", "#0B9E45", "#A85B00", "#E8380D", "#1D4ED8"]

fig, ax = plt.subplots(figsize=(13, 9))
size = 6 * np.sqrt(df["demand_twh_2050"])
for c in range(5):
    m = df["cluster"] == c
    ax.scatter(xy[m.values, 0], xy[m.values, 1], s=size[m], c=COLORS[c],
               alpha=0.75, edgecolors="white", linewidths=0.6,
               label=f"cluster {c} (n={int(m.sum())})")

# label the large grids and all sub-national / merged rows
big = df["demand_twh_2050"].nlargest(45).index
subnat = df.index[df["iso3"].isin(
    ["USE", "USW", "AUN", "AUW", "MYW", "MYE", "NWE"])]
for i, idx in enumerate(df.index):
    if idx in big or idx in subnat:
        ax.annotate(df.at[idx, "iso3"],
                    (xy[i, 0], xy[i, 1]), fontsize=7.5,
                    xytext=(3, 3), textcoords="offset points")

ax.set_title("k-means (k=5, demand-weighted) on 7 engineered SOW features, "
             "t-SNE projection\nautarky | density | 2050 kWh/cap | demand "
             "growth | clean incumbent (hydro+nuclear) | fossil | geothermal — "
             "dot area ~ 2050 demand")
ax.legend(loc="best", frameon=False)
ax.set_xticks([]), ax.set_yticks([])
fig.tight_layout()
out = HERE / "cluster_tsne.png"
fig.savefig(out, dpi=150)
print(f"-> {out}")

print("\ncluster means (unscaled):")
print(feats.assign(c=df["cluster"]).groupby("c").mean().round(2).to_string())
print("\nmembers (by 2050 demand):")
total = df["demand_twh_2050"].sum()
for c in range(5):
    m = df[df["cluster"] == c].sort_values("demand_twh_2050", ascending=False)
    print(f"\n[{c}] n={len(m)}, {m['demand_twh_2050'].sum() / total * 100:.0f}%"
          f" of 2050 demand: " + ", ".join(m["iso3"].head(28))
          + (" ..." if len(m) > 28 else ""))

# --- land-grid-map data version --------------------------------------------------
# Writes land-grid-map/data/layers/clusters-v1.js: the five clusters as archetypes
# (ids k_* defined in land-grid-map/data/archetypes.js, listed in DISPLAY_ORDER), one random modelled grid per cluster, and totals for the legend bars.
import json

CLUSTER_IDS = ["k_growth", "k_sparse", "k_densefossil", "k_geo", "k_cleanfirm"]
# legend / bar order on the page: SOW §1.2 archetype order, with the islanded slot taken by
# the high-renewables-potential cluster (k_growth)
DISPLAY_ORDER = ["k_densefossil", "k_geo", "k_islanded", "k_growth", "k_cleanfirm", "k_sparse"]
# display-only archetypes (no cluster behind them): SOW archetypes carried by a single modelled
# grid that is re-labelled on the map, in the legend and in the share bars, but keeps its cluster
# in the t-SNE view. Value = the grid's iso3.
EXTRA_ARCHETYPES = {"k_islanded": "SGP"}
REGION_ROWS = {"USE", "USW", "AUN", "AUW", "MYW", "MYE", "NWE"}   # own geometry in regions.js
MODELLED_SEED = 0
MODELLED_MIN_AREA_KM2 = 50_000
OUT_LAYER = HERE / "land-grid-map" / "data" / "layers" / "clusters-v1.js"

iso = pd.read_csv(HERE / "data" / "iso3166.csv", dtype={"country-code": str})
m49 = dict(zip(iso["alpha-3"], iso["country-code"]))


def map_key(iso3):
    return iso3 if iso3 in REGION_ROWS else m49.get(iso3)


# proximity: closeness to the own centroid in the standardized feature space (1 = at
# the centroid, 0 = as far as the farthest member of any cluster)
cent = km.cluster_centers_[km_lab]
dist = np.linalg.norm(X - cent, axis=1)
df["proximity"] = np.clip(1 - dist / dist.max(), 0.05, 1.0).round(3)
df["cluster_id"] = df["cluster"].map(dict(enumerate(CLUSTER_IDS)))
# archetype shown on the map / legend / bars: the cluster, except for the display-only archetypes
df["display_id"] = df["cluster_id"]
for aid, i3 in EXTRA_ARCHETYPES.items():
    assert (df["iso3"] == i3).any(), f"{i3} not among the clustered grids"
    df.loc[df["iso3"] == i3, "display_id"] = aid

# power-sector CO2 per row from the rule-based table (same rows, same Ember source)
arch = pd.read_csv(HERE / "country_archetypes.csv")
em = dict(zip(arch["iso3"], arch["emissions_mt"]))
df["emissions_mt"] = df["iso3"].map(em)

countries = {}
for r in df.itertuples(index=False):
    key = map_key(r.iso3)
    if key is not None:
        countries[key] = {"archetype": r.display_id,
                          "proximity": 1.0 if r.display_id != r.cluster_id else float(r.proximity)}

# fixed choice per cluster (iso3 / grid code); None -> seeded random draw below
MODELLED_FIXED = {"k_growth": "IND", "k_sparse": "USE", "k_densefossil": "NWE",
                  "k_geo": "USW", "k_cleanfirm": "BRA"}
cluster_of = dict(zip(df["iso3"], df["cluster_id"]))
rng = np.random.default_rng(MODELLED_SEED)
modelled_iso3 = {}
for cid in CLUSTER_IDS:
    if MODELLED_FIXED and MODELLED_FIXED.get(cid):
        i3 = MODELLED_FIXED[cid]
        assert cluster_of.get(i3) == cid, f"fixed modelled grid {i3} is in {cluster_of.get(i3)}, not {cid}"
        modelled_iso3[cid] = i3
        continue
    pool = df[(df["cluster_id"] == cid) & (df["demand_twh"] >= 10)
              & df["iso3"].map(lambda x: map_key(x) is not None)
              & (df["land_area_km2"].fillna(0) >= MODELLED_MIN_AREA_KM2)]
    if pool.empty:
        pool = df[(df["cluster_id"] == cid) & df["iso3"].map(lambda x: map_key(x) is not None)]
    modelled_iso3[cid] = str(rng.choice(pool["iso3"].to_numpy()))
modelled_iso3.update(EXTRA_ARCHETYPES)
modelled = {cid: map_key(i3) for cid, i3 in modelled_iso3.items()}
names = dict(zip(df["iso3"], df["name"]))
modelled_names = ", ".join(f"{names[i3]} ({cid})" for cid, i3 in modelled_iso3.items())

QUANTITIES = {"population": "population", "demand_twh": "demand_twh", "emissions_mt": "emissions_mt"}
totals = {q: {cid: float(df.loc[df["display_id"] == cid, col].fillna(0).sum()) for cid in DISPLAY_ORDER}
          for q, col in QUANTITIES.items()}
mrows = df["iso3"].isin(modelled_iso3.values())
modelled_totals = {q: float(df.loc[mrows, col].fillna(0).sum()) for q, col in QUANTITIES.items()}
totals_meta = {
    "population": {"label": "Population", "unit": "people", "year": "2025", "source": "World Bank WDI 2025"},
    "demand_twh": {"label": "Electricity consumption", "unit": "TWh", "year": "2024/25 (latest available)",
                   "source": "Ember / UN energy statistics 2024"},
    "emissions_mt": {"label": "Power-sector CO₂", "unit": "MtCO₂", "year": "2024",
                     "source": "Ember yearly release 2024 (via country_archetypes.csv)"},
    "coverage": f"{len(df)} clustered grids (≥ 1 TWh demand), {int(df['emissions_mt'].notna().sum())} with emissions data",
}
# --- "Method" tab of the map: the clustering inputs per grid, so the page can show the feature
# profile of every grid (z-scores as fed to k-means, raw values for hovering), the cluster
# centroids and the t-SNE projection. Feature order = columns of `feats`.
FEATURE_META = [
    {"id": "autarky", "label": "Autarky", "unit": "0–1",
     "desc": "1 at zero electricity trade, 0 at |net imports| ≥ 20 % of demand. Measures the absence of "
             "interconnection, not its direction."},
    {"id": "log_density", "label": "Population density", "unit": "log10 people/km²",
     "desc": "log10 of people per km² of land (floored at 1). Proxy for land constraint on renewables."},
    {"id": "log_kwh_pc_2050", "label": "2050 kWh per capita", "unit": "log10 kWh/cap",
     "desc": "log10 of expected electricity consumption per person in 2050. Wealth and demand volume, "
             "forward-looking."},
    {"id": "demand_growth", "label": "Demand growth to 2050", "unit": "log2 ratio",
     "desc": "log2 of expected 2050 demand over today's demand: 0 = flat, 1 = doubling. The axis that "
             "separates India from US East from China."},
    {"id": "clean_firm_share", "label": "Clean incumbent share", "unit": "% of generation",
     "desc": "Hydro plus nuclear share of today's generation. Incumbent low-carbon supply — what "
             "matters for investment per tonne displaced is that it is clean, not how firm it is."},
    {"id": "fossil_share", "label": "Fossil share", "unit": "% of generation",
     "desc": "Coal, gas and oil share of today's generation. Brownfield."},
    {"id": "geo_potential", "label": "Geothermal potential", "unit": "0–1",
     "desc": "Half from max(installed geothermal capacity, EGS-suitable land share), half from the p90 "
             "temperature at 5 km depth (150–300 °C ramp). Same scalar as classify.py."},
]
assert [f["id"] for f in FEATURE_META] == list(feats.columns)


def fmt_num(v, nd=0):
    return "n/a" if pd.isna(v) else f"{v:,.{nd}f}"


def disp_row(r, f):
    """Human-readable raw value per feature for the hover tooltip."""
    imp = df.at[r, "net_import_share_pct"]
    return [
        f"{f[0]:.2f}  (net imports {fmt_num(imp)} % of demand)",
        f"{fmt_num(df.at[r, 'pop_density_per_km2'])} people/km²",
        f"{fmt_num(df.at[r, 'demand_kwh_per_capita_2050'])} kWh/cap in 2050",
        f"×{2 ** f[3]:.2f}  ({fmt_num(df.at[r, 'demand_twh'])} → {fmt_num(df.at[r, 'demand_twh_2050'])} TWh)",
        f"{f[4]:.0f} % hydro + nuclear",
        f"{f[5]:.0f} % fossil",
        f"{f[6]:.2f}  ({fmt_num(df.at[r, 'geothermal_capacity_mw'])} MW installed, "
        f"{df.at[r, 'egs_suitable_share'] * 100:.0f} % EGS-suitable, T@5 km p90 {fmt_num(df.at[r, 't5km_p90_c'])} °C)",
    ]


rows = []
for i, r in enumerate(df.index):
    f = feats.loc[r].to_numpy()
    rows.append({
        "key": map_key(df.at[r, "iso3"]), "iso3": df.at[r, "iso3"], "name": df.at[r, "name"],
        "cluster": df.at[r, "cluster_id"], "proximity": float(df.at[r, "proximity"]),
        "demand_twh": round(float(df.at[r, "demand_twh"]), 1),
        "demand_twh_2050": round(float(df.at[r, "demand_twh_2050"]), 1),
        "x": round(float(xy[i, 0]), 2), "y": round(float(xy[i, 1]), 2),
        "z": [round(float(v), 2) for v in X[i]],
        "disp": disp_row(r, f),
        "override": df.at[r, "iso3"] in OVERRIDES,
    })
# centroids in z-space, keyed by cluster id (rank order), from the k-means centres
inv_rank = {v: k for k, v in rank.items()}
centroids = {CLUSTER_IDS[c]: [round(float(v), 2) for v in km.cluster_centers_[inv_rank[c]]]
             for c in range(5)}
explain = {
    "kind": "kmeans",
    "features": FEATURE_META,
    "centroids": centroids,
    "rows": rows,
    "method": ("Each grid is described by seven engineered features, standardised to z-scores "
               "(0 = average grid, ±1 = one standard deviation). k-means (k = 5, 25 restarts, seed 0) "
               "partitions the grids in that 7-D space, weighting each grid by its expected 2050 demand "
               "so the clusters split TWh rather than country count. Clusters are named by mean fossil share. "
               "The t-SNE view on the right projects the same 7-D space to two dimensions for display only "
               "(perplexity 30, PCA init); distances within it are qualitative. Grids below 1 TWh are excluded."),
    "overrides": OVERRIDES,
}

layer = {
    "id": "clusters-v1",
    "name": "k-means clusters v1",
    "description": (
        "Unsupervised k-means (k=5, weighted by expected 2050 demand) on seven engineered "
        "features: autarky, population density, 2050 kWh per capita, demand growth to 2050, "
        "clean incumbent share, fossil share, geothermal potential (misc-quarter1/country-classification/cluster_tsne.py). "
        "Grids below 1 TWh are not clustered and appear grey. "
        + (f"Modelled grids: {modelled_names}." if MODELLED_FIXED else
           f"Modelled grids are a random placeholder draw (seed {MODELLED_SEED}): {modelled_names}.")),
    "archetypes": DISPLAY_ORDER,
    "modelled": modelled,
    "countries": countries,
    "totals": totals,
    "modelled_totals": modelled_totals,
    "totals_meta": totals_meta,
    "explain": explain,
}
OUT_LAYER.parent.mkdir(parents=True, exist_ok=True)
OUT_LAYER.write_text("// GENERATED by cluster_tsne.py — k-means cluster data version.\n"
                     "window.LAYERS = window.LAYERS || [];\n"
                     "window.LAYERS.push(" + json.dumps(layer, ensure_ascii=False, indent=1) + ");\n")
print(f"\n-> {OUT_LAYER} ({len(countries)} map grids); modelled: {modelled_names}")
