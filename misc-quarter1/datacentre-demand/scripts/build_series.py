"""Data-centre electricity demand by region and year, with the total electricity demand of the same regions.

  data/iea_regions.csv, data/iea_world_cases.csv, data/outlooks.csv, config.yaml
      -> build/series_<variant>.csv, build/world_cases.csv        (python scripts/build_series.py [variant ...])

build/series_<variant>.csv: year, region (the regions of config.yaml and World), twh (data centres), demand_twh (all electricity),
share_pct, basis = history | iea_base (IEA Base Case of the region) | iea_base_world (IEA world total, regions at their
2030 shares) | extrapolated (no source, see config.yaml `projection` and `variants`).
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((HERE / "config.yaml").read_text())
REGIONS = list(CFG["regions"])
Y0, Y1 = CFG["years"]
YEARS = np.arange(Y0, Y1 + 1)


def total_demand():
    """TWh per year and region: Ember history, then the model's demand pathway."""
    d = CFG["demand"]
    countries = pd.read_csv(HERE / d["countries"], keep_default_na=False)
    tables = {y: pd.read_csv(HERE / d["pathway"].format(year=y), comment="#", keep_default_na=False)
              for y in d["pathway_years"]}
    first = next(iter(tables.values()))
    region_of = {}
    for name, spec in CFG["regions"].items():
        if spec.get("remainder"):
            continue
        m = first[first.weo_region.isin(spec["members"])].country
        if "continent" in spec:
            on = set(countries[countries.continent == spec["continent"]].iso2)
            m = m[m.isin(on)]
        region_of.update(dict.fromkeys(m, name))
    remainder = next(n for n, s in CFG["regions"].items() if s.get("remainder"))

    ember = pd.read_csv(HERE / d["ember"], low_memory=False)
    ember = ember[(ember.Category == "Electricity demand") & (ember.Unit == "TWh") & (ember.Variable == "Demand")]
    world = ember[ember.Area == "World"].set_index("Year").Value
    iso2 = countries.set_index("iso3").iso2
    c = ember[ember["Area type"] == "Country or economy"].assign(iso2=lambda x: x["ISO 3 code"].map(iso2))
    c = c.assign(region=c.iso2.map(region_of)).dropna(subset="region")
    hist = c.pivot_table(index="Year", columns="region", values="Value", aggfunc="sum").loc[Y0:d["history_until"]]
    hist["World"] = world.loc[hist.index]
    hist[remainder] = hist["World"] - hist.drop(columns="World").sum(axis=1)

    path = pd.DataFrame({y: t.assign(region=t.country.map(region_of).fillna(remainder)).groupby("region").demand_twh.sum()
                         for y, t in tables.items()}).T
    path["World"] = path.sum(axis=1)
    path *= hist["World"].iloc[-1] / pd.read_csv(HERE / d["pathway"].format(year=d["history_until"]),
                                                 comment="#").demand_twh.sum()   # the tables hold 99.5 % of the world
    out = pd.concat([hist, path]).reindex(YEARS).interpolate(method="index")
    return out[REGIONS + ["World"]]


def world_2050(rule, cases):
    """World total of the last year by the variant's rule, or None for the trend."""
    if rule in (None, "trend"):
        return None
    if rule == "median":
        o = pd.read_csv(HERE / "data/outlooks.csv", comment="#")
        return o[(o.region == "World") & (o.year == Y1) & (o.show == 1)].twh.median()
    return float(rule)


def datacentres(rule):
    p = CFG["projection"]
    r = pd.read_csv(HERE / "data/iea_regions.csv", comment="#").set_index("year")
    cases = pd.read_csv(HERE / "data/iea_world_cases.csv", comment="#").set_index("year")
    twh = r[REGIONS].reindex(YEARS).astype(float)
    basis = r.kind.map({"history": "history", "base": "iea_base"}).reindex(YEARS)

    split = twh.loc[p["regional_until"]] / twh.loc[p["regional_until"]].sum()
    last = cases.base[p["world_until"]]
    target = world_2050(rule, cases)
    if target is None:
        step = (last - cases.base[p["increment_from"]]) / (p["world_until"] - p["increment_from"])
    else:
        step = (target - last) / (Y1 - p["world_until"])
    for y in YEARS[YEARS > p["regional_until"]]:
        if y <= p["world_until"]:
            world, basis[y] = cases.base[y], "iea_base_world"
        else:
            world, basis[y] = last + step * (y - p["world_until"]), "extrapolated"
        twh.loc[y] = split * world
    twh["World"] = twh.sum(axis=1)
    return twh, basis


def main():
    demand = total_demand()
    (HERE / "build").mkdir(exist_ok=True)
    cases = pd.read_csv(HERE / "data/iea_world_cases.csv", comment="#").set_index("year")
    cases = cases.join((100 * cases.div(demand["World"], axis=0)).add_suffix("_share_pct"), how="left")
    cases.round(3).to_csv(HERE / "build/world_cases.csv")

    long = lambda df, name: df.rename_axis(index="year", columns="region").stack().rename(name)
    for variant in sys.argv[1:] or list(CFG["variants"]):
        twh, basis = datacentres(CFG["variants"][variant]["world_2050"])
        out = pd.concat([long(twh, "twh"), long(demand, "demand_twh")], axis=1).reset_index()
        out["share_pct"] = 100 * out.twh / out.demand_twh
        out["basis"] = out.year.map(basis)
        out.round(3).to_csv(HERE / f"build/series_{variant}.csv", index=False)

        show = out[out.year.isin([2020, 2024, 2030, 2035, 2050])]
        print(f"\n{variant}: data centres, TWh | share of electricity demand, %")
        print(pd.concat([show.pivot(index="region", columns="year", values="twh").round(0),
                         show.pivot(index="region", columns="year", values="share_pct").round(1)],
                        axis=1, keys=["TWh", "%"]).reindex(REGIONS + ["World"]).to_string())
    print("\ntotal electricity demand, TWh")
    print(demand.loc[[2020, 2024, 2030, 2035, 2050]].T.round(0).to_string())


if __name__ == "__main__":
    main()
