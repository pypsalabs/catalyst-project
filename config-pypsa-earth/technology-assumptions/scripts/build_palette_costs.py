# SPDX-License-Identifier: CC0-1.0
"""technology_assumptions.csv -> cost table rows of one year for the fork (`costs: overrides`).

Writes a CSV in the technology-data format (technology, parameter, value, unit, source, further description,
currency_year) that the fork's process_cost_data merges onto the technology-data table before units, currency
and annuities are processed: rows of the same (technology, parameter) are replaced, the others added. Every
value is the CSV's, translated to the fork's conventions:

- generation rows: investment (USD/kW), FOM as % of CAPEX per year, VOM, efficiency, lifetime, fuel
  (USD/MWh_th); CO2 intensity of gas-fired rows = technology-data's gas intensity x (1 - capture_rate)
- the rows the fork looks up under other names: the `carrier` column (solar-utility -> solar, offwind ->
  offwind-ac/-dc, the applicable LWR bin -> nuclear), `gas` fuel (load_costs copies it onto OCGT and CCGT),
  and zeroed offshore station / connection rows because the CSV's offshore CAPEX is all-in
- storage rows through the fork's `storage_techs` names: the store row carries the per-kWh CAPEX, the
  (bi)charger rows the per-kW CAPEX, FOM split in proportion (toy model convention), efficiency as the fork
  expects it (round trip for battery / li-ion, which it square-roots itself; per direction otherwise)
- supply-curve rows (model tranches): the row itself plus one investment row per learning component
  (`<key>-<learning_on>`, `<key>-<learning_on_2>` with capex_share_2), the reference for the per-horizon update
  of tranche costs in the fork
- the year: mature rows follow technology-data's cost path, investment x td[row, year] / td[row, costs.year]
  for the row named in techdata_trajectory (default: the row's own key when technology-data has it); advanced
  rows are flat until the learning step writes them

Standalone: python build_palette_costs.py <year> <techdata_year.csv> <techdata_base.csv> <out.csv> [ISO2 ...]
"""
import math
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import palette  # noqa: E402

UNITS = {"investment": "USD/kW", "FOM": "%/year", "VOM": "USD/MWh", "efficiency": "per unit", "lifetime": "years",
         "fuel": "USD/MWh_th", "CO2 intensity": "tCO2/MWh_th"}
SOURCE = "technology_assumptions.csv (config-pypsa-earth/technology-assumptions)"
# rows the fork adds to the offshore turbine cost; the CSV's offshore CAPEX is all-in
OFFWIND_ADDERS = [f"offwind-{k}-{p}" for k in ("ac", "dc") for p in ("station", "connection-submarine", "connection-underground")]
ROUND_TRIP_SQRT = ["battery", "li-ion"]  # carriers whose (bi)charger efficiency the fork square-roots itself
ENERGY_ROWS = set()  # store rows: investment in USD/kWh (the fork scales every "/kW" unit by 1e3, kWh included)


def investment(td, name):
    """investment of a technology-data row (its own unit), NaN when missing."""
    s = td[(td.technology == name) & (td.parameter == "investment")].value
    return float(s.iloc[0]) if len(s) else math.nan


def trajectory(row, td, td_base, names):
    """Cost path factors of a mature row for the technology-data rows `names` (1.0 where unavailable)."""
    if row["group"] != "mature":
        return [1.0] * len(names)
    out = []
    for name in names:
        f = investment(td, name) / investment(td_base, name)
        out.append(f if math.isfinite(f) else 1.0)
    return out


def generation_rows(row, factor, gas_co2):
    p = {}
    capex, fom = palette.num(row, "capex_power_usd_kw"), palette.num(row, "fom_usd_kw_yr")
    if capex is not None:
        p["investment"] = capex * factor
        if fom is not None:
            p["FOM"] = fom / capex * 100  # % of the undiscounted CAPEX: the absolute FOM follows the cost path
    for key, col in (("VOM", "vom_usd_mwh"), ("efficiency", "efficiency"), ("lifetime", "lifetime_yr"), ("fuel", "fuel_usd_mwh_th")):
        v = palette.num(row, col)
        if v is not None:
            p[key] = v
    if row.get("fuel") == "gas":
        p["CO2 intensity"] = gas_co2 * (1 - palette.num(row, "capture_rate", 0.0))
    return p


