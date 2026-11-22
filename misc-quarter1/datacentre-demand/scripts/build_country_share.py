"""Share of a country's electricity demand that could buy 24/7 CFE, per horizon: data centres + a part of the other
electricity use of RE100 members. The table the model reads.

  data/datacentre_countries.csv, data/iea_table_a4.csv, data/re100_markets.csv, data/buyers.csv,
  build/series_<first variant>.csv, the model's demand tables, config.yaml `buyer_share`
      -> build/country_share.csv                                      (python scripts/build_country_share.py)
      -> <model tables>/<year>/cfe_share.csv                          (python scripts/build_country_share.py --tables)
         columns country, share, datacentres, re100 (the two parts of the share, weight, scale and cap applied), basis,
         capped, source

share(country, year) = min(cap, scale x (data centres + weight x RE100 other))
  data centres, TWh in 2030, by the first rule that applies (column `basis`):
    country        a sourced value for 2030
    interpolated   a history value and a later value of one publisher, joined by constant growth
    history        a sourced history value x the growth of the country's IEA region to 2030
    iea            the IEA's own row for the country (United States, China; Table A.4, Base Case)
    region         the IEA region's data-centre use spread by demand (Table A.4)
  after 2030 the country's data-centre use grows like the world total of the series (config `variants`, first one).
  RE100 other: members' consumption in the country (2024, scaled for the members without a market breakdown) minus the
  data-centre operators among them, allotted by the country's data-centre use; held at its 2024 share of demand.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((HERE / "config.yaml").read_text())
B = CFG["buyer_share"]
BASE, YEAR, HORIZONS = B["base_year"], B["year"], B["horizons"]


def demand_table(year):
    d = pd.read_csv(HERE / CFG["demand"]["pathway"].format(year=year), comment="#", keep_default_na=False)
    return d.set_index("country")


def iea_regions():
    """TWh per year of the fallback regions (config `iea_regions`), the unlisted rest as the remainder region."""
    a4 = pd.read_csv(HERE / "data/iea_table_a4.csv", comment="#").set_index("year")
    out = pd.DataFrame({r: a4[m["plus"]].sum(axis=1) - a4[m.get("minus", [])].sum(axis=1)
                        for r, m in B["iea_regions"].items() if not m.get("remainder")})
    rest = next(r for r, m in B["iea_regions"].items() if m.get("remainder"))
    out[rest] = a4["World"] - out.sum(axis=1)
    return out


def sourced(demand):
    """Per country the rows in use: (history year, TWh), TWh of 2030, (later year, TWh); a share becomes TWh with the
    model's demand of the year."""
    rows = pd.read_csv(HERE / "data/datacentre_countries.csv", comment="#", keep_default_na=False)
    rows = rows[rows.use.astype(int) == 1]
    years = np.array(sorted(demand))
    out = {}
    for iso, g in rows.groupby("iso2"):
        rec = {}
        for r in g.itertuples():
            twh = float(r.value)
            if r.unit == "pct":
                twh *= demand[years[np.abs(years - r.year).argmin()]].get(iso, np.nan) / 100
            key = "history" if r.year < YEAR else "target" if r.year == YEAR else "later"
            assert key not in rec, f"{iso}: two rows in use for {key}"
            rec[key] = (int(r.year), twh, r.publisher)
        out[iso] = rec
    return out


