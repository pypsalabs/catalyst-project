"""Experience curve for one technology: a single clean panel per component, made for slides.

Reads build/learning/<tech>.json (written by fit_learning.py; all values already in
the base currency/year) and draws, per component that has collected points: the
fitted points (filled, technology colour), the excluded points (hollow grey, the
legend says why each group is excluded), the level fit with its 95 % confidence
band, and one annotation with the inferred learning rate and its uncertainty.
Everything else (the three estimators in full, sources, floors, analogy
assumptions, diligence flags) lives in the README section of the technology.
Components without any collected point are not drawn; Schmidt's derived series
(a collected series divided by a constant C-rate) are not drawn either.

Also writes <tech>_sources.tex: the numbered sources of the legend as clickable
href links, one line, for the slide deck.

Run standalone:  python plot_learning.py vrfb
"""

import json
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import yaml  # noqa: E402
from matplotlib.legend_handler import HandlerTuple
from matplotlib.transforms import blended_transform_factory  # noqa: E402
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter  # noqa: E402

from common import grid  # noqa: E402
from common import save as _save  # noqa: E402

if "snakemake" in globals():
    CFG = snakemake.config
    FIT = Path(snakemake.input.fit)
    OUTPUTS = [Path(p) for p in snakemake.output]
else:
    _HERE = Path(__file__).resolve().parent
    CFG = yaml.safe_load((_HERE / "config.yaml").read_text())
    TECH = sys.argv[1] if len(sys.argv) > 1 else "vrfb"
    FIT = _HERE / "build" / "learning" / f"{TECH}.json"
    OUTPUTS = [_HERE / "figures" / "learning" / f"{TECH}.{fmt}" for fmt in CFG["plotting"]["formats"]]
OUTPUTS[0].parent.mkdir(parents=True, exist_ok=True)

fit = json.loads(FIT.read_text())
COLOUR = fit["colour"]
GREY = "0.45"
# marker colour by numbered source: [1] is the fitted series (technology colour), the rest a fixed list
SOURCE_COLOURS = ["#e08a2e", "#2a9d8f", "#8e6bbf", "#d1495b", "#4c9be8", "#b5a642", "#7f7f7f"]
# floors / reference bands / analogy lines are documented in the README and drawn only where the
# technology sets `show_reference: true` (EGS: the shale drilling cost Fervo converges towards)
REFERENCE_LINES = bool(CFG["learning"]["technologies"][fit["technology"]].get("show_reference", False))
MODEL_LINE = bool(CFG["learning"]["technologies"][fit["technology"]].get("show_model", False))
MARKER = {"system": "o", "pack": "s", "module": "D", "cell": "^", "plant": "o", "well": "o",
          "target": "v", "estimate": "^"}
Y_LABEL = {"energy": "Energy capacity cost", "power": "Power capacity cost", "plant": "Installed cost",
           "drilling": "Drilling cost"}
X_LABEL = {"wells": "Cumulative wells drilled", "units": "Cumulative units"}


def unit_label(unit, sub):
    """Attach the carrier subscript to the energy/power part of a unit string:
    "USD2024/kWh" -> "USD2024/kWh$_{\\mathrm{el}}$", "GW" -> "GW$_{\\mathrm{el}}$"; wells, ft, units are left alone."""
    if not sub:
        return unit
    return re.sub(r"(?<![A-Za-z])([kMG]?Wh?)(?![A-Za-z])", lambda m: f"{m.group(1)}$_{{\\mathrm{{{sub}}}}}$", str(unit))
plt.rcParams.update({"font.size": 10, "axes.labelsize": 10, "xtick.labelsize": 9, "ytick.labelsize": 9,
                     "legend.fontsize": 8.5})


def pct(v):
    return f"{v * 100:.0f} %"


def log_axis(ax, which):
    ax.set_xscale("log") if which == "x" else ax.set_yscale("log")
    axis = ax.xaxis if which == "x" else ax.yaxis
    axis.set_major_locator(LogLocator(base=10, subs=(1.0,), numticks=14))
    axis.set_minor_locator(LogLocator(base=10, subs=(2.0, 5.0), numticks=14))
    axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}" if v < 1 else f"{v:,.0f}"))
    axis.set_minor_formatter(NullFormatter())


def label_minor_if_narrow(ax):
    for axis, (lo, hi) in ((ax.xaxis, ax.get_xlim()), (ax.yaxis, ax.get_ylim())):
        if np.log10(hi / lo) < 2.0:
            axis.set_minor_formatter(FuncFormatter(lambda v, _: f"{v:g}" if v < 1 else f"{v:,.0f}"))


