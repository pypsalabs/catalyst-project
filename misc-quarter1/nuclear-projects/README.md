# Nuclear projects: existing, under construction and planned

A site-level dataset of nuclear power reactors worldwide (coordinates, reactor
type and model, capacity, status, dates, owner) joined with hand-collected
published cost estimates. Built for the SMR / advanced-nuclear part of the WP2
techno-economic baseline (SOW §1.2 technology scope; the "SMR at 4,000 EUR/kW"
breakthrough scenario) and for the pipeline of existing / post-FID / pre-FID
capacity that seeds the WP3 learning loop.

```
../../models/priam-myopic/.pixi/envs/default/bin/snakemake -c1
```

## Sources

| Source | What it gives | Access | Used for |
|---|---|---|---|
| **Global Energy Monitor, Global Nuclear Power Tracker, August 2026 release** | 1,825 reactor units, all statuses (operating, construction, pre-construction, announced, mothballed, shelved, retired, cancelled), reactor type and model, MW (gross, net, thermal), construction / criticality / grid / commercial dates, owner, operator, coordinates with accuracy flag, data-centre PPA flag, wiki page | CC BY 4.0; current release behind a registration form on globalenergymonitor.org (`data/gem_nuclear_tracker_2026-08.xlsx`, obtained 2026-09-30); the January 2023 snapshot is mirrored on GitHub without a form (`retrieve_gem_mirror` rule) | **backbone: every unit and site** |
| IAEA PRIS | authoritative status and dates of power reactors | web tables only, no bulk download (pris.iaea.org redirects to pris-stats.iaea.org) | cross-check, not ingested |
| OECD-NEA SMR Dashboard (digital dashboard, 4th edition, Sept 2026) | 156 SMR / micro-reactor projects tracked, 95 assessed (licensing, siting, financing, supply chain, engagement, fuel) | Power BI view and PDF only; no export, no coordinates, no cost figures | technology-readiness context only |
| World Nuclear Association reactor database / country profiles | status, type, dates, and the best-documented cost figures per project | web pages | cost sources in `data/project_costs.csv` |
| IEA / NEA, *Projected Costs of Generating Electricity 2020*; NEA (2020) *Unlocking Reductions in the Construction Costs of Nuclear* | overnight cost by country / recent project benchmarks | open PDFs | `data/nea_benchmarks.csv` |
| ECB reference exchange rates (annual averages) | conversion to the base currency | `data-api.ecb.europa.eu` (`retrieve_ecb_fx` rule) | currency conversion |

No public database carries per-project *costs*. Trackers (GEM, WNA, PRIS)
stop at capacity and dates; the NEA dashboard rates readiness, not money.
`data/project_costs.csv` is therefore hand-collected: one row per project and
estimate kind, the figure in the currency it was reported in, the cost basis
(overnight / total incl. financing / contract / budget / press estimate), the
estimate date and a source URL. It covers the sites under construction, the
pre-construction sites with a published figure, the headline SMR / Gen IV
projects and a set of recently completed reference plants (initial and final
cost). Treat basis and vintage with care: a Rosatom build-own-operate price
(Akkuyu) includes financing, an NPCIL sanctioned cost is a budget, an EDF
"2015 money" figure is overnight in constant money, a US utility figure often
includes financing costs.

## Outputs

