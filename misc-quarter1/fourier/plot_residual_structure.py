"""Six-row figure: temporal structure of the residual demand under wind-only and solar-only
supply (misc-quarter1/fourier).

Rows (left: full year as daily means; right: two-week hourly snippet, local time)
  1  wind capacity factor
  2  solar capacity factor
  3  demand, normalised to its mean
  4  residual demand if wind alone is scaled to `overbuild` x annual demand (no storage)
  5  the same for solar
  6  left: one-sided amplitude spectrum of the residual series, averaged over the series per
     technology, smoothed at constant relative bandwidth with spectral lines kept, against
     period on a log axis, with the three period bands shaded
     right: the same information as a three-axis radar chart, one triangle per series and a
     thick one per technology: the energy that a lossless storage acting on that band alone
     would cycle per year, as % of annual demand

  7  (years variant only) the two pure triangles next to two country mixes, Great Britain
     wind-heavy and India solar-heavy, read from build/bands_mix.csv (plot_mix_radar.py)

Also written: the radar of row 6 alone (figures/residual_bands_<variant>) and the band numbers
(build/bands_<variant>.csv, incl. the band RMS as % of mean demand).

Generic over the `series` dimension of build/profiles_<variant>.nc: ten sites in one year
(extract_profiles.py) or ten weather years at one site (build_years.py); titles and the legend
come from the file's attributes. Within rows 1-5 lightness encodes the series order.

Standalone: python plot_residual_structure.py sites|years
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import xarray as xr  # noqa: E402
import yaml  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.transforms import blended_transform_factory  # noqa: E402

from bands import band_masks, band_ranges, band_stats, radar  # noqa: E402

if "snakemake" in globals():
    CFG = snakemake.config  # noqa: F821
    PROFILES = Path(snakemake.input.profiles)  # noqa: F821
    OUT_STRUCTURE = [Path(p) for p in snakemake.output.structure]  # noqa: F821
    OUT_BANDS = [Path(p) for p in snakemake.output.bands]  # noqa: F821
    OUT_TABLE = Path(snakemake.output.table)  # noqa: F821
    MIX = Path(snakemake.input.mix) if snakemake.input.get("mix") else None  # noqa: F821
else:
    import sys
    _HERE = Path(__file__).resolve().parent
    CFG = yaml.safe_load((_HERE / "config.yaml").read_text())
    VARIANT = sys.argv[1] if len(sys.argv) > 1 else "sites"        # sites | years
    PROFILES = _HERE / "build" / f"profiles_{VARIANT}.nc"
    OUT_STRUCTURE = [_HERE / "figures" / f"residual_structure_{VARIANT}.{fmt}" for fmt in CFG["plotting"]["formats"]]
    OUT_BANDS = [_HERE / "figures" / f"residual_bands_{VARIANT}.{fmt}" for fmt in CFG["plotting"]["formats"]]
    OUT_TABLE = _HERE / "build" / f"bands_{VARIANT}.csv"
    MIX = _HERE / "build" / "bands_mix.csv" if VARIANT == "years" else None
    if MIX is not None and not MIX.exists():
        MIX = None
for p in (OUT_STRUCTURE[0], OUT_TABLE):
    p.parent.mkdir(parents=True, exist_ok=True)

COL = CFG["colours"]
OVERBUILD = CFG["overbuild"]
SM = CFG["spectrum_smoothing"]
EDGES = CFG["bands"]["edges_hours"]
BAND_NAMES = CFG["bands"]["labels"]
SNIP = slice(pd.Timestamp(CFG["snippet"]["start"]), pd.Timestamp(CFG["snippet"]["end"]))

ds = xr.open_dataset(PROFILES)
names = [str(v) for v in ds.series.values]
KIND = ds.attrs.get("series_kind", "site")
cf_w = ds.cf_wind.to_pandas()[names]
cf_s = ds.cf_solar.to_pandas()[names]
dem = ds.demand_mw.to_pandas()[names]
N = len(dem)

dem_n = dem / dem.mean()                                   # demand as multiple of its mean
def residual(cf: pd.DataFrame) -> pd.DataFrame:
    """(demand - P cf) / mean demand with P chosen so annual generation = overbuild x annual demand."""
    p_nom = OVERBUILD * dem.sum() / cf.sum()
    return (dem - cf * p_nom) / dem.mean()
res_w, res_s = residual(cf_w), residual(cf_s)


# --- spectra -------------------------------------------------------------------------------
def spectrum(x: pd.Series):
    """One-sided amplitude spectrum, DC removed; returns (period in hours, amplitude)."""
    v = x.values - x.values.mean()
    amp = 2 * np.abs(np.fft.rfft(v)) / len(v)
    freq = np.fft.rfftfreq(len(v), d=1.0)
    return 1 / freq[1:], amp[1:]


def smooth_spectrum(per: np.ndarray, amp: np.ndarray, bandwidth: float, spike_factor: float) -> np.ndarray:
    """Constant-relative-bandwidth smoothing (mean over frequencies within +-bandwidth) that
    leaves spectral lines untouched: bins exceeding spike_factor x the band median keep their
    value and are excluded from their neighbours' mean, so the diurnal harmonics stay sharp."""
    f = 1.0 / per                                   # rfftfreq order: increasing frequency
    lo = np.searchsorted(f, f / (1 + bandwidth))
    hi = np.searchsorted(f, f * (1 + bandwidth), side="right")
    med = np.array([np.median(amp[a:b]) for a, b in zip(lo, hi)])
    spike = amp > spike_factor * med
    w = (~spike).astype(float)
    cs, cw = np.cumsum(amp * w), np.cumsum(w)
    tot = cs[hi - 1] - np.where(lo > 0, cs[np.maximum(lo - 1, 0)], 0.0)
    cnt = cw[hi - 1] - np.where(lo > 0, cw[np.maximum(lo - 1, 0)], 0.0)
    smooth = np.where(cnt > 0, tot / np.maximum(cnt, 1), amp)
    return np.where(spike, amp, smooth)


