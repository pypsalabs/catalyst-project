# SPDX-License-Identifier: CC0-1.0
"""
Learning sensitivities of one region side by side (branches of a common trunk, catalyst.branch), x = year.

    cd models/pypsa-earth
    pixi run python ../../config-pypsa-earth/scripts/plot_branches.py <R> <branch scen> [<branch scen> ...] [--out <name>]

e.g. plot_branches.py JP ref cfesec cfemid cfeext (ref = the no-CFE reference, its own panel). Runs summarise_cfe.py for every stage <R>-<scen> and writes
results/learning/<name>/ (default <R>-branches) power, energy, mix, learning and premium .png/.pdf (icon style):
  power     advanced power capacity in the region, stacked area by technology, one panel per sensitivity
  energy    advanced energy capacity (storage GWh), same layout
  mix       generation per horizon by technology group, stacked bars, the 24/7 CFE buyer's own plants hatched on top
            (share of the total above each bar)
  learning  learning factor per technology / component, one panel per sensitivity
  premium   24/7 CFE buyer's cost minus the load-weighted average price of the rest of the region's demand, USD/MWh,
            one line per sensitivity
The horizons up to the branch year are the trunk's (the same in every panel); a thin dashed line marks the branch.
"""
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(__file__).resolve()
sys.path.insert(0, str(next(p for p in HERE.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))
import iconstyle as ic  # noqa: E402
import merge_config  # noqa: E402
import summarise_cfe  # noqa: E402

TECH_COLOR = {"egs": ic.AMBER, "iron-air": ic.TEAL, "nuclear-gen4": ic.BLUE, "sofc": ic.VIOLET,
              "sofc-cc": ic.GOLD, "vrfb": ic.RED, "co2-battery": ic.STEEL}
NAME = {"egs": "EGS", "iron-air": "Iron-air", "nuclear-gen4": "Gen IV", "sofc": "SOFC", "sofc-cc": "SOFC-CC",
        "vrfb": "VRFB", "co2-battery": "CO2 battery"}
SPILLOVER = {"1": "secluded", "1.0": "secluded", "midpoint": "midpoint", "extrapolate": "extrapolated"}
SCEN_COLOR = [ic.STEEL, ic.BLUE, ic.AMBER, ic.TEAL, ic.VIOLET, ic.RED]


# energy mix: carrier groups bottom-up, (name, carriers, colour); everything else falls into "Other" (pale)
MIX_GROUPS = [("Nuclear", ["nuclear"], ic.VIOLET), ("Coal", ["coal", "lignite"], ic.STEEL),
              ("Gas and oil", ["CCGT", "OCGT", "oil", "gas"], ic.STEEL_L), ("Hydro", ["hydro", "ror"], ic.TEAL),
              ("Other", None, ic.PALE), ("Wind", ["onwind", "offwind-ac", "offwind-dc"], ic.BLUE),
              ("Solar", ["solar", "solar rooftop"], ic.GOLD), ("EGS", ["egs"], ic.AMBER),
              ("Other advanced", ["nuclear-gen4", "sofc", "sofc-cc"], ic.RED)]


def mix_group(carrier):
    for name, cars, _ in MIX_GROUPS:
        if cars and carrier in cars:
            return name
    return "Other"


def plot_mix(stages, mix, out, region):
    """Generation per horizon, stacked bars per sensitivity; the 24/7 CFE buyers' own plants on top, hatched."""
    from matplotlib.patches import Patch

    mix = mix.assign(group=mix.carrier.map(mix_group), grid=mix.twh - mix.twh_buyer)
    years = sorted(mix.year.unique())
    order = [g for g, _, _ in MIX_GROUPS]
    color = {g: c for g, _, c in MIX_GROUPS}
    present = [g for g in order if mix[mix.group == g].twh.max() > 0.5]
    top = mix.groupby(["stage", "year"]).twh.sum().max() * 1.1
    width = 0.68 * (years[1] - years[0]) if len(years) > 1 else 3.0
    plt.rcParams["hatch.linewidth"] = 0.7
    fig, axes = plt.subplots(1, len(stages), figsize=(3.9 * len(stages), 4.0), sharey=True, squeeze=False)
    for ax, s in zip(axes[0], stages):
        d = mix[mix.stage == s]
        grid = d.pivot_table(index="year", columns="group", values="grid", aggfunc="sum").reindex(columns=present)
        buyer = d.pivot_table(index="year", columns="group", values="twh_buyer", aggfunc="sum").reindex(columns=present)
        grid, buyer = grid.fillna(0.0), buyer.fillna(0.0)
        ax.set_xlim(years[0] - width, years[-1] + width)
        ax.set_ylim(0, top)
        for y in grid.index:
            base = 0.0
            for g in present:
                v = grid.at[y, g]
                if v > 0:
                    ax.bar(y, v, width, bottom=base, color=color[g], edgecolor=ic.INK, linewidth=ic.SEAM, zorder=2)
                    base += v
            b0 = base
            for g in present:
                v = buyer.at[y, g]
                if v > 0:
                    ax.bar(y, v, width, bottom=base, color=color[g], edgecolor=ic.INK, linewidth=ic.SEAM,
                           hatch="////", zorder=2)
                    base += v
            if base > b0:   # the buyer block: heavy outline around it
                ax.bar(y, base - b0, width, bottom=b0, fill=False, edgecolor=ic.INK, linewidth=ic.OUTLINE * 1.3,
                       zorder=3)
                ax.annotate(f"{100 * (base - b0) / base:.0f}%", (y, base), xytext=(0, 2.5), textcoords="offset points",
                            ha="center", va="bottom", color=ic.INK, fontsize=6.6)
        solved = list(grid.index)
        if solved and solved[-1] < years[-1]:
            ax.text((solved[-1] + years[-1]) / 2 + width / 2, top * 0.5, f"after {solved[-1]}:\nnot solved yet",
                    ha="center", va="center", color=ic.MUTED)
        nm, br = title_of(s)
        ax.set_title(nm + (" (TWh)" if ax is axes[0][0] else ""))
        if br:
            ax.axvline(br["year"] + (years[1] - years[0]) / 2, color=ic.MUTED, lw=0.8, ls=(0, (3, 3)), zorder=1)
        ax.set_xticks(years)
        ic.ground(ax)
    handles = [Patch(facecolor=color[g], edgecolor=ic.INK, linewidth=ic.MARK, label=g) for g in present]
    handles.append(Patch(facecolor="white", edgecolor=ic.INK, linewidth=ic.MARK * 1.6, hatch="////",
                         label="24/7 CFE buyer's own plants (share of total above the bar)"))
    fig.legend(handles=handles, loc="lower center", ncol=len(handles), frameon=False)
    fig.suptitle(f"Electricity generation in {region} per planning horizon; the 24/7 CFE buyer's plants hatched on "
                 f"top (incl. its excess sold to the grid; storage not shown)", x=0.01, ha="left", fontsize=8.6,
                 color=ic.INK)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    save(fig, out)


def title_of(stage):
    cat = merge_config.stage_config("overlay", stage)["catalyst"]
    if not cat.get("cfe"):
        return "reference (no 24/7 CFE)", cat.get("branch")
    v = str(cat.get("learning_spillover"))
    return SPILLOVER.get(v, f"x{v}" if v != "None" else "only modelled builds"), cat.get("branch")


def panels(stages, data, column, unit, out, what):
    years = sorted(data.year.unique())
    techs = [t for t in NAME if data[(data.technology == t)][column].max() > 1e-2]
    fig, axes = plt.subplots(1, len(stages), figsize=(3.9 * len(stages), 3.6), sharey=True, squeeze=False)
    top = max(data.groupby(["stage", "year"])[column].sum().max(), 1.0) * 1.12
    for ax, s in zip(axes[0], stages):
        d = data[data.stage == s].pivot_table(index="year", columns="technology", values=column, aggfunc="sum")
        solved = sorted(d.index)
        d = d.reindex(index=solved, columns=techs).fillna(0.0)
        ax.set_xlim(years[0], years[-1])
        ax.set_ylim(0, top)
        if techs and len(solved) > 1:
            ic.stacked_area(ax, solved, [d[t].to_numpy() for t in techs], [TECH_COLOR[t] for t in techs])
        if not techs:
            ax.text(0.5, 0.5, "none built", transform=ax.transAxes, ha="center", va="center", color=ic.MUTED)
        if solved and solved[-1] < years[-1]:
            ax.text((solved[-1] + years[-1]) / 2, top * 0.5, f"after {solved[-1]}:\nnot solved yet", ha="center",
                    va="center", color=ic.MUTED)
        name, br = title_of(s)
        ax.set_title(f"{name}" + (f" ({unit})" if ax is axes[0][0] else ""))
        if br:
            ax.axvline(br["year"], color=ic.MUTED, lw=0.8, ls=(0, (3, 3)), zorder=1)
        ax.set_xticks(years)
        ic.ground(ax)
    if techs:
        ic.legend_squares(axes[0][-1], [(TECH_COLOR[t], NAME[t]) for t in techs])
    fig.suptitle(what, x=0.01, ha="left", fontsize=8.6, color=ic.INK)
    fig.tight_layout()
    save(fig, out)


def save(fig, out):
    for ext in ("png", "pdf"):
        fig.savefig(f"{out}.{ext}", dpi=200)
    plt.close(fig)
    print(f"plot_branches: wrote {out}.png / .pdf")


def main(region, scens, name=None):
    stages = [f"{region}-{s}" for s in scens]
    tables = {s: summarise_cfe.summarise(s) for s in stages}
    caps = pd.concat([t["summary"] for t in tables.values()], ignore_index=True)
    cfe = pd.concat([t["cfe"] for t in tables.values() if len(t["cfe"])], ignore_index=True) \
        if any(len(t["cfe"]) for t in tables.values()) else pd.DataFrame()
    fac = pd.concat([t["factors"] for t in tables.values() if len(t["factors"])], ignore_index=True)
    outdir = os.path.join("results", "learning", name or f"{region}-branches")
    os.makedirs(outdir, exist_ok=True)
    mix = pd.concat([t["mix"] for t in tables.values() if len(t["mix"])], ignore_index=True)
    for k, df in dict(summary=caps, cfe=cfe, factors=fac, mix=mix).items():
        df.to_csv(os.path.join(outdir, f"{k}.csv"), index=False, float_format="%.6g")
    ic.use()

    panels(stages, caps, "gw", "GW", os.path.join(outdir, "power"),
           f"Advanced technologies in {region}: power capacity installed (GW, all vintages)")
    panels(stages, caps, "gwh", "GWh", os.path.join(outdir, "energy"),
           f"Advanced technologies in {region}: storage energy capacity installed (GWh)")

    plot_mix(stages, mix, os.path.join(outdir, "mix"), region)

    # learning factors
    years = sorted(fac.year.unique())
    learned = fac.groupby(["pool", "component"]).factor.min() < 1 - 1e-6
    keys = [k for k in dict.fromkeys(zip(fac.pool, fac.component)) if learned.get(k, False)]
    flat = sorted({NAME.get(p, p) for p, _ in dict.fromkeys(zip(fac.pool, fac.component))} - {NAME.get(p, p) for p, _ in keys})
    ncomp = fac.groupby("pool").component.nunique()
    comp_color = {("egs", "plant"): ic.GOLD}
    color_of = lambda k: comp_color.get(k, TECH_COLOR.get(k[0], ic.STEEL))  # noqa: E731
    fig, axes = plt.subplots(1, len(stages), figsize=(3.9 * len(stages), 3.6), sharey=True, squeeze=False)
    for ax, s in zip(axes[0], stages):
        ax.set_xlim(years[0], years[-1])
        ax.set_ylim(0, 1.08)
        for k in keys:
            d = fac[(fac.stage == s) & (fac.pool == k[0]) & (fac.component == k[1])].sort_values("year")
            if len(d):
                ic.cased_line(ax, d.year.to_numpy(), d.factor.to_numpy(), color_of(k), direct_label=False)
        nm, br = title_of(s)
        ax.set_title(nm + (" (CAPEX / 2025 CSV value)" if ax is axes[0][0] else ""))
        if br:
            ax.axvline(br["year"], color=ic.MUTED, lw=0.8, ls=(0, (3, 3)), zorder=1)
        ax.set_xticks(years)
        ic.ground(ax)
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(facecolor=color_of(k), edgecolor=ic.INK, linewidth=ic.MARK,
                              label=NAME.get(k[0], k[0]) + (f" {k[1]}" if ncomp[k[0]] > 1 else "")) for k in keys],
               loc="lower center", ncol=max(len(keys), 1), frameon=False)
    fig.suptitle("Learning factor per technology, market of each sensitivity"
                 + (f" (not built, factor 1: {', '.join(flat)})" if flat else ""), x=0.01, ha="left", fontsize=8.6,
                 color=ic.INK)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    save(fig, os.path.join(outdir, "learning"))

    # CFE premium
    if len(cfe):
        fig, (ax, ax2) = plt.subplots(1, 2, figsize=(11.6, 3.6))
        wavg = lambda col: cfe.groupby(["stage", "year"]).apply(  # noqa: E731
            lambda g: np.average(g[col], weights=g.demand_twh), include_groups=False)
        p = wavg("premium_per_mwh").rename("premium")
        buy, grid = wavg("cost_per_mwh"), wavg("grid_price_per_mwh")
        lo, hi = min(0.0, p.min()), p.max()
        ax.set_xlim(min(p.index.get_level_values(1)), max(p.index.get_level_values(1)) + 4)
        ax.set_ylim(lo - 0.08 * (hi - lo + 1), hi + 0.15 * (hi - lo + 1))
        for c, s in zip(SCEN_COLOR, stages):
            if s in p.index.get_level_values(0):
                d = p.loc[s].sort_index()
                ic.cased_line(ax, d.index.to_numpy(), d.to_numpy(), c, label=f"{title_of(s)[0]} {d.iloc[-1]:,.0f}")
        br = title_of(stages[0])[1]
        if br:
            ax.axvline(br["year"], color=ic.MUTED, lw=0.8, ls=(0, (3, 3)), zorder=1)
        ax.set_xticks(sorted(set(p.index.get_level_values(1))))
        ax.set_title("24/7 CFE buyer cost minus average grid price, USD2024/MWh")
        ic.ground(ax, at=ax.get_ylim()[0])
        # the two terms: buyer cost (pipes) and the load-weighted grid price (dashed)
        ax2.set_xlim(ax.get_xlim())
        ax2.set_ylim(0, max(buy.max(), grid.max()) * 1.15)
        for c, s in zip(SCEN_COLOR, stages):
            if s in buy.index.get_level_values(0):
                b, g = buy.loc[s].sort_index(), grid.loc[s].sort_index()
                ic.cased_line(ax2, b.index.to_numpy(), b.to_numpy(), c)
                ax2.plot(g.index, g.to_numpy(), color=c, lw=1.6, ls=(0, (4, 2)), zorder=3)
                ax2.annotate(f"{g.iloc[-1]:,.0f}", (g.index[-1], g.iloc[-1]), xytext=(6, 0),
                             textcoords="offset points", va="center", color=ic.INK)
        if br:
            ax2.axvline(br["year"], color=ic.MUTED, lw=0.8, ls=(0, (3, 3)), zorder=1)
        ax2.set_xticks(ax.get_xticks())
        ax2.set_title("buyer cost (solid) and grid price (dashed), USD2024/MWh")
        ic.ground(ax2)
        fig.tight_layout()
        save(fig, os.path.join(outdir, "premium"))


if __name__ == "__main__":
    args = sys.argv[1:]
    name = None
    if "--out" in args:
        i = args.index("--out")
        name = args[i + 1]
        del args[i:i + 2]
    main(args[0], args[1:], name)