def rate_text(comp):
    """The one annotation: inferred learning rate with its uncertainty, or why there is none."""
    s, lv = comp["summary"], comp["level"]
    if not lv:
        return "no learning rate derivable"        # the legend says why the points do not qualify
    if lv.get("lr_lo") is None:
        return f"learning rate {pct(lv['lr'])} per doubling\nline through {s['n']} points, no uncertainty"
    span = f"{s['year_min']}–{s['year_max']}" if s["year_min"] else ""
    return (f"learning rate {pct(lv['lr'])} per doubling\n"
            f"95 % confidence interval {pct(lv['lr_lo'])} to {pct(lv['lr_hi'])}\n"
            f"n = {s['n']}, {s['doublings']:.1f} doublings, {span}")


def source_colour(n):
    return COLOUR if n == 1 else SOURCE_COLOURS[(n - 2) % len(SOURCE_COLOURS)]


def draw_curve(ax, comp):
    pts = [p for p in comp["points"] if not p["derived"]]
    z = np.array([p["z"] for p in pts]); c = np.array([p["c"] for p in pts])
    handles = []
    # excluded points: hollow, coloured by source, one legend entry per reason; when several sources
    # share one reason the entry shows all their markers side by side ("excluded [2-4]: ...")
    groups = {}
    for p in pts:
        if not p["in_fit"] and p["source"] not in groups.setdefault(p["reason"], []):
            groups[p["reason"]].append(p["source"])
    for reason, srcs in groups.items():
        hs = []
        for src in srcs:
            sel = [p for p in pts if not p["in_fit"] and p["reason"] == reason and p["source"] == src]
            scope = sel[0]["scope"]
            hs.append(ax.scatter([p["z"] for p in sel], [p["c"] for p in sel], marker=MARKER.get(scope, "o"), s=26,
                                 facecolors="none", edgecolors=source_colour(src), linewidths=1.0, zorder=3))
        consecutive = srcs == list(range(srcs[0], srcs[-1] + 1))
        nums = f"{srcs[0]}–{srcs[-1]}" if len(srcs) > 1 and consecutive else ", ".join(map(str, srcs))
        handles.append((tuple(hs) if len(hs) > 1 else hs[0], f"excluded [{nums}]: {reason}"))
    # fitted points: filled, coloured by source (the fitted series is always source [1])
    fit_pts = [p for p in pts if p["in_fit"]]
    for src in dict.fromkeys(p["source"] for p in fit_pts):
        sel = [p for p in fit_pts if p["source"] == src]
        scope = sel[0]["scope"]
        h = ax.scatter([p["z"] for p in sel], [p["c"] for p in sel], marker=MARKER.get(scope, "o"), s=36,
                       color=source_colour(src), edgecolors="white", linewidths=0.6, zorder=5)
        handles.append((h, f"fitted [{src}] (n = {len(sel)})"))
    lv = comp["level"]
    if lv and lv.get("band"):
        g = np.exp(np.array(lv["band"]["logz"]))
        ax.fill_between(g, np.exp(lv["band"]["lo"]), np.exp(lv["band"]["hi"]), color=COLOUR, alpha=0.13,
                        linewidth=0, zorder=2)
        ax.plot(g, np.exp(lv["a"]) * g ** (-lv["b"]), color=COLOUR, linewidth=1.6, zorder=4)
    elif lv:                                            # two points: line without a band
        g = np.array([z.min() / 1.5, z.max() * 1.5])
        ax.plot(g, np.exp(lv["a"]) * g ** (-lv["b"]), color=COLOUR, linewidth=1.4, zorder=4)
    for sec in comp.get("secondary") or []:               # own fit of an excluded series: thin line, no band
        lv2 = sec["level"]
        g = np.array([sec["z_min"] / 1.3, sec["z_max"] * 1.3])
        h, = ax.plot(g, np.exp(lv2["a"]) * g ** (-lv2["b"]), color=source_colour(sec["source"]), linewidth=1.2,
                     linestyle=(0, (5, 2)), zorder=4)
        ci = (f", {lv2['lr_lo']*100:.0f}–{lv2['lr_hi']*100:.0f} %" if lv2.get("lr_lo") is not None else "")
        handles.append((h, f"fit of [{sec['source']}] alone: {lv2['lr']*100:.0f} % per doubling{ci}"))
    if MODEL_LINE and comp.get("model"):            # the line here, its label once the axis limits are set
        ax.axhline(comp["model"]["c"], color="#c0392b", linestyle=(0, (5, 3)), linewidth=1.2, zorder=6)
    if REFERENCE_LINES and comp["floor"]:
        f = comp["floor"]
        short = f.get("label") or f.get("kind", "floor")
        if f.get("value_hi"):
            h = ax.axhspan(f["value"], f["value_hi"], color="0.25", alpha=0.12, linewidth=0, zorder=1)
            handles.append((h, f"{short}: {f['value']:,.0f}–{f['value_hi']:,.0f} {comp['unit']}"))
        else:
            h = ax.axhline(f["value"], color="0.25", linestyle=":", linewidth=1.0, zorder=3)
            handles.append((h, f"{short}: {f['value']:,.0f} {comp['unit']}"))
    if REFERENCE_LINES and comp["analogy"] and pts:
        an = comp["analogy"]
        p0 = max(pts, key=lambda p: (p["year"] or 0, p["z"]))
        g = np.array([p0["z"], p0["z"] * 32])
        ax.plot(g, p0["c"] * (g / p0["z"]) ** (-an["b"]), color="0.35", linestyle=(0, (4, 3)), linewidth=1.0, zorder=3)
    # year labels: first and last fitted point (or all points when nothing is fitted) and, if it is
    # newer, the most recent excluded point, so the time span of the sample is visible
    lab = fit_pts or pts
    targets = [(lab[0], -8), (lab[-1], 8)] if lab else []
    excl = [p for p in pts if not p["in_fit"] and p["year"]]
    if excl and fit_pts:
        newest = max(excl, key=lambda p: (p["year"], p["z"]))
        if newest["year"] > (lab[-1]["year"] or 0):
            targets.append((newest, -8))
    for p, dx in targets:
        if p["year"]:
            ax.annotate(str(p["year"]), (p["z"], p["c"]), xytext=(dx, 6), textcoords="offset points", fontsize=8,
                        color="0.3", ha="right" if dx < 0 else "left", in_layout=False)
    log_axis(ax, "x"); log_axis(ax, "y")
    grid(ax, log=True, axis="both")
    if len(z):
        ax.set_xlim(z.min() / 2.5, z.max() * 2.5)
        ymin = min(c.min(), comp["floor"]["value"]) if REFERENCE_LINES and comp["floor"] else c.min()
        if MODEL_LINE and comp.get("model"):            # room for the rate box below a baseline line
            ymin = min(ymin, comp["model"]["c"] / (1.5 if comp["model"].get("z") else 2.5))
        ymax = max(c.max(), comp["model"]["c"]) if MODEL_LINE and comp.get("model") else c.max()
        ax.set_ylim(ymin / 1.8, ymax * 1.8)
    else:
        ax.text(0.5, 0.5, "no cost-vs-capacity data collected", transform=ax.transAxes, ha="center", va="center",
                fontsize=9, color="0.4", style="italic")
    label_minor_if_narrow(ax)
    if MODEL_LINE and comp.get("model"):
        # label the line where no point sits near it: one line at the right, the middle or the left, else
        # two lines just above it. The rate box (lower left) blocks the left when the line runs through it
        m = comp["model"]
        where = (f"at {m['z']:,.3g} {comp['capacity_unit']} ({m['year']})" if m.get("z")
                 else f"(cost baseline {m['year']})")
        text = f"model start: {m['c']:,.0f} {comp['unit']} {where}"
        if m.get("add"):                            # fit plus a fixed add-on: three short lines whose rounded
            fit_r, add_r = round(m["c_fit"]), round(m["add"]["value"])   # parts sum to the printed total
            text = (f"model start: {fit_r + add_r:,.0f} {comp['unit']}\nfit {fit_r:,.0f} {where}"
                    f"\n+ {add_r:,.0f} {m['add']['label']}")
        spec = CFG["learning"]["technologies"][fit["technology"]]
        loc = spec.get("model_label")               # explicit placement, e.g. "lower left" (per component if a mapping)
        if isinstance(loc, dict):
            loc = loc.get(comp["component"])
        xl, yl = np.log(np.array(ax.get_xlim())), np.log(np.array(ax.get_ylim()))
        near = [(np.log(p["z"]) - xl[0]) / (xl[1] - xl[0]) for p in pts
                if p["z"] and abs(np.log(p["c"] / m["c"])) < 0.2]
        in_box = (np.log(m["c"]) - yl[0]) / (yl[1] - yl[0]) < 0.3
        def clearance(iv):
            return min([0.0 if iv[0] <= x <= iv[1] else min(abs(x - iv[0]), abs(x - iv[1])) for x in near] or [1.0])
        # candidates: (ha, x, occupied interval), one-line label ~0.46 of the axes width, two lines ~0.28
        one = {"right": ("right", 0.985, (0.525, 0.985)), "mid": ("left", 0.47, (0.47, 0.93))} if in_box else \
              {"right": ("right", 0.985, (0.525, 0.985)), "center": ("center", 0.5, (0.27, 0.73)),
               "left": ("left", 0.02, (0.02, 0.48))}
        two = {"right": ("right", 0.985, (0.705, 0.985)), "mid": ("left", 0.47, (0.47, 0.75))} if in_box else \
              {"right": ("right", 0.985, (0.705, 0.985)), "center": ("center", 0.5, (0.36, 0.64)),
               "left": ("left", 0.02, (0.02, 0.30))}
        best = max(one, key=lambda k: (clearance(one[k][2]), k == "right"))
        if loc:
            v, h = loc.split()
            ha, x, va = h, {"left": 0.02, "center": 0.5, "right": 0.985}[h], {"lower": "top", "upper": "bottom"}[v]
        elif clearance(one[best][2]) > 0.03 and not m.get("add"):   # a slot counts as free with a small margin
            ha, x, va = one[best][0], one[best][1], "center"
        else:
            if not m.get("add"):
                text = text.replace(" at ", "\nat ").replace(" (cost", "\n(cost")
            best = max(two, key=lambda k: (clearance(two[k][2]), k == "right"))
            ha, x, va = two[best][0], two[best][1], "bottom"
        ax.text(x, m["c"], text, transform=blended_transform_factory(ax.transAxes, ax.transData),
                color="#c0392b", fontsize=8, ha=ha, va=va, linespacing=1.3, zorder=7,
                bbox=dict(facecolor="white", edgecolor="none", pad=1.5))
    spec = CFG["learning"]["technologies"][fit["technology"]]
    sub = spec.get("unit_subscript", "el")            # carrier the kW / kWh refer to; per component if a mapping
    if isinstance(sub, dict):
        sub = sub.get(comp["component"], "el")
    ax.set_xlabel(f"{X_LABEL.get(comp['capacity_unit'], 'Cumulative installed capacity')} "
                  f"[{unit_label(comp['capacity_unit'], sub)}]")
    ylab = spec.get("ylabel") or Y_LABEL.get(comp["component"], "Unit cost")
    ax.set_ylabel(f"{ylab} [{unit_label(comp['unit'], sub)}]")
    # with a model-start line the legend moves to the empty upper right and the rate box to the lower
    # left below the line, so neither crosses it
    swap = MODEL_LINE and comp.get("model") is not None
    ax.text(*((0.025, 0.045) if swap else (0.975, 0.955)), rate_text(comp), transform=ax.transAxes,
            ha="left" if swap else "right", va="bottom" if swap else "top", fontsize=9.5,
            linespacing=1.4, color="0.15" if lv else "0.35", in_layout=False, zorder=8,
            bbox=dict(boxstyle="round,pad=0.35", facecolor="white", edgecolor="0.8", linewidth=0.6))
    if handles and spec.get("legend", True):      # `legend: false` drops the legend (the slide text explains the points)
        widest = max(len(h) if isinstance(h, tuple) else 1 for h, _ in handles)
        ax.legend([h for h, _ in handles], [l for _, l in handles], frameon=True, framealpha=0.9, edgecolor="none",
                  loc=spec.get("legend_loc") or ("upper right" if swap else "lower left" if fit_pts else "best"),
                  handlelength=1.6 * widest, borderaxespad=0.4,
                  handler_map={tuple: HandlerTuple(ndivide=None, pad=0.3)})


