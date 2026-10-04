# Electricity demand projection 2024 → 2050 (feasibility study, 2026-10-04)

**Question.** Until 2026-10-04 the pypsa-earth runs served 2024 demand in every scenario: `overlay.now.yaml` and
`overlay.zero.yaml` both calibrated to `config-pypsa-earth/calibration/2024/demand.csv`, and the fork has no
demand growth in the electricity-only workflow (only the sector-coupled path projects demand). Can a fitted,
open method produce per-country demand for 2030–2050 that agrees with published outlooks? This directory tests
that **before** anything is wired into pypsa-earth. The per-country 2050 formula in
`country-classification/build_features.py` (two hand-picked constants) is what it would replace.

**Decision (2026-10-04): follow mainstream outlooks instead.** The fitted model was a no-go, so the demand tables
of the model are the calibrated 2024 demand times a consensus of published outlooks with the IEA's regional
pattern: `config-pypsa-earth/scripts/build_demand_pathway.py`, documented in `config-pypsa-earth/README.md`
("Demand pathway"). This directory keeps the fitted model as the record of why, and as a cross-check.

```bash
../../models/priam-myopic/.pixi/envs/default/bin/snakemake -c1      # from this directory
python scripts/fit_baseline.py declining                            # sensitivity: force a specification, then rerun the rest
```

## Result

**Result: no-go as it stands.** With the specification the backtest selects, the 2050 growth multiple is within
±7 % of IEA WEO 2025 Stated Policies for the world, India, China, the EU, Southeast Asia and Africa, but 20–32 %
too high for the US, Brazil and Russia, and the backtest misses its threshold (12–15 % demand-weighted error
against 10 %). More important, the result is not robust: a second specification that the backtest cannot tell
apart (14.0 % vs 13.8 %) moves world demand in 2050 from 58,900 to 47,400 TWh. See "Findings".

## Method

1. **Income-driven baseline** (`scripts/fit_baseline.py`). Panel regression of log per-capita demand on log GDP
   per capita with country fixed effects, 2000–2024, 144 countries above 1 million people. Only growth is
   projected, from each country's Ember 2024 demand, with SSP2 GDP and population. Three specifications:
   constant elasticity; elasticity declining with income; the latter plus a common time trend.
2. **Backtest.** Fit on 2000–2014 and predict 2024 (and 2000–2009 → 2019) with actual GDP and population. The
   specification with the lowest mean demand-weighted absolute error is used.
3. **Electrification layer** (`scripts/electrification.py`). Fossil final energy in road transport, buildings
   and industry (UN Energy Statistics, 2022) × the baseline index × an electrified share by year ÷ an efficiency
   gain. The shares and gains in `config.yaml` are **ASSUMPTION**s, set before the comparison and not tuned.
4. **Comparison** (`scripts/compare.py`). Outlooks use other demand definitions than Ember (the IEA excludes
   losses and own use), so everything is compared as a growth multiple from the outlook's own 2024 value.

| Input | Source | Where |
|---|---|---|
| Demand 2000–2024 | Ember yearly release | `config-pypsa-earth/data/validation/` |
| GDP per capita (PPP, constant 2021 int$), population | World Bank WDI | `data/wdi_*.json` (cached download) |
| GDP and population to 2050 | IIASA SSP basic drivers, 2025 release, SSP2 (OECD ENV-Growth 2025, IIASA-WiC POP 2025) | `data/ssp2_basic_drivers.csv` |
| Fossil final energy by sector | UN Energy Statistics Database, UNdata exports fetched by pypsa-earth | `~/Desktop/earth/pypsa-earth/data/demand/unsd/data` |
| Stated-policies benchmark | IEA WEO 2025, Table A.16 (hand-typed, CC BY-NC-SA) | `config-pypsa-earth/data/weo25_table_a16.csv` |
| Other outlooks | AEO25, EPE PNE2050, CETO22, ICCSD, TYNDP24 | `config-pypsa-earth/data/validation/manual_points.csv` |

## Findings

Growth multiple 2024 → 2050, selected specification (constant elasticity 0.76):

| Region | Baseline | + electrification (central) | WEO25 STEPS | Central vs STEPS |
|---|---|---|---|---|
| World | 1.62 | 1.90 | 1.82 | +5 % |
| United States | 1.36 | 1.70 | 1.38 | +24 % |
| China | 1.57 | 1.69 | 1.77 | −5 % |
| India | 2.39 | 2.90 | 2.92 | −1 % |
| European Union | 1.31 | 1.60 | 1.71 | −7 % |
| Brazil | 1.69 | 2.00 | 1.67 | +20 % |
| Southeast Asia | 2.02 | 2.42 | 2.43 | 0 % |
| Africa | 2.46 | 3.09 | 2.92 | +6 % |
| Russia | 1.36 | 1.60 | 1.21 | +32 % |
| Japan | 1.12 | 1.26 | 1.11 | +13 % |

World demand (Ember definition): 30,900 TWh in 2024 → 37,000 (2030), 42,300 (2035), 47,900 (2040),
58,900 (2050) in the central case; 73,100 in 2050 in the high case.

- **The backtest fails.** Demand-weighted absolute error is 12.2 % (2014 → 2024) and 15.4 % (2009 → 2019).
  The errors are systematic: rich countries are over-predicted (GBR +27 %, DEU +20 %, USA +14 %, IRL +38 %)
  because efficiency gains decoupled demand from income, and China is under-predicted (−13 %).
- **The specification is not identified.** Constant and declining elasticity score 13.8 % and 14.0 %. The
  declining one fixes the US, Brazil and Russia (+3 %, −3 %, +2 % against STEPS) but then misses China (−29 %),
  the EU (−25 %), India (−16 %) and the world (−16 %). Twenty-five years of history cannot say which holds, and
  the choice moves 2050 world demand by 11,500 TWh. `build/verdict_declining.md` and
  `build/comparison_declining.csv` hold that run when produced.
- **The time-trend specification is worse** in both windows (17.3 %).
- **The electrification layer does what it should in direction**: it closes the gap to STEPS for the EU, India,
  Southeast Asia and Africa. For the US and Brazil the baseline alone already equals STEPS and the layer
  overshoots, which says the IEA sees efficiency gains there that offset electrification.
- **Net-zero outlooks** (TYNDP24 for North-West Europe, CETO22 for China) sit inside the central–high band.
- **Singapore** has no 2050 demand outlook to compare with.

## Caveats

- The layer double counts to some degree: the fitted baseline already contains historical electrification.
- Data centres, hydrogen, aviation, shipping and rail are not modelled; biomass replacement is left out.
- The UNdata exports cached by pypsa-earth are silently capped at 100,000 rows per commodity: gas/diesel oil
  ends in 2021 and loses the countries after "United States", fuel oil those after "Yemen", natural gas those
  after "Uruguay" (Uzbekistan, Venezuela, Viet Nam). The latest year in 2019–2022 is used per series. This also
  affects pypsa-earth's own sector-coupled energy totals.
- India books about 69 Mt of retail diesel as "consumption not elsewhere specified (other)"; it is counted as
  road fuel (`road_from_unspecified` in `config.yaml`).
- Drivers: 11 countries take their GDP level from SSP2 (no WDI series) and 7 take the median per-capita growth
  (no SSP2 GDP series); flagged in `driver_source`. Ukraine has no Ember 2024 value and uses its latest year.
- The SSP database states its licence only as "allows for the re-use by other research communities"; the exact
  terms should be confirmed before `data/ssp2_basic_drivers.csv` goes public. The WEO table is CC BY-NC-SA.

