"""Apply the EGS cost model to every land cell and depth; pick the LCOE-optimal depth.

Inputs   build/temperature_grid.nc (build_temperature_grid.py)
         build/land_availability.nc (build_land_availability.py): share of each cell available after the
                                    onshore-wind exclusions of PyPSA-Earth; capacity = technical density x
                                    cell area x this share (it replaces the cost model's flat 20 % derating)
Outputs  build/egs_grid.nc          every cell x depth: CAPEX split, FOM, capacity, LCOE
         build/egs_potential.csv    one row per cell at its cheapest feasible depth
                                    (the headline dataset: CAPEX, OPEX, lifetime, potential)

Monetary values are converted from the cost model's 2021 USD to the repo's
base year with the US CPI table of ../technology-costs/config.yaml. LCOE uses
the 7 % real WACC convention of that workflow and excludes grid connection. Costs and capacity are per net
kW: the cost model's output excludes wellfield pumping, netted out with `parasitic_fraction`.
Standalone: python build_egs_potential.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import yaml

HERE = Path(__file__).parent
if "snakemake" in globals():
    CFG = snakemake.config
    GRID = Path(snakemake.input.grid)
    AVAIL = Path(snakemake.input.availability)
    OUT_NC, OUT_CSV = Path(snakemake.output.nc), Path(snakemake.output.csv)
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    GRID = HERE / "build" / "temperature_grid.nc"
    AVAIL = HERE / "build" / "land_availability.nc"
    OUT_NC, OUT_CSV = HERE / "build" / "egs_grid.nc", HERE / "build" / "egs_potential.csv"

import sys
sys.path.insert(0, str(HERE))
from egs_cost_model import egs_costs  # noqa: E402


def _lookup(av, lat, lon):
    """Value of the 0.25 deg availability grid at the cell centres; 0 outside its extent."""
    la, lo = av["lat"].values, av["lon"].values
    i = np.round((la[0] - lat) / (la[0] - la[1])).astype(int)
    k = np.round((lon - lo[0]) / (lo[1] - lo[0])).astype(int)
    inside = (i >= 0) & (i < len(la)) & (k >= 0) & (k < len(lo))
    out = np.zeros(len(lat))
    out[inside] = av.values[i[inside], k[inside]]
    ok = inside & np.isclose(la[np.clip(i, 0, len(la) - 1)], lat) & np.isclose(lo[np.clip(k, 0, len(lo) - 1)], lon)
    if not ok[inside].all():
        raise ValueError("availability grid and EGS cells are not aligned")
    return np.nan_to_num(out)


def crf(rate, years):
    return rate / (1 - (1 + rate) ** (-years)) if rate > 0 else 1 / years


def main():
    e = CFG["egs"]
    cpi = yaml.safe_load((HERE / CFG["tech_costs_config"]).read_text())["cpi"]["USD"]
    infl = cpi[CFG["base_currency_year"]] / cpi[e["cost_model_currency_year"]]
    ann = crf(e["wacc"], e["lifetime_years"])
    cf = e["capacity_factor"]
    # the cost model's output excludes wellfield pumping: costs per net kW and net MW
    net = 1 - e.get("parasitic_fraction", 0.0)

    g = xr.open_dataset(GRID)
    depths = g["depth"].values
    n = g.sizes["cell"]
    fields = ["capex_usd_per_kw", "plant_capex_usd_per_kw", "well_capex_usd_per_kw",
              "fom_usd_per_kw_yr", "lcoe_usd_per_mwh", "capacity_mw", "mw_per_km2", "feasible"]
    out = {f: np.full((n, len(depths)), np.nan) for f in fields}
    area = g["area_km2"].values
    air = g["air_temp_k"].values
    # available share of each cell (land-use exclusions as for onshore wind); none outside the land-cover extent
    av = xr.open_dataset(AVAIL)["available_fraction"]
    avail = _lookup(av, g["lat"].values, g["lon"].values)
    for j, d in enumerate(depths):
        t = g["t_c"].values[:, j]
        r = egs_costs(t, air, d, producers_per_injector=e["producers_per_injector"],
                      stimulate_producers=e["stimulate_producers"], lateral_length_m=e["lateral_length_m"],
                      flow_derating=e["flow_derating"], resource_derating=1.0,   # technical density; land share below
                      drill_cost_multiplier=e["drill_cost_multiplier"], plant_size_mw=e["plant_size_mw"],
                      t_max_c=e["t_max_c"])
        feas = t >= e["t_min_c"]
        plant = r["plant_capex_usd_per_kw"] * infl / net
        well = r["well_capex_usd_per_kw"] * infl / net
        fom = r["fom_usd_per_kw_yr"] * infl / net
        capex = plant + well
        lcoe = (capex * ann + fom) / (8.76 * cf)
        out["plant_capex_usd_per_kw"][:, j] = np.where(feas, plant, np.nan)
        out["well_capex_usd_per_kw"][:, j] = np.where(feas, well, np.nan)
        out["capex_usd_per_kw"][:, j] = np.where(feas, capex, np.nan)
        out["fom_usd_per_kw_yr"][:, j] = np.where(feas, fom, np.nan)
        out["lcoe_usd_per_mwh"][:, j] = np.where(feas, lcoe, np.nan)
        out["mw_per_km2"][:, j] = np.where(feas, r["mw_per_km2"] * net, np.nan)
        out["capacity_mw"][:, j] = np.where(feas, r["mw_per_km2"] * net * area * avail, np.nan)
        out["feasible"][:, j] = feas
        print(f"{d} km: {feas.mean():5.1%} of land cells >= {e['t_min_c']} C, "
              f"median CAPEX {np.nanmedian(capex[feas]) if feas.any() else np.nan:,.0f} USD{CFG['base_currency_year']}/kW")

    ds = g.copy()
    for f in fields:
        ds[f] = (("cell", "depth"), out[f])
    ds.attrs.update({
        "cost_model": "Ricks & Jenkins, Joule 2025 (Zenodo 10.5281/zenodo.15485307), GETEM-derived, converted 2021->%d USD (x%.4f)" % (CFG["base_currency_year"], infl),
        "currency": f"USD{CFG['base_currency_year']}", "lifetime_years": e["lifetime_years"],
        "capacity_factor": cf, "parasitic_fraction": 1 - net, "wacc": e["wacc"], "t_min_c": e["t_min_c"], "t_max_c": e["t_max_c"],
        "land_availability": xr.open_dataset(AVAIL).attrs.get("source", ""), "lcoe_note": "excludes grid connection",
    })
    OUT_NC.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(OUT_NC)

    # cheapest feasible depth per cell
    lc = out["lcoe_usd_per_mwh"]
    has = np.isfinite(lc).any(axis=1)
    jbest = np.nanargmin(np.where(np.isfinite(lc), lc, np.inf), axis=1)
    rows = np.arange(n)
    df = pd.DataFrame({
        "lon": g["lon"].values, "lat": g["lat"].values, "iso3": g["iso3"].values,
        "country": g["country"].values, "continent": g["continent"].values,
        "subregion": g["subregion"].values, "admin1": g["admin1"].values, "t_source": g["t_source"].values,
        "area_km2": area, "heat_flow_mwm2": g["heat_flow_mwm2"].values,
        "t_surface_c": g["t_surface_c"].values,
        "depth_km": depths[jbest], "t_reservoir_c": g["t_c"].values[rows, jbest],
        "capex_usd_per_kw": out["capex_usd_per_kw"][rows, jbest],
        "plant_capex_usd_per_kw": out["plant_capex_usd_per_kw"][rows, jbest],
        "well_capex_usd_per_kw": out["well_capex_usd_per_kw"][rows, jbest],
        "fom_usd_per_kw_yr": out["fom_usd_per_kw_yr"][rows, jbest],
        "vom_usd_per_mwh": 0.0,
        "lifetime_years": e["lifetime_years"], "capacity_factor": cf,
        "lcoe_usd_per_mwh": out["lcoe_usd_per_mwh"][rows, jbest],
        "mw_per_km2": out["mw_per_km2"][rows, jbest],   # technical density, before the land share
        "available_fraction": avail,
        "capacity_mw": out["capacity_mw"][rows, jbest],
    })
    df = df[has].reset_index(drop=True)
    print(f"land availability: area-weighted mean share {np.average(df['available_fraction'], weights=df['area_km2']):.1%} "
          f"of feasible cell area (was a flat 20 %)")
    df.to_csv(OUT_CSV, index=False, float_format="%.6g")   # 6 digits: lon/lat must survive the round trip
    tot = df["capacity_mw"].sum() / 1e6
    print(f"{len(df):,} feasible cells, {tot:.1f} TW developable at <= {depths.max()} km "
          f"(median CAPEX {df['capex_usd_per_kw'].median():,.0f} USD/kW, "
          f"capacity-weighted {np.average(df['capex_usd_per_kw'], weights=df['capacity_mw']):,.0f})")


if __name__ == "__main__" or "snakemake" in globals():
    main()
