# SPDX-License-Identifier: CC0-1.0
"""
Check the grid of the spatially resolved regions against real project metrics, without rerunning anything.

Reads the existing networks/<R>/base.nc, resources/<R>/base_network/all_lines_build_network.csv, the raw OSM tables and
data/hvdc/hvdc_project_table.csv, and applies in memory what the grid options of the stage configs do: one row per OSM
way (clean_osm_data_options.drop_duplicate_ids), circuits per way (fix_indirect_circuits), geodesic lengths (build_osm_network.geodesic_length) and ratings per
project (links.dc_projects, the fork's scripts/_dc_projects.py). Existing networks, resources and results are not touched
and do not contain these corrections. Writes to model-doc/build/grid_check/:

    projects_<R>.csv   one row per listed project: status, listed vs route km, segments, clusters crossed
    borders_NWE.csv    capacity per cross-border pair: current base network, corrected, listed in service
    ratings_<R>.csv    OSM rating tag vs table for the ways of each project, the matching does not use it
    unclaimed_names_<R>.csv  named ways no project claims: lines missing from the table
    summary.csv        one row per region: true GW km, match rates, route km per voltage, duplicates
    ac_summary.csv, ac_circuit_km_<R>.csv   AC circuit km before and after fix_indirect_circuits
    merge_fix.csv      where the load of the fragments goes without the merge (p_threshold_merge_isolated: false)

Usage (from config-pypsa-earth): ../models/pypsa-earth/.pixi/envs/default/bin/python scripts/check_grid.py [REGION ...]
"""
import ast
import json
import os
import re
import sys

import numpy as np
import pandas as pd
import pyproj
import shapely.wkt
import xarray as xr

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORK = os.path.join(HERE, "..", "models", "pypsa-earth")
sys.path.insert(0, os.path.join(FORK, "scripts"))
from _dc_projects import assign_projects, missing_links, read_way_names  # noqa: E402

OUT = os.path.join(HERE, "model-doc", "build", "grid_check")
REGIONS = {"US": ["US"], "BR": ["BR"], "IN": ["IN"], "CN": ["CN"], "NWE": "IE GB FR BE NL LU DE DK CH AT CZ PL".split()}
REFERENCE_YEAR = 2024
GEOD = pyproj.Geod(ellps="WGS84")
STEM = re.compile(r"^(\d+)(?:-(\d+))?(?:_(\d+))?$")


def true_km(rows):
    """Length on the Earth's surface. The stored length of a split line is right but measured in Web Mercator; its geometry is
    measured properly but may still be that of the whole way. So the geometry where it agrees with the stored length, else
    the stored length x cos(latitude)."""
    geoms = [shapely.wkt.loads(g) if isinstance(g, str) else None for g in rows.geometry]
    geodesic = np.array([GEOD.geometry_length(g) / 1e3 if g is not None else np.nan for g in geoms])
    lat = np.array([g.centroid.y if g is not None else np.nan for g in geoms])
    scaled = rows.length.values / 1e3 * np.cos(np.radians(lat))
    return pd.Series(np.where(geodesic <= 1.05 * scaled, geodesic, scaled), index=rows.index)


def table(ds, comp):
    idx = f"{comp}_i"
    cols = {k[len(comp) + 1 :]: ds[k].values for k in ds.data_vars if k.startswith(comp + "_") and ds[k].dims == (idx,)}
    df = pd.DataFrame(cols, index=ds[idx].values.astype(str))
    for c in df:
        if df[c].dtype.kind in "SO":
            df[c] = df[c].astype(str)
    return df


def extra_tags(cell):
    """earth-osm keeps rare tags as a dict in the column other_tags."""
    if not isinstance(cell, str):
        return {}
    try:
        return json.loads(cell)
    except ValueError:
        try:
            return ast.literal_eval(cell)
        except (ValueError, SyntaxError):
            return {}


