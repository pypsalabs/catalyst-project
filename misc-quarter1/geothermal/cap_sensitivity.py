"""Sensitivity of the EGS supply to the temperature cap of the cost model (config egs.t_max_c).

The Ricks & Jenkins plant cost and output fits are binary-cycle fits up to 200 C and linear extrapolations above;
`t_max_c` caps the (ambient-corrected) production temperature fed into them, so hotter rock earns nothing more.
The cheapest tranches of most regions sit at 250-380 C, i.e. in the extrapolated range. For each cap in
`egs.t_max_sensitivity_c`: the cheapest LCOE and the first 10 GW (CAPEX, LCOE, depth, rock temperature) per region of
`modelled_regions` + `sensitivity_regions`, and the cell of every `site_checks` site at its LCOE-optimal depth.
Same cost chain as build_egs_potential.py (USD of base_currency_year, net kW, LCOE without grid connection).

Output  build/t_max_sensitivity.csv
Standalone: python cap_sensitivity.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import yaml

HERE = Path(__file__).parent
if "snakemake" in globals():
    CFG = snakemake.config
    EGS_GRID, OUT = Path(snakemake.input.grid), Path(snakemake.output[0])
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    EGS_GRID, OUT = HERE / "build" / "egs_grid.nc", HERE / "build" / "t_max_sensitivity.csv"

import sys
sys.path.insert(0, str(HERE))
from aggregate_regions import region_masks  # noqa: E402
from build_egs_potential import crf  # noqa: E402
from egs_cost_model import egs_costs  # noqa: E402

TRANCHE_GW = 10.0


def cheapest(g, e, t_max, infl, ann, net):
    """LCOE-optimal depth per cell under cap t_max: (depth index, capex, lcoe, capacity MW) arrays."""
    depths = g["depth"].values
    t = g["t_c"].values
    lc = np.full(t.shape, np.inf)
    capex = np.full(t.shape, np.nan)
    for j, d in enumerate(depths):
        r = egs_costs(t[:, j], g["air_temp_k"].values, d, producers_per_injector=e["producers_per_injector"],
                      stimulate_producers=e["stimulate_producers"], lateral_length_m=e["lateral_length_m"],
                      flow_derating=e["flow_derating"], resource_derating=1.0,
                      drill_cost_multiplier=e["drill_cost_multiplier"], plant_size_mw=e["plant_size_mw"], t_max_c=t_max)
        c = (r["plant_capex_usd_per_kw"] + r["well_capex_usd_per_kw"]) * infl / net
        f = r["fom_usd_per_kw_yr"] * infl / net
        feas = t[:, j] >= e["t_min_c"]
        capex[:, j] = c
        lc[:, j] = np.where(feas, (c * ann + f) / (8.76 * e["capacity_factor"]), np.inf)
    jb = np.argmin(lc, axis=1)
    rows = np.arange(len(jb))
    # capacity at the chosen depth: the grid's own capacity per depth (cap-independent density x land share)
    cap = g["capacity_mw"].values[rows, jb]
    return jb, capex[rows, jb], lc[rows, jb], np.nan_to_num(cap)


def main():
    e = CFG["egs"]
    cpi = yaml.safe_load((HERE / CFG["tech_costs_config"]).read_text())["cpi"]["USD"]
    infl = cpi[CFG["base_currency_year"]] / cpi[e["cost_model_currency_year"]]
    ann = crf(e["wacc"], e["lifetime_years"])
    net = 1 - e.get("parasitic_fraction", 0.0)
    g = xr.open_dataset(EGS_GRID)
    depths = g["depth"].values
    keep = g["remote_territory"].values == 0
    df = pd.DataFrame({k: g[k].values for k in ("iso3", "country", "continent", "admin1", "lon", "lat")})
    masks, names = region_masks(df)
    regions = CFG["modelled_regions"] + CFG.get("sensitivity_regions", [])
    step = CFG["grid"]["step_deg"]
    out = []
    for t_max in e["t_max_sensitivity_c"]:
        jb, capex, lcoe, cap = cheapest(g, e, t_max, infl, ann, net)
        ok = np.isfinite(lcoe) & keep
        for reg in regions:
            m = masks[reg] & ok
            if not m.any():
                continue
            o = np.argsort(lcoe[m])
            c = cap[m][o] / 1e3
            tr = np.cumsum(c) <= TRANCHE_GW
            tr[0] = True
            w = np.where(c[tr] > 0, c[tr], 1e-9)
            out.append({"t_max_c": t_max, "region": reg, "name": names[reg],
                        "lcoe_min_usd_per_mwh": lcoe[m][o][0],
                        "capex_first_10gw_usd_per_kw": np.average(capex[m][o][tr], weights=w),
                        "lcoe_first_10gw_usd_per_mwh": np.average(lcoe[m][o][tr], weights=w),
                        "depth_first_10gw_km": np.average(depths[jb[m][o][tr]], weights=w),
                        "t_rock_first_10gw_c": np.average(g["t_c"].values[np.flatnonzero(m)[o][tr], jb[m][o][tr]], weights=w),
                        "potential_gw_lcoe_le_100": c[lcoe[m][o] <= 100].sum()})
        for key, s in CFG["site_checks"].items():
            clon, clat = (np.floor(np.array([s["lon"], s["lat"]]) / step) + 0.5) * step
            i = np.flatnonzero(np.isclose(df["lon"], clon) & np.isclose(df["lat"], clat))[0]
            out.append({"t_max_c": t_max, "region": f"site:{key}", "name": s["name"], "lcoe_min_usd_per_mwh": lcoe[i],
                        "capex_first_10gw_usd_per_kw": capex[i], "lcoe_first_10gw_usd_per_mwh": lcoe[i],
                        "depth_first_10gw_km": depths[jb[i]], "t_rock_first_10gw_c": g["t_c"].values[i, jb[i]]})
    res = pd.DataFrame(out)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT, index=False, float_format="%.5g")
    pd.set_option("display.width", 220)
    for col in ("lcoe_min_usd_per_mwh", "capex_first_10gw_usd_per_kw", "depth_first_10gw_km", "t_rock_first_10gw_c"):
        print(f"\n{col}")
        print(res.pivot(index="region", columns="t_max_c", values=col).loc[
            [r for r in regions if r in res["region"].values] + [f"site:{k}" for k in CFG["site_checks"]]].round(1).to_string())


if __name__ == "__main__" or "snakemake" in globals():
    main()
