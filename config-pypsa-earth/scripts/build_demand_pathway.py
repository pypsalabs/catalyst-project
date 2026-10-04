#!/usr/bin/env python
# SPDX-License-Identifier: MIT
"""
Build the per-country demand tables of the future model years: a consensus of published outlooks.

    python config-pypsa-earth/scripts/build_demand_pathway.py

writes config-pypsa-earth/calibration/<year>/demand.csv for 2025, 2030, ..., 2050
    country, demand_twh, weo_region, multiple, source       read by the fork's calibration.tables.demand (by column name)
and config-pypsa-earth/calibration/demand_pathway.csv
    weo_region, year, iea_steps_multiple, multiple          the growth multiples behind them

    demand(country, y) = demand(country, 2024) * IEA multiple(region of the country, y) ** alpha

1. World level: every outlook of data/demand_outlooks.csv with include = 1 becomes an annual growth rate over its
   own horizon; the consensus is their equal-weight mean, expressed as a 2024 -> 2050 multiple.
2. Regional pattern: only the IEA publishes a free regional table (WEO 2025, Table A.16, data/weo25_table_a16.csv),
   so regions keep the Stated Policies shape. Countries map to WEO regions after WEO Annex C; the table names the
   US, Brazil, the EU, Russia, China, India, Japan, Southeast Asia and Africa, every other country takes the
   remainder of its region (Europe less EU, ...). The table has 2035 and 2050; other years are interpolated at a
   constant growth rate within 2024-2035 and 2035-2050.
3. alpha scales the regional growth so that the 2050 total over all countries equals the consensus multiple times
   the 2024 total. 2024 stays fixed and the regional ordering is preserved.

The base is calibration/2024/demand.csv (Ember, scripts/build_calibration.py). Only growth is taken from the
outlooks, because their demand definitions differ (the IEA excludes own use and losses, bp reports generation).
"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.dirname(HERE)
CAL = os.path.join(CFG, "calibration")
ROW = os.path.join(CFG, "data", "row_countries.csv")
OUTLOOKS = os.path.join(CFG, "data", "demand_outlooks.csv")
WEO = os.path.join(CFG, "data", "weo25_table_a16.csv")

BASE = 2024
YEARS = [2025, 2030, 2035, 2040, 2045, 2050]
SOURCE = "Ember 2024 x outlook consensus (data/demand_outlooks.csv), IEA WEO25 STEPS regional shape"

# rest-of-region buckets: parent row of Table A.16 less the rows named inside it
REST = {"rest of North America": ("North America", ["United States"]),
        "rest of Central and South America": ("Central and South America", ["Brazil"]),
        "rest of Europe": ("Europe", ["European Union"]),
        "Caspian": ("Eurasia", ["Russia"]),
        "rest of Asia Pacific": ("Asia Pacific", ["China", "India", "Japan", "Southeast Asia"])}
NAMED = {"US": "United States", "BR": "Brazil", "RU": "Russia", "CN": "China", "HK": "China", "IN": "India", "JP": "Japan"}
EU = "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
MIDDLE_EAST = "BH IR IQ JO KW LB OM QA SA SY AE YE PS".split()          # PS: not listed by the IEA
CASPIAN = "AM AZ GE KZ KG TJ TM UZ".split()
SOUTHEAST_ASIA = "BN KH ID LA MY MM PH SG TH VN".split()
EUROPE_OUTSIDE_CONTINENT = ["TR", "IL"]                                 # the IEA counts Türkiye and Israel under Europe
BY_CONTINENT = {"Europe": "rest of Europe", "Africa": "Africa", "Asia": "rest of Asia Pacific",
                "Oceania": "rest of Asia Pacific", "South America": "rest of Central and South America"}


def weo_region(iso2, continent):
    if iso2 in NAMED:
        return NAMED[iso2]
    for members, region in ((EU, "European Union"), (MIDDLE_EAST, "Middle East"), (CASPIAN, "Caspian"),
                            (SOUTHEAST_ASIA, "Southeast Asia"), (EUROPE_OUTSIDE_CONTINENT, "rest of Europe")):
        if iso2 in members:
            return region
    if continent == "North America":
        return "rest of North America" if iso2 in ("CA", "MX") else "rest of Central and South America"
    return BY_CONTINENT[continent]


def consensus():
    """Outlook table with annual rates, and the consensus multiple BASE -> 2050."""
    o = pd.read_csv(OUTLOOKS, comment="#")
    o = o[o.include == 1].copy()
    o["rate"] = o.growth ** (1 / (o.end_year - o.base_year)) - 1
    o["multiple_2050"] = (1 + o.rate) ** (2050 - BASE)
    return o, (1 + o.rate.mean()) ** (2050 - BASE)


def iea_multiples():
    """IEA Stated Policies multiple per WEO region (rows) and year (columns), relative to BASE."""
    w = pd.read_csv(WEO, comment="#").set_index("region").drop(columns="members")
    for name, (parent, named) in REST.items():
        w.loc[name] = w.loc[parent] - w.loc[named].sum()
    m35, m50 = np.log(w.steps2035 / w.y2024), np.log(w.steps2050 / w.y2024)
    out = pd.DataFrame({BASE: 0.0}, index=w.index)
    for y in YEARS:   # constant growth rate within each segment = linear interpolation of the log multiple
        out[y] = m35 * (y - BASE) / (2035 - BASE) if y <= 2035 else m35 + (m50 - m35) * (y - 2035) / (2050 - 2035)
    return np.exp(out)


def solve_alpha(base, iea_2050, target):
    """alpha with sum(base * iea_2050 ** alpha) = target * sum(base), by bisection (the sum is increasing in alpha)."""
    lo, hi = 0.0, 3.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if (base * iea_2050 ** mid).sum() < target * base.sum() else (lo, mid)
    return (lo + hi) / 2


def main():
    base = pd.read_csv(os.path.join(CAL, str(BASE), "demand.csv"), comment="#", dtype={"country": str}, keep_default_na=False)
    base["demand_twh"] = base.demand_twh.astype(float)
    continent = pd.read_csv(ROW, keep_default_na=False).set_index("iso2").continent
    missing = sorted(set(base.country) - set(continent.index))
    assert not missing, f"countries of the base table without a continent in row_countries.csv: {missing}"
    base["weo_region"] = [weo_region(c, continent[c]) for c in base.country]

    outlooks, target = consensus()
    iea = iea_multiples()
    alpha = solve_alpha(base.demand_twh, base.weo_region.map(iea[2050]), target)
    pathway = iea ** alpha

    print(outlooks[["publisher", "outlook", "scenario", "base_year", "end_year", "growth", "rate", "multiple_2050"]]
          .round(4).to_string(index=False))
    print(f"\nconsensus: {outlooks.rate.mean():.2%} p.a., x{target:.3f} over {BASE}-2050 "
          f"(IEA regional shape gives x{(base.demand_twh * base.weo_region.map(iea[2050])).sum() / base.demand_twh.sum():.3f}); alpha = {alpha:.4f}\n")

    total = base.demand_twh.sum()
    previous = total
    for y in YEARS:
        t = base.assign(multiple=base.weo_region.map(pathway[y]))
        t["demand_twh"] = (t.demand_twh * t.multiple).round(2)
        t["multiple"] = t.multiple.round(4)
        t["source"] = SOURCE
        os.makedirs(os.path.join(CAL, str(y)), exist_ok=True)
        t[["country", "demand_twh", "weo_region", "multiple", "source"]].to_csv(os.path.join(CAL, str(y), "demand.csv"), index=False)
        assert t.demand_twh.sum() > previous, f"world demand must grow, {y}"
        previous = t.demand_twh.sum()
        print(f"{y}: {previous:9,.0f} TWh  x{previous / total:.3f}")
    assert abs(previous / total - target) < 1e-3, "2050 total must equal the consensus"

    regions = base.groupby("weo_region").demand_twh.sum().sort_values(ascending=False).index
    long = pd.concat([pd.DataFrame({"weo_region": regions, "year": y, "iea_steps_multiple": iea.loc[regions, y].round(4).values,
                                    "multiple": pathway.loc[regions, y].round(4).values}) for y in YEARS])
    long.to_csv(os.path.join(CAL, "demand_pathway.csv"), index=False)
    print("\n" + long.pivot(index="weo_region", columns="year", values="multiple").loc[regions].to_string())


if __name__ == "__main__":
    main()
