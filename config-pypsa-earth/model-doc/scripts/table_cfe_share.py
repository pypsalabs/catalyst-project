"""Table of the 24/7 CFE buyers' share of demand for the modelled archetype and test countries (Demand for 24/7 CFE).

build/cfe_share.tex: per country the data centres' share of demand in 2024 and 2030, where the 2030 value comes from, the
counted part of RE100 members' other use, and the share in 2030, 2040 and 2050 (a star marks a capped value). Reads build/country_share.csv of
misc-quarter1/datacentre-demand (all components) and its data/datacentre_countries.csv (publishers).

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/table_cfe_share.py
"""

import argparse
from pathlib import Path

import pandas as pd

TOP = Path(__file__).resolve().parents[1]
STUDY = TOP.parent
TOPIC = TOP.parents[1] / "misc-quarter1/datacentre-demand"
COUNTRIES = ["US", "CN", "IN", "BR", "SG", None, "IE", "NL", "GB", "DE", "DK", "LU", "BE", "CZ", "AT", "CH", "FR", "PL", None,
             "JP", "NZ", "ZA", "MA"]
SHORT = {"United States of America": "United States", "United Kingdom of Great Britain and Northern Ireland": "United Kingdom"}
BASIS = {"country": "{}", "interpolated": "{}, interpolated", "history": "{} $\\times$ region", "region": "IEA region", "iea": "IEA"}


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--share", default=TOPIC / "build/country_share.csv")
    p.add_argument("--sources", default=TOPIC / "data/datacentre_countries.csv")
    p.add_argument("--names", default=STUDY / "data/row_countries.csv")
    p.add_argument("--out", default=TOP / "build/cfe_share.tex")
    if "snakemake" in globals():
        a = p.parse_args(["--share", snakemake.input.share, "--sources", snakemake.input.sources,
                          "--names", snakemake.input.names, "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    s = pd.read_csv(a.share, keep_default_na=False, na_values=[""])
    wide = s.pivot(index="country", columns="year", values="share")
    capped = s.pivot(index="country", columns="year", values="capped").astype(str).eq("True")
    first = s[s.year == s.year.min()].set_index("country")
    src = pd.read_csv(a.sources, comment="#", keep_default_na=False)
    src = src[src.use.astype(int) == 1].sort_values("year")
    publisher = src.groupby("iso2").publisher.agg(lambda x: ", ".join(dict.fromkeys(" + ".join(x).split(" + "))))
    names = pd.read_csv(a.names, keep_default_na=False).set_index("iso2").name.replace(SHORT)

    order, block = [], []
    for c in COUNTRIES + [None]:            # the countries of a block with more than five rows (North-West Europe) by share
        if c is None:
            order += (sorted(block, key=lambda x: -first.share[x]) if len(block) > 5 else block) + [None]
            block = []
        else:
            block.append(c)
    pct = lambda v: f"{100 * v:.1f}"
    lines = [r"\begin{tabular}{@{}lrrlrrrr@{}}", r"\toprule",
             r" & \multicolumn{3}{c}{Data centres, \% of demand} & RE100, other & \multicolumn{3}{c}{Buyers' share, \%} \\",
             r"\cmidrule(lr){2-4}\cmidrule(l){6-8}",
             r"Country & 2024 & 2030 & 2030 value from & \% of demand & 2030 & 2040 & 2050 \\", r"\midrule"]
    for c in order[:-1]:
        if c is None:
            lines.append(r"\addlinespace")
            continue
        r = first.loc[c]
        basis = BASIS[r.basis].format(publisher.get(c, "")).replace("&", r"\&")
        share = " & ".join(pct(wide.loc[c, y]) + (r"\rlap{$^*$}" if capped.loc[c, y] else "") for y in (2030, 2040, 2050))
        lines.append(f"{names[c]} & {pct(r.datacentres_base)} & {pct(r.datacentres)} & {basis} & {pct(r.part_re100)} & {share} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(lines) + "\n")
    print(f"{len([c for c in COUNTRIES if c])} countries -> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
