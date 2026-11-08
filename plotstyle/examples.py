"""The four reference plots rebuilt with iconstyle, plus a side-by-side check against reference/*.svg.

    python plotstyle/examples.py [--out DIR] [--compare]

Writes <out>/<name>.png and .pdf (default: plotstyle/build/, gitignored). --compare also renders the reference
SVGs with headless Chrome and writes <out>/compare.png (reference left, matplotlib right).
"""
import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import iconstyle as ic  # noqa: E402

ROOT = HERE.parent
TA = ROOT / "config-pypsa-earth/technology-assumptions/technology_assumptions.csv"
LEARN = ROOT / "misc-quarter1/technology-costs/build/learning"
CAL = ROOT / "config-pypsa-earth/calibration"

kfmt = FuncFormatter(lambda v, _: f"{v / 1000:g}k" if v else "0")


def frame(fig, left, right, bottom, top):
    """Axes box in reference-SVG pixels (560 x 360), so the plots line up with reference/ for comparison."""
    fig.subplots_adjust(left=left / 560, right=right / 560, bottom=1 - bottom / 360, top=1 - top / 360)


def bars():
    ta = pd.read_csv(TA).set_index("technology")
    techs = ["solar-utility", "OCGT", "onwind", "offwind", "CCGT", "nuclear-lwr-cnin", "sofc", "egs", "nuclear-lwr-row", "nuclear-gen4"]
    short = ["Solar", "OCGT", "Onshore\nwind", "Offshore\nwind", "CCGT", "LWR\nCN+IN", "SOFC", "EGS", "LWR\nRoW", "Gen IV"]
    v = ta.loc[techs, "capex_power_usd_kw"].values
    col = [ic.AMBER if g == "advanced" else ic.STEEL_L for g in ta.loc[techs, "group"]]
    fig, ax = plt.subplots()
    frame(fig, 62, 540, 292, 52)
    x = np.arange(len(techs))
    ic.bars(ax, x, v, col)
    ax.set_xticks(x, short)
    ax.set_xlim(-0.5, len(techs) - 0.5)
    ax.set_ylim(0, 18000)
    ax.set_yticks(range(0, 18001, 5000))
    ax.yaxis.set_major_formatter(kfmt)
    ax.set_title("CAPEX, USD2024 per kW")
    ic.legend_squares(ax, [(ic.STEEL_L, "mature"), (ic.AMBER, "advanced")])
    ic.ground(ax)
    return fig


def lines():
    fig, ax = plt.subplots()
    frame(fig, 62, 470, 300, 50)
    for key, label, col in [("solar-utility", "Solar PV", ic.AMBER), ("onwind", "Onshore wind", ic.BLUE),
                            ("battery-liion", "Li-ion", ic.VIOLET)]:
        comp = json.loads((LEARN / f"{key}.json").read_text())["components"][0]
        pts = sorted([p for p in comp["points"] if p.get("in_fit") and not p.get("context")], key=lambda p: p["z"])
        z = np.array([p["z"] for p in pts]) / pts[0]["z"]
        c = np.array([p["c"] for p in pts]) / pts[0]["c"]
        ic.cased_line(ax, z, c, col, label)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(1, 55)
    ax.set_ylim(0.05, 1.6)
    ax.set_xticks([1, 2, 5, 10, 20, 50], ["1×", "2×", "5×", "10×", "20×", "50×"])
    ax.set_yticks([1, 0.5, 0.2, 0.1, 0.05], ["1", "0.5", "0.2", "0.1", "0.05"])
    ax.minorticks_off()
    ax.set_xlabel("Cumulative capacity relative to first observation (log)")
    ax.set_title("Cost relative to first observation")
    ic.legend_squares(ax, [(ic.AMBER, "Solar"), (ic.BLUE, "Wind"), (ic.VIOLET, "Li-ion")], anchor=(1.18, 1.0))
    return fig


