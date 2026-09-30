# SPDX-License-Identifier: CC0-1.0
"""
World power-mix page: the current and the carbon-neutral generation mix of every modelled country on one poster.

Every country of every stage config (the six archetype regions and the rest-of-world groups written by
select_countries.py) gets three 100 % bars, top to bottom:
    Ember   actual generation by fuel, latest year <= 2024 (yearly_full_release_long_format.csv)
    now     the <R>-now screening solve (brownfield, 2025 costs, no CO2 cap)
    zero    the <R>-zero screening solve (Co2L0, 2050 costs)
Countries of multi-node regions are split by bus country, except the multi-country archetype region NWE, which is
shown as one row (its 12 countries summed, Ember included). The model mix is primary generation: generators plus hydro
reservoir discharge; pumped hydro, battery and H2 discharge are storage throughput and left out (Ember counts neither);
load shedding is drawn as its own red segment. Right of the bars: the fossil share (coal + gas + oil) of each bar and, for
the Ember and now bars, the power-sector CO2 from fossil combustion in Mt (Ember "Fossil" aggregate of the same year, i.e.
coal + gas + other fossil without the life-cycle factors Ember adds for bioenergy, nuclear, wind and solar; the model's
direct emissions, generation / efficiency x the carrier's co2_emissions).
Next to the name: Ember demand | model load (TWh; the model load is GEGIS SSP2-2.6 2030, DemandCast 2013 where GEGIS
is empty). The header holds the aggregate of all modelled countries, four Ember-vs-now scatters (share of generation,
dot area ~ demand) and the coverage (share of Ember world demand in the model, skipped countries).

Standalone (fork env, from models/pypsa-earth); run.sh stage `world` calls it the same way:
    pixi run python ../../config-pypsa-earth/scripts/plot_world.py -o results/catalyst/validation_world.png
(a .pdf with the same stem is written next to the .png)
"""
import argparse
import glob
import logging
import os
import re
import sys
import textwrap
import warnings

import matplotlib
import numpy as np
import pandas as pd
import pypsa
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.transforms import blended_transform_factory  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.dirname(HERE)
sys.path.insert(0, CFG)
from merge_config import solved_network  # noqa: E402

warnings.filterwarnings("ignore")
logging.getLogger("pypsa").setLevel(logging.ERROR)

EMBER = os.path.join(CFG, "data", "validation", "yearly_full_release_long_format.csv")
ROW = os.path.join(CFG, "data", "row_countries.csv")
MAX_YEAR = 2024
SHED = "load shedding"
ORDER = ["coal", "gas", "oil", "nuclear", "hydro", "wind", "solar", "biomass", "other", "shed"]
NAMES = {"coal": "Coal", "gas": "Gas", "oil": "Oil / other fossil", "nuclear": "Nuclear", "hydro": "Hydro", "wind": "Wind",
         "solar": "Solar", "biomass": "Bioenergy", "other": "Geothermal / other RE", "shed": "Load shedding (model)"}
FOSSIL = ["coal", "gas", "oil"]
CARRIER_GROUP = {"coal": "coal", "lignite": "coal", "CCGT": "gas", "OCGT": "gas", "oil": "oil", "nuclear": "nuclear",
                 "hydro": "hydro", "ror": "hydro", "onwind": "wind", "offwind-ac": "wind", "offwind-dc": "wind",
                 "solar": "solar", "csp": "solar", "biomass": "biomass", "geothermal": "other", SHED: "shed"}
REPR = {"coal": "coal", "gas": "CCGT", "oil": "oil", "nuclear": "nuclear", "hydro": "hydro", "wind": "onwind",
        "solar": "solar", "biomass": "biomass", "other": "geothermal"}
FALLBACK = {"coal": "#545454", "gas": "#e05b09", "oil": "#c9c9c9", "nuclear": "#ff8c00", "hydro": "#298c81", "wind": "#235ebc",
            "solar": "#f9d002", "biomass": "#baa741", "other": "#ba91b1", "shed": "#dd2e23"}
