# SPDX-License-Identifier: CC0-1.0
"""
Validation dashboard for solved Catalyst pypsa-earth networks.

One 16:9 block per network with eight tiles: generation mix, installed capacity, electricity price
statistics, demand, CO2 emissions by source, curtailment, total system cost, summary. With two
networks the page shows them side by side (left = first, right = second), still 16:9.

Snakemake (config-pypsa-earth/validation.smk):
    rule plot_validation      input.network             -> one block
    rule validation_dashboard input.now, input.zero     -> two blocks
Standalone (inside the fork's pixi env):
    pixi run python ../../config-pypsa-earth/scripts/plot_validation.py NOW.nc [ZERO.nc] -o page.png [--title T]

All numbers are computed directly from the network (no make_summary): TWh, GW, Mt CO2, bn EUR/a. The
"existing fleet" annuity (capital_cost x fixed p_nom) is shown for information; it is not part of the
optimisation objective, which only prices extendable components.
"""
import argparse
import logging
import os
import sys
import warnings

import matplotlib
import numpy as np
import pandas as pd
import pypsa

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.gridspec import GridSpecFromSubplotSpec  # noqa: E402

warnings.filterwarnings("ignore")
logging.getLogger("pypsa").setLevel(logging.ERROR)

VRE = ["solar", "onwind", "offwind-ac", "offwind-dc", "ror", "csp"]
SHED = "load shedding"
GREY = "#b0b0b0"
FALLBACK_COLORS = {"AC": "#70af1d", "DC": "#8a1caf", SHED: "#dd2e23", "battery": "slategray", "H2": "#ea048a"}
SHORT_NAMES = {  # y-tick labels must stay short (eight tiles per block)
    "CCGT": "Gas CCGT", "OCGT": "Gas OCGT", "offwind-ac": "Offshore wind AC", "offwind-dc": "Offshore wind DC",
    "onwind": "Onshore wind", "solar": "Solar PV", "hydro": "Hydro reservoir", "ror": "Run of river", "PHS": "Pumped hydro",
    "battery": "Battery", "H2": "Hydrogen store", "AC": "AC lines", "DC": "HVDC links", SHED: "Load shedding",
    "nuclear": "Nuclear", "coal": "Coal", "lignite": "Lignite", "oil": "Oil", "biomass": "Biomass", "geothermal": "Geothermal",
}


# ----------------------------------------------------------------------------- data ---------------------
def carrier_style(n):
    col = n.carriers.color.replace("", np.nan).fillna(pd.Series(FALLBACK_COLORS)).fillna(GREY).to_dict()
    nice = n.carriers.nice_name.replace("", np.nan).to_dict()
    nice = {k: (v if isinstance(v, str) else k) for k, v in nice.items()}
    nice.update(SHORT_NAMES)
    return col, nice


