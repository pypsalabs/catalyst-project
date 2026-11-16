# SPDX-License-Identifier: CC0-1.0
"""
Spread of plant efficiencies within a fuel-burning fleet, measured on the US fleet of 2024.

The fork splits every existing fuel-burning generator into three equal parts ("tranches") with efficiencies
(1 - s), 1 and (1 + s) times the fleet efficiency (`calibration: efficiency_spread`, per carrier). This script
measures s per carrier from plant data instead of assuming it:

- EIA-923, Page 1 (generation and fuel by plant, prime mover and fuel, final 2024): fuel burnt for electricity
  (MMBtu) and net generation (MWh) -> heat rate of each plant unit group;
- EIA-860, generators operable in 2024: nameplate capacity of the same groups.

A unit group is (plant, carrier). Carriers as the model has them: coal (bituminous, subbituminous, refined and waste
coal, steam turbines), lignite, CCGT (combined-cycle prime movers CA + CT + CS together, natural gas), OCGT (gas
turbines, internal combustion engines and gas steam turbines: `electricity: gas_technology_mapping` counts
powerplantmatching's "Steam Turbine" gas plants as OCGT), oil (distillate, residual and other petroleum liquids).
Groups below MIN_CF (plants that hardly ran, whose annual heat rate is noise) or outside a plausible efficiency range
are left out. The groups are sorted by efficiency and cut into three thirds of equal capacity; the efficiency of a
third is its generation over its fuel. s = half the difference between the best and the worst third, relative to the
middle one.

The US values are applied to every region (no other fleet has open plant-level heat rates of this coverage).

Downloads (public, eia.gov) are cached under data/validation/eia/ (gitignored):
    f923_2024/f923_2024.zip     https://www.eia.gov/electricity/data/eia923/archive/xls/f923_2024.zip
    eia860_2024/eia8602024.zip  https://www.eia.gov/electricity/data/eia860/archive/xls/eia8602024.zip

Output: data/validation/efficiency_spread.csv (carrier, groups, gw, twh, efficiency of the three thirds (higher
heating value), their factors relative to the middle third, spread); the spreads are entered by hand in
statistics.yaml (`calibration: efficiency_spread`), and `--check` fails if the two differ.

Usage (from config-pypsa-earth; -I because the tables are downloads):
    ../models/pypsa-earth/.pixi/envs/default/bin/python -I scripts/build_efficiency_spread.py [--check]
"""
import argparse
import io
import os
import sys
import zipfile

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EIA = os.path.join(HERE, "data", "validation", "eia")
F923 = (os.path.join(EIA, "f923_2024", "f923_2024.zip"), "EIA923_Schedules_2_3_4_5_M_12_2024_Final.xlsx")
F860 = (os.path.join(EIA, "eia860_2024", "eia8602024.zip"), "3_1_Generator_Y2024.xlsx")
OUT = os.path.join(HERE, "data", "validation", "efficiency_spread.csv")
STATISTICS = os.path.join(HERE, "statistics.yaml")

MMBTU_PER_MWH = 3.412
MIN_CF = 0.05              # groups that ran less are left out
EFFICIENCY_RANGE = (0.15, 0.65)   # higher heating value; outside = reporting artefacts (CHP allocation, start-up fuel)
COAL = ["BIT", "SUB", "RC", "WC"]
OIL = ["DFO", "RFO", "KER", "JF", "WO"]


def carrier(prime_mover, fuel):
    """Model carrier of an EIA prime mover and fuel code, or None."""
    if fuel in COAL and prime_mover == "ST":
        return "coal"
    if fuel == "LIG" and prime_mover == "ST":
        return "lignite"
    if fuel == "NG":
        if prime_mover in ("CA", "CT", "CS"):
            return "CCGT"
        if prime_mover in ("GT", "IC", "ST"):
            return "OCGT"
    if fuel in OIL and prime_mover in ("GT", "IC", "ST"):
        return "oil"
    return None


