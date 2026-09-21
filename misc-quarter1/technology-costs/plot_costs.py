"""Plot the 2025 cost baseline with observed project costs overlaid.

One script, several figures selected by `figure` (snakemake.params.figure or the
first CLI argument when run standalone):

  capex_generation  specific investment, USD/kW, generation technologies
  capex_generation_mature / _advanced   the same split by group; the mature
                    figure shows bars only (no observed points)
  capex_storage     specific investment, USD/kWh (energy) and USD/kW (power)
  capex_storage_mature / _advanced      split by group, mature without points
  opex              fixed O&M USD/kW/a and variable O&M USD/MWh
  lcoe              levelised cost band over the capacity-factor range, USD/MWh
  dac               USD/tCO2 from capex + FOM

Two layouts:

* report (figures/): bars are the compiled assumption (hatched where gap-filled
  from other sources), markers are individual observed points from
  build/observed_normalised.csv, numbers in brackets refer to build/sources.md,
  a footnote row carries the method.
* slide (figures/slides/, `slide=True` / `--slide`): fixed 15.2 x 5.5 cm at 1:1
  for the beamer deck in beamer/2026-09-08, row labels carry the reference numbers of
  the bar's sources and (after "obs.") of the observed data, observed points
  are summarised as box plots (median, quartiles, range) with the legend on the
  right, numbers refer to references.yaml there (plotting.slide_references) (curated; sources that
  match no entry there are not cited on the slide). No titles or footnotes: the
  frame carries them.
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.ticker import FuncFormatter, LogLocator, MaxNLocator, NullFormatter  # noqa: E402

from common import footnote, grid  # noqa: E402
from common import save as _save  # noqa: E402

if "snakemake" in globals():
    CFG = snakemake.config
    TABLE = Path(snakemake.input.table)
    OBS = Path(snakemake.input.observed)
    COMPILED = Path(snakemake.input.compiled)
    FIGURE = snakemake.params.figure
    SLIDE = bool(snakemake.params.get("slide", False))
    OUTPUTS = [Path(p) for p in snakemake.output]
    _HERE = Path(snakemake.input.config).resolve().parent
else:
    _HERE = Path(__file__).resolve().parent
    CFG = yaml.safe_load((_HERE / "config.yaml").read_text())
    TABLE = _HERE / "build" / "costs_2025_table.csv"
    OBS = _HERE / "build" / "observed_normalised.csv"
    COMPILED = _HERE / "build" / "costs_2025_compiled.csv"
    args = [a for a in sys.argv[1:] if a != "--slide"]
    SLIDE = "--slide" in sys.argv
    FIGURE = args[0] if args else "capex_generation"
    OUTPUTS = [_HERE / "figures" / ("slides" if SLIDE else "") / f"{FIGURE}.{fmt}"
               for fmt in CFG["plotting"]["formats"]]
OUTPUTS[0].parent.mkdir(parents=True, exist_ok=True)

BASE = f"{CFG['base_currency']}{CFG['base_currency_year']}"
TECH = {t["key"]: t for t in CFG["technologies"]}
STYLE = CFG["point_type_style"]
POINT_COLOUR = "#222222"
DRAWN = set()          # legend entries actually used by draw_bars
# font/marker sizes: report layout vs slide layout (slide figures are placed 1:1 on a
# 16 x 9 cm beamer page, so 6-7 pt there reads like \scriptsize)
SZ = ({"tick": 6.5, "ann": 6.2, "leg": 6.2, "marker": 4.5, "na": 6.5, "label": 7.5, "xtick": 6.8}
      if SLIDE else
      {"tick": 8.5, "ann": 7.5, "leg": 7.5, "marker": 6.5, "na": 8, "label": 10, "xtick": 10})
plt.rcParams.update({"axes.labelsize": SZ["label"], "xtick.labelsize": SZ["xtick"]})

table = pd.read_csv(TABLE)
obs = pd.read_csv(OBS)
compiled = pd.read_csv(COMPILED)

# --- curated references for the slides ----------------------------------------------------

REFS = []                               # dicts with "n", "short", "match"; n = slide reference number
TD_REF = None                           # number of the technology-data compilation entry
if SLIDE:
    _ref_path = (_HERE / CFG["plotting"]["slide_references"]).resolve()
    for n, r in enumerate(yaml.safe_load(_ref_path.read_text()), 1):
        REFS.append({"n": n, "short": r["short"], "match": r.get("match") or []})
        if "__technology-data__" in REFS[-1]["match"]:
            TD_REF = n


def ref_numbers(sources, origins=None):
    """Curated reference numbers matching any of the given source strings."""
    out = set()
    for i, s in enumerate(sources):
        s = str(s)
        origin = str(origins[i]) if origins is not None else ""
        for r in REFS:
            for m in r["match"]:
                if (m == "__technology-data__" and origin.startswith("technology-data")) or \
                        (m != "__technology-data__" and m in s):
                    out.add(r["n"])
    return tuple(sorted(out))


def ref_short(n):
    return next(r["short"] for r in REFS if r["n"] == n)


def bar_refs(tech):
    """Reference numbers behind a technology's investment cost bar."""
    rows = compiled[(compiled["technology"] == tech)
                    & compiled["parameter"].str.startswith("investment")
                    & compiled["value"].notna()]
    return ref_numbers(rows["source"].tolist(), rows["origin"].tolist())


