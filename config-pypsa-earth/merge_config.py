# SPDX-License-Identifier: CC0-1.0
"""
Build models/pypsa-earth/config.yaml for one run.sh stage and print its Snakemake target.

    pixi run python ../../config-pypsa-earth/merge_config.py <kind> <stage> <out.yaml> [<planning horizon>]
    pixi run python ../../config-pypsa-earth/merge_config.py horizons <stage>     (myopic: prints the horizons)

kind = prenetwork : config.<stage>.yaml copied as is; target networks/<stage>/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}.nc
kind = overlay    : stage <R>-<scen> = config.<R>.yaml deep-merged with overlay.<scen>.yaml, run.name = stage,
                    catalyst.base_run = R; target results/<stage>/plots/validation_elec_s..._{opts}.png
kind = dashboard  : stage <R> = config.<R>.yaml + the validation custom rule; target results/catalyst/validation_<R>.png
kind = assumptions: no network; the technology-assumptions custom rules only; target the assumptions PDF
                    ../../config-pypsa-earth/technology-assumptions/build/technology_assumptions.pdf
Every merged config carries technology-assumptions/assumptions.smk in custom_rules, so the assumptions
document and the rule that feeds technology_assumptions.csv into the cost table are part of every stage.
Palette stages (catalyst.palette: true in the overlay, e.g. overlay.myopic.yaml): technology_assumptions.csv
decides what the model may build (technology-assumptions/scripts/palette.py): its `model`, `carrier`, `regions`,
`availability`, `min_load`, `fuel` and `color` columns become electricity.extendable_carriers (all four lists),
extendable_carriers_buses: all, max_hours, the fork's `conventional:` block, calibration.fuel_map, plotting, and
costs.overrides = resources/<stage>/palette/costs_{year}.csv, written per year by assumptions.smk (palette_costs)
from the CSV. Supply-curve technologies (model tranches) take their dataset and binning from the overlay's
supply_curves.<carrier> block (cutout filled in from the base config); without such a block they are not built.
Every overlay stage runs in USD (costs.output_currency), the currency of the CSV and of the calibration price tables.
Rest-of-world groups (catalyst.single_node in config.<G>.yaml, written by scripts/select_countries.py): catalyst.extra_opts
(ATKc) is prepended to every overlay opt (3h -> ATKc-3h, Co2L0-3h -> ATKc-Co2L0-3h), and the overlay target is the solved
network results/<stage>/networks/<stem>.nc (no per-network validation page; plot_world.py draws all countries at once).
Myopic overlays (foresight: myopic, e.g. overlay.myopic.yaml): the target is the solved network of the last planning
horizon, results/<stage>/networks/<stem>_<year>.nc; Snakemake solves the earlier horizons on the way. With a fourth
argument the target is that horizon's solved network instead (run.sh pathway stages advance all regions one horizon
at a time).
Learning (catalyst.learning: true in the overlay, e.g. overlay.myopic.yaml): catalyst.learning_market =
results/learning/<scen>/market_{year}.csv, the learning market of all <R>-<scen> stages (scripts/clear_market.py);
assumptions.smk makes it an input of the palette costs of every year after costs.year.
The first element of every scenario list is used for the target (run.sh runs one scenario per stage).
"""
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "technology-assumptions", "scripts"))
import palette  # noqa: E402

SMK = "../../config-pypsa-earth/validation.smk"  # relative to the fork root, see custom_rules in the overlays
ASSUMPTIONS = "../../config-pypsa-earth/technology-assumptions"
ASSUMPTIONS_SMK = ASSUMPTIONS + "/assumptions.smk"
ASSUMPTIONS_PDF = ASSUMPTIONS + "/build/technology_assumptions.pdf"
MARKET = "results/learning/{scen}/market_{{year}}.csv"  # relative to the fork root; one market per overlay


def deep_merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load(name):
    with open(os.path.join(HERE, name)) as f:
        return yaml.safe_load(f) or {}


