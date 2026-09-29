# SPDX-License-Identifier: CC0-1.0
"""
Rest of world: pick the countries that, together with the archetype regions, cover more than 99.5 % of global
electricity demand, assign each to a continental group run (one pypsa-earth run per prebuilt cutout) and write
the group configs config.<G>.yaml. Every country of a group run is one node (GADM level-0 clustering) and islanded
(ATKc); see README "Rest of world".

Demand ranking: Ember yearly_full_release_long_format.csv (data/validation/, fetched by validation.smk), electricity
demand of each "Country or economy", latest year <= 2024 (2025 covers only 91 countries). The archetype countries
(countries: of every config.<R>.yaml without catalyst.single_node) count as covered; the others are added by
descending demand until the covered share exceeds TARGET. A country is skipped (and the next one taken) when it
cannot be built out of the box:
  - no load: neither pypsa-earth's default GEGIS load (SSP2-2.6 2030, era5_2013) nor DemandCast 2013 has it. GEGIS is
    empty for HK, PR, LA, BT, PS, ...; the group configs set load_options.fallback_source: demcast (fork patch), so those
    take the DemandCast 2013 series (column load_source)
  - no Geofabrik extract that earth-osm resolves (after pypsa-earth's iso_to_geofk_dict)
  - no GADM 4.1 file (HK, MO: they are provinces of gadm41_CHN, i.e. inside the CN archetype run, whose GEGIS load
    for them is zero); checked with HEAD requests to geodata.ucdavis.edu
  - no ISO2 code / no group (Kosovo)

Outputs (tracked):
  data/row_countries.csv   every Ember country: status archetype | modelled | skipped | below_cutoff, group, reason,
                           demand, cumulative covered share, load source (gegis | demcast)
  config.<G>.yaml          one per group (overwritten; edit this script, not the configs)

Standalone, from models/pypsa-earth (needs earth_osm, pycountry from the fork env):
    pixi run python ../../config-pypsa-earth/scripts/select_countries.py
    pixi run python ../../config-pypsa-earth/scripts/select_countries.py --geofabrik <G>   # used by prestage.sh: the
        Geofabrik extracts (e.g. asia/gcc-states) of the countries of config.<G>.yaml, space separated, deduplicated
"""
import glob
import os
import sys
import urllib.error
import urllib.request

import pandas as pd
import pycountry
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.dirname(HERE)
PE = os.path.join(os.path.dirname(CFG), "models", "pypsa-earth")
EMBER = os.path.join(CFG, "data", "validation", "yearly_full_release_long_format.csv")
OUT = os.path.join(CFG, "data", "row_countries.csv")
TARGET = 0.995
MAX_YEAR = 2024
EARTH_CUTOUTS = os.path.expanduser("~/Desktop/earth/pypsa-earth/cutouts")

