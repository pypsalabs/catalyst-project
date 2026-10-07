"""Technology table of the toy model from technology_assumptions.csv (misc-quarter1/toymodel-clean-procurement).

The CSV (config `assumptions`) is read through the validated reader of the assumptions document
(config-pypsa-earth/technology-assumptions/scripts/build_table.py) and turned into one row per model
technology for a given site country:

  capital_cost_power   USD per MW per year = 1e3 x (capex_power x annuity(rate, lifetime) + fom_power)
  capital_cost_energy  USD per MWh per year (storage)
  marginal_cost        vom + fuel / efficiency
  p_max_pu             capacity_factor of firm technologies (availability); p_min_pu = config `min_load`, default 0:
                       firm plants dispatch freely, they are not forced to run as baseload
  efficiency           round trip of a storage (squared where the CSV value is per direction)

Site-specific technologies (EGS, hydrothermal) take their costs from the geothermal supply curves
within `geothermal.radius_km` of the site: `egs_tranches` is ../pareto/techs.py's, `hydrothermal_tranche`
fills plants without a cost class from the country table. `check_coverage` refuses to run when a CSV row
is neither in the palette nor in the excluded list.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "config-pypsa-earth").is_dir())
sys.path.insert(0, str(ROOT / "config-pypsa-earth" / "technology-assumptions" / "scripts"))
from build_table import NUMERIC, annuity, read  # noqa: E402  (the document's validated CSV reader)

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("pareto_techs", HERE.parent / "pareto" / "techs.py")
_pareto = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pareto)                                  # pareto's supply-curve helpers (same module name as this file)
TRANCHE_COLUMNS, egs_tranches, haversine_km = _pareto.TRANCHE_COLUMNS, _pareto.egs_tranches, _pareto.haversine_km

__all__ = ["annuity", "egs_tranches", "haversine_km", "TRANCHE_COLUMNS", "load_config", "load_assumptions",
           "components", "site_tranches", "check_coverage"]


def load_config(path: Path | None = None) -> dict:
    path = Path(path) if path else HERE / "config.yaml"
    cfg = yaml.safe_load(path.read_text())
    cfg["_dir"] = path.parent
    return cfg


def load_assumptions(cfg: dict) -> pd.DataFrame:
    """technology_assumptions.csv as numbers, indexed by technology (blank = NaN)."""
    df = read(cfg["_dir"] / cfg["assumptions"])
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c].replace("", np.nan))
    return df.set_index("technology")


def check_coverage(cfg: dict, table: pd.DataFrame) -> None:
    used = set()
    for tech, spec in cfg["palette"].items():
        rows = spec.get("rows")
        used |= set(rows.values()) if rows else {tech}
    excluded = set(cfg["excluded"])
    missing = set(table.index) - used - excluded
    unknown = (used | excluded) - set(table.index)
    if missing or unknown:
        raise SystemExit(f"technology_assumptions.csv rows not placed in config palette/excluded: {sorted(missing)}; "
                         f"config names without a CSV row: {sorted(unknown)}")


def components(cfg: dict, table: pd.DataFrame, country: str) -> pd.DataFrame:
    """One row per palette technology for a site in `country` (ISO2)."""
    rate = cfg["discount_rate"]
    out = []
    for tech, spec in cfg["palette"].items():
        rows = spec.get("rows")
        row_key = (rows.get(country, rows["default"]) if rows else tech)
        r = table.loc[row_key]
        life = float(r["lifetime_yr"])
        cp = float(np.nan_to_num(r["capex_power_usd_kw"]))
        ce = float(np.nan_to_num(r["capex_energy_usd_kwh"]))
        fom = float(np.nan_to_num(r["fom_usd_kw_yr"]))
        vom = float(np.nan_to_num(r["vom_usd_mwh"]))
        fuel = float(np.nan_to_num(r["fuel_usd_mwh_th"]))
        eff = float(r["efficiency"]) if not np.isnan(r["efficiency"]) else 1.0
        rec = dict(tech=tech, row=row_key, label=r["label"], group=r["group"], kind=r["kind"], model=spec["model"],
                   capex_power=cp, capex_energy=ce, lifetime=life, efficiency=eff, marginal_cost=vom + fuel / eff,
                   p_max_pu=float(r["capacity_factor"]) if not np.isnan(r["capacity_factor"]) else 1.0,
                   fixed_hours=float(r["duration_h"]) if spec.get("fixed_duration") else np.nan, source=spec.get("source", ""),
                   min_load=float(spec.get("min_load", 0.0)))
        if spec["model"] == "storage":
            dur = float(r["duration_h"])
            share_p = cp / (cp + ce * dur) if (cp + ce * dur) > 0 else 0.0     # FOM split at the reference duration
            fom_p, fom_e = fom * share_p, fom * (1 - share_p) / dur
            if spec.get("efficiency_per_direction"):
                rec["efficiency"] = eff ** 2
            rec["fom_power"], rec["fom_energy"] = fom_p, fom_e
            rec["capital_cost_power"] = 1e3 * (cp * annuity(rate, life) + fom_p)
            rec["capital_cost_energy"] = 1e3 * (ce * annuity(rate, life) + fom_e)
        else:
            rec["fom_power"], rec["fom_energy"] = fom, 0.0
            rec["capital_cost_power"] = 1e3 * (cp * annuity(rate, life) + fom)
            rec["capital_cost_energy"] = 0.0
        out.append(rec)
    return pd.DataFrame(out).set_index("tech")


def hydrothermal_tranche(cfg: dict, lon: float, lat: float) -> pd.DataFrame:
    """Identified hydrothermal systems within radius_km (all statuses) as one capped tranche; plants without a
    cost class (unknown plant type) take the flash-plant cost of their country."""
    g = cfg["geothermal"]
    sites = pd.read_csv(cfg["_dir"] / g["hydrothermal_sites"])
    sites = sites[haversine_km(lon, lat, sites["lon"].values, sites["lat"].values) <= g["radius_km"]]
    sites = sites[sites["capacity_mw"].fillna(0) > 0].copy()
    if sites.empty:
        return pd.DataFrame(columns=TRANCHE_COLUMNS)
    country = pd.read_csv(cfg["_dir"] / g["hydrothermal_country"]).set_index("iso3")
    for col, src in (("capex_usd_per_kw", "capex_flash_usd_per_kw"), ("fom_usd_per_kw_yr", "fom_flash_usd_per_kw_yr"),
                     ("capacity_factor", "capacity_factor_flash"), ("lifetime_years", "lifetime_years")):
        fill = sites["iso3"].map(country[src]) if src in country.columns else np.nan
        sites[col] = sites[col].fillna(fill)
    sites = sites.dropna(subset=["capex_usd_per_kw"])
    w = sites["capacity_mw"] / sites["capacity_mw"].sum()
    return pd.DataFrame([{
        "tranche": "hydrothermal",
        "capex_plant": float((sites["capex_usd_per_kw"] * w).sum()), "capex_well": 0.0,
        "capex_total": float((sites["capex_usd_per_kw"] * w).sum()),
        "fom": float((sites["fom_usd_per_kw_yr"].fillna(0) * w).sum()),
        "p_nom_max": float(sites["capacity_mw"].sum()),
        "capacity_factor": float((sites["capacity_factor"].fillna(0.9) * w).sum()),
        "lifetime": float(sites["lifetime_years"].fillna(30).iloc[0]),
        "depth_km": float("nan"), "t_reservoir_c": float((sites["t_reservoir_c"].fillna(0) * w).sum()),
        "n_cells": int(len(sites)),
    }], columns=TRANCHE_COLUMNS)


def site_tranches(cfg: dict, lon: float, lat: float) -> dict[str, pd.DataFrame]:
    """Tranche tables of the site-specific palette technologies at (lon, lat)."""
    out = {}
    for tech, spec in cfg["palette"].items():
        if spec["model"] != "tranches":
            continue
        out[tech] = egs_tranches(cfg, lon, lat) if spec["source"] == "egs" else hydrothermal_tranche(cfg, lon, lat)
    return out


if __name__ == "__main__":
    cfg = load_config()
    table = load_assumptions(cfg)
    check_coverage(cfg, table)
    pd.set_option("display.width", 250)
    for country in ("US", "IN"):
        print(f"--- components for {country}")
        print(components(cfg, table, country)[["row", "group", "model", "capex_power", "capex_energy", "lifetime", "efficiency",
                                                "marginal_cost", "p_max_pu", "capital_cost_power", "capital_cost_energy", "fixed_hours"]].round(3).to_string())
    for name, lon, lat in (("Idaho", -114.86, 45.11), ("Naivasha", 36.30, -0.90)):
        for tech, t in site_tranches(cfg, lon, lat).items():
            print(f"--- {name} {tech}\n{t.round(1).to_string(index=False) if not t.empty else '  none'}")