EMBER_FUEL = {"Coal": "coal", "Gas": "gas", "Other Fossil": "oil", "Nuclear": "nuclear", "Hydro": "hydro", "Wind": "wind",
              "Solar": "solar", "Bioenergy": "biomass", "Other Renewables": "other"}
INK, INK2, MUTED, RULE = "#1a1a1a", "#555555", "#8a8a8a", "#dddddd"
SHORT = {"KP": "North Korea", "KR": "South Korea", "CD": "DR Congo", "CG": "Congo", "US": "United States", "GB": "United Kingdom",
         "RU": "Russia", "LA": "Laos", "VE": "Venezuela", "BO": "Bolivia", "TZ": "Tanzania", "SY": "Syria", "MD": "Moldova",
         "VN": "Vietnam", "PS": "Palestine", "BN": "Brunei", "IR": "Iran", "CI": "Côte d'Ivoire", "BA": "Bosnia-Herzeg.",
         "AE": "UAE", "DO": "Dominican Rep.", "TT": "Trinidad & Tobago"}
REGION_NAMES = {"NWE": "North-West Europe"}
SCEN = ["ember", "now", "zero"]
SCEN_LABEL = {"ember": "Ember", "now": "now", "zero": "zero"}


# ----------------------------------------------------------------------------- data ---------------------
def stage_regions():
    """{region: config dict} of every non-smoke config.<R>.yaml."""
    out = {}
    for f in sorted(glob.glob(os.path.join(CFG, "config.*.yaml"))):
        r = os.path.basename(f)[len("config."):-len(".yaml")]
        if "-smoke" not in r:
            with open(f) as fh:
                out[r] = yaml.safe_load(fh)
    return out


def country_table(n):
    """Per country: TWh by ORDER group (primary generation + shedding) and the load, from one solved network."""
    w = n.snapshot_weightings.generators
    bc = n.buses.country
    g = n.generators
    e = n.generators_t.p.reindex(columns=g.index, fill_value=0.0).mul(w, axis=0).sum() / 1e6
    gen = e.groupby([g.bus.map(bc), g.carrier.map(CARRIER_GROUP).fillna("other")]).sum().unstack(fill_value=0.0)
    su = n.storage_units[n.storage_units.carrier == "hydro"]
    if len(su):
        dis = n.storage_units_t.p.reindex(columns=su.index, fill_value=0.0).clip(lower=0).mul(w, axis=0).sum() / 1e6
        gen = gen.add(dis.groupby(su.bus.map(bc)).sum().rename("hydro").to_frame(), fill_value=0.0)
    gen = gen.reindex(columns=ORDER, fill_value=0.0).fillna(0.0)
    load = n.loads_t.p_set.reindex(columns=n.loads.index, fill_value=0.0).mul(w, axis=0).sum() / 1e6
    gen["load"] = load.groupby(n.loads.bus.map(bc)).sum().reindex(gen.index).fillna(0.0)
    eff = g.efficiency.replace(0, np.nan).fillna(1.0)
    co2 = n.carriers.co2_emissions.reindex(g.carrier).fillna(0.0).values
    gen["co2"] = (e * 1e6 / eff * co2 / 1e6).groupby(g.bus.map(bc)).sum().reindex(gen.index).fillna(0.0)   # Mt
    return gen