# group -> cutout (file in models/pypsa-earth/cutouts/), its box [x0, y0, x1, y1] (= clip_bbox), where it comes from
GROUPS = {
    "EUR": dict(cutout="europe-2013-sarah3-era5", box=[-12.0, 33.0, 40.8, 72.0], src="PyPSA-Eur cutout v1.0, already hardlinked for NWE",
                title="rest of Europe"),
    "RU": dict(cutout="cutout-2013-era5-northeurasia", box=[19.2, 39.0, 178.8, 78.0], src="pypsa-earth prebuilt", title="Russia",
               mode="voronoi"),
    "CA": dict(cutout="cutout-2013-era5-northamerica", box=[-171.9, 1.5, -47.1, 73.8], clip=[-141.5, 41.5, -52.0, 73.8],
               src="pypsa-earth prebuilt", title="Canada", mode="voronoi"),
    "MEA": dict(cutout="cutout-2013-era5-westasia", box=[24.9, 8.4, 63.9, 44.1], src="pypsa-earth prebuilt",
                title="Middle East, Turkey and the Caucasus"),
    "AFR": dict(cutout="cutout-2013-era5-africa", box=[-19.5, -37.5, 67.5, 39.3], src="pypsa-earth prebuilt", title="Africa"),
    "ASI": dict(cutout="cutout-2013-era5-asia", box=[24.9, -14.4, 158.1, 55.8], src="pypsa-earth prebuilt",
                title="East, South-East, South and Central Asia"),
    "OCE": dict(cutout="cutout-2013-era5-oceania", box=[80.1, -49.8, 179.7, 19.8], src="pypsa-earth prebuilt", title="Oceania"),
    "NAM": dict(cutout="cutout-2013-era5-northamerica", box=[-171.9, 1.5, -47.1, 73.8], src="pypsa-earth prebuilt",
                title="Mexico, Central America and the Caribbean"),
    "SAM": dict(cutout="cutout-2013-era5-southamerica", box=[-109.8, -60.3, -25.5, 17.1], src="pypsa-earth prebuilt",
                title="rest of South America"),
    "IS": dict(cutout="cutout-2013-era5-iceland", box=[-25.5, 62.7, -12.5, 67.2], src="CDS build (no prebuilt cutout covers Iceland)",
               title="Iceland"),
}
MEA = {"TR", "SA", "IR", "IQ", "AE", "KW", "QA", "OM", "BH", "IL", "PS", "JO", "LB", "SY", "YE", "GE", "AM", "AZ"}
EMBER_CONTINENT = {"Africa": "AFR", "Asia": "ASI", "Europe": "EUR", "North America": "NAM", "Oceania": "OCE", "South America": "SAM"}


def group_of(iso2, continent):
    if iso2 in ("RU", "CA", "IS"):
        return iso2
    if iso2 in MEA:
        return "MEA"
    return EMBER_CONTINENT.get(continent)


def iso2_of(iso3):
    if iso3 == "XKX":
        return "XK"
    c = pycountry.countries.get(alpha_3=iso3)
    return c.alpha_2 if c else None


def archetype_countries():
    out = {}
    for f in sorted(glob.glob(os.path.join(CFG, "config.*.yaml"))):
        name = os.path.basename(f)[len("config."):-len(".yaml")]
        if "-smoke" in name:
            continue
        with open(f) as fh:
            cfg = yaml.safe_load(fh)
        if not (cfg.get("catalyst") or {}).get("single_node"):
            out.update({c: name for c in cfg["countries"]})
    return out


def ember_demand():
    e = pd.read_csv(EMBER, usecols=["Area", "ISO 3 code", "Year", "Area type", "Continent", "Category", "Variable", "Unit", "Value"])
    d = e[(e["Area type"] == "Country or economy") & (e.Category == "Electricity demand") & (e.Variable == "Demand")
          & (e.Unit == "TWh") & (e.Year <= MAX_YEAR)].dropna(subset=["Value"])
    d = d.sort_values("Year").groupby("ISO 3 code").last().reset_index()
    d = d.rename(columns={"ISO 3 code": "iso3", "Area": "name", "Continent": "continent", "Year": "year", "Value": "demand_twh"})
    d["iso2"] = d.iso3.map(iso2_of)
    return d[["iso2", "iso3", "name", "continent", "year", "demand_twh"]].sort_values("demand_twh", ascending=False)


def gegis_demand():
    """{ISO2: TWh} of pypsa-earth's default load (SSP2-2.6, 2030, weather 2013)."""
    tot = {}
    for f in glob.glob(os.path.join(PE, "data", "ssp2-2.6", "2030", "era5_2013", "*.csv")):
        g = pd.read_csv(f, sep=";", usecols=["region_code", "Electricity demand"], keep_default_na=False, dtype=str)
        v = pd.to_numeric(g["Electricity demand"], errors="coerce")
        tot.update((v.groupby(g.region_code).sum(min_count=1) / 1e6).dropna().to_dict())
    return tot