def stage_config(kind, stage):
    """Merged config dict of one stage."""
    if kind == "overlay":
        base_run, scen = stage.rsplit("-", 1)
        cfg = deep_merge(load(f"config.{base_run}.yaml"), load(f"overlay.{scen}.yaml"))
        cfg.setdefault("run", {})["name"] = stage
        cat = cfg.setdefault("catalyst", {})
        cat.update(base_run=base_run, scenario=scen)
        if cat.get("extra_opts"):
            cfg["scenario"]["opts"] = [f"{cat['extra_opts']}-{o}" for o in cfg["scenario"]["opts"]]
        cfg.setdefault("costs", {})["output_currency"] = "USD"  # the study's currency (technology_assumptions.csv, price tables)
        if cat.get("palette"):
            apply_palette(cfg, stage)
        if cat.get("learning"):
            if not cat.get("palette") or cfg.get("foresight") != "myopic":
                raise ValueError(f"{stage}: catalyst.learning needs catalyst.palette and foresight: myopic")
            cat["learning_market"] = MARKET.format(scen=scen)
    elif kind == "assumptions":
        cfg = {"run": {"name": "assumptions"}, "custom_rules": [SMK]}
    else:
        cfg = load(f"config.{stage}.yaml")
        if kind == "dashboard":
            cfg["custom_rules"] = sorted(set(cfg.get("custom_rules", []) or []) | {SMK})
    cfg["custom_rules"] = sorted(set(cfg.get("custom_rules", []) or []) | {ASSUMPTIONS_SMK})
    return cfg


def apply_palette(cfg, stage):
    """technology_assumptions.csv -> extendable carriers, availability, fuel map, colours, cost overrides (palette.py)."""
    rows = palette.read()
    deep_merge(cfg, palette.model_config(rows, cfg["countries"], stage))
    tranches = palette.tranche_carriers(rows, cfg["countries"])
    curves = cfg.get("supply_curves") or {}
    for c in tranches:
        if c in curves:
            curves[c].setdefault("cutout", next(iter(cfg["atlite"]["cutouts"])))
        else:
            print(f"merge_config: {c} is a supply-curve technology of the palette but the overlay has no "
                  f"supply_curves.{c} block; it is not built in stage {stage}", file=sys.stderr)
    cfg["supply_curves"] = {c: v for c, v in curves.items() if c in tranches}


def network_stem(cfg):
    sc = cfg["scenario"]
    first = {k: str(sc[k][0]) for k in ("simpl", "clusters", "ll", "opts")}
    return "elec_s{simpl}_{clusters}_ec_l{ll}_{opts}".format(**first)


def solved_network(region, scen):
    """Path (relative to the fork root) of the solved screening network <region>-<scen>."""
    stage = f"{region}-{scen}"
    return f"results/{stage}/networks/{network_stem(stage_config('overlay', stage))}.nc"


def solved_horizon(stage, year):
    """Path (relative to the fork root) of the solved network of a myopic stage <R>-<scen> in one horizon."""
    return f"results/{stage}/networks/{network_stem(stage_config('overlay', stage))}_{year}.nc"


def target_of(kind, stage, cfg, horizon=None):
    if kind == "assumptions":
        return ASSUMPTIONS_PDF
    stem = network_stem(cfg)
    if kind == "prenetwork":
        return f"networks/{stage}/{stem}.nc"
    if kind == "overlay" and cfg.get("foresight") == "myopic":
        horizons = cfg["scenario"]["planning_horizons"]
        if horizon is not None and int(horizon) not in horizons:
            raise ValueError(f"{stage}: horizon {horizon} not in planning_horizons {horizons}")
        return f"results/{stage}/networks/{stem}_{horizon or horizons[-1]}.nc"
    if kind == "overlay" and cfg["catalyst"].get("single_node"):
        return f"results/{stage}/networks/{stem}.nc"
    if kind == "overlay":
        return f"results/{stage}/plots/validation_{stem}.png"
    return f"results/catalyst/validation_{stage}.png"


if __name__ == "__main__":
    if sys.argv[1] == "horizons":
        print(" ".join(str(y) for y in stage_config("overlay", sys.argv[2])["scenario"]["planning_horizons"]))
        sys.exit()
    kind, stage, out = sys.argv[1:4]
    horizon = sys.argv[4] if len(sys.argv) > 4 else None
    cfg = stage_config(kind, stage)
    with open(out, "w") as f:
        f.write(f"# generated by config-pypsa-earth/merge_config.py for stage '{stage}' ({kind}); do not edit\n")
        yaml.safe_dump(cfg, f, sort_keys=False)
    print(target_of(kind, stage, cfg, horizon))
