# SPDX-License-Identifier: CC0-1.0
"""
Build the tidy validation-point table used by plot_validation.py (dots / labels next to the model bars).

Sources
  Ember  yearly_full_release_long_format.csv   generation, capacity, demand, power-sector CO2 by fuel, per country
  Ember  european_wholesale_electricity_price_data_monthly.csv   monthly day-ahead prices (EUR/MWh), Europe
  IRENA  IRENA_Statistics_Extract_2025H2.xlsx  installed capacity (all technologies) and generation, per country
  EI     EI-Stats-Review-ALL-data-2025.xlsx    Energy Institute Statistical Review 2025: generation by fuel, wind/solar capacity,
         and the 2024 fuel-price markers (Henry Hub/TTF/LNG, coal FOB/CIF, crude) converted to EUR/MWh_th
         (Cloudflare-gated; archive link in the README, fetched with a browser and kept in the repo)
  ECB    annual average reference exchange rates (EUR base)
  manual_points.csv   hand-curated points with citation (national statistics, prices, 2050 outlooks)

Output columns: region,country,scenario,quantity,carrier,value,unit,year,source_short,source,url,note
  region    SG | BR | IN | NWE | US | CN (the run.sh stage prefixes; countries from config.<R>.yaml)
  country   ISO2 of a single country, empty for region totals
  scenario  now (actual statistics) | zero (2050 outlooks)
  quantity  generation | capacity | demand | price | emissions | fuel_price
  carrier   coal gas oil nuclear hydro wind solar biomass geothermal other battery H2 total (+ lignite uranium for fuel_price)
  unit      TWh | GW | MtCO2 | EUR/MWh (electricity, ECB annual average of the data year) | EUR/MWh_th (fuel, net calorific
            value; manual rows may be quoted as <CUR>[<fxyear>]/MMBtu (gross CV, x1.108), /bbl (1.615 MWh_NCV/bbl) or
            /t@<kcal>kcal (kcal/kg NAR x 0.001163 MWh/t) and are converted here)

Snakemake: rule build_validation_points in validation.smk. Standalone (fork pixi env):
    pixi run python ../../config-pypsa-earth/scripts/build_validation.py --out resources/catalyst/validation_points.csv
"""
import argparse
import os

import re

import numpy as np
import pandas as pd
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.dirname(HERE)
DATA = os.path.join(CFG, "data", "validation")
COLS = ["region", "country", "scenario", "quantity", "carrier", "value", "unit", "year", "source_short", "source", "url", "note"]
ISO3 = {"AT": "AUT", "BE": "BEL", "CH": "CHE", "CZ": "CZE", "DE": "DEU", "DK": "DNK", "FR": "FRA", "GB": "GBR", "IE": "IRL",
        "LU": "LUX", "NL": "NLD", "PL": "POL", "US": "USA", "BR": "BRA", "IN": "IND", "SG": "SGP", "CN": "CHN"}
ISO2 = {v: k for k, v in ISO3.items()}
EMBER_FUEL = {"Bioenergy": "biomass", "Coal": "coal", "Gas": "gas", "Hydro": "hydro", "Nuclear": "nuclear",
              "Other Fossil": "oil", "Other Renewables": "geothermal", "Solar": "solar", "Wind": "wind",
              "Total Generation": "total", "Total emissions": "total", "Demand": "total"}
EMBER_CAT = {"Electricity generation": ("generation", "TWh"), "Capacity": ("capacity", "GW"),
             "Electricity demand": ("demand", "TWh"), "Power sector emissions": ("emissions", "MtCO2")}
IRENA_TECH = {"Coal and peat": "coal", "Natural gas": "gas", "Oil": "oil", "Nuclear": "nuclear",
              "Other non-renewable energy": "other", "Pumped storage": "hydro", "Mixed Hydro Plants": "hydro",
              "Renewable hydropower": "hydro", "Biogas": "biomass", "Liquid biofuels": "biomass",
              "Renewable municipal waste": "biomass", "Solid biofuels": "biomass", "Geothermal energy": "geothermal",
              "Marine energy": "other", "Solar photovoltaic": "solar", "Solar thermal energy": "solar",
              "Offshore wind energy": "wind", "Onshore wind energy": "wind"}
CARRIERS = ["coal", "gas", "oil", "nuclear", "hydro", "wind", "solar", "biomass", "geothermal", "other", "battery", "H2", "total",
            "lignite", "uranium"]
