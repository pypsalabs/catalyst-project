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
#   modeldoc_loadability  circuit length and the loadability limit of long AC circuits in the six spatially resolved regions,
#                       four figures of one script (scripts/plot_loadability.py): line_lengths (capacity between clusters by
#                       circuit length, one row per region), loadability_curve (St. Clair curve; loadable share per line),
#                       loadability_map (the clustered networks by usable share), loadability_check (limits per GW of peak
#                       load; model over published transfer capacity across borders); its inputs build/loadability/* come
#                       from ../scripts/check_loadability.py, run by hand (read-only, 3 min, no model rerun)
#   modeldoc_grid_expansion  the cap on grid build-out per region against delivered growth and plans (scripts/plot_grid_expansion.py,
#                       from ../data/grid_expansion/*.csv; also writes build/grid_expansion.tex, the rows of the table of rates)
#   modeldoc_demand_placement  demand per province of China, model over published, before and after the provincial shares
#                       (scripts/plot_demand_placement.py); its inputs build/demand_placement/CN_{before,after}.csv come from
#                       ../scripts/check_demand_placement.py, run by hand on the China run before and after (read-only)
#   modeldoc_circuits   real ways hit by the circuit defect, without and with fix_indirect_circuits (scripts/table_circuits.py -> build/circuit_ways.tex)
#   modeldoc_isolated   the AC sub-networks of IN, CN, NWE and what simplify_network does with them, recomputed from
#                       networks/<R>-now/elec.nc (scripts/plot_isolated.py); build/isolated_fates.csv = sub-networks per fate
#   modeldoc_fleet_tables  plant list against the capacity statistic, and Ember rows too small for their generation
#                       (scripts/table_fleet.py -> build/fleet_{groups,ember}.tex)
#   modeldoc_fleet_check   capacity and fleet efficiency against national statistics (scripts/plot_fleet_check.py); the inputs
#                       of both, build/fleet_check/*, come from ../scripts/check_fleet.py, run by hand (read-only, 1 min, no model rerun)
#   modeldoc_fleet_map  world map of the statistic over the plant list per country (scripts/plot_fleet_map.py; build/fleet_check/world.csv)
#   modeldoc_fleet_sources  the matched plant list by fuel and reporting databases, and the fields it fills
#                       (scripts/plot_fleet_sources.py; build/fleet_check/{sources,fields}.csv)
#   modeldoc_fleet_vintage  commissioning years of the five regions' `now` plant lists (scripts/plot_fleet_vintage.py)
#   modeldoc_fleet_dropped  US coal and gas plants, kept and dropped by filled retirement dates (scripts/plot_fleet_dropped.py)
#   modeldoc_fleet_merit    Germany's thermal merit order, standard procedure against the solved `now` network (scripts/plot_fleet_merit.py)
#   modeldoc_fleet_envelope minimum and maximum output of the existing fleet per country (scripts/plot_fleet_envelope.py)
#   modeldoc_fleet_retirements  the 2024 fleet in operation 2024-2050, with the cost table's and with powerplantmatching's lifetimes
#                       (scripts/plot_fleet_retirements.py; build/fleet_check/retirements.csv)
#   modeldoc_fleet_efficiency  fuel burnt per MWh of electricity, PyPSA-Earth v0.9.0 against the fleet efficiencies
#                       (scripts/plot_fleet_efficiency.py; calibration tables only)
#   modeldoc_mix_before_after  2024 electricity mix per country, Ember against out-of-the-box v0.9.0 (scripts/plot_mix_before_after.py;
#                       the validation_world.csv tables of the baseline worktree and of the fork, no network read)
#   modeldoc_renew_*    Renewables & Weather: installed capacity of the largest fleets (fleet), world maps of the model
#                       over the observed capacity factor (map), the cutout boxes (cutouts), land cover and land
#                       eligibility of a region of north-east Scotland (eligibility), the standard procedure for the
#                       onshore wind of north-west Europe (steps), one week of hourly profiles at a few buses (timeseries), plant list / IRENA / network (capacity), model against observed capacity
#                       factor (cf), resource classes (classes); all but `timeseries` read build/renewables_check/*, written
#                       by ../scripts/check_renewables.py, run by hand (read-only, a few minutes, no model rerun; the
#                       eligibility table only on request: `check_renewables.py eligibility`)
#   modeldoc_cfe_*      Demand for 24/7 CFE: data centres by region (datacentres), RE100 members and corporate buyers
#                       (buyers), world map of the buyers' share in 2030 (share_map), its parts and path in the modelled
#                       regions (share_regions), the table per country (table -> build/cfe_share.tex); they read the topic
#                       directory misc-quarter1/datacentre-demand (build it first: its Snakefile, then `model_tables`)
#                       and calibration/<year>/cfe_share.csv
#   modeldoc_yaml       the options the document quotes, cut out of the config files as YAML code blocks
#                       (scripts/yaml_snippets.py -> build/yaml/<name>.yaml, \\yamlblock in doc/main.tex)
#   modeldoc_commit_stats  lines added / removed per cited fork commit, printed by \commit (scripts/commit_stats.py
#                       -> build/commit_stats.tex); reruns when a section changes
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
CFE = P("../../misc-quarter1/datacentre-demand")   # evidence for the 24/7 CFE buyers' share; build it there first (its Snakefile)
CFE_YEARS = [2030, 2035, 2040, 2045, 2050]


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
        uncorrected=[os.path.join(FORK, f"results/archive/{r}-now-20261020/networks/elec_s_50_ec_lcopt_3h.nc") for r in ["US", "BR", "IN", "CN", "NWE"]],
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


