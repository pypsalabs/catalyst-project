"""Helpers shared by the scripts of this workflow.

Pure functions only (no file I/O at import time), so that every script can
still run standalone. Snakemake puts the script directory on sys.path, so
`from common import ...` works from `script:` rules as well.
"""

import re
import textwrap

import numpy as np
import pandas as pd


# --- money -----------------------------------------------------------------------

def annuity(rate, years):
    return rate / (1 - (1 + rate) ** -years)


def split_currency(unit):
    """Return (currency or None, unit without the currency prefix)."""
    m = re.match(r"^(EUR|USD|GBP|CAD|AUD|CNY|JPY)\s*/\s*(.+)$", unit)
    if m:
        return m.group(1), m.group(2)
    return None, unit


def make_to_base(cfg):
    """Return `to_base(value, currency, year)` bound to the FX/CPI tables of `cfg`.

    value_base = value * fx_eur_per_unit[cur][y] / fx_eur_per_unit[base][y]
                       * cpi[base][base_year] / cpi[base][y]
    i.e. convert at the exchange rate of the stated price year, then inflate
    with the base currency's CPI. A missing currency year is taken as the base
    year and noted; a year outside the tables raises (extend config.yaml).
    """
    base_year = int(cfg["base_currency_year"])
    base_cur = cfg["base_currency"]
    fx = cfg["fx_eur_per_unit"]
    cpi = cfg["cpi"]

    def to_base(value, currency, year, mode="price_year"):
        """Convert `value` in `currency` of price year `year` to the base currency and year.

        mode="price_year" (default): exchange at the rate of `year`, then inflate with the
        base currency's CPI. mode="constant": deflate within `currency` using its own CPI to
        `base_year`, then exchange once at the base-year rate. The second keeps a single-
        country time series free of exchange-rate noise (a floating rate would otherwise
        change the slope of an experience curve, not only its intercept).
        """
        notes = []
        if pd.isna(value):
            return np.nan, ""
        if currency is None or (isinstance(currency, float) and np.isnan(currency)) or currency == "":
            currency = "EUR"
        if pd.isna(year):
            year = base_year
            notes.append(f"no currency year stated, assumed {base_year}")
        year = int(year)
        if currency not in fx:
            raise ValueError(f"no FX table for currency {currency!r}")
        if mode == "constant":
            if currency not in cpi or year not in cpi[currency] or base_year not in fx[currency]:
                raise ValueError(f"no CPI/FX entry for constant-currency conversion of {currency} {year}")
            base = (value * cpi[currency][base_year] / cpi[currency][year]
                    * fx[currency][base_year] / fx[base_cur][base_year])
            notes.append(f"deflated in {currency}, exchanged at the {base_year} rate")
            return base, "; ".join(notes)
        if mode != "price_year":
            raise ValueError(f"unknown fx_mode {mode!r}")
        if year not in fx[currency] or year not in cpi[base_cur]:
            raise ValueError(f"no FX/CPI entry for {currency} {year}")
        base = (value * fx[currency][year] / fx[base_cur][year]
                * cpi[base_cur][base_year] / cpi[base_cur][year])
        return base, "; ".join(notes)

    return to_base


# --- matplotlib ------------------------------------------------------------------

def grid(ax, log, axis="x"):
    """Light major (and, on log axes, minor) grid; no top/right spines."""
    ax.set_axisbelow(True)
    ax.grid(True, axis=axis, which="major", color="0.75", linewidth=0.7)
    if log:
        ax.grid(True, axis=axis, which="minor", color="0.88", linewidth=0.4)
    ax.spines[["top", "right"]].set_visible(False)


def footnote(axf, text):
    """Wrapped 7 pt grey text on a text-only axes carrying `wrap_chars`."""
    if axf is None:
        return
    axf.text(0, 1, "\n".join(textwrap.wrap(text, axf.wrap_chars)), transform=axf.transAxes,
             fontsize=7, color="0.35", ha="left", va="top")


def save(fig, outputs, dpi):
    import matplotlib.pyplot as plt
    for out in outputs:
        fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print("wrote", ", ".join(str(o) for o in outputs))
