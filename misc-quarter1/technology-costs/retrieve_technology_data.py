"""Download the pinned PyPSA/technology-data 2025 cost file.

Skips the download when the target already exists and is non-empty, so the
committed copy is used offline. Change `technology_data.tag` in config.yaml to
fetch a different release (the output name carries the tag).
"""

from pathlib import Path

import requests

if "snakemake" in globals():
    OUT = Path(snakemake.output[0])
    TAG = snakemake.params.tag
    URL = snakemake.params.url
else:
    import yaml

    _HERE = Path(__file__).parent
    _cfg = yaml.safe_load((_HERE / "config.yaml").read_text())["technology_data"]
    TAG, URL = _cfg["tag"], _cfg["url"].format(tag=_cfg["tag"])
    OUT = _HERE / "data" / "technology-data" / f"costs_2025_{TAG}.csv"

OUT.parent.mkdir(parents=True, exist_ok=True)

if OUT.exists() and OUT.stat().st_size > 0:
    print(f"{OUT} present, skipping download")
else:
    url = URL
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    assert r.text.startswith("technology,parameter,value,unit"), (
        f"unexpected header from {url}: {r.text[:80]!r}")
    OUT.write_text(r.text)
    print(f"downloaded {url} -> {OUT} ({len(r.text) / 1e3:.0f} kB)")