def sheet(source, name, skiprows):
    with zipfile.ZipFile(source[0]) as z:
        return pd.read_excel(io.BytesIO(z.read(source[1])), sheet_name=name, skiprows=skiprows)


def unit_groups():
    """(plant, carrier): fuel for electricity [MMBtu], net generation [MWh], nameplate capacity [MW]."""
    gen = sheet(F923, "Page 1 Generation and Fuel Data", 5)
    gen.columns = [str(c).replace("\n", " ").strip() for c in gen.columns]
    gen["carrier"] = [carrier(p, f) for p, f in zip(gen["Reported Prime Mover"], gen["Reported Fuel Type Code"])]
    gen = gen.dropna(subset=["carrier"])
    for c in ["Elec Fuel Consumption MMBtu", "Net Generation (Megawatthours)"]:
        gen[c] = pd.to_numeric(gen[c], errors="coerce").fillna(0.0)
    energy = gen.groupby(["Plant Id", "carrier"])[["Elec Fuel Consumption MMBtu", "Net Generation (Megawatthours)"]].sum()
    energy.columns = ["mmbtu", "mwh"]

    units = sheet(F860, "Operable", 1)
    units["carrier"] = [carrier(p, f) for p, f in zip(units["Prime Mover"], units["Energy Source 1"])]
    units = units.dropna(subset=["carrier"])
    units["mw"] = pd.to_numeric(units["Nameplate Capacity (MW)"], errors="coerce")
    capacity = units.groupby(["Plant Code", "carrier"]).mw.sum().rename_axis(["Plant Id", "carrier"])

    d = energy.join(capacity, how="inner")
    d = d[(d.mwh > 0) & (d.mmbtu > 0) & (d.mw > 0)]
    d["efficiency"] = d.mwh * MMBTU_PER_MWH / d.mmbtu
    d["cf"] = d.mwh / (d.mw * 8784)   # 2024 is a leap year
    return d[(d.cf >= MIN_CF) & d.efficiency.between(*EFFICIENCY_RANGE)]


def spread(d):
    rows = []
    for c, g in d.groupby(level="carrier"):
        g = g.sort_values("efficiency")
        third = np.minimum((g.mw.cumsum() - g.mw / 2) / g.mw.sum() * 3, 2.999).astype(int)
        e = g.groupby(third.values).apply(lambda x: x.mwh.sum() * MMBTU_PER_MWH / x.mmbtu.sum())
        rows.append(dict(carrier=c, groups=len(g), gw=g.mw.sum() / 1e3, twh=g.mwh.sum() / 1e6,
                         efficiency_low=e[0], efficiency_mid=e[1], efficiency_high=e[2],
                         factor_low=e[0] / e[1], factor_high=e[2] / e[1], spread=(e[2] - e[0]) / (2 * e[1])))
    return pd.DataFrame(rows).set_index("carrier")


def configured():
    """`calibration: efficiency_spread` of statistics.yaml, per carrier."""
    import yaml

    with open(STATISTICS) as f:
        return (yaml.safe_load(f).get("calibration") or {}).get("efficiency_spread") or {}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--check", action="store_true", help="fail if statistics.yaml does not carry the measured spreads")
    a = p.parse_args()
    t = spread(unit_groups())
    t.round(4).to_csv(OUT)
    print(t.round(3).to_string())
    print(f"-> {OUT}")
    if a.check:
        cfg = configured()
        bad = {c: (cfg.get(c) if isinstance(cfg, dict) else cfg, round(float(s), 2)) for c, s in t.spread.items()
               if not isinstance(cfg, dict) or abs(cfg.get(c, np.nan) - round(float(s), 2)) > 1e-9}
        if bad:
            sys.exit(f"statistics.yaml calibration.efficiency_spread differs from the measured values: {bad}")
        print("statistics.yaml carries the measured spreads")