# --- period bands (bands.py) ---------------------------------------------------------------
BAND_RANGES = band_ranges(EDGES)
MASKS = band_masks(N, EDGES, BAND_NAMES)

records = []
for hue, df in (("wind", res_w), ("solar", res_s)):
    for name in names:
        for band, r in band_stats(df[name], MASKS).iterrows():
            records.append({"technology": hue, KIND: name, "band": band, **r})
bands = pd.DataFrame(records)
bands.to_csv(OUT_TABLE, index=False, float_format="%.3f")
VALUE = "shifted_pct_annual_demand"
print(bands.groupby(["technology", "band"])[VALUE].mean().unstack().loc[["wind", "solar"], BAND_NAMES].round(1))


def radar_series() -> list[dict]:
    out = []
    for hue in ("wind", "solar"):
        sub = bands[bands.technology == hue]
        members = [g.set_index("band").loc[BAND_NAMES, VALUE].values for _, g in sub.groupby(KIND, sort=False)]
        mean = sub.groupby("band")[VALUE].mean().loc[BAND_NAMES].values
        out.append(dict(label=f"{hue}-only residual, mean of {len(names)} {KIND}s", colour=COL[hue], mean=mean, members=members))
    return out


WHERE = ds.attrs.get("site", f"{len(names)} mutually uncorrelated PyPSA-Earth buses")
RADAR_TITLE = ("Residual demand variability by period band\n"
               "energy a lossless storage on that band alone would cycle per year, % of annual demand;\n"
               f"wind or solar capacity = {OVERBUILD:.1f} × annual demand, no other flexibility\n"
               f"{WHERE}, {ds.attrs.get('period_label', '')}")


def ramp(name: str):
    r = COL["ramps"][name]
    cmap = LinearSegmentedColormap.from_list(name, [r["light"], r["dark"]])
    return [cmap(k / max(len(names) - 1, 1)) for k in range(len(names))]


def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(True, axis="y", color="0.88", linewidth=0.5)
    ax.tick_params(labelsize=8)