def tex_escape(t):
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
                 ("_", r"\_"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\^{}")):
        t = t.replace(a, b)
    return t


def sources_tex(comps):
    """One LaTeX line for the slide: href{url}{[n]} short citation for every source in the legend."""
    seen = {}
    for comp in comps:
        for src in comp["summary"]["sources"]:
            seen.setdefault(src["n"], src)
    parts = []
    for n, src in sorted(seen.items()):
        link = f"\\href{{{src['url']}}}{{[{n}]}}" if src["url"] and src["url"] != "nan" else f"[{n}]"
        parts.append(f"{link}~{tex_escape(src['citation'])}")
    return "% generated by plot_learning.py; numbers match the figure legend\n" + "\\quad\n".join(parts) + "\n"


comps = [c for c in fit["components"] if any(not p["derived"] for p in c["points"])] or fit["components"][:1]
figure, axes = plt.subplots(len(comps), 1, figsize=(7.2, 3.9 * len(comps)), layout="constrained", squeeze=False)
for ax, comp in zip(axes[:, 0], comps):
    draw_curve(ax, comp)
_save(figure, [o for o in OUTPUTS if o.suffix != ".tex"], CFG["plotting"]["dpi"])
tex = [o for o in OUTPUTS if o.suffix == ".tex"] or [OUTPUTS[0].with_name(OUTPUTS[0].stem + "_sources.tex")]
tex[0].write_text(sources_tex(comps))