LOADABILITY_REGIONS = ["USW", "USE", "BR", "IN", "CN", "NWE"]


rule modeldoc_loadability:
    input:
        summary=os.path.join(BUILD, "loadability/summary.csv"),
        tables=[os.path.join(BUILD, "loadability", f) for f in ["curve.csv", "transfer.csv"]
                + [f"{k}_{r}.csv" for k in ["lines", "circuits"] for r in LOADABILITY_REGIONS]],
        shapes=[os.path.join(FORK, f"resources/{r}/shapes/country_shapes.geojson") for r in LOADABILITY_REGIONS],
    output:
        os.path.join(FIG, "{figure}.pdf"),
    wildcard_constraints:
        figure="line_lengths|loadability_curve|loadability_map|loadability_check",
    params:
        figure=lambda w: "lengths" if w.figure == "line_lengths" else w.figure.replace("loadability_", ""),
    resources:
        mem_mb=1000,
    script:
        "scripts/plot_loadability.py"


rule modeldoc_grid_expansion:
    input:
        rates=P("../data/grid_expansion/grid_expansion.csv"),
        published=P("../data/grid_expansion/published.csv"),
    output:
        figure=os.path.join(FIG, "grid_expansion.pdf"),
        table=os.path.join(BUILD, "grid_expansion.tex"),
    resources:
        mem_mb=500,
    script:
        "scripts/plot_grid_expansion.py"


rule modeldoc_demand_placement:
    input:
        before=os.path.join(BUILD, "demand_placement/CN_before.csv"),
        after=os.path.join(BUILD, "demand_placement/CN_after.csv"),
    output:
        os.path.join(FIG, "demand_placement.pdf"),
    resources:
        mem_mb=500,
    script:
        "scripts/plot_demand_placement.py"


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
        spread=P("../data/validation/efficiency_spread.csv"),
    output:
        groups=os.path.join(BUILD, "fleet_groups.tex"),
        ember=os.path.join(BUILD, "fleet_ember.tex"),
        spread=os.path.join(BUILD, "fleet_spread.tex"),
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


rule modeldoc_fleet_map:
    input:
        world=os.path.join(BUILD, "fleet_check/world.csv"),
        row_countries=P("../data/row_countries.csv"),
        configs=sorted(glob(P("../config.*.yaml"))),
        countries=COUNTRIES,
        helper=P("scripts/plot_grid_map.py"),
    output:
        os.path.join(FIG, "fleet_map.pdf"),
    resources:
        mem_mb=1000,
    script:
        "scripts/plot_fleet_map.py"


rule modeldoc_fleet_sources:
    input:
        sources=os.path.join(BUILD, "fleet_check/sources.csv"),
        fields=os.path.join(BUILD, "fleet_check/fields.csv"),
    output:
        os.path.join(FIG, "fleet_sources.pdf"),
    resources:
        mem_mb=500,
    script:
        "scripts/plot_fleet_sources.py"


