"""Radar of the residual demand variability by period band for the two pure cases (wind only,
solar only: the mean triangles of the years variant) and two countries whose supply is a
superposition of both (misc-quarter1/fourier): country-aggregated PyPSA-Earth capacity
factors and demand (2013), wind and solar each scaled so that together they generate
`overbuild` x annual demand with the energy share `mixes.<CC>.wind_share` from wind.

Outputs figures/residual_bands_mix.{png,pdf} and build/bands_mix.csv (label, colour key and line
style per case, so that plot_residual_structure.py can redraw the radar as row h of the years figure).
Standalone: python plot_mix_radar.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pypsa  # noqa: E402
import xarray as xr  # noqa: E402
import yaml  # noqa: E402

from bands import band_masks, band_ranges, band_stats, radar  # noqa: E402

if "snakemake" in globals():
    CFG = snakemake.config  # noqa: F821
    PURE = Path(snakemake.input.pure)  # noqa: F821
    NETWORKS = {r: Path(p) for r, p in zip(snakemake.params.regions, snakemake.input.networks)}  # noqa: F821
    OUT_FIG = [Path(p) for p in snakemake.output.figure]  # noqa: F821
    OUT_TABLE = Path(snakemake.output.table)  # noqa: F821
else:
    _HERE = Path(__file__).resolve().parent
    CFG = yaml.safe_load((_HERE / "config.yaml").read_text())
    PURE = _HERE / "build" / "profiles_years.nc"
    NETWORKS = {r: _HERE / CFG["networks_dir"] / spec["file"] for r, spec in CFG["regions"].items()}
    OUT_FIG = [_HERE / "figures" / f"residual_bands_mix.{fmt}" for fmt in CFG["plotting"]["formats"]]
    OUT_TABLE = _HERE / "build" / "bands_mix.csv"
for p in (OUT_FIG[0], OUT_TABLE):
    p.parent.mkdir(parents=True, exist_ok=True)

COL = CFG["colours"]
OVERBUILD = CFG["overbuild"]
EDGES = CFG["bands"]["edges_hours"]
BAND_NAMES = CFG["bands"]["labels"]
BAND_RANGES = band_ranges(EDGES)
VALUE = "shifted_pct_annual_demand"
MIXES = CFG["mixes"]


def country_profiles(n: pypsa.Network, countries: list[str]) -> pd.DataFrame:
    """Potential-weighted wind and solar capacity factors and the summed demand of the buses in
    `countries` (bus attribute `country`)."""
    buses = n.buses.index[n.buses.country.isin(countries)]
    out = {}
    for carrier, col in (("onwind", "cf_wind"), ("solar", "cf_solar")):
        g = n.generators[(n.generators.carrier == carrier) & n.generators.bus.isin(buses)]
        w = g.p_nom_max.clip(lower=0)
        out[col] = (n.generators_t.p_max_pu[g.index] * w).sum(axis=1) / w.sum()
    loads = n.loads.index[n.loads.bus.isin(buses)]
    out["demand_mw"] = n.loads_t.p_set[loads].sum(axis=1)
    return pd.DataFrame(out)


def mixed_residual(df: pd.DataFrame, wind_share: float) -> pd.Series:
    """(d - P_w cf_w - P_s cf_s) / mean d with the two capacities chosen so that wind supplies
    wind_share and solar (1 - wind_share) of overbuild x annual demand."""
    d = df.demand_mw
    p_w = wind_share * OVERBUILD * d.sum() / df.cf_wind.sum()
    p_s = (1 - wind_share) * OVERBUILD * d.sum() / df.cf_solar.sum()
    return (d - p_w * df.cf_wind - p_s * df.cf_solar) / d.mean()


# --- pure cases: mean over the weather years of the years variant
ds = xr.open_dataset(PURE)
names = [str(v) for v in ds.series.values]
dem = ds.demand_mw.to_pandas()[names]
records = []
series = []
for hue, cf in (("wind", ds.cf_wind.to_pandas()[names]), ("solar", ds.cf_solar.to_pandas()[names])):
    p_nom = OVERBUILD * dem.sum() / cf.sum()
    res = (dem - cf * p_nom) / dem.mean()
    masks = band_masks(len(res), EDGES, BAND_NAMES)
    tri = np.mean([band_stats(res[nm], masks).loc[BAND_NAMES, VALUE].values for nm in names], axis=0)
    label = f"{hue} only, {ds.attrs.get('site', 'one site')}, mean of {len(names)} years"
    series.append(dict(label=label, colour=COL[hue], mean=tri))
    for band, val in zip(BAND_NAMES, tri):
        records.append({"case": f"{hue}-only", "label": label, "colour": hue, "ls": "-",
                        "wind_share": 1.0 if hue == "wind" else 0.0, "band": band, VALUE: val})

# --- country mixes
loaded = {}
for cc, spec in MIXES.items():
    if spec["region"] not in loaded:
        loaded[spec["region"]] = pypsa.Network(NETWORKS[spec["region"]])
    df = country_profiles(loaded[spec["region"]], spec["countries"])
    res = mixed_residual(df, spec["wind_share"])
    masks = band_masks(len(res), EDGES, BAND_NAMES)
    st = band_stats(res, masks)
    tri = st.loc[BAND_NAMES, VALUE].values
    label = f"{spec['name']}, {spec['wind_share']:.0%} wind / {1 - spec['wind_share']:.0%} solar by energy, 2013"
    series.append(dict(label=label, colour=COL["mixes"][cc], mean=tri, ls="--"))
    for band, val in zip(BAND_NAMES, tri):
        records.append({"case": spec["name"], "label": label, "colour": f"mixes.{cc}", "ls": "--",
                        "wind_share": spec["wind_share"], "band": band, VALUE: val,
                        "rms_pct_mean_demand": st.loc[band, "rms_pct_mean_demand"]})
    print(f"{spec['name']}: {len(df)} h, load {df.demand_mw.sum() / 1e6:.1f} TWh/a, mean CF wind {df.cf_wind.mean():.3f}, "
          f"solar {df.cf_solar.mean():.3f}, bands {np.round(tri, 1)}")

table = pd.DataFrame(records)
table.to_csv(OUT_TABLE, index=False, float_format="%.3f")
print(table.pivot(index="case", columns="band", values=VALUE)[BAND_NAMES].round(1))

fig = plt.figure(figsize=(6.4, 5.9), layout="constrained")
ax = fig.add_subplot(projection="polar")
h = radar(ax, series, BAND_NAMES, BAND_RANGES)
ax.set_title("Residual demand variability by period band: pure wind, pure solar, two country mixes\n"
             "energy a lossless storage on that band alone would cycle per year, % of annual demand;\n"
             f"generation = {OVERBUILD:.1f} × annual demand, no other flexibility; the country cases use\n"
             "PyPSA-Earth country-aggregated capacity factors and demand", fontsize=9, loc="left", color="0.15", pad=6)
ax.legend(handles=h, loc="upper center", bbox_to_anchor=(0.5, 0.23), frameon=False, fontsize=8)
for out in OUT_FIG:
    fig.savefig(out, dpi=CFG["plotting"]["dpi"])
print("wrote", ", ".join(str(o) for o in (*OUT_FIG, OUT_TABLE)))
