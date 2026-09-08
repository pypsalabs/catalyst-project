# Compile the kickoff slides. Everything the deck needs is in this directory:
# figures/ holds the 16:9 renders from ../tech/figures/slides (cost baseline)
# and the priam-myopic learning-curve plot; copy fresh figures in by hand when
# those workflows change. screenshots/ holds the map and archetype images,
# rendered here from ../land-grid-map by ../screenshot_map.py (headless
# Chrome) whenever the page or its data changes, so `snakemake -c1` alone
# brings the slides up to date with the front-end.
#
# Run from this directory (needs snakemake, latexmk, biber and the TeX packages
# listed in README.md on PATH), e.g. with the priam-myopic pixi env:
#   ../../../models/priam-myopic/.pixi/envs/default/bin/snakemake -c1

import sys
from glob import glob

SCREENSHOTS = ["map_screenshot", "archetypes", "shares", "tsne"]   # names in ../screenshot_map.py SHOTS
FIGURES = ["capex_generation_mature", "capex_generation_advanced",
           "capex_storage_mature", "capex_storage_advanced", "learning_curve"]


rule all:
    input:
        "slides.pdf",


rule slides:
    input:
        tex="slides.tex",
        bib="slides.bib",
        theme=["beamerthemePyPSALabs.sty", "beamercolorthemePyPSALabs.sty", "logo.png", "google_logo.png"],
        screenshots=expand("screenshots/{f}.png", f=SCREENSHOTS),
        figures=expand("figures/{f}.pdf", f=FIGURES),
        references=["references.tex", "refnums.tex"],
    output:
        "slides.pdf",
    resources:
        mem_mb=1000, runtime="10m",
    shell:
        "latexmk -pdf -interaction=nonstopmode -halt-on-error {input.tex} > latexmk.out 2>&1 "
        "|| (tail -40 latexmk.out; exit 1)"


rule references:
    input:
        "references.yaml",
    output:
        list="references.tex",
        nums="refnums.tex",
    script:
        "make_references.py"


# map, archetype list and share bars as shown on the land grid map page; needs google-chrome
# (or CHROME=...) and network access for the basemap tiles
rule screenshots:
    input:
        script="../screenshot_map.py",
        page="../land-grid-map/index.html",
        data=["../land-grid-map/data/archetypes.js", "../land-grid-map/data/regions.js"]
             + sorted(glob("../land-grid-map/data/layers/*.js")),
    output:
        expand("screenshots/{f}.png", f=SCREENSHOTS),
    resources:
        mem_mb=2000, runtime="10m",
    shell:
        "{sys.executable} {input.script} screenshots " + " ".join(SCREENSHOTS)