MMBTU_PER_MWH = 3.41214          # 1 MWh = 3.41214 million Btu
GCV_NCV_GAS = 1.108              # gas markers are quoted per MMBtu gross calorific value; the model's EUR/MWh_th is net (IEA ratio)
MWH_NCV_PER_BBL = 1.615          # 5.8 MMBtu/bbl (EIA crude convention, gross) x 0.95 NCV/GCV x 0.293071 MWh/MMBtu
MWH_PER_KCAL_KG = 0.001163       # 1 kcal/kg = 1.163 kWh/t


def fxrate(fx, cur, year):
    """ECB annual average <cur> per EUR of `year`."""
    r = fx.loc[(fx.CURRENCY == cur) & (fx.TIME_PERIOD == int(year)), "OBS_VALUE"]
    if r.empty:
        raise SystemExit(f"no ECB rate for {cur} {year} in ecb_fx_annual.csv")
    return float(r.iloc[0])


def regions():
    """{region: [ISO2, ...]} from config-pypsa-earth/config.<R>.yaml (stage names without '-smoke')."""
    out = {}
    for f in sorted(os.listdir(CFG)):
        if f.startswith("config.") and f.endswith(".yaml") and "-smoke" not in f:
            r = f[len("config."):-len(".yaml")]
            with open(os.path.join(CFG, f)) as fh:
                out[r] = list(yaml.safe_load(fh)["countries"])
    return out


def rows(region, scenario, quantity, unit, year, source_short, source, url, note, values, country=""):
    """values: {carrier: value} -> list of row dicts."""
    return [dict(region=region, country=country, scenario=scenario, quantity=quantity, carrier=c, value=float(v), unit=unit,
                 year=int(year), source_short=source_short, source=source, url=url, note=note)
            for c, v in values.items() if pd.notna(v)]


# ------------------------------------------------------------------------------------------ Ember ----------
def ember(path, regs):
    df = pd.read_csv(path)
    df = df[df["ISO 3 code"].isin(ISO3.values()) & df.Category.isin(EMBER_CAT) & df.Subcategory.isin(["Fuel", "Total", "Demand"])
            & df.Unit.isin(["TWh", "GW", "mtCO2"])]
    df = df.assign(carrier=df.Variable.map(EMBER_FUEL)).dropna(subset=["carrier"])
    out = []
    src = "Ember, Yearly electricity data (yearly_full_release_long_format.csv)"
    url = "https://ember-energy.org/data/yearly-electricity-data/"
    for reg, ccs in regs.items():
        iso = [ISO3[c] for c in ccs]
        sub = df[df["ISO 3 code"].isin(iso)]
        # latest year with a total-generation value for every country of the region
        tg = sub[sub.Variable == "Total Generation"].pivot_table(index="Year", columns="ISO 3 code", values="Value")
        year = int(tg.dropna().index.max())
        sub = sub[sub.Year == year]
        short = f"Ember {year}"
        for cat, (qty, unit) in EMBER_CAT.items():
            s = sub[sub.Category == cat]
            if s.empty:
                continue
            note = {"generation": "net generation? Ember reports generation incl. own use as published by national sources",
                    "capacity": "Ember 'Other Fossil' -> oil, 'Other Renewables' -> geothermal",
                    "demand": "Ember demand = generation + net imports",
                    "emissions": "Ember uses life-cycle factors (non-fossil carriers non-zero)"}[qty]
            if qty in ("emissions",):  # only fossil + total are comparable with the model's combustion CO2
                s = s[s.carrier.isin(["coal", "gas", "oil", "total"])]
            agg = s.groupby("carrier").Value.sum(min_count=1)
            miss = s.groupby("carrier")["ISO 3 code"].nunique()
            if len(iso) > 1:
                note += f"; sum over {len(iso)} countries"
                partial = miss[miss < len(iso)]
                if len(partial):
                    note += " (" + ", ".join(f"{c}: {m}/{len(iso)}" for c, m in partial.items()) + " reporting)"
            out += rows(reg, "now", qty, unit, year, short, src, url, note, agg.to_dict())
            if qty == "demand" and len(iso) > 1:
                for i3, v in s.groupby("ISO 3 code").Value.sum().items():
                    out += rows(reg, "now", qty, unit, year, short, src, url, "Ember demand = generation + net imports",
                                {"total": v}, country=ISO2[i3])
    return pd.DataFrame(out)