rule modeldoc_fleet_vintage:
    input:
        plants=[os.path.join(FORK, f"resources/{r}-now/powerplants.csv") for r in ["US", "CN", "IN", "NWE", "BR"]],
    output:
        os.path.join(FIG, "fleet_vintage.pdf"),
    resources:
        mem_mb=1000,
    script:
        "scripts/plot_fleet_vintage.py"


rule modeldoc_fleet_dropped:
    input:
        plants=os.path.join(FORK, "resources/US-now/powerplants.csv"),
        dropped=os.path.join(BUILD, "fleet_check/dropped_US.csv"),
        shape=os.path.join(FORK, "resources/US/shapes/country_shapes.geojson"),
    output:
        os.path.join(FIG, "fleet_dropped.pdf"),
    resources:
        mem_mb=1000,
    script:
        "scripts/plot_fleet_dropped.py"


rule modeldoc_fleet_merit:
    input:
        network=os.path.join(FORK, "results/NWE-now/networks/elec_s_50_ec_lcopt_3h.nc"),
        costs=os.path.join(FORK, "resources/NWE-now/costs_2025_elec.csv"),
    output:
        os.path.join(FIG, "fleet_merit.pdf"),
    resources:
        mem_mb=2000,
    script:
        "scripts/plot_fleet_merit.py"


rule modeldoc_fleet_envelope:
    input:
        tables=sorted(glob(P("../calibration/2024/envelope/floor/*.csv"))),
        capacity=P("../calibration/2024/capacity.csv"),
        row_countries=P("../data/row_countries.csv"),
    output:
        os.path.join(FIG, "fleet_envelope.pdf"),
    resources:
        mem_mb=500,
    script:
        "scripts/plot_fleet_envelope.py"


rule modeldoc_fleet_retirements:
    input:
        os.path.join(BUILD, "fleet_check/retirements.csv"),
    output:
        os.path.join(FIG, "fleet_retirements.pdf"),
    resources:
        mem_mb=500,
    script:
        "scripts/plot_fleet_retirements.py"


rule modeldoc_fleet_efficiency:
    input:
        efficiency=P("../calibration/2024/efficiency.csv"),
        generation=P("../calibration/2024/generation.csv"),
        capacity=P("../calibration/2024/capacity.csv"),
        costs=os.path.join(FORK, "resources/US-now/costs_2025.csv"),
        row_countries=P("../data/row_countries.csv"),
        world=os.path.join(BUILD, "fleet_check/world.csv"),
    output:
        os.path.join(FIG, "fleet_efficiency.pdf"),
    resources:
        mem_mb=500,
    script:
        "scripts/plot_fleet_efficiency.py"


rule modeldoc_mix_before_after:
    input:
        before=P("../../models/pypsa-earth-baseline/results/catalyst/validation_world.csv"),
        after=os.path.join(FORK, "results/catalyst/validation_world.csv"),
    output:
        os.path.join(FIG, "mix_before_after.pdf"),
    resources:
        mem_mb=500,
    script:
        "scripts/plot_mix_before_after.py"

YAML_SNIPPETS = ["gas_mapping", "plant_statistics", "plant_efficiency", "envelope", "tranches", "retirements",
                 "drop_duplicate_ids", "fix_indirect_circuits", "geodesic_length", "dc_ratings", "dc_projects", "isolated", "loadability", "demand_shares", "time_shift",
                 "clip_bbox", "excluder_resolution", "renewable_capacities", "cf_targets", "cluster_weight", "resource_classes"]


rule modeldoc_yaml:
    input:
        P("../statistics.yaml"),
        [P(f"../overlay.{s}.yaml") for s in ["now", "zero", "myopic"]],
        [P(f"../config.{r}.yaml") for r in ["USW", "USE", "BR", "IN", "CN", "NWE", "EUR"]],
    output:
        [os.path.join(BUILD, "yaml", f"{n}.yaml") for n in YAML_SNIPPETS],
    params:
        configs=P(".."),
    resources:
        mem_mb=200,
    script:
        "scripts/yaml_snippets.py"