def collect(n):
    """Return a dict of tidy tables (pandas) for one solved network, region-wide."""
    w = n.snapshot_weightings.generators
    d = {}
    ac = n.buses.index[n.buses.carrier == "AC"]
    g = n.generators
    gp = n.generators_t.p.reindex(columns=g.index, fill_value=0.0)
    shed = g.index[g.carrier == SHED]
    prod = g.index.difference(shed)

    # ---- demand
    load = n.loads_t.p_set.reindex(columns=n.loads.index, fill_value=0.0)
    load_bus_country = n.loads.bus.map(n.buses.country)
    d["load_hourly"] = load.sum(axis=1)                                      # MW
    d["demand_twh"] = float((d["load_hourly"] * w).sum() / 1e6)
    d["peak_gw"] = float(d["load_hourly"].max() / 1e3)
    d["load_monthly_by_country"] = (
        load.mul(w, axis=0).T.groupby(load_bus_country).sum().T.resample("MS").sum() / 1e6  # TWh
    )
    d["countries"] = sorted(n.buses.loc[ac, "country"].dropna().unique().tolist())
    d["demand_by_country"] = (load.mul(w, axis=0).sum().groupby(load_bus_country).sum() / 1e6).sort_values(ascending=False)

    # ---- generation mix (TWh, positive supply to the AC side)
    gen = gp[prod].mul(w, axis=0).sum().groupby(g.carrier).sum() / 1e6
    su = n.storage_units
    sup = n.storage_units_t.p.reindex(columns=su.index, fill_value=0.0)
    su_dis = sup.clip(lower=0).mul(w, axis=0).sum().groupby(su.carrier).sum() / 1e6
    su_chg = (-sup.clip(upper=0)).mul(w, axis=0).sum().groupby(su.carrier).sum() / 1e6
    lk = n.links
    l1 = n.links_t.p1.reindex(columns=lk.index, fill_value=0.0)
    l0 = n.links_t.p0.reindex(columns=lk.index, fill_value=0.0)
    dis = lk.index[lk.bus1.isin(ac) & ~lk.bus0.isin(ac)]          # discharger / fuel cell: store bus -> AC bus
    chg = lk.index[lk.bus0.isin(ac) & ~lk.bus1.isin(ac)]          # charger / electrolysis: AC bus -> store bus
    st_dis = (-l1[dis]).clip(lower=0).mul(w, axis=0).sum().groupby(lk.loc[dis, "bus0"].map(n.buses.carrier)).sum() / 1e6
    st_chg = l0[chg].clip(lower=0).mul(w, axis=0).sum().groupby(lk.loc[chg, "bus1"].map(n.buses.carrier)).sum() / 1e6
    shed_twh = float(gp[shed].mul(w, axis=0).sum().sum() / 1e6) if len(shed) else 0.0
    mix = pd.concat([gen, su_dis, st_dis]).groupby(level=0).sum()
    mix = mix[mix > 1e-6].sort_values(ascending=False)
    if shed_twh > 1e-6:
        mix[SHED] = shed_twh
    d["mix_twh"] = mix
    d["storage_charge_twh"] = pd.concat([su_chg, st_chg]).groupby(level=0).sum()
    d["shed_twh"] = shed_twh
    d["shed_hours"] = int((gp[shed].sum(axis=1) > 1.0).sum()) if len(shed) else 0
    d["generation_twh"] = float(mix.drop(SHED, errors="ignore").sum())

    # ---- capacity (GW): pre-solve p_nom vs p_nom_opt, by carrier
    gg = g.loc[prod]
    pre = gg.p_nom.groupby(gg.carrier).sum() / 1e3
    opt = gg.p_nom_opt.groupby(gg.carrier).sum() / 1e3
    pre_su = su.p_nom.groupby(su.carrier).sum() / 1e3
    opt_su = su.p_nom_opt.groupby(su.carrier).sum() / 1e3
    st_car = lk.loc[dis, "bus0"].map(n.buses.carrier)
    pre_st = lk.loc[dis, "p_nom"].groupby(st_car).sum() / 1e3
    opt_st = lk.loc[dis, "p_nom_opt"].groupby(st_car).sum() / 1e3
    cap = pd.DataFrame({"pre": pd.concat([pre, pre_su, pre_st]).groupby(level=0).sum(),
                        "opt": pd.concat([opt, opt_su, opt_st]).groupby(level=0).sum()}).fillna(0.0)
    cap = cap[(cap.max(axis=1) > 1e-3)].sort_values("opt", ascending=False)
    d["cap_gw"] = cap
    stores = n.stores
    d["store_gwh"] = stores.e_nom_opt.groupby(stores.carrier).sum() / 1e3
    lines = n.lines
    d["lines_gwkm"] = (float((lines.s_nom * lines.length).sum() / 1e3), float((lines.s_nom_opt * lines.length).sum() / 1e3))
    dc = lk.index[lk.carrier == "DC"]
    d["dc_gw"] = (float(lk.loc[dc, "p_nom"].sum() / 1e3), float(lk.loc[dc, "p_nom_opt"].sum() / 1e3))

    # ---- prices (EUR/MWh): load-weighted regional hourly price, spread across buses
    mp = n.buses_t.marginal_price.reindex(columns=ac, fill_value=np.nan)
    lb = load.T.groupby(n.loads.bus).sum().T.reindex(columns=ac, fill_value=0.0)
    wsum = lb.sum(axis=1).replace(0, np.nan)
    price = (mp * lb).sum(axis=1) / wsum
    d["price_hourly"] = price
    d["price_band"] = pd.DataFrame({"p05": mp.quantile(0.05, axis=1), "p95": mp.quantile(0.95, axis=1)})
    shed_cost = float(g.loc[shed, "marginal_cost"].max()) if len(shed) else np.inf
    ok = mp < 0.5 * shed_cost                                # bus-snapshots not priced at the shedding penalty
    lb_ok = lb.where(ok, 0.0)
    price_ok = (mp.where(ok) * lb_ok).sum(axis=1) / lb_ok.sum(axis=1).replace(0, np.nan)
    d["price_stats"] = {
        "mean": float(np.nansum(price * d["load_hourly"] * w) / np.nansum(d["load_hourly"] * w)),
        "mean_ok": float(np.nansum(price_ok * lb_ok.sum(axis=1) * w) / np.nansum(lb_ok.sum(axis=1) * w)),
        "share_shed_bus_h": float(100 * (~ok).values.sum() / ok.size),
        "median": float(price.median()), "p95": float(price.quantile(0.95)), "max": float(price.max()),
        "min": float(price.min()), "bus_mean_spread": (float(mp.mean().min()), float(mp.mean().max())),
    }
    d["shed_cost"] = shed_cost
    d["hours_at_shed_price"] = int((price >= 0.5 * shed_cost).sum()) if len(shed) else 0
    gc = n.global_constraints
    d["co2_limit"] = float(gc.at["CO2Limit", "constant"]) if "CO2Limit" in gc.index else np.nan
    d["co2_price"] = float(abs(gc.at["CO2Limit", "mu"])) if "CO2Limit" in gc.index else np.nan

    # ---- emissions (Mt CO2/a) by carrier
    eff = gg.efficiency.replace(0, np.nan).fillna(1.0)
    co2 = n.carriers.co2_emissions.reindex(gg.carrier).fillna(0.0).values
    em = (gp[gg.index].mul(w, axis=0).sum() / eff * co2).groupby(gg.carrier).sum() / 1e6
    d["emissions_mt"] = em[em > 1e-6].sort_values(ascending=False)
    d["emissions_total"] = float(em.sum())

    # ---- curtailment (TWh) of variable generators
    vre = gg.index[gg.carrier.isin(VRE)]
    pmp = n.generators_t.p_max_pu.reindex(columns=vre).fillna(0.0)
    static = gg.loc[vre.difference(n.generators_t.p_max_pu.columns), "p_max_pu"]
    for c in static.index:
        pmp[c] = static[c]
    avail = pmp * gg.loc[vre, "p_nom_opt"]
    curt = (avail - gp[vre]).clip(lower=0).mul(w, axis=0).sum().groupby(gg.loc[vre, "carrier"]).sum() / 1e6
    availc = avail.mul(w, axis=0).sum().groupby(gg.loc[vre, "carrier"]).sum() / 1e6
    d["curtailment"] = pd.DataFrame({"curtailed": curt, "available": availc})
    d["curtailment"] = d["curtailment"][d["curtailment"].available > 1e-6]

    # ---- system cost (bn EUR/a)
    ext = gg.p_nom_extendable
    exist_cap = (gg.loc[~ext, "capital_cost"] * gg.loc[~ext, "p_nom"]).sum() \
        + (gg.loc[ext, "capital_cost"] * gg.loc[ext, "p_nom_min"]).sum() \
        + (su.capital_cost * np.where(su.p_nom_extendable, su.p_nom_min, su.p_nom)).sum()
    new_cap = (gg.loc[ext, "capital_cost"] * (gg.loc[ext, "p_nom_opt"] - gg.loc[ext, "p_nom_min"]).clip(lower=0)).sum() \
        + (su.capital_cost * (su.p_nom_opt - np.where(su.p_nom_extendable, su.p_nom_min, su.p_nom)).clip(lower=0)).sum() \
        + (stores.capital_cost * (stores.e_nom_opt - stores.e_nom_min).clip(lower=0)).sum() \
        + (lk.loc[~lk.carrier.isin(["DC", "AC"]), "capital_cost"]
           * (lk.loc[~lk.carrier.isin(["DC", "AC"]), "p_nom_opt"] - lk.loc[~lk.carrier.isin(["DC", "AC"]), "p_nom_min"]).clip(lower=0)).sum()
    tr_cap = (lines.capital_cost * (lines.s_nom_opt - lines.s_nom_min).clip(lower=0)).sum() \
        + (lk.loc[dc, "capital_cost"] * (lk.loc[dc, "p_nom_opt"] - lk.loc[dc, "p_nom_min"]).clip(lower=0)).sum()
    mc = n.get_switchable_as_dense("Generator", "marginal_cost").reindex(columns=gg.index)
    opex = float((gp[gg.index] * mc).mul(w, axis=0).sum().sum()) \
        + float((sup.clip(lower=0) * su.marginal_cost).mul(w, axis=0).sum().sum()) \
        + float((l0.clip(lower=0) * lk.marginal_cost).mul(w, axis=0).sum().sum())
    shed_pen = float((gp[shed] * g.loc[shed, "marginal_cost"]).mul(w, axis=0).sum().sum()) if len(shed) else 0.0
    d["cost_bn"] = pd.Series({"existing fleet (sunk annuity)": exist_cap, "new generation & storage": new_cap,
                              "transmission expansion": tr_cap, "operation (fuel, VOM)": opex}) / 1e9
    d["shed_penalty_bn"] = shed_pen / 1e9
    d["objective_bn"] = float(getattr(n, "objective", np.nan)) / 1e9
    d["cost_total_bn"] = float(d["cost_bn"].sum())
    d["cost_per_mwh"] = d["cost_total_bn"] * 1e9 / (d["demand_twh"] * 1e6)

    meta = getattr(n, "meta", {}) or {}
    d["meta"] = {"run": meta.get("run", {}).get("name", ""), "opts": meta.get("wildcards", {}).get("opts", ""),
                 "scenario": (meta.get("catalyst") or {}).get("scenario", ""),
                 "ll": meta.get("wildcards", {}).get("ll", ""), "cost_year": meta.get("costs", {}).get("year", ""),
                 "clusters": meta.get("wildcards", {}).get("clusters", ""), "countries": meta.get("countries", d["countries"])}
    d["n_buses"] = len(ac)
    d["hours"] = len(n.snapshots)
    return d


