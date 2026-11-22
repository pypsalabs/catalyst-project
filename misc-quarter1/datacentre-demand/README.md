# Data-centre electricity demand by region, 2020-2050

How much electricity data centres use, where, and what share of all electricity demand that is: the anchor for the
share of demand that the model lets procure 24/7 carbon-free electricity (`config-pypsa-earth/overlay.cfe.yaml`,
`catalyst.cfe.share`: 1 % of demand in 2030, linear to 10 % in 2050, the same in every region; SOW §1.4 scenario S2).
Started 2026-11-18.

```bash
../../models/priam-myopic/.pixi/envs/default/bin/snakemake -c1      # or run the two scripts by hand
```

| File | Content |
|---|---|
| `data/iea_regions.csv` | IEA: data-centre consumption per year and region 2020-2030 (history to 2024, Base Case after) |
| `data/iea_world_cases.csv` | IEA: world total per year 2025-2035 in the Base Case and the three other cases |
| `data/outlooks.csv` | outlooks of other publishers (world, US, China, Europe), one sourced row per value |
| `data/buyers.csv` | electricity use of the corporate buyers (RE100 total and 57 companies per year), one sourced row per value |
| `data/re100_markets.csv` | RE100 members' electricity consumption of 2024 by market (the report's appendix table, 480 of 557 TWh) |
| `data/iea_table_a4.csv` | IEA: data-centre consumption of the United States, China and six regions, 2023 to 2030 (the regional fallback of the country table) |
| `data/datacentre_countries.csv` | data-centre consumption per country, one sourced row per value with the words of the source; `use` marks the rows the table is built from |
| `data/sources_collected.csv` | the 188 source rows of the first research round (regions and countries), kept as collected |
| `scripts/build_series.py` | regional series 2020-2050 + total electricity demand of the same regions -> `build/series_<variant>.csv` |
| `scripts/plot_overview.py` | `figures/datacentre_demand_<variant>.{png,pdf}` |
| `scripts/plot_buyers.py` | `figures/corporate_buyers.{png,pdf}` |
| `scripts/build_buyer_share.py` | data centres plus the other use of RE100 members as a share of demand in 2030 -> `build/buyer_share.csv`, `build/re100_countries.csv` |
| `scripts/build_country_share.py` | the share per country and horizon -> `build/country_share.csv`; with `--tables` (rule `model_tables`) the model's tables `config-pypsa-earth/calibration/<year>/cfe_share.csv` |
| `scripts/ftlook.py` | the look of the figures (layout after the Financial Times' charts on a white background; asked for, the repo default is `plotstyle/`) |

## The figure

`figures/datacentre_demand_<variant>.png`: left, stacked areas of data-centre consumption by region; right, the same as a
share of the region's total electricity demand, with the global share in black and the model's share of 24/7 buyers
as a grey line. Three stretches of years, told apart by the strength of the fill and by the line style:

| Years | Data centres | Total demand (denominator) |
|---|---|---|
| 2020-2024 | IEA estimate per region | Ember yearly data |
| 2025-2030 | IEA Base Case per region | the model's demand pathway (Ember 2024 x outlook consensus, `build_demand_pathway.py`) |
| 2031-2035 | IEA Base Case for the world; **assumption**: regions keep their 2030 shares of it | same |
| 2036-2050 | **assumption, no source**, one rule per variant (below); regions keep their 2030 shares | same |

The whisker at 2035 is the span of the IEA's four cases (942 to 1,637 TWh in the 2026 update; 707 to 1,719 TWh in the
first edition). The hollow dots are world outlooks of other publishers.

Two variants of the stretch after 2035 (`config.yaml`, `variants`):

| Variant | Rule | World 2050 | Global share 2050 | US share 2050 |
|---|---|---|---|---|
| `trend` | the Base Case's mean yearly increment of 2030-2035 (50 TWh a year) continues | 1,937 TWh | 3.5 % | 14.6 % |
| `outlooks` | straight line from the Base Case of 2035 to the median of the three published 2050 values | 3,500 TWh | 6.4 % | 26.5 % |