def demcast_demand():
    """{ISO2: TWh} of DemandCast, weather year 2013 (the fallback_source of the group configs)."""
    d = pd.read_parquet(os.path.join(PE, "data", "demand", "forecasts_on_historical_period.parquet"))
    d = d[pd.to_datetime(d["Time (UTC)"]).dt.year == 2013]
    tot = d.groupby("Entity code")["Forecast load (MW)"].sum() / 1e6
    return {iso2_of(k): v for k, v in tot.items() if iso2_of(k)}


def geofabrik_resolver():
    sys.path.insert(0, os.path.join(PE, "scripts"))
    from earth_osm import gfk_data
    iso_to_geofk = yaml.safe_load(open(os.path.join(PE, "configs", "regions_definition_config.yaml")))["iso_to_geofk_dict"]

    def resolve(iso2):
        """Geofabrik path (e.g. asia/gcc-states) the way download_osm_data / earth-osm resolve it, or None."""
        code = iso_to_geofk.get(iso2, iso2)
        rid = gfk_data.get_id_by_code(code) or code   # earth-osm: not a short code -> probably an id
        try:
            url = gfk_data.get_region_dict(rid)["urls"]["pbf"]
        except (IndexError, KeyError):
            return None
        return url.split("download.geofabrik.de/", 1)[1][: -len("-latest.osm.pbf")]
    return resolve


def gadm_checker():
    sys.path.insert(0, os.path.join(PE, "scripts"))
    from build_shapes import get_GADM_filename

    def ok(iso2):
        if os.path.exists(os.path.join(PE, "data", "gadm", get_GADM_filename(iso2))):
            return True
        url = f"https://geodata.ucdavis.edu/gadm/gadm4.1/gpkg/{get_GADM_filename(iso2)}.gpkg"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=60) as r:
                return r.status == 200
        except urllib.error.HTTPError:
            return False
    return ok


def select():
    d = ember_demand()
    arch = archetype_countries()
    gegis = gegis_demand()
    demcast = demcast_demand()
    resolve = geofabrik_resolver()
    gadm_ok = gadm_checker()
    world = d.demand_twh.sum()
    covered = d.loc[d.iso2.isin(arch), "demand_twh"].sum()
    rows = []
    for r in d.itertuples(index=False):
        row = r._asdict()
        if r.iso2 in arch:
            row.update(status="archetype", group=arch[r.iso2], reason="", load_source="gegis")
            rows.append(row)
    for r in d.itertuples(index=False):
        if r.iso2 in arch:
            continue
        row = r._asdict()
        grp = group_of(r.iso2, r.continent) if r.iso2 else None
        gf = resolve(r.iso2) if r.iso2 else None
        load = ("gegis" if gegis.get(r.iso2, 0) > 0 else "demcast" if demcast.get(r.iso2, 0) > 0 else "") if r.iso2 else ""
        if covered / world > TARGET:
            row.update(status="below_cutoff", group=grp or "", reason="")
            rows.append(row)
            continue
        reason = ("no ISO2 code" if not r.iso2 else "no group" if not grp
                  else "no load in GEGIS nor DemandCast" if not load
                  else "no Geofabrik extract resolvable by earth-osm" if gf is None
                  else "no GADM 4.1 file (part of another country's GADM)" if not gadm_ok(r.iso2) else "")
        if reason:
            row.update(status="skipped", group=grp or "", reason=reason)
        else:
            covered += r.demand_twh
            row.update(status="modelled", group=grp, reason="", geofabrik=gf, load_source=load)
        rows.append(row)
    df = pd.DataFrame(rows)
    inc = df.status.isin(["archetype", "modelled"])
    df.loc[inc, "cum_share"] = (df.loc[inc, "demand_twh"].cumsum() / world).round(5)
    df["demand_twh"] = df.demand_twh.round(2)
    cols = ["iso2", "iso3", "name", "continent", "year", "demand_twh", "status", "group", "cum_share", "load_source", "geofabrik",
            "reason"]
    return df.reindex(columns=cols), world


