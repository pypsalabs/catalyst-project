# Compile the kickoff slides. Everything the deck needs is in this directory:
# figures/ holds the 16:9 renders from ../tech/figures/slides (cost baseline)
# and the priam-myopic learning-curve plot; screenshots/ the map and archetype
# images. Copy fresh figures in by hand when those workflows change.
#
# Run from this directory (needs snakemake, latexmk, biber and the TeX packages
# listed in README.md on PATH), e.g. with the priam-myopic pixi env:
#   ../../../models/priam-myopic/.pixi/envs/default/bin/snakemake -c1

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
        screenshots=expand("screenshots/{f}.png", f=["map_screenshot", "archetypes", "shares"]),
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
