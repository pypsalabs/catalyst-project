"""Income-driven baseline: fit, backtest, projection.

    ln(kWh per capita)_it = a_i + f(ln GDP per capita_it) [+ tau * t] + e_it        (country fixed effects a_i)

      constant          f = b1 x
      declining         f = b1 x + b2 x^2, held flat beyond the vertex so that demand never falls with income
      declining_trend   declining plus a common linear time trend

Only growth is projected: demand(y) = demand(base) * exp(f(x_y) - f(x_base) [+ tau (y - base)]) * population index.
The backtest fits each specification on the years up to T0 and predicts T1 from the T0 actual with the actual
GDP and population of T1; the specification with the lowest mean demand-weighted absolute error is used.

    build/fit.json        coefficients, elasticities and backtest scores per specification, the selected one
    build/backtest.csv    iso3, window, specification, actual, predicted, error
    build/baseline.csv    iso3, year, baseline_twh, baseline_index
"""

import json
import os
import sys

import numpy as np
import pandas as pd

from common import BUILD, CONFIG, ember_demand, modelled_countries

CFG = CONFIG["baseline"]
BASE = CONFIG["base_year"]


def design(x, t, spec):
    cols = [x] if spec == "constant" else [x, x ** 2]
    if spec == "declining_trend":
        cols.append(t)
    return np.column_stack(cols)


def fit(panel, spec):
    """Within estimator. Returns the coefficient vector (b1[, b2][, tau])."""
    x, t, y = np.log(panel.gdp_pc.values), panel.year.values.astype(float), np.log(panel.kwh_pc.values)
    X = pd.DataFrame(design(x, t, spec))
    g = panel.iso3.values
    Xd = X - X.groupby(g).transform("mean")
    yd = y - pd.Series(y).groupby(g).transform("mean").values
    return np.linalg.lstsq(Xd.values, yd, rcond=None)[0]


def growth(beta, spec, x0, x1, dt):
    """Log change of per-capita demand between income x0 and x1 (logs), dt years apart."""
    if spec == "constant":
        return beta[0] * (x1 - x0)
    b1, b2 = beta[0], beta[1]
    if b2 < 0:                                   # concave: no income effect beyond the vertex
        vertex = -b1 / (2 * b2)
        x0, x1 = np.minimum(x0, vertex), np.minimum(x1, vertex)
    f = lambda x: b1 * x + b2 * x ** 2
    return f(x1) - f(x0) + (beta[2] * dt if spec == "declining_trend" else 0.0)


def elasticity(beta, spec, gdp_pc):
    if spec == "constant":
        return float(beta[0])
    return float(max(beta[0] + 2 * beta[1] * np.log(gdp_pc), 0.0))


def sample(panel, until=None):
    p = panel.dropna()
    p = p[(p.population >= CFG["min_population"]) & (p.demand_twh > 0)]
    if until:
        p = p[p.year <= until]
    return p[p.groupby("iso3").year.transform("size") >= min(CFG["min_observations"], (until or BASE) - 2000)]


def backtest(panel):
    rows = []
    for t0, t1 in CFG["backtest_windows"]:
        train = sample(panel, until=t0)
        a = panel[panel.year == t0].set_index("iso3")
        b = panel[panel.year == t1].set_index("iso3")
        both = a.dropna().index.intersection(b.dropna().index).intersection(train.iso3.unique())
        a, b = a.loc[both], b.loc[both]
        for spec in CFG["specifications"]:
            beta = fit(train, spec)
            g = growth(beta, spec, np.log(a.gdp_pc.values), np.log(b.gdp_pc.values), t1 - t0)
            pred = a.demand_twh.values * np.exp(g) * (b.population.values / a.population.values)
            rows.append(pd.DataFrame({"iso3": both, "window": f"{t0}-{t1}", "specification": spec,
                                      "actual": b.demand_twh.values, "predicted": pred}))
    bt = pd.concat(rows)
    bt["error"] = bt.predicted / bt.actual - 1
    return bt


def scores(bt):
    def one(d):
        return pd.Series({"weighted_abs_error": (d.predicted - d.actual).abs().sum() / d.actual.sum(),
                          "total_error": d.predicted.sum() / d.actual.sum() - 1,
                          "median_abs_error": d.error.abs().median(), "countries": len(d)})
    return bt.groupby(["specification", "window"]).apply(one, include_groups=False)


def main():
    panel = pd.read_csv(os.path.join(BUILD, "panel.csv"))
    panel["kwh_pc"] = panel.demand_twh * 1e9 / panel.population

    bt = backtest(panel)
    sc = scores(bt)
    mean_score = sc.weighted_abs_error.groupby("specification").mean()
    selected = sys.argv[1] if len(sys.argv) > 1 else mean_score.idxmin()     # optional override for sensitivity runs
    bt.to_csv(os.path.join(BUILD, "backtest.csv"), index=False)
    print(sc.round(3).to_string(), "\n\nmean weighted abs error:\n", mean_score.round(3).to_string(), "\nselected:", selected)

    full = sample(panel)
    fits = {}
    for spec in CFG["specifications"]:
        beta = fit(full, spec)
        fits[spec] = {"beta": [float(b) for b in beta],
                      "elasticity_at_gdp_pc": {str(g): round(elasticity(beta, spec, g), 3) for g in (2000, 5000, 10000, 20000, 40000, 80000)},
                      "mean_weighted_abs_error": float(mean_score[spec])}
        print(spec, fits[spec]["beta"], fits[spec]["elasticity_at_gdp_pc"])
    json.dump({"selected": selected, "fit_countries": int(full.iso3.nunique()), "observations": int(len(full)),
               "specifications": fits, "backtest": sc.reset_index().to_dict("records")},
              open(os.path.join(BUILD, "fit.json"), "w"), indent=1)

    # projection for every country with Ember demand and SSP population
    dem = ember_demand()
    dem = dem[dem.year <= BASE].sort_values("year").groupby("iso3").last()
    drv = pd.read_csv(os.path.join(BUILD, "drivers.csv"))
    drv = drv[drv.iso3.isin(dem.index)]
    beta = np.array(fits[selected]["beta"])
    x0 = np.log(drv.gdp_pc_base.values)
    g = growth(beta, selected, x0, x0 + np.log(drv.gdp_pc_index.values), drv.year.values - BASE)
    drv["baseline_index"] = np.exp(g) * drv.pop_index
    drv["baseline_twh"] = drv.iso3.map(dem.demand_twh) * drv.baseline_index
    drv[["iso3", "year", "baseline_twh", "baseline_index", "driver_source"]].to_csv(os.path.join(BUILD, "baseline.csv"), index=False)

    m = modelled_countries()
    w = drv[drv.iso3.isin(m)].groupby("year").baseline_twh.sum()
    print("\nmodelled countries, baseline TWh:\n", w.round(0).to_string())


if __name__ == "__main__":
    main()
