# Land grid map

Interactive world map that draws a Mercator quadtree grid over land, sizes each square by
population and colours it by the power-system archetype (Google / PyPSA Labs SOW §1.2) the
country, or sub-national grid, is classified into. Open `index.html` in a browser; only the basemap tiles
need the network.

Ported from the Claude Design project "Interactive map with land grid overlay"; archetype colours
and icons from "Power System Archetype Icons".

## Files

| File | Purpose |
| --- | --- |
| `index.html` | the page, no build step |
| `data/countries.js` | Natural Earth 1:50m countries (world-atlas TopoJSON), embedded so file:// works |
| `data/population.js` | GPW v4 2020 population count, 4 arc-minute grid, log-encoded PNG in base64 |
| `data/regions.js` | grid regions replacing their country: sub-national splits (US East incl. ERCOT / West, plus Alaska and Hawaii as unmodelled regions, Australia NEM/SWIS, Malaysia Peninsular/Borneo) and the merged North-West Europe region `NWE` (Iberia, France, Germany, Benelux, UK; `replaces` lists all eight parents), built by `../build_regions.py` |
| `data/archetypes.js` | the five archetypes: id, names, colour, tint, SVG icon |
| `data/layers/*.js` | data versions (see below), one file each |
| `../prepare_population.py` | rebuilds `data/population.js` from the GPW Cloud Optimized GeoTIFF (pipeline repo) |
| `../classify.py` | rule-based decision tree → `data/layers/rules-v1.js` (modelled: North-West Europe, US West, Australia SWIS, Brazil, US East) plus the `explain` block behind the Rule-based tab |
| `../cluster_tsne.py` | k-means on engineered features → `data/layers/clusters-v1.js` (cluster archetypes `k_*` in `archetypes.js`, modelled: India, US East, North-West Europe, US West, Brazil, plus a display-only grey islanded archetype carried by Singapore) plus the `explain` block behind the KMeans clustering tab |

## Data versions

Each data version is a JS file that pushes one object onto `window.LAYERS`. The panel has three
tabs: **Map** (the map, with the classification dropdown, archetype meanings and share bars),
**KMeans clustering** and **Rule-based** (full-screen views of how each classification was made).
`?layer=<id>` selects a data version by URL.

```js
window.LAYERS = window.LAYERS || [];
window.LAYERS.push({
  id: 'run-2026-03',                  // URL id
  name: 'March 2026 run',             // dropdown label
  description: 'one sentence shown under the dropdown',
  archetypes: ['dense', 'geothermal', 'islanded', 'hydro', 'fossil'],   // optional: wheel order,
                                      // ids from data/archetypes.js; an entry may be an object
                                      // { id: 'hydro', color: '#123456' } to override a definition
  modelled: { dense: '276', geothermal: '792', islanded: '036', hydro: '076', fossil: '356' },
  countries: {
    '276': { archetype: 'dense', proximity: 1.0 },    // Germany
    '250': { archetype: 'dense', proximity: 0.82 },   // France
    ...
  }
});
```

- Country keys are ISO 3166-1 numeric ids as strings (as in Natural Earth), or the exact Natural
  Earth name for the few geometries without an id (Kosovo, Somaliland, ...). The split regions are
  keyed by their grid code (`USE`, `USW`, `AUN`, `AUW`, `MYW`, `MYE`, `NWE`); the parent ids (840,
  036, 458 and the eight North-West European countries) are not drawn.
- `proximity` is 0..1 and is carried through to the CSV export. Cells are drawn in the archetype's
  full colour; set `PROXIMITY_SHADING = true` in `index.html` to fade towards white with low
  proximity instead. Countries missing from `countries` are drawn light grey.
- `modelled` names the one representative country per archetype; those get the black cell outline
  and are listed in the Legend tab.
- Optional `totals`: `{ population: {dense: n, ...}, demand_twh: {...}, emissions_mt: {...} }`,
  absolute sums per archetype. When present, the Legend tab shows three vertical stacked bars with
  each archetype's share of the quantity. `totals_meta[q].label` sets the bar label. `classify.py`
  fills these from `country_features.csv` and the Ember yearly release.

To add a version: drop the file in `data/layers/` and add a `<script src="data/layers/<id>.js">`
tag in `index.html` next to the existing ones. The order of the script tags is the dropdown order.

Unresolved country keys are counted and shown under the dropdown description.

