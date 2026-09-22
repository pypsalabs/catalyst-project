"""Fit experience curves per technology and component; write the numbers the dashboards show.

Observations come from data/learning/schmidt2018.csv (parsed open dataset) and
data/learning/manual.csv (hand-curated rows), one row per (technology,
component, year): unit cost with currency and price year, cumulative installed
capacity, scope, series id, `derived` (a series computed from another one via a
constant ratio; never fitted) and `context` (a different scope, drawn hollow,
never fitted). Costs are converted to the base currency/year of config.yaml
with the shared FX/CPI tables; a currency conversion only shifts the intercept.

Three estimates per component, on the fitted series only:

  level     ln c = a - b ln z (OLS); experience rate LR = 1 - 2^-b; standard
            error, 95 % CI and p-value against b = 0 from the t distribution
            with n - 2 degrees of freedom; R²; residual std; 95 % confidence
            band of the fitted line for the plot
  first     d ln c = -ω d ln z + η on consecutive points, no intercept
            (Lafond et al. 2018 / Way et al. 2022): ω̂, σ̂ω, σ̂η and the lag-1
            autocorrelation of the residuals (reported, not imposed)
  time      ln c = α - μ year (Moore's law) as a cross-check: annual decline
            1 - e^-μ, plus the Wright exponent it implies through the mean
            growth rate of ln z (Sahal identity b = μ / g)

plus n, years, doublings covered, scope, numbered sources, and three flags:
`n_lt_min` (fewer fit points than learning.min_points), `chained` (the fit
pools more than one series), `no_rate` (fewer than two fit points).

Modes: `fit` writes build/learning/<tech>.json; `summary` collects every json
into build/learning_rates.csv.

Run standalone:  python fit_learning.py vrfb   |   python fit_learning.py --summary
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy import stats

from common import make_to_base, split_currency

if "snakemake" in globals():
    CFG = snakemake.config
    MODE = snakemake.params.mode
    _HERE = Path(snakemake.input.config).resolve().parent
    if MODE == "fit":
        TECH = snakemake.params.tech
        IN_OBS = [Path(snakemake.input.schmidt), Path(snakemake.input.manual)]
        IN_FLOORS = Path(snakemake.input.floors)
        IN_PUB = Path(snakemake.input.published)
        IN_COSTS = Path(snakemake.input.costs)
        OUT = Path(snakemake.output[0])
    else:
        IN_FITS = [Path(p) for p in snakemake.input.fits]
        OUT = Path(snakemake.output[0])
else:
    _HERE = Path(__file__).resolve().parent
    CFG = yaml.safe_load((_HERE / "config.yaml").read_text())
    MODE = "summary" if "--summary" in sys.argv else "fit"
    if MODE == "fit":
        TECH = sys.argv[1] if len(sys.argv) > 1 else "vrfb"
        IN_OBS = [_HERE / "data" / "learning" / "schmidt2018.csv", _HERE / "data" / "learning" / "manual.csv"]
        IN_FLOORS = _HERE / "data" / "learning" / "floors.csv"
        IN_PUB = _HERE / "data" / "learning" / "schmidt2018_published.csv"
        IN_COSTS = _HERE / "build" / "costs_2025_compiled.csv"
        OUT = _HERE / "build" / "learning" / f"{TECH}.json"
    else:
        IN_FITS = sorted((_HERE / "build" / "learning").glob("*.json"))
        OUT = _HERE / "build" / "learning_rates.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

LEARN = CFG["learning"]
TECHS = LEARN["technologies"]
PALETTE = {t["key"]: t for t in CFG["technologies"]}
BASE = f"{CFG['base_currency']}{CFG['base_currency_year']}"
MIN_POINTS = int(LEARN.get("min_points", 5))
NOT_FITTED = LEARN.get("not_fitted", {})
SCHMIDT_CITATION = str(LEARN["schmidt"].get("citation", "Schmidt et al. (2017)"))          # series id -> why it is drawn but never fitted
to_base = make_to_base(CFG)

# capacity to GWh (energy) or GW (power/plant); wells and units stay as they are
CAP_FACTOR = {"kwh": 1e-6, "mwh": 1e-3, "gwh": 1.0, "twh": 1e3, "kw": 1e-6, "mw": 1e-3, "gw": 1.0,
              "tw": 1e3, "wells": 1.0, "units": 1.0}
CAP_LABEL = {"kwh": "GWh", "mwh": "GWh", "gwh": "GWh", "twh": "GWh", "kw": "GW", "mw": "GW", "gw": "GW",
             "tw": "GW", "wells": "wells", "units": "units"}
# cost per kWh / per kW / per well; MWh and MW quotes are divided by 1000
VAL_FACTOR = {"kwh": (1.0, "kWh"), "mwh": (1e-3, "kWh"), "kw": (1.0, "kW"), "mw": (1e-3, "kW"),
              "well": (1.0, "well"), "unit": (1.0, "unit"), "ft": (1.0, "ft"), "m": (1.0, "m")}
DEFAULT_UNIT = {"energy": ("kWh", "GWh"), "power": ("kW", "GW"), "plant": ("kW", "GW"), "drilling": ("ft", "wells")}


# --- data -------------------------------------------------------------------------------------

def load_observations(paths):
    frames = [pd.read_csv(p) for p in paths if p.exists() and p.stat().st_size > 0]
    obs = pd.concat([f for f in frames if len(f)], ignore_index=True)
    for col, default in (("derived", False), ("context", False), ("scope", ""), ("note", ""), ("url", ""),
                         ("citation", ""),
                         ("fx_mode", "price_year")):
        if col not in obs:
            obs[col] = default
        obs[col] = obs[col].fillna(default)
    obs["derived"] = obs["derived"].astype(str).str.lower().isin(("true", "1"))
    obs["context"] = obs["context"].astype(str).str.lower().isin(("true", "1"))
    obs = obs[obs["technology"].fillna("").astype(str).str.len() > 0].copy()
    unknown = set(obs["technology"]) - set(PALETTE)
    assert not unknown, f"observations for technologies not in config.yaml: {sorted(unknown)}"
    vals, units, caps, cap_units, notes = [], [], [], [], []
    for _, r in obs.iterrows():
        cur, rest = split_currency(str(r["unit"]).strip())
        rest = rest.strip().lower().replace("_e", "").replace("el", "")
        if rest not in VAL_FACTOR:
            raise ValueError(f"cannot read cost unit {r['unit']!r} ({r['technology']}, {r['series']})")
        f, per = VAL_FACTOR[rest]
        v, n = to_base(float(r["value"]) * f, r["currency"] if pd.notna(r["currency"]) else cur, r["currency_year"],
                       mode=str(r["fx_mode"]) if r["fx_mode"] else "price_year")
        cu = str(r["capacity_unit"]).strip().lower()
        if cu not in CAP_FACTOR:
            raise ValueError(f"cannot read capacity unit {r['capacity_unit']!r} ({r['technology']}, {r['series']})")
        vals.append(v); units.append(f"{BASE}/{per}")
        caps.append(float(r["capacity"]) * CAP_FACTOR[cu]); cap_units.append(CAP_LABEL[cu])
        notes.append("; ".join(x for x in (str(r["note"]) if r["note"] else "", n) if x))
    obs["value_base"] = vals
    obs["unit_base"] = units
    obs["capacity_base"] = caps
    obs["capacity_unit_base"] = cap_units
    obs["note"] = notes
    return obs


def load_floors(path):
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    fl = pd.read_csv(path)
    if not len(fl):
        return fl
    if "value_hi" not in fl:
        fl["value_hi"] = np.nan
    vals, his = [], []
    for _, r in fl.iterrows():
        cur, rest = split_currency(str(r["unit"]).strip())
        f, _ = VAL_FACTOR[rest.strip().lower()]
        c = r["currency"] if pd.notna(r["currency"]) else cur
        vals.append(to_base(float(r["value"]) * f, c, r["currency_year"])[0])
        his.append(to_base(float(r["value_hi"]) * f, c, r["currency_year"])[0] if pd.notna(r["value_hi"]) else np.nan)
    fl["value_base"] = vals
    fl["value_hi_base"] = his   # optional upper end of a reference band
    return fl


# --- statistics ---------------------------------------------------------------------------------

def _ci(est, se, dof):
    if not np.isfinite(se) or dof < 1:
        return np.nan, np.nan
    t = stats.t.ppf(0.975, dof)
    return est - t * se, est + t * se


def level_fit(logz, logc, extend_to=None):
    """OLS ln c = a - b ln z with t-based uncertainty (dof = n - 2)."""
    n = len(logz)
    if n < 2:
        return None
    x, y = np.asarray(logz), np.asarray(logc)
    xm, ym = x.mean(), y.mean()
    sxx = ((x - xm) ** 2).sum()
    if sxx == 0:
        return None
    slope = ((x - xm) * (y - ym)).sum() / sxx
    a = ym - slope * xm
    resid = y - (a + slope * x)
    dof = n - 2
    sigma = np.sqrt((resid ** 2).sum() / dof) if dof > 0 else np.nan
    se = sigma / np.sqrt(sxx) if dof > 0 else np.nan
    b = -slope
    lo, hi = _ci(b, se, dof)
    p = 2 * stats.t.sf(abs(b) / se, dof) if dof > 0 and se > 0 else np.nan
    sst = ((y - ym) ** 2).sum()
    r2 = 1 - (resid ** 2).sum() / sst if sst > 0 else np.nan
    span = x.max() - x.min() or 1
    x_hi = max(x.max(), extend_to) if extend_to is not None else x.max()   # band drawn out to the model-start capacity
    grid = np.linspace(x.min() - 0.15 * span, x_hi + 0.15 * span, 60)
    band = None
    if dof > 0:
        t = stats.t.ppf(0.975, dof)
        se_mean = sigma * np.sqrt(1 / n + (grid - xm) ** 2 / sxx)
        band = {"logz": grid.tolist(), "lo": (a + slope * grid - t * se_mean).tolist(),
                "hi": (a + slope * grid + t * se_mean).tolist()}
    return {"n": n, "a": a, "b": b, "se_b": se, "b_lo": lo, "b_hi": hi, "p_b": p, "r2": r2, "sigma": sigma,
            "dof": dof, "lr": 1 - 2 ** -b, "lr_lo": 1 - 2 ** -lo if np.isfinite(lo) else np.nan,
            "lr_hi": 1 - 2 ** -hi if np.isfinite(hi) else np.nan,
            "se_lr": np.log(2) * 2 ** -b * se if np.isfinite(se) else np.nan, "band": band}


def first_difference_fit(logz, logc):
    """d ln c = -ω d ln z + η on consecutive points, no intercept (Lafond et al. 2018)."""
    if len(logz) < 2:
        return None
    dz, dc = np.diff(np.asarray(logz)), np.diff(np.asarray(logc))
    m = len(dz)
    szz = (dz ** 2).sum()
    if szz == 0:
        return None
    omega = -(dz * dc).sum() / szz
    resid = dc + omega * dz
    sigma_eta = np.sqrt((resid ** 2).sum() / (m - 1)) if m > 1 else np.nan
    sigma_omega = sigma_eta / np.sqrt(szz) if m > 1 else np.nan
    rho1 = np.corrcoef(resid[1:], resid[:-1])[0, 1] if m > 2 and resid.std() > 0 else np.nan
    return {"m": m, "omega": omega, "sigma_omega": sigma_omega, "sigma_eta": sigma_eta, "rho1": rho1,
            "lr": 1 - 2 ** -omega, "zero_steps": int((dz == 0).sum())}


def time_fit(years, logz, logc):
    """ln c = α - μ year; annual decline 1 - e^-μ; implied Wright exponent μ / g (Sahal)."""
    yrs = np.asarray(years, dtype=float)
    if len(np.unique(yrs)) < 3:
        return None
    fit = level_fit(yrs, logc)            # slope sign convention: b = -slope = μ
    if fit is None:
        return None
    mu = fit["b"]
    span = yrs.max() - yrs.min()
    g = (np.asarray(logc) * 0 + np.asarray(logz))[-1] - np.asarray(logz)[0]
    g = g / span if span > 0 else np.nan
    return {"n": fit["n"], "mu": mu, "se_mu": fit["se_b"], "mu_lo": fit["b_lo"], "mu_hi": fit["b_hi"],
            "p_mu": fit["p_b"], "r2": fit["r2"], "annual_decline": 1 - np.exp(-mu),
            "decline_lo": 1 - np.exp(-fit["b_lo"]) if np.isfinite(fit["b_lo"]) else np.nan,
            "decline_hi": 1 - np.exp(-fit["b_hi"]) if np.isfinite(fit["b_hi"]) else np.nan,
            "g": g, "b_implied": mu / g if g and np.isfinite(g) and g != 0 else np.nan}


# --- per technology -------------------------------------------------------------------------------

def fit_component(obs, tech, component, floors, published):
    spec = TECHS[tech]
    rows = obs[(obs["technology"] == tech) & (obs["component"] == component)].copy()
    rows = rows.sort_values(["year", "capacity_base"], kind="stable")
    fit_series = (spec.get("fit") or {}).get(component)
    eligible = ~rows["derived"] & ~rows["context"] & (rows["value_base"] > 0) & (rows["capacity_base"] > 0)
    if fit_series:
        eligible &= rows["series"].isin(fit_series)
    rows["in_fit"] = eligible
    fit = rows[rows["in_fit"]]
    # numbered sources: fitted series first, then context
    src_order = list(dict.fromkeys(list(fit["source"]) + list(rows.loc[~rows["in_fit"], "source"])))
    src_no = {s: i + 1 for i, s in enumerate(src_order)}
    points = [{"year": int(r["year"]) if pd.notna(r["year"]) else None, "z": float(r["capacity_base"]),
               "c": float(r["value_base"]), "scope": str(r["scope"]), "series": str(r["series"]),
               "source": int(src_no[r["source"]]), "in_fit": bool(r["in_fit"]), "derived": bool(r["derived"]),
               "context": bool(r["context"]), "note": str(r["note"]),
               "reason": ("" if r["in_fit"] else "derived from another series" if r["derived"]
                          else NOT_FITTED.get(str(r["series"]), "not in the fitted series"))}
              for _, r in rows.iterrows()]
    unit = rows["unit_base"].iloc[0] if len(rows) else f"{BASE}/{DEFAULT_UNIT.get(component, ('kW', 'GW'))[0]}"
    cap_unit = rows["capacity_unit_base"].iloc[0] if len(rows) else DEFAULT_UNIT.get(component, ("kW", "GW"))[1]
    if len(rows) and rows["unit_base"].nunique() > 1:
        raise ValueError(f"{tech}/{component}: mixed cost units {sorted(rows['unit_base'].unique())}")
    if len(fit) and fit["capacity_unit_base"].nunique() > 1:
        raise ValueError(f"{tech}/{component}: mixed capacity units in the fit "
                         f"{sorted(fit['capacity_unit_base'].unique())}")
    logz, logc = np.log(fit["capacity_base"].to_numpy()), np.log(fit["value_base"].to_numpy())
    # `model_capacity` places the model start at an assumed cumulative capacity beyond the series
    # (e.g. series end plus the fleet installed since); the fit and its band are drawn out to it
    mc = spec.get("model_capacity") if spec.get("show_model") is True else None
    level = level_fit(logz, logc, extend_to=np.log(float(mc["value"])) if mc else None)
    fd = first_difference_fit(logz, logc)
    tm = time_fit(fit["year"].to_numpy(), logz, logc) if fit["year"].notna().all() else None
    summary = {
        "n": int(len(fit)), "n_context": int((~rows["in_fit"]).sum()),
        "year_min": int(fit["year"].min()) if len(fit) else None,
        "year_max": int(fit["year"].max()) if len(fit) else None,
        "doublings": float(np.log2(fit["capacity_base"].max() / fit["capacity_base"].min())) if len(fit) > 1 else None,
        "scopes": sorted(set(fit["scope"].astype(str))), "series": list(dict.fromkeys(fit["series"])),
        "sources": [{"n": i + 1, "source": s, "url": str(rows.loc[rows["source"] == s, "url"].iloc[0]),
                     "citation": str(rows.loc[rows["source"] == s, "citation"].iloc[0]) or
                                 (SCHMIDT_CITATION if str(rows.loc[rows["source"] == s, "series"].iloc[0]).startswith("schmidt2018") else s)}
                    for i, s in enumerate(src_order)],
        "flags": {"n_lt_min": bool(0 < len(fit) < MIN_POINTS), "chained": bool(fit["series"].nunique() > 1),
                  "no_rate": bool(len(fit) < 2)},
    }
    floor = None
    if len(floors):
        f = floors[(floors["technology"] == tech) & (floors["component"] == component)]
        if len(f):
            f = f.iloc[0]
            floor = {"value": float(f["value_base"]), "kind": str(f.get("kind", "floor")), "source": str(f["source"]),
                     "label": str(f["label"]) if "label" in f and pd.notna(f["label"]) and str(f["label"]) else "",
                     "value_hi": float(f["value_hi_base"]) if pd.notna(f["value_hi_base"]) else None,
                     "url": str(f.get("url", "")), "note": str(f.get("note", ""))}
    analogy = spec.get("analogy")
    if analogy:
        analogy = {"rate": float(analogy["rate"]), "b": -np.log2(1 - float(analogy["rate"])),
                   "label": analogy.get("label", "")}
    pub = None
    if len(published):
        p = published[published["series"].isin(summary["series"]) & (published["component"] == component)]
        if len(p):
            pub = [{"block": r["block"], "b": float(r["b"]), "sigma": float(r["sigma"]), "ER": str(r["ER"]),
                    "n": int(r["n"])} for _, r in p.iterrows()]
    # model start: `show_model: true` = level fit at today's cumulative capacity (top-down);
    # `show_model: baseline` = the 2025 cost baseline of this workflow (bottom-up, build/costs_2025_compiled.csv)
    model = None
    if spec.get("show_model") == "baseline":
        param = {"plant": "investment", "energy": "investment_kwh", "power": "investment_kw"}[component]
        costs = pd.read_csv(IN_COSTS)
        row = costs[(costs["technology"] == tech) & (costs["parameter"] == param)]
        if len(row):
            row = row.iloc[0]
            if str(row["unit"]).split("/")[-1] != str(unit).split("/")[-1]:
                raise ValueError(f"{tech}/{component}: baseline unit {row['unit']} does not match {unit}")
            model = {"z": None, "year": int(CFG["base_currency_year"]) + 1, "c": float(row["value"]),
                     "source": str(row["source"]), "url": str(row["url"]), "origin": str(row["origin"])}
    elif level and level.get("a") is not None and len(fit):
        if mc:
            assert str(mc.get("unit", cap_unit)) == str(cap_unit), f"{tech}/{component}: model_capacity unit"
            model = {"z": float(mc["value"]), "year": int(mc["year"]), "source": str(mc.get("source", "")),
                     "url": str(mc.get("url", "")), "note": str(mc.get("note", ""))}
        else:
            last = fit.loc[fit["capacity_base"].idxmax()]
            model = {"z": float(last["capacity_base"]), "year": int(last["year"]) if pd.notna(last["year"]) else None}
        model["c"] = float(np.exp(level["a"]) * model["z"] ** (-level["b"]))
        add = spec.get("model_add")                  # fixed cost on top of the fit (e.g. installation)
        if add:
            v, _ = to_base(float(add["value"]), str(add["currency"]), int(add["currency_year"]))
            model["c_fit"] = model["c"]
            model["add"] = {"value": float(v), "label": str(add.get("label", "")), "source": str(add.get("source", "")),
                            "note": str(add.get("note", ""))}
            model["c"] = model["c_fit"] + float(v)
    # secondary fits: series listed under `secondary` get their own level fit, drawn as a thin line without band
    secondary = []
    for ser in (spec.get("secondary") or {}).get(component) or []:
        sel = rows[(rows["series"] == ser) & ~rows["derived"] & (rows["value_base"] > 0) & (rows["capacity_base"] > 0)]
        if len(sel) < 2:
            continue
        lz2, lc2 = np.log(sel["capacity_base"].to_numpy()), np.log(sel["value_base"].to_numpy())
        secondary.append({"series": ser, "source": int(src_no[sel["source"].iloc[0]]), "n": int(len(sel)),
                          "year_min": int(sel["year"].min()), "year_max": int(sel["year"].max()),
                          "doublings": float(np.log2(sel["capacity_base"].max() / sel["capacity_base"].min())),
                          "z_min": float(sel["capacity_base"].min()), "z_max": float(sel["capacity_base"].max()),
                          "level": level_fit(lz2, lc2), "first_difference": first_difference_fit(lz2, lc2)})
    return {"component": component, "unit": unit, "capacity_unit": cap_unit, "points": points, "secondary": secondary,
            "level": level, "first_difference": fd, "time": tm, "summary": summary, "floor": floor,
            "analogy": analogy, "published": pub, "model": model}


def clean(o):
    """numpy -> json types; NaN -> None."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def fit_technology(tech):
    assert tech in TECHS, f"{tech!r} is not configured under learning.technologies"
    obs = load_observations(IN_OBS)
    floors = load_floors(IN_FLOORS)
    published = pd.read_csv(IN_PUB) if IN_PUB.exists() else pd.DataFrame()
    comps = [fit_component(obs, tech, c, floors, published) for c in TECHS[tech]["components"]]
    return clean({"technology": tech, "label": PALETTE[tech]["label"], "colour": PALETTE[tech]["colour"],
                  "group": PALETTE[tech].get("group", ""), "base": BASE, "min_points": MIN_POINTS,
                  "components": comps})