def ember_prices(path, ember_path, regs):
    p = pd.read_csv(path)
    p["Date"] = pd.to_datetime(p["Date"])
    p["y"] = p.Date.dt.year
    full = p.groupby(["ISO3 Code", "y"]).size()
    full = full[full == 12].reset_index()
    year = int(full.y.max())                        # latest complete year in the file
    ann = p[p.y == year].groupby("ISO3 Code")["Price (EUR/MWhe)"].mean()
    dem = pd.read_csv(ember_path)
    dem = dem[(dem.Variable == "Demand") & (dem.Unit == "TWh") & (dem.Year == year)].groupby("ISO 3 code").Value.first()
    src = "Ember, European wholesale electricity price data (monthly)"
    url = "https://ember-energy.org/data/european-wholesale-electricity-price-data/"
    out = []
    for reg, ccs in regs.items():
        iso = [ISO3[c] for c in ccs if ISO3[c] in ann.index]
        if not iso:
            continue
        for i3 in iso:
            out += rows(reg, "now", "price", "EUR/MWh", year, f"Ember prices {year}", src, url,
                        "day-ahead, mean of monthly averages", {"total": ann[i3]}, country=ISO2[i3])
        if len(ccs) > 1:
            w = dem.reindex(iso)
            v = float((ann[iso] * w).sum() / w.sum())
            missing = sorted(set(ccs) - {ISO2[i] for i in iso})
            out += rows(reg, "now", "price", "EUR/MWh", year, f"Ember prices {year}", src, url,
                        f"day-ahead, mean of monthly averages, weighted by {year} demand" + (f"; no data for {', '.join(missing)}" if missing else ""),
                        {"total": v})
    return pd.DataFrame(out)


# ------------------------------------------------------------------------------------------ IRENA ----------
def irena(path, regs):
    df = pd.read_excel(path, sheet_name="Country")
    df = df[df["ISO3 code"].isin(ISO3.values())].assign(carrier=lambda x: x.Technology.map(IRENA_TECH))
    src = "IRENA (2025), Renewable Energy Statistics 2025 (IRENA_Statistics_Extract_2025H2.xlsx, sheet Country)"
    url = "https://www.irena.org/Data/Downloads/IRENASTAT"
    out = []
    # capacity only: IRENA generation lags a year and Ember + EI + national statistics already give three sources
    for qty, col, unit, scale in [("capacity", "Electricity Installed Capacity (MW)", "GW", 1e-3)]:
        for reg, ccs in regs.items():
            iso = [ISO3[c] for c in ccs]
            s = df[df["ISO3 code"].isin(iso) & df[col].notna() & (df[col] > 0)]
            if s.empty:
                continue
            year = int(s.groupby("Year")["ISO3 code"].nunique().pipe(lambda x: x[x == len(iso)]).index.max())
            s = s[s.Year == year]
            agg = s.groupby("carrier")[col].sum() * scale
            agg["total"] = float(s[col].sum() * scale)
            note = ("all producer types; pumped storage counted as hydro; 'Other non-renewable', marine -> other"
                    + (f"; sum over {len(iso)} countries" if len(iso) > 1 else ""))
            out += rows(reg, "now", qty, unit, year, f"IRENA {year}", src, url, note, agg.to_dict())
    return pd.DataFrame(out)


# ------------------------------------------------------------------------------------------ EI -------------
EI_LABEL = {"US": "US", "BR": "Brazil", "IN": "India", "SG": "Singapore", "AT": "Austria", "BE": "Belgium", "CH": "Switzerland",
            "CZ": "Czech Republic", "DE": "Germany", "DK": "Denmark", "FR": "France", "GB": "United Kingdom", "IE": "Ireland",
            "LU": "Luxembourg", "NL": "Netherlands", "PL": "Poland", "CN": "China"}


def _ei_wide(x, sheet, year):
    """Wide EI sheet (countries x years) -> Series label -> value of `year` (first column headed by that year)."""
    df = x.parse(sheet, header=None)
    hdr = df.index[df[0].astype(str).str.strip().isin(["Terawatt-hours", "Megawatts", "Gigawatts"])][0]
    cols = [c for c in df.columns[1:] if str(df.at[hdr, c]).split(".")[0] == str(year)]
    s = df.loc[hdr + 1:, [0, cols[0]]].dropna()
    s = s[s[0].astype(str).str.strip().isin(EI_LABEL.values())]
    return pd.to_numeric(s.set_index(s[0].astype(str).str.strip())[cols[0]], errors="coerce").dropna()


