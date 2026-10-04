"""Shared paths and readers of the demand-projection workflow."""

import os
import re
import unicodedata

import pandas as pd
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
BUILD = os.path.join(ROOT, "build")
FIGURES = os.path.join(ROOT, "figures")

with open(os.path.join(ROOT, "config.yaml")) as fh:
    CONFIG = yaml.safe_load(fh)


def path(key):
    p = os.path.expanduser(CONFIG["paths"][key])
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(ROOT, p))


# names used by the SSP database, UNdata and the World Bank that differ from ISO 3166 short names
ALIASES = {
    "bolivia": "BOL", "bolivia plurinational state of": "BOL", "brunei": "BRN", "cape verde": "CPV",
    "china hong kong sar": "HKG", "hong kong": "HKG", "china macao sar": "MAC", "macao": "MAC", "congo": "COG",
    "democratic republic of the congo": "COD", "dem rep of the congo": "COD", "cote divoire": "CIV",
    "czech republic": "CZE", "czechia": "CZE", "iran": "IRN", "iran islamic rep of": "IRN",
    "korea republic of": "KOR", "republic of korea": "KOR", "south korea": "KOR",
    "korea dem peoples rep": "PRK", "korea dem peoples rep of": "PRK", "north korea": "PRK", "laos": "LAO",
    "lao peoples dem rep": "LAO", "micronesia": "FSM", "micronesia fed states of": "FSM", "moldova": "MDA",
    "republic of moldova": "MDA", "netherlands": "NLD", "netherlands kingdom of the": "NLD", "palestine": "PSE",
    "state of palestine": "PSE", "russia": "RUS", "russian federation": "RUS", "syria": "SYR",
    "taiwan": "TWN", "tanzania": "TZA", "united rep of tanzania": "TZA", "turkey": "TUR", "turkiye": "TUR",
    "united kingdom": "GBR", "united states": "USA", "venezuela": "VEN", "venezuela bolivar rep": "VEN",
    "venezuela bolivar rep of": "VEN", "vietnam": "VNM", "viet nam": "VNM", "swaziland": "SWZ", "eswatini": "SWZ",
    "the former yugoslav rep of macedonia": "MKD", "north macedonia": "MKD", "macedonia": "MKD",
    "st kitts nevis": "KNA", "st lucia": "LCA", "st vincent grenadines": "VCT", "bolivia plur state of": "BOL",
    "gambia": "GMB", "bahamas": "BHS", "curacao": "CUW", "reunion": "REU", "kosovo": "XKX", "niger": "NER",
    "dominican republic": "DOM", "philippines": "PHL", "sudan": "SDN", "united arab emirates": "ARE",
    "central african rep": "CAF", "central african republic": "CAF", "comoros": "COM",
}


def _norm(name):
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", s)).strip()


_iso = pd.read_csv(path("iso"), keep_default_na=False)
_BY_NAME = {_norm(n): a3 for n, a3 in zip(_iso["name"], _iso["alpha-3"])}
ISO2 = dict(zip(_iso["alpha-3"], _iso["alpha-2"]))
ISO3 = {v: k for k, v in ISO2.items()}


def iso3_of(name):
    n = _norm(name)
    return ALIASES.get(n) or _BY_NAME.get(n)


def ember_demand():
    """Annual demand (TWh) per country and year, with the Ember grouping flags."""
    cols = ["Area", "ISO 3 code", "Year", "Area type", "Continent", "EU", "ASEAN", "Category", "Variable", "Unit", "Value"]
    e = pd.read_csv(path("ember"), usecols=cols)
    d = e[(e["Area type"] == "Country or economy") & (e.Category == "Electricity demand") & (e.Variable == "Demand")
          & (e.Unit == "TWh")].dropna(subset=["Value"])
    return d.rename(columns={"ISO 3 code": "iso3", "Area": "name", "Year": "year", "Value": "demand_twh",
                             "Continent": "continent", "EU": "eu", "ASEAN": "asean"})[
        ["iso3", "name", "year", "demand_twh", "continent", "eu", "asean"]]


def modelled_countries():
    """iso3 -> archetype region or rest-of-world group of the 132 countries in the pypsa-earth runs."""
    c = pd.read_csv(path("countries"), keep_default_na=False)
    c = c[c.status.isin(["archetype", "modelled"])]
    return dict(zip(c.iso3, c.group))


ARCHETYPES = ["US", "BR", "IN", "SG", "NWE", "CN"]
