# Advanced-technology supplier pipelines

Who builds the six advanced technologies of
`config-pypsa-earth/technology-assumptions/technology_assumptions.csv` (Gen IV nuclear, enhanced geothermal,
solid-oxide fuel cells, iron-air, vanadium flow and CO2 batteries), and how much of each is operating,
under construction, announced, or promised by year. The point is a feel for how much of each technology
could be available when, and from whom. That feeds the existing / post-FID / pre-FID seed volumes
(`existing_gw`, `pipeline_gw`) and the still missing build-rate limits of the learning market (SOW §1.2
technology scope, WP2 "existing / post-FID / pre-FID capacity").

```
../../models/priam-myopic/.pixi/envs/default/bin/snakemake -c1
```

`figures/<tech>.png|pdf` is one chart per technology; `figures/overview.png|pdf` puts all six on one page.

## Reading the charts

- **x** = year 2010-2040. **y** = cumulative capacity, in GW, or in MW when a technology stays below 1 GW.
  Storage charts have a GWh twin axis: exact for iron-air at 100 h, and at the capacity-weighted mean
  duration of the projects for VRFB (3.6 h) and CO2 batteries (9.2 h).
- **Colour = company.** The eight companies with the most on the table get a colour: the 2040 envelope incl.
  targets, plus announced projects without a year. Everything else goes into the steel "Rest of suppliers"
  band. The icon style allows six colours; two extra hues (rose, brown) were added because the request was
  one colour per company.
- **Fill = status.** The layers are stacked over all companies, in this order:
  - **operating**, solid: online, at the year of first power.
  - **under construction**, light and hatched: being built, post-FID, or a firm contract with a delivery
    date. Construction without a stated year is placed at next year.
  - **announced**, pale and dotted: pre-FID projects at their stated online year. Announced projects without
    a year are counted in a note in the top left but not drawn.
  - **stated targets**, outline hatching: offtake deals and corporate goals with a year, drawn as a straight
    line from the company's project total today to the stated MW at the stated year, flat afterwards.
    Statements are never summed, because one company's deals overlap: an option sits inside a framework, a
    framework contains PPAs, a named project sits behind a deal. The maximum is the conservative reading.
    Undated targets are listed in the note only.
- **Dotted line = stated factory capacity**, run at nameplate from its first year (an undated statement
  counts as current capacity, i.e. from next year) until 2040, on top of the area. It is the manufacturing
  ceiling, not a deployment statement, so it is not stacked. Where it rises far above the area, the chart
  clips it and the note gives its 2040 value.
- Projects still under construction or announced whose stated year has already passed are moved to next
  year: late, not cancelled.
- **Market = main continent** of a company: where its MW go, not its headquarters (NAM, SAM, EUR incl.
  Russia, ASI incl. the Middle East, AFR, OCE). The right panel lists the companies with their market tag,
  a bar of the 2040 envelope by market, and the layer totals in 2026, 2030 and 2040.

## Data

| File | Content |
|---|---|
| `data/projects.csv` | one row per project or phase: company, country, continent, MW (MWh for storage), status, online year, offtaker, source URL, note |
| `data/targets.csv` | company statements: `offtake`, `corporate_goal` (cumulative MW at a year) and `factory_capacity` (MW per year from a year) |
| `data/companies.csv` | per company: HQ, main continent and its basis |
| `data/gen4_vendor_map.csv` | GEM (project, model) -> reactor vendor, include yes/no |
| `../nuclear-projects/build/nuclear_units.csv` | Gen IV units from the GEM Global Nuclear Power Tracker (Aug 2026): families fast, htgr, fhr, msr, microreactor, gcr. GEM `pre-construction` and `announced` both count as announced; paused and ended units are dropped. Rows of projects.csv whose note starts `CORRECTS GEM:` replace the GEM unit of the same name. |

Rows whose note starts `CONVENTIONAL`, `HYDROTHERMAL`, `RESEARCH` or `EXCLUDE` stay in the data for
reference but are not counted (config `exclude_note_prefixes`). Curation edits made on top of the research
are marked `CURATED:` in the note. Every project and target row carries a source URL; all were collected on
2026-11-08.

Outputs in `build/`:

| File | Content |
|---|---|
| `pipeline.csv` | tech, company, layer, year, MW; layers not stacked; `factory` = ceiling above the targets |
| `companies.csv` | MW per company and layer, undated MW, undated targets, envelopes 2030/35/40, factory extra |
| `summary.csv` | GW per tech and layer in 2025/30/35/40 |
| `crosscheck.csv` | comparison with technology_assumptions.csv |

## What it says (2026-11-08)

Cumulative GW per layer, each layer counted on its own (the chart stacks them):

| Technology | Operating end-2025 | + construction | + announced, dated (undated) | + targets by 2040 | Factory ceiling 2040 |
|---|---|---|---|---|---|
| Gen IV nuclear | 2.3 | 1.9 | 5.2 (6.6) | 13.8 | 35.9 |
| EGS | 0.015 (0.054 by 2026) | 0.47 | 1.4 | 2.7 | – |
| SOFC | 1.6 | 2.4 | 1.6 | – | 47.6 |
| Iron-air | 0 | 0.03 | 0.34 (0.10) | – (undated: ~0.8 GW of Form agreements) | 6.6 |
| VRFB | 1.9 (7.9 GWh) | 0.8 | – (1.9) | – | 56 |
| CO2 battery | 0.04 (0.14 by 2026) | 0.08 | – (0.04) | – | – |

