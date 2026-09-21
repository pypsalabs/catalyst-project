# PyPSA-Earth out-of-the-box validation (WP1, September 2026)

How do the six catalyst prenetworks behave when solved *as PyPSA-Earth comes*, before any project
patch touches costs, technologies or constraints? One 16:9 page per region, produced inside the
[soft fork](../../config-pypsa-earth/README.md) by `config-pypsa-earth/validation.smk` and copied
here because the fork's `results/` directory is not tracked. The pages are the WP1 sanity check of
the data pipeline against published statistics (SOW §2, WP1: IEA/IRENA validation) and the
baseline the WP3 investment loop starts from.

Each page shows two screening solves side by side (weather 2013, 50 clusters except Singapore
with one node, 3-hourly, Gurobi barrier, details in the
[screening-solves section](../../config-pypsa-earth/README.md#screening-solves-stages-r-now-r-zero-dashboardr-2026-09-1920)):

* **left, `<R>-now`**: the current system, brownfield expansion, no CO2 cap, `costs_2025.csv`;
* **right, `<R>-zero`**: carbon-neutral the way PyPSA-Earth does it by default, `opts Co2L0`,
  `costs_2050.csv`, no new firm clean technology, no imports.

Ten tiles per block: generation mix, installed capacity (hatched = added by the optimiser),
load-weighted price duration curve with the band across buses, demand per country, CO2 by carrier,
curtailment, the fuel prices the model assumes, system cost split, a summary box and the network
map. Dots and dashed levels are published statistics on the left (Ember 2025, national statistics
2024, IRENA 2024, Energy Institute 2024, Ember prices 2023) and 2050 outlooks on the right
(TYNDP24, IEA WEO25 NZE / STEPS and regional equivalents); the sources are listed in
`config-pypsa-earth/data/validation/`.

Both solves inherit PyPSA-Earth defaults that shape the numbers and are worth keeping in mind when
reading the pages: GEGIS SSP2-2.6 **2030** demand rather than 2024/25, load shedding at
100 kEUR/MWh, `noisy_costs`, 6 h hydro reservoirs, the ≈2022 powerplantmatching fleet plus IRENA
2023 wind and solar as fixed minimum capacity.

China was a candidate dense-grid region and was screened before North-West Europe replaced it in
the archetype set; its page is kept for reference.

| Region | Page |
|---|---|
| United States (CONUS) | [figures/validation_US.png](figures/validation_US.png) |
| North-West Europe (AT, BE, CH, CZ, DE, DK, FR, GB, IE, LU, NL, PL) | [figures/validation_NWE.png](figures/validation_NWE.png) |
| Brazil | [figures/validation_BR.png](figures/validation_BR.png) |
| India | [figures/validation_IN.png](figures/validation_IN.png) |
| Singapore (one node) | [figures/validation_SG.png](figures/validation_SG.png) |
| China (reference only) | [figures/validation_CN.png](figures/validation_CN.png) |

<img src="figures/validation_NWE.png" alt="North-West Europe: current system (left) and carbon-neutral (right) screening solves against published statistics" width="100%">

## Regenerating

The pages are rendered in the fork (`models/pypsa-earth/results/catalyst/validation_<R>.png`) by
the `dashboard:<R>` stage of `config-pypsa-earth/run.sh`, which needs the two solved networks of the
region:

```bash
# from the repo root
bash config-pypsa-earth/run.sh <R>-now <R>-zero dashboard:<R>
# then, from this directory, copy the fresh pages into figures/
../../models/priam-myopic/.pixi/envs/default/bin/snakemake -c1
```

The copy is `cp -p`, so a page's timestamp is the time it was rendered in the fork
(all six: 2026-09-21).