def ember_table():
    e = pd.read_csv(EMBER, usecols=["Area", "ISO 3 code", "Year", "Area type", "Category", "Subcategory", "Variable", "Unit",
                                    "Value"])
    e = e[(e["Area type"] == "Country or economy") & (e.Year <= MAX_YEAR)]
    gen = e[(e.Category == "Electricity generation") & (e.Subcategory == "Fuel") & (e.Unit == "TWh")]
    year = gen.groupby("ISO 3 code").Year.max()
    gen = gen[gen.Year == gen["ISO 3 code"].map(year)]
    t = gen.pivot_table(index="ISO 3 code", columns="Variable", values="Value", aggfunc="sum").rename(columns=EMBER_FUEL)
    t = t.T.groupby(level=0).sum().T.reindex(columns=ORDER, fill_value=0.0).fillna(0.0)
    dem = e[(e.Category == "Electricity demand") & (e.Variable == "Demand") & (e.Unit == "TWh")].dropna(subset=["Value"])
    dem = dem.sort_values("Year").groupby("ISO 3 code").last()
    t["demand"] = dem.Value.reindex(t.index)
    t["year"] = year.reindex(t.index)
    em = e[(e.Category == "Power sector emissions") & (e.Subcategory == "Aggregate fuel") & (e.Variable == "Fossil")
           & (e.Unit == "mtCO2")]
    em = em[em.Year == em["ISO 3 code"].map(year)].set_index("ISO 3 code").Value
    t["co2"] = em.reindex(t.index)
    t["name"] = e.drop_duplicates("ISO 3 code").set_index("ISO 3 code").Area.reindex(t.index).map(
        lambda a: re.sub(r"\s*\(.*?\)", "", a) if isinstance(a, str) else a)
    return t, float(dem.Value.sum())


def collect(fork):
    """Long table: one row per (country, scenario) with ORDER columns in TWh, plus region / load / name / Ember demand."""
    import pycountry

    ember, world = ember_table()
    rows, missing = [], []
    for r, cfg in stage_regions().items():
        ccs = [str(c) for c in cfg["countries"]]
        for scen in ("now", "zero"):
            path = os.path.join(fork, solved_network(r, scen))
            if not os.path.exists(path):
                missing.append(f"{r}-{scen}")
                continue
            print(f"reading {path}", flush=True)
            t = country_table(pypsa.Network(path))
            for c in ccs:
                row = t.loc[c].to_dict() if c in t.index else {k: np.nan for k in ORDER + ["load"]}
                rows.append(dict(row, country=c, region=r, scen=scen))
        for c in ccs:
            iso3 = pycountry.countries.get(alpha_2=c).alpha_3
            if iso3 in ember.index:
                rows.append(dict(ember.loc[iso3, ORDER + ["co2"]].to_dict(), country=c, region=r, scen="ember"))
    df = pd.DataFrame(rows)
    iso3 = {c: pycountry.countries.get(alpha_2=c).alpha_3 for c in df.country.unique()}
    for k in ("demand", "year", "name"):
        df[k] = df.country.map(lambda c: ember[k].get(iso3[c], np.nan))
    df["name"] = df.country.map(SHORT).fillna(df["name"]).fillna(df.country)
    # multi-country archetype regions are one row: the countries summed per scenario
    for r, cfg in stage_regions().items():
        if len(cfg["countries"]) > 1 and not (cfg.get("catalyst") or {}).get("single_node"):
            sub = df[df.region == r]
            agg = sub.groupby("scen")[ORDER + ["load", "co2", "demand"]].sum(min_count=1).reset_index()
            agg["country"], agg["region"], agg["year"] = r, f"{len(cfg['countries'])} countries", sub.year.max()
            agg["name"] = REGION_NAMES.get(r, r)
            df = pd.concat([df[df.region != r], agg], ignore_index=True)
    return df, world, missing


# ----------------------------------------------------------------------------- drawing ------------------
def colors(fork, df):
    """Group colours from the carriers table of the first solved network (the palette of the regional dashboards)."""
    col = dict(FALLBACK)
    for r in df.region.unique():
        path = os.path.join(fork, solved_network(r, "now"))
        if os.path.exists(path):
            car = pypsa.Network(path).carriers.color
            for grp, c in REPR.items():
                if isinstance(car.get(c), str) and car.get(c):
                    col[grp] = car[c]
            break
    return col


def shares(v):
    tot = np.nansum([v[k] for k in ORDER])
    return {k: (v[k] / tot if tot > 0 else np.nan) for k in ORDER}, tot


