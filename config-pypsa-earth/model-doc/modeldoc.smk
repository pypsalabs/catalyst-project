# Methods document of the Catalyst model: figures from the model's data -> build/model_doc.pdf.
#
# Standalone, from this directory (the priam-myopic env: snakemake, geopandas, xarray; latexmk, biber, kpfonts on PATH):
#     ../../models/priam-myopic/.pixi/envs/default/bin/snakemake -s modeldoc.smk -c1
#
# rules
#   modeldoc_coverage   world map of the modelled countries (spatially resolved / one node / not modelled) beside a bar
#                       chart of their share of world electricity demand 2024 (scripts/plot_coverage.py)
#   modeldoc_layers     the layer stack of one country model, drawn with Brazil's data (scripts/plot_layers.py): the
#                       base network and plant list of the fork's BR / BR-now stages, the tracked capacity-factor grid
#                       and technology_assumptions.csv of technology-assumptions/
#   modeldoc_grid_map   world map of the grid representation per country, classified from data/row_countries.csv and
#                       the stage configs (scripts/plot_grid_map.py); build/grid_classes.csv lists the classes
#   modeldoc_grid_steps the standard grid procedure for Brazil in three panels: raw OSM, base network, clustered network,
#                       and two close-ups of raw OSM against the base network on OpenStreetMap tiles (scripts/plot_grid_steps.py;
#                       tiles fetched from tile.openstreetmap.org on first run, cached in build/osm_tiles/)
#   modeldoc_hvdc_check France-GB ways in OSM and cross-border capacity now / corrected against the operating projects
#                       (scripts/plot_hvdc_check.py); build/hvdc_check.csv = the numbers of the tables
#   modeldoc_osm_entries  an HVDC way of OpenStreetMap whose name matches a project, and one that does not (scripts/plot_osm_entries.py)
#   modeldoc_grid_check HVDC GW km and AC circuit km, uncorrected and corrected, against project and published metrics (scripts/plot_grid_check.py);
#                       its inputs build/grid_check/* come from ../scripts/check_grid.py, run by hand (read-only, about 10 min, no model rerun)
#   modeldoc_circuits   real ways hit by the circuit defect, without and with fix_indirect_circuits (scripts/table_circuits.py -> build/circuit_ways.tex)
#   modeldoc_isolated   the AC sub-networks of IN, CN, NWE and what simplify_network does with them, recomputed from
#                       networks/<R>-now/elec.nc (scripts/plot_isolated.py); build/isolated_fates.csv = sub-networks per fate
#   modeldoc_fleet_tables  plant list against the capacity statistic, and Ember rows too small for their generation
#                       (scripts/table_fleet.py -> build/fleet_{groups,ember}.tex)
#   modeldoc_fleet_check   capacity and fleet efficiency against national statistics (scripts/plot_fleet_check.py); the inputs
#                       of both, build/fleet_check/*, come from ../scripts/check_fleet.py, run by hand (read-only, 10 s, no model rerun)
#   modeldoc_pdf        latexmk over doc/main.tex -> build/model_doc.pdf
#
# Paths are relative to this file's directory, like assumptions.smk, so the file can later be included in the fork.

import os
from glob import glob

HERE = os.path.relpath(str(workflow.current_basedir), os.getcwd())


def P(*parts):
    return os.path.normpath(os.path.join(HERE, *parts))


DOC = P("doc")
BUILD = P("build")
FIG = os.path.join(BUILD, "figures")
FORK = P("../../models/pypsa-earth")
TA = P("../technology-assumptions")
COUNTRIES = P("../../misc-quarter1/country-classification/data/ne_50m_admin_0_countries/ne_50m_admin_0_countries.shp")


rule modeldoc_all:
    input:
        os.path.join(BUILD, "model_doc.pdf"),


rule modeldoc_coverage:
    input:
        row_countries=P("../data/row_countries.csv"),
        configs=sorted(glob(P("../config.*.yaml"))),
        countries=COUNTRIES,
        helper=P("scripts/plot_grid_map.py"),
    output:
        os.path.join(FIG, "coverage.pdf"),
    resources:
        mem_mb=1000,
    script:
        "scripts/plot_coverage.py"


rule modeldoc_layers:
    input:
        network=os.path.join(FORK, "networks/BR/base.nc"),
        shape=os.path.join(FORK, "resources/BR/shapes/country_shapes.geojson"),
        plants=os.path.join(FORK, "resources/BR-now/powerplants.csv"),
        demand=os.path.join(FORK, "resources/BR-now/demand_profiles.csv"),
        cf=os.path.join(TA, "data/resource_cf_2011.nc"),
        csv=os.path.join(TA, "technology_assumptions.csv"),
    output:
        os.path.join(FIG, "layers.pdf"),
    resources:
        mem_mb=1500,
    script:
        "scripts/plot_layers.py"


rule modeldoc_grid_map:
    input:
        row_countries=P("../data/row_countries.csv"),
        configs=sorted(glob(P("../config.*.yaml"))),
        countries=COUNTRIES,
    output:
        map=os.path.join(FIG, "grid_map.pdf"),
        table=os.path.join(BUILD, "grid_classes.csv"),
    resources:
        mem_mb=1000,
    script:
        "scripts/plot_grid_map.py"