# --- the six-row figure --------------------------------------------------------------------
plt.rcParams.update({"axes.labelsize": 9, "axes.titlesize": 10})
NROWS = 7 if MIX is not None else 6
fig = plt.figure(figsize=(13, 20 + 6.5 * (NROWS - 6)), layout="constrained")
gs = fig.add_gridspec(NROWS, 2, width_ratios=[2.3, 1], height_ratios=[1, 1, 1, 1, 1, 1.8, 2.5][:NROWS], hspace=0.06, wspace=0.04)

ROWS = [
    ("a", "Wind capacity factor", cf_w, "wind", "capacity factor", False),
    ("b", "Solar capacity factor", cf_s, "solar", "capacity factor", False),
    ("c", "Demand" + (f" ({ds.attrs['demand_note']})" if ds.attrs.get("demand_note") else ""), dem_n, "demand", "demand / mean demand", False),
    ("d", f"Residual demand, wind only (capacity = {OVERBUILD:.1f} × annual demand, no storage)",
     res_w, "wind", "residual / mean demand", True),
    ("e", f"Residual demand, solar only (capacity = {OVERBUILD:.1f} × annual demand, no storage)",
     res_s, "solar", "residual / mean demand", True),
]
snip_label = f"hourly, {SNIP.start:%d %b} – {SNIP.stop:%d %b}, local time"
for row, (tag, title, df, hue, ylabel, zero) in enumerate(ROWS):
    colours = ramp(hue)
    axl = fig.add_subplot(gs[row, 0])
    axr = fig.add_subplot(gs[row, 1], sharey=axl)
    daily = df.resample("1D").mean()
    snip = df.loc[SNIP]
    for k, name in enumerate(names):
        axl.plot(daily.index, daily[name], color=colours[k], lw=0.9, alpha=0.9)
        axr.plot(snip.index, snip[name], color=colours[k], lw=0.9, alpha=0.9)
    if zero:
        for ax in (axl, axr):
            ax.axhline(0, color="0.3", lw=0.8, zorder=0)
            ax.text(0.995, 0.97, "unmet ↑", transform=ax.transAxes, ha="right", va="top", fontsize=7, color="0.4")
            ax.text(0.995, 0.03, "surplus ↓", transform=ax.transAxes, ha="right", va="bottom", fontsize=7, color="0.4")
    period = f", {ds.attrs.get('period_label', '')}" if row == 0 else ""
    axl.set_title(f"{tag}  {title} — daily means{period}", loc="left")
    axr.set_title(snip_label, loc="left", fontsize=8.5, color="0.3")
    axl.set_ylabel(ylabel)
    axl.set_xlim(daily.index[0], daily.index[-1])
    axr.set_xlim(snip.index[0], snip.index[-1])
    axl.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b"))
    axr.xaxis.set_major_locator(matplotlib.dates.DayLocator(interval=2))
    axr.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d"))
    axr.tick_params(labelleft=False)
    style(axl)
    style(axr)

# site legend (lightness order) above the figure
handles = [Line2D([], [], color=c, lw=2.5, label=f"{k + 1}  {n}") for k, (c, n) in enumerate(zip(ramp("demand"), names))]
fig.legend(handles=handles, loc="outside upper center", ncol=5, frameon=False, fontsize=8,
           title=ds.attrs.get("legend_title", ""), title_fontsize=8.5)

# --- row f left: spectra with the period bands shaded
ax = fig.add_subplot(gs[5, 0])
for df, hue in ((res_w, "wind"), (res_s, "solar")):
    amps = []
    for name in names:
        per, amp = spectrum(df[name])
        amps.append(amp)
    mean = smooth_spectrum(per, np.mean(amps, axis=0), SM["bandwidth"], SM["spike_factor"])
    ax.plot(per, mean, color=COL[hue], lw=1.2, label=f"{hue}-only residual, mean of {len(names)} {KIND}s")
ax.set_xscale("log")
ax.set_yscale("log")
ticks = [3, 6, 12, 24, 24 * 3.5, 24 * 7, 24 * 30.4, 24 * 91, 8760 / 2, 8760]
labels = ["3 h", "6 h", "12 h", "1 d", "3.5 d", "1 wk", "1 mo", "3 mo", "6 mo", "1 yr"]
for t in ticks:
    ax.axvline(t, color="0.9", lw=0.6, zorder=0)