def raw_ways(region):
    """All ways; name and rating of the HVDC ways come from their own column or from other_tags (earth-osm puts a tag in either)."""
    frames = []
    for kind in ("lines", "cables"):
        fn = os.path.join(FORK, f"resources/{region}/osm/raw/all_raw_{kind}.csv")
        if os.path.getsize(fn):
            cols = ("id", "Region", "tags.name", "tags.rating", "tags.frequency", "tags.voltage", "lonlat", "other_tags")
            frames.append(pd.read_csv(fn, low_memory=False, usecols=lambda c: c in cols))
    raw = pd.concat(frames, ignore_index=True).reindex(columns=["id", "Region", "tags.name", "tags.rating", "tags.frequency", "tags.voltage", "lonlat", "other_tags"])
    dc = pd.to_numeric(raw["tags.frequency"], errors="coerce").eq(0)
    extra = raw.other_tags[dc].map(extra_tags)
    raw["osm_name"], raw["osm_rating"] = raw["tags.name"].astype(object), raw["tags.rating"].astype(object)
    raw.loc[dc, "osm_name"] = raw["tags.name"][dc].where(raw["tags.name"][dc].notna(), extra.map(lambda t: t.get("tags.name:en") or t.get("tags.name")))
    raw.loc[dc, "osm_rating"] = raw["tags.rating"][dc].where(raw["tags.rating"][dc].notna(), extra.map(lambda t: t.get("tags.rating")))
    return raw


def read_links(region):
    """DC links of the base network, with OSM way id and geodesic length from the build_osm_network table."""
    ds = xr.open_dataset(os.path.join(FORK, f"networks/{region}/base.nc"))
    links, buses = table(ds, "links"), table(ds, "buses")
    dc = links[links.carrier == "DC"].copy()
    ways = pd.read_csv(os.path.join(FORK, f"resources/{region}/base_network/all_lines_build_network.csv"), low_memory=False,
                       usecols=lambda c: c in ("Unnamed: 0", "line_id", "dc", "voltage", "geometry"))
    ways.index = ways["Unnamed: 0"].astype(str)
    dc["line_id"] = ways.line_id.reindex(dc.index).astype(str)
    ways["length"] = dc.length.astype(float).reindex(ways.index) * 1e3  # km in the network
    dc["geodesic_km"] = true_km(ways.reindex(dc.index))
    dc["length"] = dc.length.astype(float)
    dc["osm_id"] = dc.line_id.map(lambda s: m.group(1) if (m := STEM.match(s)) else s)
    dc["copy"] = dc.line_id.map(lambda s: int(m.group(2)) if (m := STEM.match(s)) and m.group(2) else 1)
    return dc, buses


def drop_duplicates(dc, raw):
    """What drop_duplicate_ids removes: of a way in n country extracts, keep the rows of one extract."""
    extracts = raw.groupby("id").size()
    n = dc.osm_id.map(lambda s: extracts.get(int(s), 1) if s.isdigit() else 1)
    size = dc.groupby("osm_id").copy.transform("max")
    return dc[(n <= 1) | (dc["copy"] <= (size / n).clip(lower=1))]


def busmap(region):
    """Base bus -> cluster of the existing `now` stage."""
    folder = os.path.join(FORK, f"resources/{region}-now/bus_regions")
    first = pd.read_csv(os.path.join(folder, "busmap_elec_s.csv"), index_col=0, dtype=str).squeeze("columns")
    second = pd.read_csv(os.path.join(folder, "busmap_elec_s_50.csv"), index_col=0, dtype=str).squeeze("columns")
    first.index, second.index = first.index.astype(str), second.index.astype(str)
    return first.map(second)


def dc_to_cluster(region, buses):
    """Cluster of every bus; DC buses are absorbed in simplify_network, so they take the cluster of the nearest mapped bus."""
    from scipy.spatial import KDTree

    mapped = busmap(region).dropna()
    known = buses.reindex(mapped.index)[["x", "y"]].astype(float).dropna()
    tree = KDTree(known.values)
    nearest = tree.query(buses[["x", "y"]].astype(float).values)[1]
    full = pd.Series(mapped.reindex(known.index).values[nearest], index=buses.index.astype(str))
    full.update(mapped)
    return full


def osm_mw(text):
    """Sum of a rating tag such as '250 MW;440 MW' or '8000 MVA'; NaN if none."""
    values = re.findall(r"(\d+(?:\.\d+)?)\s*(GW|MW|MVA)?", str(text)) if pd.notna(text) else []
    return sum(float(v) * (1000 if u == "GW" else 1) for v, u in values) if values else np.nan


def rating_check(report, dc, raw):
    """OSM rating tag of the ways of each matched project: an input the matching does not use."""
    ways = raw[pd.to_numeric(raw["tags.frequency"], errors="coerce").eq(0)].drop_duplicates("id").set_index("id")
    rows = []
    for _, r in report[report.link_ids.astype(str).ne("")].iterrows():
        for link in str(r.link_ids).split(";"):
            way = dc.at[link, "osm_id"] if link in dc.index else ""
            if way.isdigit() and int(way) in ways.index and pd.notna(ways.osm_rating[int(way)]):
                rows.append(dict(project=r["name"], p_nom_mw=r.p_nom_mw, link=link, osm_rating=ways.osm_rating[int(way)], osm_mw=osm_mw(ways.osm_rating[int(way)])))
    return pd.DataFrame(rows, columns=["project", "p_nom_mw", "link", "osm_rating", "osm_mw"])


