# Technology assumptions of the Catalyst model

The one place for the model's techno-economic inputs: `technology_assumptions.csv`, one
row per technology (CAPEX, fixed and variable O&M, efficiency, lifetime, existing and
pipeline capacity, lead time, build limit, learning rate and its basis, source, comment),
and a justification document `build/technology_assumptions.pdf` whose first page shows
exactly those numbers, each technology name linking to the subsection that argues for the row
on the remaining pages. Downstream rules that feed the CSV into the fork's cost table will be added
next to `assumptions.smk`; for now only the CSV and the document are wired in.

```
technology_assumptions.csv   the input (USD2024; edit here)
assumptions.smk              Snakemake rules: assumptions_table (CSV -> build/table.tex), assumptions_resource_cf,
                             assumptions_offshore_mask, assumptions_resource_maps (solar / onshore / offshore wind
                             maps), assumptions_doc (latexmk)
scripts/build_table.py       the table generator; standalone: python scripts/build_table.py
scripts/build_resource_cf.py weather octants (models/octants, ERA5 2011) -> data/resource_cf_2011.nc (3 min, ~2 GB RAM)
scripts/build_offshore_mask.py GEBCO 2025 of the fork (7 GB) -> data/offwind_shallow_share.nc, share of each cell 0-50 m deep (25 s)
scripts/plot_resource_maps.py those grids + the CSV -> build/figures/{solar-utility,onwind,offwind}_{cf,lcoe}.pdf
data/resource_cf_2011.nc     annual mean capacity factor of solar and onshore wind, global 0.5 degree grid (1.4 MB,
                             tracked so that the document builds without the 7 GB of octants); offwind_shallow_share.nc
                             likewise tracked so that GEBCO is not needed
doc/main.tex                 the document; doc/sections/<technology>.tex one file per row; doc/references.bib; doc/figures/;
                             doc/icons/ one drawn icon per advanced technology (<key>.svg source, <key>.pdf for LaTeX;
                             \techicon macro, wrapped beside the section's first paragraphs)
build/                       gitignored: table.tex, figures/, technology_assumptions.pdf, latexmk files, build_table.log
```

## Build

Three equivalent ways (latexmk, biber and the kpfonts package must be on the PATH):

```bash
# standalone, from this directory (snakemake 9 of the priam-myopic env, or the fork's snakemake 7)
../../models/priam-myopic/.pixi/envs/default/bin/snakemake -s assumptions.smk -c1

# through the fork driver, from the repo root (memory scope, logs/catalyst/assumptions.log)
bash config-pypsa-earth/run.sh assumptions

# inside the fork by hand (merge_config.py puts assumptions.smk into custom_rules of every stage)
cd models/pypsa-earth && pixi run snakemake ../../config-pypsa-earth/technology-assumptions/build/technology_assumptions.pdf -c1
```

`assumptions.smk` derives its paths from its own location (`workflow.current_basedir`), so
the same file works standalone (paths `./...`) and included from the fork root
(`../../config-pypsa-earth/technology-assumptions/...`). Snakemake's metadata lives in the
respective working directory, so the two modes may each rebuild once.

## The table / text contract

- Pages 1 and 2 (Table 1, Table 2, one per page; every caption sentence on its own line) are
  generated from the CSV by `scripts/build_table.py`, advanced technologies first: every numeric column appears (plus the derived LCOE columns), values are passed as the CSV strings through siunitx `\num{}`
  (thousands grouping, no rounding), blanks print as "–". Every technology name is a clickable
  link (`\techlink`, defined in `doc/main.tex`, dark blue) to `\label{sec:<technology>}` in that
  technology's section. The `comment` and `source` columns are **not typeset**: they document
  the CSV, and their content is argued in prose in the sections. **Never edit `build/table.tex`.**
