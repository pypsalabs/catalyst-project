# Technology assumptions of the Catalyst model: technology_assumptions.csv -> page-1 tables ->
# justification document build/technology_assumptions.pdf.
#
# One file, two ways to run:
#   standalone, from this directory (any env with snakemake + pandas; latexmk, biber, kpfonts on PATH):
#     ../../models/priam-myopic/.pixi/envs/default/bin/snakemake -s assumptions.smk -c1
#   inside the pypsa-earth fork: merge_config.py adds this file to `custom_rules` of every stage, and
#     `bash config-pypsa-earth/run.sh assumptions` builds the PDF (target relative to the fork root:
#     ../../config-pypsa-earth/technology-assumptions/build/technology_assumptions.pdf)
#
# rules
#   assumptions_table   CSV -> build/table.tex (scripts/build_table.py; warns when a section file is missing
#                       or its hand-typed title CAPEX differs from the CSV)
#   assumptions_resource_cf    weather octants (models/octants, ERA5 2011, ~7 GB) -> data/resource_cf_2011.nc, the
#                       annual mean capacity factor of solar and onshore wind on a 0.5 degree grid (~1.4 MB, kept
#                       in the repo so the document builds without the octants; 3 min)
#   assumptions_offshore_mask  GEBCO 2025 bathymetry of the fork (7 GB) -> data/offwind_shallow_share.nc, the share of
#                       each 0.5 degree cell 0-50 m deep (kept in the repo like the capacity factors; 25 s)
#   assumptions_resource_maps  those grids + the CSV -> build/figures/{solar-utility,onwind,offwind}_{cf,lcoe}.pdf, the
#                       capacity factor and LCOE world maps of the solar, onshore and offshore wind sections
#                       (offshore: the onshore octant's wind over shallow sea, a proxy)
#   assumptions_doc     latexmk over doc/main.tex -> build/technology_assumptions.pdf
#
# Paths are relative to Snakemake's working directory ("." standalone, the fork root when included), so
# they are derived from the location of this file at parse time. `script:` paths are relative to this
# file as always. Keep the parse-time code light: every fork stage parses this file.

import os
from glob import glob

HERE = os.path.relpath(str(workflow.current_basedir), os.getcwd())   # str(): works for snakemake 7 and 9


def P(*parts):   # path under this directory, without a leading "./" (snakemake 9 warns about it)
    return os.path.normpath(os.path.join(HERE, *parts))


DOC = P("doc")
BUILD = P("build")
OCTANTS = P("../../models/octants")
WEATHER_YEAR = 2011
RESOURCE_CF = P(f"data/resource_cf_{WEATHER_YEAR}.nc")
MAPS = [os.path.join(BUILD, "figures", f"{tech}_{kind}.pdf") for tech in ["solar-utility", "onwind", "offwind"] for kind in ["cf", "lcoe"]]
GEBCO = P("../../models/pypsa-earth/data/gebco/GEBCO_2025_sub_ice.nc")
SHALLOW = P("data/offwind_shallow_share.nc")


rule assumptions_all:   # standalone default target; the fork keeps its own default when this file is included
    input:
        os.path.join(BUILD, "technology_assumptions.pdf"),


rule assumptions_table:
    input:
        csv=P("technology_assumptions.csv"),
    output:
        tex=os.path.join(BUILD, "table.tex"),
    params:
        sections=os.path.join(DOC, "sections"),
    log:
        os.path.join(BUILD, "build_table.log"),
    resources:
        mem_mb=500,
    script:
        "scripts/build_table.py"


rule assumptions_resource_cf:
    input:
        [os.path.join(OCTANTS, f"octant-{WEATHER_YEAR}-{q}-{h}-{t}.nc") for t in ["solar", "onwind"] for q in range(4) for h in range(2)],
    output:
        RESOURCE_CF,
    params:
        octants=OCTANTS,
        year=WEATHER_YEAR,
    resources:
        mem_mb=2000,
    script:
        "scripts/build_resource_cf.py"


rule assumptions_offshore_mask:
    input:
        GEBCO,
    output:
        SHALLOW,
    params:
        max_depth=50,   # the fork's offwind-ac/dc max_depth
    resources:
        mem_mb=1000,
    script:
        "scripts/build_offshore_mask.py"


rule assumptions_resource_maps:
    input:
        cf=RESOURCE_CF,
        shallow=SHALLOW,
        csv=P("technology_assumptions.csv"),
        countries=P("../../misc-quarter1/country-classification/data/ne_50m_admin_0_countries/ne_50m_admin_0_countries.shp"),
    output:
        MAPS,
    resources:
        mem_mb=1500,
    script:
        "scripts/plot_resource_maps.py"


rule assumptions_doc:
    input:
        tex=os.path.join(DOC, "main.tex"),
        table=os.path.join(BUILD, "table.tex"),
        maps=MAPS,
        bib=os.path.join(DOC, "references.bib"),
        sections=sorted(glob(os.path.join(DOC, "sections", "*.tex"))),
        figures=sorted(glob(os.path.join(DOC, "figures", "*"))),
        icons=sorted(glob(os.path.join(DOC, "icons", "*.pdf"))),
    output:
        os.path.join(BUILD, "technology_assumptions.pdf"),
    params:
        doc=DOC,
    resources:
        mem_mb=1000,
    shell:
        "cd {params.doc} && latexmk -pdf -interaction=nonstopmode -halt-on-error "
        "-outdir=../build -jobname=technology_assumptions main.tex > ../build/latexmk.out 2>&1 "
        "|| (tail -40 ../build/latexmk.out; exit 1)"
