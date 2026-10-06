"""Conventional (hydrothermal) geothermal: where it is, how much, what it costs.

Hydrothermal power needs a naturally permeable, hot reservoir, so unlike EGS it is
spatially confined to volcanic arcs, rifts and a few extensional basins. There is no
open global site-level resource assessment, so this module combines what exists:

  sites      Global Energy Monitor geothermal power tracker (operating and in-
             development units, coordinates, plant type) and, for the US, the
             USGS 2008 identified hydrothermal systems (temperature, MW potential)
  countries  installed capacity (IRENA via Our World in Data), GEM pipeline,
             Holocene-volcano count (NOAA/Smithsonian), published potential
             estimates (Stefansson 2005, Bertani 2003), and a volcano-scaled
             screening estimate calibrated to Stefansson's 209 GWe world total
  cells      distance of every 0.25 deg land cell to the nearest Holocene volcano
             and to the nearest known geothermal plant (hydrothermal prospectivity
             screen; also flags near-field EGS candidates)
  costs      NREL ATB 2024 hydrothermal flash / binary (and the EGS classes),
             IRENA 2024 observed costs, converted to USD2024

Outputs  build/hydrothermal_sites.csv, build/hydrothermal_country.csv,
         build/hydrothermal_cells.csv, build/hydrothermal_costs.csv,
         figures/hydrothermal_sites.{png,pdf}
Standalone: python build_hydrothermal.py
"""

import importlib.util
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
import yaml
from scipy.spatial import cKDTree

HERE = Path(__file__).parent
if "snakemake" in globals():
    CFG = snakemake.config
    I = {k: Path(v) for k, v in snakemake.input.items()}
    O = {k: Path(v) for k, v in snakemake.output.items() if k != "figs"}
    FIGS = [Path(f) for f in snakemake.output.figs]
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    I = {"gem": HERE / "data/gem_geothermal_tracker_2023-01.csv",
         "usgs": HERE / "data/ricks2025/Costing_and_Supply_Curves/NearField/GeothermalSites_ExclusionTable.csv",
         "volcanoes": HERE / "data/noaa_volcano_locations.csv",
         "atb": HERE / "data/atb2024_geothermal.csv",
         "regional": HERE / "data/hydrothermal_regional_potential.csv",
         "installed": HERE / CFG["archetype_data_dir"] / "installed-geothermal-capacity.csv",
         "grid": HERE / "build/temperature_grid.nc",
         "potential": HERE / "build/egs_potential.csv"}
    O = {k: HERE / "build" / f"hydrothermal_{k}.csv" for k in ("sites", "country", "cells", "costs")}
    FIGS = [HERE / "figures" / f"hydrothermal_sites.{f}" for f in CFG["plotting"]["formats"]]

DATA = (HERE / CFG["archetype_data_dir"]).resolve()
EARTH_RADIUS_KM = 6371.0
H = CFG["hydrothermal"]


def load_egs_module():
    spec = importlib.util.spec_from_file_location("geothermal_egs", DATA.parent / "geothermal_egs.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["geothermal_egs"] = mod
    spec.loader.exec_module(mod)
    return mod


def unit_vectors(lat, lon):
    lat, lon = np.radians(lat), np.radians(lon)
    return np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])


def great_circle_km(tree, lat, lon):
    chord, j = tree.query(unit_vectors(lat, lon), workers=-1)
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.clip(chord / 2, 0, 1)), j


def label_iso3(egs, countries, df):
    """ISO3 by point-in-polygon, nearest country polygon centroid as fallback (small islands)."""
    lab = egs.assign_cells(df[["lon", "lat"]].reset_index(drop=True), countries.geometry, countries["iso3"].astype(object))
    lab = lab.values.astype(object)
    miss = pd.isna(lab)
    if miss.any():
        pts = countries.representative_point()
        tree = cKDTree(unit_vectors(pts.y.values, pts.x.values))
        _, j = great_circle_km(tree, df["lat"].values[miss], df["lon"].values[miss])
        lab[miss] = countries["iso3"].values[j]
    return lab