def storage_rows(row, carrier, storage_techs, f_energy, f_power):
    """Rows per the fork's storage_techs entry of `carrier`; falls back to the row's own key (all-in per kW)."""
    cp, ce = palette.num(row, "capex_power_usd_kw", 0.0), palette.num(row, "capex_energy_usd_kwh", 0.0)
    h, fom = palette.num(row, "duration_h", 0.0), palette.num(row, "fom_usd_kw_yr", 0.0)
    eff, life = palette.num(row, "efficiency"), palette.num(row, "lifetime_yr")
    total = cp + ce * h
    share_p = cp / total if total else 0.0
    fom_p, fom_e = fom * share_p, (fom * (1 - share_p) / h if h else 0.0)  # USD/kW/yr, USD/kWh/yr
    common = {"lifetime": life} if life is not None else {}
    st = storage_techs.get(carrier)
    if st is None:
        p = dict(common, investment=total * f_power)
        if total:
            p["FOM"] = fom / total * 100
        if eff is not None:
            p["efficiency"] = eff
        return {row["technology"]: p}
    rows = {st["store"]: dict(common, investment=ce * f_energy, **({"FOM": fom_e / ce * 100} if ce else {}))}
    ENERGY_ROWS.add(st["store"])  # investment per kWh
    per_direction = eff if carrier in ROUND_TRIP_SQRT else (math.sqrt(eff) if eff is not None else None)
    power = {"bicharger": 1.0} if "bicharger" in st else {"charger": 0.5, "discharger": 0.5}
    for key, share in power.items():
        p = dict(common, investment=cp * share * f_power)
        if cp:
            p["FOM"] = fom_p * share / (cp * share) * 100
        if per_direction is not None:
            p["efficiency"] = per_direction
        rows[st[key]] = p
    return rows


def build(csv_path, countries, year, td_path, td_base_path, storage_techs, out_path):
    rows = palette.applicable(palette.read(csv_path), countries)
    td, td_base = pd.read_csv(td_path), pd.read_csv(td_base_path)
    gas_co2 = float(td[(td.technology == "gas") & (td.parameter == "CO2 intensity")].value.iloc[0])
    table = {}  # technology -> {parameter: value}

    def put(name, params, note):
        table.setdefault(name, {}).update({k: (v, note) for k, v in params.items() if v is not None})

    gas_fuel = set()
    for r in rows:
        key, note = r["technology"], f"row {r['technology']} of the palette ({r['group']}, model {r['model']})"
        names = palette._list(r.get("techdata_trajectory")) or [key]
        if r["model"] == "storage":
            f = trajectory(r, td, td_base, names if len(names) == 2 else names * 2)
            for c in palette.carriers(r):
                put_rows = storage_rows(r, c, storage_techs, f[0], f[1])
                for name, p in put_rows.items():
                    put(name, p, note)
            continue
        (f,) = trajectory(r, td, td_base, names[:1])
        p = generation_rows(r, f, gas_co2)
        if r["model"] == "existing" and r["kind"] == "storage":
            p.pop("efficiency", None)  # the fork's PHS efficiency convention differs from the CSV's (per direction)
        for name in {key, *palette.carriers(r)}:
            put(name, p, note)
        if r["model"] == "tranches":
            share_2 = palette.num(r, "capex_share_2", 0.0)
            for comp, share in ((r["learning_on"], 1 - share_2), (r.get("learning_on_2"), share_2)):
                if comp and comp != "none":
                    put(f"{key}-{comp}", {"investment": p["investment"] * share}, f"{note}; CAPEX share of the {comp} component")
        if r.get("fuel") == "gas" and "fuel" in p:
            gas_fuel.add(p["fuel"])
        if key == "offwind":
            for name in OFFWIND_ADDERS:
                put(name, {"investment": 0.0}, "the palette's offshore wind CAPEX is all-in")
    if gas_fuel:
        if len(gas_fuel) > 1:
            raise ValueError(f"gas-fired rows disagree on the gas price: {sorted(gas_fuel)} (the fork has one `gas` fuel row)")
        put("gas", {"fuel": gas_fuel.pop()}, "gas price of the palette's gas-fired rows")
    def unit(t, k):
        return "USD/kWh" if k == "investment" and t in ENERGY_ROWS else UNITS[k]

    out = [dict(technology=t, parameter=k, value=v, unit=unit(t, k), source=SOURCE, **{"further description": note},
                currency_year=2024) for t, ps in table.items() for k, (v, note) in ps.items()]
    out = pd.DataFrame(out)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    out.to_csv(out_path, index=False)
    return out


if __name__ == "__main__":
    if "snakemake" in globals():
        build(snakemake.input.csv, snakemake.params.countries, int(snakemake.wildcards.year), snakemake.input.techdata,
              snakemake.input.techdata_base, snakemake.params.storage_techs, snakemake.output[0])
    else:
        import yaml

        year, td, td_base, out, *countries = sys.argv[1:]
        fork = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "models", "pypsa-earth")
        storage_techs = yaml.safe_load(open(os.path.join(fork, "config.default.yaml")))["storage_techs"]
        df = build(palette.CSV, countries or ["SG"], int(year), td, td_base, storage_techs, out)
        print(df.drop(columns=["source"]).to_string())