# Published AC circuit km at the modelled voltages, for the partial AC check. km; the Brazil value is route or circuit km as ONS reports it, for 2020
PUBLISHED_AC = {"IN": (466560, "CEA via Indian Infrastructure, May 2024: 765, 400 and 230/220 kV"),
                "DE": (37000, "German economy ministry grid dossier: about 37,000 km, 220 and 380 kV"),
                "BR": (123008, "ONS 2020 via IPEA: 123,008 km of AC lines; IPEA projects +28 % by 2024")}


def ac_check(region):
    """AC circuit km: as in the network, with geodesic lengths, one row per way and fix_indirect_circuits, against published totals."""
    d = pd.read_csv(os.path.join(FORK, f"resources/{region}/base_network/all_lines_build_network.csv"), low_memory=False,
                    usecols=["line_id", "circuits", "voltage", "length", "dc", "bus0", "geometry"])
    a = d[~d.dc.astype(bool)].copy()
    a["osm"] = pd.to_numeric(a.line_id.str.extract(r"^(\d+)")[0], errors="coerce")
    a["geodesic_km"] = true_km(a)
    cols = ("id", "tags.circuits", "tags.cables", "tags.voltage", "Region")
    raw = []
    for kind in ("lines", "cables"):
        raw.append(pd.read_csv(os.path.join(FORK, f"resources/{region}/osm/raw/all_raw_{kind}.csv"), low_memory=False,
                               usecols=lambda c: c in cols).reindex(columns=list(cols)))
    raw = pd.concat(raw)
    extracts = raw.groupby("id").size()
    raw = raw.drop_duplicates("id").set_index("id")
    tags = raw.reindex(a.osm.fillna(-1).astype("int64")).reset_index(drop=True)
    tags.index = a.index
    n_volt = tags["tags.voltage"].astype(str).str.split(";").map(len)
    n_circ = tags["tags.circuits"].astype(str).str.split(";").map(len)
    cables = pd.to_numeric(tags["tags.cables"], errors="coerce")
    # the branch of fill_circuits: several voltages, circuits missing or of another length, one total of cables
    hit = (n_volt > 1) & (tags["tags.circuits"].isna() | (n_circ != n_volt)) & cables.notna()
    a["fixed"] = a.circuits.where(~hit, a.circuits / 3.0)
    # drop_duplicate_ids: a way in n extracts keeps 1 / n of its rows, approximately by scaling
    a["fixed"] = a.fixed / a.osm.map(extracts).fillna(1.0).clip(lower=1.0)
    km = a.length / 1e3
    per_way = pd.DataFrame({"osm": a.osm, "old": a.circuits, "new": a.fixed, "hit": hit})
    tagged = per_way[per_way.hit].groupby("osm").agg(old=("old", "sum"), new=("new", "sum"))
    total = tags["tags.circuits"].groupby(a.osm).first().pipe(pd.to_numeric, errors="coerce").reindex(tagged.index)
    ok = total.notna()
    by_v = pd.DataFrame({"network": a.circuits * km, "true_length": a.circuits * a.geodesic_km, "corrected": a.fixed * a.geodesic_km}).groupby(a.voltage).sum()
    by_v.to_csv(os.path.join(OUT, f"ac_circuit_km_{region}.csv"), float_format="%.0f")
    rows = [dict(area=region, network=(a.circuits * km).sum(), true_length=(a.circuits * a.geodesic_km).sum(), corrected=(a.fixed * a.geodesic_km).sum(),
                 ways_hit=len(tagged), ways_tagged=int(ok.sum()), ways_old_above_tag=int((tagged.old[ok] > total[ok] + 1e-6).sum()),
                 ways_new_above_tag=int((tagged.new[ok] > total[ok] + 1e-6).sum()))]
    if region == "NWE":
        ds = xr.open_dataset(os.path.join(FORK, f"networks/{region}/base.nc"))
        bus = pd.Series(ds.buses_country.values.astype(str), ds.buses_i.values.astype(str))
        de = a.bus0.astype(str).map(bus) == "DE"
        rows.append(dict(area="DE", network=(a.circuits * km)[de].sum(), true_length=(a.circuits * a.geodesic_km)[de].sum(), corrected=(a.fixed * a.geodesic_km)[de].sum()))
    for r in rows:
        r["published"], r["published_source"] = PUBLISHED_AC.get(r["area"], (np.nan, ""))
    return rows


