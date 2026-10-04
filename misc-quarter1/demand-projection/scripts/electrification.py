"""Electrification layer: electricity that replaces fossil final energy in road transport, buildings and industry.

    added(y) = sum over sectors of  fossil final energy(unsd_year) * baseline index(y) * share(y) / efficiency gain

Fossil final energy comes from the UN Energy Statistics Database (the raw UNdata exports pypsa-earth downloads):
motor gasoline, gas/diesel oil, LPG, fuel oil, hard and brown coal, natural gas, in the transactions
"in road", "by households" + "commerce and public services", and "manufacturing, construction and non-fuel".
Biomass is left out (its replacement is mostly a clean-cooking question), as are aviation, shipping and rail.
Per country, fuel and transaction the latest year in [unsd_year - 3, unsd_year] is used: the UNdata exports are
capped at 100,000 rows each, so the gas/diesel oil file ends in 2021 and loses the countries after "United States",
fuel oil those after "Yemen" and natural gas those after "Uruguay" (Uzbekistan, Venezuela, Viet Nam, ...).
The energy service is assumed to grow with the income-driven baseline index of the country.

    build/fossil_final_energy.csv   iso3, sector, fuel, twh           (cache of the UNdata parse)
    build/electrification.csv       iso3, year, level, sector, twh
"""

import glob
import os

import numpy as np
import pandas as pd

from common import BUILD, CONFIG, iso3_of, path

CFG = CONFIG["electrification"]
SECTORS = {"road": ["in road"],
           "buildings": ["by households", "commerce and public services"],
           "industry": ["manufacturing, construction and non-fuel"]}
FUELS = {"road": ["motor gasoline", "gas oil/ diesel oil", "liquefied petroleum gas", "natural gas"],
         "buildings": ["natural gas", "liquefied petroleum gas", "gas oil/ diesel oil", "fuel oil", "hard coal", "brown coal"],
         "industry": ["natural gas", "hard coal", "brown coal", "fuel oil", "gas oil/ diesel oil", "liquefied petroleum gas"]}


def fuel_of(commodity):
    c = commodity.lower().replace("liquified", "liquefied")
    for f in list(CFG["ncv_twh_per_kt"]) + ["natural gas (including lng)"]:
        if c.startswith(f):
            return f.split(" (")[0]


def fossil_final_energy():
    cache = os.path.join(BUILD, "fossil_final_energy.csv")
    if os.path.exists(cache):
        return pd.read_csv(cache)
    rows = []
    for f in sorted(glob.glob(os.path.join(path("unsd"), "*.txt"))):
        head = pd.read_csv(f, sep=";", nrows=1)
        if fuel_of(head.iloc[0, 1]) is None:
            continue
        d = pd.read_csv(f, sep=";", usecols=[0, 1, 2, 3, 4], names=["country", "ct", "year", "unit", "quantity"], header=0)
        d["year"] = pd.to_numeric(d.year, errors="coerce")
        d = d[d.year.between(CFG["unsd_year"] - 3, CFG["unsd_year"])]
        d = d.sort_values("year").groupby(["country", "ct"]).last().reset_index()   # latest year in the window
        d["fuel"] = d.ct.map(fuel_of)
        d = d.dropna(subset=["fuel"])
        transaction = d.ct.str.split(" - ", n=1).str[1].str.lower()
        for sector, keys in SECTORS.items():
            s = d[transaction.apply(lambda t: any(k in t for k in keys)) & d.fuel.isin(FUELS[sector])]
            rows.append(s.assign(sector=sector))
        # countries that book retail diesel under "not elsewhere specified (other)" instead of road
        nes = d[transaction.str.contains("not elsewhere specified (other)", regex=False)]
        nes = nes[[f in CFG["road_from_unspecified"].get(iso3_of(c), []) for c, f in zip(nes.country, nes.fuel)]]
        rows.append(nes.assign(sector="road"))
    d = pd.concat(rows)
    d["quantity"] = pd.to_numeric(d.quantity, errors="coerce")
    tj = d.unit.str.contains("Terajoule")
    assert (tj == (d.fuel == "natural gas")).all(), d[tj != (d.fuel == "natural gas")].unit.unique()
    assert d[~tj].unit.str.contains("Metric tons").all()
    d["twh"] = np.where(tj, d.quantity / 3600, d.quantity * d.fuel.map(CFG["ncv_twh_per_kt"]))
    d["iso3"] = d.country.map(iso3_of)
    missing = d[d.iso3.isna()].groupby("country").twh.sum().sort_values(ascending=False)
    if len(missing):
        print("UN names without ISO code (TWh dropped):", missing.round(1).head(10).to_dict())
    out = d.dropna(subset=["iso3"]).groupby(["iso3", "sector", "fuel"]).twh.sum().reset_index()
    out.to_csv(cache, index=False)
    return out


def share(level, sector, year):
    pts = CFG["shares"][level][sector]
    return float(np.interp(year, sorted(pts), [pts[y] for y in sorted(pts)]))


def main():
    ffe = fossil_final_energy().groupby(["iso3", "sector"]).twh.sum().unstack(fill_value=0.0)
    base = pd.read_csv(os.path.join(BUILD, "baseline.csv"))
    rows = []
    for level in CFG["shares"]:
        for sector in SECTORS:
            f = base.iso3.map(ffe[sector]).fillna(0.0)
            s = base.year.map(lambda y: share(level, sector, y))
            rows.append(pd.DataFrame({"iso3": base.iso3, "year": base.year, "level": level, "sector": sector,
                                      "twh": f * base.baseline_index * s / CFG["efficiency_gain"][sector]}))
    out = pd.concat(rows)
    out.to_csv(os.path.join(BUILD, "electrification.csv"), index=False)
    no_data = sorted(set(base.iso3) - set(ffe.index))
    print(f"fossil final energy {CFG['unsd_year']}, world TWh:\n{ffe.sum().round(0).to_string()}")
    print(f"countries without UN data (no layer): {len(no_data)} {no_data[:20]}")
    print(out[out.year == 2050].groupby(["level", "sector"]).twh.sum().round(0).unstack().to_string())


if __name__ == "__main__":
    main()
