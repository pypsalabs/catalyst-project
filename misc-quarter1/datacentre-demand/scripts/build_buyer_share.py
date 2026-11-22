"""Who could buy 24/7 CFE in 2030: data centres plus the other electricity use of RE100 members, as a share of demand.

  build/series_<first variant>.csv, data/re100_markets.csv, data/buyers.csv, config.yaml -> build/buyer_share.csv, build/re100_countries.csv
      (python scripts/build_buyer_share.py)

Two sets that overlap (the RE100 members that run data centres are in both):
  data centres   IEA Base Case of the region in `buyer_share.year` (build/series_*.csv, the same in every variant)
  RE100, other   the members' consumption of 2024 by market, without their data centres, held at its 2024 share of demand
ASSUMPTIONS, both in config.yaml `buyer_share`: the members that gave RE100 no breakdown by market (77 of 557 TWh) are
spread like the others; the data-centre operators among the members (`overlap`) are taken out of each region in
proportion to the region's data-centre use, China left out (none of them runs data centres of its own there).
"""

from pathlib import Path

import pandas as pd
import yaml

HERE = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((HERE / "config.yaml").read_text())
B = CFG["buyer_share"]
REGIONS = list(CFG["regions"])


def re100_by_region(markets):
    """TWh of the base year per region of config.yaml, from the report's subtotals and country rows."""
    twh = markets.set_index("market").consumption_gwh / 1e3
    out = pd.Series({r: twh[m["plus"]].sum() - twh[m.get("minus", [])].sum() for r, m in B["re100_markets"].items()})
    rest = next(r for r, s in CFG["regions"].items() if s.get("remainder"))
    out[rest] = twh["All markets"] - out.sum()
    return out[REGIONS]


def countries(markets):
    """RE100 members' consumption per country against the country's demand of the base year (as reported, not scaled)."""
    c = pd.read_csv(HERE / CFG["demand"]["countries"], keep_default_na=False)
    demand = c.set_index(c.name.replace(B["country_names"])).demand_twh.astype(float)
    m = markets[markets.level == "country"].set_index("market").consumption_gwh / 1e3
    t = pd.DataFrame({"re100_twh": m, "demand_twh": demand}).dropna()
    t["re100_pct"] = 100 * t.re100_twh / t.demand_twh
    return t.sort_values("re100_twh", ascending=False).rename_axis("country")


def main():
    s = pd.read_csv(HERE / f"build/series_{next(iter(CFG['variants']))}.csv")
    dc = s.pivot(index="year", columns="region", values="twh")
    demand = s.pivot(index="year", columns="region", values="demand_twh")
    base, year = B["base_year"], B["year"]

    buyers = pd.read_csv(HERE / "data/buyers.csv", comment="#")
    total = buyers[(buyers.entity == "RE100 members") & (buyers.year == base)].twh.iloc[0]
    operators = buyers[buyers.entity.isin(B["overlap"]) & (buyers.year == base)].set_index("entity").twh
    assert set(operators.index) == set(B["overlap"]), "an overlap company has no value in the base year"

    markets = pd.read_csv(HERE / "data/re100_markets.csv", comment="#")
    re100 = re100_by_region(markets)
    re100 *= total / re100.sum()                                  # members without a market breakdown
    key = dc.loc[base, REGIONS].drop(B["overlap_not_in"])
    overlap = (operators.sum() * key / key.sum()).reindex(REGIONS).fillna(0.0)
    other = re100 - overlap

    t = pd.DataFrame({
        "datacentres_twh": dc.loc[year, REGIONS],
        "datacentres_pct": 100 * dc.loc[year, REGIONS] / demand.loc[year, REGIONS],
        f"re100_{base}_twh": re100,
        f"re100_operators_{base}_twh": overlap,
        "re100_other_pct": 100 * other / demand.loc[base, REGIONS],
    })
    world = pd.Series({
        "datacentres_twh": dc.loc[year, "World"], "datacentres_pct": 100 * dc.loc[year, "World"] / demand.loc[year, "World"],
        f"re100_{base}_twh": re100.sum(), f"re100_operators_{base}_twh": overlap.sum(),
        "re100_other_pct": 100 * other.sum() / demand.loc[base, "World"]}, name="World")
    t = pd.concat([t, world.to_frame().T])
    for name, weight in B["mixes"].items():
        t[f"{name}_pct"] = t.datacentres_pct + weight * t.re100_other_pct
    t.index.name = "region"
    (HERE / "build").mkdir(exist_ok=True)
    t.round(2).to_csv(HERE / "build/buyer_share.csv")
    print(f"buyers in {year}, % of the region's electricity demand (RE100 at its {base} share)")
    print(t.round(2).to_string())
    c = countries(markets)
    c.round(2).to_csv(HERE / "build/re100_countries.csv")
    print(f"\nRE100 members' consumption by country, {base} (as reported: {c.re100_twh.sum():.0f} TWh in {len(c)} countries)")
    print(c.head(14).round(2).to_string())


if __name__ == "__main__":
    main()
