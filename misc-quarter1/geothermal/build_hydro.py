"""Hydropower companion dataset: costs, lifetimes, pumped-hydro site classes,
existing fleet.

No open site-level dataset of *undeveloped* conventional hydropower with costs
exists (see README: Gernaat 2017 is on request, Xu 2023 publishes code only,
Hoes 2017 is gross potential without costs), so conventional hydro is
described by regional cost statistics; off-river pumped hydro *is* covered
globally by the ANU atlas, whose cost model and regional site counts are used.

Inputs   data/irena_hydro_costs_2024.csv          transcribed IRENA tables
         data/anu_phes_global_summary.xlsx        ANU greenfield PHES atlas, sites by region / class
         data/anu_phes_simplified_calculator_2406.xlsx  ANU PHES cost model (2024 USD)
         data/glohydrores_v1.csv                  GloHydroRes existing plants (Sci. Data 2025)
         ../technology-costs/build/costs_2025_compiled.csv   lifetimes / FOM of technology-data
Outputs  build/hydro_costs.csv                  long table: technology, region, metric, value, unit
         build/phes_potential_by_region.csv     ANU site counts and GWh by region, configuration, class
         build/hydro_existing_by_country.csv    GloHydroRes capacity by country and plant type
Standalone: python build_hydro.py
"""

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).parent
if "snakemake" in globals():
    CFG = snakemake.config
    IRENA, ANU_SUM, ANU_CALC, GHR = (Path(snakemake.input[k]) for k in ("irena", "anu_summary", "anu_calc", "glohydrores"))
    TD = Path(snakemake.input.techdata)
    OUT_COSTS, OUT_PHES, OUT_EXIST = (Path(snakemake.output[k]) for k in ("costs", "phes", "existing"))
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    IRENA = HERE / "data/irena_hydro_costs_2024.csv"
    ANU_SUM = HERE / "data/anu_phes_global_summary.xlsx"
    ANU_CALC = HERE / "data/anu_phes_simplified_calculator_2406.xlsx"
    GHR = HERE / "data/glohydrores_v1.csv"
    TD = HERE / "../technology-costs/build/costs_2025_compiled.csv"
    OUT_COSTS, OUT_PHES, OUT_EXIST = (HERE / "build" / f for f in ("hydro_costs.csv", "phes_potential_by_region.csv", "hydro_existing_by_country.csv"))

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def read_xlsx(path):
    """{sheet name: list of rows (list of str)} with the standard library."""
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    names = [s.get("name") for s in wb.find("m:sheets", NS)]
    files = sorted((n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", n)),
                   key=lambda n: int(re.findall(r"\d+", n)[0]))
    out = {}
    for name, f in zip(names, files):
        rows = []
        for row in ET.fromstring(z.read(f)).iter("{%s}row" % NS["m"]):
            vals = []
            for c in row.findall("m:c", NS):
                v = c.find("m:v", NS)
                val = v.text if v is not None else ""
                if c.get("t") == "s" and val:
                    val = shared[int(val)]
                vals.append(val)
            rows.append(vals)
        out[name] = rows
    return out


def anu_cost(power_mw, head_m, sep_m, energy_gwh, wr_ratio, dam_usd_per_m3_2017=168, infl_2017_2024=0.81,
             eff_pump=0.88, eff_gen=0.88, usable=0.85, land_usd_m2=0.1, fill_usd_ml=25, depth_m=20):
    """The ANU simplified PHES cost model (2406-PHES-simplified-calculator.xlsx),
    2024 USD. Returns a dict of USD million components and unit costs."""
    P, H, S, E = power_mw, head_m, sep_m, energy_gwh
    avail_gl = E * 3600 / (9.8 * eff_gen * H)          # available water, GL (=Mm3)
    total_gl = avail_gl / usable
    rock_gl = total_gl / wr_ratio
    area_ha = 2 * 100 * total_gl / depth_m
    reservoirs = dam_usd_per_m3_2017 * rock_gl / infl_2017_2024          # USD million
    if H <= 800:
        tunnel = ((66000 * P + 17e6) + S * (1280 * P + 210000) * H ** (-0.54)) / 1e6 / infl_2017_2024
        powerhouse = 63.5 * H ** (-0.5) * P ** 0.75 / infl_2017_2024
    else:   # two tunnels and powerhouses of half head, half power, half separation
        tunnel = 2 * ((66000 * P / 2 + 17e6) + S / 2 * (1280 * P / 2 + 210000) * (H / 2) ** (-0.54)) / 1e6 / infl_2017_2024
        powerhouse = 2 * 63.5 * (H / 2) ** (-0.5) * (P / 2) ** 0.75 / infl_2017_2024
    land = land_usd_m2 * area_ha / 100
    fill = fill_usd_ml * total_gl / 1000
    total = reservoirs + tunnel + powerhouse + land + fill
    return {"reservoirs_musd": reservoirs, "tunnel_musd": tunnel, "powerhouse_musd": powerhouse,
            "land_musd": land, "fill_musd": fill, "total_musd": total,
            "power_usd_per_kw": (tunnel + powerhouse) * 1e3 / P, "energy_usd_per_kwh": reservoirs / E,
            "total_usd_per_kw": total * 1e3 / P, "total_usd_per_kwh": total / E,
            "fom_usd_per_kw_yr": 8210 / infl_2017_2024 / 1e3, "vom_usd_per_mwh_per_direction": 0.3 / infl_2017_2024}


def phes_regions(sheets):
    rows = []
    for name, data in sheets.items():
        if not name.endswith("Summary"):
            continue
        region = data[0][0].replace(" Summary", "") if data and data[0] else name
        region = name.replace(" Summary", "") if name != "Global Summary" else "Global"
        for r in data[5:]:
            if len(r) < 14 or not r[0] or "GWh" not in r[0]:
                continue
            cfg_ = r[0]
            gwh, hrs, gw = float(r[1]), float(r[2]), float(r[3])
            counts = [int(x) for x in r[4:9]]
            energy = [float(x) for x in r[10:15]] if len(r) >= 15 else [c * gwh for c in counts]
            for cls, cnt, en in zip("ABCDE", counts, energy):
                rows.append({"region": region, "configuration": cfg_, "energy_gwh": gwh, "hours": hrs,
                             "power_gw": gw, "site_class": cls, "n_sites": cnt, "energy_total_gwh": en})
    return pd.DataFrame(rows)


def main():
    ir = pd.read_csv(IRENA)
    td = pd.read_csv(TD, header=None)
    td.columns = ["technology", "parameter", "value", "unit", "value_orig", "unit_orig", "currency", "currency_year",
                  "source", "n", "further", "x", "note"][: td.shape[1]]
    rows = []
    for _, r in ir.iterrows():
        rows.append({"technology": r["technology"], "region": r["region"], "period": r["period"],
                     "size_class": r["size_class"], "metric": r["metric"], "value": r["value"], "unit": r["unit"],
                     "currency_year": r["currency_year"], "source": r["source"], "note": r["note"]})
    for tech, life in CFG["hydro"]["lifetime_years"].items():
        rows.append({"technology": tech, "region": "Global", "period": "", "size_class": "", "metric": "lifetime",
                     "value": life, "unit": "years", "currency_year": "",
                     "source": "PyPSA technology-data v0.15.0 via ../technology-costs/build/costs_2025_compiled.csv", "note": ""})
    for tech in ("hydro", "ror", "PHS"):
        sub = td[(td["technology"] == tech) & (td["parameter"].isin(["investment", "investment_kw", "investment_kwh", "FOM", "FOM_kwh"]))]
        for _, r in sub.iterrows():
            rows.append({"technology": tech, "region": "Global (Europe-centric)", "period": "2025", "size_class": "",
                         "metric": f"technology_data_{r['parameter']}", "value": r["value"], "unit": r["unit"],
                         "currency_year": 2024, "source": f"PyPSA technology-data v0.15.0 ({r['source']}) via ../technology-costs",
                         "note": "converted to USD2024 by ../technology-costs"})
    # ANU PHES cost model at the atlas configurations
    s = CFG["hydro"]["anu_default_site"]
    for gwh, hrs in [(2, 6), (5, 6), (5, 18), (15, 6), (15, 18), (50, 6), (50, 18), (150, 18), (150, 50), (500, 168)]:
        P = gwh / hrs * 1000
        c = anu_cost(P, s["head_m"], s["separation_m"], gwh, s["water_rock_ratio"])
        for k in ("power_usd_per_kw", "energy_usd_per_kwh", "total_usd_per_kw", "total_usd_per_kwh", "fom_usd_per_kw_yr",
                  "vom_usd_per_mwh_per_direction"):
            rows.append({"technology": "PHS (off-river, ANU model)", "region": "site-generic", "period": "2024",
                         "size_class": f"{gwh} GWh / {hrs} h ({P:.0f} MW)", "metric": k, "value": c[k],
                         "unit": k.split("_", 1)[1].replace("_", "/"), "currency_year": 2024,
                         "source": "ANU RE100 PHES simplified calculator (June 2024), Blakers et al.",
                         "note": f"head {s['head_m']} m, separation {s['separation_m']} m, water/rock {s['water_rock_ratio']}; class ~AA site"})
    # class ladder: cost relative to the A/B benchmark
    bench = anu_cost(s["power_mw"], s["head_m"], s["separation_m"], s["energy_gwh"], s["water_rock_ratio"])["total_musd"] / 0.42141287543203582
    rows.append({"technology": "PHS (off-river, ANU model)", "region": "site-generic", "period": "2024",
                 "size_class": "1000 MW / 100 GWh", "metric": "class_A_B_benchmark_total_usd_per_kw",
                 "value": bench * 1e3 / s["power_mw"], "unit": "USD/kW", "currency_year": 2024,
                 "source": "inferred from the calculator's default example (cost / benchmark = 0.4214 for its default site)",
                 "note": "classes: AAA < 0.33, AA < 0.67, A < 1.0, B < 1.25, C < 1.5, D < 1.75, E < 2.0 x benchmark"})
    for cls, f in CFG["hydro"]["anu_class_ladder"].items():
        rows.append({"technology": "PHS (off-river, ANU model)", "region": "site-generic", "period": "2024",
                     "size_class": "1000 MW / 100 GWh", "metric": f"class_{cls}_max_total_usd_per_kwh",
                     "value": f * bench / s["energy_gwh"], "unit": "USD/kWh", "currency_year": 2024,
                     "source": "ANU class ladder x inferred benchmark", "note": "upper bound of the class, 100 h storage"})
    costs = pd.DataFrame(rows)
    OUT_COSTS.parent.mkdir(parents=True, exist_ok=True)
    costs.to_csv(OUT_COSTS, index=False, float_format="%.5g")

    phes = phes_regions(read_xlsx(ANU_SUM))
    phes.to_csv(OUT_PHES, index=False)

    g = pd.read_csv(GHR, low_memory=False)
    ex = (g.pivot_table(index="country", columns="plant_type", values="capacity_mw", aggfunc="sum", fill_value=0)
          .assign(total_mw=lambda d: d.sum(axis=1), n_plants=g.groupby("country").size()))
    ex.to_csv(OUT_EXIST, float_format="%.1f")
    print(f"hydro_costs: {len(costs)} rows; PHES regions: {phes['region'].nunique()}; "
          f"GloHydroRes: {len(g):,} plants, {ex['total_mw'].sum() / 1e3:,.0f} GW")
    print(costs[costs["metric"].str.startswith("total_usd")].pivot_table(index="size_class", columns="metric", values="value").round(0).to_string())


if __name__ == "__main__" or "snakemake" in globals():
    main()
