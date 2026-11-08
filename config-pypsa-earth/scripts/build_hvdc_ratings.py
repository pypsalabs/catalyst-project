# SPDX-License-Identifier: CC0-1.0
"""
Rated capacity of an HVDC line by country and pole voltage, for the fork option `links.dc_ratings` (base_network).

OpenStreetMap maps HVDC lines with their voltage but (on ways) without their rating, and PyPSA-Earth turns every DC
line into a link of v_nom x 1.638 kA (one 500 kV cable type): 1.31 GW for a +-800 kV bipole that carries 4-10 GW. This
script reads Wikipedia's "List of HVDC projects" (wikitext cached in data/hvdc/list_of_hvdc_projects.wikitext, fetched
2026-10-19 with action=raw) and writes

    data/hvdc/hvdc_projects.csv   one row per listed point-to-point project (plus data/hvdc/manual.csv, projects the
                                  list lacks) (B2B table left out): name, country1,
                                  country2, voltage_kv, p_nom_mw, year, status (row colour of the list)
    data/hvdc/hvdc_ratings.csv    country, voltage_kv, p_nom_mw, n_projects, source: the median rating of the projects
                                  not decommissioned per country (either terminal) and voltage; rows with country "*" = the
                                  world median per voltage, used where a country has no project at that voltage

Screening-grade: one source, medians over projects of different eras, multi-bipole projects listed with their total
(e.g. Itaipu) are counted as one line. Usage (from config-pypsa-earth):

    ../models/pypsa-earth/.pixi/envs/default/bin/python scripts/build_hvdc_ratings.py

With --table it writes only data/hvdc/hvdc_project_table.csv, the input of the fork option `links.dc_projects`, and leaves the
two files above alone: one row per project of the modelled regions with terminals x1, y1, x2, y2, length_km, in the priority
data/hvdc/project_corrections.csv (hand-curated, one source per row; action drop removes a list row) > the list's own
coordinates > data/hvdc/links_p_nom.csv (the coordinates PyPSA-Eur extracted from an older revision of the same list), and
osm_names = the OSM way names of the project from data/hvdc/osm_name_map.csv, | separated.
"""
import os
import re
import sys

import country_converter as coco
import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(HERE, "data", "hvdc")
SOURCE = "Wikipedia, List of HVDC projects (revision of 2026-10-19)"
STATUS = {"efbfbf": "decommissioned", "efffbf": "planned", "bfbfff": "under construction"}


def number(cell):
    """First number of a table cell (strips +-, thousands separators and footnotes); NaN if none."""
    m = re.search(r"\d[\d,]*(?:\.\d+)?", cell.replace("&nbsp;", " "))
    return float(m.group(0).replace(",", "")) if m else float("nan")


def country(cell):
    """Country name in front of " - " of a converter-station cell."""
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", cell)
    return re.split(r"\s+[-–]\s+|<br", text, maxsplit=1)[0].strip()


def coordinate(cell):
    """(lon, lat) of the {{Coord}} template of a converter-station cell; NaNs if none."""
    m = re.search(r"\{\{[Cc]oord\|([^}]*)\}\}", cell)
    if not m:
        return float("nan"), float("nan")
    parts = [p.strip() for p in m.group(1).split("|") if "=" not in p and ":" not in p]
    try:
        if not {"N", "S"} & set(parts):
            return float(parts[1]), float(parts[0])
        i = next(k for k, p in enumerate(parts) if p in "NS")
        j = next(k for k, p in enumerate(parts) if p in "EW")
        dms = lambda values: sum(float(v) / 60**k for k, v in enumerate(values))
        return (dms(parts[i + 1 : j]) * (1 if parts[j] == "E" else -1), dms(parts[:i]) * (1 if parts[i] == "N" else -1))
    except (ValueError, StopIteration):
        return float("nan"), float("nan")


