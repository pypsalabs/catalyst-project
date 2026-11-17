"""Stacked-area charts of the supplier pipelines, one per advanced technology, plus an overview grid.

Stacking is by layer first (operating at the bottom, then construction, announced, stated targets), and by
company within each layer, so the height of each layer boundary reads as "how much exists / is being built /
is announced / is promised by year X". The company is the colour (six largest by 2040 envelope, the rest in
one steel band), the layer is the fill: solid / light with hatching / pale with dots / outline hatching.
The panel right of each chart lists the companies with their main continent and the 2040 envelope, and a bar
of that envelope split by continent.

    python scripts/plot_pipeline.py            (from misc-quarter1/technology-suppliers; after build_pipeline.py)
"""
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from matplotlib.colors import to_rgb
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(next(p for p in HERE.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import iconstyle as ic  # noqa: E402

LAYERS = ["operating", "construction", "announced", "target"]
LAYER_LABEL = {"operating": "operating", "construction": "under construction",
               "announced": "announced", "target": "stated targets", "factory": "factory ceiling (total)"}
REST = "Rest of suppliers"
# the six icon accents plus rose and brown: the user asked for one colour per company, so these charts go
# beyond the icon style's six-colour rule (config top_n)
PALETTE = ic.CATEGORICAL + ["#c4569a", "#8a5a2b"]
# continents in ink and steel tones so they never compete with the company colours; code printed on top
CONT_COLOR = {"NAM": ic.INK, "EUR": ic.MUTED, "ASI": ic.STEEL, "SAM": ic.STEEL_L, "OCE": ic.PALE, "AFR": "#ffffff"}
CONT_TEXT = {"NAM": "white", "EUR": "white"}


def blend(c, w):
    """Mix colour c with white; w = share of white."""
    r = np.array(to_rgb(c))
    return tuple(r * (1 - w) + w)


def layer_style(color, layer):
    if layer == "operating":
        return dict(facecolor=color, hatch=None, hatchcolor=color)
    if layer == "construction":
        return dict(facecolor=blend(color, 0.45), hatch="////", hatchcolor=color)
    if layer == "announced":
        return dict(facecolor=blend(color, 0.8), hatch="..", hatchcolor=color)
    return dict(facecolor="white", hatch="\\\\\\\\", hatchcolor=blend(color, 0.35))


def prepare(df, tech, top_n):
    d = df[df.technology == tech].copy()
    # companies without any area (only a stated factory) carry no colour: they fold into the rest
    area = d[d.layer != "factory"].groupby("company").mw.sum()
    d.loc[d.company.map(area).fillna(0).le(0), "rank"] = 10_000
    d.loc[d["rank"] > top_n, "company"] = REST
    d.loc[d.company == REST, "continent"] = "mixed"
    order = (d[d.company != REST].drop_duplicates("company").sort_values("rank").company.tolist()
             + ([REST] if (d.company == REST).any() else []))
    colors = dict(zip(order, PALETTE))
    colors[REST] = ic.STEEL_L
    piv = d.groupby(["layer", "company", "year"]).mw.sum().unstack("year").fillna(0)
    cont = d.drop_duplicates("company").set_index("company").continent.to_dict()
    return piv, order, colors, cont


def unit_for(piv):
    top = piv.groupby(level="layer").sum().sum().max()
    return (1e3, "GW") if top >= 1000 else (1.0, "MW")


def draw_main(ax, piv, order, colors, cfg, scale, unit, spec, duration, compact=False):
    years = piv.columns.values.astype(float)
    y0, y1 = cfg["years"]
    ax.set_xlim(y0, y1)
    stack = piv.drop(index="factory", level="layer", errors="ignore")
    total = stack.sum().values / scale
    ceiling = piv.sum().values / scale          # stack + factories at nameplate
    top = max(total.max() * 1.1, 1e-6)
    clipped = ceiling.max() > 1.8 * top
    ax.set_ylim(0, top if clipped else max(top, ceiling.max() * 1.06))
    base = np.zeros(len(years))
    plt.rcParams["hatch.linewidth"] = 0.55
    for li, layer in enumerate(LAYERS):
        for comp in order:
            if (layer, comp) not in piv.index:
                continue
            v = piv.loc[(layer, comp)].values / scale
            if not v.any():
                continue
            top = base + v
            st = layer_style(colors[comp], layer)
            ax.fill_between(years, base, top, facecolor=st["facecolor"], hatch=st["hatch"],
                            hatchcolor=st["hatchcolor"], edgecolor="none", lw=0, zorder=2)
            ax.plot(years, top, color=ic.INK, lw=ic.SEAM * 0.8, zorder=2.5)
            base = top
        # layer boundary: a heavier ink line
        ax.plot(years, base, color=ic.INK, lw=ic.MARK if li < 3 else ic.OUTLINE, zorder=2.6,
                ls="-" if li < 3 else (0, (3, 1.5)))
    notes = []
    if (ceiling > total + 1e-9).any():
        ax.plot(years, ceiling, color=ic.INK, lw=1.1, ls=(0, (1, 1.6)), zorder=2.7, clip_on=True)
        ylim = ax.get_ylim()[1]
        msg = f"stated factory capacity at nameplate: {cap(ceiling[-1] * scale)} by {int(years[-1])}"
        if clipped:
            msg += " (line leaves the chart)"
        notes.append(msg)
    today = cfg["today"]
    ax.axvline(today + 0.5, color=ic.MUTED, lw=0.8, ls=(0, (2, 2)), zorder=3)
    ax.annotate("today", (today + 0.5, 0), xycoords=("data", "axes fraction"), xytext=(-3, 6),
                textcoords="offset points", ha="right", va="bottom", fontsize=6.8, color=ic.MUTED, zorder=5,
                bbox=dict(fc="white", ec="none", pad=0.8))
    title = f"{spec['label']}, cumulative {unit}"
    if spec.get("storage"):
        title += f" (right: {'G' if unit == 'GW' else 'M'}Wh at {duration:.0f} h)"
        sec = ax.secondary_yaxis("right", functions=(lambda x: x * duration, lambda x: x / duration))
        sec.tick_params(length=0, labelsize=7, labelcolor=ic.MUTED)
        sec.spines["right"].set_visible(False)
    ax.set_title(title, loc="left", fontsize=8.6 if compact else None)
    ic.ground(ax)
    return notes


def layer_key(ax, compact=False):
    handles = []
    for layer in LAYERS:
        st = layer_style(ic.STEEL if layer != "operating" else ic.STEEL, layer)
        handles.append(Patch(facecolor=st["facecolor"], hatch=st["hatch"], edgecolor=ic.INK,
                             linewidth=ic.MARK * 0.8, label=LAYER_LABEL[layer]))
    handles.append(Line2D([], [], color=ic.INK, lw=1.1, ls=(0, (1, 1.6)), label="stated factory capacity"))
    return handles


def short(name, n=30):
    return name if len(name) <= n else name[:n - 1].rstrip() + "…"


def cap(mw):
    """Capacity in readable units: GW above 1 GW, MW below."""
    if mw >= 1000:
        return f"{mw / 1e3:,.1f} GW"
    return f"{mw:,.0f} MW" if mw >= 1 else f"{mw:,.1f} MW"


def totals_block(ax, piv, y_top, cfg):
    """Layer totals (cumulative MW of each layer) at today, 2030 and 2040, under the company list."""
    years = [cfg["today"], 2030, cfg["years"][1]]
    lay = piv.groupby(level="layer").sum()
    stack = lay.drop(index="factory", errors="ignore").sum()
    if "factory" in lay.index:
        lay.loc["factory"] = stack + lay.loc["factory"]
    ax.text(0, y_top, "Cumulative, by layer", fontsize=7.2, color=ic.MUTED, va="bottom")
    for j, y in enumerate(years):
        ax.text(0.52 + 0.24 * j, y_top, str(y), fontsize=7.2, color=ic.MUTED, va="bottom", ha="right")
    rows = LAYERS + (["factory"] if "factory" in lay.index and lay.loc["factory"].max() > stack.max() + 1e-6 else [])
    for i, layer in enumerate(rows):
        yy = y_top - 0.05 * (i + 1)
        ax.text(0, yy, LAYER_LABEL[layer], fontsize=7, color=ic.INK, va="bottom")
        for j, y in enumerate(years):
            v = lay.loc[layer, y] if layer in lay.index else 0
            ax.text(0.52 + 0.24 * j, yy, cap(v) if v > 0 else "–", fontsize=7, color=ic.INK, va="bottom",
                    ha="right")


def company_panel(ax, order, colors, cont, piv, cfg):
    """Company list with main-market tag and 2040 envelope, continent bar of that envelope, layer totals."""
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    y1 = cfg["years"][1]
    stack = piv.drop(index="factory", level="layer", errors="ignore")
    tot = {c: stack.xs(c, level="company")[y1].sum() if c in stack.index.get_level_values("company") else 0
           for c in order}
    step = 0.052
    ax.text(0, 1.0, "Supplier", fontsize=7.2, color=ic.MUTED, va="top")
    ax.text(0.66, 1.0, "market", fontsize=7.2, color=ic.MUTED, va="top", ha="center")
    ax.text(1.0, 1.0, f"by {y1}", fontsize=7.2, color=ic.MUTED, va="top", ha="right")
    for i, c in enumerate(order):
        y = 0.93 - i * step
        ax.add_patch(Rectangle((0, y - 0.019), 0.04, 0.038, facecolor=colors[c], edgecolor=ic.INK, lw=ic.MARK))
        name = short(c, 27)
        ax.text(0.06, y, name, va="center", fontsize=7.2, color=ic.INK)
        code = cont.get(c, "?")
        if code in CONT_COLOR:
            ax.add_patch(Rectangle((0.61, y - 0.022), 0.10, 0.044, facecolor=CONT_COLOR[code], edgecolor=ic.INK,
                                   lw=ic.SEAM))
            ax.text(0.66, y, code, va="center", ha="center", fontsize=6.2, color=CONT_TEXT.get(code, ic.INK),
                    fontweight=ic.EMPH)
        else:
            ax.text(0.66, y, "mixed" if c == REST else "n/a", va="center", ha="center", fontsize=6.2, color=ic.MUTED)
        ax.text(1.0, y, cap(tot[c]), va="center", ha="right", fontsize=7.2, color=ic.INK)
    # continent bar of the 2040 envelope
    yb = 0.93 - len(order) * step - 0.06
    ax.text(0, yb + 0.03, f"{y1} incl. targets by main market", fontsize=7.2, color=ic.MUTED, va="bottom")
    share = {}
    for c in order:
        code = cont.get(c) if cont.get(c) in CONT_COLOR else "mixed"
        share[code] = share.get(code, 0) + tot[c]
    s = sum(share.values()) or 1
    x = 0
    for code in list(CONT_COLOR) + ["mixed"]:
        w = share.get(code, 0) / s
        if w <= 0:
            continue
        ax.add_patch(Rectangle((x, yb - 0.025), w, 0.05, facecolor=CONT_COLOR.get(code, "white"), edgecolor=ic.INK,
                               lw=ic.MARK, hatch="xx" if code == "mixed" else None))
        if w > 0.035 * len(code):
            ax.text(x + w / 2, yb, code, ha="center", va="center", fontsize=6.2,
                    color=CONT_TEXT.get(code, ic.INK), fontweight=ic.EMPH,
                    bbox=dict(fc="white", ec="none", pad=0.6) if code == "mixed" else None)
        x += w
    ax.text(0, yb - 0.045, "NAM N. America · EUR Europe incl. Russia · ASI Asia\n"
            "SAM S. America · OCE Oceania · AFR Africa · market = where its MW go", fontsize=5.8,
            color=ic.MUTED, va="top", linespacing=1.4)
    totals_block(ax, piv, yb - 0.17, cfg)


def write_notes(ax, notes, comp_table, tech):
    """Top-left notes: what the area does not show (undated announcements and targets, the factory line)."""
    ct = comp_table[comp_table.technology == tech]
    u = ct.undated_mw.sum()
    if u >= 0.5:
        notes = [f"+ {cap(u)} announced without an online year (not drawn)"] + notes
    t = ct.undated_target_max_mw.fillna(0)
    if t.sum() >= 0.5:
        who = ", ".join(f"{c} {cap(v)}" for c, v in zip(ct.company, t) if v >= 0.5)
        notes.append(f"undated targets, not drawn: {who}")
    for i, n in enumerate(notes):
        ax.annotate(n, (0.01, 0.975 - 0.065 * i), xycoords="axes fraction", va="top", fontsize=6.5,
                    color=ic.MUTED, zorder=6, bbox=dict(fc="white", ec="none", pad=0.6, alpha=0.9))


def main():
    with open(HERE / "config.yaml") as f:
        cfg = yaml.safe_load(f)
    ic.use()
    df = pd.read_csv(HERE / "build/pipeline.csv")
    ct = pd.read_csv(HERE / "build/companies.csv")
    summ = pd.read_csv(HERE / "build/summary.csv")
    dur = summ.drop_duplicates("technology").set_index("technology").duration_h.to_dict()
    (HERE / "figures").mkdir(exist_ok=True)
    techs = cfg["technologies"]

    for tech, spec in techs.items():
        if not (df.technology == tech).any():
            print(f"{tech}: no data, skipped", file=sys.stderr)
            continue
        piv, order, colors, cont = prepare(df, tech, cfg["top_n"])
        scale, unit = unit_for(piv)
        fig = plt.figure(figsize=(8.8, 5.0))
        ax = fig.add_axes([0.065, 0.09, 0.56, 0.78])
        axp = fig.add_axes([0.695, 0.02, 0.29, 0.875])
        notes = draw_main(ax, piv, order, colors, cfg, scale, unit, spec, dur.get(tech))
        write_notes(ax, notes, ct, tech)
        fig.legend(handles=layer_key(ax), loc="upper left", bbox_to_anchor=(0.065, 0.995), ncol=5,
                   fontsize=7.2, handlelength=1.6, handleheight=1.0, columnspacing=1.2, frameon=False)
        company_panel(axp, order, colors, cont, piv, cfg)
        for ext in ("png", "pdf"):
            fig.savefig(HERE / f"figures/{tech}.{ext}", dpi=200)
        plt.close(fig)

    # overview grid
    fig, axes = plt.subplots(2, 3, figsize=(19, 8.2))
    fig.subplots_adjust(left=0.03, right=0.905, top=0.875, bottom=0.06, wspace=0.78, hspace=0.42)
    for ax, (tech, spec) in zip(axes.flat, techs.items()):
        if not (df.technology == tech).any():
            ax.set_axis_off()
            continue
        piv, order, colors, cont = prepare(df, tech, cfg["top_n"])
        scale, unit = unit_for(piv)
        draw_main(ax, piv, order, colors, cfg, scale, unit, spec, dur.get(tech), compact=True)
        handles = [Patch(facecolor=colors[c], edgecolor=ic.INK, linewidth=ic.MARK,
                         label=f"{short(c)} · {cont.get(c) if cont.get(c) in CONT_COLOR else 'mixed'}")
                   for c in order]
        ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.09 if spec.get("storage") else 1.02, 1.0),
                  fontsize=6.6, frameon=False, handlelength=1.0, handleheight=0.9, borderaxespad=0,
                  labelspacing=0.35)
    fig.legend(handles=layer_key(None), loc="upper left", bbox_to_anchor=(0.04, 0.985), ncol=5, fontsize=8,
               handlelength=1.8, handleheight=1.1, columnspacing=1.4, frameon=False)
    fig.text(0.97, 0.975, "colour = company · fill = status · code = main market "
             "(NAM, EUR, ASI, SAM, OCE, AFR)", ha="right", va="top", fontsize=7.6, color=ic.MUTED)
    for ext in ("png", "pdf"):
        fig.savefig(HERE / f"figures/overview.{ext}", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    main()
