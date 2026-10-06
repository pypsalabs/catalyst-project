#!/usr/bin/env python
"""
Check that the bus_regions/ files of a pypsa-earth run describe the run's own networks.

    cd models/pypsa-earth && pixi run python ../../config-pypsa-earth/scripts/check_bus_regions.py [RUN ...] [-v]

Without arguments every networks/<run>/ that holds a clustered network elec_s{simpl}_{clusters}.nc is
checked. One line per run and clustering; exit code 1 if any run is inconsistent.

Checks (c = clusters wildcard, files under resources/<run>/bus_regions/ and networks/<run>/):
  regions_s   every name of regions_onshore_elec_s{simpl}.geojson is a bus of elec_s{simpl}.nc (skipped for
              GADM-clustered runs, clustering.alternative_clustering, whose simplified regions are GADM shapes)
  busmap_idx  busmap_elec_s{simpl}_{c}.csv index               == buses of elec_s{simpl}.nc
  busmap_val  busmap_elec_s{simpl}_{c}.csv values (clusters)   == buses of elec_s{simpl}_{c}.nc
  regions_c   every name of regions_onshore/offshore_elec_s{simpl}_{c}.geojson is a bus of elec_s{simpl}_{c}.nc
  Buses without an onshore polygon (DC buses and other substations pypsa-earth's build_bus_regions gives no
  Voronoi cell, e.g. the DC buses of the pre-2026-09-19 smoke runs) are reported but are not a mismatch;
  a polygon that belongs to no bus is.
  xy_mean     x/y of every clustered bus == mean x/y of its busmap members (|dev| < 1e-6 deg); this is
              the check that catches a busmap of the right shape but from a different clustering run
  downstream  every later network of the run (elec_s{simpl}_{c}_*.nc, results/<run>/networks/*.nc)
              contains the clustered buses (extra store buses from add_extra_components are allowed)

Why: cluster_network writes network and busmap/regions in one go, so they can only disagree when files
are overwritten afterwards. That happened on 2026-09-20 for the base runs US, BR and IN: the scenario
runs <R>-now / <R>-zero shared resources/<R> through a directory symlink and simplify_network /
cluster_network of the scenario runs (by then with the DC-bus absorption patch of 2026-09-19, i.e. a
different simplified network) rewrote resources/<R>/bus_regions/*. run.sh gives scenario runs their own
bus_regions/ since then; this script makes the state visible. See config-pypsa-earth/README.md,
"Caveats: bus_regions of the base runs".

Only the bus tables of the netCDF files are read (no time series), so a check costs seconds.
"""
import argparse
import glob
import os
import re
import sys

import json

import pandas as pd
import xarray as xr

HERE = os.path.dirname(os.path.abspath(__file__))


def find_pe():
    """models/pypsa-earth above this script, identified by its Snakefile (a git worktree of the study repo holds an
    empty models/pypsa-earth placeholder; PYPSA_EARTH overrides)."""
    if os.environ.get("PYPSA_EARTH"):
        return os.environ["PYPSA_EARTH"]
    d = HERE
    while True:
        cand = os.path.join(d, "models", "pypsa-earth")
        if os.path.isfile(os.path.join(cand, "Snakefile")):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            sys.exit("models/pypsa-earth (with a Snakefile) not found above " + HERE)
        d = parent


PE = find_pe()

CLUSTERED = re.compile(r"^elec_s(?P<simpl>\d*)_(?P<clusters>\d+(?:m|flex)?)\.nc$")
TOL = 1e-6


def buses(path):
    """Static bus table of a pypsa netCDF export (buses_* variables over buses_i), no time series."""
    with xr.open_dataset(path) as ds:
        cols = {
            k[len("buses_"):]: ds[k].values
            for k in ds.data_vars
            if k.startswith("buses_") and ds[k].dims == ("buses_i",)
        }
        return pd.DataFrame(cols, index=ds["buses_i"].values.astype(str))


def alternative_clustering(path):
    """clustering.alternative_clustering of the config stored in the network's meta (GADM-shape clustering)."""
    with xr.open_dataset(path) as ds:
        try:
            return bool(json.loads(ds.attrs["meta"])["clustering"]["alternative_clustering"])
        except (KeyError, ValueError, TypeError):
            return False


def region_names(path):
    import geopandas as gpd

    return set(gpd.read_file(path, columns=["name"])["name"].astype(str))


def describe(a, b, name_a, name_b, limit=6):
    only_a, only_b = sorted(a - b), sorted(b - a)
    out = []
    if only_a:
        out.append(f"{len(only_a)} only in {name_a}: {only_a[:limit]}{' ...' if len(only_a) > limit else ''}")
    if only_b:
        out.append(f"{len(only_b)} only in {name_b}: {only_b[:limit]}{' ...' if len(only_b) > limit else ''}")
    return "; ".join(out)


