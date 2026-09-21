"""Classify every row of country_features.csv into a SOW power-system archetype.

Initial proposition: a transparent rule-based decision tree over the feature
columns, assigning each grid to one of the five archetypes defined in
land-grid-map/data/archetypes.js:

    dense       renewables-constrained, high-density (W. Europe, Korea, Japan)
    geothermal  geothermal-favourable (US West, SE Asia, Turkey, Italy)
    islanded    islanded / weak interconnection (SWIS, island states)
    hydro       hydro-rich clean-firm incumbents (Norway, Brazil, Canada)
    fossil      fossil-heavy brownfield, interconnected (India, China, US East)

Rules fire in order (first match wins) - the order encodes priorities:
extreme density first (city-states are land-constrained whatever they burn),
geothermal before hydro (Iceland is the geothermal exemplar despite 71%
hydro), overwhelming fossil before islanded/dense. Every row also gets five
continuous membership scores (0-1); `proximity` is the score of the assigned
archetype (how representative the row is), `rule_fired` says which branch
decided - both make threshold tuning a diff instead of a debugging session.

Known edge case, documented rather than patched: Ireland lands in fossil, not
the SOW's "islanded" - the data is defensible (GB interconnectors, 16% import
share).

Outputs: country_archetypes.csv and land-grid-map/data/layers/rules-v1.js
(a "data version" for the land grid map, countries keyed by UN M49 id).

Run via `snakemake -c1` (rule classify) or standalone:
  models/priam-myopic/.pixi/envs/default/bin/python classify.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

if "snakemake" in globals():
    FEATURES = Path(snakemake.input.features)
    ISO = Path(snakemake.input.iso)
    OUT_TABLE = Path(snakemake.output.table)
    OUT_LAYER = Path(snakemake.output.layer)
else:
    _HERE = Path(__file__).parent
    FEATURES = _HERE / "country_features.csv"
    ISO = _HERE / "data" / "iso3166.csv"
    OUT_TABLE = _HERE / "country_archetypes.csv"
    OUT_LAYER = _HERE / "land-grid-map" / "data" / "layers" / "rules-v1.js"

ARCHETYPE_IDS = ["dense", "geothermal", "islanded", "hydro", "fossil"]

# explicit archetype overrides by grid code (none at the moment)
OVERRIDES = {}

# sub-national rows (USE/USW, AUN/AUW, MYW/MYE) and the merged North-West Europe
# row (NWE, merge_nwe.py) have their own geometry on the map
# (land-grid-map/data/regions.js, built by build_regions.py) and are keyed by
# their iso3 code; the parent countries are not drawn.
REGION_ROWS = {"USE", "USW", "AUN", "AUW", "MYW", "MYE", "NWE"}


def ramp(x, lo, hi):
    """Clipped linear score in [0, 1]; NaN maps to 0."""
    if pd.isna(x):
        return 0.0
    return float(np.clip((x - lo) / (hi - lo), 0.0, 1.0))


def scores(r):
    """Continuous membership per archetype, each in [0, 1]."""
    return {
        "hydro": ramp(r.share_hydro_pct, 20, 80),
        "fossil": ramp(r.share_fossil_pct, 40, 90),
        "geothermal": (
            0.5 * max(ramp(np.log10(r.geothermal_capacity_mw + 1), 1, 3.3),
                      ramp(r.egs_suitable_share, 0.05, 0.5))
            + 0.5 * ramp(r.t5km_p90_c, 150, 300)),
        "dense": max(
            float(np.mean([ramp(r.pop_density_per_km2, 100, 500),
                           ramp(r.demand_kwh_per_capita, 2000, 8000),
                           1 - ramp(r.pvout_kwh_per_kwp_day, 3.2, 4.8)])),
            ramp(r.nuclear_f, 20, 60)),
        "islanded": float(np.mean([
            1.0 if r.is_island else (0.5 if r.n_land_borders <= 1 else 0.0),
            1 - ramp(abs(r.imports_f), 0, 15),
            1 - ramp(r.demand_twh, 10, 500)])),
    }


def classify_row(r):
    if r.iso3 in OVERRIDES:
        return OVERRIDES[r.iso3], "override"
    # R1 city-states: extreme density trumps everything (Singapore)
    if r.pop_density_per_km2 >= 2000:
        return "dense", "R1"
    # R2 geothermal before hydro (Iceland: 788 MW geo, 71% hydro). The
    # 500 MW line keeps Japan (469 MW) in dense; the guards keep France
    # (nuclear), Japan again (density) and Ethiopia (hydro) out of the
    # EGS branch.
    if (r.geothermal_capacity_mw >= 500
            or (r.egs_suitable_share >= 0.15 and r.nuclear_f < 20
                and r.hydro_f < 40 and r.pop_density_per_km2 < 200)):
        return "geothermal", "R2"
    # R3 hydro-rich clean-firm incumbents (Sweden 40.1% stays in)
    if r.hydro_f >= 40:
        return "hydro", "R3"
    # R4 overwhelming fossil pre-empts dense/islanded (MYW 90%, India 73%)
    if r.fossil_f >= 70:
        return "fossil", "R4"
    # R5 islanded: physically isolated, self-supplied, not a giant (AUW;
    # AUN at 266 TWh deliberately falls through - the SOW names the SWIS)
    if ((r.is_island or r.n_land_borders == 0)
            and abs(r.imports_f) < 5 and r.demand_twh < 250):
        return "islanded", "R5"
    # R6 dense: RE-constrained rich grids, or nuclear-dominated (France).
    # 4000 kWh/cap keeps Vietnam (3087, 55% fossil) in fossil via R7.
    if ((r.pop_density_per_km2 >= 200 and r.demand_kwh_per_capita >= 4000
            and r.pvout_kwh_per_kwp_day < 4.2) or r.nuclear_f >= 40):
        return "dense", "R6"
    # R7 fossil, looser (Vietnam 54.6%)
    if r.fossil_f >= 50:
        return "fossil", "R7"
    # R8 fallback: nearest archetype by membership score
    s = scores(r)
    return max(s, key=s.get), "R8"


def size_tier(demand_twh):
    if pd.isna(demand_twh) or demand_twh < 1:
        return "micro"
    if demand_twh < 10:
        return "small"
    if demand_twh < 100:
        return "medium"
    if demand_twh < 1000:
        return "large"
    return "giga"


df = pd.read_csv(FEATURES)

# --- power-sector CO2 (Ember yearly release), reference year with full coverage ------------
EMBER = (_HERE if "snakemake" not in globals() else FEATURES.parent) / "data" / "yearly_full_release_long_format.csv"
EMISSIONS_YEAR = 2024
SPLITS = {"USA": ["USE", "USW"], "AUS": ["AUN", "AUW"], "MYS": ["MYW", "MYE"]}
MERGES = {"NWE": ["IRL", "GBR", "FRA", "BEL", "NLD", "LUX", "DEU", "DNK", "CHE", "AUT", "CZE", "POL"]}   # merge_nwe.py
FUEL_COLS = {"Coal": "gen_coal_twh", "Gas": "gen_gas_twh", "Other Fossil": "gen_other_fossil_twh"}


def load_emissions():
    e = pd.read_csv(EMBER, usecols=["ISO 3 code", "Year", "Area type", "Category", "Variable", "Unit", "Value"])
    e = e[(e["Category"] == "Power sector emissions") & (e["Unit"] == "mtCO2")
          & (e["Area type"] == "Country or economy") & (e["Year"] <= EMISSIONS_YEAR)]
    e = e.sort_values("Year").groupby(["ISO 3 code", "Variable"]).tail(1)   # latest year <= reference
    piv = e.pivot(index="ISO 3 code", columns="Variable", values="Value")
    yr = e[e["Variable"] == "Total emissions"].set_index("ISO 3 code")["Year"]
    return piv, yr


ember, ember_year = load_emissions()
child_of = {c: p for p, cs in SPLITS.items() for c in cs}


def row_emissions(r):
    """(mtCO2, year) for a national row from Ember; sub-national rows share the parent's
    per-fuel emissions in proportion to their fossil generation by fuel; a merged row sums
    its members."""
    if r.iso3 in ember.index:
        return float(ember.at[r.iso3, "Total emissions"]), int(ember_year[r.iso3])
    if r.iso3 in MERGES:
        mem = [i for i in MERGES[r.iso3] if i in ember.index]
        return float(sum(ember.at[i, "Total emissions"] for i in mem)), int(max(ember_year[i] for i in mem))
    p = child_of.get(r.iso3)
    if p is None or p not in ember.index:
        return np.nan, np.nan
    sibs = df[df["iso3"].isin(SPLITS[p])]
    em = 0.0
    for fuel, col in FUEL_COLS.items():
        nat = float(ember.at[p, fuel]) if fuel in ember.columns and pd.notna(ember.at[p, fuel]) else 0.0
        tot = float(sibs[col].fillna(0).sum())
        mine = float(getattr(r, col)) if pd.notna(getattr(r, col)) else 0.0
        em += nat * (mine / tot if tot > 0 else 1.0 / len(sibs))
    return em, int(ember_year[p])


df["nuclear_f"] = df["share_nuclear_pct"].fillna(0.0)
df["hydro_f"] = df["share_hydro_pct"].fillna(0.0)
df["fossil_f"] = df["share_fossil_pct"].fillna(0.0)
df["imports_f"] = df["net_import_share_pct"].fillna(0.0)

records = []
for r in df.itertuples(index=False):
    arch, rule = classify_row(r)
    s = scores(r)
    em, em_year = row_emissions(r)
    records.append({
        "iso3": r.iso3, "iso2": r.iso2, "name": r.name,
        "archetype": arch, "rule_fired": rule,
        "proximity": round(float(np.clip(s[arch], 0.05, 1.0)), 3),
        "size_tier": size_tier(r.demand_twh),
        "population": r.population, "demand_twh": r.demand_twh,
        "emissions_mt": round(em, 2) if pd.notna(em) else np.nan, "emissions_year": em_year,
        **{f"score_{a}": round(s[a], 3) for a in ARCHETYPE_IDS},
    })
out = pd.DataFrame(records)

missing = set(ARCHETYPE_IDS) - set(out["archetype"])
if missing:
    raise SystemExit(f"empty archetypes: {missing}")
out.to_csv(OUT_TABLE, index=False)

# --- land-grid-map data version ----------------------------------------------

iso = pd.read_csv(ISO, dtype={"country-code": str})
m49 = dict(zip(iso["alpha-3"], iso["country-code"]))  # zero-padded strings

by_iso3 = out.set_index("iso3")


def map_key(iso3):
    """Key used by the map: iso3 for split regions, else the M49 numeric id."""
    return iso3 if iso3 in REGION_ROWS else m49.get(iso3)


countries = {}
for iso3, row in by_iso3.iterrows():
    key = map_key(iso3)
    if key is not None:
        countries[key] = {"archetype": row["archetype"],
                          "proximity": float(row["proximity"])}

# modelled country per archetype: for now a seeded random draw among the
# medium-or-larger grids classified into that archetype (placeholder until
# the WP1 country mapping is fixed). Change MODELLED_SEED for another draw;
# sub-national rows are skipped because the map has no geometry for them.
MODELLED_SEED = 0
MODELLED_MIN_AREA_KM2 = 50_000   # visible on the world map (excludes city-states)
# fixed choice per archetype (iso3 / grid code); None -> seeded random draw below
MODELLED_FIXED = {"dense": "NWE", "geothermal": "USW", "islanded": "AUW",
                  "hydro": "BRA", "fossil": "USE"}
rng = np.random.default_rng(MODELLED_SEED)
area = dict(zip(df["iso3"], df["land_area_km2"].fillna(0.0)))
MODELLED = {}
for a in ARCHETYPE_IDS:
    if MODELLED_FIXED and MODELLED_FIXED.get(a):
        iso3 = MODELLED_FIXED[a]
        assert by_iso3.at[iso3, "archetype"] == a, \
            f"fixed modelled grid {iso3} classifies as {by_iso3.at[iso3, 'archetype']}, not {a}"
        MODELLED[a] = iso3
        continue
    pool = out[(out["archetype"] == a)
               & out["size_tier"].isin(["medium", "large", "giga"])
               & out["iso3"].map(lambda x: map_key(x) is not None)
               & out["iso3"].map(lambda x: area.get(x, 0) >= MODELLED_MIN_AREA_KM2)]
    if pool.empty:
        pool = out[(out["archetype"] == a) & out["iso3"].map(lambda x: map_key(x) is not None)]
    MODELLED[a] = str(rng.choice(pool["iso3"].to_numpy()))
modelled = {a: map_key(iso3) for a, iso3 in MODELLED.items()}
modelled_names = ", ".join(
    f"{by_iso3.at[iso3, 'name']} ({a})" for a, iso3 in MODELLED.items())

# per-archetype totals over all classified rows (sub-national rows count with their own
# archetype), for the stacked share bars next to the colour wheel
QUANTITIES = {"population": "population", "demand_twh": "demand_twh", "emissions_mt": "emissions_mt"}
totals = {q: {a: float(out.loc[out["archetype"] == a, col].fillna(0).sum()) for a in ARCHETYPE_IDS}
          for q, col in QUANTITIES.items()}
# share of each quantity sitting in the modelled countries (one per archetype)
modelled_rows = out["iso3"].isin(MODELLED.values())
modelled_totals = {q: float(out.loc[modelled_rows, col].fillna(0).sum()) for q, col in QUANTITIES.items()}
totals_meta = {
    "population": {"label": "Population", "unit": "people", "year": "2025", "source": "World Bank WDI 2025"},
    "demand_twh": {"label": "Electricity consumption", "unit": "TWh", "year": "2024/25 (latest available)",
                   "source": "Ember / UN energy statistics 2024"},
    "emissions_mt": {"label": "Power-sector CO₂", "unit": "MtCO₂", "year": str(EMISSIONS_YEAR),
                     "source": f"Ember yearly release, {EMISSIONS_YEAR} (latest year where missing); "
                               "sub-national grids apportioned by fossil generation"},
    "coverage": f"{len(out)} classified grids, {int(out['emissions_mt'].notna().sum())} with emissions data",
}

# --- "Rule-based" tab of the map: features with thresholds, the ordered rules and every grid's
# decision path, so the page can show why each grid landed where it did.
def _norm(v, scale):
    kind, lo, hi = scale
    if pd.isna(v):
        return 0.0
    if kind == "log":
        v, lo, hi = np.log10(max(v, 1e-9) + (1 if lo <= 1 else 0)), np.log10(lo + (1 if lo <= 1 else 0)), np.log10(hi + (1 if lo <= 1 else 0))
    return float(np.clip((v - lo) / (hi - lo), 0.0, 1.0))


RULE_FEATURES = [
    {"id": "density", "label": "Population density", "unit": "people/km²", "col": "pop_density_per_km2",
     "scale": ["log", 1, 10000], "thresholds": [200, 2000], "fmt": "{:,.0f}",
     "desc": "People per km² of land. Land constraint on renewables: ≥ 2000 is a city-state (R1), ≥ 200 is one of the three dense-grid conditions (R6) and < 200 is a guard on the EGS branch (R2)."},
    {"id": "geo_mw", "label": "Geothermal capacity", "unit": "MW", "col": "geothermal_capacity_mw",
     "scale": ["log", 1, 10000], "thresholds": [500], "fmt": "{:,.0f}",
     "desc": "Installed geothermal power capacity. ≥ 500 MW classifies as geothermal-favourable outright (R2); the line keeps Japan (469 MW) out."},
    {"id": "egs", "label": "EGS-suitable land", "unit": "share", "col": "egs_suitable_share",
     "scale": ["lin", 0, 1], "thresholds": [0.15], "fmt": "{:.2f}",
     "desc": "Share of the land area whose temperature at 5 km depth makes enhanced geothermal plausible. ≥ 0.15 opens the EGS branch of R2, guarded by nuclear, hydro and density."},
    {"id": "hydro", "label": "Hydro share", "unit": "% of generation", "col": "hydro_f",
     "scale": ["lin", 0, 100], "thresholds": [40], "fmt": "{:.0f}",
     "desc": "Hydro share of today's generation. ≥ 40 % is hydro-rich (R3); < 40 % is a guard on the EGS branch (R2)."},
    {"id": "nuclear", "label": "Nuclear share", "unit": "% of generation", "col": "nuclear_f",
     "scale": ["lin", 0, 100], "thresholds": [20, 40], "fmt": "{:.0f}",
     "desc": "Nuclear share of today's generation. ≥ 40 % counts as dense / RE-constrained (R6, France); < 20 % is a guard on the EGS branch (R2)."},
    {"id": "fossil", "label": "Fossil share", "unit": "% of generation", "col": "fossil_f",
     "scale": ["lin", 0, 100], "thresholds": [50, 70], "fmt": "{:.0f}",
     "desc": "Coal, gas and oil share of today's generation. ≥ 70 % is fossil-heavy before the islanded and dense rules get a say (R4); ≥ 50 % after them (R7)."},
    {"id": "isolation", "label": "Physical isolation", "unit": "", "col": None,
     "scale": ["lin", 0, 1], "thresholds": [], "fmt": None,
     "desc": "Island, or a mainland grid without land borders, both count as isolated for the islanded rule (R5). Shown as 1 = isolated, 0.5 = one land border, 0 = more."},
    {"id": "imports", "label": "Net import share", "unit": "% of demand, absolute", "col": "imports_f",
     "scale": ["lin", 0, 30], "thresholds": [5], "fmt": "{:.0f}",
     "desc": "Net electricity imports as a share of demand, sign ignored. < 5 % is self-supplied for the islanded rule (R5)."},
    {"id": "demand", "label": "Electricity demand", "unit": "TWh", "col": "demand_twh",
     "scale": ["log", 1, 10000], "thresholds": [250], "fmt": "{:,.0f}",
     "desc": "Today's electricity consumption. < 250 TWh is the size cap of the islanded rule (R5): Australia NEM at 266 TWh falls through deliberately."},
    {"id": "kwh_pc", "label": "Demand per capita", "unit": "kWh/cap", "col": "demand_kwh_per_capita",
     "scale": ["log", 100, 20000], "thresholds": [4000], "fmt": "{:,.0f}",
     "desc": "Electricity consumption per person. ≥ 4000 kWh/cap is one of the three dense-grid conditions (R6); it keeps Vietnam (3087) in fossil."},
    {"id": "pvout", "label": "Solar yield", "unit": "kWh/kWp/day", "col": "pvout_kwh_per_kwp_day",
     "scale": ["lin", 2.5, 5.5], "thresholds": [4.2], "fmt": "{:.1f}",
     "desc": "Practical PV output per installed kWp (Global Solar Atlas). < 4.2 marks a poor solar resource, one of the three dense-grid conditions (R6)."},
]
for f in RULE_FEATURES:
    f["ticks"] = [_norm(t, f["scale"]) for t in f["thresholds"]]

RULES = [
    {"id": "R1", "archetype": "dense", "title": "City-state",
     "cond": "population density ≥ 2000 /km²",
     "note": "Extreme density trumps everything a grid burns (Singapore, Hong Kong)."},
    {"id": "R2", "archetype": "geothermal", "title": "Geothermal",
     "cond": "geothermal capacity ≥ 500 MW, or EGS-suitable land ≥ 0.15 with nuclear < 20 %, hydro < 40 % and density < 200 /km²",
     "note": "Sits before hydro so Iceland (788 MW, 71 % hydro) is the geothermal exemplar. The guards keep France (nuclear), Japan (density) and Ethiopia (hydro) out of the EGS branch."},
    {"id": "R3", "archetype": "hydro", "title": "Hydro-rich",
     "cond": "hydro share ≥ 40 %",
     "note": "Clean-firm incumbents; Sweden at 40.1 % stays in."},
    {"id": "R4", "archetype": "fossil", "title": "Overwhelming fossil",
     "cond": "fossil share ≥ 70 %",
     "note": "Pre-empts the islanded and dense rules (Peninsular Malaysia 90 %, India 73 %)."},
    {"id": "R5", "archetype": "islanded", "title": "Islanded",
     "cond": "island or no land border, |net imports| < 5 % of demand, demand < 250 TWh",
     "note": "Physically isolated, self-supplied and not a giant (Western Australia). The NEM at 266 TWh falls through: the SOW names the SWIS."},
    {"id": "R6", "archetype": "dense", "title": "Dense / RE-constrained",
     "cond": "density ≥ 200 /km² and demand ≥ 4000 kWh/cap and solar yield < 4.2 kWh/kWp/day, or nuclear ≥ 40 %",
     "note": "Rich, crowded, poorly-lit grids, or nuclear-dominated ones (France). 4000 kWh/cap keeps Vietnam in fossil via R7."},
    {"id": "R7", "archetype": "fossil", "title": "Fossil, looser",
     "cond": "fossil share ≥ 50 %",
     "note": "Catches the remaining fossil-dominated grids (Vietnam 55 %)."},
    {"id": "R8", "archetype": None, "title": "Fallback",
     "cond": "nearest archetype by membership score",
     "note": "Five continuous 0–1 membership scores (below); the highest wins."},
]

SCORE_DESC = {
    "hydro": "hydro share ramped 20 → 80 %",
    "fossil": "fossil share ramped 40 → 90 %",
    "geothermal": "½ · max(log10 geothermal MW ramped 1 → 3.3, EGS share ramped 0.05 → 0.5) + ½ · T at 5 km (p90) ramped 150 → 300 °C",
    "dense": "max(mean of density 100 → 500 /km², demand 2000 → 8000 kWh/cap, poor solar 4.8 → 3.2 kWh/kWp/day; nuclear 20 → 60 %)",
    "islanded": "mean of isolation (island 1, one border ½), self-supply (|imports| 15 → 0 %), smallness (demand 500 → 10 TWh)",
}


def _cmp(v, op, t, fmt):
    ok = v >= t if op == "≥" else v < t
    return ok, f"{fmt.format(v)} {'≥' if v >= t else '<'} {fmt.format(t)}"


def _isolation(r):
    if r.is_island:
        return 1.0, "island"
    n = 0 if pd.isna(r.n_land_borders) else int(r.n_land_borders)
    return (1.0 if n == 0 else 0.5 if n == 1 else 0.0), ("no land border" if n == 0 else f"{n} land border{'s' if n > 1 else ''}")


def decision_path(r):
    """[{rule, pass, why}] up to and including the rule that fired (mirrors classify_row)."""
    d, mw, egs = r.pop_density_per_km2, r.geothermal_capacity_mw, r.egs_suitable_share
    d = 0.0 if pd.isna(d) else d
    mw = 0.0 if pd.isna(mw) else mw
    egs = 0.0 if pd.isna(egs) else egs
    pv = r.pvout_kwh_per_kwp_day
    iso_v, iso_t = _isolation(r)
    path = []

    def step(rid, ok, why):
        path.append({"rule": rid, "pass": bool(ok), "why": why})
        return ok

    if r.iso3 in OVERRIDES:
        return [{"rule": "override", "pass": True, "why": f"manual override → {OVERRIDES[r.iso3]}"}]
    ok, t = _cmp(d, "≥", 2000, "{:,.0f}")
    if step("R1", ok, f"density {t} /km²"):
        return path
    if mw >= 500:
        step("R2", True, f"geothermal {mw:,.0f} MW ≥ 500"); return path
    guards = [("nuclear", r.nuclear_f < 20, f"nuclear {r.nuclear_f:.0f} % {'<' if r.nuclear_f < 20 else '≥'} 20"),
              ("hydro", r.hydro_f < 40, f"hydro {r.hydro_f:.0f} % {'<' if r.hydro_f < 40 else '≥'} 40"),
              ("density", d < 200, f"density {d:,.0f} {'<' if d < 200 else '≥'} 200")]
    if egs >= 0.15 and all(g[1] for g in guards):
        step("R2", True, f"EGS share {egs:.2f} ≥ 0.15; " + ", ".join(g[2] for g in guards)); return path
    why = f"geothermal {mw:,.0f} MW < 500; EGS share {egs:.2f} " + (
        "< 0.15" if egs < 0.15 else "≥ 0.15 but " + ", ".join(g[2] for g in guards if not g[1]))
    step("R2", False, why)
    ok, t = _cmp(r.hydro_f, "≥", 40, "{:.0f}")
    if step("R3", ok, f"hydro {t} %"):
        return path
    ok, t = _cmp(r.fossil_f, "≥", 70, "{:.0f}")
    if step("R4", ok, f"fossil {t} %"):
        return path
    parts = [(iso_v >= 1.0, iso_t),
             (abs(r.imports_f) < 5, f"|imports| {abs(r.imports_f):.0f} % {'<' if abs(r.imports_f) < 5 else '≥'} 5"),
             (r.demand_twh < 250, f"demand {r.demand_twh:,.0f} TWh {'<' if r.demand_twh < 250 else '≥'} 250")]
    ok = all(p[0] for p in parts)
    if step("R5", ok, "; ".join(p[1] for p in parts) if ok else "; ".join(p[1] for p in parts if not p[0])):
        return path
    dense3 = [(d >= 200, f"density {d:,.0f} {'≥' if d >= 200 else '<'} 200"),
              (r.demand_kwh_per_capita >= 4000, f"{r.demand_kwh_per_capita:,.0f} kWh/cap {'≥' if r.demand_kwh_per_capita >= 4000 else '<'} 4000"),
              (pd.notna(pv) and pv < 4.2, f"solar {pv:.1f} {'<' if pd.notna(pv) and pv < 4.2 else '≥'} 4.2" if pd.notna(pv) else "solar yield unknown")]
    nuc = r.nuclear_f >= 40
    if all(p[0] for p in dense3):
        step("R6", True, "; ".join(p[1] for p in dense3)); return path
    if nuc:
        step("R6", True, f"nuclear {r.nuclear_f:.0f} % ≥ 40"); return path
    step("R6", False, "; ".join(p[1] for p in dense3 if not p[0]) + f"; nuclear {r.nuclear_f:.0f} % < 40")
    ok, t = _cmp(r.fossil_f, "≥", 50, "{:.0f}")
    if step("R7", ok, f"fossil {t} %"):
        return path
    s = scores(r)
    best = max(s, key=s.get)
    step("R8", True, f"highest membership score: {best} ({s[best]:.2f})")
    return path


rows = []
for r in df.itertuples(index=False):
    o = by_iso3.loc[r.iso3]
    vals, disp = [], []
    for f in RULE_FEATURES:
        if f["id"] == "isolation":
            v, t = _isolation(r)
            vals.append(round(v, 3)); disp.append(t)
            continue
        raw = getattr(r, f["col"])
        raw = abs(raw) if f["id"] == "imports" else raw
        vals.append(round(_norm(raw, f["scale"]), 3))
        disp.append("n/a" if pd.isna(raw) else f["fmt"].format(raw) + (" " + f["unit"] if f["unit"] else ""))
    path = decision_path(r)
    assert path[-1]["rule"] == o["rule_fired"], (r.iso3, path[-1]["rule"], o["rule_fired"])
    rows.append({
        "key": map_key(r.iso3), "iso3": r.iso3, "name": r.name,
        "archetype": o["archetype"], "rule": o["rule_fired"], "proximity": float(o["proximity"]),
        "demand_twh": round(float(r.demand_twh), 1) if pd.notna(r.demand_twh) else 0.0,
        "v": vals, "disp": disp, "path": path,
        "scores": {a: float(o[f"score_{a}"]) for a in ARCHETYPE_IDS},
    })
explain = {
    "kind": "rules",
    "features": [{k: f[k] for k in ("id", "label", "unit", "desc", "ticks", "thresholds")} for f in RULE_FEATURES],
    "rules": RULES,
    "scores": SCORE_DESC,
    "rows": rows,
    "method": ("A transparent decision tree over the feature table. The rules on the right are tried in order "
               "and the first one that matches decides the archetype, so the order encodes priorities: "
               "extreme density first, geothermal before hydro, overwhelming fossil before the islanded and "
               "dense rules. Grids no rule catches fall back to the nearest of five continuous membership "
               "scores. Every threshold is a plain number on a raw feature, which makes tuning a diff rather "
               "than a retraining."),
}

layer = {
    "id": "rules-v1",
    "name": "Rule-based v1",
    "description": (
        "Decision-tree classification from country_features.csv "
        "(misc-quarter1/country-classification/classify.py). The US (East incl. ERCOT / West), Australia "
        "(NEM / SWIS) and Malaysia (Peninsular / Borneo) are split into their grids; Ireland, the UK, France, Benelux, Germany, Denmark, Switzerland, Austria, Czechia and Poland "
        "are merged into one North-West Europe grid (merge_nwe.py, as in config.NWE.yaml). "
        + (f"Modelled grids: {modelled_names}." if MODELLED_FIXED else
           f"Modelled countries are a random placeholder draw (seed {MODELLED_SEED}): {modelled_names}.")),
    "archetypes": ARCHETYPE_IDS,
    "modelled": modelled,
    "countries": countries,
    "totals": totals,
    "modelled_totals": modelled_totals,
    "totals_meta": totals_meta,
    "explain": explain,
}
OUT_LAYER.parent.mkdir(parents=True, exist_ok=True)
OUT_LAYER.write_text(
    "// GENERATED by classify.py — rule-based archetype data version.\n"
    "window.LAYERS = window.LAYERS || [];\n"
    "window.LAYERS.push(" + json.dumps(layer, ensure_ascii=False, indent=1)
    + ");\n")

print(out["archetype"].value_counts().to_string())
print(out["rule_fired"].value_counts().to_string())
print(f"-> {OUT_TABLE} ({len(out)} rows), {OUT_LAYER} "
      f"({len(countries)} map countries)")
