"""Snakemake script: one site x weather year -> build/runs/<site>/<year>.csv (misc-quarter1/toymodel-clean-procurement).

Standalone: python run_site_year.py <site key> <year> [out.csv]
"""

import logging
import sys
from pathlib import Path

from build_network import run
from techs import load_config

logging.basicConfig(level=logging.INFO, format="%(message)s")
if "snakemake" in globals():
    cfg = load_config(Path(snakemake.input.config))  # noqa: F821
    site, year, out = snakemake.wildcards.site, int(snakemake.wildcards.year), Path(snakemake.output[0])  # noqa: F821
else:
    cfg = load_config()
    site, year = sys.argv[1], int(sys.argv[2])
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(__file__).resolve().parent / "build" / "runs" / site / f"{year}.csv"
out.parent.mkdir(parents=True, exist_ok=True)
run(cfg, site, year).to_csv(out, index=False, float_format="%.6g")
logging.getLogger("run").info("wrote %s", out)