**`trend` is the variant in use** (decided 2026-11-19): the years to 2035 matter most, because the catalytic effect
of early procurement sits there, and to 2035 the two variants are the same numbers. `outlooks` stays as a cross-check.

Neither is a forecast. `trend` ends below every published outlook for 2050; `outlooks` joins two bodies of work that
disagree already in 2035 (IEA Base Case 1,193 TWh, BNEF's pipeline-based case 2,354 TWh), hence its kink.

## Numbers

Data centres' share of electricity demand, % (both variants agree to 2035):

| Region | 2020 | 2024 | 2030 | 2035 |
|---|---|---|---|---|
| United States | 2.6 | 4.1 | 8.8 | 10.3 |
| China | 0.8 | 1.0 | 2.3 | 2.4 |
| Europe | 1.4 | 1.8 | 2.5 | 2.8 |
| Asia excl. China | 0.6 | 0.8 | 1.3 | 1.3 |
| Rest of world | 0.2 | 0.3 | 0.5 | 0.6 |
| World | 1.0 | 1.3 | 2.6 | 2.8 |

The shares of 2020-2024 reproduce Our World in Data's (IEA numerator over Ember demand: world 1.01 / 1.34 %, US 2.64 /
4.15 %). The IEA's own shares are higher (world 1.5 %, US 4.4 % in 2024) because its demand total is final
consumption without losses.

## Sources and how they were read

- **IEA, Energy and AI (April 2025)** and its update **Key questions on energy and AI (April 2026)**, both CC BY 4.0,
  PDFs on `iea.blob.core.windows.net` (URLs in the CSV headers; `www.iea.org` itself sits behind a bot check). The
  annual regional series is Figure 2.12 of the first report, read off the vector chart of the PDF; it agrees within
  1 TWh with the annex tables (Table A.4: 2020, 2023, 2024, 2025, 2030). The update left the Base Case to 2030
  unchanged (945 TWh) and narrowed the other cases. The IEA calls everything after 2030 exploratory and publishes no
  regional split after 2030, no number after 2035 and no regional values for the cases other than the Base Case.
- **Scope of the IEA numbers**: enterprise, colocation and hyperscale facilities, whole facility (IT x PUE);
  telecom networks (about 280 TWh in 2023) and crypto mining (about 125 TWh) are not in. All past values are modelled
  estimates. Europe is the wide grouping (EU-27, UK, Norway, Switzerland, Iceland, Türkiye, Ukraine, Israel, Western
  Balkans, Belarus, Moldova), China includes Hong Kong, and "Asia excl. China" leaves Australia and New Zealand in the
  rest of the world. `config.yaml` rebuilds these regions from the outlook regions of the demand tables.
- **Other outlooks** (`data/outlooks.csv`): read on 2026-11-18 from the URL of each row; `primary` says whether that is
  the publisher's own text.

## Caveats

- **The IEA Base Case is at the low end of what is published in 2026.** United States 2030: IEA 426 TWh, LBNL's 2025
  update 649 TWh (521 to 843), EPRI 380 to 790 TWh, BNEF 12 % of US consumption and about 20 % in 2035. China 2030:
  IEA 277 TWh, Rystad 289, CAICT 400, Wood Mackenzie 774, the energy administration about 800. World 2035: IEA 1,193
  TWh, BNEF 2,354. The newer the forecast, the higher (BNEF's US capacity for 2035: 78 GW in April 2025, 106 GW in
  December 2025, 194 GW in July 2026).
- **China has no consistent series**: the IEA counts about 100 TWh in 2024, Chinese counts 140 TWh (2024) and
  170 TWh (2025, "computing centres"), and older official figures have 200 TWh already in 2020.
- **The denominators do not know about the data centres.** The model's US demand grows by 416 TWh from 2024 to 2030;
  the IEA's US data centres alone add 244 TWh and LBNL's 457 TWh. The demand pathway is a consensus of general
  outlooks; with the higher data-centre forecasts the shares here are overstated and the demand pathway understated.