def parse(fn):
    t = open(fn).read()
    t = re.sub(r"<ref[^>]*/>", "", t)
    t = re.sub(r"<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    tables = re.findall(r"\n\{\|.*?\n\|\}", t, flags=re.S)[:6]  # the six regional tables; the seventh is back-to-back
    rows = []
    for tb in tables:
        for r in re.split(r"\n\|-", tb)[1:]:
            head, _, body = r.partition("\n")
            cells = [c.strip() for c in re.split(r"\|\||\n\|(?![-}])", body)]
            if len(cells) < 7 or not cells[0].startswith("|"):
                continue
            colour = re.search(r"#([0-9a-fA-F]{6})", head)
            (x1, y1), (x2, y2) = coordinate(cells[1]), coordinate(cells[2])
            rows.append(
                dict(
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    length_km=number(cells[3]),
                    name=re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", cells[0].lstrip("| ")).strip(),
                    country1=country(cells[1]),
                    country2=country(cells[2]),
                    voltage_kv=number(cells[4]),
                    p_nom_mw=number(cells[5]),
                    year=number(cells[6]),
                    status=STATUS.get(colour.group(1).lower(), "existing") if colour else "existing",
                )
            )
    df = pd.DataFrame(rows)
    cc = coco.CountryConverter()
    for c in ("country1", "country2"):
        df[c] = cc.convert(df[c].tolist(), to="ISO2", not_found=None)
    return df


REGION_COUNTRIES = {"US", "BR", "IN", "CN", "IE", "GB", "FR", "BE", "NL", "LU", "DE", "DK", "CH", "AT", "CZ", "PL"}


def project_table():
    """The projects of the modelled regions with terminals, for links.dc_projects (see the module docstring)."""
    df = parse(os.path.join(DIR, "list_of_hvdc_projects.wikitext"))
    eur = pd.read_csv(os.path.join(DIR, "links_p_nom.csv"))
    clean = lambda s: re.sub(r"\W+", "", str(s)).lower()
    eur = eur.assign(key=eur.Name.map(clean)).drop_duplicates("key").set_index("key")
    for c in ("x1", "y1", "x2", "y2"):
        df[c] = df[c].fillna(df.name.map(clean).map(eur[c]))
    df["source"] = SOURCE
    corrections = pd.read_csv(os.path.join(DIR, "project_corrections.csv"), comment="#")
    drop = corrections[corrections.action == "drop"].name
    df = df[~df.name.isin(drop)].set_index("name")
    for _, r in corrections[corrections.action != "drop"].iterrows():
        given = r.drop(["name", "action"]).dropna()
        if r["name"] not in df.index:
            df.loc[r["name"]] = pd.NA
        df.loc[r["name"], given.index] = given.values
    df = df.reset_index()
    df = df[df.country1.isin(REGION_COUNTRIES) | df.country2.isin(REGION_COUNTRIES)]
    df = df[df.status != "decommissioned"]
    names = pd.read_csv(os.path.join(DIR, "osm_name_map.csv"), comment="#")
    unknown = set(names.project) - set(df.name)
    assert not unknown, f"osm_name_map.csv names projects that are not in the table: {unknown}"
    df["osm_names"] = df.name.map(names.groupby("project").osm_name.agg("|".join))
    return df[["name", "country1", "country2", "voltage_kv", "p_nom_mw", "year", "status", "length_km", "x1", "y1", "x2", "y2", "osm_names", "source"]]


if __name__ == "__main__":
    if "--table" in sys.argv:
        table = project_table()
        table.to_csv(os.path.join(DIR, "hvdc_project_table.csv"), index=False, float_format="%.5g")
        ok = table[["x1", "y1", "x2", "y2"]].notna().all(axis=1)
        print(f"{len(table)} projects, {ok.sum()} with both terminals -> hvdc_project_table.csv")
        sys.exit()
    df = parse(os.path.join(DIR, "list_of_hvdc_projects.wikitext")).drop(columns=["x1", "y1", "x2", "y2", "length_km"])
    df = pd.concat([df, pd.read_csv(os.path.join(DIR, "manual.csv"), comment="#").drop(columns="source")], ignore_index=True)
    df.to_csv(os.path.join(DIR, "hvdc_projects.csv"), index=False)
    # design ratings of every listed project except decommissioned ones: the list's row colours lag years behind
    # (Chinese UHVDC lines in operation since 2017-2021 still show as planned / under construction)
    ok = df[(df.status != "decommissioned") & (df.voltage_kv >= 100) & (df.p_nom_mw > 0)]
    both = pd.concat([ok.assign(country=ok.country1), ok[ok.country2 != ok.country1].assign(country=ok.country2)])
    national = both.groupby(["country", "voltage_kv"]).p_nom_mw.agg(["median", "size"])
    world = ok.groupby("voltage_kv").p_nom_mw.agg(["median", "size"])
    world.index = pd.MultiIndex.from_product([["*"], world.index], names=["country", "voltage_kv"])
    out = pd.concat([national, world]).rename(columns={"median": "p_nom_mw", "size": "n_projects"}).reset_index()
    out["source"] = SOURCE
    out.to_csv(os.path.join(DIR, "hvdc_ratings.csv"), index=False)
    print(f"{len(df)} projects ({len(ok)} used) -> {len(out)} rating rows")
