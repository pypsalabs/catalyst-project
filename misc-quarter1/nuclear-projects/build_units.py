"""Unit-level nuclear dataset from the Global Energy Monitor tracker.

Reads the GEM xlsx (all statuses: operating, construction, pre-construction,
announced, mothballed, shelved, retired, cancelled), harmonises the columns,
assigns a reactor family and a status group, and writes one row per reactor
unit plus one row per site.

Inputs   data/gem_nuclear_tracker_2026-08.xlsx
Outputs  build/nuclear_units.csv     one row per unit
         build/nuclear_sites.csv     one row per (site, status group)
Standalone: python build_units.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from xlsx import read_sheet

HERE = Path(__file__).parent
if "snakemake" in globals():
    CFG = snakemake.config
    GEM = Path(snakemake.input.gem)
    OUT_UNITS, OUT_SITES = Path(snakemake.output.units), Path(snakemake.output.sites)
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    GEM = HERE / CFG["gem"]["file"]
    OUT_UNITS, OUT_SITES = HERE / "build/nuclear_units.csv", HERE / "build/nuclear_sites.csv"

COLUMNS = {
    "GEM unit ID": "gem_unit_id",
    "GEM location ID": "gem_location_id",
    "Country/Area": "country",
    "Project Name": "project",
    "Unit Name": "unit",
    "Status": "status",
    "Reactor Type": "reactor_type",
    "Model": "model",
    "Capacity (MW)": "capacity_mw",
    "Reference Net Capacity (MW)": "net_capacity_mw",
    "Thermal Capacity (MWt)": "thermal_mw",
    "Start Year": "start_year",
    "Construction Start Date": "construction_start",
    "First Grid Connection": "grid_connection",
    "Commercial Operation Date": "commercial_operation",
    "Retirement Year": "retirement_year",
    "Planned Retirement": "planned_retirement",
    "Cancellation Year": "cancellation_year",
    "Owner": "owner",
    "Operator": "operator",
    "Data Center PPA": "data_center_ppa",
    "Latitude": "lat",
    "Longitude": "lon",
    "Location Accuracy": "location_accuracy",
    "State/Province": "state",
    "Region": "region",
    "Subregion": "subregion",
    "Date Last Researched": "last_researched",
    "Wiki URL": "wiki_url",
}
NUMERIC = ["capacity_mw", "net_capacity_mw", "thermal_mw", "start_year", "retirement_year",
           "planned_retirement", "cancellation_year", "lat", "lon"]


def family(row):
    m = row["model"].strip()
    for key, fam in CFG["family_by_model"].items():
        if m.startswith(key):
            return fam
    fam = CFG["family_by_type"].get(row["reactor_type"], "unknown")
    if fam == "lwr-large" and row["capacity_mw"] <= CFG["smr_max_mw"]:
        return "lwr-smr"
    return fam


def status_group(status):
    for group, members in CFG["status_groups"].items():
        if status in members:
            return group
    return "other"


def main():
    raw = read_sheet(GEM, CFG["gem"]["sheet"])
    df = raw[list(COLUMNS)].rename(columns=COLUMNS)
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["data_center_ppa"] = df["data_center_ppa"].eq("Y")
    df["model"] = df["model"].replace("", "unknown")
    df["status_group"] = df["status"].map(status_group)
    df["family"] = df.apply(family, axis=1)
    # years for the timeline: construction start from the date, operation from Start Year
    df["construction_start_year"] = pd.to_numeric(df["construction_start"].str[:4], errors="coerce")
    df["build_years"] = np.where(df["status"].eq("operating"),
                                 df["start_year"] - df["construction_start_year"], np.nan)
    df = df.sort_values(["country", "project", "unit"])
    OUT_UNITS.parent.mkdir(exist_ok=True)
    df.to_csv(OUT_UNITS, index=False)

    sites = (df.groupby(["gem_location_id", "country", "project", "status_group"])
             .agg(units=("gem_unit_id", "size"), capacity_mw=("capacity_mw", "sum"),
                  families=("family", lambda s: "/".join(sorted(set(s)))),
                  models=("model", lambda s: "/".join(sorted(set(s)))),
                  statuses=("status", lambda s: "/".join(sorted(set(s)))),
                  first_start_year=("start_year", "min"), last_start_year=("start_year", "max"),
                  construction_start_year=("construction_start_year", "min"),
                  lat=("lat", "first"), lon=("lon", "first"),
                  location_accuracy=("location_accuracy", "first"),
                  data_center_ppa=("data_center_ppa", "any"), owner=("owner", "first"),
                  region=("region", "first"), subregion=("subregion", "first"))
             .reset_index())
    sites.to_csv(OUT_SITES, index=False)

    summary = (df.groupby(["status_group", "family"])["capacity_mw"].agg(["size", "sum"]).unstack(0).fillna(0))
    print(f"{len(df)} units, {sites.gem_location_id.nunique()} sites")
    print((summary["sum"] / 1e3).round(1).to_string())


if __name__ == "__main__":
    main()