- **Gen IV:** North America holds most of the announced and promised capacity (Oklo, X-energy, TerraPower,
  Kairos, Aalo). What is actually running is Russian (BN-600/800) and Chinese (HTR-PM, CFR-600, CEFR).
  The targets are dominated by non-binding data-centre frameworks: Oklo–Switch 12 GW through 2044, cut at
  2040; X-energy–Amazon 5 GW by 2039. Aalo's claim of 1 GW/yr per factory is the largest factory ceiling.
- **EGS:** almost entirely Fervo (Cape Station: 33 MW online since Sept 2026, 466 MW under construction
  incl. Phase II) plus the US start-ups. The Google framework (3 GW by 2033) and Ormat's 1 GW by 2035 make
  the target layer.
- **SOFC:** Bloom is the only supplier at scale. Oracle (1.2 GW contracted plus up to 1.6 GW more), AEP
  Wyoming for Google (702 MW) and SK ecoplant fill 2026-28. Bloom's factory (2 GW/yr from 2027) and Elcogen's
  give a ceiling far above any stated deployment.
- **Iron-air:** Form Energy only at commercial scale. Next to nothing is under construction; Pine Island
  (300 MW / 30 GWh) is announced for 2028, pending regulatory approval. The 500 MW/yr factory and the
  ~80 GWh of agreements (undated) are the upside.
- **VRFB:** an almost purely Chinese market (Rongke, Shanghai Electric, Weilide, Liquid Flow); Invinity and
  Sumitomo are the non-Chinese suppliers. Stated Chinese factory capacity (Rongke 1 GW/yr, Xingchen
  2 GW/yr, Zhoukou 0.5 GW/yr) far exceeds deployment, which supports the "hype fades" reading of the market.
- **CO2 battery:** Energy Dome (Ottana 20 MW / 200 MWh, then Alliant, NTPC Kudgi, Offaly, SRP) and, counted
  here, the independent Chinese compressed-CO2 plants (Mulei 100 MW / 1 GWh, Sept 2026), which are already
  larger than Energy Dome's fleet.

### Against technology_assumptions.csv (not changed here)

| Technology | existing_gw CSV | operating end-2025 here | pipeline_gw CSV | construction here | Note |
|---|---|---|---|---|---|
| nuclear-gen4 | 1.7 | 2.3 | 1.2 | 1.9 | the difference is CFR-600 unit 1 (600 MW, its grid status is undisclosed) and unit 2 under construction; without CFR-600 the operating total is 1.7 |
| egs | 0.004 | 0.015 | 0.5 | 0.47 | here incl. the Upper Rhine plants and Desert Peak 2; US commercial ~0.04 GW by end-2026 |
| sofc | 1.4 | 1.6 | – | 2.4 | Bloom fleet ~1.5 GW + Ene-Farm Type S 0.07 GW |
| iron-air | 0.002 | 0 | 0.4 | 0.03 | the Cambridge MN pilot is not online yet (now 2027); Pine Island counts as announced, not construction |
| vrfb | 1.0 | 1.9 | – | 0.8 | the market total used for 2025 (Yahua) is the high one of four; with Project Blue (6.5 GWh) it would be ~1.8 GW at 3.6 h |
| co2-battery | 0.0025 | 0.043 | 0.04 | 0.08 | Ottana full scale (20 MW) online since July 2025, plus the Chinese plants |

## Caveats

- Press-release capacities: gross vs net is often not stated, and phases with "mid-2030s" or "end of the
  decade" are mapped to 2035 / 2030 (stated in the note of each row).
- Bloom stopped reporting acceptances after FY2023. Its 2024 and 2025 additions are differences between
  rounded installed-base statements, and 2025 (~0.1 GW) is probably far too low; analysts put 2025
  deliveries at 0.7-0.8 GW.
- Ene-Farm Type S is counted only up to 100,000 units (July 2020); no PEFC/SOFC split is published after that.
- VRFB: the four market statistics for 2025 disagree (2.2-4.2 GWh of additions). The "unattributed" rows
  close the gap between named projects and the chosen total. The pipeline of Chinese projects is mostly
  undated.
- Closed-loop geothermal (Eavor, XGS) is counted under EGS and marked `CLOSED-LOOP` in the note. The Upper
  Rhine and Cornwall plants are fault-hosted reservoirs with stimulation, so EGS only in a broad sense.
- CO2 battery: the Chinese compressed-CO2 plants (Exax / Dongfang Electric, Xi'an Jiaotong University
  technology) were developed independently of Energy Dome but use the same closed CO2 cycle with liquid
  storage, so they count as the same technology. Drop them by prefixing their note with `EXCLUDE`.
- Left out of the target layer:
  - PacifiCorp's 2025 IRP (511 MW of iron-air by 2030, 3.1 GW by 2045): a utility plan with no supplier named.
  - Ansaldo's 2022 Energy Dome plan: stale.
  - Bloom's "expandable to 5 GW/yr if needed": conditional.
  - Reverion's planned factory: not built.
- Factory ceilings mix cell and system capacity (Elcogen makes cells and stacks for SOFC and SOEC) and run at
  nameplate for 13-14 years. They bound what could be made, not what will be deployed.
- No retirements: BN-600 (1980) is still counted in 2040.
