# SPDX-License-Identifier: CC0-1.0
"""
Learning market of a pathway: cost factor and cumulative capacity of every learning pool per planning horizon.

    cd models/pypsa-earth
    pixi run python ../../config-pypsa-earth/scripts/plot_learning.py <market>

Reads results/learning/<market>/market_<year>.csv (scripts/clear_market.py) and writes
results/learning/<market>/learning.{png,pdf}: left the CAPEX of each pool and component relative to its 2025 value
(the factor the palette costs of that horizon use), right the cumulative capacity (log scale, GW or GWh) with the
reference capacity Q0 as the starting point. Icon style (plotstyle/).
"""
import glob
import os
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(__file__).resolve()
sys.path.insert(0, str(next(p for p in HERE.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
sys.path.insert(0, str(HERE.parents[1] / "technology-assumptions" / "scripts"))
import iconstyle as ic  # noqa: E402
import palette  # noqa: E402


def load(market):
    files = sorted(glob.glob(os.path.join("results", "learning", market, "market_*.csv")))
    if not files:
        sys.exit(f"plot_learning: no market files under results/learning/{market}/")
    frames = []
    for f in files:
        df = pd.read_csv(f, comment="#")
        df["year"] = int(re.search(r"market_(\d{4})", f).group(1))
        frames.append(df)
    header = [l[2:].strip() for l in open(files[-1]) if l.startswith("#")]
    return pd.concat(frames, ignore_index=True), header


def label(rows, pool, comp, two):
    name = rows[pool].get("label") or pool
    return f"{name} ({comp})" if two else name


def end_labels(ax, items, gap=0.06):
    """Direct labels at the line ends, pushed apart vertically (axis fraction) so coinciding lines stay legible."""
    to_ax = ax.transData + ax.transAxes.inverted()
    pts = sorted(((to_ax.transform((x, y))[1], x, text) for x, y, text in items), key=lambda t: t[0])
    ys = []
    for y, _, _ in pts:
        ys.append(max(y, ys[-1] + gap) if ys else y)
    shift = max(0.0, ys[-1] - 0.98) if ys else 0.0
    for (y0, x, text), y in zip(pts, ys):
        ax.annotate(text, xy=(x, y0), xycoords=("data", "axes fraction"), xytext=(10, (y - shift - y0) * ax.bbox.height),
                    textcoords="offset points", va="center", ha="left", color=ic.INK, annotation_clip=False)


def plot(market):
    df, header = load(market)
    rows = {r["technology"]: r for r in palette.read()}
    keys = list(dict.fromkeys(zip(df.pool, df.component)))
    ncomp = df.groupby("pool").component.nunique()
    colors = dict(zip(keys, ic.CATEGORICAL))
    ic.use()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.2, 3.9))
    years = sorted(df.year.unique())
    labels1, labels2 = [], []
    for k in keys:
        d = df[(df.pool == k[0]) & (df.component == k[1])].sort_values("year")
        name = label(rows, k[0], k[1], ncomp[k[0]] > 1)
        x, f, q = d.year.to_numpy(), d.factor.to_numpy(), d.cumulative_capacity.to_numpy()
        ic.cased_line(a1, x, f, colors[k], direct_label=False)
        ic.cased_line(a2, x, q, colors[k], direct_label=False)
        labels1.append((x[-1], f[-1], f"{name} {f[-1]:.2f}"))
        labels2.append((x[-1], q[-1], f"{name}, {q[-1]:,.3g} {d.unit.iloc[0]}"))
    a1.set_title("CAPEX relative to the 2025 CSV value (learning factor)")
    a1.set_ylim(0, 1.08)
    a2.set_title("Cumulative capacity, Q0 = existing + pipeline (log)")
    a2.set_yscale("log")
    a2.minorticks_off()
    a2.set_ylim(df.cumulative_capacity.min() / 2, df.cumulative_capacity.max() * 2)
    for a in (a1, a2):
        a.set_xticks(years)
        a.set_xlim(years[0] - 1, years[-1] + 9)
        ic.ground(a, at=a.get_ylim()[0])
    end_labels(a1, labels1)
    end_labels(a2, labels2)
    fig.text(0.01, 0.005, " | ".join(header[1:2]), fontsize=6.5, color=ic.MUTED, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    out = os.path.join("results", "learning", market, "learning")
    for ext in ("png", "pdf"):
        fig.savefig(f"{out}.{ext}", dpi=200)
    print(f"plot_learning: wrote {out}.png / .pdf")


if __name__ == "__main__":
    plot(sys.argv[1] if len(sys.argv) > 1 else "myopic")
