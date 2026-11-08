"""Tables of the Existing Fleet section: plant list against the capacity statistic, and the statistic rows too small for their generation.

Reads build/fleet_check/{groups,ember_rows}.csv, written by ../scripts/check_fleet.py (read-only, no model rerun), and writes
two tabulars:
    build/fleet_groups.tex   per region and fuel group: GW of the plant list as build_powerplants filters it, and of the statistic
    build/fleet_ember.tex    the rows of Ember's capacity that cannot deliver Ember's generation, largest shortfall first

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/table_fleet.py
"""

import argparse
from pathlib import Path

import pandas as pd

HERE = Path(snakemake.scriptdir) if "snakemake" in globals() else Path(__file__).resolve().parent
TOP = HERE.parent
REGIONS = {"US": "US", "BR": "Brazil", "IN": "India", "CN": "China", "NWE": "NW Europe"}
GROUPS = {"coal": "Coal", "gas": "Gas", "oil": "Oil", "nuclear": "Nuclear", "biomass": "Biomass", "geothermal": "Geothermal"}
COUNTRIES = {"CN": "China", "IR": "Iran", "ID": "Indonesia", "EG": "Egypt", "US": "US", "TR": "Türkiye", "SY": "Syria",
             "TW": "Taiwan", "RU": "Russia", "NL": "Netherlands", "CD": "DR Congo", "PL": "Poland", "IT": "Italy", "JP": "Japan"}
FIX = {"biomass": "IRENA", "geothermal": "IRENA"}


def gw(x):
    return "--" if x < 0.005 else (f"{x:.0f}" if x >= 10 else f"{x:.1f}" if x >= 1 else f"{x:.2f}")


def groups_table(fn):
    g = pd.read_csv(fn).set_index(["region", "group"])
    lines = [r"\begin{tabular}{@{}l" + "r" * len(GROUPS) + "@{}}", r"\toprule",
             "Region & " + " & ".join(GROUPS.values()) + r" \\", r"\midrule"]
    for r, name in REGIONS.items():
        cells = []
        for k in GROUPS:
            row = g.loc[(r, k)]
            cells.append("--" if row.plant_list_now_gw < 0.005 and row.statistic_gw < 0.005
                         else rf"{gw(row.plant_list_now_gw)} $\to$ {gw(row.statistic_gw)}")
        lines.append(f"{name} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


def ember_table(fn, n=10):
    t = pd.read_csv(fn)
    t = t[t.previous_cf > 1].sort_values("unreachable_twh", ascending=False)
    total, count = t.unreachable_twh.sum(), len(t)
    lines = [r"\begin{tabular}{@{}llrrrrl@{}}", r"\toprule",
             r"Country & Group & TWh & Ember, GW & Capacity factor & Table, GW & Source \\", r"\midrule"]
    for r in t.head(n).itertuples():
        lines.append(f"{COUNTRIES.get(r.country, r.country)} & {GROUPS.get(r.group, r.group.capitalize())} & {r.twh:.1f} & {gw(r.ember_gw)} "
                     f"& {r.ember_cf:.1f} & {gw(r.table_gw)} & {FIX.get(r.group, 'back-filled')}" + r" \\")
    rest = t.iloc[n:]
    lines += [r"\midrule",
              rf"\multicolumn{{7}}{{@{{}}l}}{{{len(rest)} further rows, {rest.unreachable_twh.sum():.0f}\,TWh; all {count} rows: "
              rf"{total:.0f}\,TWh that the capacity cannot deliver at full output}} \\",
              r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--groups", default=TOP / "build/fleet_check/groups.csv")
    p.add_argument("--ember", default=TOP / "build/fleet_check/ember_rows.csv")
    p.add_argument("--out-groups", default=TOP / "build/fleet_groups.tex")
    p.add_argument("--out-ember", default=TOP / "build/fleet_ember.tex")
    if "snakemake" in globals():
        a = p.parse_args(["--groups", str(snakemake.input.groups), "--ember", str(snakemake.input.ember),
                          "--out-groups", str(snakemake.output.groups), "--out-ember", str(snakemake.output.ember)])
    else:
        a = p.parse_args()
    Path(a.out_groups).write_text(groups_table(a.groups))
    Path(a.out_ember).write_text(ember_table(a.ember))
    print(f"-> {a.out_groups}, {a.out_ember}")


if __name__ == "__main__":
    main()
