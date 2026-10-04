"""History panel and future drivers.

    build/panel.csv     iso3, year (2000-2024), demand_twh (Ember), population, gdp_pc (WDI, PPP constant 2021 int$)
    build/drivers.csv   iso3, year, pop_index, gdp_pc_index (relative to the base year), gdp_pc_base, driver_source

The SSP2 series start in 2025; the base-year -> 2025 step is taken at the country's own 2025-2030 annual rate.
Countries without an SSP GDP series (AFG, PSE, SYR, VEN among the modelled ones) get the median per-capita growth
of the others; countries without WDI GDP (CUB, PRK, TWN, VEN, YEM) get their GDP level from the SSP 2025 value,
rescaled by the median WDI/SSP ratio. Both are flagged in `driver_source`.
"""

import json
import os

import numpy as np
import pandas as pd

from common import BUILD, CONFIG, DATA, ember_demand, iso3_of

BASE = CONFIG["base_year"]
YEARS = [BASE] + CONFIG["years"]


def wdi(indicator):
    rows = json.load(open(os.path.join(DATA, f"wdi_{indicator}.json")))[1]
    d = pd.DataFrame([(r["countryiso3code"], int(r["date"]), r["value"]) for r in rows], columns=["iso3", "year", "value"])
    return d[d.iso3 != ""].dropna().set_index(["iso3", "year"]).value


def ssp(variable):
    s = pd.read_csv(os.path.join(DATA, "ssp2_basic_drivers.csv"))
    s = s[(s.variable == variable) & ~s.region.str.contains(r"\(R\d+\)|World")]
    s = s.assign(iso3=s.region.map(iso3_of)).dropna(subset=["iso3"])
    return s.pivot_table(index="iso3", columns="year", values="value")


def index_from_ssp(wide):
    """Index relative to the base year for every year in YEARS; linear in logs between the 5-year SSP steps."""
    logs = np.log(wide)
    rate = (logs[2030] - logs[2025]) / 5
    out = pd.DataFrame({BASE: 0.0}, index=wide.index)
    for y in YEARS[1:]:
        out[y] = logs[y] - logs[2025] + rate * (2025 - BASE)
    return np.exp(out)


def main():
    os.makedirs(BUILD, exist_ok=True)
    dem = ember_demand()
    pop, gdp = wdi("SP.POP.TOTL"), wdi("NY.GDP.PCAP.PP.KD")

    lo, hi = CONFIG["baseline"]["fit_years"]
    panel = dem[(dem.year >= lo) & (dem.year <= hi)][["iso3", "year", "demand_twh"]].set_index(["iso3", "year"])
    panel["population"], panel["gdp_pc"] = pop, gdp
    panel.reset_index().to_csv(os.path.join(BUILD, "panel.csv"), index=False)

    ssp_pop, ssp_gdp = ssp("Population"), ssp("GDP|PPP")
    pop_idx = index_from_ssp(ssp_pop)
    common = ssp_gdp.index.intersection(ssp_pop.index)
    ssp_pc = ssp_gdp.loc[common] / ssp_pop.loc[common] * 1e3     # USD2017 PPP per capita
    pc_idx = index_from_ssp(ssp_pc)

    countries = sorted(set(dem.iso3))
    gdp_base = gdp.xs(BASE, level="year").reindex(countries)
    for back in (1, 2, 3):                                        # a few countries report GDP with a lag
        gdp_base = gdp_base.fillna(gdp.xs(BASE - back, level="year").reindex(countries))
    ratio = (gdp_base / ssp_pc[2025].reindex(countries)).median()
    source = pd.Series("wdi+ssp2", index=countries)
    no_level = gdp_base.isna()
    gdp_base[no_level] = ssp_pc[2025].reindex(countries)[no_level] * ratio
    source[no_level] = "gdp level from ssp2"
    median_idx = pc_idx.median()

    rows = []
    for c in countries:
        if c not in pop_idx.index:
            continue
        has_gdp = c in pc_idx.index
        for y in YEARS:
            rows.append((c, y, pop_idx.at[c, y], pc_idx.at[c, y] if has_gdp else median_idx[y],
                         gdp_base[c] if not np.isnan(gdp_base[c]) else gdp_base.median(),
                         source[c] if has_gdp else "median gdp growth"))
    out = pd.DataFrame(rows, columns=["iso3", "year", "pop_index", "gdp_pc_index", "gdp_pc_base", "driver_source"])
    out.to_csv(os.path.join(BUILD, "drivers.csv"), index=False)
    print(f"panel: {panel.dropna().index.get_level_values(0).nunique()} countries with complete history; "
          f"drivers: {out.iso3.nunique()} countries")
    print(out[out.year == 2050].driver_source.value_counts().to_string())


if __name__ == "__main__":
    main()