# ----------------------------------------------------------------------------- validation points ---------
GROUPS = {  # validation carrier -> model carriers (segments drawn in this order)
    "coal": ["coal", "lignite"], "gas": ["CCGT", "OCGT"], "oil": ["oil"], "nuclear": ["nuclear"],
    "hydro": ["hydro", "ror", "PHS"], "wind": ["onwind", "offwind-ac", "offwind-dc"], "solar": ["solar", "csp"],
    "biomass": ["biomass"], "geothermal": ["geothermal"], "battery": ["battery"], "H2": ["H2"], SHED: [SHED],
}
GROUP_NAMES = {"coal": "Coal", "gas": "Gas", "oil": "Oil", "nuclear": "Nuclear", "hydro": "Hydro", "wind": "Wind",
               "solar": "Solar", "biomass": "Biomass", "geothermal": "Geothermal", "battery": "Battery", "H2": "Hydrogen",
               SHED: "Load shedding", "total": "Total", "other": "Other"}
SUB_SHORT = {"coal": "hard", "lignite": "lign", "CCGT": "CCGT", "OCGT": "OCGT", "hydro": "res", "ror": "RoR", "PHS": "PHS",
             "onwind": "on", "offwind-ac": "offAC", "offwind-dc": "offDC", "solar": "PV", "csp": "CSP"}