def _ei_block(x, sheet, year):
    """Two-year block sheet ('Elec generation by fuel', 'Renewables Generation by Source') -> DataFrame label x fuel."""
    df = x.parse(sheet, header=None)
    yrow = df.index[df.isin([year]).any(axis=1)][0]
    ycol = [c for c in df.columns if df.at[yrow, c] == year][0]
    hdr = yrow + 1
    names = df.loc[hdr]
    end = ycol
    start = [c for c in df.columns if c < ycol and (str(names[c]).strip() in ("Oil", "Wind"))]
    start = [c for c in start if c > (ycol - 9)][0]
    cols = list(range(start, end + 1))
    body = df.loc[hdr + 1:, [0] + cols].dropna(subset=[0])
    body = body[body[0].astype(str).str.strip().isin(EI_LABEL.values())]
    body.columns = ["label"] + [str(names[c]).strip().rstrip("#").strip() for c in cols]
    return body.set_index("label").apply(pd.to_numeric, errors="coerce")


def ei(path, regs, year=2024):
    """Energy Institute Statistical Review: generation by fuel (TWh) and wind/solar capacity (GW)."""
    if not os.path.exists(path):
        print(f"EI workbook {path} missing, skipping")
        return pd.DataFrame(columns=COLS)
    x = pd.ExcelFile(path)
    src = f"Energy Institute, Statistical Review of World Energy {year + 1} (EI-Stats-Review-ALL-data.xlsx)"
    url = "https://www.energyinst.org/statistical-review/resources-and-data-downloads"
    total = _ei_wide(x, "Electricity Generation - TWh", year)
    nuclear = _ei_wide(x, "Nuclear Generation - TWh", year)
    ren = _ei_block(x, "Renewables Generation by Source", year)
    fuel = _ei_block(x, "Elec generation by fuel", year)
    other = _ei_wide(x, "Geo Biomass Other - TWh", year)
    cap_solar = _ei_wide(x, "Solar Installed Capacity", year) / 1e3
    cap_wind = _ei_wide(x, "Wind Installed Capacity", year) / 1e3
    out = []
    for reg, ccs in regs.items():
        labs = [EI_LABEL[c] for c in ccs]
        gen = {"total": total.reindex(labs).sum(min_count=len(labs)), "nuclear": nuclear.reindex(labs).sum(min_count=len(labs)),
               "hydro": ren.Hydro.reindex(labs).sum(min_count=len(labs)), "wind": ren.Wind.reindex(labs).sum(min_count=len(labs)),
               "solar": ren.Solar.reindex(labs).sum(min_count=len(labs)), "biomass": other.reindex(labs).sum(min_count=len(labs))}
        note = "gross generation; 'biomass' = EI geothermal + biomass + other"
        if all(l in fuel.index for l in labs):
            gen.update({"coal": fuel.Coal.reindex(labs).sum(), "gas": fuel["Natural Gas"].reindex(labs).sum(), "oil": fuel.Oil.reindex(labs).sum()})
        else:
            note += "; coal/gas/oil not published for every country of the region"
        if len(labs) > 1:
            note += f"; sum over {len(labs)} countries"
        out += rows(reg, "now", "generation", "TWh", year, f"EI {year}", src, url, note, gen)
        cap = {"solar": cap_solar.reindex(labs).sum(min_count=len(labs)), "wind": cap_wind.reindex(labs).sum(min_count=len(labs))}
        out += rows(reg, "now", "capacity", "GW", year, f"EI {year}", src, url, "EI publishes capacity for solar and wind only", cap)
    return pd.DataFrame(out)


EI_GAS = {"US": ("US Henry Hub", "Henry Hub"), "NWE": ("Netherlands TTF", "TTF"),
          "CN": ("China (Mainland)", "LNG China (mainland) cif"), "IN": ("West India Marker", "LNG West India Marker (Platts WIM)"),
          "SG": ("Japan Korea Marker", "LNG Japan Korea Marker (Platts JKM)")}
EI_COAL = {"US": ("United States", 6900, "NAPP FOB Baltimore 6,900 kcal/kg NAR"), "NWE": ("Northwest Europe", 6000, "CIF ARA 6,000 kcal/kg NAR"),
           "CN": ("South China", 5500, "CFR South China 5,500 kcal/kg NAR"),
           "IN": ("South Africa", 5500, "FOB Richards Bay 5,500 kcal/kg NAR, India's import marker (domestic CIL coal is cheaper)")}