rule modeldoc_grid_steps:
    input:
        raw_lines=os.path.join(FORK, "resources/BR/osm/raw/all_raw_lines.csv"),
        raw_cables=os.path.join(FORK, "resources/BR/osm/raw/all_raw_cables.csv"),
        base=os.path.join(FORK, "networks/BR/base.nc"),
        clustered=os.path.join(FORK, "networks/BR-now/elec_s_50.nc"),
        regions=os.path.join(FORK, "resources/BR-now/bus_regions/regions_onshore_elec_s_50.geojson"),
        shape=os.path.join(FORK, "resources/BR/shapes/country_shapes.geojson"),
        raw_substations=os.path.join(FORK, "resources/BR/osm/raw/all_raw_substations.csv"),
    output:
        os.path.join(FIG, "grid_steps.pdf"),
    params:
        tiles=os.path.join(BUILD, "osm_tiles"),   # OSM map tiles of the close-ups, fetched once (network) and cached
    resources:
        mem_mb=2000,
    script:
        "scripts/plot_grid_steps.py"


rule modeldoc_hvdc_check:
    input:
        projects=P("../data/hvdc/hvdc_projects.csv"),
        countries=COUNTRIES,
        borders=os.path.join(BUILD, "grid_check/borders_NWE.csv"),
        networks=[os.path.join(FORK, f"networks/{r}/base.nc") for r in ["US", "BR", "IN", "CN", "NWE"]],
    output:
        fig=os.path.join(FIG, "hvdc_check.pdf"),
        table=os.path.join(BUILD, "hvdc_check.csv"),
    resources:
        mem_mb=2000,
    script:
        "scripts/plot_hvdc_check.py"


rule modeldoc_osm_entries:
    input:
        raw=os.path.join(FORK, "resources/CN/osm/raw/all_raw_lines.csv"),
        countries=COUNTRIES,
    output:
        os.path.join(FIG, "osm_entries.pdf"),
    resources:
        mem_mb=2000,
    script:
        "scripts/plot_osm_entries.py"


rule modeldoc_grid_check:
    input:
        summary=os.path.join(BUILD, "grid_check/summary.csv"),
        ac=os.path.join(BUILD, "grid_check/ac_summary.csv"),
    output:
        os.path.join(FIG, "grid_check.pdf"),
    resources:
        mem_mb=1000,
    script:
        "scripts/plot_grid_check.py"


rule modeldoc_isolated:
    input:
        networks=[os.path.join(FORK, f"networks/{r}-now/elec.nc") for r in ["IN", "CN", "NWE"]],
        shapes=[os.path.join(FORK, f"resources/{r}/shapes/country_shapes.geojson") for r in ["IN", "CN", "NWE"]],
    output:
        fig=os.path.join(FIG, "isolated.pdf"),
        table=os.path.join(BUILD, "isolated_fates.csv"),
    resources:
        mem_mb=4000,
    script:
        "scripts/plot_isolated.py"


rule modeldoc_circuits:
    input:
        raw=[os.path.join(FORK, f"resources/{r}/osm/raw/all_raw_{k}.csv") for r in ["US", "NWE"] for k in ["lines", "cables"]],
        networks=[os.path.join(FORK, f"resources/{r}/base_network/all_lines_build_network.csv") for r in ["US", "NWE"]],
    output:
        tex=os.path.join(BUILD, "circuit_ways.tex"),
        csv=os.path.join(BUILD, "circuit_ways.csv"),
    resources:
        mem_mb=4000,
    script:
        "scripts/table_circuits.py"


rule modeldoc_fleet_tables:
    input:
        groups=os.path.join(BUILD, "fleet_check/groups.csv"),
        ember=os.path.join(BUILD, "fleet_check/ember_rows.csv"),
    output:
        groups=os.path.join(BUILD, "fleet_groups.tex"),
        ember=os.path.join(BUILD, "fleet_ember.tex"),
    resources:
        mem_mb=500,
    script:
        "scripts/table_fleet.py"


rule modeldoc_fleet_check:
    input:
        national=os.path.join(BUILD, "fleet_check/national.csv"),
        efficiency=os.path.join(BUILD, "fleet_check/efficiency.csv"),
    output:
        os.path.join(FIG, "fleet_check.pdf"),
    resources:
        mem_mb=1000,
    script:
        "scripts/plot_fleet_check.py"


rule modeldoc_pdf:
    input:
        circuits=os.path.join(BUILD, "circuit_ways.tex"),
        fleet=[os.path.join(BUILD, f) for f in ["fleet_groups.tex", "fleet_ember.tex"]],
        tex=os.path.join(DOC, "main.tex"),
        bib=os.path.join(DOC, "references.bib"),
        sections=sorted(glob(os.path.join(DOC, "sections", "*.tex"))),
        figures=[os.path.join(FIG, f) for f in ["coverage.pdf", "layers.pdf", "grid_map.pdf", "grid_steps.pdf", "hvdc_check.pdf", "osm_entries.pdf", "grid_check.pdf", "isolated.pdf", "fleet_check.pdf"]],
    output:
        os.path.join(BUILD, "model_doc.pdf"),
    params:
        doc=DOC,
    resources:
        mem_mb=1000,
    shell:
        "cd {params.doc} && latexmk -pdf -interaction=nonstopmode -halt-on-error "
        "-outdir=../build -jobname=model_doc main.tex > ../build/latexmk.out 2>&1 "
        "|| (tail -40 ../build/latexmk.out; exit 1)"
