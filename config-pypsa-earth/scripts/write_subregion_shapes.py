#!/usr/bin/env python
# SPDX-License-Identifier: MIT
"""
Subregion shapes of a run that was built before its config got a `subregion:` block (clusters per market zone,
catalyst: cluster_by_zone in config.<R>.yaml; README "Market zones").

    cd models/pypsa-earth && pixi run python ../../config-pypsa-earth/scripts/write_subregion_shapes.py CN [--check]
    (a stage name, e.g. CN-now, takes the config of the stage and writes into the shapes of its base run)

PyPSA-Earth writes resources/<run>/shapes/subregion_{shapes,offshore}.geojson in build_shapes, from the GADM
shapes and the config (subregion: define_by_gadm). A fresh build therefore needs nothing from this script. For a
run that exists, running build_shapes again would give every shape file a new time stamp and so rebuild the whole
run (profiles, plants, networks). This script writes the two files instead, with the functions build_shapes uses
(crop_country, crop_offshore) on the run's gadm_shapes.geojson, and only if they differ from what is on disk: the
new time stamp makes cluster_network and everything after it run again, in the base run and in every stage that
shares its shapes, and nothing before it.

--check prints what would be written and writes nothing.
"""
import os
import sys

import geopandas as gpd
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, "scripts")   # the fork's scripts (cwd = fork root)
import merge_config  # noqa: E402


def same(path, new):
    """True if the file holds the shapes of `new` (same names, same geometries)."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return new.empty
    old = gpd.read_file(path)
    if "name" not in old or set(old.name) != set(new.index):
        return False
    old = old.set_index("name").geometry.reindex(new.index)
    return bool(old.geom_equals_exact(new.geometry, tolerance=1e-9).all())


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check = "--check" in sys.argv
    if len(args) != 1:
        sys.exit(__doc__)
    run = args[0]
    cfg = merge_config.stage_config("overlay" if "-" in run else "prenetwork", run)
    sub = cfg.get("subregion") or {}
    if sub.get("method") != "gadm":
        sys.exit(f"{run}: no subregion: method: gadm in the config, nothing to write")

    from _helpers import save_to_geojson
    from build_shapes import crop_country, crop_offshore

    shapes = f"resources/{(cfg.get('catalyst') or {}).get('base_run', run)}/shapes/"   # a stage shares its base run's
    gadm = gpd.read_file(shapes + "gadm_shapes.geojson").set_index("GADM_ID")
    listed = {u for units in sub["define_by_gadm"].values() for u in units}
    missing = sorted(listed - set(gadm.index))
    if missing:
        sys.exit(f"{run}: GADM units of subregion: define_by_gadm that are not in {shapes}gadm_shapes.geojson: {missing}")
    regions = crop_country(gadm, sub["define_by_gadm"])
    country = gpd.read_file(shapes + "country_shapes.geojson").set_index("name")
    offshore = gpd.read_file(shapes + "offshore_shapes.geojson").set_index("name")["geometry"]
    crs = cfg.get("crs") or yaml.safe_load(open("config.default.yaml"))["crs"]   # the fork's default
    regions_offshore = crop_offshore(regions, country, offshore, distance_crs=crs["distance_crs"])

    print(f"{run}: {len(regions)} subregions ({', '.join(regions.index)}); {len(regions_offshore)} with a sea area")
    for name, new, write in [
        ("subregion_shapes.geojson", regions, lambda p: save_to_geojson(regions, p)),
        ("subregion_offshore.geojson", regions_offshore, lambda p: regions_offshore.reset_index().to_file(p)),
    ]:
        path = shapes + name
        if same(path, new):
            print(f"   {path}: up to date")
        elif check:
            print(f"   {path}: would be written")
        else:
            if os.path.exists(path):
                os.unlink(path)   # the shapes of a run may be hard links into another run: never write through one
            write(path)
            print(f"   {path}: written")
