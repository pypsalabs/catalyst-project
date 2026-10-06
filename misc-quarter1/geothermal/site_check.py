"""The EGS cost model at real project sites: build/site_check.csv.

For every site under `site_checks` in config.yaml (Fervo Cape Station), the 0.25 deg cell of build/egs_potential.csv
that contains it, and for each fitted depth the drilling cost of one cased horizontal well (egs_cost_model.well_costs,
the configured lateral, stimulation excluded), its measured length (vertical depth + lateral) and the cost per foot,
in USD of base_currency_year. The row at the cell's LCOE-optimal depth carries `model_depth = True` and the cell's
CAPEX / LCOE; ../technology-costs draws its cost per foot on the Fervo drilling figure (config `model_point`).

Standalone: python site_check.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from egs_cost_model import DEPTHS, well_costs

HERE = Path(__file__).parent
if "snakemake" in globals():
    CFG = snakemake.config
    POT, OUT = Path(snakemake.input.potential), Path(snakemake.output[0])
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    POT, OUT = HERE / "build" / "egs_potential.csv", HERE / "build" / "site_check.csv"

FT_PER_M = 1 / 0.3048


def main():
    e, step = CFG["egs"], CFG["grid"]["step_deg"]
    cpi = yaml.safe_load((HERE / CFG["tech_costs_config"]).read_text())["cpi"]["USD"]
    infl = cpi[CFG["base_currency_year"]] / cpi[e["cost_model_currency_year"]]
    pot = pd.read_csv(POT, usecols=["lon", "lat", "depth_km", "t_reservoir_c", "capex_usd_per_kw", "lcoe_usd_per_mwh"])
    rows = []
    for key, s in CFG["site_checks"].items():
        # centre of the cell that contains the site
        clon, clat = (np.floor(np.array([s["lon"], s["lat"]]) / step) + 0.5) * step
        cell = pot[np.isclose(pot["lon"], clon) & np.isclose(pot["lat"], clat)]
        if cell.empty:
            raise ValueError(f"{key}: no feasible EGS cell at ({clon}, {clat})")
        cell = cell.iloc[0]
        for d in DEPTHS:
            cased, _ = well_costs(d, e["lateral_length_m"], e["drill_cost_multiplier"])
            md_ft = (d * 1000 + e["lateral_length_m"]) * FT_PER_M
            best = np.isclose(d, cell["depth_km"])
            rows.append({"site": key, "name": s["name"], "lon": s["lon"], "lat": s["lat"], "cell_lon": clon,
                         "cell_lat": clat, "depth_km": d, "model_depth": bool(best),
                         "well_length_ft": round(md_ft), "well_cost_usd": round(cased * infl),
                         "drilling_usd_per_ft": round(cased * infl / md_ft, 1),
                         "t_reservoir_c": round(cell["t_reservoir_c"], 1) if best else np.nan,
                         "capex_usd_per_kw": round(cell["capex_usd_per_kw"]) if best else np.nan,
                         "lcoe_usd_per_mwh": round(cell["lcoe_usd_per_mwh"], 1) if best else np.nan})
    df = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(df.to_string(index=False))


if __name__ == "__main__" or "snakemake" in globals():
    main()
