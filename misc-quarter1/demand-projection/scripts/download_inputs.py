"""Cache the downloaded inputs under data/.

    python scripts/download_inputs.py wdi    World Bank WDI history (GDP per capita PPP, population), needs requests
    python scripts/download_inputs.py ssp    IIASA SSP basic drivers 2025 release, SSP2, needs pyam-iamc (not in the
                                             priam-myopic env: `uv run --with pyam-iamc python scripts/download_inputs.py ssp`)

data/ssp2_basic_drivers.csv is tracked, so the workflow never needs pyam.
"""

import json
import os
import sys

from common import DATA

WDI = {"NY.GDP.PCAP.PP.KD": "GDP per capita, PPP (constant 2021 international $)", "SP.POP.TOTL": "Population, total"}


def wdi():
    import requests

    for ind in WDI:
        url = f"https://api.worldbank.org/v2/country/all/indicator/{ind}?format=json&date=2000:2024&per_page=20000"
        meta, rows = requests.get(url, timeout=120).json()
        assert meta["pages"] == 1, meta
        with open(os.path.join(DATA, f"wdi_{ind}.json"), "w") as fh:
            json.dump([meta, rows], fh)
        print(ind, len(rows), "rows, last updated", meta["lastupdated"])


def ssp():
    import pyam

    df = pyam.read_iiasa("ssp", scenario="SSP2", variable=["GDP|PPP", "Population"]).as_pandas()
    df = df[((df.model == "OECD ENV-Growth 2025") & (df.unit == "billion USD_2017/yr"))
            | (df.model == "IIASA-WiC POP 2025")]
    df = df[df.year <= 2050][["model", "scenario", "region", "variable", "unit", "year", "value"]]
    df.sort_values(["variable", "region", "year"]).to_csv(os.path.join(DATA, "ssp2_basic_drivers.csv"), index=False)
    print(df.groupby("variable").region.nunique())


if __name__ == "__main__":
    {"wdi": wdi, "ssp": ssp}[sys.argv[1]]()