rule modeldoc_commit_stats:
    input:
        sections=sorted(glob(os.path.join(DOC, "sections", "*.tex"))),
    output:
        os.path.join(BUILD, "commit_stats.tex"),
    params:
        repo=FORK,
    resources:
        mem_mb=200,
    script:
        "scripts/commit_stats.py"


rule modeldoc_renew_fleet:
    input:
        capacity=os.path.join(BUILD, "renewables_check/capacity.csv"),
    output:
        os.path.join(FIG, "renew_fleet.pdf"),
    resources:
        mem_mb=500,
    script:
        "scripts/plot_renew_fleet.py"


rule modeldoc_renew_cutouts:
    input:
        cutouts=os.path.join(BUILD, "renewables_check/cutouts.csv"),
        row_countries=P("../data/row_countries.csv"),
        configs=sorted(glob(P("../config.*.yaml"))),
        countries=COUNTRIES,
        helper=P("scripts/plot_grid_map.py"),
    output:
        os.path.join(FIG, "renew_cutouts.pdf"),
    resources:
        mem_mb=1000,
    script:
        "scripts/plot_renew_cutouts.py"


rule modeldoc_renew_eligibility:
    input:
        eligibility=os.path.join(BUILD, "renewables_check/eligibility_NWE.npz"),
        config=os.path.join(FORK, "config.default.yaml"),
    output:
        os.path.join(FIG, "renew_eligibility.pdf"),
    resources:
        mem_mb=1500,
    script:
        "scripts/plot_renew_eligibility.py"


rule modeldoc_renew_map:
    input:
        cf=os.path.join(BUILD, "renewables_check/cf.csv"),
        row_countries=P("../data/row_countries.csv"),
        configs=sorted(glob(P("../config.*.yaml"))),
        countries=COUNTRIES,
        helper=P("scripts/plot_grid_map.py"),
    output:
        os.path.join(FIG, "renew_map.pdf"),
    resources:
        mem_mb=1500,
    script:
        "scripts/plot_renew_map.py"


rule modeldoc_renew_steps:
    input:
        profile=os.path.join(FORK, "resources/NWE/renewable_profiles/profile_onwind.nc"),
        cells=os.path.join(FORK, "resources/NWE/renewable_profiles/cells_onwind.nc"),
        base=os.path.join(FORK, "networks/NWE/base.nc"),
        shape=os.path.join(FORK, "resources/NWE/shapes/country_shapes.geojson"),
        eligibility=os.path.join(BUILD, "renewables_check/eligibility_NWE.npz"),
    output:
        os.path.join(FIG, "renew_steps.pdf"),
    resources:
        mem_mb=2000,
    script:
        "scripts/plot_renew_steps.py"


rule modeldoc_renew_timeseries:
    input:
        profiles=[os.path.join(FORK, f"resources/{r}/renewable_profiles/profile_{c}.nc")
                  for r in ["US", "BR", "NWE", "CN"] for c in ["solar", "onwind", "offwind-ac"]],
        base=[os.path.join(FORK, f"networks/{r}/base.nc") for r in ["US", "BR", "NWE", "CN"]],
    output:
        os.path.join(FIG, "renew_timeseries.pdf"),
    params:
        fork=FORK,
    resources:
        mem_mb=3000,
    script:
        "scripts/plot_renew_timeseries.py"


rule modeldoc_renew_capacity:
    input:
        capacity=os.path.join(BUILD, "renewables_check/capacity.csv"),
    output:
        os.path.join(FIG, "renew_capacity.pdf"),
    resources:
        mem_mb=500,
    script:
        "scripts/plot_renew_capacity.py"


rule modeldoc_renew_cf:
    input:
        cf=os.path.join(BUILD, "renewables_check/cf.csv"),
    output:
        os.path.join(FIG, "renew_cf.pdf"),
    resources:
        mem_mb=500,
    script:
        "scripts/plot_renew_cf.py"


rule modeldoc_renew_classes:
    input:
        classes=os.path.join(BUILD, "renewables_check/classes.csv"),
    output:
        os.path.join(FIG, "renew_classes.pdf"),
    resources:
        mem_mb=500,
    script:
        "scripts/plot_renew_classes.py"