def merge_check():
    """p_threshold_merge_isolated: false, structurally: where the load of the fragments below 300 MW goes (elec.nc of the `now` stage)."""
    sys.path.insert(0, os.path.join(HERE, "model-doc", "scripts"))
    from plot_isolated import fates
    from scipy.spatial import KDTree

    rows = []
    for region in ("IN", "CN", "NWE"):
        buses, _, merged = fates(os.path.join(FORK, f"networks/{region}-now/elec.nc"), merge=True)
        for country, m in merged.items():
            nat = buses[(buses.country == country) & (buses.fate != "dropped")].load.sum()
            frag = buses[(buses.country == country) & (buses.fate == "merged")]
            back = buses[(buses.country == country) & (buses.fate == "backbone")]
            target = back.index[KDTree(back[["x", "y"]].values).query(frag[["x", "y"]].values)[1]]
            per_bus = frag.load.groupby(target).sum()
            largest = frag.groupby("sub").load.sum().max()
            rows.append(dict(region=region, country=country, merged_load_gw=m["load"] / 1e3, merged_share=m["share"], today="joined at one bus" if m["fetched"] else "stays isolated",
                             fragments=frag["sub"].nunique(), largest_fragment_share=largest / nat, fix_isolated_left=int((frag.groupby("sub").load.sum() / nat >= 0.05).sum()),
                             fix_largest_on_one_bus_gw=per_bus.max() / 1e3, fix_buses_receiving=len(per_bus)))
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(OUT, "merge_fix.csv"), index=False, float_format="%.4g")
    print(out.round(3).to_string(index=False))
    return out