def obs_refs(tech, metric):
    rows = obs[(obs["technology"] == tech) & (obs["metric"] == metric)]
    return ref_numbers(rows["source"].tolist())


# --- helpers --------------------------------------------------------------------

def fmt_refs(nums):
    return f" [{','.join(str(n) for n in nums)}]" if nums else ""


def tick_label(row, extra="", refs=(), bar=()):
    """Slide: name [bar refs] · obs. [observed refs]; report: name [source ids]."""
    if SLIDE:
        obs_part = f"\nobserved{fmt_refs(refs)}" if refs else ""
        return f"{row['label']}{fmt_refs(bar)}{extra}{obs_part}"
    ids = f" [{row['source_ids'].replace(';', ',')}]" if isinstance(row["source_ids"], str) else ""
    flag = "" if row["bar"] else "\n(site-specific, no single value)"
    return f"{row['label']}{ids}{extra}{flag}"


def draw_bars(ax, rows, col, xlabel, log, obs_metric, extra_label=None, range_col=None,
              subs=(1.0, 2.0, 5.0), points=True):
    """Horizontal bars for `col` (or a range from range_col to col) plus observed costs.

    Report layout: individual observed points, jittered. Slide layout: a box plot
    of all observed values below the bar (single markers when fewer than 3)."""
    if SLIDE:
        rows = rows[~rows["technology"].isin(CFG["plotting"].get("slide_exclude", []))]
    n = len(rows)
    groups = rows["group"].tolist()
    GAP = 1.4 if SLIDE else 0.9                 # extra space between groups (group label sits in it)
    pos, y = [], 0.0
    for k in range(n):
        if k and groups[k] != groups[k - 1]:
            y += GAP
        pos.append(y)
        y += 1.0
    ys = (y - 1.0) - np.array(pos)              # first row at the top
    split = SLIDE and points                    # bar above, box plot below the row centre
    bar_dy, bar_h = (0.2, 0.36) if split else (0.0, 0.62)
    finite, labels = [], []
    for y, (_, r) in zip(ys, rows.iterrows()):
        colour = TECH[r["technology"]]["colour"]
        hatch = None if SLIDE else ("///" if r["capex_origin"] == "gap_fill" else None)
        v = r[col]
        if r["bar"] and pd.notna(v):
            if SLIDE:
                DRAWN.add(("bar", bar_refs(r["technology"])))
            elif r["capex_origin"] == "gap_fill":
                DRAWN.add("gap_fill")
        if not r["bar"]:
            pass                                 # site-specific: observed costs only
        elif range_col is not None and pd.notna(v) and pd.notna(r[range_col]):
            left, width = v, r[range_col] - v
            ax.barh(y + bar_dy, width, left=left, height=bar_h, color=colour, alpha=0.55,
                    edgecolor=colour, hatch=hatch)
            ax.plot([v], [y + bar_dy], marker="|", markersize=14, color=colour, mew=2.5)
            finite += [v, r[range_col]]
        elif pd.notna(v):
            ax.barh(y + bar_dy, v, height=bar_h, color=colour, alpha=0.9,
                    edgecolor="white" if hatch is None else colour, hatch=hatch)
            finite.append(v)
        else:
            ax.text(0, y + bar_dy, " n/a", va="center", ha="left", fontsize=SZ["na"],
                    color="0.45", transform=ax.get_yaxis_transform())

        pts = obs[(obs["technology"] == r["technology"]) & (obs["metric"] == obs_metric)]
        if not points:
            pts = pts.iloc[:0]
        refs = obs_refs(r["technology"], obs_metric) if (SLIDE and len(pts)) else ()
        # bar_refs only counts investment rows with a value, so an n/a panel still cites
        # the technology's other component (shared y labels come from the last panel)
        brefs = bar_refs(r["technology"]) if (SLIDE and r["bar"]) else ()
        labels.append(tick_label(r, extra_label(r) if extra_label else "", refs, brefs))
        if SLIDE:
            vals = pts["value_base"].dropna().to_numpy()
            if len(vals) >= 3:
                DRAWN.add("box")
                ax.boxplot(vals, positions=[y - 0.22], vert=False, widths=0.36, whis=(0, 100),
                           patch_artist=True, showfliers=False, zorder=5,
                           boxprops=dict(facecolor="white", edgecolor=POINT_COLOUR, lw=0.9),
                           medianprops=dict(color=POINT_COLOUR, lw=1.4),
                           whiskerprops=dict(color=POINT_COLOUR, lw=0.9),
                           capprops=dict(color=POINT_COLOUR, lw=0.9))
                ax.text(vals.max(), y - 0.22, f" n={len(vals)}", va="center", ha="left",
                        fontsize=5.4, color="0.35", zorder=6, in_layout=False)
            elif len(vals):
                DRAWN.add("few")
                ax.plot(vals, [y - 0.22] * len(vals), marker="o", linestyle="none",
                        markersize=SZ["marker"], color=POINT_COLOUR, markerfacecolor="white",
                        markeredgewidth=1.0, zorder=5)
            finite += list(vals)
            continue

        singles = pts[~pts["point_type"].str.startswith("benchmark_range")]
        for i, (_, p) in enumerate(singles.iterrows()):
            st = STYLE[p["point_type"]]
            DRAWN.add(p["point_type"])
            jitter = 0.16 * ((i % 3) - 1)
            ax.plot(p["value_base"], y + jitter, marker=st["marker"], linestyle="none",
                    markersize=SZ["marker"], color=POINT_COLOUR,
                    markerfacecolor=POINT_COLOUR if st["filled"] else "white",
                    markeredgewidth=1.1, zorder=5)
            finite.append(p["value_base"])
        ranges = pts[pts["point_type"].str.startswith("benchmark_range")]
        for j, (proj, pr) in enumerate(ranges.groupby("project")):
            DRAWN.add("benchmark_range")
            lo = pr.loc[pr["point_type"] == "benchmark_range_low", "value_base"]
            hi = pr.loc[pr["point_type"] == "benchmark_range_high", "value_base"]
            yy = y - 0.24 - 0.12 * j
            if len(lo) and len(hi):
                ax.plot([lo.iloc[0], hi.iloc[0]], [yy, yy], color=POINT_COLOUR, lw=1.2,
                        marker="|", markersize=7, zorder=5)
                finite += [lo.iloc[0], hi.iloc[0]]
            else:
                x = pd.concat([lo, hi]).iloc[0]
                ax.plot(x, yy, marker="|", color=POINT_COLOUR, markersize=7, zorder=5)
                finite.append(x)

    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=SZ["tick"])
    ax.set_ylim(-0.8, ys[0] + (1.3 if SLIDE else 0.8))
    if log:
        ax.set_xscale("log")
        ax.xaxis.set_major_locator(LogLocator(base=10, subs=subs, numticks=12))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax.xaxis.set_minor_formatter(NullFormatter())
        if finite:
            lo, hi = min(finite), max(finite)
            ax.set_xlim(lo / 1.6, hi * (1.9 if SLIDE else 1.6))
    else:
        ax.set_xlim(0, max(finite) * 1.12 if finite else 1)
        if SLIDE:
            ax.xaxis.set_major_locator(MaxNLocator(4))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_xlabel(xlabel)
    grid(ax, log)

    # separator and label between mature and advanced
    for k in range(1, n):
        if groups[k] != groups[k - 1]:
            ax.axhline(ys[k] + 0.5 + GAP / 2, color="0.5", lw=0.8, ls="--")
    names = {"mature": "mature · exogenous costs", "advanced": "advanced · endogenous learning"}
    for g in dict.fromkeys(groups) if len(set(groups)) > 1 else []:   # redundant for one group
        idx = [i for i, gg in enumerate(groups) if gg == g]
        # in_layout=False: the label may be wider than a narrow panel and must not make
        # constrained layout reserve space for its overhang
        if idx[0] == 0:                          # first group: label above its first row
            ax.text(1.0, ys[0] + 0.42, names[g], transform=ax.get_yaxis_transform(),
                    ha="right", va="bottom", fontsize=SZ["ann"], color="0.4", style="italic",
                    in_layout=False)
        else:                                    # later groups: label sits on the separator
            ax.text(1.0, ys[idx[0]] + 0.5 + GAP / 2, names[g], transform=ax.get_yaxis_transform(),
                    ha="right", va="center", fontsize=SZ["ann"], color="0.4", style="italic",
                    bbox=dict(facecolor="white", edgecolor="none", pad=1.5), zorder=3,
                    in_layout=False)