def hbar(ax, y, sh, col, h):
    x = 0.0
    for k in ORDER:
        s = sh.get(k, 0.0)
        if not s > 0:
            continue
        ax.barh(y, s, left=x, height=h, color=col[k], edgecolor="white", linewidth=0.5)
        x += s


def draw_column(ax, block, col):
    tr = blended_transform_factory(ax.transAxes, ax.transData)
    step = 3.9
    for i, (c, g) in enumerate(block):
        y0 = i * step
        first = g.iloc[0]
        ax.text(-0.155, y0 + 1, first["name"], transform=tr, ha="right",
                va="center", fontsize=6.6, color=INK)
        load = g.loc[g.scen == "now", "load"]
        dem = f"{first['demand']:.0f}" if pd.notna(first["demand"]) else "–"
        mod = f"{load.iloc[0]:.0f}" if len(load) and pd.notna(load.iloc[0]) else "–"
        yr = "" if first["year"] == MAX_YEAR or pd.isna(first["year"]) else f" ({int(first['year'])})"
        ax.text(-0.155, y0 + 2.05, f"{c} · {first['region']} · {dem} | {mod} TWh{yr}", transform=tr, ha="right", va="center",
                fontsize=4.8, color=MUTED)
        for j, scen in enumerate(SCEN):
            y = y0 + j
            ax.text(-0.012, y, SCEN_LABEL[scen], transform=tr, ha="right", va="center", fontsize=4.6, color=MUTED)
            r = g[g.scen == scen]
            if not len(r) or not np.nansum([r.iloc[0][k] for k in ORDER]) > 0:
                ax.text(0.01, y, "not solved" if scen != "ember" else "no Ember data", transform=tr, va="center", fontsize=4.6,
                        color=MUTED)
                continue
            sh, tot = shares(r.iloc[0])
            hbar(ax, y, sh, col, 0.78)
            fos = sum(sh[k] for k in FOSSIL)
            txt = f"{100 * fos:.0f} %"
            co2 = r.iloc[0].get("co2", np.nan)
            if scen != "zero" and pd.notna(co2):
                txt += f" · {co2:.1f} Mt" if co2 < 10 else f" · {co2:,.0f} Mt"
            if sh["shed"] > 0.005:
                txt += f"  shed {100 * sh['shed']:.0f} %"
            ax.text(1.012, y, txt, transform=tr, va="center", fontsize=4.8,
                    color=FALLBACK["shed"] if sh["shed"] > 0.005 else INK2)
    ax.set_xlim(0, 1)
    ax.set_ylim(len(block) * step - 0.6, -0.8)
    ax.axis("off")


def draw_scatter(ax, df, groups, title):
    w = df.pivot_table(index="country", columns="scen", values=groups, aggfunc="sum")
    tot = {s: df[df.scen == s].set_index("country")[ORDER].sum(axis=1) for s in ("ember", "now")}
    x = w.xs("ember", axis=1, level=1).sum(axis=1) / tot["ember"]
    y = w.xs("now", axis=1, level=1).sum(axis=1) / tot["now"]
    dem = df.drop_duplicates("country").set_index("country").demand
    ok = x.notna() & y.notna()
    x, y, dem = 100 * x[ok], 100 * y[ok], dem.reindex(x[ok].index).fillna(1)
    ax.plot([0, 100], [0, 100], color=RULE, lw=1, zorder=0)
    ax.scatter(x, y, s=4 + 60 * np.sqrt(dem / dem.max()), color="#3b6fd6", alpha=0.55, edgecolor="white", linewidth=0.5)
    big = (dem * (x - y).abs()).sort_values(ascending=False).index[:4]
    for c in big:
        ax.annotate(c, (x[c], y[c]), fontsize=5.5, color=INK2, xytext=(3, 2), textcoords="offset points")
    ax.set_xlim(-3, 103)
    ax.set_ylim(-3, 103)
    ax.set_xticks([0, 50, 100])
    ax.set_yticks([0, 50, 100])
    ax.tick_params(labelsize=5.5, colors=INK2, length=2)
    for s in ax.spines.values():
        s.set_color(RULE)
    ax.set_title(title, fontsize=7, color=INK, loc="left")
    ax.set_xlabel("Ember %", fontsize=5.5, color=INK2, labelpad=1)
    ax.set_ylabel("model now %", fontsize=5.5, color=INK2, labelpad=1)


