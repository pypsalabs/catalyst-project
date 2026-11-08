"""What fill_circuits does with real ways that have several voltages and one total of cables (Grid Data, adjustments, 95faae14).

Tags of five example ways from resources/<R>/osm/raw, circuits per voltage without and with clean_osm_data's fix_indirect_circuits,
and the number of ways in the base network with the same number of voltages, cables and circuits tag. Without the fix a voltage gets
cables / n circuits, the values the base network holds, which the script asserts; with it a third of that.
Writes build/circuit_ways.tex (a tabular) and build/circuit_ways.csv.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/table_circuits.py
"""

import argparse
from pathlib import Path

import pandas as pd

HERE = Path(snakemake.scriptdir) if "snakemake" in globals() else Path(__file__).resolve().parent
TOP = HERE.parent
FORK = TOP / "../../models/pypsa-earth"
EXAMPLES = [("US", 5872234), ("US", 5396703), ("NWE", 22766290), ("NWE", 23557550), ("NWE", 21030812)]
REGION = {"US": "US", "NWE": "NWE"}


def number(x):
    return f"{x:.0f}" if abs(x - round(x)) < 1e-6 else f"{x:.2f}"


def per_voltage(values):
    each = " + ".join(number(v) for v in values) if number(values[0]) == f"{values[0]:.0f}" else rf"{len(values)} $\times$ {number(values[0])}"
    return f"{each} = {number(sum(values))}"


def region_table(region):
    raw = pd.concat([pd.read_csv(FORK / f"resources/{region}/osm/raw/all_raw_{k}.csv", low_memory=False,
                                 usecols=lambda c: c in ("id", "tags.voltage", "tags.cables", "tags.circuits")) for k in ("lines", "cables")])
    raw = raw.drop_duplicates("id").set_index("id")
    net = pd.read_csv(FORK / f"resources/{region}/base_network/all_lines_build_network.csv", low_memory=False, usecols=["line_id", "circuits", "dc"])
    net = net[~net.dc.astype(bool)]
    net["way"] = pd.to_numeric(net.line_id.str.extract(r"^(\d+)")[0], errors="coerce")
    tags = raw.reindex(net.way.dropna().astype("int64").unique())
    n_volt = tags["tags.voltage"].fillna("").astype(str).str.split(";").map(len)
    n_circ = tags["tags.circuits"].fillna("").astype(str).str.split(";").map(len)
    hit = tags[(n_volt > 1) & (tags["tags.circuits"].isna() | (n_circ != n_volt)) & pd.to_numeric(tags["tags.cables"], errors="coerce").notna()]
    pattern = pd.DataFrame({"n": n_volt[hit.index], "cables": pd.to_numeric(hit["tags.cables"]), "tag": hit["tags.circuits"].fillna("nan").astype(str)})
    return raw, net, pattern


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--out", default=TOP / "build/circuit_ways.tex")
    a = p.parse_args(["--out", str(snakemake.output.tex)] if "snakemake" in globals() else None)

    rows = []
    for region in dict.fromkeys(r for r, _ in EXAMPLES):
        raw, net, pattern = region_table(region)
        for way in [w for r, w in EXAMPLES if r == region]:
            t = raw.loc[way]
            volts = str(t["tags.voltage"]).split(";")
            cables = float(t["tags.cables"])
            before = [cables / len(volts)] * len(volts)
            kept = net[net.way == way].circuits
            assert (abs(kept - before[0]) < 1e-6).all(), f"way {way}: the base network holds {kept.unique()}, not {before[0]}"
            tag = str(t["tags.circuits"])
            alike = ((pattern.n == len(volts)) & (pattern.cables == cables) & (pattern.tag == tag)).sum()
            rows.append(dict(region=region, way=way, voltage=";".join(str(int(v) // 1000) for v in volts), cables=int(cables),
                             circuits_tag="none" if tag == "nan" else tag, without_fix=per_voltage(before), with_fix=per_voltage([v / 3 for v in before]),
                             ways_alike=alike, ways_hit=len(pattern)))
    df = pd.DataFrame(rows)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out.with_suffix(".csv"), index=False)
    lines = [rf"{REGION[r.region]} & \href{{https://www.openstreetmap.org/way/{r.way}}}{{{r.way}}} & {r.voltage} & {r.cables} & {r.circuits_tag} & {r.without_fix} & {r.with_fix} & {r.ways_alike:,} \\"
             for r in df.itertuples()]
    # the whole tabular: \\bottomrule cannot follow an \\input inside one
    head = [r"\begin{tabular}{@{}llllllll@{}}", r"\toprule", r"Region & Way & kV & Cables & \texttt{circuits} & Without & With & Ways alike \\", r"\midrule"]
    out.write_text("\n".join(head + lines + [r"\bottomrule", r"\end{tabular}"]) + "\n")
    print(df.to_string(index=False))


if __name__ == "__main__" or "snakemake" in globals():
    main()
