# SPDX-License-Identifier: CC0-1.0
"""
Before/after the catalyst patches on one page: PyPSA-Earth v0.9.0 as it comes (baseline/run_overnight.sh, worktree
models/pypsa-earth-baseline) against the patched and calibrated fork (models/pypsa-earth), both read from the per-country
tables plot_world.py writes (validation_world.csv: one `ember`, `now` and `zero` row per country, generation in TWh).

  left:  all modelled countries together: generation mix of Ember 2024, `now` ("2024 run"), 0.9.0 / with patches
  right: `now` against Ember: demand-weighted mean absolute error of each fuel group's share of generation, per country
One row, sized for a slide; carrier colours are the PyPSA-Eur defaults (config/plotting.default.yaml, tech_colors).

Only countries with a `now` row in both tables enter (a) and (b). The model's share is of its own generation (load shedding
excluded); the bars on the left draw shedding as its own segment. Also writes <out>.pdf and <out>.csv (the metrics).

Standalone (fork env, from anywhere):
    python config-pypsa-earth/scripts/plot_before_after.py --before models/pypsa-earth-baseline/results/catalyst/validation_world.csv \
        --after models/pypsa-earth/results/catalyst/validation_world.csv \
        --out misc-quarter1/pypsa-earth-out-of-the-box-validation/figures/before-after/before_after.png
"""
import argparse
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import iconstyle as ic  # noqa: E402

FUELS = ["coal", "gas", "oil", "nuclear", "hydro", "wind", "solar", "biomass", "other"]
# drawn segments in the PyPSA-Eur default tech_colors (coal, gas, oil, nuclear, hydro, onwind, solar, biomass, load)
SEGMENTS = [("coal", ["coal"], "#545454"), ("gas", ["gas"], "#e05b09"), ("oil & other", ["oil", "other"], "#c9c9c9"),
            ("nuclear", ["nuclear"], "#ff8c00"), ("hydro", ["hydro"], "#298c81"), ("wind", ["wind"], "#235ebc"),
            ("solar", ["solar"], "#f9d002"), ("biomass", ["biomass"], "#baa741"), ("load shed", ["shed"], "#dd2e23")]
DARK = {"#545454", "#e05b09", "#298c81", "#235ebc", "#dd2e23"}   # segments that take white numbers
ERRORS = [("fossil", ["coal", "gas", "oil"]), ("coal", ["coal"]), ("gas", ["gas"]), ("nuclear", ["nuclear"]),
          ("hydro", ["hydro"]), ("wind + solar", ["wind", "solar"]), ("biomass", ["biomass"])]
BEFORE_C, AFTER_C = ic.STEEL_L, ic.BLUE
SHOW = {"before": "0.9.0", "after": "with patches"}   # how the two sides are named on the page


def read(path):
    d = pd.read_csv(path)
    d[FUELS + ["shed"]] = d[FUELS + ["shed"]].fillna(0.0)
    return d


def share(rows, groups):
    """Share of `groups` in the generation (shedding excluded) of the summed rows."""
    tot = rows[FUELS].to_numpy().sum()
    return rows[groups].to_numpy().sum() / tot if tot > 0 else np.nan


def mix(rows):
    """Segments of one 100 % bar (shedding included in the total)."""
    tot = rows[FUELS + ["shed"]].to_numpy().sum()
    return [rows[g].to_numpy().sum() / tot for _, g, _ in SEGMENTS]


def country_errors(model, ember):
    """Per country: model minus Ember share of each ERRORS group, and the Ember demand as weight."""
    m = model.set_index("country")
    e = ember.set_index("country")
    out = pd.DataFrame(index=m.index)
    for name, g in ERRORS:
        out[name] = [share(m.loc[[c]], g) - share(e.loc[[c]], g) for c in m.index]
    out["demand"] = e.demand.reindex(m.index)
    return out.dropna()


def wmae(err, col):
    return float(np.average(err[col].abs(), weights=err.demand))