rule modeldoc_cfe_datacentres:
    input:
        series=os.path.join(CFE, "build/series_trend.csv"),
        outlooks=os.path.join(CFE, "data/outlooks.csv"),
    output:
        os.path.join(FIG, "cfe_datacentres.pdf"),
    resources:
        mem_mb=500,
    script:
        "scripts/plot_cfe_datacentres.py"


rule modeldoc_cfe_buyers:
    input:
        stack=os.path.join(CFE, "build/buyers_stack.csv"),
        share=os.path.join(CFE, "build/buyers_share.csv"),
        config=os.path.join(CFE, "config.yaml"),
        helper=P("scripts/plot_cfe_datacentres.py"),
    output:
        os.path.join(FIG, "cfe_buyers.pdf"),
    resources:
        mem_mb=500,
    script:
        "scripts/plot_cfe_buyers.py"


rule modeldoc_cfe_share_map:
    input:
        share=P("../calibration/2030/cfe_share.csv"),
        row_countries=P("../data/row_countries.csv"),
        configs=sorted(glob(P("../config.*.yaml"))),
        countries=COUNTRIES,
        helper=P("scripts/plot_grid_map.py"),
    output:
        os.path.join(FIG, "cfe_share_map.pdf"),
    resources:
        mem_mb=1000,
    script:
        "scripts/plot_cfe_share_map.py"


rule modeldoc_cfe_share_regions:
    input:
        tables=[P(f"../calibration/{y}/cfe_share.csv") for y in CFE_YEARS],
        demand=[P(f"../calibration/{y}/demand.csv") for y in CFE_YEARS],
        names=P("../data/row_countries.csv"),
        helper=P("scripts/plot_cfe_datacentres.py"),
    output:
        os.path.join(FIG, "cfe_share_regions.pdf"),
    resources:
        mem_mb=500,
    script:
        "scripts/plot_cfe_share_regions.py"


rule modeldoc_cfe_table:
    input:
        share=os.path.join(CFE, "build/country_share.csv"),
        sources=os.path.join(CFE, "data/datacentre_countries.csv"),
        names=P("../data/row_countries.csv"),
    output:
        os.path.join(BUILD, "cfe_share.tex"),
    resources:
        mem_mb=500,
    script:
        "scripts/table_cfe_share.py"


rule modeldoc_pdf:
    input:
        circuits=os.path.join(BUILD, "circuit_ways.tex"),
        commits=os.path.join(BUILD, "commit_stats.tex"),
        yaml=rules.modeldoc_yaml.output,
        fleet=[os.path.join(BUILD, f) for f in ["fleet_groups.tex", "fleet_ember.tex", "fleet_spread.tex"]],
        tex=os.path.join(DOC, "main.tex"),
        bib=os.path.join(DOC, "references.bib"),
        sections=sorted(glob(os.path.join(DOC, "sections", "*.tex"))),
        figures=[os.path.join(FIG, f) for f in ["coverage.pdf", "layers.pdf", "grid_map.pdf", "grid_steps.pdf", "hvdc_check.pdf", "osm_entries.pdf", "grid_check.pdf", "isolated.pdf", "line_lengths.pdf", "loadability_curve.pdf", "loadability_map.pdf", "loadability_check.pdf", "fleet_check.pdf",
                                                   "fleet_map.pdf", "fleet_sources.pdf", "fleet_vintage.pdf", "fleet_dropped.pdf",
                                                   "fleet_merit.pdf", "fleet_envelope.pdf", "fleet_retirements.pdf", "fleet_efficiency.pdf", "mix_before_after.pdf",
                                                   "renew_fleet.pdf", "renew_map.pdf", "renew_cutouts.pdf", "renew_eligibility.pdf", "renew_steps.pdf", "renew_timeseries.pdf",
                                                   "renew_capacity.pdf", "renew_cf.pdf", "renew_classes.pdf",
                                                   "cfe_datacentres.pdf", "cfe_buyers.pdf", "cfe_share_map.pdf", "cfe_share_regions.pdf"]],
        cfe=os.path.join(BUILD, "cfe_share.tex"),
        demand=os.path.join(FIG, "demand_placement.pdf"),
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
