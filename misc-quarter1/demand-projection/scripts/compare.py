"""Projection table, comparison with published outlooks, go / no-go verdict, figures.

    build/projection.csv    iso3, iso2, group, year, baseline_twh, central_twh, high_twh
    build/comparison.csv    growth multiples base year -> 2035 / 2050: ours against each outlook
    build/verdict.md        the criteria of config.yaml, evaluated
    figures/growth_vs_weo.png, projection_regions.png, backtest.png

Outlooks use other demand definitions than Ember (the IEA excludes losses and own use), so everything is compared
as a growth multiple from the outlook's own 2024 value; in the regional figure the outlook dots are that multiple
times Ember 2024.
"""

import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import ARCHETYPES, BUILD, CONFIG, DATA, FIGURES, ISO2, ISO3, ember_demand, modelled_countries, path

BASE = CONFIG["base_year"]
CRIT = CONFIG["criteria"]
BLUE, BLUE_LIGHT, ORANGE, INK, MUTED, GRID, SURFACE = "#2a78d6", "#9ec5f4", "#eb6834", "#1a1a19", "#6b6a63", "#e4e3dc", "#fcfcfb"
# outlook rows of manual_points.csv whose base differs from the region's `now` point: 2050 value to use instead
# (AEO: total consumption incl. direct use, the definition of the EIA 2024 point; the row itself is retail sales)
MANUAL_VALUE = {"EIA AEO25 Ref 2050": 6281.289}
LEVEL = {"EPE PNE2050 expansion": "expansion", "EPE PNE2050 stagnation": "stagnation", "EIA AEO25 Ref 2050": "reference",
         "CETO22 CNS1 2050": "net zero", "ICCSD 1.5C 2050": "net zero", "TYNDP24 DE 2050": "net zero",
         "TYNDP24 GA 2050": "net zero"}


def projection():
    base = pd.read_csv(os.path.join(BUILD, "baseline.csv"))
    el = pd.read_csv(os.path.join(BUILD, "electrification.csv")).groupby(["iso3", "year", "level"]).twh.sum().unstack()
    p = base.set_index(["iso3", "year"])[["baseline_twh", "driver_source"]].join(el)
    p["central_twh"] = p.baseline_twh + p.central
    p["high_twh"] = p.baseline_twh + p.high
    p = p.reset_index()
    p["iso2"] = p.iso3.map(ISO2)
    p["group"] = p.iso3.map(modelled_countries())
    return p[["iso3", "iso2", "group", "year", "baseline_twh", "central_twh", "high_twh", "driver_source"]]


def members(spec, flags):
    if spec == "world":
        return list(flags.index)
    kind, _, value = spec.partition(":")
    if kind == "flag":
        return list(flags.index[flags[value.lower()] == 1])
    if kind == "continent":
        return list(flags.index[flags.continent == value])
    return [spec]


def multiples(p, isos):
    s = p[p.iso3.isin(isos)].groupby("year")[["baseline_twh", "central_twh", "high_twh"]].sum()
    return s / s.loc[BASE]


def compare(p):
    dem = ember_demand()
    flags = dem.sort_values("year").groupby("iso3").last()[["continent", "eu", "asean"]]
    flags = flags[flags.index.isin(p.iso3)]
    rows = []

    weo = pd.read_csv(path("weo"), comment="#")
    for r in weo[weo.members != "-"].itertuples():
        m = multiples(p, members(r.members, flags))
        for year, cps, steps in ((2035, r.cps2035, r.steps2035), (2050, r.cps2050, r.steps2050)):
            for name, v, level in (("IEA WEO25 STEPS", steps, "stated policies"), ("IEA WEO25 CPS", cps, "current policies")):
                rows.append(dict(region=r.region, year=year, outlook=name, level=level, outlook_multiple=v / r.y2024,
                                 baseline=m.at[year, "baseline_twh"], central=m.at[year, "central_twh"], high=m.at[year, "high_twh"]))

    mp = pd.read_csv(path("manual_points"), comment="#", keep_default_na=False)
    mp = mp[(mp.quantity == "demand") & (mp.country == "")]
    now = mp[mp.scenario == "now"].set_index("region").value.astype(float)
    groups = pd.Series(modelled_countries())
    for r in mp[(mp.scenario == "zero") & ~mp.source_short.str.startswith("IEA WEO25")].itertuples():
        m = multiples(p, groups.index[groups == r.region])
        value = MANUAL_VALUE.get(r.source_short, float(r.value))
        rows.append(dict(region=r.region, year=int(r.year), outlook=r.source_short.replace(" 2050", ""), level=LEVEL[r.source_short],
                         outlook_multiple=value / now[r.region], baseline=m.at[2050, "baseline_twh"],
                         central=m.at[2050, "central_twh"], high=m.at[2050, "high_twh"]))

    old = pd.read_csv(path("old_heuristic"), keep_default_na=False)
    old = old[pd.to_numeric(old.demand_twh_2050, errors="coerce").notna()].set_index("iso3")
    for region in ARCHETYPES + ["World"]:
        isos = list(flags.index) if region == "World" else list(groups.index[groups == region])
        o = old.reindex(isos).dropna(subset=["demand_twh_2050"])
        m = multiples(p, isos)
        rows.append(dict(region=region, year=2050, outlook="old heuristic (country-classification)", level="heuristic",
                         outlook_multiple=o.demand_twh_2050.astype(float).sum() / o.demand_twh.astype(float).sum(),
                         baseline=m.at[2050, "baseline_twh"], central=m.at[2050, "central_twh"], high=m.at[2050, "high_twh"]))

    c = pd.DataFrame(rows)
    c["central_vs_outlook"] = c.central / c.outlook_multiple - 1
    return c