def cost_table():
    cpi = yaml.safe_load((HERE / CFG["tech_costs_config"]).read_text())["cpi"]["USD"]
    infl = cpi[CFG["base_currency_year"]] / cpi[H["atb_currency_year"]]
    atb = pd.read_csv(I["atb"])
    atb["capex_usd_per_kw"] = atb["occ_usd_per_kw"] * infl
    atb["fom_usd_per_kw_yr"] = atb["fom_usd_per_kw_yr"] * infl
    atb["currency_year"] = CFG["base_currency_year"]
    atb["lifetime_years"] = CFG["egs"]["lifetime_years"]
    atb["source"] = f"NREL ATB 2024 v3 ({H['atb_currency_year']} USD OCC x {infl:.4f} CPI)"
    reg = pd.read_csv(I["regional"])
    ir = reg[reg["metric"].str.contains("capex|fom|capacity_factor|lcoe")].copy()
    return atb, ir, infl


def class_costs(atb):
    """CAPEX / FOM / CF per cost class from the ATB Moderate case of the baseline year."""
    sel = atb[(atb["scenario"] == "Moderate") & (atb["year"] == H["atb_year"])].set_index("techdetail")
    return {"flash": sel.loc["HydroFlash"], "binary": sel.loc["HydroBinary"]}


def sites(egs, countries, atb):
    cc = class_costs(atb)
    gem = pd.read_csv(I["gem"], encoding="utf-8-sig")
    gem = gem.rename(columns={"Latitude": "lat", "Longitude": "lon"})
    gem = gem[gem["Status"].isin(H["gem_statuses"])].copy()
    t = gem["Type"].fillna("unknown type").str.lower()
    gem["cost_class"] = np.where(t.str.contains("binary"), "binary", np.where(t.str.contains("flash|dry steam"), "flash", "unknown"))
    g = pd.DataFrame({
        "name": gem["Project Name"] + " / " + gem["Unit Name"].fillna(""), "country_source": gem["Country"],
        "lat": gem["lat"], "lon": gem["lon"], "source": "GEM Global Geothermal Power Tracker (Jan 2023)",
        "status": gem["Status"], "plant_type": gem["Type"], "start_year": gem["Start year"],
        "capacity_mw": pd.to_numeric(gem["Unit Capacity (MW)"], errors="coerce"),
        "t_reservoir_c": np.nan, "cost_class": gem["cost_class"], "location_accuracy": gem["Location accuracy"],
    })
    us = pd.read_csv(I["usgs"]).rename(columns={"Lat_84": "lat", "Lon_84": "lon"})
    u = pd.DataFrame({
        "name": us["Name"], "country_source": "United States", "lat": us["lat"], "lon": us["lon"],
        "source": "USGS 2008 identified hydrothermal systems (Williams et al. 2008), as shipped with Ricks & Jenkins 2025",
        "status": "identified resource", "plant_type": "", "start_year": np.nan,
        "capacity_mw": us["PPotMWe_Mn"], "t_reservoir_c": us["Temp_C_ML"],
        "cost_class": np.where(us["Temp_C_ML"] >= H["flash_min_c"], "flash", "binary"), "location_accuracy": "exact",
    })
    u["capacity_p5_mw"], u["capacity_p95_mw"] = us["PPotMWeP5"].values, us["PPotMWeP95"].values
    df = pd.concat([g, u], ignore_index=True)
    df["iso3"] = label_iso3(egs, countries, df)
    for k in ("capex_usd_per_kw", "fom_usd_per_kw_yr", "capacity_factor"):
        df[k] = [cc[c][k] if c in cc else np.nan for c in df["cost_class"]]
    df["lifetime_years"] = CFG["egs"]["lifetime_years"]
    df["cost_note"] = np.where(df["cost_class"] == "unknown", "plant type unknown: use the IRENA 2024 global average (hydrothermal_costs.csv)", "")
    return df