def legend(fig, ax, include_range=True, above=False):
    """Report: bar origins and point types drawn. Slide: box-plot symbols only, to the right
    of the axes, or in one row above them (right-aligned) when `above` is set."""
    if SLIDE:
        handles = []                             # bar sources are cited in the row labels
        if "box" in DRAWN:
            handles.append(Line2D([0, 1], [0, 0], color=POINT_COLOUR, lw=0.9, marker="s",
                                  markerfacecolor="white", markersize=6, markeredgewidth=0.9,
                                  label="Observed: median, quartiles, range"))
        if "few" in DRAWN:
            handles.append(Line2D([], [], marker="o", linestyle="none", color=POINT_COLOUR,
                                  markerfacecolor="white", markeredgewidth=1.0,
                                  markersize=SZ["marker"], label="Observed (fewer than 3)"))
        if handles:
            loc, ncol = ("outside upper right", len(handles)) if above else ("outside right upper", 1)
            fig.legend(handles=handles, loc=loc, ncol=ncol, fontsize=SZ["leg"], frameon=False,
                       handletextpad=0.6, handlelength=1.8, labelspacing=0.9, columnspacing=1.6)
        return
    handles = [Patch(facecolor="0.6", edgecolor="white",
                     label=f"technology-data {CFG['technology_data']['tag']} (2025)")]
    if "gap_fill" in DRAWN:
        handles.append(Patch(facecolor="0.6", edgecolor="0.4", hatch="///",
                             label="gap-filled from other sources"))
    for key, st in STYLE.items():
        if key not in DRAWN:
            continue
        if key == "benchmark_range":
            if include_range:
                handles.append(Line2D([0, 1], [0, 0], color=POINT_COLOUR, marker="|",
                                      markersize=7, lw=1.2, label=st["label"]))
            continue
        handles.append(Line2D([], [], marker=st["marker"], linestyle="none", color=POINT_COLOUR,
                              markerfacecolor=POINT_COLOUR if st["filled"] else "white",
                              markeredgewidth=1.1, markersize=SZ["marker"], label=st["label"]))
    fig.legend(handles=handles, loc="outside lower center", ncol=4, fontsize=SZ["leg"],
               frameon=False, columnspacing=1.2, handletextpad=0.5)