def verdict(c):
    fit = json.load(open(os.path.join(BUILD, "fit.json")))
    bt = pd.read_csv(os.path.join(BUILD, "backtest.csv"))
    bt = bt[bt.specification == fit["selected"]]
    groups = modelled_countries()
    arche = [i for i, g in groups.items() if g in ARCHETYPES]
    lines = [f"# Go / no-go ({fit['selected']} specification, base {BASE})", "",
             "| criterion | threshold | result | pass |", "|---|---|---|---|"]
    ok = True

    def add(name, threshold, value, text=None):
        nonlocal ok
        passed = abs(value) <= threshold
        ok &= passed
        lines.append(f"| {name} | ±{threshold:.0%} | {text or f'{value:+.1%}'} | {'yes' if passed else 'NO'} |")

    for window, d in bt.groupby("window"):
        w = (d.predicted - d.actual).abs().sum() / d.actual.sum()
        add(f"backtest {window}, demand-weighted absolute error", CRIT["backtest_weighted_abs_error"], w, f"{w:.1%}")
        a = d[d.iso3.isin(arche)].set_index("iso3").error
        worst = a.abs().idxmax()
        add(f"backtest {window}, worst archetype country", CRIT["backtest_archetype_country_error"], a[worst], f"{worst} {a[worst]:+.1%}")
    steps = c[(c.outlook == "IEA WEO25 STEPS") & (c.year == 2050)].set_index("region").central_vs_outlook
    for region in ["United States", "India", "China", "European Union", "Brazil"]:
        add(f"2050 growth multiple vs WEO25 STEPS, {region}", CRIT["outlook_2050_region_error"], steps[region])
    add("2050 growth multiple vs WEO25 STEPS, World", CRIT["outlook_2050_world_error"], steps["World"])
    lines += ["", f"**Verdict: {'GO' if ok else 'NO-GO as it stands'}**"]
    open(os.path.join(BUILD, "verdict.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def fig_weo(c):
    d = c[(c.outlook == "IEA WEO25 STEPS") & (c.year == 2050)].sort_values("outlook_multiple")
    fig, ax = plt.subplots(figsize=(8, 4.6), facecolor=SURFACE)
    style(ax)
    y = np.arange(len(d))
    ax.hlines(y, d.central, d.high, color=BLUE_LIGHT, linewidth=4, label="up to the high electrification case", zorder=2)
    ax.scatter(d.baseline, y, s=46, facecolor=SURFACE, edgecolor=BLUE, linewidth=1.6, label="income-driven baseline only", zorder=3)
    ax.scatter(d.central, y, s=56, color=BLUE, edgecolor=SURFACE, linewidth=1.5, label="baseline + electrification, central", zorder=4)
    ax.scatter(d.outlook_multiple, y, s=64, marker="D", color=ORANGE, edgecolor=SURFACE, linewidth=1.5, label="IEA WEO 2025, Stated Policies", zorder=5)
    ax.set_yticks(y, d.region, color=INK, fontsize=9)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(f"electricity demand in 2050 as a multiple of {BASE}", color=MUTED, fontsize=9)
    ax.set_title("Demand growth to 2050: this projection against the IEA Stated Policies Scenario", loc="left", color=INK, fontsize=11)
    ax.legend(frameon=False, fontsize=8, loc="lower right", labelcolor=INK)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES, "growth_vs_weo.png"), dpi=200)