HEADER = """\
# SPDX-License-Identifier: CC0-1.0
#
# GENERATED by config-pypsa-earth/scripts/select_countries.py - edit the script, not this file.
# Catalyst / rest of world, group {G} ({title}): {n} {countries_word}, each ONE NODE and islanded, power-only, weather year 2013.
# {countries_long}
# Ember demand {twh:.0f} TWh ({share:.2f} % of the world). Out of the box like the archetype runs, except:
{mode_notes}
#   - catalyst.extra_opts ATKc (merge_config.py adds it to the overlay opts): prepare_network removes every cross-border
#     line / link, so no country trades with its neighbours.
#   - load_options.fallback_source demcast (fork patch): countries without GEGIS load take DemandCast 2013{fallback}
#   - renewable.<tech>.excluder_resolution 1000 m (fork patch; default 100 m): atlite rasterises each region's exclusion
#     mask over its bounding box, which at 100 m does not fit memory for country-sized regions (Argentina: OOM at 12 GB)
# Cutout: {cutout} ({src}); clip_bbox {clip}, so overseas islands outside it are ignored.
"""
MODE_NOTES = {
    "gadm": """\
#   - clustering.alternative_clustering + gadm_layer_id 0 (native pypsa-earth): build_bus_regions keeps one onshore region per
#     GADM country shape, so renewable profiles, plants and load are per country, and cluster_network maps every AC bus
#     of a country onto one bus (busmap gadm_0_AC). Islands and isolated OSM fragments are lumped into that node.
#   - threshold_voltage 100 kV (archetypes: 200 kV): the grid is collapsed anyway, and several small systems have no
#     >= 200 kV substation in OSM; every country needs at least one bus.""",
    "voronoi": """\
#   - one country too large for a whole-country region (atlite reads the 100 m land-cover raster over the region's bounding
#     box at native resolution: 3-6e9 pixels), so the archetype recipe: Voronoi regions per base bus at 200 kV, every
#     isolated sub-network fetched into the backbone (s_threshold_fetch_isolated 1.0: below 100 % of the national load),
#     then clusters 1 (like SG).""",
}