SLIDE_SIZE = (15.2 / 2.54, 5.5 / 2.54)         # inches; 16:9 beamer page is 16 x 9 cm, title ~1.8 cm


def make_fig(ncols, height, width=9.0, width_ratios=None, sharey=False):
    """Figure with `ncols` bar axes on top and a text-only footnote row below.

    In slide mode the size is fixed and the footnote row is dropped (axf is None)."""
    if SLIDE:
        fig = plt.figure(figsize=SLIDE_SIZE, layout="constrained")
        axes = fig.subplots(1, ncols, sharey=sharey, width_ratios=width_ratios, squeeze=False)[0]
        return fig, list(axes), None
    fig = plt.figure(figsize=(width, height + 0.7), layout="constrained")
    gs = fig.add_gridspec(2, ncols, height_ratios=[height, 0.7], width_ratios=width_ratios)
    axes = []
    for i in range(ncols):
        axes.append(fig.add_subplot(gs[0, i], sharey=axes[0] if (sharey and axes) else None))
    axf = fig.add_subplot(gs[1, :])
    axf.axis("off")
    axf.wrap_chars = int((width - 3.3) * 16)   # ~16 chars/inch at 7 pt, minus label column
    return fig, axes, axf


def save(fig):
    _save(fig, OUTPUTS, CFG["plotting"]["dpi"])


