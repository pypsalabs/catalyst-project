"""Vectorised port of the EGS cost model of Ricks & Jenkins (Joule 2025).

Source: Zenodo 10.5281/zenodo.15485307, Costing_and_Supply_Curves/EGS_Costs.py
(CC-BY-4.0), a GETEM-derived model in 2021 USD: surface-plant cost and gross
power per injector are fitted per depth as functions of the production
temperature (binary/ORC plants; linear extrapolation above 200 degC), well
costs are quadratic in depth, stimulation, exploration, interest during
construction, O&M and labour follow GETEM with the NREL ATB 2023 O&M
derating. The functions here reproduce that script to floating-point
precision (see `regression_test`) but take numpy arrays.

Output per cell and depth (all USD2021 unless converted by the caller):
  gross_mw_per_injector   gross electric output of one injector unit (MW)
  plant_capex_usd_per_kw  surface plant incl. interest during construction
  well_capex_usd_per_kw   wellfield (drilling, stimulation, exploration) incl. IDC
  fom_usd_per_kw_yr       fixed O&M (plant + wellfield maintenance, taxes,
                          insurance, labour)
  mw_per_km2              developable capacity density after resource derating

Standalone: python egs_cost_model.py   runs the regression test against the
CONUS supply-curve file shipped with the Zenodo record.
"""

from pathlib import Path

import numpy as np
import pandas as pd

DEPTHS = (2.5, 3.5, 4.5, 5.5, 6.5)

# Per-depth fit coefficients (from EGS_Costs.py)
_PWR = {2.5: (0.005526, -1.3473, 124.43), 3.5: (0.005767, -1.4473, 136.4),
        4.5: (0.005777, -1.4566, 139.59), 5.5: (0.005362, -1.331, 132.57),
        6.5: (0.004806, -1.1589, 121.77)}
_PLANT = {2.5: (58770, -0.02232, 2006), 3.5: (70160, -0.02273, 1994),
          4.5: (74180, -0.02236, 1961), 5.5: (70590, -0.02085, 1791),
          6.5: (55080, -0.01768, 1358)}
# lateral-length adjustment of the well cost: (cost with 2286 m lateral - cost with 1786 m), depth factor
_LATERAL = {2.5: (4953350 - 4394664, 0.886), 3.5: (8630763 - 7753212, 0.899),
            4.5: (10385865 - 9508314, 0.913), 5.5: (18356326 - 17040291, 0.926),
            6.5: (20988394 - 19672360, 0.940)}

PARAMS = dict(
    pre_survey_cost=250_000, test_drilling_cost=3_300_000,
    pre_survey_years=3, test_drilling_years=0.5, drilling_years=1, construction_years=1,
    pre_survey_interest=1.15, test_drilling_interest=1.15, drilling_interest=1.1,
    construction_interest=1.08,
    wf_maint=0.015, pp_maint=0.018, tandi=0.0075,
    drill_success_rate=0.9, stim_cost=3_480_000,
    plantcost_adj=1.491 / 1.408, laborcost_adj=1.556 / 1.449,
    om_derating=0.77,
)


def conv_temp(t_prod_c, t_amb_k):
    """Effective resource-temperature shift for ambient temperature (K) other
    than 283.15 K, from the source model (binary-plant performance fit)."""
    t_prod_c = np.asarray(t_prod_c, dtype=float)
    t_amb_k = np.asarray(t_amb_k, dtype=float)
    temp_diff = t_amb_k - 283.15
    t = t_prod_c + 273.15
    A, B, C, GPB = 4.01465, -0.01204, 0.00001605, 288.15
    cold = temp_diff <= 0
    C1 = np.where(cold, 0.002746, 0.002713)
    C0 = np.where(cold, -0.083806, -0.091841)
    D1 = np.where(cold, 0.002713, 0.002676)
    D0 = np.where(cold, -0.091841, -0.1012)
    etaull = C1 * t + C0
    etauul = D1 * t + D0
    lg = np.log(t / GPB)
    poly = ((t - GPB) * (A - B * GPB) - A * GPB * lg
            + 0.5 * (t ** 2 - GPB ** 2) * (B - C * GPB) + C / 3 * (t ** 3 - GPB ** 3))
    dpdt_amb = -(etaull * (-A * lg - GPB * (B - C * GPB) - B * (t - GPB) + B * GPB
                           - 0.5 * C * (t ** 2 - GPB ** 2) - C * GPB ** 2)
                 + (etauul / 10 - etaull / 10) * poly)
    dpdt_prod = C1 * poly + (C1 * t + C0) * (-A * GPB / t + A + t * (B - C * GPB)
                                             - B * GPB + C * t ** 2)
    return -(dpdt_amb / dpdt_prod) * temp_diff


