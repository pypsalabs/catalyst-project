"""Technology parameters for the learning loop (misc-quarter1/pareto).

Turns `config.yaml` plus the technology-costs baseline into one row per *component*
(a generator plant, a storage power or energy part, a link, a store) with the 2025 capex,
FOM fraction, lifetime, efficiency, marginal cost, learning rate and global reference
capacity, and provides the learning-curve arithmetic shared by run_loop.py and plot_loop.py.
Site-specific technologies (EGS, hydrothermal) carry a cost *factor* here; their per-site
supply-curve tranches come from misc-quarter1/geothermal via `egs_tranches` /
`hydrothermal_tranche`.

Units: capex in USD2024 per kW (power) or per kWh (energy); capacities in MW / MWh inside
the model; reference capacities are given in GW / GWh in the config and converted here.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
log = logging.getLogger("techs")

POWER_TYPES = {"generator", "storage_power", "link"}
EARTH_RADIUS_KM = 6371.0


def load_config(path: Path | None = None) -> dict:
    path = Path(path) if path else HERE / "config.yaml"
    cfg = yaml.safe_load(path.read_text())
    cfg["_dir"] = path.parent
    return cfg


def annuity(rate: float, lifetime: float) -> float:
    """Capital recovery factor (per year)."""
    if rate == 0:
        return 1.0 / lifetime
    return rate / (1.0 - (1.0 + rate) ** (-lifetime))


def _resolve(spec: dict, table: pd.DataFrame, default_row: str, kind: str, capex: float | None = None,
             fill_fom: float = 0.0) -> float:
    """Resolve a capex / fom / lifetime spec against the cost table.

    capex: {value} or {row, column}          -> USD/kW or USD/kWh
    fom:   {frac} or {value} or {row, column} -> fraction of capex per year
    lifetime: {value} or {row}                -> years
    """
    if kind == "capex":
        if "value" in spec:
            return float(spec["value"])
        return float(table.loc[spec.get("row", default_row), spec["column"]])
    if kind == "lifetime":
        if "value" in spec:
            return float(spec["value"])
        return float(table.loc[spec.get("row", default_row), "lifetime"])
    if kind == "fom":
        if "frac" in spec:
            return float(spec["frac"])
        if "value" in spec:
            absolute = float(spec["value"])
        else:
            absolute = table.loc[spec.get("row", default_row), spec["column"]]
            if pd.isna(absolute):
                absolute = fill_fom
        return float(absolute) / capex if capex else 0.0
    raise ValueError(kind)


def load_components(cfg: dict) -> pd.DataFrame:
    """One row per component, indexed by (tech, component)."""
    base = cfg["_dir"]
    table = pd.read_csv(base / cfg["costs_table"]).set_index("technology")
    colours = {t["key"]: t["colour"] for t in yaml.safe_load((base / cfg["costs_config"]).read_text())["technologies"]}
    colours.update(cfg.get("plotting", {}).get("colours", {}))
    fill_fom = cfg.get("fill_missing_fom", 0.0)

    rows = []
    for tech, tspec in cfg["technologies"].items():
        storage = tspec.get("storage", {})
        eff_rt = None
        if storage:
            e = storage["efficiency"]
            eff_rt = float(e["value"]) if "value" in e else float(table.loc[e.get("row", tech), "efficiency"])
        for comp, c in tspec["components"].items():
            ctype = c["type"]
            capex = _resolve(c["capex"], table, tech, "capex")
            row = {
                "tech": tech,
                "component": comp,
                "tech_label": tspec["label"],
                "colour": colours.get(tech, "#999999"),
                "site_specific": bool(tspec.get("site_specific", False)),
                "type": ctype,
                "unit": "MW" if ctype in POWER_TYPES else "MWh",
                "cf": c.get("cf"),
                "availability": float(c.get("availability", 1.0)),
                "efficiency": float(c.get("efficiency", 1.0)),
                "round_trip_efficiency": eff_rt,
                "fixed_hours": storage.get("fixed_hours"),
                "bus0": c.get("bus0"),
                "bus1": c.get("bus1"),
                "bus": c.get("bus"),
                "cost_basis": c.get("cost_basis", "input"),
                "capex0": capex,
                "fom_frac": _resolve(c["fom"], table, tech, "fom", capex=capex, fill_fom=fill_fom),
                "lifetime": _resolve(c["lifetime"], table, tech, "lifetime"),
                "learning_rate": float(c["learning"]["rate"]),
                "learning_source": c["learning"]["source"],
                "cref_global": float(c["reference"]["capacity"]) * 1e3,      # GW -> MW, GWh -> MWh
                "floor": float(c["reference"].get("floor", 0.0)) * 1e3,
                "reference_source": c["reference"]["source"],
            }
            # marginal cost of generators: VOM + fuel / efficiency (no CO2 price: clean palette)
            mc = 0.0
            if ctype == "generator" and not row["site_specific"]:
                trow = table.loc[c.get("capex", {}).get("row", tech)]
                vom = trow.get("vom_mwh")
                mc += 0.0 if pd.isna(vom) else float(vom)
                fuel = trow.get("fuel_mwh_th")
                if not pd.isna(fuel):
                    mc += float(fuel) / float(trow["efficiency"])
            row["marginal_cost"] = mc
            rows.append(row)
    comps = pd.DataFrame(rows).set_index(["tech", "component"])
    return comps


def fixed_cost_per_year(capex: float | np.ndarray, fom_frac, lifetime, rate: float):
    """USD per MW (or MWh) per year from a capex in USD per kW (or kWh)."""
    crf = np.vectorize(annuity)(rate, lifetime) if np.ndim(lifetime) else annuity(rate, lifetime)
    return capex * 1e3 * (crf + fom_frac)


def reference_base(comps: pd.DataFrame) -> pd.Series:
    """Global reference cumulative capacity per component, floored by one indivisible unit."""
    return np.maximum(comps["cref_global"], comps["floor"]).clip(lower=1e-3)


def world_shares(cfg: dict) -> list:
    """Share of world demand the sub-system represents in each round."""
    lb = cfg["learning_base"]
    shares = lb["shares_of_world"]
    if not isinstance(shares, (list, tuple)):
        shares = [shares] * cfg["steps"]
    if len(shares) < cfg["steps"]:
        shares = list(shares) + [shares[-1]] * (cfg["steps"] - len(shares))
    return [float(x) for x in shares]


def world_scale(cfg: dict, load_twh: float, step: int) -> float:
    """Factor by which the build of round `step` counts toward the global curve.

    counting = increment: the growth of the sub-system since the previous round (share_k - share_{k-1});
    counting = full: the whole fleet of the round at share_k.
    """
    lb = cfg["learning_base"]
    shares = world_shares(cfg)
    share = shares[step]
    if lb.get("counting", "increment") == "increment" and step > 0:
        share = shares[step] - shares[step - 1]
    return lb["world_demand_twh"] * share / load_twh


def learned_capex(capex0, cumulative, cref, learning_rate):
    """Wright's law: capex0 x (cumulative / cref) ** log2(1 - rate)."""
    b = np.log2(1.0 - np.asarray(learning_rate, dtype=float))
    ratio = np.maximum(np.asarray(cumulative, dtype=float) / np.asarray(cref, dtype=float), 1.0)
    return np.asarray(capex0, dtype=float) * ratio**b