NOTE = (f"All values in {BASE}; every row converted at the ECB annual rate of its stated price year "
        f"and inflated with US CPI-U. Bracketed numbers refer to build/sources.md.")

# --- figures --------------------------------------------------------------------------------

if FIGURE == "capex_generation":
    rows = table[table["kind"] == "generation"]
    fig, (ax,), axf = make_fig(1, 0.42 * len(rows) + 1.5)
    draw_bars(ax, rows, "capex_kw", f"Specific investment cost [{BASE}/kW]", log=True,
              obs_metric="capex_per_kw")
    if not SLIDE:
        ax.set_title("Generation technologies: 2025 capex baseline vs observed project costs",
                     fontsize=11, loc="left")
    legend(fig, ax)
    footnote(axf, NOTE + " Observed nuclear totals include financing where the source does.")
    save(fig)

elif FIGURE in ("capex_generation_mature", "capex_generation_advanced"):
    group = FIGURE.rsplit("_", 1)[1]
    rows = table[(table["kind"] == "generation") & (table["group"] == group)]
    fig, (ax,), axf = make_fig(1, 0.42 * len(rows) + 1.5)
    draw_bars(ax, rows, "capex_kw", f"Specific investment cost [{BASE}/kW]", log=True,
              obs_metric="capex_per_kw", points=(group == "advanced"))
    if not SLIDE:
        ax.set_title(f"{group.capitalize()} generation technologies: 2025 capex baseline"
                     + (" vs observed project costs" if group == "advanced" else ""),
                     fontsize=11, loc="left")
    legend(fig, ax)
    footnote(axf, NOTE + (" Observed nuclear totals include financing where the source does."
                          if group == "advanced" else ""))
    save(fig)

elif FIGURE in ("capex_storage", "capex_storage_mature", "capex_storage_advanced"):
    rows = table[table["kind"] == "storage"]
    group = FIGURE.rsplit("_", 1)[1] if FIGURE != "capex_storage" else None
    if group:
        rows = rows[rows["group"] == group]
    points = group != "mature"
    fig, axes, axf = make_fig(2, 0.5 * len(rows) + 1.5, width=11, sharey=True)
    if SLIDE:
        kw = dict(subs=(1.0,))                   # narrow panels: decades only
        xl_e, xl_p = f"Energy\n[{BASE}/kWh]", f"Power\n[{BASE}/kW]"
    else:
        kw = {}
        xl_e, xl_p = f"Energy capacity cost [{BASE}/kWh]", f"Power capacity cost [{BASE}/kW]"
    log = points                                 # bars-only figure: linear axis reads better
    draw_bars(axes[0], rows, "capex_kwh", xl_e, log=log, obs_metric="capex_per_kwh",
              points=points, **kw)
    draw_bars(axes[1], rows, "capex_kw", xl_p, log=log, obs_metric="capex_per_kw",
              points=points, **kw)
    axes[1].tick_params(labelleft=False)
    if not SLIDE:
        fig.suptitle(f"{(group or 'storage').capitalize()} storage technologies: 2025 capex baseline"
                     + (" vs observed project costs" if points else ""),
                     fontsize=11, x=0.01, ha="left")
    legend(fig, axes[1], above=SLIDE)             # slide: panels are narrow, legend goes on top
    footnote(axf, NOTE + " Observed storage points are total project cost divided by energy "
             "(left) or power (right) capacity; the duration in the label is typical for the "
             "technology; rows are ordered by it within each group. The H2 store is a "
             "pressurised tank priced per kWh of electricity out (tank cost / SOFC efficiency); "
             "salt caverns would be ~20x cheaper per kWh where geology allows.")
    save(fig)