SOURCE_STYLE = [("#111111", "o"), ("#e6194b", "D"), ("#3b6fd6", "s"), ("#f58231", "^"), ("#911eb4", "v"), ("#469990", "P"),
                ("#9a6324", "X")]


def load_points(path, region, scenario):
    """Validation points of one region / scenario -> DataFrame, plus {source_short: (color, marker)} in a stable order."""
    if not path or not region or not os.path.exists(path):
        return pd.DataFrame(columns=["country", "quantity", "carrier", "value", "unit", "year", "source_short"]), {}
    pts = pd.read_csv(path, dtype={"country": str}, keep_default_na=False)
    pts = pts[(pts.region == region) & (pts.scenario == scenario)].copy()
    pts["country"] = pts.country.fillna("").astype(str)
    order = sorted(pts.source_short.unique(), key=lambda s: (-(pts.source_short == s).sum(), s))  # richest source first
    styles = {s: SOURCE_STYLE[i % len(SOURCE_STYLE)] for i, s in enumerate(order)}
    return pts, styles


def to_groups(series):
    """carrier series -> (group totals sorted desc, {group: [(carrier, value), ...]})."""
    carrier_group = {c: g for g, cs in GROUPS.items() for c in cs}
    segs, tot = {}, {}
    for c, v in series.items():
        g = carrier_group.get(c, c)
        segs.setdefault(g, []).append((c, float(v)))
        tot[g] = tot.get(g, 0.0) + float(v)
    tot = pd.Series(tot, dtype=float).sort_values(ascending=False)
    return tot, segs


def group_label(g, segs, nice):
    if g in GROUP_NAMES:
        name = GROUP_NAMES[g]
    else:
        name = nice.get(g, g)
    present = [c for c, v in segs.get(g, []) if abs(v) > 1e-9]
    if len(present) > 1:                      # segment order, left to right
        name += " (" + "|".join(SUB_SHORT.get(c, c) for c in present) + ")"
    return name


def _dots(ax, rows, y_of, styles, xmax):
    """Draw validation dots; rows = DataFrame with columns carrier (or country), value, source_short; y_of: key -> y."""
    if rows is None or not len(rows):
        return xmax
    srcs = [s for s in styles if s in set(rows.source_short)]
    k = len(srcs)
    for i, s in enumerate(srcs):
        col, mk = styles[s]
        r = rows[rows.source_short == s]
        off = (i - (k - 1) / 2) * 0.22 if k > 1 else 0.0
        ys = [y_of[key] + off for key in r["_key"]]
        ax.scatter(r.value.values, ys, s=16, marker=mk, color=col, edgecolor="white", linewidth=0.5, zorder=5)
        xmax = max(xmax, float(r.value.max()))
    return xmax


