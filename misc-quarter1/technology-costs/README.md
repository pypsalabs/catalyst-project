# 2025 techno-economic cost baseline (SOW WP2)

A small Snakemake workflow that compiles capex, opex, lifetime, efficiency and
LCOE for the SOW technology palette from the **2025** file of
[PyPSA/technology-data](https://github.com/PyPSA/technology-data) (pinned
`v0.15.0`), fills gaps from other referenced sources, and plots the result with
observed real-project cost points overlaid. Only the 2025 file is used because
cost decline of advanced technologies is endogenous (learning) in the study.

```
data/technology-data/costs_2025_v0.15.0.csv    pinned download (committed; retrieve rule skips if present)
data/gap_fill.csv                               parameters technology-data lacks or gets wrong, with URL
data/observed_projects.csv                      flagship projects + benchmarks, with URL
config.yaml                                     palette, technology-data name mapping, CF bands, FX/CPI tables
  └─ compile_costs.py ─► build/costs_2025_compiled.csv   long: every parameter, original and USD2024 value, origin, source id
                         build/costs_2025_table.csv      wide: one row per technology incl. LCOE band
                         build/observed_normalised.csv   observed points in USD2024
                         build/sources.md                numbered source list (the [n] in the figures)
       └─ plot_costs.py ─► figures/capex_generation.{png,pdf}   USD/kW, generation (+ _mature bars-only, _advanced)
                           figures/capex_storage.{png,pdf}      USD/kWh and USD/kW, storage, ordered by duration (+ _mature, _advanced)
                           figures/opex.{png,pdf}               FOM USD/kW/a, VOM USD/MWh
                           figures/lcoe.{png,pdf}               USD/MWh over the CF band
                           figures/dac.{png,pdf}                USD/tCO2 (capex + FOM only)
                           figures/slides/<same>.{png,pdf}      16:9 layout (15.2 x 5.5 cm, legend right, no ids/footnote,
                                                                `plotting.slide_exclude` techs dropped) for the kickoff deck (../../beamer/2026-09-08)
```

Run from this directory with the priam-myopic pixi environment:

```bash
S=../../models/priam-myopic/.pixi/envs/default/bin/snakemake
$S -n        # dry run
$S -c1       # build everything
```

Scripts also run standalone (`python compile_costs.py`, `python plot_costs.py lcoe`,
`python plot_costs.py capex_storage --slide`).

## Method

- **Currency.** Everything is expressed in USD2024 (`base_currency` and
  `base_currency_year` in `config.yaml`; EUR2023 works too, which is what the
  SOW quotes, e.g. 4,000 EUR/kW for the SMR breakthrough). Each row is
  converted at the ECB annual average rate of its stated price year, then
  inflated with the base currency's CPI:
  `v_base = v · fx[cur][y] / fx[base][y] · CPI[base][2024] / CPI[base][y]`.
  Tables and their sources (ECB, Eurostat, BLS, ONS, StatCan) are in
  `config.yaml`. technology-data rows carry their own `currency_year` (v0.15.0
  inflates investment rows to 2025 while leaving FOM/lifetime at their original
  year); rows without one are taken as the base year and flagged in `note`.
- **Units.** technology-data mixes `EUR/kW`, `EUR/kW_e`, `EUR/kWel`,
  `EUR/MW`, `EUR/MWh`, `%/year` … `compile_costs.py` maps them to EUR/kW,
  EUR/kWh, EUR/kW/a, EUR/kWh/a, EUR/MWh, EUR/MWh_th and raises on anything
  unknown. FOM given as `%/year` is applied to the normalised investment of the
  same technology.
- **Precedence.** technology-data first; `data/gap_fill.csv` fills parameters
  that are missing, replaces them when its `note` starts with `OVERRIDE:`
  (used for Allam-cycle, whose upstream row is an explicit "own assumption,
  TODO"), or adds a component on top when it starts with `ADD:` (the SOFC on
  top of the technology-data electrolyser for the hydrogen store). The `origin`
  column and the hatching in the figures show which is which.
- **LCOE.** `annuity(r, n) = r / (1 − (1 + r)^−n)` at r = 7 % real (Lazard-style
  commercial WACC; priam-myopic uses a 2 % social rate, which would lower every
  bar), `LCOE(CF) = (annuity · capex + FOM) · 1000 / (8760 · CF) + VOM + fuel/η +
  p_CO2 · intensity · (1 − capture)/η`. The bar spans the capacity-factor band in
  `config.yaml` (high CF at the marker, low CF at the far end). Fuel prices are
  the technology-data 2025 rows (`gas`, `uranium`, `biomass`); CO2 price 0 by
  default. Storage has no LCOE here (capex per kWh and per kW instead); DAC is
  reduced to USD/tCO2 from capex + FOM at 90 % availability, excluding energy.
- **Observed points.** `data/observed_projects.csv` holds realised project
  costs, project estimates/targets, PPA or auction prices, IRENA global weighted
  averages and Lazard/NREL benchmark ranges, each with the price year and a URL.
  They go through the same currency conversion. Nuclear totals include
  financing where the source does; storage projects are total cost divided by
  energy or power capacity.

## Gap-fill choices (central values; ranges and alternatives in `data/gap_fill.csv`)

