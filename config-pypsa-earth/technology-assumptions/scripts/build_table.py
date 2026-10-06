"""technology_assumptions.csv -> build/table.tex: the page-1 tables of the assumptions document.

Two tables, one per page (costs and performance; deployment and learning), advanced
technologies first, that show every numeric column of the CSV verbatim (rows with
in_default_mix = no are shaded instead of carrying a column), plus LCOE / LCOS columns at
2 and 7 % real discount rate computed from the row's own numbers and coloured green -> red: values are passed as the CSV strings through
siunitx \\num{} (thousands grouping, no rounding), blanks print as "--". Every technology
name is a hyperlink (\\techlink, defined in doc/main.tex) to \\label{sec:<technology>} in that
technology's section, where the content of the free-text `source` and `comment` columns is
argued in prose (the columns themselves document the CSV; they are not typeset).

Also warns (never fixes) when a CSV row has no doc/sections/<technology>.tex, when that file
has no \\label{sec:<technology>} (the table link would dangle), or when the CAPEX typed into
its first \\subsection title differs from the CSV: the title number is hand-typed on purpose
so that a divergence is visible.

Standalone:  python scripts/build_table.py [technology_assumptions.csv] [-o build/table.tex] [--sections doc/sections]
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

TOP = Path(__file__).resolve().parents[1]

COLUMNS = ["technology", "label", "group", "kind", "in_default_mix", "capex_power_usd_kw", "capex_energy_usd_kwh", "duration_h",
           "fom_usd_kw_yr", "vom_usd_mwh", "efficiency", "lifetime_yr", "capacity_factor", "cycles_per_yr",
           "fuel_usd_mwh_th", "existing_gw", "pipeline_gw", "lead_time_yr", "max_build_rate_gw_yr", "learning_rate",
           "learning_on", "learning_basis", "currency_year", "source", "comment"]
# optional: a second learning rate on another component (EGS: drilling + plant), and reference_site = the site whose
# CAPEX the row carries where the cost depends on the site (EGS: Fervo Cape Station; the CAPEX and LCOE cells are
# marked with a dagger named in the caption), and section = the key of the section the row's table link jumps to when
# it shares another row's section (SOFC with CC -> sofc; blank = its own technology key); missing columns are added blank
OPTIONAL = ["learning_rate_2", "learning_on_2", "reference_site", "section"]
NUMERIC = ["capex_power_usd_kw", "capex_energy_usd_kwh", "duration_h", "fom_usd_kw_yr", "vom_usd_mwh", "efficiency",
           "lifetime_yr", "capacity_factor", "cycles_per_yr", "fuel_usd_mwh_th", "existing_gw", "pipeline_gw",
           "lead_time_yr", "max_build_rate_gw_yr", "learning_rate", "learning_rate_2", "currency_year"]
# levelised cost columns computed from the table's own numbers at these real discount rates
DISCOUNT_RATES = [0.02, 0.07]
HOURS = 8760
VOCAB = {"group": {"mature", "advanced"}, "kind": {"generation", "storage"}, "in_default_mix": {"yes", "no"},
         "learning_on": {"plant", "energy", "power", "drilling", "none"},
         "learning_on_2": {"plant", "energy", "power", "drilling", ""},
         "learning_basis": {"fitted", "analogy", "literature", "assumption", "decided", "exogenous", "none"}}
GROUP_ORDER = ["advanced", "mature"]
# rows not in the default technology mix are shaded (colour `offmix` defined in doc/main.tex), not listed as a column
OFFMIX = "\\rowcolor{offmix}"
# rows with a reference_site (EGS: per-cell supply curves in the model): CAPEX and LCOE are those of the reference
# site and carry this mark, named in the caption
SITE_MARK = "\\rlap{\\textsuperscript{\\textdagger}}"

# (column, header line 1, header line 2)
COST_COLS = [("capex_power_usd_kw", "CAPEX", "\\$/kW"), ("capex_energy_usd_kwh", "CAPEX", "\\$/kWh"),
             ("duration_h", "Dur.", "h"), ("fom_usd_kw_yr", "FOM", "\\$/kW/yr"), ("vom_usd_mwh", "VOM", "\\$/MWh"),
             ("efficiency", "Eff.", "--"), ("lifetime_yr", "Life", "yr"),
             ("utilisation", "CF/cyc.", "--/yr"), ("fuel_usd_mwh_th", "Fuel", "\\$/MWh\\textsubscript{th}")] + \
            [(f"lcoe_{int(r * 100)}", "LCOE", f"{int(r * 100)}\\,\\% \\$/MWh") for r in DISCOUNT_RATES]
LCOE_COLS = [f"lcoe_{int(r * 100)}" for r in DISCOUNT_RATES]
DEPLOY_COLS = [("existing_gw", "Existing", "GW"), ("pipeline_gw", "Pipeline", "GW"), ("lead_time_yr", "Lead time", "yr"),
               ("max_build_rate_gw_yr", "Build limit", "GW/yr"), ("learning_rate", "Learning rate", "--"),
               ("learning_on", "Learning on", ""), ("learning_basis", "Basis", "")]

ESC = {"&": "\\&", "%": "\\%", "$": "\\$", "#": "\\#", "_": "\\_", "{": "\\{", "}": "\\}", "~": "\\textasciitilde{}",
       "^": "\\textasciicircum{}"}


def esc(s):
    return "".join(ESC.get(c, c) for c in str(s))


def num(s):
    return "--" if s == "" else f"\\num{{{s}}}"


def read(path):
    df = pd.read_csv(path, dtype=str, keep_default_na=False).apply(lambda c: c.str.strip())
    for c in OPTIONAL:
        if c not in df.columns:
            df[c] = ""
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    if df["technology"].duplicated().any():
        raise ValueError(f"duplicate technology keys: {df['technology'][df['technology'].duplicated()].tolist()}")
    for col, vocab in VOCAB.items():
        bad = df.loc[~df[col].isin(vocab), ["technology", col]]
        if len(bad):
            raise ValueError(f"unknown {col} values: {bad.values.tolist()} (allowed {sorted(vocab)})")
    for col in NUMERIC:
        for tech, v in zip(df["technology"], df[col]):
            if v != "":
                try:
                    float(v)
                except ValueError:
                    raise ValueError(f"{tech}: {col} = {v!r} is not a number") from None
    if df["currency_year"].nunique() != 1:
        raise ValueError(f"currency_year must be uniform, got {sorted(df['currency_year'].unique())}")
    return df


def annuity(rate, years):
    return rate / (1 - (1 + rate) ** -years)


def lcoe(r, rate):
    """Levelised cost in USD/MWh from the row's own numbers, or None where a number is missing.

    generation: (annuity x CAPEX_kW + FOM) / (8760 h x CF) + VOM + fuel / efficiency
    storage (LCOS, per MWh discharged, charging electricity excluded):
                (annuity x (CAPEX_kW + CAPEX_kWh x duration) + FOM) / (cycles x duration)
    """
    f = lambda c: float(r[c]) if r[c] != "" else None
    life, fom, vom = f("lifetime_yr"), f("fom_usd_kw_yr") or 0.0, f("vom_usd_mwh") or 0.0
    if life is None:
        return None
    a = annuity(rate, life)
    if r["kind"] == "storage":
        h, cyc = f("duration_h"), f("cycles_per_yr")
        if h is None or cyc is None:
            return None
        capex = (f("capex_power_usd_kw") or 0.0) + (f("capex_energy_usd_kwh") or 0.0) * h
        return (a * capex + fom) / (cyc * h) * 1e3
    capex, cf = f("capex_power_usd_kw"), f("capacity_factor")
    if capex is None or cf is None:
        return None
    fuel, eff = f("fuel_usd_mwh_th"), f("efficiency")
    fuel_term = fuel / eff if fuel is not None and eff else 0.0
    return (a * capex + fom) * 1e3 / (HOURS * cf) + vom + fuel_term


def add_lcoe(df):
    """Adds the utilisation column (CF or cycles) and one LCOE column per discount rate, formatted."""
    df = df.copy()
    df["utilisation"] = [r["cycles_per_yr"] if r["kind"] == "storage" else r["capacity_factor"] for _, r in df.iterrows()]
    for rate, col in zip(DISCOUNT_RATES, LCOE_COLS):
        df[col] = [lcoe(r, rate) for _, r in df.iterrows()]
    return df


def cell_colour(v, lo, hi):
    """Pastel green -> yellow -> red on a log scale between lo and hi (Excel-style conditional format)."""
    import math
    t = (math.log(v) - math.log(lo)) / (math.log(hi) - math.log(lo)) if hi > lo else 0.5
    t = min(max(t, 0.0), 1.0)
    green, yellow, red = (198, 239, 206), (255, 235, 156), (255, 199, 206)
    a, b, u = (green, yellow, t * 2) if t < 0.5 else (yellow, red, (t - 0.5) * 2)
    return "".join(f"{round(x + (y - x) * u):02X}" for x, y in zip(a, b))


def sec_key(r):
    """Section the row's table link jumps to: its own technology key unless `section` names another row's."""
    return r["section"] or r["technology"]


def site_specific(r):
    return r["reference_site"] != ""


def rows_of(df, cols):
    """Table body: one block per group, technologies in CSV order."""
    vals = [v for c in LCOE_COLS if c in df for v in df[c] if v is not None]
    lcoe_range = (min(vals), max(vals)) if vals else (1.0, 1.0)
    lines = []
    for i, group in enumerate(GROUP_ORDER):
        block = df[df["group"] == group]
        if i:
            lines.append("\\addlinespace[3pt]")
        lines.append(f"\\multicolumn{{{len(cols) + 1}}}{{l}}{{\\itshape {group.capitalize()} technologies}}\\\\")
        for _, r in block.iterrows():
            cells = []
            site = site_specific(r)
            for c in cols:
                if site and c == "capex_power_usd_kw":
                    cells.append(f"{num(r[c])}{SITE_MARK}")   # reference site, see caption
                elif c in LCOE_COLS:
                    v = r[c]
                    cells.append("--" if v is None else f"\\cellcolor[HTML]{{{cell_colour(v, *lcoe_range)}}}\\num{{{v:.0f}}}"
                                 + (SITE_MARK if site else ""))
                elif c in ("learning_rate", "learning_on") and r[f"{c}_2"] != "":
                    fmt = num if c == "learning_rate" else esc
                    cells.append(f"{fmt(r[c])} / {fmt(r[c + '_2'])}")   # two components, e.g. drilling / plant
                elif c in NUMERIC or c == "utilisation":
                    cells.append(num(r[c]))
                else:
                    cells.append(esc(r[c]) if r[c] != "" else "--")
            label = f"\\techlink{{{sec_key(r)}}}{{{esc(r['label'])}}}"   # jumps to \label{sec:<section key>}
            shade = OFFMIX if r["in_default_mix"] == "no" else ""
            lines.append(f"{shade}{label} & " + " & ".join(cells) + "\\\\")
    return "\n".join(lines)


def header(cols):
    # a third header line spanning the table so the legend does not widen the first column
    legend = "\\colorbox{offmix}{\\strut\\,shaded\\,} = not in the default mix"
    return (" & ".join(["Technology"] + [h1 for _, h1, _ in cols]) + "\\\\\n"
            + " & ".join([""] + [f"{{\\scriptsize {h2}}}" for _, _, h2 in cols]) + "\\\\\n"
            + f"\\multicolumn{{{len(cols) + 1}}}{{@{{}}l}}{{\\scriptsize {legend}}}\\\\")


def table(df, cols, caption, label):
    spec = "l" + "r" * len(cols)
    out = ["\\begin{center}", f"\\begin{{tabular}}{{@{{}}{spec}@{{}}}}", "\\toprule",
           header(cols), "\\midrule", rows_of(df, [c for c, _, _ in cols]), "\\bottomrule", "\\end{tabular}",
           f"\\captionof{{table}}[{caption[0]}]{{{' \\newline '.join(caption)}}}\\label{{{label}}}", "\\end{center}"]
    return "\n".join(out)


def build(df):
    year = df["currency_year"].iloc[0]
    df = add_lcoe(df)
    rates = " and ".join(f"{int(r * 100)}\\,\\%" for r in DISCOUNT_RATES)
    # captions: one statement per line (joined with \newline in table())
    cap1 = [f"Costs and performance, USD\\textsubscript{{{esc(year)}}}.",
            "Click technology names to jump to the respective section.",
            "Storage: CAPEX per kW of power plus per kWh at the stated duration (Dur.); efficiency (Eff.) = round trip; "
            "FOM per kW of power including the energy part.",
            "CF/cyc.\\ = capacity factor (generation) or full cycles per year (storage).",
            f"LCOE at a real discount rate of {rates} from this table's numbers: (annuity $\\times$ CAPEX + FOM)/(8760\\,h "
            "$\\times$ CF) + VOM + fuel/efficiency, no CO\\textsubscript{2} price.",
            "Storage per MWh discharged: (annuity $\\times$ (CAPEX\\textsubscript{kW} + CAPEX\\textsubscript{kWh} "
            "$\\times$ Dur.) + FOM)/(cycles $\\times$ Dur.), charging electricity excluded."]
    site = [r for _, r in df.iterrows() if site_specific(r)]
    if site:
        for r in site:
            cap1.append(f"\\textdagger\\ \\techlink{{{sec_key(r)}}}{{{esc(r['label'])}}}: CAPEX and LCOE at the reference site, "
                        f"\\textbf{{{esc(r['reference_site'])}}}, as representative values; costs depend on the site, and the "
                        "model uses supply curves per grid cell.")
    cap2 = ["Deployment and learning.",
            "Existing = global operating capacity end-2024; pipeline = under construction / post-FID.",
            "Lead time = years from investment decision to operation; build limit = maximum global additions per year.",
            "Build limits are set for the nuclear bins, from recent construction starts; blank = unconstrained.",
            "Learning rate = cost reduction per doubling of cumulative capacity, applied to the stated component "
            "(`a / b' = two components with their own rates; `none' = exogenous or no learning).",
            "Basis: decided in the project, fitted to observed series, taken from the literature, analogy to a "
            "comparable technology, or exogenous cost path."]
    # one table per page; the comment and source columns are argued in the sections, not typeset
    return "\n\n".join([
        "% generated by scripts/build_table.py from technology_assumptions.csv -- do not edit",
        table(df, COST_COLS, cap1, "tab:costs"),   # \\ref{tab:costs} in the sections
        "\\clearpage",
        table(df, DEPLOY_COLS, cap2, "tab:deployment"),
    ]) + "\n"


def check_sections(df, sections):
    """Warn for rows without a section file or \\label{sec:<section key>}, and for titles whose CAPEX differs from the CSV
    (a shared section must carry the CAPEX of every row that links to it)."""
    sections = Path(sections)
    for _, r in df.iterrows():
        key = sec_key(r)
        f = sections / f"{key}.tex"
        if not f.exists():
            print(f"warning: no section file {f} for {r['technology']}")
            continue
        text = f.read_text()
        if f"\\label{{sec:{key}}}" not in text:
            print(f"warning: {f}: no \\label{{sec:{key}}}, the table link to it dangles")
        m = re.search(r"\\subsection\{([^}]*)\}", text)
        if not m:
            print(f"warning: {f}: no \\subsection title")
            continue
        nums = [float(x.replace(",", "")) for x in re.findall(r"[\d,]*\.?\d+", m.group(1).replace("~", " "))]
        capex = r["capex_energy_usd_kwh"] if r["kind"] == "storage" and r["capex_energy_usd_kwh"] else r["capex_power_usd_kw"]
        if capex and float(capex) not in nums:
            print(f"warning: {f}: title '{m.group(1)}' does not carry the CSV CAPEX {capex}")


def main():
    if "snakemake" in globals():
        csv, out, sections = snakemake.input.csv, snakemake.output.tex, snakemake.params.sections
        sys.stdout = open(snakemake.log[0], "w")
    else:
        p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
        p.add_argument("csv", nargs="?", default=TOP / "technology_assumptions.csv")
        p.add_argument("-o", "--out", default=TOP / "build/table.tex")
        p.add_argument("--sections", default=TOP / "doc/sections")
        a = p.parse_args()
        csv, out, sections = a.csv, a.out, a.sections
    df = read(csv)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(build(df))
    check_sections(df, sections)
    print(f"{len(df)} technologies -> {out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