elif FIGURE == "opex":
    rows = table[table["kind"].isin(["generation", "storage"])]
    gen = table[table["kind"] == "generation"]
    fig, axes, axf = make_fig(2, 0.42 * len(rows) + 1.5, width=11, width_ratios=[1.2, 1])
    draw_bars(axes[0], rows, "fom_kw_a", f"Fixed O&M [{BASE}/kW/a]", log=True, obs_metric="fom")
    draw_bars(axes[1], gen, "vom_mwh", f"Variable O&M excl. fuel [{BASE}/MWh]", log=False,
              obs_metric="vom")
    if not SLIDE:
        fig.suptitle("Operating costs: 2025 baseline", fontsize=11, x=0.01, ha="left")
    legend(fig, axes[0], include_range=False)
    footnote(axf, NOTE + " Fixed O&M given as %/year in technology-data is converted using "
             "the same row's investment cost; storage FOM refers to the power component.")
    save(fig)

elif FIGURE == "lcoe":
    rows = table[(table["kind"] == "generation")]
    fig, (ax,), axf = make_fig(1, 0.42 * len(rows) + 1.5, width=9.5)
    draw_bars(ax, rows, "lcoe_at_cf_high", f"Levelised cost of electricity [{BASE}/MWh]",
              log=False, obs_metric="lcoe", range_col="lcoe_at_cf_low",
              extra_label=lambda r: (f"  · CF {r['cf_low']:.0%}–{r['cf_high']:.0%}"
                                     if pd.notna(r["cf_low"]) else ""))
    if not SLIDE:
        ax.set_title(f"LCOE at {CFG['discount_rate']:.0%} real discount rate: baseline band "
                     "(high → low capacity factor) vs observed", fontsize=11, loc="left")
    legend(fig, ax)
    footnote(axf, NOTE + f" Bars span the capacity-factor band in config.yaml; fuel at "
             f"technology-data 2025 prices, CO2 price {CFG['co2_price_eur_t']:.0f} EUR/t. "
             "Observed LCOE benchmarks assume their own financing and fuel assumptions.")
    save(fig)

elif FIGURE == "dac":
    rows = table[table["kind"] == "dac"]
    fig, (ax,), axf = make_fig(1, 2.0, width=8.5)
    draw_bars(ax, rows, "cost_per_tco2", f"Cost of CO2 removal [{BASE}/tCO2]", log=False,
              obs_metric="cost_per_tco2")
    if not SLIDE:
        ax.set_title("Direct air capture: 2025 capex+FOM baseline vs observed prices and targets",
                     fontsize=11, loc="left")
    legend(fig, ax)
    footnote(axf, NOTE + f" Bar: technology-data DAC capex + FOM annuitised at "
             f"{CFG['discount_rate']:.0%} over {int(rows['lifetime'].iloc[0])} a at "
             f"{CFG['dac']['capacity_factor']:.0%} availability, excluding heat/electricity and "
             "storage; the SOW uses 300-600 EUR/t (150 in the CDR breakthrough) as the cost cut-off.")
    save(fig)

else:
    raise SystemExit(f"unknown figure {FIGURE!r}")