| Technology | Value used | Source |
|---|---|---|
| Nuclear SMR | 8,000 USD2022/kW overnight, FOM 136 USD/kW/a, 60 a, η 0.37 | NREL ATB 2024 Nuclear-Small (Moderate); DOE Liftoff FOAK median ~13,000 shown as a point |
| EGS | *no bar* (`bar: false`); indicative 13,508 USD2022/kW (deep EGS binary), FOM 226 USD/kW/a kept in the compiled table | NREL ATB 2024; flash 7,630, DOE Liftoff FOAK 14,700 and Fervo FOAK ~7,000 shown as points |
| Closed-loop geothermal | *no bar*; indicative 33,000 USD/kW "today" (modelled), FOM 1.5 %/a | DOE Liftoff Next-Gen Geothermal (Mar 2024); NREL Eavor-Loop 2.0 study |
| CO2 battery | 220 EUR2023/kWh, 10 h (→ 2,200 EUR/kW), RTE 0.75, 30 a; no FOM found | Energy Dome CEO (2023); Alliant project 300–450 USD/kWh as a point |
| SOFC | 3,250 USD2023/kW (Bloom product cost, not installed), η 0.59 LHV, 10 a, FOM 5 %/a PEM proxy; **no capture rate published → unabated** | Bloom Energy datasheets; DEA PEMFC proxy |
| Allam-cycle | **OVERRIDE** 6,170 USD2025/kW (NET Power Project Permian FOAK, $1.7–2.0 bn / 300 MW), FOM 2.5 %/a | NET Power Q4 2024 results; Xie et al. 2024 |
| Li-ion FOM | **OVERRIDE** 40 USD2023/kW/a | EIA/S&L AEO2025 case 19 (technology-data has inverter FOM only) |
| H2 tank + electrolyser + SOFC | energy: DEA 151a tank incl. compressor 68 EUR2025/kWh_H2 ÷ 0.59 SOFC efficiency = 127 USD/kWh_el (`energy_per_output: true`); power: technology-data AEC electrolyser 2,263 EUR2025/kW **ADD** SOFC 3,250 USD2023/kW; FOM 4 %/a of the sum (electrolyser rate as proxy); round trip 0.587 × 0.59 = 0.35 | technology-data; Thunder Said Energy / Bloom. Salt caverns (DEA 151c, 3.3 EUR/kWh_H2) would be ~20x cheaper but are geology-bound |
| Fusion | n/a | no published baseline (SOW) |

Geothermal is site-dependent, so it gets no single assumption bar: EGS and
closed-loop geothermal keep their observed points only (`bar: false` in
`config.yaml`), and conventional hydrothermal is not in the palette at all — in
the model these would be parametrised per site or supply-curve tranche (e.g.
NREL ATB's six geothermal resource classes), not as one national number.

Pumped hydro is equally site-specific, but PyPSA-Eur and PyPSA-Earth default
runs sidestep the question: PHS enters as fixed existing capacity from
powerplantmatching with `PHS_max_hours: 6` and is not in
`extendable_carriers`, so its capital cost never enters the optimisation.
PyPSA-Earth maps an extendable PHS to technology-data's PNNL 2022 rows
(`Pumped-Storage-Hydro-bicharger` powerhouse per kW, `-store` reservoir per
kWh), and that split is the bar here; technology-data's plain `PHS` row is a
2013 DIW placeholder identical to its reservoir-hydro value and is not used.
The observed points (Snowy 2.0, Fengning, Coire Glas, Hatta, Kidston,
Goldendale, ATB classes) show the site spread around it.

Storage rows are ordered by typical discharge duration within each group
(Li-ion 4 h, pumped hydro 6–20 h; then vanadium flow 4–10 h, CO2 battery 10 h,
iron-air 100 h, hydrogen 100+ h); the duration in the label is typical for the
technology, not a modelling assumption, except where the bar is derived from it
(CO2 battery power = 220 EUR/kWh × 10 h).

Vanadium flow batteries have observed points on the energy panel only. The
technology-data power bar is the PNNL 2022 "power equipment" component alone
(~190 USD2024/kW), whereas published per-kW project costs are total cost
divided by MW, i.e. exactly the per-kWh cost times the duration (PNNL 10 h,
Dalian 4 h). Those per-kW points duplicated the per-kWh points and were removed
so the panel compares like with like.

Gas CCGT with post-combustion CCS was dropped from the palette (Sep 2026): the
SOW names Allam-cycle CCS as the advanced gas option, and a second, exogenous
gas + CCS route would only compete with it for the same role.

## technology-data caveats

- `SMR` / `SMR CC` in technology-data are **steam methane reforming**, not small
  modular reactors; the script asserts they are never mapped.
- `fuel cell` is a low-temperature PEM CHP unit, not an SOFC.
- `geothermal` has FOM and lifetime but no investment cost in the 2025 file
  (not used: hydrothermal is out of the palette).
- `allam` is flagged upstream as "Own assumption. TODO" and is overridden.
- `iron-air battery` is Form Energy's *target* cost, not an observed one; no
  Form project has a disclosed cost, and Energy Dome's US project only
  discloses a range, so the two LDES newcomers rest on vendor statements.
- v0.15.0 vs v0.13.3 differences in investment rows are inflation
  (currency_year 2020/2023 → 2025), not cost changes.

## Sources

See `build/sources.md` after a run; the same numbers appear in brackets in the
figure labels. Hand-curated inputs carry the URL in their own row.