def draw_co2_scatter(ax, df):
    e = df[df.scen == "ember"].set_index("country").co2
    m = df[df.scen == "now"].set_index("country").co2
    ok = e.notna() & (e > 0.05) & m.reindex(e.index).notna() & (m.reindex(e.index) > 0.05)
    x, y = e[ok], m.reindex(e.index)[ok]
    lim = (0.05, max(x.max(), y.max()) * 1.5)
    ax.plot(lim, lim, color=RULE, lw=1, zorder=0)
    ax.scatter(x, y, s=4 + 60 * np.sqrt(x / x.max()), color="#3b6fd6", alpha=0.55, edgecolor="white", linewidth=0.5)
    big = (np.log(y / x).abs() * x).sort_values(ascending=False).index[:4]
    for c in big:
        ax.annotate(c, (x[c], y[c]), fontsize=5.5, color=INK2, xytext=(3, 2), textcoords="offset points")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.tick_params(labelsize=5.5, colors=INK2, length=2, which="both")
    ax.minorticks_off()
    for s in ax.spines.values():
        s.set_color(RULE)
    ax.set_title("Fossil CO2, Mt", fontsize=7, color=INK, loc="left")
    ax.set_xlabel("Ember", fontsize=5.5, color=INK2, labelpad=1)
    ax.set_ylabel("model now", fontsize=5.5, color=INK2, labelpad=1)