Optional `explain` feeds the two method tabs, which replace the map with two columns. The block's
`kind` says which tab it belongs to:

- `kind: "kmeans"` (written by `cluster_tsne.py`): left, one row per cluster with the centroid and
  the six largest grids by 2050 demand as cards with a seven-bar z-score profile; right, the t-SNE
  projection. Schema: `features: [{id, label, unit, desc}]`, `centroids: {archetype: [z...]}`,
  `rows: [{key, iso3, name, cluster, proximity, demand_twh, demand_twh_2050, x, y, z, disp, override}]`,
  `method`.
- `kind: "rules"` (written by `classify.py`): left, one row per archetype with the six largest grids
  as cards showing each raw feature on its own scale with the rule thresholds as ticks and a badge
  for the rule that fired; right, the ordered decision tree with counts per rule and the fallback
  membership scores. Schema: `features: [{id, label, unit, desc, thresholds, ticks}]`,
  `rules: [{id, archetype, title, cond, note}]`, `scores: {archetype: text}`,
  `rows: [{key, iso3, name, archetype, rule, proximity, demand_twh, v, disp, path: [{rule, pass, why}], scores}]`,
  `method`.

Hovering a bar, a card, a feature chip, a point or a rule shows the details; a card highlights its
point (k-means) or its path through the tree (rules). Each tab uses the selected data version if it
carries a block of its kind, otherwise the first one that does.

## Grid cells

The grid is a quadtree of the Web Mercator world: level `k` has `2^k` cells across, a cell is
`(k, i, j)` with `i` counting east from 180°W and `j` south from the top Mercator edge (85.05°).
A cell's country is decided by its centre point. The level follows the zoom and the cell-size
slider unless "Lock grid level" is on. "Export cells at this level (CSV)" writes every land cell
at the current level with bounds, area, country, population, density, archetype, proximity and a
`modelled` flag (levels up to 10).

## URL parameters

The display options have no controls in the UI; they are set through the URL (or
`landGrid.set({...})` in the console): `layer`, `sizeBy` (uniform|population), `colorBy`
(uniform|population|country|archetype), `data` (population|demo), `basemap` (light|streets),
`cellPx` (default 8), `alpha`, `lockK`, `tab=legend|kmeans|rules`, `lat`, `lon`, `zoom`,
`highlight=modelled|none|Name,Name`, `seed` (random outline pick). `landGrid.exportCsv()` downloads
every land cell at the current level.

`shot=map|archetypes|shares|tsne` (with `w`, `h` in CSS px) is the export mode behind
`../screenshot_map.py`: it shows only the map (pinned to `w` x `h` at the top left, no panel or
controls), only the archetype list / share bars of the Map tab, or only the cluster key and t-SNE
plot of the KMeans tab, each on white, for headless Chrome to screenshot. The kickoff deck's
Snakefile renders its four images that way.

Example: `index.html?layer=clusters-v1&lat=20&lon=30&zoom=3`

## Rebuilding data

This directory is its own git repository holding only the static page and its data. The scripts that
produce the data live one level up in the `scripts/sep` pipeline (part of the main project repo) and
write into `data/` here. Run them from `scripts/sep`:

```
~/micromamba/envs/pypsa-demand/bin/python prepare_population.py   # data/population.js; needs rasterio + Pillow
../../models/priam-myopic/.pixi/envs/default/bin/python build_regions.py   # data/regions.js; needs geopandas
../../models/priam-myopic/.pixi/envs/default/bin/snakemake -c1           # data/layers/rules-v1.js (classify.py)
../../models/priam-myopic/.pixi/envs/default/bin/python cluster_tsne.py   # data/layers/clusters-v1.js
```

After regenerating, commit the changed files here and push; Vercel redeploys from the repo.

## Deploying

The page is static: deploy this directory as-is (for Vercel, `vercel deploy` from
`scripts/sep/land-grid-map`, no build step, output directory `.`). Only Leaflet and the basemap
tiles are fetched from the network; the repository is about 5 MB.

## Memory

Steady state is about 120 MB of JS heap: the population grid as 16-bit log codes with a lookup
table (29 MB) plus its float sum pyramid (19 MB), and the 4096² country mask as 8-bit indices
(17 MB). Both are decoded from their canvases in row bands so no full-size RGBA copy is held.
`?memprobe=1` writes the heap size into the page title after 25 s.