EI_OIL = {"US": "West Texas", "NWE": "Brent", "BR": "Brent", "CN": "Dubai", "IN": "Dubai", "SG": "Dubai"}


def _ei_price_sheet(x, sheet, year, header_row):
    """Price sheet (years x markers) -> {marker header (footnote digits stripped): value of `year`}."""
    df = x.parse(sheet, header=None)
    hdr = {c: re.sub(r"\d+$", "", str(df.at[header_row, c]).replace("\n", " ")).strip() for c in df.columns[1:]}
    row = df[df[0].astype(str).str.strip() == str(year)]
    if row.empty:
        return {}
    row = row.iloc[0]
    return {h: pd.to_numeric(row[c], errors="coerce") for c, h in hdr.items() if h and h != "nan"}


def ei_fuel(path, regs, fx, year=2024):
    """Energy Institute fuel-price markers of `year` -> fuel_price rows in EUR/MWh_th (NCV)."""
    if not os.path.exists(path):
        return pd.DataFrame(columns=COLS)
    x = pd.ExcelFile(path)
    gas = _ei_price_sheet(x, "Gas Prices ", year, 3)
    coal = _ei_price_sheet(x, "Coal & Uranium - Prices", year, 3)
    oil = _ei_price_sheet(x, "Spot crude prices", year, 1)
    usd = fxrate(fx, "USD", year)
    src = f"Energy Institute, Statistical Review of World Energy {year + 1}, sheets 'Gas Prices', 'Coal & Uranium - Prices', 'Spot crude prices' (S&P Global Commodity Insights)"
    url = "https://www.energyinst.org/statistical-review/resources-and-data-downloads"
    pick = lambda table, key: next((v for h, v in table.items() if h.startswith(key)), np.nan)
    out = []
    for reg in regs:
        vals, notes = {}, []
        if reg in EI_GAS:
            v = pick(gas, EI_GAS[reg][0])
            if pd.notna(v):
                vals["gas"] = v * MMBTU_PER_MWH * GCV_NCV_GAS / usd
                notes.append(f"gas: {EI_GAS[reg][1]} {v:.2f} USD/MMBtu (GCV) x{GCV_NCV_GAS} GCV/NCV")
        if reg in EI_COAL:
            key, kcal, desc = EI_COAL[reg]
            v = pick(coal, key)
            if pd.notna(v):
                vals["coal"] = v / (kcal * MWH_PER_KCAL_KG) / usd
                notes.append(f"coal: {desc} {v:.1f} USD/t = {kcal * MWH_PER_KCAL_KG:.2f} MWh/t")
        if reg in EI_OIL:
            v = pick(oil, EI_OIL[reg])
            if pd.notna(v):
                vals["oil"] = v / MWH_NCV_PER_BBL / usd
                notes.append(f"oil: {EI_OIL[reg]} crude {v:.1f} USD/bbl at {MWH_NCV_PER_BBL} MWh_NCV/bbl")
        if vals:
            out += rows(reg, "now", "fuel_price", "EUR/MWh_th", year, f"EI {year}", src, url,
                        "; ".join(notes) + f"; ECB USD {year} average {usd:.3f}", vals)
    return pd.DataFrame(out)