def countries_table(egs, countries, site_df, volc, atb):
    inst = pd.read_csv(I["installed"])
    inst = inst[inst["Code"].notna() & ~inst["Code"].str.startswith("OWID")]
    inst = inst.sort_values("Year").groupby("Code").last()
    reg = pd.read_csv(I["regional"])
    ident = reg[(reg["scope"] == "country") & (reg["metric"] == "identified_hydrothermal_potential")].set_index("iso3")["value"]
    usgs_national = float(reg.loc[reg["metric"] == "identified_hydrothermal_potential_usgs2008", "value"].iloc[0])
    world = reg[reg["scope"] == "world"].set_index("metric")["value"]
    mw_per_volcano = world["identified_hydrothermal_potential"] / world["accessible_active_volcanoes"]
    usgs = site_df[site_df["source"].str.startswith("USGS")]
    gem = site_df[site_df["source"].str.startswith("GEM")]
    rows = []
    for iso in sorted(set(inst.index) | set(site_df["iso3"]) | set(volc["iso3"]) | set(ident.index)):
        g = gem[gem["iso3"] == iso]
        nv = int((volc["iso3"] == iso).sum())
        row = {
            "iso3": iso, "installed_mw": inst["Geothermal (total)"].get(iso, 0.0),
            "installed_year": inst["Year"].get(iso, np.nan),
            "gem_operating_mw": g.loc[g["status"] == "operating", "capacity_mw"].sum(),
            "gem_pipeline_mw": g.loc[g["status"].isin(["construction", "pre-construction", "announced"]), "capacity_mw"].sum(),
            "n_gem_sites": int(g["name"].str.split(" / ").str[0].nunique()),
            "n_holocene_volcanoes": nv,
            "volcano_scaled_potential_mw": nv * mw_per_volcano,
            "usgs_identified_mw": usgs.loc[usgs["iso3"] == iso, "capacity_mw"].sum() if iso == "USA" else np.nan,
            "published_identified_mw": ident.get(iso, np.nan),
        }
        if iso == "USA":
            best, src = max(usgs_national, row["usgs_identified_mw"]), "USGS 2008 identified systems, national mean"
        elif pd.notna(row["published_identified_mw"]):
            best, src = row["published_identified_mw"], "published assessment (Stefansson 2005, Table 1)"
        else:
            best, src = row["volcano_scaled_potential_mw"], "volcano-scaled (Stefansson 2005 method)"
        best = max(best, row["installed_mw"], row["gem_operating_mw"] + row["gem_pipeline_mw"])
        row["potential_best_mw"] = best
        row["potential_best_source"] = src
        row["potential_upper_mw"] = best * H["hidden_resource_multiplier"]
        row["remaining_potential_mw"] = max(best - max(row["installed_mw"], row["gem_operating_mw"]), 0.0)
        rows.append(row)
    df = pd.DataFrame(rows)
    names = countries.drop_duplicates("iso3").set_index("iso3")["NAME"]
    df.insert(1, "country", df["iso3"].map(names))
    cc = class_costs(atb)
    for cls in ("flash", "binary"):
        df[f"capex_{cls}_usd_per_kw"] = cc[cls]["capex_usd_per_kw"]
        df[f"fom_{cls}_usd_per_kw_yr"] = cc[cls]["fom_usd_per_kw_yr"]
    df["capacity_factor_flash"], df["capacity_factor_binary"] = cc["flash"]["capacity_factor"], cc["binary"]["capacity_factor"]
    df["lifetime_years"] = CFG["egs"]["lifetime_years"]
    df = df[(df["potential_best_mw"] > 0) | (df["installed_mw"] > 0)]
    return df.sort_values("potential_best_mw", ascending=False)


def cells_table(site_df, volc):
    g = xr.open_dataset(I["grid"])
    lat, lon = g["lat"].values, g["lon"].values
    dv, _ = great_circle_km(cKDTree(unit_vectors(volc["lat"].values, volc["lon"].values)), lat, lon)
    known = site_df[site_df["status"].isin(["operating", "construction", "identified resource"])]
    ds, j = great_circle_km(cKDTree(unit_vectors(known["lat"].values, known["lon"].values)), lat, lon)
    pot = pd.read_csv(I["potential"], dtype={"admin1": str, "iso3": str})
    pot = pot.set_index([pot["lon"].round(4), pot["lat"].round(4)])
    df = pd.DataFrame({"lon": lon, "lat": lat, "iso3": g["iso3"].values, "area_km2": g["area_km2"].values,
                       "dist_volcano_km": dv, "dist_geothermal_site_km": ds,
                       "nearest_site": known["name"].values[j]})
    df["hydrothermal_prospective"] = (dv <= H["volcano_radius_km"]) | (ds <= H["site_radius_km"])
    egs = pot.reindex(pd.MultiIndex.from_arrays([df["lon"].round(4), df["lat"].round(4)]))
    df["egs_capex_usd_per_kw"] = egs["capex_usd_per_kw"].values
    df["egs_lcoe_usd_per_mwh"] = egs["lcoe_usd_per_mwh"].values
    df["egs_depth_km"] = egs["depth_km"].values
    df["nearfield_egs_candidate"] = df["hydrothermal_prospective"] & np.isfinite(df["egs_capex_usd_per_kw"])
    return df