def area():
    region = pd.read_csv(CAL / "2050/demand.csv").set_index("country").weo_region
    named = ["China", "United States", "European Union", "India"]
    years = [2024, 2025, 2030, 2035, 2040, 2045, 2050]
    rows = []
    for y in years:
        df = pd.read_csv(CAL / str(y) / "demand.csv")
        df["weo_region"] = df.country.map(region)
        rows.append([df.loc[df.weo_region == g, "demand_twh"].sum() for g in named]
                    + [df.loc[~df.weo_region.isin(named), "demand_twh"].sum()])
    layers = np.array(rows).T
    fig, ax = plt.subplots()
    frame(fig, 62, 440, 292, 52)
    ymax = math.ceil(layers.sum(axis=0).max() / 10000) * 10000
    ax.set_xlim(2024, 2050)
    ax.set_ylim(0, ymax)
    ax.set_xticks([2024, 2030, 2040, 2050])
    ax.yaxis.set_major_formatter(kfmt)
    ax.set_title("Electricity demand, TWh")
    ic.stacked_area(ax, years, layers, [ic.RED, ic.BLUE, ic.TEAL, ic.GOLD, ic.STEEL_L],
                    named + ["Rest of world"], values_fmt="{:,.0f} in 2050")
    ic.ground(ax, overhang=0.016)
    return fig


def lcoe():
    ta = pd.read_csv(TA).set_index("technology")
    techs = ["solar-utility", "onwind", "nuclear-lwr-cnin", "offwind", "CCGT", "geothermal", "egs", "biomass", "nuclear-lwr-row", "nuclear-gen4"]
    r, rows = 0.07, []
    for t in techs:
        s = ta.loc[t]
        cf = s.capacity_factor if pd.notna(s.capacity_factor) else 0.9
        crf = r / (1 - (1 + r) ** -s.lifetime_yr)
        rows.append((s.label.replace("Geothermal (hydrothermal)", "Geothermal"),
                     s.capex_power_usd_kw * crf * 1000 / (cf * 8760),
                     (s.fom_usd_kw_yr if pd.notna(s.fom_usd_kw_yr) else 0) * 1000 / (cf * 8760),
                     (s.vom_usd_mwh if pd.notna(s.vom_usd_mwh) else 0)
                     + (s.fuel_usd_mwh_th / s.efficiency if pd.notna(s.fuel_usd_mwh_th) else 0)))
    rows.sort(key=lambda r: -sum(r[1:]))          # barh draws bottom-up: cheapest on top
    fig, ax = plt.subplots()
    frame(fig, 168, 500, 296, 48)
    y = np.arange(len(rows))
    ic.stacked_barh(ax, y, [[r[k] for r in rows] for k in (1, 2, 3)], [ic.STEEL, ic.BLUE, ic.AMBER])
    ax.set_yticks(y, [r[0] for r in rows])
    ax.tick_params(axis="y", labelcolor=ic.INK)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlim(0, 200)
    ax.set_xticks(range(0, 201, 50))
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(axis="x", length=0)
    ax.set_title("Levelised cost, USD2024 per MWh, 7 % real", x=-0.45)
    ic.legend_squares(ax, [(ic.STEEL, "capital"), (ic.BLUE, "fixed O&M"), (ic.AMBER, "fuel, variable")],
                      loc="upper left", anchor=(0.0, -0.1), on_title_line=False)
    ic.ground(ax, axis="y", overhang=0.02)
    return fig


def compare(out, names):
    from PIL import Image
    tiles = []
    for n in names:
        ref = out / f"_ref_{n}.png"
        subprocess.run(["google-chrome", "--headless", "--disable-gpu", f"--screenshot={ref}", "--window-size=560,360",
                        "--hide-scrollbars", (HERE / "reference" / f"{n}.svg").as_uri()],
                       check=True, capture_output=True)
        tiles.append((Image.open(ref).convert("RGB"), Image.open(out / f"{n}.png").convert("RGB").resize((560, 360))))
    sheet = Image.new("RGB", (1140, 370 * len(tiles)), "white")
    for i, (a, b) in enumerate(tiles):
        sheet.paste(a, (0, 370 * i))
        sheet.paste(b, (580, 370 * i))
    sheet.save(out / "compare.png")
    for n in names:
        (out / f"_ref_{n}.png").unlink()


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", type=Path, default=HERE / "build")
    p.add_argument("--compare", action="store_true")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    ic.use()
    names = ["bars", "lines", "area", "lcoe"]
    for n in names:
        fig = globals()[n]()
        fig.savefig(a.out / f"{n}.png", dpi=100)
        fig.savefig(a.out / f"{n}.pdf")
        plt.close(fig)
    if a.compare:
        compare(a.out, names)
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
