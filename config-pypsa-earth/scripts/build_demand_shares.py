# SPDX-License-Identifier: CC0-1.0
"""
Share of a country's electricity demand per GADM level-1 unit, for the fork option `load_options: subnational_shares`.

Reads the curated tables of data/demand_provinces/ and writes calibration/2024/demand_shares.csv (key, country, name,
demand_twh, share; shares sum to 1 per country). Only the shares are used by the model: the national level stays the
calibrated one (calibration/<year>/demand.csv). tables.smk hands the table to every run as
resources/<run>/statistics/demand_shares.csv; a country without rows is spread by GDP and population as before.

China (cn_provinces_2024.csv): the 31 provinces are measured off a published bar chart (see the file's header);
their bar lengths are converted with one scale so that they sum to the national consumption, and compared with the
exact figures the file holds for some of them. Hong Kong and Macau are given in TWh.

United States: retail sales of electricity per state in 2024, EIA form 861 (data/validation/eia/state/HS861 2010-.xlsx,
read by build_region_tables.eia_sales, which also splits the national demand over US West and US East with it). Retail
sales are consumption without grid losses and without the plants' own use; only their shares are used. One national
table serves both halves: a run holds the states of its half only, and the option scales their shares to one.

Usage (from config-pypsa-earth): ../models/pypsa-earth/.pixi/envs/default/bin/python scripts/build_demand_shares.py
"""
import os

import pandas as pd

import build_region_tables as rt

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "calibration", "2024", "demand_shares.csv")
CN_NATIONAL_TWH = 9852.1   # 全社会用电量 2024, National Energy Administration (98,521 亿千瓦时)


def china():
    d = pd.read_csv(os.path.join(HERE, "data", "demand_provinces", "cn_provinces_2024.csv"), comment="#")
    bars = d.bar_px.notna()
    scale = CN_NATIONAL_TWH / d.bar_px[bars].sum()
    d.loc[bars, "demand_twh"] = d.bar_px[bars] * scale
    c = d[d.check_twh.notna()]
    dev = c.demand_twh / c.check_twh - 1
    print(f"China: {bars.sum()} provinces from the chart at {scale:.3f} TWh per pixel; against {len(c)} exact figures: "
          f"{dev.min():+.1%} to {dev.max():+.1%} (" + ", ".join(f"{n} {v:+.1%}" for n, v in zip(c.name, dev)) + ")")
    assert dev.abs().max() < 0.03, "the reading of the chart is off by more than 3 % for a province with an exact figure"
    d["country"] = "CN"
    return d[["key", "country", "name", "demand_twh"]]


def united_states(year=2024):
    sales = rt.eia_sales(year) / 1e6
    codes = pd.Series(rt.unit_codes("US"))
    d = pd.DataFrame({"key": codes.index, "country": "US", "name": codes.values, "demand_twh": codes.map(sales).values})
    assert d.demand_twh.notna().all(), f"no retail sales for {d.name[d.demand_twh.isna()].tolist()}"
    print(f"United States: {len(d)} states, retail sales {d.demand_twh.sum():.0f} TWh in {year} (EIA form 861)")
    return d


def main():
    out = pd.concat([china(), united_states()], ignore_index=True)
    assert not out.key.duplicated().any() and out.demand_twh.gt(0).all()
    out["share"] = out.demand_twh / out.groupby("country").demand_twh.transform("sum")
    out["demand_twh"] = out.demand_twh.round(1)
    out["share"] = out.share.round(5)
    out.to_csv(OUT, index=False)
    print(f"-> {OUT} ({len(out)} units, {out.groupby('country').demand_twh.sum().round(0).to_dict()} TWh)")


if __name__ == "__main__":
    main()