def plot(site_df, volc, countries):
    INK, MUTED = "#0b0b0b", "#52514e"
    fig, ax = plt.subplots(figsize=(15, 7.2))
    fig.patch.set_facecolor("#fcfcfb")
    countries.plot(ax=ax, color="#efeeea", edgecolor="white", linewidth=0.3)
    ax.scatter(volc["lon"], volc["lat"], s=3, color="#c3c2b7", label=f"Holocene volcanoes (NOAA/Smithsonian, n = {len(volc):,})", zorder=2, linewidths=0)
    op = site_df[site_df["status"] == "operating"]
    dev = site_df[site_df["status"].isin(["construction", "pre-construction", "announced"])]
    us = site_df[site_df["status"] == "identified resource"]
    sz = lambda mw: np.clip(mw.fillna(5) / 4, 6, 200)
    ax.scatter(us["lon"], us["lat"], s=sz(us["capacity_mw"]), facecolors="none", edgecolors="#1baf7a", linewidths=0.8,
               label=f"USGS 2008 identified systems, US ({us['capacity_mw'].sum() / 1e3:.1f} GW P50)", zorder=3)
    ax.scatter(dev["lon"], dev["lat"], s=sz(dev["capacity_mw"]), color="#eb6834", alpha=0.75, linewidths=0,
               label=f"GEM: in development ({dev['capacity_mw'].sum() / 1e3:.1f} GW)", zorder=4)
    ax.scatter(op["lon"], op["lat"], s=sz(op["capacity_mw"]), color="#2a78d6", alpha=0.75, linewidths=0,
               label=f"GEM: operating ({op['capacity_mw'].sum() / 1e3:.1f} GW)", zorder=5)
    ax.set_xlim(-180, 180); ax.set_ylim(-58, 84); ax.set_aspect("equal"); ax.set_axis_off()
    ax.legend(loc="lower left", fontsize=9, frameon=False, markerscale=1.0)
    ax.set_title("Conventional (hydrothermal) geothermal is where the volcanoes are: known plants, identified US systems, Holocene volcanoes "
                 "(marker area ~ MW)", fontsize=11, color=INK, loc="left")
    fig.tight_layout()
    for f in FIGS:
        f.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(f, dpi=CFG["plotting"]["dpi"], facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    egs = load_egs_module()
    countries = gpd.read_file(DATA / "ne_50m_admin_0_countries" / "ne_50m_admin_0_countries.shp")
    countries["iso3"] = egs.natural_earth_iso3(countries)
    countries = countries.dropna(subset=["iso3"]).reset_index(drop=True)
    atb, irena, infl = cost_table()

    volc = pd.read_csv(I["volcanoes"]).rename(columns={"latitude": "lat", "longitude": "lon"})
    # Stefansson counts accessible volcanoes: drop submarine ones and the Antarctic
    volc = volc[volc["lat"].notna() & (volc["lat"] > -60) & ~volc["morphology"].fillna("").str.contains("Submarine", case=False)].copy()
    volc["iso3"] = label_iso3(egs, countries, volc)

    site_df = sites(egs, countries, atb)
    site_df.to_csv(O["sites"], index=False, float_format="%.5g")
    ctry = countries_table(egs, countries, site_df, volc, atb)
    ctry.to_csv(O["country"], index=False, float_format="%.5g")
    cells = cells_table(site_df, volc)
    cells.to_csv(O["cells"], index=False, float_format="%.5g")

    costs = pd.concat([
        atb.assign(kind="ATB class"),
        pd.DataFrame({"techdetail": "IRENA observed", "resource_class": "all hydrothermal", "scenario": "observed",
                      "year": 2024, "metric": irena["metric"], "value": irena["value"], "unit": irena["unit"],
                      "source": irena["source"], "note": irena["note"], "kind": "IRENA"}),
    ], ignore_index=True)
    costs.to_csv(O["costs"], index=False, float_format="%.5g")
    plot(site_df, volc, countries)

    top = ctry.head(15)[["country", "installed_mw", "gem_pipeline_mw", "n_holocene_volcanoes", "potential_best_mw", "potential_best_source"]]
    pd.set_option("display.width", 200)
    print(top.round(0).to_string(index=False))
    print(f"world: installed {ctry['installed_mw'].sum() / 1e3:.1f} GW, best-estimate potential {ctry['potential_best_mw'].sum() / 1e3:.0f} GW, "
          f"prospective land {cells.loc[cells['hydrothermal_prospective'], 'area_km2'].sum() / 1e6:.2f} M km2 "
          f"({cells['hydrothermal_prospective'].mean():.1%} of cells)")


if __name__ == "__main__" or "snakemake" in globals():
    main()
