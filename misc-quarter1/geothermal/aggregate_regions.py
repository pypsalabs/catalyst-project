"""Supply curves and summary tables per country and per composite region.

Inputs   build/egs_potential.csv
Outputs  build/egs_supply_curves.csv   region x LCOE bin: capacity in the bin and cumulative,
                                       capacity-weighted CAPEX / FOM of the bin
         build/egs_region_summary.csv  one row per region: potential below LCOE thresholds,
                                       cost of the cheapest tranche, depth, resource temperature

Regions: every ISO3 with feasible cells, plus the composites in config.yaml
(US West/East, Australia SWIS, North-West Europe, IEA comparison groups).
Standalone: python aggregate_regions.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).parent
if "snakemake" in globals():
    CFG = snakemake.config
    POT = Path(snakemake.input[0])
    OUT_SC, OUT_SUM = Path(snakemake.output.curves), Path(snakemake.output.summary)
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    POT = HERE / "build" / "egs_potential.csv"
    OUT_SC, OUT_SUM = HERE / "build" / "egs_supply_curves.csv", HERE / "build" / "egs_region_summary.csv"

THRESHOLDS = (75, 100, 150, 200, 300)   # USD/MWh
TRANCHE_GW = 10.0


def region_masks(df):
    masks = {}
    for iso, sub in df.groupby("iso3"):
        masks[iso] = (df["iso3"] == iso).values
    names = df.drop_duplicates("iso3").set_index("iso3")["country"].to_dict()
    for key, spec in CFG["regions"].items():
        if "members" in spec:
            m = df["iso3"].isin(spec["members"]).values
        elif "continent" in spec:
            m = (df["continent"] == spec["continent"]).values
        elif "admin1_codes" in spec:
            m = ((df["iso3"] == spec["iso3"]) & df["admin1"].isin(spec["admin1_codes"])).values
        elif "admin1_complement_of" in spec:
            other = CFG["regions"][spec["admin1_complement_of"]]
            m = ((df["iso3"] == spec["iso3"]) & ~df["admin1"].isin(other["admin1_codes"])).values
        else:
            raise ValueError(key)
        masks[key] = m
        names[key] = spec["name"]
    return masks, names


def wavg(x, w):
    return float(np.average(x, weights=w)) if w.sum() > 0 else np.nan


def main():
    df = pd.read_csv(POT, dtype={"admin1": str, "iso3": str})
    bins = CFG["egs"]["lcoe_bins"]
    masks, names = region_masks(df)
    curves, summary = [], []
    for key, m in masks.items():
        sub = df[m]
        if sub.empty or sub["capacity_mw"].sum() <= 0:
            continue
        sub = sub.sort_values("lcoe_usd_per_mwh")
        cap = sub["capacity_mw"].values / 1000  # GW
        lcoe = sub["lcoe_usd_per_mwh"].values
        cum = np.cumsum(cap)
        lo = 0
        for hi in bins:
            sel = (lcoe > lo) & (lcoe <= hi)
            curves.append({
                "region": key, "name": names[key], "lcoe_min_usd_per_mwh": lo, "lcoe_max_usd_per_mwh": hi,
                "capacity_gw": cap[sel].sum(), "capacity_cumulative_gw": cap[lcoe <= hi].sum(),
                "capex_usd_per_kw": wavg(sub["capex_usd_per_kw"].values[sel], cap[sel]),
                "fom_usd_per_kw_yr": wavg(sub["fom_usd_per_kw_yr"].values[sel], cap[sel]),
                "depth_km": wavg(sub["depth_km"].values[sel], cap[sel]),
                "t_reservoir_c": wavg(sub["t_reservoir_c"].values[sel], cap[sel]),
            })
            lo = hi
        tr = cum <= TRANCHE_GW
        if not tr.any():
            tr[0] = True
        row = {"region": key, "name": names[key], "land_area_1000km2": sub["area_km2"].sum() / 1e3,
               "potential_gw": cap.sum(), "lcoe_min_usd_per_mwh": lcoe.min(),
               "capex_min_usd_per_kw": sub["capex_usd_per_kw"].min()}
        for t in THRESHOLDS:
            row[f"potential_gw_lcoe_le_{t}"] = cap[lcoe <= t].sum()
        row.update({
            f"capex_first_{TRANCHE_GW:.0f}gw_usd_per_kw": wavg(sub["capex_usd_per_kw"].values[tr], cap[tr]),
            f"fom_first_{TRANCHE_GW:.0f}gw_usd_per_kw_yr": wavg(sub["fom_usd_per_kw_yr"].values[tr], cap[tr]),
            f"lcoe_first_{TRANCHE_GW:.0f}gw_usd_per_mwh": wavg(lcoe[tr], cap[tr]),
            f"depth_first_{TRANCHE_GW:.0f}gw_km": wavg(sub["depth_km"].values[tr], cap[tr]),
            f"t_reservoir_first_{TRANCHE_GW:.0f}gw_c": wavg(sub["t_reservoir_c"].values[tr], cap[tr]),
            "lifetime_years": CFG["egs"]["lifetime_years"], "capacity_factor": CFG["egs"]["capacity_factor"],
        })
        summary.append(row)
    sc = pd.DataFrame(curves)
    sm = pd.DataFrame(summary).sort_values("potential_gw", ascending=False)
    OUT_SC.parent.mkdir(parents=True, exist_ok=True)
    sc.to_csv(OUT_SC, index=False, float_format="%.5g")
    sm.to_csv(OUT_SUM, index=False, float_format="%.5g")
    show = sm.set_index("region").loc[[r for r in CFG["modelled_regions"] if r in sm["region"].values]]
    cols = ["potential_gw", "potential_gw_lcoe_le_100", "potential_gw_lcoe_le_150", "lcoe_min_usd_per_mwh",
            f"capex_first_{TRANCHE_GW:.0f}gw_usd_per_kw", f"depth_first_{TRANCHE_GW:.0f}gw_km"]
    pd.set_option("display.width", 200)
    print(show[cols].round(0).to_string())


if __name__ == "__main__" or "snakemake" in globals():
    main()
