# SPDX-License-Identifier: CC0-1.0
"""
World power-mix page, before and after the catalyst patches: per modelled country three 100 % bars, top to bottom
    Ember 2024     actual generation by fuel, latest year <= 2024
    0.9.0          the `now` solve of PyPSA-Earth v0.9.0 as it comes (baseline/run_overnight.sh)
    with patches   the `now` solve of the patched fork: dispatch of the 2024 system calibrated to Ember
Both model rows are read from the per-country tables plot_world.py writes (validation_world.csv), so no network is
opened; the `zero` solves are left out. Right of the bars: fossil share (coal + gas + oil) and power-sector CO2 in Mt
(as on the plot_world.py page). Next to the name: code · Ember demand | 0.9.0 load | patched load (TWh).
The header holds the aggregate over all countries and five scatters of each model row against Ember (dot area ~ demand).
Carrier colours are the PyPSA-Eur defaults (plot_world.FALLBACK).

Standalone (fork env, from anywhere):
    python config-pypsa-earth/scripts/plot_world_before_after.py \
        --before models/pypsa-earth-baseline/results/catalyst/validation_world.csv \
        --after models/pypsa-earth/results/catalyst/validation_world.csv \
        --out misc-quarter1/pypsa-earth-out-of-the-box-validation/figures/before-after/validation_world_before_after.png
"""
import argparse
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.transforms import blended_transform_factory  # noqa: E402

from plot_world import FALLBACK, FOSSIL, INK, INK2, MUTED, NAMES, ORDER, RULE, hbar, shares  # noqa: E402

ROWS = ["ember", "before", "after"]
LABEL = {"ember": "Ember 2024", "before": "0.9.0", "after": "with patches"}
DOT = {"before": "#9a9a9a", "after": "#3b6fd6"}


def read(before, after):
    """Long table: one row per (country, ROWS entry); Ember from the after table, model rows from the `now` solves."""
    b, a = pd.read_csv(before), pd.read_csv(after)
    df = pd.concat([a[a.scen == "ember"], b[b.scen == "now"].assign(scen="before"), a[a.scen == "now"].assign(scen="after")],
                   ignore_index=True)
    df[ORDER] = df[ORDER].fillna(0.0)
    meta = a.drop_duplicates("country").set_index("country")[["name", "region", "demand", "year"]]
    for k in meta.columns:
        df[k] = df.country.map(meta[k]).fillna(df[k])
    return df


def draw_column(ax, block, col):
    tr = blended_transform_factory(ax.transAxes, ax.transData)
    step = 3.9
    for i, (c, g) in enumerate(block):
        y0 = i * step
        first = g.iloc[0]
        ax.text(-0.155, y0 + 1, first["name"], transform=tr, ha="right", va="center", fontsize=6.6, color=INK)
        load = {s: g.loc[g.scen == s, "load"] for s in ("before", "after")}
        mod = [f"{v.iloc[0]:.0f}" if len(v) and pd.notna(v.iloc[0]) else "–" for v in load.values()]
        dem = f"{first['demand']:.0f}" if pd.notna(first["demand"]) else "–"
        ax.text(-0.155, y0 + 2.05, f"{c} · {dem} | {mod[0]} | {mod[1]} TWh", transform=tr, ha="right",
                va="center", fontsize=4.8, color=MUTED)
        for j, scen in enumerate(ROWS):
            y = y0 + j
            ax.text(-0.012, y, LABEL[scen], transform=tr, ha="right", va="center", fontsize=4.6, color=MUTED)
            r = g[g.scen == scen]
            if not len(r) or not np.nansum([r.iloc[0][k] for k in ORDER]) > 0:
                why = "no Ember data" if scen == "ember" else ("no load" if len(r) and r.iloc[0].load == 0 else "not solved")
                ax.text(0.01, y, why, transform=tr, va="center", fontsize=4.6, color=MUTED)
                continue
            sh, _ = shares(r.iloc[0])
            hbar(ax, y, sh, col, 0.78)
            txt = f"{100 * sum(sh[k] for k in FOSSIL):.0f} %"
            co2 = r.iloc[0].get("co2", np.nan)
            if pd.notna(co2):
                txt += f" · {co2:.1f} Mt" if co2 < 10 else f" · {co2:,.0f} Mt"
            if sh["shed"] > 0.005:
                txt += f"  shed {100 * sh['shed']:.0f} %"
            ax.text(1.012, y, txt, transform=tr, va="center", fontsize=4.8,
                    color=FALLBACK["shed"] if sh["shed"] > 0.005 else INK2)
    ax.set_xlim(0, 1)
    ax.set_ylim(len(block) * step - 0.6, -0.8)
    ax.axis("off")


def frame(ax, title, xlabel, ylabel):
    ax.tick_params(labelsize=5.5, colors=INK2, length=2, which="both")
    for s in ax.spines.values():
        s.set_color(RULE)
    ax.set_title(title, fontsize=7, color=INK, loc="left")
    ax.set_xlabel(xlabel, fontsize=5.5, color=INK2, labelpad=1)
    ax.set_ylabel(ylabel, fontsize=5.5, color=INK2, labelpad=1)


