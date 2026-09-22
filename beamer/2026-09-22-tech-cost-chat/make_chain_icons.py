"""LDES chain icon for the hydrogen-store slides, reproduced from the Claude Design project
"LDES Chain Icon" (https://claude.ai/design/p/d21fd8a5-0481-41d6-8897-e5e10f682800): three stages
in a row, electrolysis -> storage (salt cavern / pressure tank) -> SOFC, black line icons with
uppercase Space Grotesk labels and a red dashed frame around the highlighted stage. The SVG path
data and layout are copied from `LDES Chain Icon.dc.html`; matplotlib renders them because no SVG
converter is installed. Writes ldes-chain-{charging,storage,discharging}.pdf (+ png for checks).
Run:  python make_chain_icons.py
"""
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import PathPatch, Rectangle, Circle, FancyBboxPatch
from matplotlib.path import Path as MPath

HERE = Path(__file__).resolve().parent
FONT = FontProperties(fname=HERE / "SpaceGrotesk-Medium.ttf")
BLACK, RED, ARROW = "#000000", "#D8232A", "#c9c9c4"


def svg_path(d):
    """Minimal SVG path parser: M m L l H h V v C c S s Z z (absolute and relative)."""
    tokens = re.findall(r"[MmLlHhVvCcSsZz]|-?\d*\.?\d+(?:e-?\d+)?", d)
    verts, codes = [], []
    i, cmd, cur, start, last_c2 = 0, None, (0.0, 0.0), (0.0, 0.0), None
    def num():
        nonlocal i
        v = float(tokens[i]); i += 1; return v
    while i < len(tokens):
        if re.match(r"[A-Za-z]", tokens[i]):
            cmd = tokens[i]; i += 1
            if cmd in "Zz":
                verts.append(start); codes.append(MPath.CLOSEPOLY); cur = start; last_c2 = None
                continue
        rel = cmd.islower()
        if cmd in "Mm":
            x, y = num(), num()
            if rel: x, y = cur[0] + x, cur[1] + y
            verts.append((x, y)); codes.append(MPath.MOVETO); cur = start = (x, y); last_c2 = None
            cmd = "l" if rel else "L"                      # subsequent pairs are line-tos
        elif cmd in "Ll":
            x, y = num(), num()
            if rel: x, y = cur[0] + x, cur[1] + y
            verts.append((x, y)); codes.append(MPath.LINETO); cur = (x, y); last_c2 = None
        elif cmd in "Hh":
            x = num(); x = cur[0] + x if rel else x
            verts.append((x, cur[1])); codes.append(MPath.LINETO); cur = (x, cur[1]); last_c2 = None
        elif cmd in "Vv":
            y = num(); y = cur[1] + y if rel else y
            verts.append((cur[0], y)); codes.append(MPath.LINETO); cur = (cur[0], y); last_c2 = None
        elif cmd in "CcSs":
            if cmd in "Cc":
                x1, y1, x2, y2, x, y = (num() for _ in range(6))
                if rel: x1, y1, x2, y2, x, y = (cur[0] + x1, cur[1] + y1, cur[0] + x2, cur[1] + y2, cur[0] + x, cur[1] + y)
            else:
                x2, y2, x, y = (num() for _ in range(4))
                if rel: x2, y2, x, y = cur[0] + x2, cur[1] + y2, cur[0] + x, cur[1] + y
                x1, y1 = (2 * cur[0] - last_c2[0], 2 * cur[1] - last_c2[1]) if last_c2 else cur
            verts += [(x1, y1), (x2, y2), (x, y)]; codes += [MPath.CURVE4] * 3
            cur, last_c2 = (x, y), (x2, y2)
    return MPath(verts, codes)


def draw_icon(ax, x0, y0, size, paths, rects=(), circles=(), lw=2.2, dashes=None):
    """Draw a 64x64 viewBox icon at (x0, y0) top-left in canvas px, scaled to `size` px."""
    k = size / 64
    tf = matplotlib.transforms.Affine2D().scale(k, k).translate(x0, y0) + ax.transData
    for d, dash in paths:
        ax.add_patch(PathPatch(svg_path(d), transform=tf, fill=False, edgecolor=BLACK, linewidth=lw * k * PT,
                               capstyle="round", joinstyle="round", linestyle=dash or "solid"))
    for (x, y, w, h, r) in rects:
        if r:
            ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", transform=tf,
                                        fill=False, edgecolor=BLACK, linewidth=lw * k * PT))
        else:
            ax.add_patch(Rectangle((x, y), w, h, transform=tf, fill=False, edgecolor=BLACK, linewidth=lw * k * PT))
    for (cx, cy, r) in circles:
        ax.add_patch(Circle((cx, cy), r, transform=tf, fill=False, edgecolor=BLACK, linewidth=lw * k * PT))


