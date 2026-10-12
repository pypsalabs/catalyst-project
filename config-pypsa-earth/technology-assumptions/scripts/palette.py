# SPDX-License-Identifier: CC0-1.0
"""technology_assumptions.csv -> what the PyPSA-Earth fork needs to build the palette.

The CSV is the single source of truth: which technologies the model may build, as which carrier, where, and
with which fuel, availability and colour are columns of the CSV (see `MODEL_COLUMNS` in build_table.py), not a
palette list in a config file. This module reads those columns for

- merge_config.py, which derives the stage config from them (`model_config`: extendable carriers, storage
  durations, availability / minimum load through the fork's `conventional:` block, the calibration fuel map,
  colours and labels, the path of the per-year cost overrides), and
- build_palette_costs.py, which writes the cost table rows of one year (`costs: overrides` of the fork).

Row semantics
    in_default_mix  yes/no: part of the study palette at all (VRFB and CO2 battery are kept in the table, not built)
    model           profile  : renewable with an atlite profile (solar, wind)
                    firm     : dispatchable generator, buildable at every bus (fork: extendable_carriers_buses: all)
                    tranches : site-specific supply curve attached per cluster region (fork: supply_curves)
                    storage  : StorageUnit with the CSV duration when only a per-kWh CAPEX is given (iron-air),
                               Store + charger / discharger links when a per-kW CAPEX is given too (battery)
                    existing : the existing fleet only, no new builds
    carrier         the fork's carrier name(s) the row drives (comma list: offwind -> offwind-ac, offwind-dc)
    regions         ISO2 list; blank = everywhere not claimed by a row with an explicit match on the same carrier
Buildable = in_default_mix yes and model != existing.
"""
import csv
import sys
from pathlib import Path

CSV = Path(__file__).resolve().parents[1] / "technology_assumptions.csv"
PRICED_FUELS = ["gas", "coal", "lignite", "oil", "uranium", "biomass"]  # fuels of calibration/<year>/fuel_prices.csv


def read(path=CSV):
    """Rows of the CSV as dicts of stripped strings (blank = missing)."""
    with open(path, newline="") as f:
        return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def _list(s):
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def carriers(row):
    return _list(row.get("carrier")) or [row["technology"]]


def regions(row):
    return _list(row.get("regions"))


def num(row, col, default=None):
    v = row.get(col, "")
    return float(v) if v != "" else default


def applicable(rows, countries):
    """Rows that apply to a region (list of ISO2 codes): rows with an explicit region match, and rows without
    regions whose carriers no explicit row claims. Raises when two rows would drive one carrier."""
    countries = set(countries)
    explicit = [r for r in rows if regions(r) and set(regions(r)) & countries]
    claimed = {c for r in explicit for c in carriers(r)}
    out = [r for r in rows if (r in explicit) or (not regions(r) and not set(carriers(r)) & claimed)]
    seen = {}
    for r in out:
        for c in carriers(r):
            if c in seen:
                raise ValueError(f"carrier {c}: rows {seen[c]} and {r['technology']} both apply to {sorted(countries)}")
            seen[c] = r["technology"]
    return out


def buildable(rows):
    return [r for r in rows if r["in_default_mix"] == "yes" and r["model"] != "existing"]


def is_storage_unit(row):
    """Storage with a fixed duration and no separate power cost: a StorageUnit of `duration_h` (iron-air)."""
    return row["model"] == "storage" and not row.get("capex_power_usd_kw")


def fuel_map(rows):
    """Carrier -> fuel of the calibration price tables (`calibration: fuel_map` of the fork)."""
    return {c: r["fuel"] for r in rows if r.get("fuel") in PRICED_FUELS for c in carriers(r)}


def tech_colors(rows):
    return {c: r["color"] for r in rows if r.get("color") for c in carriers(r)}


def nice_names(rows):
    return {c: r["label"] for r in rows if r.get("label") for c in carriers(r)}


def model_config(rows, countries, stage):
    """Config fragment of one stage (deep-merged onto the stage config by merge_config.py)."""
    rows = applicable(rows, countries)
    b = buildable(rows)
    gens = [c for r in b if r["model"] in ("profile", "firm") for c in carriers(r)]
    sus = [c for r in b if is_storage_unit(r) for c in carriers(r)]
    stores = [c for r in b if r["model"] == "storage" and not is_storage_unit(r) for c in carriers(r)]
    conventional = {}
    for r in b:
        if r["model"] != "firm":
            continue
        attrs = {k: num(r, col) for k, col in (("p_max_pu", "availability"), ("p_min_pu", "min_load")) if r.get(col)}
        for c in carriers(r):
            if attrs:
                conventional[c] = dict(attrs)
    cfg = {
        "electricity": {
            "extendable_carriers": {"Generator": gens, "StorageUnit": sus, "Store": stores, "Link": []},
            "extendable_carriers_buses": "all",
            "max_hours": {c: num(r, "duration_h") for r in b if is_storage_unit(r) for c in carriers(r)},
        },
        "conventional": conventional,
        "costs": {
            "overrides": f"resources/{stage}/palette/costs_{{year}}.csv",  # written by assumptions.smk palette_costs
            "marginal_cost": {},  # the fork's defaults would override the CSV VOM
            "rooftop_share": 0.0,  # solar = the CSV's utility-scale row
            "output_currency": "USD",
        },
        "calibration": {"fuel_map": fuel_map(rows)},
        "plotting": {"tech_colors": tech_colors(rows), "nice_names": nice_names(rows)},
    }
    return cfg


def tranche_carriers(rows, countries):
    """Carriers built as supply curves (model = tranches); their datasets are configured in the overlay (supply_curves)."""
    return [c for r in buildable(applicable(rows, countries)) if r["model"] == "tranches" for c in carriers(r)]


if __name__ == "__main__":
    import json

    countries = sys.argv[1:] or ["SG"]
    print(json.dumps(model_config(read(), countries, "test"), indent=1))
    print("tranches:", tranche_carriers(read(), countries))