def draw_scatter(ax, df, groups, title):
    share = {s: (lambda d: d[groups].sum(axis=1) / d[ORDER].sum(axis=1))(df[df.scen == s].set_index("country"))
             for s in ROWS}
    dem = df.drop_duplicates("country").set_index("country").demand
    ax.plot([0, 100], [0, 100], color=RULE, lw=1, zorder=0)
    for s in ("before", "after"):
        x, y = share["ember"], share[s].reindex(share["ember"].index)
        ok = x.notna() & y.notna()
        d = dem.reindex(x[ok].index).fillna(1)
        ax.scatter(100 * x[ok], 100 * y[ok], s=4 + 60 * np.sqrt(d / dem.max()), color=DOT[s], alpha=0.6,
                   edgecolor="white", linewidth=0.5, zorder=2 if s == "after" else 1)
    ax.set_xlim(-3, 103)
    ax.set_ylim(-3, 103)
    ax.set_xticks([0, 50, 100])
    ax.set_yticks([0, 50, 100])
    frame(ax, title, "Ember 2024 %", "model %")


def draw_co2_scatter(ax, df):
    e = df[df.scen == "ember"].set_index("country").co2
    hi = 0.0
    for s in ("before", "after"):
        m = df[df.scen == s].set_index("country").co2.reindex(e.index)
        ok = e.notna() & (e > 0.05) & m.notna() & (m > 0.05)
        ax.scatter(e[ok], m[ok], s=4 + 60 * np.sqrt(e[ok] / e.max()), color=DOT[s], alpha=0.6, edgecolor="white",
                   linewidth=0.5, zorder=2 if s == "after" else 1)
        hi = max(hi, e[ok].max(), m[ok].max())
    lim = (0.05, hi * 1.5)
    ax.plot(lim, lim, color=RULE, lw=1, zorder=0)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.minorticks_off()
    frame(ax, "Fossil CO2, Mt", "Ember 2024", "model")


def page(df, col, out):
    order = (df[df.scen == "ember"].drop_duplicates("country").set_index("country").demand
             .reindex(df.country.unique()).sort_values(ascending=False, na_position="last").index)
    blocks = [(c, df[df.country == c]) for c in order]
    ncol = 4
    per = int(np.ceil(len(blocks) / ncol))
    fig = plt.figure(figsize=(24, 17.5), facecolor="white")
    fig.text(0.02, 0.975, "Electricity mix for 2024 validation of PyPSA-Earth 0.9.0 before and after patches, per country",
             fontsize=15, color=INK, weight="bold", va="top")

    # header: aggregate bars, scatters, legend
    ax = fig.add_axes([0.07, 0.855, 0.25, 0.075])
    agg = df.groupby("scen")[ORDER].sum()
    for j, scen in enumerate(ROWS):
        sh, tot = shares(agg.loc[scen])
        hbar(ax, j, sh, col, 0.75)
        x = 0
        for k in ORDER:
            if sh[k] > 0.045:
                ax.text(x + sh[k] / 2, j, f"{100 * sh[k]:.0f}", ha="center", va="center", fontsize=6.5,
                        color="white" if k in ("coal", "gas", "hydro", "wind", "shed") else INK)
            x += sh[k] if sh[k] > 0 else 0
        tr = blended_transform_factory(ax.transAxes, ax.transData)
        ax.text(-0.01, j, LABEL[scen], ha="right", va="center", fontsize=7.5, color=INK2, transform=tr)
        ax.text(1.01, j, f"{tot:,.0f} TWh", va="center", fontsize=6.5, color=INK2, transform=tr)
    ax.set_xlim(0, 1)
    ax.set_ylim(2.6, -0.6)
    ax.axis("off")
    co2 = df.groupby("scen").co2.sum() / 1e3
    ax.set_title(f"Aggregate (% of generation) · fossil CO2: Ember 2024 {co2['ember']:.1f} Gt, 0.9.0 {co2['before']:.1f} Gt, "
                 f"with patches {co2['after']:.1f} Gt", fontsize=7.5, color=INK, loc="left")
    for i, (grps, title) in enumerate([(FOSSIL, "Fossil share"), (["nuclear"], "Nuclear share"), (["hydro"], "Hydro share"),
                                       (["wind", "solar"], "Wind + solar share")]):
        draw_scatter(fig.add_axes([0.375 + i * 0.072, 0.845, 0.052, 0.085]), df, grps, title)
    draw_co2_scatter(fig.add_axes([0.375 + 4 * 0.072, 0.845, 0.052, 0.085]), df)
    handles = [plt.Rectangle((0, 0), 1, 1, color=col[k]) for k in ORDER]
    handles += [plt.Line2D([], [], ls="", marker="o", ms=5, color=DOT[s], alpha=0.8) for s in ("before", "after")]
    fig.legend(handles, [NAMES[k] for k in ORDER] + ["0.9.0 (scatters)", "with patches (scatters)"], loc="upper left",
               bbox_to_anchor=(0.745, 0.94), ncol=2, fontsize=7, frameon=False, handlelength=1.2, columnspacing=1.0)

    # body: four columns of countries sorted by Ember demand
    for k in range(ncol):
        part = blocks[k * per:(k + 1) * per]
        if part:
            draw_column(fig.add_axes([0.085 + k * 0.245, 0.015, 0.145, 0.80]), part, col)
    fig.savefig(out, dpi=200)
    fig.savefig(os.path.splitext(out)[0] + ".pdf")
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").strip().split("\n")[0])
    p.add_argument("--before", required=True, help="validation_world.csv of the v0.9.0 baseline run")
    p.add_argument("--after", required=True, help="validation_world.csv of the patched fork")
    p.add_argument("--out", required=True, help="png; a pdf with the same stem is written next to it")
    a = p.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    page(read(a.before, a.after), FALLBACK, a.out)
    print(f"wrote {a.out} and {os.path.splitext(a.out)[0]}.pdf")


if __name__ == "__main__":
    main()