def _hbars(ax, series, colors, nice, unit, share_of=None, hatch_series=None, hatch_label=None, points=None, styles=None,
           extra_rows=(), total_row=None):
    """Horizontal bars per validation group (segments = model carriers), value labels, optional validation dots.

    series: model values by carrier; hatch_series: 'existing' part by carrier (rest hatched = added).
    points: DataFrame(carrier, value, source_short) for this quantity; rows for carriers absent from the model are
    added with an empty bar so the dot is visible; total_row: model total to show as first row when points have 'total'.
    """
    tot, segs = to_groups(series)
    if hatch_series is not None:
        pre_tot, pre_segs = to_groups(hatch_series.reindex(series.index).fillna(0.0))
    if points is not None and len(points):
        for g in sorted(set(points.carrier) - set(tot.index) - {"total", "other"}):
            tot[g] = 0.0
            segs[g] = []
        tot = tot.sort_values(ascending=False)
    rows_ = list(tot.index)
    if total_row is not None and points is not None and (points.carrier == "total").any():
        rows_ = ["total"] + rows_
        tot["total"] = float(total_row)
    rows_ = rows_ + [r for r in extra_rows if r not in rows_]
    y_of = {g: len(rows_) - 1 - i for i, g in enumerate(rows_)}
    for g in rows_:
        y = y_of[g]
        if g == "total":
            ax.barh(y, tot[g], color="0.8", edgecolor="white", linewidth=0.5)
            continue
        left = 0.0
        for c, v in segs.get(g, []):
            col = colors.get(c, GREY)
            if hatch_series is not None:
                base = min(max(dict(pre_segs.get(g, [])).get(c, 0.0), 0.0), v)
                ax.barh(y, base, left=left, color=col, edgecolor="white", linewidth=0.5)
                ax.barh(y, max(v - base, 0.0), left=left + base, color=col, alpha=0.45, hatch="////", edgecolor="white", linewidth=0.5)
            else:
                ax.barh(y, v, left=left, color=col, edgecolor="white", linewidth=0.5)
            left += v
    ax.set_yticks([y_of[g] for g in rows_], [group_label(g, segs, nice) for g in rows_], fontsize=6.5)
    xmax = float(tot.max()) if len(tot) else 1.0
    pts = None
    if points is not None and len(points):
        pts = points[points.carrier.isin(rows_)].assign(_key=lambda x: x.carrier)
        xmax = _dots(ax, pts, y_of, styles, xmax)
    for g in rows_:
        v = float(tot.get(g, 0.0))
        txt = f"{v:,.0f}" if v >= 10 else (f"{v:,.1f}" if v >= 0.1 else f"{v:,.2f}")
        if isinstance(share_of, pd.Series) and g != "total":
            sh = share_of.reindex(GROUPS.get(g, [g])).sum()
            txt += f" ({100 * v / sh:.1f}%)" if sh > 0 else ""
        elif share_of and g != "total":
            txt += f" ({100 * v / share_of:.0f}%)"
        xr = v
        if pts is not None:
            near = pts[(pts.carrier == g)]
            if len(near):
                xr = max(v, float(near.value.max()))
        ax.text(xr + 0.015 * xmax, y_of[g], txt, va="center", fontsize=6.5)
    ax.set_xlim(0, xmax * 1.35 if xmax > 0 else 1)
    ax.set_ylim(-0.6, max(len(rows_) - 0.4, 0.6))
    ax.set_xlabel(unit, fontsize=7, labelpad=1)
    ax.tick_params(axis="x", labelsize=6.5)
    ax.spines[["top", "right"]].set_visible(False)
    if hatch_label:
        ax.text(0.98, 0.02, hatch_label, transform=ax.transAxes, ha="right", va="bottom", fontsize=6, color="0.35")


def _pts(points, quantity, country=None):
    if points is None or not len(points):
        return None
    p = points[points.quantity == quantity]
    if country is not None:
        p = p[p.country == country]
    return p