| File | Content |
|---|---|
| `build/nuclear_units.csv` | 1,825 rows, one per reactor unit: GEM ids, country, project, unit, status, `status_group` (operating / construction / planned / paused / ended), reactor type, model, `family` (lwr-large, lwr-smr, htgr, fast, msr, fhr, microreactor, phwr, gcr, lwgr, fusion, unknown), MW (gross, net, thermal), dates, owner, operator, data-centre PPA flag, lat / lon, location accuracy, region |
| `build/nuclear_sites.csv` | 592 sites × status group: units, MW, families, models, first / last start year, construction start, coordinates, owner |
| `build/project_costs.csv` | 143 hand-collected cost rows for 104 projects (41 of the 47 sites under construction = 95 % of the MW, 46 of 58 pre-construction sites = 95 %, 20 announced sites, 6 completed reference plants), converted to USD2024 (`cost_musd2024`, `usd2024_per_kw`) and joined to the site's coordinates and family. `units_status` (built / construction / planned / cancelled) and `family` describe the costed units, not the whole site; `category` separates new-build figures (132) from restarts (4), partial contracts (2: Tianwan nuclear island, Kaiga EPC), programme totals (2: EDF's six EPR2), funding-only amounts (2: Wylfa allocation, Värö equity cap) and the Pele prototype |
| `build/nea_benchmarks.csv` | NEA / IEA published overnight costs in USD2024/kW |
| `figures/nuclear_sites_map.png` | world map of sites by status, marker size = MW |
| `figures/nuclear_cost_per_kw.png` | USD2024/kW per project, initial estimate → latest / final; colour = generation, marker = status of the costed units |
| `figures/nuclear_cost_strip.png` | the same projects as one jittered strip: colour = region (`cost_regions` in config.yaml), shape = reactor type (fusion and unknown dropped), area = MW covered (floor at ~150 MW). The marker sits at the *expected final cost*: the final cost for built plants, the latest revised estimate where one exists, else the initial figure × the region's median latest-or-final / initial ratio over same-scope pairs (real USD, so exchange-rate and inflation effects are taken out; pooled median over all pairs, ×1.27, where a region has fewer than `drift_min_pairs` of its own), with a thin line down to the published initial figure. The factor is a latest/initial ratio, so it is applied to initial-kind figures only: scaling Hinkley's or Sizewell's already revised estimate would double-count, while China's State Council approval totals and NPCIL sanctioned budgets are exactly the initial kind. Observed: West ×1.56 (10 pairs), Rosatom exports ×1.25 (5), Korea/Russia ×1.27 (3); India's two pairs are ≈×1.0 in real USD (rupee depreciation and inflation absorb the nominal +40–70 %). One panel (the density panel was removed on 2026-10-05): the legends sit side by side above the points, and the model inputs of the technology-assumptions CSV (`model_inputs` in config.yaml) are dashed lines in the colour of the group they stand for (`group` per row), labelled in the right margin. Region means for reference: China / India 3,164 USD/kW (median 3,200, n = 28), West large LWR 10,904 (9,864, 20), West light-water SMR 13,297 (13,303, 9). |

## Conventions and caveats

- **Family**: from GEM's reactor type, refined by model (KP-FHR → fhr, IMSR /
  ThorCon / SSR → msr, Aurora / ARC-100 → fast, BANR → htgr, PWR-20 / Aalo → microreactor)
  and size (PWR / BWR units ≤ 350 MW → lwr-smr). GEM's own "small modular
  reactor" type is a marketing label, hence the refinement.
- **Status groups**: GEM infers "cancelled - inferred 4 y" and "shelved -
  inferred 2 y" from research inactivity; they are grouped with cancelled /
  shelved. "Planned" = pre-construction + announced; announced projects are a
  wish-list (e.g. 18 GW in Uganda), not a pipeline.
- **Money**: as in `../technology-costs`, a figure is exchanged at the ECB
  annual-average rate of its price year and inflated with US CPI to 2024. The
  price year is the `price_year` column where the source states money-of-year,
  else the estimate year. RUB after March 2022 uses Bank of Russia annual
  averages (config.yaml).
- **Cost per kW** divides by the net capacity the figure covers, which for
  multi-unit sites and shared infrastructure (Darlington: C$1.6 bn common
  works for four units) is a judgement recorded in `scope` and `note`.
- **What the numbers say** (latest / final new-build figures, USD2024 per kW of covered
  capacity): China clusters at 2,100–3,300 (State Council approvals, ~CNY 20 bn per Hualong /
  CAP1000 unit); India PHWRs 1,500–2,600; Russian / Rosatom export builds 4,000–7,000; Korea
  3,200–3,500; Western large LWRs 8,000–20,000 (Vogtle final ≈ 16,000, Flamanville ≈ 18,000,
  Hinkley ≈ 22,000 in 2015-money converted); Western LWR SMRs with a firm figure 12,000–19,000
  (Darlington BWRX-300, CFPP, Clinch River, Doicești). Initial → latest tails show the FOAK overrun
  (Vogtle 2.5×, Olkiluoto 3.4×, Flamanville 6×, Kola II 4×). Compare with the SOW "SMR at
  4,000 EUR/kW" breakthrough: no Western project is within a factor of two of it.
- GEM data errors found so far: Sizewell C1-2 typed as PHWR (fixed by the EPR model
  override in config.yaml). Xiapu's CFR-600 fast reactors are absent from the tracker.
- Coordinates flagged `approximate` (616 of 1,825 units) are typically the
  nearest town for announced projects.
- The GEM xlsx must not be regenerated by rule; the Snakefile takes it as an
  input. Re-downloading a newer release means re-submitting the form and
  updating `gem.file` / `gem.release` in `config.yaml`.
