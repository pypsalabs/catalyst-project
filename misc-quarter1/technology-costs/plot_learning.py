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
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import yaml  # noqa: E402
from matplotlib.legend_handler import HandlerTuple  # noqa: E402
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
MARKER = {"system": "o", "pack": "s", "module": "D", "cell": "^", "plant": "o", "well": "o",
          "target": "v", "estimate": "^"}
Y_LABEL = {"energy": "Energy capacity cost", "power": "Power capacity cost", "plant": "Installed cost",
           "drilling": "Drilling cost"}
X_LABEL = {"wells": "Cumulative wells drilled", "units": "Cumulative units"}
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
        return f"LR = {pct(lv['lr'])} per doubling\nline through {s['n']} points, no uncertainty"
    span = f"{s['year_min']}–{s['year_max']}" if s["year_min"] else ""
    return (f"LR = {pct(lv['lr'])} per doubling\n"
            f"95 % CI {pct(lv['lr_lo'])} to {pct(lv['lr_hi'])}\n"
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
        ax.set_ylim(ymin / 1.8, c.max() * 1.8)
    else:
        ax.text(0.5, 0.5, "no cost-vs-capacity data collected", transform=ax.transAxes, ha="center", va="center",
                fontsize=9, color="0.4", style="italic")
    label_minor_if_narrow(ax)
    ax.set_xlabel(f"{X_LABEL.get(comp['capacity_unit'], 'Cumulative installed capacity')} [{comp['capacity_unit']}]")
    ax.set_ylabel(f"{Y_LABEL.get(comp['component'], 'Unit cost')} [{comp['unit']}]")
    ax.text(0.975, 0.955, rate_text(comp), transform=ax.transAxes, ha="right", va="top", fontsize=9.5,
            linespacing=1.4, color="0.15" if lv else "0.35", in_layout=False,
            bbox=dict(boxstyle="round,pad=0.35", facecolor="white", edgecolor="0.8", linewidth=0.6))
    if handles:
        widest = max(len(h) if isinstance(h, tuple) else 1 for h, _ in handles)
        ax.legend([h for h, _ in handles], [l for _, l in handles], frameon=False,
                  loc="lower left" if fit_pts else "best", handlelength=1.6 * widest, borderaxespad=0.4,
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