def draw_block(fig, cell, d, colors, nice, title, points=None, styles=None):
    gs = GridSpecFromSubplotSpec(4, 2, subplot_spec=cell, wspace=0.55, hspace=0.75)
    axes = [fig.add_subplot(gs[r, c]) for r in range(4) for c in range(2)]
    for ax in axes:
        ax.tick_params(labelsize=6.5)
    ts = dict(fontsize=7.5, fontweight="bold", loc="left", pad=3)
    region_pts = points[points.country == ""] if points is not None and len(points) else None

    # 1 generation mix
    ax = axes[0]
    _hbars(ax, d["mix_twh"], colors, nice, "TWh/a", share_of=d["demand_twh"], points=_pts(region_pts, "generation"), styles=styles,
           total_row=d["generation_twh"])
    ax.set_title(f"Generation mix  ({d['generation_twh']:,.0f} TWh, % of demand)", **ts)

    # 2 installed capacity
    ax = axes[1]
    cap = d["cap_gw"]
    _hbars(ax, cap["opt"], colors, nice, "GW", hatch_series=cap["pre"], hatch_label="hatched = added by the optimiser",
           points=_pts(region_pts, "capacity"), styles=styles)
    st = ", ".join(f"{c} {v:,.0f}" for c, v in d["store_gwh"].items() if v > 0.5)
    ax.set_title("Installed capacity" + (f"  (stores {st} GWh)" if st else ""), **ts)
    l0, l1 = d["lines_gwkm"]
    c0, c1 = d["dc_gw"]
    ax.text(0.98, 0.14, f"AC lines {l0:,.0f} → {l1:,.0f} GW·km\nHVDC {c0:,.0f} → {c1:,.0f} GW", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=6, color="0.35")

    # 3 price statistics: duration curve + band + validation levels
    ax = axes[2]
    p = d["price_hourly"].dropna()
    ps = d["price_stats"]
    hpt = 8760.0 / max(len(p), 1)                       # hours per snapshot (3 for the 3-hourly runs)
    ax.plot(np.arange(len(p)) * hpt, np.sort(p.values)[::-1], color="k", lw=1.0)
    band = d["price_band"].dropna()
    if len(band):
        lo, hi = np.sort(band.p05.values)[::-1], np.sort(band.p95.values)[::-1]
        ax.fill_between(np.arange(len(lo)) * hpt, lo, hi, color="tab:blue", alpha=0.2, lw=0)
    top = float(np.nanpercentile(p.values, 99)) if len(p) else 1.0
    pp = _pts(region_pts, "price")
    if pp is not None and len(pp):
        top = max(top, float(pp.value.max()) * 1.05)
    ylo, yhi = min(0, ps["min"]) - 0.02 * top, max(top * 1.15, 1)
    ax.set_ylim(ylo, yhi)
    ax.set_xlim(0, 8760)
    if pp is not None and len(pp):
        pp = pp.sort_values("value")
        step = 0.075 * (yhi - ylo)
        ytxt, last = [], -np.inf
        for v in pp.value:
            yy = max(v, last + step)
            ytxt.append(yy)
            last = yy
        for (s, v), yy in zip(zip(pp.source_short, pp.value), ytxt):
            col, mk = styles.get(s, ("k", "o"))
            ax.axhline(v, color=col, lw=0.8, ls=(0, (4, 2)), zorder=4)
            ax.text(8760 * 0.99, yy + 0.01 * (yhi - ylo), f"{s}: {v:,.0f}", color=col, fontsize=6, ha="right", va="bottom", zorder=6)
    ax.set_xlabel("hours (sorted)", fontsize=7, labelpad=1)
    ax.set_ylabel("EUR/MWh", fontsize=7, labelpad=1)
    ax.spines[["top", "right"]].set_visible(False)
    txt = (f"load-weighted mean {ps['mean']:,.1f}\nmedian {ps['median']:,.1f}   p95 {ps['p95']:,.0f}\n"
           f"max {ps['max']:,.0f}   min {ps['min']:,.1f}\nbus means {ps['bus_mean_spread'][0]:,.0f}–{ps['bus_mean_spread'][1]:,.0f}")
    if ps["share_shed_bus_h"] > 0:
        txt += (f"\nexcl. shedding-priced bus-hours ({ps['share_shed_bus_h']:.1f} %):\n  load-weighted mean {ps['mean_ok']:,.1f}")
    if np.isfinite(d["co2_price"]):
        txt += f"\nCO2 shadow price {d['co2_price']:,.0f} EUR/t"
    ax.text(0.03, 0.05, txt, transform=ax.transAxes, fontsize=6, va="bottom", ha="left",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="0.8", lw=0.5))
    ax.set_title("Price  (load-wtd; band 5–95 % of buses; dashed: published)", **ts)

    # 4 demand: annual TWh per country (+ total row when region-level points exist)
    ax = axes[3]
    dem = d["demand_by_country"]
    multi = len(dem) > 1
    pd_ = _pts(points, "demand")
    rows_ = list(dem.index)
    vals = dem.copy()
    if multi and pd_ is not None and (pd_.country == "").any():
        rows_ = ["total"] + rows_
        vals["total"] = d["demand_twh"]
    y_of = {c: len(rows_) - 1 - i for i, c in enumerate(rows_)}
    cmap = plt.get_cmap("tab20")
    for i, c in enumerate(rows_):
        ax.barh(y_of[c], vals[c], color="0.8" if c == "total" else (cmap(i % 20) if multi else "#4a6fa5"), edgecolor="white", linewidth=0.5)
    xmax = float(vals.max())
    if pd_ is not None and len(pd_):
        key = pd_.country.where(pd_.country != "", "total" if multi else dem.index[0])
        pdd = pd_.assign(_key=key)
        pdd = pdd[pdd._key.isin(rows_)]
        xmax = _dots(ax, pdd, y_of, styles, xmax)
    for c in rows_:
        v = float(vals[c])
        xr = v
        if pd_ is not None and len(pd_):
            near = pdd[pdd._key == c]
            if len(near):
                xr = max(v, float(near.value.max()))
        ax.text(xr + 0.015 * xmax, y_of[c], f"{v:,.0f}", va="center", fontsize=6.5)
    ax.set_yticks([y_of[c] for c in rows_], ["Total" if c == "total" else str(c) for c in rows_], fontsize=6.5 if len(rows_) <= 8 else 5.5)
    ax.set_xlim(0, xmax * 1.35)
    ax.set_ylim(-0.6, len(rows_) - 0.4)
    ax.set_xlabel("TWh/a", fontsize=7, labelpad=1)
    ax.spines[["top", "right"]].set_visible(False)
    if d["shed_twh"] > 1e-6:
        ax.text(0.98, 0.02, f"load shedding {d['shed_twh']:.2f} TWh ({100 * d['shed_twh'] / d['demand_twh']:.2f} % of demand, {d['shed_hours']} snapshots)",
                transform=ax.transAxes, fontsize=6, va="bottom", ha="right", color="#dd2e23")
    ax.set_title(f"Demand  {d['demand_twh']:,.0f} TWh/a, peak {d['peak_gw']:,.0f} GW", **ts)

    # 5 emissions
    ax = axes[4]
    pe = _pts(region_pts, "emissions")
    if len(d["emissions_mt"]) or (pe is not None and len(pe)):
        em = d["emissions_mt"] if len(d["emissions_mt"]) else pd.Series(dtype=float)
        _hbars(ax, em, colors, nice, "Mt CO2/a", points=pe, styles=styles, total_row=d["emissions_total"])
    else:
        ax.text(0.5, 0.5, "no CO2 emissions", ha="center", va="center", fontsize=8, transform=ax.transAxes)
        ax.set_axis_off()
    lim = d["co2_limit"]
    cap_txt = f", cap {lim / 1e6:,.1f} Mt" if np.isfinite(lim) else ", no cap"
    ax.set_title(f"CO2 emissions  {d['emissions_total']:,.1f} Mt/a{cap_txt}  ({1e3 * d['emissions_total'] / d['demand_twh']:.0f} g/kWh)", **ts)

    # 6 curtailment
    ax = axes[5]
    cu = d["curtailment"]
    if len(cu) and cu.curtailed.sum() > 1e-3:
        c_series = cu.curtailed.sort_values(ascending=False)
        _hbars(ax, c_series, colors, nice, "TWh/a (share of available)", share_of=cu.available)
        tot, av = cu.curtailed.sum(), cu.available.sum()
        ax.set_title(f"Curtailment  {tot:,.0f} TWh/a  ({100 * tot / av:.0f} % of {av:,.0f} avail.)", **ts)
    elif len(cu):
        ax.text(0.5, 0.5, f"no curtailment\n({cu.available.sum():,.0f} TWh available from variable generators)",
                ha="center", va="center", fontsize=7, transform=ax.transAxes, color="0.35")
        ax.set_axis_off()
        ax.set_title("Curtailment  0.0 TWh/a", **ts)
    else:
        ax.text(0.5, 0.5, "no variable generators", ha="center", va="center", fontsize=8, transform=ax.transAxes)
        ax.set_axis_off()
        ax.set_title("Curtailment", **ts)

    # 7 system cost
    ax = axes[6]
    cost = d["cost_bn"]
    ccols = ["0.55", "#2a9d8f", "#8a1caf", "#e76f51"]
    bottom = 0.0
    for (k, v), col in zip(cost.items(), ccols):
        ax.bar([0], [v], bottom=bottom, color=col, width=0.5, label=f"{k}: {v:,.1f}")
        bottom += v
    if d["shed_penalty_bn"] > 1e-3:
        ax.plot([], [], " ", label=f"+ load shedding penalty {d['shed_penalty_bn']:,.0f} bn (in objective, not in total)")
    ax.set_xlim(-0.4, 4.0)
    ax.set_xticks([])
    ax.set_ylabel("bn EUR/a", fontsize=7, labelpad=1)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(fontsize=5.5, loc="upper left", bbox_to_anchor=(0.17, 1.0), frameon=False)
    ax.set_title(f"Total system cost  {d['cost_total_bn']:,.1f} bn EUR/a  ({d['cost_per_mwh']:,.0f} EUR/MWh)", **ts)

    # 8 summary
    ax = axes[7]
    ax.set_axis_off()
    mt = d["meta"]
    lines = [
        f"run {mt['run']}, opts '{mt['opts']}', ll {mt['ll']}",
        f"costs {mt['cost_year']}, {d['n_buses']} AC buses, {d['hours']} snapshots",
        "",
        f"Demand       {d['demand_twh']:>8,.0f} TWh",
        f"Peak load    {d['peak_gw']:>8,.0f} GW",
        f"Generation   {d['generation_twh']:>8,.0f} TWh",
        f"Shedding     {d['shed_twh']:>8,.2f} TWh ({d['shed_hours']} h)",
        f"CO2          {d['emissions_total']:>8,.1f} Mt ({1e3 * d['emissions_total'] / d['demand_twh']:.0f} g/kWh)",
        f"Price        {ps['mean']:>8,.1f} EUR/MWh (lw mean)",
        f"  excl. shed {ps['mean_ok']:>8,.1f} EUR/MWh",
        f"System cost  {d['cost_total_bn']:>8,.1f} bn/a ({d['cost_per_mwh']:,.0f} EUR/MWh)",
        f"Objective    {d['objective_bn']:>8,.1f} bn EUR",
    ]
    if np.isfinite(d["co2_price"]):
        lines.append(f"CO2 price    {d['co2_price']:>8,.0f} EUR/t (shadow)")
    chg = d["storage_charge_twh"].sort_values(ascending=False).head(2)
    for c, v in chg.items():
        if v > 0.05:
            lines.append(f"{nice.get(c, c)[:12]:<12} {v:>8,.1f} TWh charged")
    ax.text(0.0, 1.0, "\n".join(lines), transform=ax.transAxes, va="top", ha="left", fontsize=6.3, family="monospace")
    ax.set_title("Summary", **ts)

    # block title + source legend
    x0, x1 = cell.get_position(fig).x0, cell.get_position(fig).x1
    y1 = cell.get_position(fig).y1
    fig.text((x0 + x1) / 2, y1 + 0.042, title, ha="center", va="bottom", fontsize=10.5, fontweight="bold")
    if styles:
        from matplotlib.lines import Line2D
        used = [s for s in styles if points is not None and (points.source_short == s).any()]
        handles = [Line2D([], [], marker=styles[s][1], color=styles[s][0], ls="", markersize=4, markeredgecolor="white",
                          markeredgewidth=0.5) for s in used]
        fig.legend(handles, [f"{s}" for s in used], loc="center", bbox_to_anchor=((x0 + x1) / 2, y1 + 0.022),
                   ncol=len(used), fontsize=6 if len(used) <= 5 else 5.2, frameon=False, handletextpad=0.3,
                   columnspacing=1.0, title=None)   # keep <= 6 sources per block (one legend row)