def summary_row(fit, comp):
    s, lv, fd, tm = comp["summary"], comp["level"] or {}, comp["first_difference"] or {}, comp["time"] or {}
    pub = comp["published"][0] if comp["published"] else {}
    return {
        "technology": fit["technology"], "label": fit["label"], "component": comp["component"],
        "unit": comp["unit"], "capacity_unit": comp["capacity_unit"], "n": s["n"], "n_context": s["n_context"],
        "model_start_cost": comp["model"]["c"] if comp.get("model") else None,
        "year_min": s["year_min"], "year_max": s["year_max"], "doublings": s["doublings"],
        "b": lv.get("b"), "se_b": lv.get("se_b"), "b_lo": lv.get("b_lo"), "b_hi": lv.get("b_hi"),
        "p_b": lv.get("p_b"), "r2": lv.get("r2"), "sigma": lv.get("sigma"),
        "lr": lv.get("lr"), "lr_lo": lv.get("lr_lo"), "lr_hi": lv.get("lr_hi"), "se_lr": lv.get("se_lr"),
        "omega": fd.get("omega"), "se_omega": fd.get("sigma_omega"), "sigma_eta": fd.get("sigma_eta"),
        "rho1": fd.get("rho1"), "lr_fd": fd.get("lr"),
        "mu": tm.get("mu"), "annual_decline": tm.get("annual_decline"), "decline_lo": tm.get("decline_lo"),
        "decline_hi": tm.get("decline_hi"), "r2_time": tm.get("r2"), "b_implied": tm.get("b_implied"),
        "floor_base": (comp["floor"] or {}).get("value"), "analogy_rate": (comp["analogy"] or {}).get("rate"),
        "published_b": pub.get("b"), "published_er": pub.get("ER"),
        "flag_n_lt_min": s["flags"]["n_lt_min"], "flag_chained": s["flags"]["chained"],
        "flag_no_rate": s["flags"]["no_rate"], "scopes": "|".join(s["scopes"]), "series": "|".join(s["series"]),
        "sources": " ".join(f"[{x['n']}] {x['source']}" for x in s["sources"]),
    }