def label(ax, x, y, text, size=9.5, spacing=" "):
    ax.text(x, y, spacing.join(text.upper()), fontproperties=FONT, fontsize=size * PT, ha="center", va="top",
            color=BLACK, linespacing=1.35)


def arrow(ax, x, y):
    ax.plot([x, x + 20], [y, y], color=ARROW, lw=1.4 * PT, solid_capstyle="round")
    ax.plot([x + 17, x + 20, x + 17], [y - 3, y, y + 3], color=ARROW, lw=1.4 * PT, solid_capstyle="round",
            solid_joinstyle="round")


# canvas in CSS px; one px = PT points on paper so that sizes follow the design at 1 px = 0.75 pt
PT = 0.75
W, H = 334, 118
ELECTRO = [("M24 10V5M40 10V5", None), ("M24 16v32M40 16v32", None)]
CAVERN = [("M6 20h52", None), ("M32 20v10", None),
          ("M32 30c-13 0-16 8-14 14 2 6 9 10 14 10s12-4 14-10c2-6-1-14-14-14z", None)]
TANK = [("M22 20v24M42 20v24", None), ("M32 20v-6", None)]
SOFC = [("M12 26h40M12 38h40", None), ("M24 14v36M40 14v36", (0, (3, 5))), ("M52 32h8", None)]

for stage, hi in (("charging", "a"), ("storage", "b"), ("discharging", "c")):
    fig = plt.figure(figsize=(W * PT / 72, H * PT / 72))
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.set_aspect("equal"); ax.axis("off")
    x = 2
    # stage A: electrolysis (box 80 wide)
    boxes = {}
    boxes["a"] = (x, 8, 80, 100)
    draw_icon(ax, x + 20, 18, 40, ELECTRO, rects=[(14, 10, 36, 44, 0)],
              circles=[(30, 42, 2.4), (35, 33, 2.4), (30, 25, 2.4)])
    label(ax, x + 40, 67, "Electro-\nlysis")
    x += 80 + 2; arrow(ax, x, 58); x += 22 + 2
    # stage B: storage (box 108 wide): cavern row, tank row, STORAGE label
    boxes["b"] = (x, 2, 108, 114)
    draw_icon(ax, x + 12, 10, 34, CAVERN, lw=2.6)
    ax.text(x + 54, 27, " ".join("SALT") + "\n" + " ".join("CAVERN"), fontproperties=FONT, fontsize=8.5 * PT,
            ha="left", va="center", color=BLACK, linespacing=1.3)
    draw_icon(ax, x + 12, 51, 34, TANK, rects=[(8, 20, 48, 24, 12)], lw=2.6)
    ax.text(x + 54, 68, " ".join("PRESSURE") + "\n" + " ".join("TANK"), fontproperties=FONT, fontsize=8.5 * PT,
            ha="left", va="center", color=BLACK, linespacing=1.3)
    label(ax, x + 54, 92, "Storage")
    x += 108 + 2; arrow(ax, x, 58); x += 22 + 2
    # stage C: SOFC
    boxes["c"] = (x, 8, 80, 100)
    draw_icon(ax, x + 20, 18, 40, SOFC, rects=[(12, 14, 40, 36, 0)])
    label(ax, x + 40, 67, "SOFC")
    bx, by, bw, bh = boxes[hi]
    ax.add_patch(Rectangle((bx + 1, by + 1), bw - 2, bh - 2, fill=False, edgecolor=RED, linewidth=1.5 * PT,
                           linestyle=(0, (6 / 1.5, 5 / 1.5))))
    for ext in ("pdf", "png"):
        fig.savefig(HERE / f"ldes-chain-{stage}.{ext}", dpi=300, transparent=True)
    plt.close(fig)
    print("wrote", f"ldes-chain-{stage}.pdf")