def write_config(g, sel, world):
    spec = GROUPS[g]
    mode = spec.get("mode", "gadm")
    ccs = sorted(sel.iso2)
    box = spec["box"]
    clip = spec.get("clip", box)
    build = spec["src"].startswith("CDS")
    long = ", ".join(f"{r.iso2} {r.name}" for r in sel.sort_values("demand_twh", ascending=False).itertuples())
    wrapped, line = [], ""
    for part in long.split(", "):
        if len(line) + len(part) > 110:
            wrapped.append(line.rstrip(", "))
            line = ""
        line += part + ", "
    wrapped.append(line.rstrip(", "))
    demcast = sorted(sel.loc[sel.load_source == "demcast", "iso2"])
    head = HEADER.format(G=g, title=spec["title"], n=len(ccs), countries_word="country" if len(ccs) == 1 else "countries",
                         countries_long="\n# ".join(wrapped), twh=sel.demand_twh.sum(), share=100 * sel.demand_twh.sum() / world,
                         mode_notes=MODE_NOTES[mode], fallback=f" ({', '.join(demcast)})" if demcast else " (none in this group)",
                         cutout=spec["cutout"], src=spec["src"], clip=clip)
    if mode == "gadm":
        clusters = f"[{len(ccs)}]          # one per country (the GADM busmap ignores the number; it only names the files)"
        threshold = 100000
        shape_extra = "  gadm_layer_id: 0\n"
        clustering = """clustering:                          # (the archetype configs use the deprecated alias cluster_options; one block here)
  alternative_clustering: true
  simplify_network:
    p_threshold_drop_isolated: false   # default 20 MW would drop unpopulated buses together with their plants
"""
    else:
        clusters = "[1]"
        threshold = 200000
        shape_extra = ""
        clustering = """clustering:
  simplify_network:
    p_threshold_drop_isolated: false   # keep isolated buses and their plants ...
    s_threshold_fetch_isolated: 1.0    # ... and fetch every isolated sub-network into the backbone: one sub-network, one cluster
"""
    renew = "".join(f"  {t}:\n    excluder_resolution: 1000\n" for t in ("onwind", "offwind-ac", "offwind-dc", "solar"))
    cfg = f"""
countries: [{", ".join(f'"{c}"' for c in ccs)}]   # quoted: YAML 1.1 reads NO (Norway) as false

run:
  name: {g}
  shared_cutouts: true

scenario:
  simpl: [""]
  clusters: {clusters}
  ll: [copt]
  opts: [Co2L]

snapshots:
  start: "2013-01-01"
  end: "2014-01-01"
  inclusive: left

enable:
  retrieve_databundle: true
  retrieve_cost_data: true
  retrieve_cutout: false
  build_cutout: {"true" if build else "false"}{"      # needs ~/.cdsapirc; run.sh flips it off once the file exists" if build else "     # cutouts/" + spec["cutout"] + ".nc: hardlink made by prestage.sh"}
  download_osm_data: true
  build_natura_raster: false
  progress_bar: false

download_osm_data_nprocesses: 1

osm:
  clean_osm_data:
    threshold_voltage: {threshold}

atlite:
  nprocesses: 1
  default: {spec["cutout"]}
  cutouts:
    {spec["cutout"]}:
      module: era5
      dx: 0.3
      dy: 0.3
      x: [{box[0]}, {box[2]}]
      y: [{box[1]}, {box[3]}]

load_options:
  fallback_source: demcast

electricity:
  renewable_carriers: [solar, onwind, offwind-ac, offwind-dc, hydro]

renewable:
{renew}
build_shape_options:
  nprocesses: 1
  gdp_method: standard
{shape_extra}  clip_bbox: [{clip[0]}, {clip[1]}, {clip[2]}, {clip[3]}]

{clustering}
solving:
  solver:
    name: gurobi

catalyst:
  single_node: true
  extra_opts: ATKc
"""
    with open(os.path.join(CFG, f"config.{g}.yaml"), "w") as f:
        f.write(head + cfg)


def main():
    df, world = select()
    df.to_csv(OUT, index=False)
    mod = df[df.status == "modelled"]
    for g in GROUPS:
        sel = mod[mod.group == g]
        if len(sel):
            write_config(g, sel, world)
    inc = df.status.isin(["archetype", "modelled"])
    print(f"world {world:.0f} TWh; archetypes {df.loc[df.status == 'archetype', 'demand_twh'].sum():.0f} TWh; "
          f"covered {df.loc[inc, 'demand_twh'].sum() / world:.2%} with {len(mod)} single-node countries")
    print(mod.groupby("group").agg(n=("iso2", "size"), twh=("demand_twh", "sum")).to_string())
    sk = df[df.status == "skipped"]
    print("skipped:", "; ".join(f"{r.iso2 or r.iso3} {r.name} {r.demand_twh:.1f} TWh ({r.reason})" for r in sk.itertuples()))
    print("last modelled:", mod.iloc[-1][["iso2", "name", "demand_twh"]].to_dict())


if __name__ == "__main__":
    if sys.argv[1:2] == ["--geofabrik"]:
        with open(os.path.join(CFG, f"config.{sys.argv[2]}.yaml")) as fh:
            ccs = yaml.safe_load(fh)["countries"]
        resolve = geofabrik_resolver()
        paths = [resolve(c) for c in ccs]
        if None in paths:
            sys.exit(f"no Geofabrik extract for {[c for c, p in zip(ccs, paths) if p is None]}")
        print(" ".join(dict.fromkeys(paths)))
    else:
        main()