def scenario_title(d, label=None):
    mt = d["meta"]
    opts = mt["opts"] or ""
    detail = f"opts '{opts}', costs {mt['cost_year']}, ll {mt['ll']}"
    if label:
        return f"{label}  ({detail})"
    scen = mt["scenario"] or ("zero" if "Co2L0" in opts else ("now" if "Co2L" not in opts else ""))
    names = {"now": "current system, no CO2 cap", "zero": "carbon-neutral, CO2 = 0"}
    return f"{names[scen]}  ({detail})" if scen in names else detail


def make_page(networks, out, page_title=None, labels=None, points_csv=None):
    fig = plt.figure(figsize=(16, 9), dpi=150)
    k = len(networks)
    gs = fig.add_gridspec(1, k, left=0.08, right=0.985, top=0.87, bottom=0.06, wspace=0.3)
    for i, n in enumerate(networks):
        d = collect(n)
        colors, nice = carrier_style(n)
        lab = labels[i] if labels and i < len(labels) else None
        reg = d["meta"]["run"].rsplit("-", 1)[0] if d["meta"]["scenario"] else ""
        scen = d["meta"]["scenario"] or ("zero" if "Co2L0" in (d["meta"]["opts"] or "") else "now")
        pts, styles = load_points(points_csv, reg, scen)
        draw_block(fig, gs[0, i], d, colors, nice, scenario_title(d, lab), points=pts, styles=styles)
        if page_title is None:
            reg_t = reg or d["meta"]["run"].rsplit("-", 1)[0] or "+".join(d["countries"])
            ncl = d["meta"]["clusters"] or d["n_buses"]
            page_title = f"{reg_t}  |  {ncl} clusters"
            if len(d["countries"]) > 1:
                page_title += f"  |  {', '.join(d['countries'])}"
    if k == 2:
        fig.add_artist(plt.Line2D([0.515, 0.515], [0.04, 0.91], color="0.75", lw=0.8, transform=fig.transFigure))
    fig.suptitle(page_title, fontsize=14, fontweight="bold", y=0.975)
    fig.text(0.985, 0.012, "Catalyst screening: pypsa-earth fork, weather 2013, GEGIS SSP2-2.6 2030 demand, "
             "existing fleet ≈2022 + IRENA 2023 wind/solar; 'existing fleet' annuity not part of the objective. "
             "Dots / dashed levels: published statistics (left) and 2050 outlooks (right), see legend",
             ha="right", va="bottom", fontsize=6, color="0.4")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fig.savefig(out)
    plt.close(fig)


if __name__ == "__main__":
    if "snakemake" in globals():
        inp = snakemake.input  # noqa: F821
        files = [inp.network] if hasattr(inp, "network") else [inp.now, inp.zero]
        make_page([pypsa.Network(f) for f in files], snakemake.output[0],  # noqa: F821
                  points_csv=inp.points if hasattr(inp, "points") else None)
    else:
        ap = argparse.ArgumentParser()
        ap.add_argument("networks", nargs="+")
        ap.add_argument("-o", "--out", required=True)
        ap.add_argument("--title")
        ap.add_argument("--points", help="validation_points.csv from build_validation.py")
        a = ap.parse_args()
        make_page([pypsa.Network(f) for f in a.networks], a.out, a.title, points_csv=a.points)
