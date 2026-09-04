---
name: compile-figures
description: Compile the priam-myopic model figures if they are not present already, then show them. Use when the user asks for the model's plots/figures/results and results are missing or stale, or asks to (re)run the model.
---

# Compile priam-myopic figures

Repo: `models/priam-myopic` (relative to this project root). Figures land in
`models/priam-myopic/results/<run>/<scenario>/plots/` and
`.../results/<run>/plots/world-scenarios/` where `<run>` and the scenario list
come from `config.yaml` (`run:` and `scenarios:` keys).

## 1. Check whether figures already exist

```bash
RUN=$(grep -oP '^run:\s*"\K[^"]+' models/priam-myopic/config.yaml)
ls models/priam-myopic/results/$RUN/*/plots/*.png 2>/dev/null
```

If they exist and the user didn't ask for a re-run, skip straight to showing them (/show skill: `eog` on the PNGs).

## 2. Prerequisites (verify, don't assume)

- **Octant weather data** in `models/octants/` (config `octant_folder: "../octants/"`).
  Files are `octant-2011-{quadrant}-{hemisphere}-{solar|onwind}.nc`, ~292 MB each, from
  `https://model.energy/octants/<filename>`. Download any that are missing or zero-size:

  ```bash
  cd models/octants
  for oct in 0-0 0-1 1-0 1-1 2-0 2-1 3-0 3-1; do for tech in solar onwind; do
    f="octant-2011-${oct}-${tech}.nc"
    [ -s "$f" ] || curl -sf -o "$f" "https://model.energy/octants/$f"
  done; done
  ```

- **Pixi environment**: `cd models/priam-myopic && pixi install --locked` (idempotent).
- **Gurobi license**: `~/gurobi.lic` must exist.

## 3. Run

```bash
cd models/priam-myopic && pixi run snakemake -c12
```

Run this in the background (takes ~10–40 min from scratch; seconds if only plots
are outdated). Snakemake is incremental — it only rebuilds missing/stale outputs.
Monitor via the Snakemake output; solver logs are in `results/<run>/<scenario>/logs/`.

## 4. Show

Open the resulting figures with the /show approach, e.g.:

```bash
(nohup eog models/priam-myopic/results/$RUN/*/plots/*.png >/dev/null 2>&1 &)
```

## Troubleshooting

- `gurobipy` license errors → check `~/gurobi.lic` and `GRB_LICENSE_FILE`.
- Missing octant errors name the exact file — download just that one.
- To force a full re-run: `pixi run snakemake -c12 --forceall`, or delete
  `results/<run>/`.