def hbars(ax, labels, parts_rows, ytick_kw=None):
    y = np.arange(len(labels))
    parts = np.array(parts_rows).T
    ic.stacked_barh(ax, y, parts, [c for _, _, c in SEGMENTS], totals=False, height=0.68)
    for yi, row in zip(y, parts_rows):
        x = 0
        for (name, _, c), v in zip(SEGMENTS, row):
            if v > 0.06:
                ax.text(x + v / 2, yi, f"{100 * v:.0f}", ha="center", va="center", fontsize=6.5,
                        color="white" if c in DARK else ic.INK, zorder=3)
            x += v
    ax.set_yticks(y, labels, **(ytick_kw or {}))
    ax.set_ylim(len(labels) - 0.4, -0.6)
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.grid(axis="y", visible=False)
    ic.ground(ax, axis="y")


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").strip().split("\n")[0])
    p.add_argument("--before", required=True, help="validation_world.csv of the v0.9.0 baseline run")
    p.add_argument("--after", required=True, help="validation_world.csv of the patched fork")
    p.add_argument("--out", required=True, help="png; a pdf and a csv with the same stem are written next to it")
    p.add_argument("--before-label", default="v0.9.0 as it comes")
    p.add_argument("--after-label", default="catalyst fork")
    a = p.parse_args()

    bef, aft = read(a.before), read(a.after)
    ember = aft[aft.scen == "ember"]
    both = sorted(set(bef[bef.scen == "now"].dropna(subset=["load"]).country)
                  & set(aft[aft.scen == "now"].dropna(subset=["load"]).country))
    sel = lambda d, scen: d[(d.scen == scen) & d.country.isin(both)]
    eb = ember[ember.country.isin(both)]
    err = {"before": country_errors(sel(bef, "now"), eb), "after": country_errors(sel(aft, "now"), eb)}

    metrics = []
    for side, e in err.items():
        row = {"side": side, "countries": len(e)}
        row.update({f"mae_{k.replace(' + ', '_')}_pp": 100 * wmae(e, k) for k, _ in ERRORS})
        row["fossil_within_10pp"] = int((e.fossil.abs() <= 0.10).sum())
        row["fossil_within_20pp"] = int((e.fossil.abs() <= 0.20).sum())
        d = bef if side == "before" else aft
        for scen in ("now", "zero"):
            s = sel(d, scen)
            row[f"{scen}_co2_gt"] = s.co2.sum() / 1e3
            row[f"{scen}_shed_twh"] = s.shed.sum()
            row[f"{scen}_load_twh"] = s.load.sum()
        metrics.append(row)
    metrics = pd.DataFrame(metrics).set_index("side")
    metrics.loc["ember", ["countries", "now_co2_gt", "now_load_twh"]] = [len(eb), eb.co2.sum() / 1e3, eb.demand.sum()]
    # countries a run gives no load at all (v0.9.0: no GEGIS series) have no share: out of the MAE, counted as misses

    ic.use()
    fig = plt.figure(figsize=(11.0, 4.1))
    gs = fig.add_gridspec(1, 2, left=0.15, right=0.975, top=0.84, bottom=0.24, wspace=0.27)
    fig.text(0.012, 0.965, "Electricity mix for 2024 validation of 0.9.0 before and after patches",
             fontsize=11.5, fontweight=ic.EMPH, color=ic.INK, va="top")

    # (a) world mix
    ax = fig.add_subplot(gs[0, 0])
    rows = [("Ember 2024", eb)] + [(f"{run}, {SHOW[side]}", sel(d, scen)) for run, scen in (("2024 run", "now"),)
                                   for side, d in (("before", bef), ("after", aft))]
    hbars(ax, [r[0] for r in rows], [mix(r[1]) for r in rows])
    ax.set_title(f"(a) {len(both)} countries aggregated (99.5% of power demand), generation shares")
    patches = [matplotlib.patches.Patch(facecolor=c, edgecolor=ic.INK, linewidth=ic.MARK, label=n) for n, _, c in SEGMENTS]
    ax.legend(handles=[patches[i] for i in (0, 5, 1, 6, 2, 7, 3, 8, 4)],   # matplotlib fills columns: reads by row
              loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=5, frameon=False, fontsize=7.4,
              handlelength=1.1, columnspacing=1.2)

    # (b) error of now vs Ember
    ax = fig.add_subplot(gs[0, 1])
    names = [k for k, _ in ERRORS]
    y = np.arange(len(names))
    h = 0.36
    for off, side, c in ((-h / 2, "before", BEFORE_C), (h / 2, "after", AFTER_C)):
        v = [100 * wmae(err[side], k) for k in names]
        ax.barh(y + off, v, height=h, color=c, edgecolor=ic.INK, linewidth=ic.MARK, zorder=2)
        for yi, vi in zip(y + off, v):
            ax.annotate(f"{vi:.1f}", (vi, yi), xytext=(4, 0), textcoords="offset points", va="center", fontsize=6.6,
                        color=ic.INK)
    ax.set_xlim(0, 1.1 * max(100 * wmae(err[side], k) for side in err for k in names))
    ax.set_yticks(y, names)
    ax.set_ylim(len(names) - 0.4, -0.6)
    ax.grid(axis="y", visible=False)
    ax.set_title("(b) per-carrier deviation from electricity mix (%)")
    ic.legend_squares(ax, [(BEFORE_C, SHOW["before"]), (AFTER_C, SHOW["after"])], on_title_line=False, loc="lower right",
                      anchor=(1.0, 0.0), frameon=False)
    ic.ground(ax, axis="y")

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=200)
    fig.savefig(out.with_suffix(".pdf"))
    metrics.round(3).to_csv(out.with_suffix(".csv"))
    print(metrics.round(2).T.to_string())
    print(f"-> {out}, {out.with_suffix('.pdf')}, {out.with_suffix('.csv')}")


if __name__ == "__main__":
    main()