def check_run(run, verbose=False):
    """Return (ok, lines). One entry per clustered network of the run."""
    ndir = os.path.join(PE, "networks", run)
    rdir = os.path.join(PE, "resources", run, "bus_regions")
    lines, ok_all = [], True
    clustered = sorted(f for f in os.listdir(ndir) if CLUSTERED.match(f)) if os.path.isdir(ndir) else []
    if not clustered:
        return True, [f"{run:10s} no clustered network in networks/{run}/ -> skipped"]
    for f in clustered:
        m = CLUSTERED.match(f)
        simpl, c = m["simpl"], m["clusters"]
        results = {}  # check -> (ok, detail)

        def rec(name, ok, detail=""):
            results[name] = (ok, detail)

        try:
            bs = buses(os.path.join(ndir, f"elec_s{simpl}.nc"))
            bc = buses(os.path.join(ndir, f))
        except FileNotFoundError as e:
            lines.append(f"{run:10s} {f}: cannot read {e.filename}")
            ok_all = False
            continue
        s_set, c_set = set(bs.index), set(bc.index)
        gadm = alternative_clustering(os.path.join(ndir, f))

        def polygons_vs_buses(names, bus_set, bus_df, label):
            """ok unless a polygon names no bus; buses without a polygon are listed as information."""
            orphan, bare = sorted(names - bus_set), sorted(bus_set - names)
            det = []
            if orphan:
                det.append(f"{len(orphan)} polygons that are no bus of {label}: {orphan[:6]}{' ...' if len(orphan) > 6 else ''}")
            if bare:
                carriers = bus_df.reindex(bare)["carrier"].value_counts().to_dict() if "carrier" in bus_df else {}
                det.append(f"{len(bare)} buses without onshore polygon {carriers or ''}: {bare[:6]}{' ...' if len(bare) > 6 else ''}")
            return not orphan, "; ".join(det)

        p = os.path.join(rdir, f"regions_onshore_elec_s{simpl}.geojson")
        if gadm:
            rec("regions_s", True, "GADM shapes (alternative_clustering), not per bus -> skipped")
        elif os.path.exists(p):
            rec("regions_s", *polygons_vs_buses(region_names(p), s_set, bs, "elec_s"))
        else:
            rec("regions_s", False, "missing")

        p = os.path.join(rdir, f"busmap_elec_s{simpl}_{c}.csv")
        busmap = None
        if os.path.exists(p):
            busmap = pd.read_csv(p, index_col=0).squeeze("columns")
            busmap.index = busmap.index.astype(str)
            busmap = busmap.astype(str)
            rec("busmap_idx", set(busmap.index) == s_set, describe(set(busmap.index), s_set, "busmap", "elec_s"))
            rec("busmap_val", set(busmap.unique()) == c_set, describe(set(busmap.unique()), c_set, "busmap", f"elec_s_{c}"))
        else:
            rec("busmap_idx", False, "missing")
            rec("busmap_val", False, "missing")

        p = os.path.join(rdir, f"regions_onshore_elec_s{simpl}_{c}.geojson")
        if os.path.exists(p):
            ok_c, det = polygons_vs_buses(region_names(p), c_set, bc, f"elec_s_{c}")
            off = os.path.join(rdir, f"regions_offshore_elec_s{simpl}_{c}.geojson")
            if os.path.exists(off):
                extra = sorted(region_names(off) - c_set)
                if extra:
                    ok_c = False
                    det += f"; {len(extra)} offshore polygons that are no bus: {extra[:6]}"
            rec("regions_c", ok_c, det)
        else:
            rec("regions_c", False, "missing")

        if busmap is not None and results["busmap_idx"][0] and results["busmap_val"][0]:
            mean_xy = bs[["x", "y"]].groupby(busmap).mean().reindex(bc.index)
            dev = (bc[["x", "y"]] - mean_xy).abs()
            worst = dev.max(axis=1).sort_values(ascending=False)
            rec("xy_mean", worst.iloc[0] < TOL, f"max |xy - member mean| = {worst.iloc[0]:.3g} deg at {worst.index[0]}")
        else:
            rec("xy_mean", False, "not evaluated (busmap does not match)")

        later = sorted(glob.glob(os.path.join(ndir, f"elec_s{simpl}_{c}_*.nc"))) + sorted(
            glob.glob(os.path.join(PE, "results", run, "networks", f"elec_s{simpl}_{c}_*.nc"))
        )
        bad = []
        for q in later:
            missing = c_set - set(buses(q).index)
            if missing:
                bad.append(f"{os.path.relpath(q, PE)} lacks {len(missing)} buses")
        rec("downstream", not bad, "; ".join(bad) if bad else f"{len(later)} later networks")

        ok = all(v[0] for v in results.values())
        ok_all &= ok
        failed = [k for k, v in results.items() if not v[0]]
        head = f"{run:10s} elec_s{simpl}_{c}: {len(bs)} simplified -> {len(bc)} clustered buses: " + (
            "OK" if ok else "MISMATCH (" + ", ".join(failed) + ")"
        )
        lines.append(head)
        if verbose or not ok:
            for k, (good, det) in results.items():
                if verbose or not good:
                    lines.append(f"{'':10s}   {'ok  ' if good else 'FAIL'} {k:11s} {det}")
    return ok_all, lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="*", help="run names (networks/<run>/); default: all runs with a clustered network")
    ap.add_argument("-v", "--verbose", action="store_true", help="print every check, not only the failed ones")
    args = ap.parse_args(argv)
    runs = args.runs or sorted(
        d for d in os.listdir(os.path.join(PE, "networks"))
        if os.path.isdir(os.path.join(PE, "networks", d))
        and any(CLUSTERED.match(f) for f in os.listdir(os.path.join(PE, "networks", d)))
    )
    ok_all = True
    for run in runs:
        ok, lines = check_run(run, args.verbose)
        ok_all &= ok
        print("\n".join(lines))
    if not ok_all:
        print(
            "\nInconsistent runs: their resources/<run>/bus_regions/ files were written for another network "
            "(see config-pypsa-earth/README.md, 'Caveats: bus_regions of the base runs'); rebuild with\n"
            "  rm networks/<run>/elec_s*.nc && bash config-pypsa-earth/run.sh <run>"
        )
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