def _piecewise(t, coef_lo, above200):
    """Quadratic fit up to 200 degC, then the model's linear/exponential tail."""
    a, b, c = coef_lo
    t = np.asarray(t, dtype=float)
    lo = a * np.minimum(t, 200) ** 2 + b * np.minimum(t, 200) + c
    return lo + np.where(t > 200, above200(t), 0.0)


def well_costs(depth_km, lateral_length_m=2286, drill_cost_multiplier=1.0):
    """Drilling cost of one (cased, uncased) horizontal well with `lateral_length_m` of lateral at vertical
    depth `depth_km`, USD2021, stimulation excluded (quadratic fits of the source model)."""
    d = float(depth_km)
    uncased = (399766 * d ** 2 + 25250 * d + 2439840) * drill_cost_multiplier
    cased = (413193 * d ** 2 + 152907 * d + 2932844) * drill_cost_multiplier
    dl, fac = _LATERAL[d]
    lat_adj = (dl * (2286 - lateral_length_m) / 500 + 163.8 * (2286 - lateral_length_m)) * 0.87 * fac * drill_cost_multiplier
    return cased - lat_adj, uncased - 0.6 * lat_adj


def egs_costs(restemp_c, air_temp_k, depth_km, producers_per_injector=1.5,
              stimulate_producers=True, lateral_length_m=2286, flow_derating=0.77,
              resource_derating=0.2, drill_cost_multiplier=1.0, plant_size_mw=50,
              t_max_c=None):
    """Costs of an EGS unit at `depth_km` for reservoir temperature `restemp_c`
    (array, degC at that depth) and ambient air temperature `air_temp_k` (K).
    Returns a dict of arrays in USD2021 (see module docstring)."""
    p = PARAMS
    d = float(depth_km)
    if d not in _PWR:
        raise ValueError(f"depth {d} km not in the fitted set {DEPTHS}")
    restemp_c = np.asarray(restemp_c, dtype=float)
    air_temp_k = np.broadcast_to(np.asarray(air_temp_k, dtype=float), restemp_c.shape)

    mass_flow = 160 * 0.925 * (lateral_length_m / 2286) * flow_derating   # kg/s per injector
    wellfield_area_km2 = 1.39 * (lateral_length_m / 2286) * flow_derating

    t_prod = restemp_c - (0.6889 * d - 0.1333)          # wellbore loss
    adj_temp = t_prod + conv_temp(t_prod, air_temp_k)
    if t_max_c is not None:
        adj_temp = np.minimum(adj_temp, t_max_c)

    # gross electric power per injector (kW per kg/s -> MW)
    gross_kw = _piecewise(adj_temp, _PWR[d], lambda t: 0.862 * (t - 200)) * mass_flow
    gross_mw = gross_kw / 1000

    # surface plant cost (USD/kW -> USD/MW), with economies of scale
    size_mult = (plant_size_mw / 10) ** (-0.244)
    k1, k2, k3 = _PLANT[d]
    plant = (k1 * np.exp(k2 * np.minimum(adj_temp, 200)) + k3
             + np.where(adj_temp > 200,
                        55630 * (np.exp(-0.02319 * adj_temp) - np.exp(-0.02319 * 200)), 0.0))
    plant_cost = plant * size_mult * 1000 * p["plantcost_adj"]   # USD/MW

    # wellfield
    cased, uncased = well_costs(d, lateral_length_m, drill_cost_multiplier)
    stim = p["stim_cost"] * lateral_length_m / 2286
    if stimulate_producers:
        wells = cased * (1 + producers_per_injector) / p["drill_success_rate"] + stim * (1 + producers_per_injector)
    else:
        wells = (cased + uncased * producers_per_injector) / p["drill_success_rate"] + stim
    wellfield_cost = wells / gross_mw                       # USD/MW

    # O&M (USD/MW-yr)
    plant_maint = plant_cost * p["pp_maint"] * p["om_derating"]
    wf_maint = wellfield_cost * p["wf_maint"] * p["om_derating"]
    plant_ti = plant_cost * p["tandi"] * p["om_derating"]
    wf_ti = wellfield_cost * p["tandi"] * p["om_derating"]
    labor = ((0.25 * plant_size_mw ** 0.525 * 20 * 8760
              + 0.15 * plant_size_mw ** 0.65 * (24 + 24 + 17.5) * 2000
              + 0.075 * plant_size_mw ** 0.65 * (40 + 30 + 12) * 2000)
             / plant_size_mw * 1.8 * 1.37 * p["om_derating"] * p["laborcost_adj"])
    fom = plant_maint + plant_ti + labor + wf_maint + wf_ti

    # CAPEX with exploration and interest during construction (USD/MW)
    expl = ((p["pre_survey_cost"] / plant_size_mw * p["pre_survey_interest"] ** p["pre_survey_years"])
            + p["test_drilling_cost"] / plant_size_mw) * p["test_drilling_interest"] ** p["test_drilling_years"]
    wf_capex = ((expl + wellfield_cost) * p["drilling_interest"] ** p["drilling_years"]
                * p["construction_interest"] ** p["construction_years"])
    plant_capex = plant_cost * p["construction_interest"] ** p["construction_years"]

    return {
        "adj_temp_c": adj_temp,
        "gross_mw_per_injector": gross_mw,
        "plant_capex_usd_per_kw": plant_capex / 1000,
        "well_capex_usd_per_kw": wf_capex / 1000,
        "fom_usd_per_kw_yr": fom / 1000,
        "mw_per_km2": gross_mw / wellfield_area_km2 * resource_derating,
    }


