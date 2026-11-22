"""Electricity use of the corporate buyers behind voluntary clean-electricity procurement: the RE100 members, with the
largest of them named (config.yaml `buyers`), and their share of world electricity demand.

  data/buyers.csv, data/iea_regions.csv, Ember yearly data -> figures/corporate_buyers.{png,pdf}, build/buyers_{stack,share}.csv
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import yaml
from matplotlib.colors import to_rgb

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "scripts"))
import ftlook as ft

CFG = yaml.safe_load((HERE / "config.yaml").read_text())
GROUPS = CFG["buyers"]["groups"]
HUE = dict(zip(GROUPS, [ft.OXFORD, ft.TEAL, ft.MANDARIN, ft.VELVET, ft.CANDY]))
TINTS = [0.0, 0.24, 0.44, 0.60, 0.72, 0.82]            # share of white mixed into the group's hue, per company
OTHER, OTHER_COLOUR = "Other members", "#D6D6D6"
TOTAL = "RE100 members"


def tint(colour, white):
    return tuple(c + (1 - c) * white for c in to_rgb(colour))


def stack_table():
    """TWh per year: the named members from the year they joined and report, and the rest of the RE100 total."""
    y0, y1 = CFG["buyers"]["years"]
    b = pd.read_csv(HERE / "data/buyers.csv", comment="#")
    joined = b.dropna(subset="re100_joined").groupby("entity").re100_joined.first()
    wide = b.pivot(index="year", columns="entity", values="twh").loc[y0:y1]
    names = [c for members in GROUPS.values() for c in members]
    stack = wide[names].copy()
    for c in names:
        stack.loc[stack.index < joined[c], c] = float("nan")
        assert stack[c].loc[stack[c].first_valid_index():].notna().all(), f"{c}: gap after its first year"
    stack = stack.fillna(0.0)
    stack[OTHER] = wide[TOTAL] - stack.sum(axis=1)
    return stack, wide


def column(values, gap, lo, hi):
    """Label positions in one column: each at its value where there is room, otherwise pushed up, never closer than
    `gap` and never outside lo..hi; order is kept."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    y = [values[i] for i in order]
    y[0] = max(y[0], lo)
    for i in range(1, len(y)):
        y[i] = max(y[i], y[i - 1] + gap)
    y[-1] = min(y[-1], hi)
    for i in range(len(y) - 2, -1, -1):
        y[i] = min(y[i], y[i + 1] - gap)
    out = [0.0] * len(y)
    for i, v in zip(order, y):
        out[i] = v
    return out


def end_labels(ax, x, items, gap, dx, size=9):
    """Names at the right end: [(text, y, colour of the dot or None, bold)], each joined to its value by a hairline
    that leaves the value level, ends level before the text and never runs through another name."""
    span = ax.get_ylim()[1]
    pos = column([y for _, y, _, _ in items], gap * span, 0.012 * span, 0.985 * span)
    for (text, y0, dot, bold), y1 in zip(items, pos):
        # leader: a short level stub out of the band, a slanted run, a short level stub into the name
        ax.plot([x, x + 0.26 * dx, x + 0.70 * dx, x + 0.90 * dx], [y0, y0, y1, y1], color=ft.SOFT, linewidth=0.6,
                clip_on=False, zorder=5, solid_capstyle="butt", solid_joinstyle="round")
        ax.text(x + dx, y1, text, ha="left", va="center", fontsize=size, color=ft.INK,
                fontweight="bold" if bold else "regular", clip_on=False)
        if dot:
            ax.plot(x, y0, "o", color=dot, markersize=4.5, zorder=6, clip_on=False)


def main():
    ft.use()
    stack, wide = stack_table()
    years = stack.index
    colour = {c: tint(HUE[g], TINTS[i]) for g, members in GROUPS.items() for i, c in enumerate(members)}
    colour[OTHER] = OTHER_COLOUR
    (HERE / "build").mkdir(exist_ok=True)
    stack.round(3).to_csv(HERE / "build/buyers_stack.csv")

    ember = pd.read_csv(HERE / CFG["demand"]["ember"], low_memory=False)
    world = ember[(ember.Area == "World") & (ember.Category == "Electricity demand") & (ember.Unit == "TWh")
                  & (ember.Variable == "Demand")].set_index("Year").Value
    centres = pd.read_csv(HERE / "data/iea_regions.csv", comment="#").set_index("year").World
    tech = next(iter(GROUPS.values()))
    share = pd.DataFrame({
        TOTAL: wide[TOTAL],
        "All data centres": centres[centres.index <= years.max()],
        "Four tech companies": wide[tech].sum(axis=1, min_count=len(tech)),
        "Google and Microsoft": wide[CFG["buyers"]["hourly_goal"]].sum(axis=1, min_count=2),
    }).loc[years.min():years.max()].div(world, axis=0).dropna(how="all") * 100
    share.round(4).rename_axis("year").to_csv(HERE / "build/buyers_share.csv")
    line_colour = {TOTAL: ft.BLACK, "All data centres": ft.SLATE, "Four tech companies": ft.CLARET,
                   "Google and Microsoft": ft.OXFORD}

    fig = plt.figure(figsize=(11.2, 6.4), layout="none")
    grid = fig.add_gridspec(1, 2, width_ratios=[1.45, 1], left=0.05, right=0.815, top=0.845, bottom=0.095, wspace=0.50)
    a, c = fig.add_subplot(grid[0]), fig.add_subplot(grid[1])

    a.stackplot(years, stack.T.values, colors=[colour[k] for k in stack], edgecolor=ft.PAPER, linewidth=0.6)
    a.set_xlim(years.min(), years.max())
    a.set_ylim(0, 1.04 * stack.sum(axis=1).max())
    top = stack.cumsum(axis=1).iloc[-1]
    mid = top - stack.iloc[-1] / 2
    end_labels(a, years.max(), [(k, mid[k], None, False) for k in stack], 0.039, 0.50, size=8.5)
    a.yaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")

    for k in share:
        s = share[k].dropna()
        c.plot(s.index, s.values, color=line_colour[k], linewidth=2.3 if k == TOTAL else 1.9)
    c.set_xlim(years.min(), years.max())
    c.set_ylim(0, None)
    c.yaxis.set_major_locator(plt.MultipleLocator(0.5))
    c.yaxis.set_major_formatter(lambda v, _: f"{v:g}")
    last = share.loc[years.max()]
    end_labels(c, years.max(), [(f"{k}  {last[k]:.2f}", last[k], line_colour[k], k == TOTAL) for k in share],
               0.056, 0.30)

    for ax in (a, c):
        ax.set_xticks(range(int(years.min()), int(years.max()) + 1, 2))
        ax.set_xticks(range(int(years.min()), int(years.max()) + 1), minor=True)
        ax.tick_params(axis="x", which="minor", length=2, width=0.6)

    ft.heading(fig, a, "Corporate buyers' electricity use", "TWh a year, members of RE100")
    ft.heading(fig, c, "Share of world electricity demand", "%")
    ft.source(fig, a, "Sources: RE100; company reports; IEA; Ember")

    (HERE / "figures").mkdir(exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(HERE / f"figures/corporate_buyers.{ext}")

    named = stack.drop(columns=OTHER).sum(axis=1)
    print(pd.DataFrame({"named": named, "total": wide[TOTAL].loc[years], "named_pct": 100 * named / wide[TOTAL].loc[years]}).round(1))
    print(pd.DataFrame({g: stack[m].sum(axis=1) for g, m in GROUPS.items()}).round(1))


if __name__ == "__main__":
    main()