def main():
    demand = {y: demand_table(y).demand_twh.astype(float) for y in [BASE, 2025] + HORIZONS}
    first = demand_table(YEAR)
    region_of = {w: r for r, m in B["iea_regions"].items() for w in m["weo"]}
    region = first.weo_region.map(region_of)
    assert region.notna().all(), f"no IEA region for {sorted(first.weo_region[region.isna()].unique())}"
    iea = iea_regions()

    # the region's data-centre use spread over its countries by demand
    spread = lambda y, dy: iea.loc[y, region].values * demand[dy] / demand[dy].groupby(region).transform("sum")
    dc_base, dc = spread(BASE, BASE), spread(YEAR, YEAR)
    basis = pd.Series("region", index=first.index).mask(region.isin(B["iea_countries"]), "iea")
    for iso, rec in sourced(demand).items():
        r, h = region[iso], rec.get("history")
        if h:
            dc_base[iso] = h[1] * iea.loc[BASE, r] / iea.loc[h[0], r]
        if "target" in rec:
            dc[iso], basis[iso] = rec["target"][1], "country"
        elif h and "later" in rec and rec["later"][2] == h[2]:
            (y0, v0, _), (y1, v1, _) = h, rec["later"]
            dc[iso], basis[iso] = v0 * (v1 / v0) ** ((YEAR - y0) / (y1 - y0)), "interpolated"
        elif h:
            dc[iso], basis[iso] = h[1] * iea.loc[YEAR, r] / iea.loc[h[0], r], "history"

    series = pd.read_csv(HERE / f"build/series_{next(iter(CFG['variants']))}.csv")
    world = series[series.region == "World"].set_index("year").twh
    growth = world / world[YEAR]

    # RE100 members' other use
    names = pd.read_csv(HERE / CFG["demand"]["countries"], keep_default_na=False)
    iso_of = names.set_index(names.name.replace(B["country_names"])).iso2
    markets = pd.read_csv(HERE / "data/re100_markets.csv", comment="#")
    total = markets.set_index("market").consumption_gwh["All markets"] / 1e3
    m = markets[markets.level == "country"].assign(iso2=lambda x: x.market.map(iso_of)).dropna(subset="iso2")
    buyers = pd.read_csv(HERE / "data/buyers.csv", comment="#")
    members = buyers[(buyers.entity == "RE100 members") & (buyers.year == BASE)].twh.iloc[0]
    operators = buyers[buyers.entity.isin(B["overlap"]) & (buyers.year == BASE)].twh.sum()
    re100 = (m.set_index("iso2").consumption_gwh / 1e3 * members / total).reindex(first.index).fillna(0.0)
    key = dc_base.where(~region.isin(B["overlap_not_in"]), 0.0)
    other = (re100 - operators * key / key.sum()).clip(lower=0) / demand[BASE].reindex(first.index)

    out = []
    for y in HORIZONS:
        d = demand[y].reindex(first.index)
        t = pd.DataFrame({"year": y, "region": region, "demand_twh": d, "datacentres_twh": dc * growth[y],
                          "datacentres": dc * growth[y] / d, "re100_other": other, "basis": basis})
        t[["datacentres", "re100_other"]] = t[["datacentres", "re100_other"]].fillna(0.0)   # a country without demand
        # the two parts of the share; the cap takes from the data centres' part
        t["part_re100"] = (B["scale"] * B["weight"] * t.re100_other).clip(upper=B["cap"])
        t["share_uncapped"] = B["scale"] * (t.datacentres + B["weight"] * t.re100_other)
        t["share"] = t.share_uncapped.clip(upper=B["cap"])
        t["part_datacentres"] = t.share - t.part_re100
        t["capped"] = t.share_uncapped > B["cap"]
        out.append(t.reset_index())
    out = pd.concat(out)
    out["datacentres_base"] = out.country.map((dc_base / demand[BASE].reindex(first.index)).fillna(0.0))
    (HERE / "build").mkdir(exist_ok=True)
    out.round(5).to_csv(HERE / "build/country_share.csv", index=False)

    if "--tables" in sys.argv:
        note = (f"misc-quarter1/datacentre-demand: data centres ({{}}) + {B['weight']} x other use of RE100 members, "
                f"scale {B['scale']}, cap {B['cap']}")
        for y, t in out.groupby("year"):
            t = t.assign(datacentres=t.part_datacentres, re100=t.part_re100, source=t.basis.map(note.format))
            t = t[["country", "share", "datacentres", "re100", "basis", "capped", "source"]]
            t.round(5).to_csv(HERE / B["tables"].format(year=y), index=False)

    t = out[out.year == YEAR].set_index("country")
    w = lambda col, g=None: (t[col] * t.demand_twh).groupby(g).sum() / t.demand_twh.groupby(g).sum() if g is not None \
        else (t[col] * t.demand_twh).sum() / t.demand_twh.sum()
    print(f"{YEAR}: world share {100 * w('share'):.2f} % (data centres {100 * w('datacentres'):.2f} %, "
          f"RE100 other {100 * w('re100_other'):.2f} %); data centres {t.datacentres_twh.sum():.0f} TWh "
          f"against {iea.loc[YEAR].sum():.0f} TWh in the IEA table")
    reg = pd.DataFrame({"iea_twh": iea.loc[YEAR], "countries_twh": t.datacentres_twh.groupby(t.region).sum(),
                        "share_pct": 100 * w("share", t.region)})
    print(reg.round(2).to_string())
    own = t[~t.basis.isin(["region", "iea"])].sort_values("share", ascending=False)
    print(f"\ncountries with a value of their own ({len(own)}), % of demand in {YEAR}")
    print((100 * own[["datacentres", "re100_other", "share"]]).round(2).assign(basis=own.basis, twh=own.datacentres_twh.round(1)).to_string())
    hit = out[out.capped].groupby("country").agg(first_year=("year", "min"), uncapped_first=("share_uncapped", "first"),
                                                 uncapped_last=("share_uncapped", "last"))
    print(f"\ncapped at {B['cap']:.0%}:")
    print(hit.assign(uncapped_first=100 * hit.uncapped_first, uncapped_last=100 * hit.uncapped_last).round(1).to_string())
    print("\nlargest shares among the others")
    print((100 * t[t.basis.isin(["region", "iea"])].nlargest(8, "share")[["datacentres", "re100_other", "share"]]).round(2).to_string())


if __name__ == "__main__":
    main()