- **Regions are coarse.** Within them the share differs by an order of magnitude: Ireland 23 % of metered consumption
  in 2025 (CSO; 5 % in 2015), Virginia about 25 %, Malaysia 7 % today and 18 to 33 % in 2035 (BNEF, the ministry),
  Australia's NEM 3 % today and 13 % in 2036 (AEMO), against 0.5 % in India and less in Africa. BNEF expects 34 %
  of PJM's and 22 % of ERCOT's electricity to go to data centres in 2035.
- **Two BNEF figures are ambiguous** and noted in the header of `data/outlooks.csv`: the 2025 outlook's 1,200 / 3,700 TWh
  may be increments, and the 2026 outlook's "1,114 TWh by 2050" is not a 2050 value by its own percentages.
- **Not opened**: IIASA (Fan, Wilson, Kamiya, Mastrucci, Energy and Climate Change 7, 2026; 1,800 to 5,000 TWh in
  2050 across the SSPs, pure.iiasa.ac.at/21676, behind a bot check), the only peer-reviewed 2050 range seen.

## What this means for the model's 24/7 share

Data-centre demand is not the demand that procures 24/7: only part of it belongs to buyers with an hourly-matching
goal, and some such buyers are not data centres (next section). As an upper bound per region it still says that one
share for all regions cannot be right: 1 % in 2030 is below the data centres' share in the United States (8.8 %),
Europe (2.5 %) and China (2.3 %) and above it in the rest of the world (0.5 %); 10 % in 2050 is reached by data
centres only in the United States, in either variant.

## Data centres plus RE100: a combined buyer share

`scripts/build_buyer_share.py` -> `build/buyer_share.csv`. Data centres and RE100 members are two sets that overlap,
neither holds the other: of the 416 TWh that data centres used in 2024, the RE100 members Google, Microsoft, Meta,
Apple and Equinix account for about 92 TWh; the rest belongs to non-members (Amazon, the Chinese operators, most
colocation and enterprise sites). Of the members' 557 TWh, about 465 TWh are not data centres (chip and electronics
plants, solar manufacturing, telecoms, retail). The combined share of a region in 2030 is

    data centres (IEA Base Case 2030)  +  weight x RE100 members' other use (2024, held at its 2024 share of demand)

| Region | Data centres 2030, % | RE100 other, % | weight 0.5, % | weight 1, % |
|---|---|---|---|---|
| United States | 8.8 | 1.4 | 9.5 | 10.2 |
| China | 2.3 | 1.1 | 2.8 | 3.3 |
| Europe | 2.5 | 1.3 | 3.2 | 3.8 |
| Asia excl. China | 1.3 | 3.8 | 3.2 | 5.1 |
| Rest of world | 0.5 | 0.4 | 0.7 | 0.9 |
| World | 2.6 | 1.5 | 3.3 | 4.1 |

The weight is a choice (`config.yaml`, `buyer_share: mixes`), not a source. What is assumed on the way:

- The members that gave RE100 no breakdown by market (77 of 557 TWh) are spread over the regions like the others.
- The five operators' 92 TWh are taken out of each region in proportion to its data-centre use, China left out. Their
  own regional split was not read from their reports.
- The other use of the members keeps its 2024 share of demand to 2030. The members' total was nearly flat from 2023 to
  2024 (545 to 557 TWh), so this is on the generous side unless membership grows.
- Being a member means an annual 100 % renewable goal, not hourly matching.