xlim = (2, 8760 * 1.15)
bounds = [xlim[0], *EDGES, xlim[1]]
band_tf = blended_transform_factory(ax.transData, ax.transAxes)
for k, lab in enumerate(BAND_NAMES):
    if k % 2 == 0:
        ax.axvspan(bounds[k], bounds[k + 1], color="0.955", zorder=-1, lw=0)
    ax.text(np.sqrt(bounds[k] * bounds[k + 1]), 0.985, lab, transform=band_tf, ha="center", va="top",
            fontsize=8.5, color="0.35")
ax.set_xticks(ticks, labels)
ax.set_xlim(*xlim)
ax.set_xlabel("period")
ax.set_ylabel("amplitude, fraction of mean demand")
ax.set_title(f"f  Amplitude spectra of the residual demand series, mean over the {len(names)} {KIND}s per technology,\n"
             f"smoothed over ±{SM['bandwidth']:.0%} in frequency (spectral lines kept); shading = the period bands of g", loc="left")
ax.legend(frameon=False, fontsize=8.5, loc="lower left")
ax.spines[["top", "right"]].set_visible(False)
ax.tick_params(labelsize=8)
ax.grid(True, axis="y", which="major", color="0.88", linewidth=0.5)

# --- row f right: the radar
axp = fig.add_subplot(gs[5, 1], projection="polar")
h = radar(axp, radar_series(), BAND_NAMES, BAND_RANGES, member_label=f"individual {KIND}s")
axp.set_title("g  Energy cycled per period band,\n% of annual demand", loc="left", pad=2)
axp.legend(handles=h, loc="upper center", bbox_to_anchor=(0.5, 0.23), frameon=False, fontsize=8)

# --- row h (years variant): the pure triangles next to the country mixes of plot_mix_radar.py
if MIX is not None:
    mix = pd.read_csv(MIX)
    series = []
    for case, grp in mix.groupby("case", sort=False):
        key = grp.colour.iloc[0]
        colour = COL["mixes"][key.split(".")[1]] if key.startswith("mixes.") else COL[key]
        series.append(dict(label=grp.label.iloc[0], colour=colour, ls=grp.ls.iloc[0],
                           mean=grp.set_index("band").loc[BAND_NAMES, VALUE].values))
    axm = fig.add_subplot(gs[6, :], projection="polar")      # fixed aspect: centred in the full-width row
    h = radar(axm, series, BAND_NAMES, BAND_RANGES)
    axm.set_title("h  Pure wind, pure solar and two countries supplied by a wind/solar superposition (dashed)\n"
                  "energy cycled per period band, % of annual demand; countries from PyPSA-Earth country-aggregated "
                  f"profiles, 2013, total generation {OVERBUILD:.1f} × annual demand", loc="center", pad=4)
    axm.legend(handles=h, loc="upper center", bbox_to_anchor=(0.5, 0.21), frameon=False, fontsize=9)

for out in OUT_STRUCTURE:
    fig.savefig(out, dpi=CFG["plotting"]["dpi"])
plt.close(fig)

# --- the radar alone -----------------------------------------------------------------------
fig2 = plt.figure(figsize=(6.4, 5.6), layout="constrained")
axp = fig2.add_subplot(projection="polar")
h = radar(axp, radar_series(), BAND_NAMES, BAND_RANGES, member_label=f"individual {KIND}s")
axp.set_title(RADAR_TITLE, fontsize=9, loc="left", color="0.15", pad=6)
axp.legend(handles=h, loc="upper center", bbox_to_anchor=(0.5, 0.23), frameon=False, fontsize=8)
for out in OUT_BANDS:
    fig2.savefig(out, dpi=CFG["plotting"]["dpi"])
plt.close(fig2)
print("wrote", ", ".join(str(o) for o in (*OUT_STRUCTURE, *OUT_BANDS, OUT_TABLE)))