# ------------------------------------------------------------------------------------------ manual ---------
def manual(path, fx):
    if not os.path.exists(path):
        return pd.DataFrame(columns=COLS)
    m = pd.read_csv(path, dtype=str, keep_default_na=False, comment="#")
    m = m[m.value != ""].copy()
    m["value"] = m.value.astype(float)
    m["year"] = m.year.astype(int)
    m["carrier"] = m.carrier.str.strip()
    bad = set(m.carrier) - set(CARRIERS)
    if bad:
        raise SystemExit(f"manual_points.csv: unknown carriers {sorted(bad)}; allowed: {CARRIERS}")
    for i, r in m.iterrows():
        u = r.unit.strip()
        if u in ("TWh", "GW", "MtCO2", "EUR/MWh", "EUR/MWh_th"):
            continue
        if u in ("GWp", "GWac", "GWdc"):
            m.at[i, "unit"] = "GW"
        elif u == "MW":
            m.at[i, "value"], m.at[i, "unit"] = r.value / 1e3, "GW"
        elif u == "GWh":
            m.at[i, "value"], m.at[i, "unit"] = r.value / 1e3, "TWh"
        elif u == "ktCO2":
            m.at[i, "value"], m.at[i, "unit"] = r.value / 1e3, "MtCO2"
        elif re.match(r"^[A-Z]{3}(\d{4})?/", u):
            # <CUR>[<currency year>]/<per>: electricity MWh|kWh, or fuel MMBtu (gross CV) | bbl | t@<kcal>kcal (NAR)
            cur, per = u.split("/", 1)
            cur, fxy = cur[:3], int(cur[3:]) if len(cur) > 3 else int(r.year)
            if per in ("MWh", "kWh"):
                v, unit = r.value * (1e3 if per == "kWh" else 1.0), "EUR/MWh"
            elif per == "MMBtu":
                v, unit = r.value * MMBTU_PER_MWH * GCV_NCV_GAS, "EUR/MWh_th"
            elif per == "bbl":
                v, unit = r.value / MWH_NCV_PER_BBL, "EUR/MWh_th"
            elif re.match(r"^t@\d+kcal$", per):
                v, unit = r.value / (int(per[2:-4]) * MWH_PER_KCAL_KG), "EUR/MWh_th"
            else:
                raise SystemExit(f"manual_points.csv row {i}: unit '{u}' not understood")
            if cur != "EUR":
                v = v / fxrate(fx, cur, fxy)
            m.at[i, "note"] = (r.note + "; " if r.note else "") + f"converted from {r.value:g} {u}" + (
                f" at ECB {cur} {fxy} average" if cur != "EUR" else "") + (
                f" ({GCV_NCV_GAS} GCV/NCV)" if per == "MMBtu" else f" ({MWH_NCV_PER_BBL} MWh_NCV/bbl)" if per == "bbl" else "")
            m.at[i, "value"], m.at[i, "unit"] = v, unit
        else:
            raise SystemExit(f"manual_points.csv row {i}: unit '{u}' not understood")
    return m


def main(out, ember_csv, price_csv, irena_xlsx, fx_csv, manual_csv, ei_xlsx):
    regs = regions()
    fx = pd.read_csv(fx_csv)[["CURRENCY", "TIME_PERIOD", "OBS_VALUE"]]
    parts = [ember(ember_csv, regs), ember_prices(price_csv, ember_csv, regs), irena(irena_xlsx, regs), ei(ei_xlsx, regs),
             ei_fuel(ei_xlsx, regs, fx), manual(manual_csv, fx)]
    df = pd.concat([p for p in parts if len(p)], ignore_index=True)[COLS]
    df = df[df.region.isin(regs)]
    df = df[(df.value != 0) | (df.carrier == "total")]          # zero rows carry no information as dots
    df["value"] = df.value.astype(float).round(4)
    df = df.sort_values(["region", "scenario", "quantity", "source_short", "country", "carrier"]).reset_index(drop=True)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    df.to_csv(out, index=False)
    print(df.groupby(["region", "scenario", "quantity"]).source_short.nunique().unstack("quantity").fillna(0).astype(int).to_string())
    return df


if __name__ == "__main__":
    if "snakemake" in globals():
        i = snakemake.input  # noqa: F821
        main(snakemake.output[0], i.ember, i.prices, i.irena, i.fx, i.manual, i.ei)  # noqa: F821
    else:
        ap = argparse.ArgumentParser()
        ap.add_argument("--out", required=True)
        ap.add_argument("--ember", default=os.path.join(DATA, "yearly_full_release_long_format.csv"))
        ap.add_argument("--prices", default=os.path.join(DATA, "european_wholesale_electricity_price_data_monthly.csv"))
        ap.add_argument("--irena", default=os.path.join(CFG, "..", "models", "pypsa-earth", "data", "IRENA_Statistics_Extract_2025H2.xlsx"))
        ap.add_argument("--fx", default=os.path.join(DATA, "ecb_fx_annual.csv"))
        ap.add_argument("--manual", default=os.path.join(DATA, "manual_points.csv"))
        ap.add_argument("--ei", default=os.path.join(DATA, "EI-Stats-Review-ALL-data-2025.xlsx"))
        a = ap.parse_args()
        main(a.out, a.ember, a.prices, a.irena, a.fx, a.manual, a.ei)
