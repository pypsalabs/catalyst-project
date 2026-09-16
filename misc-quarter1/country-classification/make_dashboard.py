"""Embed country_features.csv into dashboard_template.html.

Produces country_atlas.html — fully self-contained, works offline.

Run via `snakemake -c1` (rule dashboard) or standalone:
  models/priam-myopic/.pixi/envs/default/bin/python make_dashboard.py
"""

import datetime
import json
from pathlib import Path

import pandas as pd

if "snakemake" in globals():
    FEATURES = Path(snakemake.input.features)
    TEMPLATE = Path(snakemake.input.template)
    OUT = Path(snakemake.output[0])
else:
    _HERE = Path(__file__).parent
    FEATURES = _HERE / "country_features.csv"
    TEMPLATE = _HERE / "dashboard_template.html"
    OUT = _HERE / "country_atlas.html"

df = pd.read_csv(FEATURES)
# NaN -> null so the JS can test with == null
records = json.loads(df.to_json(orient="records"))

html = TEMPLATE.read_text()
html = html.replace("__DATA__", json.dumps(records, separators=(",", ":")))
html = html.replace("__DATE__", datetime.date.today().isoformat())

OUT.write_text(html)
print(f"{OUT} ({OUT.stat().st_size / 1e6:.2f} MB, {len(records)} countries)")
