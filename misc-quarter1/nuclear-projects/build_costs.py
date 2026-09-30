"""Project cost estimates in a common currency, joined to the GEM sites.

data/project_costs.csv is hand-collected (one row per project and estimate
kind, figure in the currency it was reported in, source URL). This script
converts every figure to the base currency and year (ECB annual-average rate
of the estimate year, then US CPI), divides by the covered capacity, and
attaches the site's coordinates, family and status from build/nuclear_sites.csv.

Inputs   data/project_costs.csv
         data/nea_benchmarks.csv        NEA/IEA published overnight costs (passed through, converted)
         data/ecb_fx_annual.csv         ECB reference rates, annual averages (units per EUR)
         data/ecb_fx_monthly.csv        monthly averages, to fill the current (incomplete) year
         build/nuclear_sites.csv, build/nuclear_units.csv
Outputs  build/project_costs.csv        one row per (project, estimate kind), USD2024 and USD/kW
         build/nea_benchmarks.csv
Standalone: python build_costs.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).parent
if "snakemake" in globals():
    CFG = snakemake.config
    COSTS, NEA, FX, FX_M, SITES, UNITS = (Path(snakemake.input[k]) for k in ("costs", "nea", "fx", "fx_monthly", "sites", "units"))
    OUT, OUT_NEA = Path(snakemake.output.costs), Path(snakemake.output.nea)
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    COSTS, NEA, FX = HERE / "data/project_costs.csv", HERE / "data/nea_benchmarks.csv", HERE / "data/ecb_fx_annual.csv"
    FX_M = HERE / "data/ecb_fx_monthly.csv"
    SITES, UNITS = HERE / "build/nuclear_sites.csv", HERE / "build/nuclear_units.csv"
    OUT, OUT_NEA = HERE / "build/project_costs.csv", HERE / "build/nea_benchmarks.csv"


def fx_table():
    """{currency: {year: units per EUR}} from the ECB file plus config overrides."""
    ecb = pd.read_csv(FX)
    table = {"EUR": {}}
    for cur, g in ecb.groupby("CURRENCY"):
        table[cur] = dict(zip(g["TIME_PERIOD"].astype(int), g["OBS_VALUE"].astype(float)))
    monthly = pd.read_csv(FX_M)
    monthly["year"] = monthly["TIME_PERIOD"].str[:4].astype(int)
    for (cur, year), g in monthly.groupby(["CURRENCY", "year"]):
        table.setdefault(cur, {}).setdefault(year, g["OBS_VALUE"].astype(float).mean())   # partial-year mean
    for cur, years in CFG.get("fx_units_per_eur_override", {}).items():
        table.setdefault(cur, {}).update({int(y): float(v) for y, v in years.items()})
    years = set().union(*(set(v) for v in table.values()))
    table["EUR"] = {y: 1.0 for y in years}
    return table


def make_to_base(fx):
    base, base_year, cpi = CFG["base_currency"], int(CFG["base_currency_year"]), CFG["cpi"][CFG["base_currency"]]

    def to_base(value, currency, year):
        if pd.isna(value) or pd.isna(year):
            return np.nan
        year = int(year)
        if currency not in fx or year not in fx[currency]:
            raise ValueError(f"no FX rate for {currency} {year}")
        if year not in cpi:
            raise ValueError(f"no CPI for {base} {year}")
        eur = value / fx[currency][year]
        return eur * fx[base][year] * cpi[base_year] / cpi[year]

    return to_base


def main():
    fx = fx_table()
    to_base = make_to_base(fx)
    base = f"{CFG['base_currency'].lower()}{CFG['base_currency_year']}"

    costs = pd.read_csv(COSTS, dtype={"gem_location_id": str})
    costs["estimate_year"] = pd.to_numeric(costs["estimate_date"].astype(str).str[:4], errors="coerce")
    # the price year of a figure: stated money-of-year if given, else the year of the estimate
    costs["price_year"] = costs["price_year"].where(costs["price_year"].notna(), costs["estimate_year"])
    mult = costs["cost_unit"].map({"bn": 1e3, "m": 1.0})
    costs[f"cost_m{base}"] = [to_base(v * k, c, y) for v, k, c, y in
                              zip(costs["cost_value"], mult, costs["currency"], costs["price_year"])]
    costs[f"{base}_per_kw"] = costs[f"cost_m{base}"] * 1e3 / costs["capacity_mw_covered"]

    sites = pd.read_csv(SITES, dtype={"gem_location_id": str})
    site_cols = ["gem_location_id", "status_group", "families", "models", "lat", "lon", "region", "subregion"]
    # a site appears once per status group; prefer construction > operating > planned > paused > ended
    order = {"construction": 0, "operating": 1, "planned": 2, "paused": 3, "ended": 4}
    one = (sites.assign(_o=sites["status_group"].map(order)).sort_values("_o")
           .drop_duplicates("gem_location_id")[site_cols])
    out = costs.merge(one, on="gem_location_id", how="left")
    # status of the costed units, unless the data file states it: a final cost means built; a
    # site with nothing open is cancelled; otherwise the site's most advanced open stage
    # (construction before planned), so a phase-II row at an operating site reads as
    # construction / planned rather than operating
    groups = sites.groupby("gem_location_id")["status_group"].agg(set)
    def unit_status(r):
        if isinstance(r["units_status"], str):
            return r["units_status"]
        g = groups.get(r["gem_location_id"], set())
        if r["estimate_kind"] == "final" or g <= {"operating", "paused"}:
            return "built"
        if g <= {"ended", "paused"}:
            return "cancelled"
        return "construction" if "construction" in g else "planned"
    out["units_status"] = out.apply(unit_status, axis=1)
    # family of the costed units, unless the data file states it: the family with the most MW
    # among the site's units in that status
    units = pd.read_csv(UNITS, dtype={"gem_location_id": str})
    status_of = {"built": "operating", "construction": "construction", "planned": "planned", "cancelled": "ended"}
    fam_mw = units.groupby(["gem_location_id", "status_group", "family"])["capacity_mw"].sum()
    def unit_family(r):
        if isinstance(r["family"], str):
            return r["family"]
        key = (r["gem_location_id"], status_of[r["units_status"]])
        if key in fam_mw.index:
            return fam_mw.loc[key].idxmax()
        return str(r["families"]).split("/")[0]
    out["family"] = out.apply(unit_family, axis=1)
    missing = out[out["gem_location_id"].notna() & out["lat"].isna()]
    if len(missing):
        print("no site match for:", missing["project"].tolist())
    out = out.sort_values(["country", "project", "estimate_kind"])
    OUT.parent.mkdir(exist_ok=True)
    out.to_csv(OUT, index=False)

    nea = pd.read_csv(NEA)
    nea[f"{base}_per_kw"] = [to_base(v, c, y) if u == "per kW" else np.nan for v, c, y, u in
                             zip(nea["overnight_cost_value"], nea["currency"], nea["currency_year"], nea["unit"])]
    nea.to_csv(OUT_NEA, index=False)

    print(f"{len(out)} cost rows for {out['project'].nunique()} projects, "
          f"{out[f'{base}_per_kw'].notna().sum()} with USD/kW")
    print(out.groupby("estimate_kind")[f"{base}_per_kw"].describe()[["count", "25%", "50%", "75%"]].round(0))


if __name__ == "__main__":
    main()