def page(df, world, missing, col, out):
    order = (df[df.scen == "ember"].drop_duplicates("country").set_index("country").demand
             .reindex(df.country.unique()).sort_values(ascending=False, na_position="last").index)
    blocks = [(c, df[df.country == c]) for c in order]
    ncol = 4
    per = int(np.ceil(len(blocks) / ncol))
    fig = plt.figure(figsize=(24, 17.5), facecolor="white")

    # ---- header: title, aggregate bars, scatters, notes
    covered = df[df.scen == "ember"].drop_duplicates("country").demand.sum()
    fig.text(0.02, 0.975, "Out-of-the-box PyPSA-Earth: current vs carbon-neutral power mix, all modelled countries",
             fontsize=15, color=INK, weight="bold", va="top")
    n_c = sum(len(cfg["countries"]) for cfg in stage_regions().values())
    fig.text(0.02, 0.953, f"{n_c} countries in {df.country.nunique()} rows = {100 * covered / world:.2f} % of world electricity demand "
             f"(Ember, latest year ≤ {MAX_YEAR}: {world:,.0f} TWh). Weather year 2013, 3-hourly. "
             "Archetype regions multi-node (NWE = AT BE CH CZ DE DK FR GB IE LU NL PL as one row), all other countries one node "
             "each and islanded (no trade).",
             fontsize=8, color=INK2, va="top")
    ax = fig.add_axes([0.07, 0.855, 0.25, 0.075])
    agg = df.groupby("scen")[ORDER].sum()
    for j, scen in enumerate(SCEN):
        if scen not in agg.index:
            continue
        sh, tot = shares(agg.loc[scen])
        hbar(ax, j, sh, col, 0.75)
        x = 0
        for k in ORDER:
            if sh[k] > 0.045:
                ax.text(x + sh[k] / 2, j, f"{100 * sh[k]:.0f}", ha="center", va="center", fontsize=6.5,
                        color="white" if k in ("coal", "gas", "nuclear", "hydro", "wind", "shed") else INK)
            x += sh[k] if sh[k] > 0 else 0
        ax.text(-0.01, j, {"ember": "Ember", "now": "model now", "zero": "model zero"}[scen], ha="right", va="center",
                fontsize=7.5, color=INK2, transform=blended_transform_factory(ax.transAxes, ax.transData))
        ax.text(1.01, j, f"{tot:,.0f} TWh", va="center", fontsize=6.5, color=INK2,
                transform=blended_transform_factory(ax.transAxes, ax.transData))
    ax.set_xlim(0, 1)
    ax.set_ylim(2.6, -0.6)
    ax.axis("off")
    co2 = df.groupby("scen").co2.sum()
    ax.set_title("All modelled countries together (% of generation) · fossil CO2: Ember "
                 f"{co2.get('ember', np.nan) / 1e3:.1f} Gt, model now {co2.get('now', np.nan) / 1e3:.1f} Gt, zero "
                 f"{co2.get('zero', 0) / 1e3:.1f} Gt", fontsize=7.5, color=INK, loc="left")
    for i, (grps, title) in enumerate([(FOSSIL, "Fossil share"), (["nuclear"], "Nuclear share"), (["hydro"], "Hydro share"),
                                       (["wind", "solar"], "Wind + solar share")]):
        draw_scatter(fig.add_axes([0.375 + i * 0.072, 0.845, 0.052, 0.085]), df, grps, title)
    draw_co2_scatter(fig.add_axes([0.375 + 4 * 0.072, 0.845, 0.052, 0.085]), df)
    handles = [plt.Rectangle((0, 0), 1, 1, color=col[k]) for k in ORDER]
    fig.legend(handles, [NAMES[k] for k in ORDER], loc="upper left", bbox_to_anchor=(0.745, 0.94), ncol=2, fontsize=7,
               frameon=False, handlelength=1.2, columnspacing=1.0)
    notes = ["Per country, top to bottom: Ember actual · model now (brownfield, 2025 costs, no CO2 cap) · model zero (Co2L0, "
             "2050 costs). Right of the bars: fossil share and power-sector CO2 from coal, gas and oil in Mt (Ember 'Fossil', "
             "same year; model: direct emissions). Grey line: code · region run · Ember demand | model load (TWh; GEGIS "
             "SSP2-2.6 2030, DemandCast 2013 where GEGIS is empty)."]
    sk = pd.read_csv(ROW, keep_default_na=False) if os.path.exists(ROW) else pd.DataFrame()
    if len(sk):
        s = sk[sk.status == "skipped"]
        notes.append("Not modelled: " + ", ".join(f"{r.iso2 or r.iso3} {r.demand_twh:.0f} TWh ({r.reason})" for r in s.itertuples()))
    if missing:
        notes.append("Missing solves: " + ", ".join(missing))
    notes = "\n".join(textwrap.fill(par, 100) for par in notes)
    fig.text(0.745, 0.865, notes, fontsize=6.3, color=INK2, va="top", linespacing=1.4)

    # ---- body: four columns of countries sorted by Ember demand
    for k in range(ncol):
        part = blocks[k * per:(k + 1) * per]
        if part:
            draw_column(fig.add_axes([0.085 + k * 0.245, 0.015, 0.145, 0.80]), part, col)
    fig.savefig(out, dpi=200)
    fig.savefig(os.path.splitext(out)[0] + ".pdf")
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-o", "--out", default="results/catalyst/validation_world.png")
    p.add_argument("--fork", default=".", help="models/pypsa-earth (paths of the solved networks are relative to it)")
    p.add_argument("--table", default=None, help="also write the per-country table (CSV)")
    a = p.parse_args()
    df, world, missing = collect(a.fork)
    table = a.table or os.path.splitext(a.out)[0] + ".csv"
    df.to_csv(table, index=False)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    page(df, world, missing, colors(a.fork, df), a.out)
    print(f"wrote {a.out}, {os.path.splitext(a.out)[0]}.pdf and {table}")


if __name__ == "__main__":
    main()
