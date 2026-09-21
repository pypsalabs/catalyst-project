"""Compile the 2025 techno-economic baseline for the SOW technology palette.

Inputs
  technology-data costs_2025 (pinned tag), data/gap_fill.csv (parameters that
  technology-data lacks or gets wrong), data/observed_projects.csv (real
  project costs and published benchmarks), config.yaml (palette, mappings,
  capacity factors, FX and CPI tables).

Outputs
  build/costs_2025_compiled.csv  long format, one row per (technology, parameter)
                                 with original value/unit/currency year, the
                                 normalised base-currency value, origin and source id
  build/costs_2025_table.csv     wide, one row per technology incl. LCOE band
  build/observed_normalised.csv  observed points converted to the base currency
  build/sources.md               numbered source list used by plots and README

Method
  currency: value * fx_eur_per_unit[cur][y] / fx_eur_per_unit[base][y]
                  * cpi[base][base_year] / cpi[base][y]
  LCOE(CF) = (annuity(r, n) * capex + FOM) * 1000 / (8760 * CF)
             + VOM + fuel / eta + co2_price * intensity * (1 - capture) / eta
  annuity(r, n) = r / (1 - (1 + r)^-n)
  (currency conversion and annuity live in common.py)

Run standalone:  python compile_costs.py   (paths relative to this file)
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from common import annuity, make_to_base, split_currency  # noqa: F401

if "snakemake" in globals():
    CFG = snakemake.config
    TD = Path(snakemake.input.td)
    GAP = Path(snakemake.input.gap_fill)
    OBS = Path(snakemake.input.observed)
    OUT_COMPILED = Path(snakemake.output.compiled)
    OUT_TABLE = Path(snakemake.output.table)
    OUT_OBS = Path(snakemake.output.observed)
    OUT_SOURCES = Path(snakemake.output.sources)
else:
    _HERE = Path(__file__).parent
    CFG = yaml.safe_load((_HERE / "config.yaml").read_text())
    TD = _HERE / "data" / "technology-data" / f"costs_2025_{CFG['technology_data']['tag']}.csv"
    GAP = _HERE / "data" / "gap_fill.csv"
    OBS = _HERE / "data" / "observed_projects.csv"
    OUT_COMPILED = _HERE / "build" / "costs_2025_compiled.csv"
    OUT_TABLE = _HERE / "build" / "costs_2025_table.csv"
    OUT_OBS = _HERE / "build" / "observed_normalised.csv"
    OUT_SOURCES = _HERE / "build" / "sources.md"
OUT_COMPILED.parent.mkdir(parents=True, exist_ok=True)

BASE_YEAR = int(CFG["base_currency_year"])
BASE_CUR = CFG["base_currency"]
FX = CFG["fx_eur_per_unit"]
CPI = CFG["cpi"]
CURRENCIES = set(FX)
HOURS = CFG["hours_per_year"]
R = CFG["discount_rate"]

# technology-data `parameter` used for each of our parameter names
TD_PARAM = {
    "investment": "investment", "investment_kwh": "investment",
    "investment_kw": "investment", "FOM": "FOM", "FOM_kwh": "FOM", "VOM": "VOM",
    "lifetime": "lifetime", "efficiency": "efficiency", "efficiency_2": "efficiency",
    "fuel": "fuel",
}
CANONICAL_UNITS = {
    f"{BASE_CUR}/kW", f"{BASE_CUR}/kWh", f"{BASE_CUR}/kW/a", f"{BASE_CUR}/kWh/a",
    f"{BASE_CUR}/MWh", f"{BASE_CUR}/MWh_th", f"{BASE_CUR}/(tCO2/h)", f"{BASE_CUR}/tCO2",
    "years", "fraction", "fraction_of_investment", "tCO2/MWh_th",
}


# --- helpers -------------------------------------------------------------------

to_base = make_to_base(CFG)


def normalise_unit(parameter, value, unit):
    """Map a raw unit string to a canonical unit; returns (value, unit, factor)."""
    u = re.sub(r",\s*\d{4}\s*$", "", str(unit)).strip().strip('"')
    cur, rest = split_currency(u)
    rest = rest.replace(" ", "")
    rest_l = rest.lower()

    def money(canonical, factor=1.0):
        return value * factor, canonical.replace("EUR/", f"{BASE_CUR}/")

    if parameter in ("investment", "investment_kw"):
        if rest_l in ("kw", "kw_e", "kwel", "kw_el", "kwe"):
            return money("EUR/kW")
        if rest_l in ("mw", "mw_e", "mwel", "mw_el"):
            return money("EUR/kW", 1e-3)
        if rest_l == "(tco2/h)":
            return money("EUR/(tCO2/h)")
        if rest_l in ("kwh", "kwh_e"):   # storage-only technologies quoted per kWh
            return money("EUR/kWh")
    if parameter == "investment_kwh":
        if rest_l in ("kwh", "kwh_e", "kwhel"):
            return money("EUR/kWh")
        if rest_l in ("mwh", "mwh_e", "mwhel"):
            return money("EUR/kWh", 1e-3)
    if parameter in ("FOM", "FOM_kwh"):
        if u in ("%/year", "%/a", "%"):
            return value / 100, "fraction_of_investment"
        if re.fullmatch(r"kw(_e|el)?[/-](a|yr|year)", rest_l):
            return money("EUR/kW/a")
        if re.fullmatch(r"kwh[/-](a|yr|year)", rest_l):
            return money("EUR/kWh/a")
    if parameter == "VOM":
        if rest_l in ("mwh", "mwh_e", "mwhel", "mwh_el"):
            return money("EUR/MWh")
    if parameter == "fuel":
        if rest_l in ("mwh_th", "mwhth"):
            return money("EUR/MWh_th")
    if parameter in ("efficiency", "efficiency_2", "capture_rate", "capacity_factor"):
        if u.lower() in ("per unit", "p.u.", "fraction", "-", "per unit (in lhv)"):
            return value, "fraction"
        if u == "%":
            return value / 100, "fraction"
    if parameter == "lifetime" and u.lower() in ("years", "a", "yr"):
        return value, "years"
    if parameter == "co2_intensity" and rest_l.replace("_", "") in ("tco2/mwhth",):
        return value, "tCO2/MWh_th"
    if parameter == "cost_per_tco2" and rest_l in ("tco2", "t", "tonne", "ton"):
        return money("EUR/tCO2")
    raise ValueError(f"cannot normalise unit {unit!r} for parameter {parameter!r}")


# --- technology-data ----------------------------------------------------------------

td = pd.read_csv(TD)
td = td[td["technology"].str.len() < 60]          # drop leaked sentences
td_index = td.set_index(["technology", "parameter"])

techs = CFG["technologies"]
records = []
for t in techs:
    for param, td_name in (t.get("td") or {}).items():
        assert td_name not in ("SMR", "SMR CC"), (
            "technology-data 'SMR' is steam methane reforming, not a reactor")
        key = (td_name, TD_PARAM[param])
        if key not in td_index.index:
            raise KeyError(f"{t['key']}: technology-data has no row {key}")
        row = td_index.loc[key]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        records.append({
            "technology": t["key"], "parameter": param,
            "value_orig": row["value"], "unit_orig": row["unit"],
            "currency": split_currency(str(row["unit"]))[0] or "EUR",
            "currency_year_orig": row["currency_year"],
            "origin": f"technology-data {CFG['technology_data']['tag']}",
            "source": str(row["source"]).strip(), "url": "",
            "note": str(row.get("further description", "") or "").strip(),
        })
        if param == "fuel" and (td_name, "CO2 intensity") in td_index.index:
            ci = td_index.loc[(td_name, "CO2 intensity")]
            records.append({
                "technology": t["key"], "parameter": "co2_intensity",
                "value_orig": ci["value"], "unit_orig": ci["unit"], "currency": "EUR",
                "currency_year_orig": np.nan,
                "origin": f"technology-data {CFG['technology_data']['tag']}",
                "source": str(ci["source"]).strip(), "url": "", "note": "",
            })
long = pd.DataFrame(records)

# --- gap fill ---------------------------------------------------------------------

gap = pd.read_csv(GAP, dtype={"note": str, "url": str, "source": str})
gap["note"] = gap["note"].fillna("")
dup = gap.duplicated(["technology", "parameter"], keep=False)
assert not dup.any(), f"duplicate gap_fill rows:\n{gap[dup]}"
unknown = set(gap["technology"]) - {t["key"] for t in techs}
assert not unknown, f"gap_fill technologies not in config: {unknown}"

existing = set(zip(long["technology"], long["parameter"]))
add = []
for _, g in gap.iterrows():
    k = (g["technology"], g["parameter"])
    override = g["note"].startswith("OVERRIDE")
    addition = g["note"].startswith("ADD")
    if addition:                       # component added on top of the technology-data value
        assert k in existing, f"{k}: ADD row without a technology-data base row"
        k = (k[0], k[1] + "+")
    elif k in existing and not override:
        continue                       # technology-data wins unless overridden
    elif k in existing:
        long = long[~((long["technology"] == k[0]) & (long["parameter"] == k[1]))]
    cur = g["currency"] if isinstance(g["currency"], str) else split_currency(str(g["unit"]))[0]
    add.append({
        "technology": k[0], "parameter": k[1],
        "value_orig": g["value"], "unit_orig": g["unit"],
        "currency": cur or "EUR", "currency_year_orig": g["currency_year"],
        "origin": "gap_fill", "source": g["source"], "url": g["url"] if isinstance(g["url"], str) else "",
        "note": g["note"],
    })
long = pd.concat([long, pd.DataFrame(add)], ignore_index=True)

# --- normalise units and currency ------------------------------------------------------

vals, units, notes = [], [], []
for _, r in long.iterrows():
    if pd.isna(r["value_orig"]):
        vals.append(np.nan); units.append(""); notes.append(r["note"]); continue
    v, u = normalise_unit(r["parameter"].rstrip("+"), float(r["value_orig"]), r["unit_orig"])
    if u.startswith(f"{BASE_CUR}/"):
        v, n = to_base(v, r["currency"], r["currency_year_orig"])
    else:
        n = ""
    vals.append(v); units.append(u)
    notes.append("; ".join(x for x in (r["note"], n) if x))
long["value"] = vals
long["unit"] = units
long["note"] = notes
assert set(long["unit"]) - {""} <= CANONICAL_UNITS, set(long["unit"]) - CANONICAL_UNITS

# --- sources -----------------------------------------------------------------------------

obs = pd.read_csv(OBS, dtype={"note": str, "url": str, "source": str})
obs["note"] = obs["note"].fillna("")


def source_key(source, url):
    s = str(source).strip()
    u = str(url).strip() if isinstance(url, str) else ""
    m = re.search(r"https?://\S+", s)
    if not u and m:
        u = m.group(0).rstrip(".,;)")
    return s, u


src_ids = {}
for df in (long, obs):
    for s, u in (source_key(a, b) for a, b in zip(df["source"], df["url"])):
        if (s, u) not in src_ids:
            src_ids[(s, u)] = len(src_ids) + 1
long["source_id"] = [src_ids[source_key(a, b)] for a, b in zip(long["source"], long["url"])]
obs["source_id"] = [src_ids[source_key(a, b)] for a, b in zip(obs["source"], obs["url"])]

# --- wide table -------------------------------------------------------------------------

def get(tech, param):
    """Value of `param`, plus any `param+` component from an ADD gap-fill row."""
    m = long[(long["technology"] == tech) & (long["parameter"] == param)]
    v = float(m["value"].iloc[0]) if len(m) and pd.notna(m["value"].iloc[0]) else np.nan
    a = long[(long["technology"] == tech) & (long["parameter"] == param + "+")]
    if len(a) and pd.notna(a["value"].iloc[0]):
        assert a["unit"].iloc[0] == m["unit"].iloc[0], (tech, param, "ADD unit mismatch")
        v += float(a["value"].iloc[0])
    return v


def get_unit(tech, param):
    m = long[(long["technology"] == tech) & (long["parameter"] == param)]
    return m["unit"].iloc[0] if len(m) else ""


def origin(tech, param):
    m = long[(long["technology"] == tech) & (long["parameter"].isin([param, param + "+"]))]
    if not len(m):
        return ""
    return "gap_fill" if (m["origin"] == "gap_fill").any() else m["origin"].iloc[0]


rows = []
for t in techs:
    k = t["key"]
    capex_kw = get(k, "investment")
    if np.isnan(capex_kw):
        capex_kw = get(k, "investment_kw")
    capex_kwh = get(k, "investment_kwh")
    if get_unit(k, "investment") == "EUR/kWh":      # storage quoted per kWh only
        capex_kwh, capex_kw = capex_kw, np.nan

    def fom_abs(param, base):
        f = get(k, param)
        if np.isnan(f):
            return np.nan
        if get_unit(k, param) == "fraction_of_investment":
            return f * base
        return f

    fom_kw_a = fom_abs("FOM", capex_kw)
    fom_kwh_a = fom_abs("FOM_kwh", capex_kwh)
    if np.isnan(fom_kwh_a) and get_unit(k, "FOM") == "EUR/kWh/a":
        fom_kwh_a, fom_kw_a = get(k, "FOM"), np.nan
    eff = get(k, "efficiency")
    eff2 = get(k, "efficiency_2")
    if not np.isnan(eff2):
        eff = eff * eff2
    if t.get("energy_per_output"):      # fuel store quoted per kWh_fuel -> per kWh_el out
        assert not np.isnan(eff2) and eff2 > 0, f"{k}: energy_per_output needs efficiency_2"
        capex_kwh, fom_kwh_a = capex_kwh / eff2, fom_kwh_a / eff2
    fuel = CFG["fuel_override"].get(k, get(k, "fuel"))
    co2i = CFG["co2_intensity_t_mwh_th"].get(t["td"].get("fuel"), get(k, "co2_intensity")) \
        if t.get("td") else np.nan
    capture = CFG["capture_rate"].get(k, get(k, "capture_rate"))
    if capture is None or (isinstance(capture, float) and np.isnan(capture)):
        capture = 0.0
    lifetime = get(k, "lifetime")
    vom = get(k, "VOM")
    cf = CFG["capacity_factor"].get(k, [np.nan, np.nan])

    lcoe = {}
    if t["kind"] == "generation" and not np.isnan(capex_kw) and not np.isnan(lifetime):
        a = annuity(R, lifetime)
        fuel_term = 0.0
        if not np.isnan(fuel) and not np.isnan(eff) and eff > 0:
            fuel_term = fuel / eff
            if not np.isnan(co2i):
                fuel_term += CFG["co2_price_eur_t"] * co2i * (1 - capture) / eff
        for tag, c in (("cf_low", cf[0]), ("cf_high", cf[1])):
            lcoe[tag] = ((a * capex_kw + (0 if np.isnan(fom_kw_a) else fom_kw_a)) * 1000
                         / (HOURS * c) + (0 if np.isnan(vom) else vom) + fuel_term)
    eur_per_tco2 = np.nan
    if t["kind"] == "dac" and not np.isnan(capex_kw):
        a = annuity(R, lifetime)
        eur_per_tco2 = (a * capex_kw + (0 if np.isnan(fom_kw_a) else fom_kw_a)) \
            / (HOURS * CFG["dac"]["capacity_factor"])

    used = long[long["technology"] == k]
    rows.append({
        "technology": k, "label": t["label"], "group": t["group"], "kind": t["kind"],
        "bar": bool(t.get("bar", True)),
        "capex_kw": capex_kw, "capex_kwh": capex_kwh,
        "fom_kw_a": fom_kw_a, "fom_kwh_a": fom_kwh_a, "vom_mwh": vom,
        "lifetime": lifetime, "efficiency": eff, "fuel_mwh_th": fuel,
        "co2_t_mwh_th": co2i, "capture_rate": capture if capture else np.nan,
        "cf_low": cf[0], "cf_high": cf[1],
        "lcoe_at_cf_low": lcoe.get("cf_low", np.nan),
        "lcoe_at_cf_high": lcoe.get("cf_high", np.nan),
        "cost_per_tco2": eur_per_tco2,
        "capex_origin": origin(k, "investment") or origin(k, "investment_kw")
        or origin(k, "investment_kwh"),
        "source_ids": ";".join(str(i) for i in sorted(set(used["source_id"]))),
        "note": "; ".join(sorted({n for n in used["note"] if n.startswith("n/a") or n.startswith("OVERRIDE")})),
    })
table = pd.DataFrame(rows)

for _, r in table.iterrows():
    if r["kind"] == "generation":
        assert not np.isnan(r["capex_kw"]) or r["note"], f"{r['technology']}: no capex and no n/a note"
    if r["kind"] == "storage":
        assert not (np.isnan(r["capex_kw"]) and np.isnan(r["capex_kwh"])) or r["note"], \
            f"{r['technology']}: no storage capex and no n/a note"

# --- observed points ------------------------------------------------------------------------

METRIC_UNIT = {k: f"{BASE_CUR}/{v}" for k, v in {
    "capex_per_kw": "kW", "capex_per_kwh": "kWh", "lcoe": "MWh", "fom": "kW/a",
    "vom": "MWh", "cost_per_tco2": "tCO2"}.items()}
unknown = set(obs["technology"]) - {t["key"] for t in techs}
assert not unknown, f"observed technologies not in config: {unknown}"
assert set(obs["metric"]) <= set(METRIC_UNIT), set(obs["metric"]) - set(METRIC_UNIT)
assert set(obs["point_type"]) <= {"final_cost", "estimate", "ppa_price", "weighted_average",
                                  "benchmark_range_low", "benchmark_range_high"}, \
    set(obs["point_type"])

vals, notes = [], []
for _, r in obs.iterrows():
    v = float(r["value"])
    rest = split_currency(str(r["unit"]).strip())[1].replace(" ", "").lower()
    if r["metric"] in ("lcoe", "vom") and rest in ("kwh", "kwh_e"):
        v *= 1000                                   # /kWh -> /MWh
    elif r["metric"] in ("capex_per_kw",) and rest in ("mw", "mw_e"):
        v /= 1000
    elif r["metric"] == "capex_per_kwh" and rest in ("mwh", "mwh_e"):
        v /= 1000
    elif r["metric"] == "fom" and re.fullmatch(r"kw(_e)?[/-](a|yr|year)", rest) is None:
        raise ValueError(f"observed fom unit {r['unit']!r}")
    e, n = to_base(v, r["currency"], r["currency_year"])
    vals.append(e); notes.append("; ".join(x for x in (r["note"], n) if x))
obs["value_base"] = vals
obs["unit_base"] = obs["metric"].map(METRIC_UNIT)
obs["note"] = notes

# --- write ------------------------------------------------------------------------------------

long = long[["technology", "parameter", "value", "unit", "value_orig", "unit_orig", "currency",
             "currency_year_orig", "origin", "source_id", "source", "url", "note"]]
long.to_csv(OUT_COMPILED, index=False)
table.to_csv(OUT_TABLE, index=False)
obs.to_csv(OUT_OBS, index=False)

lines = [f"# Sources (compiled {pd.Timestamp.today():%Y-%m-%d}; all costs in {BASE_CUR}{BASE_YEAR})", ""]
for (s, u), i in sorted(src_ids.items(), key=lambda x: x[1]):
    lines.append(f"[{i}] {s}" + (f" — <{u}>" if u and u not in s else ""))
OUT_SOURCES.write_text("\n".join(lines) + "\n")

print(f"{len(table)} technologies, {len(long)} parameters, {len(obs)} observed points, "
      f"{len(src_ids)} sources")
print(table[["technology", "capex_kw", "capex_kwh", "fom_kw_a", "vom_mwh", "lifetime",
             "lcoe_at_cf_high", "lcoe_at_cf_low", "cost_per_tco2", "capex_origin"]]
      .to_string(index=False, float_format=lambda x: f"{x:,.1f}"))