def fig_regions(p, c):
    dem = ember_demand()
    groups = pd.Series(modelled_countries())
    weo_for = {"US": "United States", "BR": "Brazil", "IN": "India", "CN": "China", "NWE": "European Union"}
    fig, axes = plt.subplots(2, 3, figsize=(12, 6.4), facecolor=SURFACE)
    for ax, region in zip(axes.flat, ARCHETYPES):
        style(ax)
        isos = groups.index[groups == region]
        hist = dem[dem.iso3.isin(isos) & (dem.year <= BASE)].groupby("year").demand_twh.sum()
        s = p[p.iso3.isin(isos)].groupby("year")[["baseline_twh", "central_twh", "high_twh"]].sum()
        ax.plot(hist.index, hist.values, color=INK, linewidth=2, label="Ember history")
        ax.fill_between(s.index, s.central_twh, s.high_twh, color=BLUE_LIGHT, alpha=0.6, linewidth=0, label="up to high electrification")
        ax.plot(s.index, s.baseline_twh, color=BLUE, linewidth=1.5, linestyle=(0, (4, 2)), label="income-driven baseline")
        ax.plot(s.index, s.central_twh, color=BLUE, linewidth=2, label="baseline + electrification, central")
        base = s.central_twh.loc[BASE]
        dots = c[(c.year.isin([2035, 2050])) & (c.level != "heuristic") & (c.outlook != "IEA WEO25 CPS")
                 & ((c.region == region) | (c.region == weo_for.get(region)))]
        for i, d in enumerate(dots.itertuples()):
            ax.scatter(d.year, d.outlook_multiple * base, s=46, marker="D", color=ORANGE, edgecolor=SURFACE, linewidth=1.2,
                       zorder=5, label="published outlook (growth multiple x Ember 2024)" if i == 0 else None)
            if d.year == 2050:
                name = d.outlook.replace("IEA ", "") + (" (EU)" if region == "NWE" and d.region == "European Union" else "")
                ax.annotate(name, (d.year, d.outlook_multiple * base), xytext=(-6, 0), textcoords="offset points",
                            ha="right", va="center", fontsize=6.5, color=MUTED)
        ax.set_title({"US": "United States", "BR": "Brazil", "IN": "India", "SG": "Singapore (no 2050 demand outlook)",
                      "NWE": "North-West Europe (12 countries)", "CN": "China"}[region], loc="left", color=INK, fontsize=10)
        ax.set_ylim(0)
        ax.set_ylabel("TWh", color=MUTED, fontsize=8)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=8.5, ncol=5, loc="lower center", labelcolor=INK)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(os.path.join(FIGURES, "projection_regions.png"), dpi=200)


def fig_backtest():
    fit = json.load(open(os.path.join(BUILD, "fit.json")))
    bt = pd.read_csv(os.path.join(BUILD, "backtest.csv"))
    bt = bt[(bt.specification == fit["selected"]) & (bt.window == "2014-2024")]
    fig, ax = plt.subplots(figsize=(6, 5.6), facecolor=SURFACE)
    style(ax)
    lim = [bt.actual.min() * 0.7, bt.actual.max() * 1.5]
    ax.plot(lim, lim, color=MUTED, linewidth=1)
    ax.fill_between(lim, [v * 0.8 for v in lim], [v * 1.2 for v in lim], color=GRID, alpha=0.7, linewidth=0)
    ax.scatter(bt.actual, bt.predicted, s=18, color=BLUE, edgecolor=SURFACE, linewidth=0.6, zorder=3)
    for r in bt[bt.iso3.isin(["USA", "CHN", "IND", "BRA", "DEU", "GBR", "FRA", "SGP", "JPN", "RUS"])].itertuples():
        ax.annotate(r.iso3, (r.actual, r.predicted), xytext=(4, -8), textcoords="offset points", fontsize=7, color=INK)
    ax.set_xscale("log"), ax.set_yscale("log"), ax.set_xlim(lim), ax.set_ylim(lim)
    ax.set_xlabel("actual demand 2024 (TWh, Ember)", color=MUTED, fontsize=9)
    ax.set_ylabel("predicted from 2014 with a fit on 2000-2014 (TWh)", color=MUTED, fontsize=9)
    ax.set_title("Backtest of the income-driven baseline (band: ±20 %)", loc="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES, "backtest.png"), dpi=200)


def main():
    os.makedirs(FIGURES, exist_ok=True)
    p = projection()
    dem = ember_demand()
    last = dem[dem.year <= BASE].sort_values("year").groupby("iso3").last().demand_twh
    b = p[p.year == BASE].set_index("iso3")
    assert np.allclose(b.central_twh, last.reindex(b.index)), "base-year projection must equal Ember"
    falling = p[(p.year == 2050)].set_index("iso3").central_twh / b.central_twh
    print("countries with falling demand to 2050:", falling[falling < 0.9].round(2).to_dict())
    p.to_csv(os.path.join(BUILD, "projection.csv"), index=False)

    c = compare(p)
    c.round(3).to_csv(os.path.join(BUILD, "comparison.csv"), index=False)
    print(c[c.year == 2050].round(2).to_string(index=False), "\n")
    world = p.groupby("year")[["baseline_twh", "central_twh", "high_twh"]].sum()
    print("world, TWh (Ember definition):\n", world.round(0).to_string(), "\n")
    verdict(c)
    fig_weo(c), fig_regions(p, c), fig_backtest()


if __name__ == "__main__":
    main()