"Asia excl. China" hides the largest differences (`build/re100_countries.csv`, members' consumption as reported over
the country's demand of 2024): South Korea 11.2 %, Taiwan 12.9 %, Japan 4.6 %, Vietnam 2.6 %, India 0.65 %. Outside
Asia: United Kingdom 3.4 %, United States 2.3 %, Germany 2.2 %, Brazil 0.8 %. The data-centre series has no country
rows, so a combined share per country is not built.

## The share per country: the table the model reads

Decided 2026-11-19: the share of a country's demand that may procure 24/7 CFE is

    share = min(cap, scale x (data centres + 0.5 x RE100 other))        (config.yaml `buyer_share`: weight, scale, cap)

with scale 1.0 until the share is brought down to what 24/7 CFE supply can plausibly come online by 2030, and a cap
of 20 % of a country's demand (the level is a choice; it binds on Ireland from 2030 and on Denmark from 2045, and
takes from the data centres' part).
`scripts/build_country_share.py` builds it for every country of the model's demand tables and the horizons 2030 to
2050; `snakemake -c1 model_tables` writes `config-pypsa-earth/calibration/<year>/cfe_share.csv` (columns country,
share, datacentres, re100 = the two parts of the share, basis, capped). The rule is not part of `all`, so the model's tables
change only when asked.

Data centres in 2030, by the first rule that applies (`basis`):

| basis | Rule | Countries (2026-11-19) |
|---|---|---|
| `country` | a sourced value for 2030 | IE, GB, DE, FR, DK, CH, JP, AU, MY, ID, SG |
| `interpolated` | a history value and a later value of one publisher, joined by constant growth | IN, BR (BloombergNEF 2025, 2035), KR (2025, 2038), PL (2025, 2035) |
| `history` | a sourced history value x the growth of the country's IEA region to 2030 | NL |
| `iea` | the IEA's own row | US, CN (with Hong Kong) |
| `region` | the IEA region's data-centre use spread by demand | all others |

After 2030 a country's data-centre use grows like the world total of the `trend` variant; RE100's other use keeps its
2024 share of demand. Which row of `data/datacentre_countries.csv` is in use follows the rules in that file's header
(a source read directly before a quoted one; the central scenario; the lower end of a range).

Caveats:

- **The sources do not add up.** The country values sum to 161 TWh in Europe against the IEA's 114 TWh, and to
  179 TWh in Asia Pacific outside China against 101 TWh; the world is 1,075 TWh against 945 TWh. They are not
  reconciled, and a country without a value keeps the full regional share (so Afghanistan or Pakistan get the 1.4 %
  of their region, which is too high for them).
- **Large shares.** Before the cap Ireland is at 35 % of demand in 2030 (EirGrid's median: 32 % for data centres
  and "new technology loads") and the world-trend growth after 2030 would take it to 49 % in 2050, which no source
  says; hence the cap. Below it: Denmark 16 %, Malaysia 14 %, Singapore 12 % in 2030.
- **Sources that disagree.** Brazil: BloombergNEF 2 TWh (2025), Brasscom 11.3 TWh (2024), EPE 3 TWh (2026) and 30 TWh
  (2036). India 2030: 32 TWh on BloombergNEF's path, 57 TWh at S&P Global. Germany 2030: 25 to 38 TWh. Malaysia
  2030: BloombergNEF 33 TWh, Ember 68 TWh.
- **Not in use although found**: Netherlands 15 % in 2030 (read in a bank's note on the grid operators' scenarios).
- **No value found**: Belgium (elia.be refuses automated requests), Austria, Czechia, Luxembourg, Taiwan, New Zealand,
  South Africa, Morocco; Ireland, the Netherlands, Poland, Brazil and South Korea have no 2030 value in TWh read at
  the source.
- Read in a press report, not in the document: Singapore, South Korea, Poland.
- `data/iea_table_a4.csv` is from an annex under CC BY-NC-SA 4.0; check before the repo's data go out under CC BY 4.0.

Figures of the table are in the model doc (`config-pypsa-earth/model-doc`, section "Demand for 24/7 Carbon-Free
Electricity": `scripts/plot_cfe_*.py`, study style).

## Who would buy: RE100 members and the large technology companies

`figures/corporate_buyers.png` (`data/buyers.csv`, 2018-2024): the electricity use of the RE100 members that report,
with the 18 largest members that publish a figure every year named (`config.yaml`, `buyers`), and shares of world
demand (Ember). RE100's reports give the members' total and, per member, only percentages, so every company's
consumption is read from its own sustainability report (57 companies in `data/buyers.csv`, each row with period, scope
and source).

| Named members, TWh | 2018 | 2020 | 2022 | 2024 |
|---|---|---|---|---|
| Big tech (Google, Microsoft, Meta, Apple) | 23 | 36 | 54 | 84 |
| Chips and electronics (Samsung Electronics, TSMC, SK hynix, Hon Hai, Intel, Samsung Display) | 0 | 35 | 78 | 97 |
| Solar manufacturing (Tongwei, LONGi, Jinko Solar) | 0 | 3 | 15 | 57 |
| Telecoms (Deutsche Telekom, Verizon, Telefónica) | 7 | 7 | 18 | 27 |
| Retail and industry (Seven & i, General Motors) | 6 | 13 | 13 | 13 |
| Named, share of the RE100 total | 16 % | 27 % | 37 % | 50 % |

- A company counts from the year it joined RE100 and from the first year it has a figure; before that its load is in
  "Other members". The total grows mostly by new members: Samsung Electronics (32 TWh) joined in 2022, Tongwei
  (37 TWh in 2024, polysilicon) in 2023, Hon Hai and Verizon (10 TWh each) in 2024. Deutsche Telekom (member since
  2019) and LONGi (2020) enter the figure in 2021, the first year with a figure.
- The other half is about 390 members, none above roughly 7 TWh except Walmart: a member since 2015 with no published
  electricity figure (about 24 TWh by an unverified estimate; "did not report" in RE100's 2025 report).
- Left out of the named set although large: Equinix (8.6 TWh, not in RE100's 2025 member table), Vodafone (5 TWh, no
  figure for its fiscal year 2020), Procter & Gamble (5.6 TWh, no figure for 2023). Weak points of single values are
  listed in the header of `data/buyers.csv`.

| Share of world electricity demand, % | 2018 | 2020 | 2022 | 2024 |
|---|---|---|---|---|
| RE100 members (all sectors; annual matching) | 0.86 | 1.27 | 1.66 | 1.80 |
| All data centres (IEA) | | 1.01 | 1.12 | 1.35 |
| Google, Microsoft, Meta, Apple | 0.09 | 0.13 | 0.19 | 0.27 |
| Google and Microsoft (goal of hourly matching by 2030) | 0.07 | 0.10 | 0.14 | 0.20 |

- RE100's 557 TWh of 2024 is larger than all data centres (416 TWh) because most of it is manufacturing, not computing;
  293 TWh of it is in Asia, 108 TWh in North America and 61 TWh in Europe (480 TWh carry a market). 59 % was reported
  as renewable, on annual matching. Growth has flattened (545 TWh in 2023).
- The two companies with a public goal of hourly matching used 61.5 TWh in 2024 and 80.6 TWh in 2025 (Google 43.6,
  Microsoft 37.0 in its fiscal year 2025): 0.20 % and about 0.25 % of world demand, growing by a quarter to a third a
  year. Google's hourly carbon-free score has stayed at 64 to 66 % since 2020 (2025: Europe 83 %, North America 68 %,
  Asia Pacific 13 %); Microsoft publishes no hourly score. No source gives the volume procured under hourly matching.
- Not in the figure: Amazon (24 TWh in 2020 and 30.9 TWh in 2021 including logistics, no figure since, not an RE100
  member), Tencent (8.7 TWh in 2025), Alibaba (8.3 TWh in its fiscal year 2024), Oracle (reports energy, not
  electricity). Fiscal years are drawn at the calendar year they end in.
- Corporate clean PPAs (BloombergNEF): 13.4 GW signed in 2018, 62 GW in 2024, 55.9 GW in 2025, of which 29.5 GW in
  the United States; Meta, Amazon, Google and Microsoft signed 49 % of the 2025 volume.
- Hourly matching by regulation: the EU's rule for renewable hydrogen requires hourly correlation from 2030 (the
  Commission's 10 Mt ambition would need 500 to 550 TWh, an ambition and under review in autumn 2026); the US 45V
  credit is limited to plants that start construction before 2028.

Read together with the data-centre shares: the buyers with an hourly goal today are 0.2 % of world demand; if they
grow with the data-centre market they reach roughly 0.5 % by 2030, all hyperscale facilities about 1 % (381 TWh
in ABI Research's forecast, abiresearch.com/blog/data-center-energy-consumption-forecast), all data centres 2.6 %. The model's 1 % in 2030 is therefore an upper reading for the world as a whole, and far off region by
region.