- From page 3, `doc/sections/<technology>.tex` holds one `\subsection` per row, followed by
  `\label{sec:<technology>}` (the target of the table link), whose title names the CAPEX,
  e.g. `\subsection{Iron-air battery, 100~h (75~\$/kWh)}\label{sec:iron-air}`. That
  number is **typed by hand on purpose**: when the CSV changes and the text does not (or
  vice versa), the document shows both and `build_table.py` prints
  `warning: ... title ... does not carry the CSV CAPEX ...` in `build/build_table.log`
  (standalone: on stdout). It also warns for rows without a section file and for section
  files without the label (the table link would dangle). Warnings never fail the build.
- Every section follows the same order, one paragraph each, separated by a 1.5-line pitch
  (`\parskip` = half a line, set once in `doc/main.tex`): (1) what the technology is and what gap
  it fills, in one or two sentences; (2) the CAPEX, how it was chosen and any qualifier (EGS: varies
  by site; SOFC: excludes carbon capture); (3) the learning rate, in the same way; (4) where the
  remaining parameters come from; (5) other useful context, only if there is any. Plain language.
- Every fact in a row's `comment` / `source` cell must appear in its section's prose (how
  existing and pipeline capacity were counted, O&M derivations, lead time, learning basis,
  the sources); when you change a cell, change the section.
- New technology = new CSV row + new `doc/sections/<key>.tex` (with its `\label{sec:<key>}`) + an `\input` line in
  `doc/main.tex` (the input list is hand-written so the order and grouping are yours).