def regression_test(csv_path, n=2000, seed=0):
    """Compare against the original row-wise function on a sample of the
    CONUS file; returns the maximum relative deviation."""
    import importlib.util
    src = Path(csv_path).parent / "EGS_Costs.py"
    code = src.read_text().split("# Temperature-at-depth data")[0]   # functions only
    ns = {}
    exec(compile(code, str(src), "exec"), ns)
    df = pd.read_csv(csv_path, low_memory=False).sample(n, random_state=seed)
    worst = 0.0
    for d in (3.5, 4.5, 5.5, 6.5):
        ref = df.apply(ns["get_egs_costs"], axis=1, args=[d, 1.5, True, 2286, 0.77, 0.2])
        ref = pd.DataFrame(ref.tolist(), index=df.index)
        out = egs_costs(df[f"MEAN{str(d).replace('.', '_')}"].values, df["Air_Temp"].values, d)
        cap = out["mw_per_km2"] * df["area_sqkm"].values
        for mine, theirs in [(cap, ref[0]), (out["plant_capex_usd_per_kw"] * 1000, ref[3]),
                             (out["well_capex_usd_per_kw"] * 1000, ref[4]),
                             (out["fom_usd_per_kw_yr"] * 1000, ref[6] + ref[8])]:
            rel = np.nanmax(np.abs(mine - theirs.values) / np.abs(theirs.values))
            worst = max(worst, rel)
    return worst


if __name__ == "__main__":
    here = Path(__file__).parent
    f = here / "data/ricks2025/Costing_and_Supply_Curves/geothermal_lcoe_conus_15_zone_geothermal_Stanford.csv"
    print(f"max relative deviation from EGS_Costs.py: {regression_test(f):.2e}")
    for T in (150, 175, 200, 250, 300):
        for d in DEPTHS:
            o = egs_costs(np.array([T]), np.array([283.15]), d)
            print(f"T={T} C at {d} km: CAPEX {o['plant_capex_usd_per_kw'][0] + o['well_capex_usd_per_kw'][0]:7.0f} USD2021/kW "
                  f"(plant {o['plant_capex_usd_per_kw'][0]:5.0f}, wells {o['well_capex_usd_per_kw'][0]:6.0f}), "
                  f"FOM {o['fom_usd_per_kw_yr'][0]:5.0f}, {o['mw_per_km2'][0]:.2f} MW/km2")