if MODE == "fit":
    out = fit_technology(TECH)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    for c in out["components"]:
        s, lv = c["summary"], c["level"]
        msg = (f"LR {lv['lr']:.1%} (b {lv['b']:.3f} ± {lv['se_b'] if lv['se_b'] is not None else float('nan'):.3f})"
               if lv else "no rate")
        print(f"{TECH:<16} {c['component']:<7} n={s['n']:>3} ctx={s['n_context']:>3} "
              f"{s['year_min']}-{s['year_max']}  {msg}  flags={[k for k, v in s['flags'].items() if v]}")
else:
    rows = []
    for p in IN_FITS:
        fit = json.loads(Path(p).read_text())
        rows.extend(summary_row(fit, c) for c in fit["components"])
    order = {t: i for i, t in enumerate(TECHS)}
    df = pd.DataFrame(rows)
    df = df.sort_values(["technology", "component"], key=lambda s: s.map(order) if s.name == "technology" else s)
    df.to_csv(OUT, index=False)
    print(df[["technology", "component", "n", "year_min", "year_max", "doublings", "lr", "lr_lo", "lr_hi",
              "lr_fd", "annual_decline", "published_er", "flag_no_rate"]]
          .to_string(index=False, float_format=lambda x: f"{x:.3f}"))