# ---------------------------------------------------------------- site-specific geothermal
def haversine_km(lon: float, lat: float, lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    lon0, lat0 = np.radians(lon), np.radians(lat)
    lons, lats = np.radians(lons), np.radians(lats)
    a = np.sin((lats - lat0) / 2) ** 2 + np.cos(lat0) * np.cos(lats) * np.sin((lons - lon0) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def site_coordinates(cfg: dict, dataset: str, series: str) -> tuple[float, float]:
    """(lon, lat) of a series: from a csv with site/x/y columns, or a fixed pair in the config."""
    spec = cfg["datasets"][dataset]["coordinates"]
    if isinstance(spec, dict):
        return float(spec["lon"]), float(spec["lat"])
    table = pd.read_csv(cfg["_dir"] / spec).set_index("site")
    return float(table.at[series, "x"]), float(table.at[series, "y"])


TRANCHE_COLUMNS = ["tranche", "capex_plant", "capex_well", "capex_total", "fom", "p_nom_max", "capacity_factor",
                   "lifetime", "depth_km", "t_reservoir_c", "n_cells"]


def egs_tranches(cfg: dict, lon: float, lat: float) -> pd.DataFrame:
    """EGS supply curve at a site: cells within radius_km binned by CAPEX (USD2024/kW).

    Per tranche: capacity-weighted plant and well CAPEX, FOM (USD/kW/a), summed capacity (MW,
    already 20 % land-derated), capacity factor, lifetime, weighted depth and temperature.
    """
    g = cfg["geothermal"]
    cells = pd.read_csv(cfg["_dir"] / g["egs_potential"],
                        usecols=["lon", "lat", "plant_capex_usd_per_kw", "well_capex_usd_per_kw", "capex_usd_per_kw",
                                 "fom_usd_per_kw_yr", "capacity_mw", "capacity_factor", "lifetime_years", "depth_km", "t_reservoir_c"])
    cells = cells[haversine_km(lon, lat, cells["lon"].values, cells["lat"].values) <= g["radius_km"]]
    edges = list(g["capex_bins_usd_kw"])
    cells = cells[cells["capex_usd_per_kw"] < edges[-1]]
    rows = []
    for k, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
        sub = cells[(cells["capex_usd_per_kw"] >= lo) & (cells["capex_usd_per_kw"] < hi)]
        if sub.empty or sub["capacity_mw"].sum() <= 0:
            continue
        w = sub["capacity_mw"] / sub["capacity_mw"].sum()
        rows.append({
            "tranche": f"t{k} {lo:,.0f}–{hi:,.0f} $/kW",
            "capex_plant": float((sub["plant_capex_usd_per_kw"] * w).sum()),
            "capex_well": float((sub["well_capex_usd_per_kw"] * w).sum()),
            "capex_total": float((sub["capex_usd_per_kw"] * w).sum()),
            "fom": float((sub["fom_usd_per_kw_yr"] * w).sum()),
            "p_nom_max": float(sub["capacity_mw"].sum()),
            "capacity_factor": float((sub["capacity_factor"] * w).sum()),
            "lifetime": float(sub["lifetime_years"].iloc[0]),
            "depth_km": float((sub["depth_km"] * w).sum()),
            "t_reservoir_c": float((sub["t_reservoir_c"] * w).sum()),
            "n_cells": int(len(sub)),
        })
    return pd.DataFrame(rows, columns=TRANCHE_COLUMNS)


def hydrothermal_tranche(cfg: dict, lon: float, lat: float) -> pd.DataFrame:
    """Identified hydrothermal systems within radius_km as one capped tranche (no well/plant split)."""
    g = cfg["geothermal"]
    sites = pd.read_csv(cfg["_dir"] / g["hydrothermal_sites"])
    sites = sites[haversine_km(lon, lat, sites["lon"].values, sites["lat"].values) <= g["radius_km"]]
    sites = sites[sites["capacity_mw"].fillna(0) > 0]
    if sites.empty:
        return pd.DataFrame(columns=TRANCHE_COLUMNS)
    w = sites["capacity_mw"] / sites["capacity_mw"].sum()
    return pd.DataFrame([{
        "tranche": "hydrothermal",
        "capex_plant": float((sites["capex_usd_per_kw"] * w).sum()),
        "capex_well": 0.0,
        "capex_total": float((sites["capex_usd_per_kw"] * w).sum()),
        "fom": float((sites["fom_usd_per_kw_yr"] * w).sum()),
        "p_nom_max": float(sites["capacity_mw"].sum()),
        "capacity_factor": float((sites["capacity_factor"].fillna(0.9) * w).sum()),
        "lifetime": float(sites["lifetime_years"].fillna(30).iloc[0]),
        "depth_km": float("nan"),
        "t_reservoir_c": float((sites["t_reservoir_c"].fillna(0) * w).sum()),
        "n_cells": int(len(sites)),
    }], columns=TRANCHE_COLUMNS)


def site_tranches(cfg: dict, dataset: str, series: str) -> dict[str, pd.DataFrame]:
    """Tranche tables of every site-specific technology for one series (empty unless the series is
    in geothermal.sites)."""
    allowed = cfg["geothermal"].get("sites")
    if allowed is not None and series not in allowed:
        return {t: pd.DataFrame(columns=TRANCHE_COLUMNS) for t in ("egs", "hydrothermal") if t in cfg["technologies"]}
    lon, lat = site_coordinates(cfg, dataset, series)
    out = {}
    if "egs" in cfg["technologies"]:
        out["egs"] = egs_tranches(cfg, lon, lat)
    if "hydrothermal" in cfg["technologies"]:
        out["hydrothermal"] = hydrothermal_tranche(cfg, lon, lat)
    return out


def check_against_fits(cfg: dict, comps: pd.DataFrame) -> None:
    """Warn where a configured rate labelled as a fit differs from learning_rates.csv."""
    path = cfg["_dir"] / cfg["learning_rates"]
    if not path.exists():
        return
    fits = pd.read_csv(path)
    fits = fits[fits["lr"].notna()].set_index(["technology", "component"])["lr"]
    for (tech, comp), row in comps.iterrows():
        if "level fit" not in row["learning_source"]:
            continue
        key_tech = {"h2": "h2-sofc"}.get(tech, tech)
        key_comp = {"electrolyser": "power", "sofc": "plant"}.get(comp, comp)
        if tech == "h2" and comp == "sofc":
            key_tech = "sofc"
        fit = fits.get((key_tech, key_comp))
        if fit is not None and abs(fit - row["learning_rate"]) > 0.005:
            log.warning("%s/%s: configured rate %.3f vs fitted %.3f in learning_rates.csv", tech, comp, row["learning_rate"], fit)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config()
    comps = load_components(cfg)
    check_against_fits(cfg, comps)
    pd.set_option("display.width", 250)
    cols = ["type", "unit", "site_specific", "capex0", "fom_frac", "lifetime", "efficiency", "marginal_cost", "learning_rate", "cref_global", "floor"]
    print(comps[cols].round(4).to_string())
    print("\nreference base (MW / MWh):")
    print(reference_base(comps).round(1).to_string())
    dataset = sys.argv[1] if len(sys.argv) > 1 else "sites"
    names = pd.read_csv(cfg["_dir"] / cfg["datasets"][dataset]["coordinates"])["site"].tolist() if dataset == "sites" else ["2019"]
    for name in names:
        print(f"\n{name}: world scale factors at 40 TWh per round = " + ", ".join(f"{world_scale(cfg, 40.0, k):.1f}" for k in range(cfg["steps"])))
        for tech, tr in site_tranches(cfg, dataset, name).items():
            print(tech)
            print(tr.round(1).to_string(index=False) if not tr.empty else "  none within radius")