- Figure captions name their sources. The learning figures of `misc-quarter1/technology-costs` number
  their sources [1], [2], ... in the legend (list in `figures/learning/<tech>_sources.tex` there); each
  caption maps those numbers to `references.bib` keys. The learning figures (`show_model: assumptions` in
  that workflow's config) and the nuclear cost strip (`model_inputs` in `misc-quarter1/nuclear-projects`)
  read their dashed "model input" line from this CSV, so rerun those workflows after a CAPEX change.
- The EGS section carries the gradient / CAPEX map pair of `misc-quarter1/geothermal` (rule `doc_maps`,
  described in that README).
- The solar and onshore wind sections carry two maps side by side: the annual mean capacity factor
  on land (left) and the LCOE it implies with the row's own CAPEX, FOM, VOM and lifetime at a 7 %
  real discount rate (right; log colour scale per technology, so the two LCOE maps do not share a
  scale). The octants carry no offshore profile, so the offshore wind maps take the onshore octant's
  capacity factor over sea (model.energy's onshore turbine, no wake losses: an upper bound) on cells
  at least a quarter 0-50 m deep (the fork's offwind max_depth) south of the Arctic circle. A changed CSV value
  redraws the LCOE maps; the capacity-factor grid is only rebuilt when the octants change. Two of
  the octant files were truncated downloads until 2026-10-03; check sizes against Content-Length.
- Icons (advanced sections, excluded ones included): schematic drawings of the central piece of each plant
  (reactor pool, cell enclosure, rig over the wells, cell stack, two tanks, gas dome), made for this document
  (2026-10-06, also on the Claude canvas "Advanced technology icons"); replaced openly licensed photos. After
  editing an SVG, convert it with headless Chrome: an HTML page with `@page{size:200px 200px;margin:0}` holding
  the SVG, `google-chrome --headless --no-pdf-header-footer --print-to-pdf=icons/<key>.pdf page.html`.
- References go into `doc/references.bib` (biblatex author-year, `\citep` / `\citet`);
  figures into `doc/figures/` or straight from the topic workflows
  (`../../../misc-quarter1/technology-costs/figures/learning/<tech>.pdf`,
  `../../../misc-quarter1/nuclear-projects/figures/...`).

## Columns

| column | meaning |
|---|---|
| `technology` | key; the PyPSA-Earth carrier name where one exists (`solar-utility`, `onwind`, `offwind`, `hydro`, `ror`, `biomass`, `CCGT`, `OCGT`, `battery-liion`, `PHS`, `geothermal`), else the study's own (`nuclear-lwr-cnin`, `nuclear-lwr-row`, `nuclear-gen4`, `iron-air`, `egs`, `sofc`, `vrfb`, `co2-battery`) |
| `label`, `group`, `kind` | display name; `mature` (exogenous cost path) / `advanced` (endogenous learning, SOW §1.2); `generation` / `storage` |
| `in_default_mix` | `yes` / `no`: whether the technology is part of the default palette of the scenario runs. Not a table column: rows with `no` (VRFB, CO₂ battery) are shaded in the document, with the legend under the "Technology" header |
| `capex_power_usd_kw`, `capex_energy_usd_kwh`, `duration_h` | overnight investment per kW (generation; storage power part) and per kWh (storage energy part) at the stated duration; iron-air is all-in per kWh at a fixed 100 h |
| `fom_usd_kw_yr` | fixed O&M, absolute per kW of power (storage: including the energy part × duration). Absolute rather than % of CAPEX so that the decided CAPEX bins (3,000 vs 11,000 $/kW for the same LWR) do not silently scale O&M |
| `vom_usd_mwh` | variable O&M excluding fuel |
| `efficiency` | electric efficiency (generation, fuel → electricity) or round-trip efficiency (storage) |
| `lifetime_yr` | technical lifetime used for the annuity |
| `capacity_factor`, `cycles_per_yr`, `fuel_usd_mwh_th` | utilisation assumed for the levelised cost (generation: capacity factor; storage: full cycles per year) and the fuel price per MWh thermal (technology-data 2025: gas 47.2, biomass 10.3, nuclear 8.2). Only the LCOE / LCOS columns of Table 1 depend on them: `build_table.py` computes (annuity × CAPEX + FOM)/(8760 h × CF) + VOM + fuel/efficiency for generation (no CO₂ price) and (annuity × (CAPEX_kW + CAPEX_kWh × duration) + FOM)/(cycles × duration) per MWh discharged for storage (charging electricity excluded), at the real discount rates in `DISCOUNT_RATES` (2 % and 7 %); the cells are coloured green → red on a log scale |
| `existing_gw`, `pipeline_gw` | global operating capacity end-2024; under construction / post-FID. Mature: Ember 2024 via `../calibration/2024/capacity.csv` (onshore = wind − GWEC offshore); hydro and gas rows carry the whole group; nuclear from `misc-quarter1/nuclear-projects/build/nuclear_units.csv` (non-Gen-IV fission operating per region; Gen IV = fast/HTGR/MSR/FHR), geothermal from `misc-quarter1/geothermal/build/hydrothermal_country.csv` |
| `lead_time_yr` | years from investment decision to operation (placeholders; GEM medians for nuclear) |
| `reference_site` | optional, the site whose CAPEX the row carries where the cost depends on the site (EGS: Fervo Cape Station (Utah)): the CAPEX and LCOE cells get a dagger named in the caption (representative values of that site) |
| `section` | optional, the key of another row whose section this row's table link jumps to (SOFC with CC -> `sofc`); blank = its own `doc/sections/<technology>.tex`. A shared section's title carries the CAPEX of every row that links to it |
| `max_build_rate_gw_yr` | maximum global additions per year, blank = unconstrained; set for the nuclear bins (2026-10-05) from GEM construction starts: China + India 12 (China ~10-11 + India ~2), rest of world 7 (2024 peak), Gen IV 1 (assumption, pipeline delivery rate) |
| `learning_rate`, `learning_on`, `learning_basis` | cost reduction per doubling of cumulative capacity (fraction), the component it applies to (`plant`, `energy`, `power`, `drilling`, `none`) and its basis: `decided` (project meeting), `fitted` (technology-costs learning dashboards), `literature` (taken from a study, e.g. Ricks & Jenkins 2025 for EGS), `analogy`, `assumption`, `exogenous` (mature), `none` |
| `learning_rate_2`, `learning_on_2` | optional second rate on another component, blank elsewhere; EGS: 0.15 on `drilling` (wellfield) and 0.10 on `plant` (surface binary plant). Table 2 prints both as `a / b` |
| `currency_year` | 2024 for every row (`build_table.py` asserts uniformity; conversions as in `misc-quarter1/technology-costs`: ECB rate of the price year, US CPI to 2024) |
| `source`, `comment` | free text documenting the CSV; not typeset, their content is argued in the technology's section |

## Where the numbers come from

- Mature rows: `misc-quarter1/technology-costs/build/costs_2025_table.csv` (PyPSA/technology-data
  v0.15.0, DEA catalogue, USD2024; Li-ion FOM overridden to 40 USD2023/kW/yr there); hydrothermal
  geothermal from `misc-quarter1/geothermal` (NREL ATB 2024 flash class).
- Decided rows (project meeting 2026-09-30): nuclear in three bins (the two water-cooled bins moved to the mature group on
  2026-10-05: no learning, constant cost; Gen IV stays advanced), LWR China + India 3,150 (3,000 at the meeting; 2026-10-05 raised to the empirical mean of 3,164)
  $/kW no learning, LWR rest of world 11,000 $/kW no learning ("minor" discussed), Gen IV 17,000
  $/kW 10 %; LWR includes large and small modular reactors. Iron-air 75 $/kWh unsubsidised at a
  fixed 100 h (the Pine Island price before incentives), target 15–20. EGS: 6,700 $/kW = the geothermal cost model at the Fervo Cape Station
  cell (misc-quarter1/geothermal build/site_check.csv; Fervo's S-1 estimate ~7,000), a reference site only (the
  7,500 $/kW level of the meeting was dropped): the cost is highly heterogeneous per site and the model uses the
  geothermal supply curves; `reference_site` marks the CAPEX and LCOE cells of Table 1 with a dagger (representative values of that site). Learning 15 % wellfield / 10 % plant after Ricks & Jenkins 2025. SOFC
  4,100 $/kW without carbon capture, stack life not reflected. Row sofc-cc (2026-10-05): the same fuel cell with carbon capture, 4,740 $/kW = 4,100 + a 640 $/kW
  capture adder from NETL (2022, DOE/NETL-2022-3259, reference plant with vs without CCS), efficiency 0.55, 97.8 % capture,
  CO2 transport and storage as VOM 4.5 $/MWh; it should share the SOFC row's cumulative capacity for learning. Gas (2026-10-05): CCGT 2,500 $/kW (US/EU quotes
  during the turbine shortage; technology-data 1,257), OCGT 1,300 (technology-data 654 x the same factor), gas price
  20 $/MWh_th for CCGT, OCGT and SOFC (technology-data 47.2 is a European value; the 2024 calibration uses regional prices). Allam cycle and the hydrogen chain
  dropped (see the document's last section).
- Remaining advanced rows (VRFB, CO₂ battery; not in the default mix): technology-costs values and
  fitted / analogy rates from `build/learning_rates.csv` there. Closed-loop geothermal was removed
  on 2026-10-01 (see the document's last section).

## Caveats

- `CCGT` / `OCGT` carry the pre-2024 DEA figure; US and European new-build quotes are now
  ~2,000–2,500 $/kW with 4–5-year turbine lead times (the reason LDES is being procured), to be
  replaced by a regional override before the scenario runs.
- `battery-liion` and `vrfb` existing capacity are still blank ("TO FILL" in the comment).
- `PHS` (0.894) and `vrfb` (0.806) carry technology-data's *bicharger* efficiency, which is per
  direction (round trip 0.80 and 0.65), although the column is defined as round trip; the sections
  say so. `battery-liion` 0.955 is technology-data's round-trip inverter value. Not yet corrected in
  the CSV; the LCOS columns do not use efficiency.
- Lead times are placeholders except where the comment cites GEM build durations.

Figures float only within their own subsection (`placeins`, a `\FloatBarrier` before every `\subsection`) and
sit in the source right after the paragraph that first references them. Citations, references and URLs are dark
red (`reflink` in main.tex), the table's technology links blue.