def check(region):
    countries = REGIONS[region]
    raw = raw_ways(region)
    dc_all, buses = read_links(region)
    dc = drop_duplicates(dc_all, raw)
    projects = pd.read_csv(os.path.join(HERE, "data", "hvdc", "hvdc_project_table.csv"))
    projects = projects[projects.country1.isin(countries) | projects.country2.isin(countries)]
    names = read_way_names(os.path.join(FORK, f"resources/{region}/osm/raw"))
    dc = dc.copy()
    dc["osm_name"] = dc.osm_id.map(lambda s: names.get(int(s)) if s.isdigit() else None)
    p_nom, future, report = assign_projects(dc.assign(length=dc.geodesic_km.fillna(dc.length)), buses, projects, REFERENCE_YEAR, dc.osm_name)
    report["cross_check_km"] = report.route_km / report.length_km

    bm = dc_to_cluster(region, buses)
    crossed = []
    for ids in report.link_ids.astype(str):
        ends = dc.reindex([i for i in ids.split(";") if i], columns=["bus0", "bus1"]).astype(str).values.ravel()
        crossed.append(pd.Series(ends).map(bm).nunique() if len(ends) else 0)
    report["clusters"] = crossed

    added = missing_links(report, projects, buses, REFERENCE_YEAR)
    added.to_csv(os.path.join(OUT, f"added_{region}.csv"))

    new = dc.copy()
    new["p_nom_new"] = p_nom.reindex(new.index)
    new["matched"] = new.p_nom_new.notna()
    new["future"] = future.reindex(new.index).astype("boolean").fillna(False).astype(bool)
    new["p_nom_new"] = new.p_nom_new.fillna(new.p_nom.astype(float))
    new.loc[new.future, "p_nom_new"] = 0.0
    report.drop(columns="link_ids").to_csv(os.path.join(OUT, f"projects_{region}.csv"), index=False, float_format="%.5g")
    ratings = rating_check(report, dc, raw)
    ratings["agree"] = (ratings.osm_mw - ratings.p_nom_mw).abs() <= 0.1 * ratings.p_nom_mw
    ratings.to_csv(os.path.join(OUT, f"ratings_{region}.csv"), index=False)
    # named ways no project claims, longest first: lines missing from the table
    mapped = set(pd.read_csv(os.path.join(HERE, "data", "hvdc", "osm_name_map.csv"), comment="#").osm_name)
    unclaimed = new[new.osm_name.notna() & ~new.osm_name.isin(mapped)]
    unclaimed.groupby("osm_name").geodesic_km.sum().sort_values(ascending=False).to_csv(os.path.join(OUT, f"unclaimed_names_{region}.csv"), float_format="%.0f")

    done = report[report.status == "matched"]
    in_service = report[(report.year <= REFERENCE_YEAR) & (report.status != "below threshold")]
    listed = in_service[in_service.length_km.notna() & in_service.p_nom_mw.notna()]
    out = dict(
        region=region,
        duplicates_removed=len(dc_all) - len(dc),
        projects_in_service=len(in_service),
        projects_matched=len(in_service[in_service.status == "matched"]),
        dc_km_geodesic=dc.geodesic_km.sum(),
        dc_km_matched=new.loc[new.matched, "geodesic_km"].sum(),
        gwkm_current_mercator=(dc_all.p_nom.astype(float) * dc_all.length).sum() / 1e3,
        gwkm_current_geodesic=(dc_all.p_nom.astype(float) * dc_all.geodesic_km).sum() / 1e3,
        gwkm_keep_unmatched=(new.p_nom_new * new.geodesic_km).sum() / 1e3,
        gwkm_matched_only=(new.p_nom_new * new.geodesic_km)[new.matched].sum() / 1e3,
        projects_added=len(added),
        gwkm_added=(added.p_nom * added.length).sum() / 1e3 if len(added) else 0.0,
        gwkm_listed=(listed.p_nom_mw * listed.length_km).sum() / 1e3,
        by_name=int(report.method.eq("name").sum()),
        by_name_and_terminals=int(report.method.eq("name and terminals").sum()),
        by_name_all_ways=int(report.method.eq("name, all ways").sum()),
        dc_km_named=dc.geodesic_km[dc.osm_name.notna()].sum(),
        dc_km_unclaimed=unclaimed.geodesic_km.sum(),
        rated_links=len(ratings),
        rating_agree=int(ratings.agree.sum()),
        listed_with_length=len(listed),
        route_within_10pct=((done.cross_check_km - 1).abs() <= 0.1).sum(),
        route_compared=done.cross_check_km.notna().sum(),
        median_route_ratio=done.cross_check_km.median(),
        links=len(dc),
        links_unmatched=int((~new.matched).sum()),
        mercator_factor=dc.length.sum() / dc.geodesic_km.sum(),
    )
    out["gwkm_corrected"] = out["gwkm_matched_only"] + out["gwkm_added"]
    print(f"\n=== {region}\n" + pd.Series(out).to_string())
    print(report.drop(columns="link_ids").sort_values("year").round(2).to_string(index=False))

    if region == "NWE":
        cur, cor = dc_all.copy(), new
        def by_pair(df, col):
            a, b = df.bus0.astype(str).map(buses.country), df.bus1.astype(str).map(buses.country)
            pair = pd.Series(["-".join(sorted(x)) for x in zip(a, b)], index=df.index)
            return df[col].astype(float)[a != b].groupby(pair[a != b]).sum() / 1e3
        p = projects[(projects.year <= REFERENCE_YEAR) & (projects.country1 != projects.country2)]
        p = p[p.country1.isin(countries) & p.country2.isin(countries)]
        listed_pair = p.groupby(["-".join(sorted(x)) for x in zip(p.country1, p.country2)]).p_nom_mw.sum() / 1e3
        cor = cor[cor.matched]
        extra = added.assign(a=added.bus0.map(buses.country), b=added.bus1.map(buses.country))
        extra = extra[extra.a != extra.b]
        extra = extra.groupby(["-".join(sorted(x)) for x in zip(extra.a, extra.b)]).p_nom.sum() / 1e3
        corrected = by_pair(cor, "p_nom_new").add(extra, fill_value=0.0)
        borders = pd.DataFrame({"current_base_sum": by_pair(cur, "p_nom"), "corrected_sum": corrected, "listed": listed_pair}).fillna(0.0)
        borders.to_csv(os.path.join(OUT, "borders_NWE.csv"), float_format="%.3f")
        print(borders.round(2).to_string())
    return out, new


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    regions = sys.argv[1:] or list(REGIONS)
    rows = [check(r)[0] for r in regions]
    ac = pd.DataFrame([row for r in regions for row in ac_check(r)])
    ac.to_csv(os.path.join(OUT, "ac_summary.csv"), index=False, float_format="%.4g")
    print(ac.round(3).T.to_string())
    merge_check()
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "summary.csv" if not sys.argv[1:] else f"summary_{'_'.join(regions)}.csv"), index=False, float_format="%.4g")
