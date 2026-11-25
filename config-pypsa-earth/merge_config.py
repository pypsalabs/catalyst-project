# SPDX-License-Identifier: CC0-1.0
"""
Build models/pypsa-earth/config.yaml for one run.sh stage and print its Snakemake target.

    pixi run python ../../config-pypsa-earth/merge_config.py <kind> <stage> <out.yaml> [<planning horizon>]
    pixi run python ../../config-pypsa-earth/merge_config.py horizons <stage>     (myopic: prints the horizons)

kind = prenetwork : statistics.yaml < config.<stage>.yaml; target networks/<stage>/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}.nc
kind = overlay    : stage <R>-<scen> = statistics.yaml < config.<R>.yaml < overlay.<scen>.yaml (deep merge), run.name =
                    stage, catalyst.base_run = R; target results/<stage>/plots/validation_elec_s..._{opts}.png
kind = dashboard  : stage <R> = statistics.yaml < config.<R>.yaml + the validation custom rule; target
                    results/catalyst/validation_<R>.png
statistics.yaml carries the 2024 statistics (calibration at the source: plant list, demand, hydro, wind / solar,
efficiencies, fuel prices, operating envelope) as switches; the tables behind them are written per run by tables.smk
(resources/<run>/statistics/). catalyst.envelope: nofloor in an overlay makes tables.smk take the envelope tables of
calibration/<year>/envelope/nofloor/ (no must-run floors on emitting carriers); the attributes without a table there are
dropped here.
kind = assumptions: no network; the technology-assumptions custom rules only; target the assumptions PDF
                    ../../config-pypsa-earth/technology-assumptions/build/technology_assumptions.pdf
Every merged config carries technology-assumptions/assumptions.smk in custom_rules, so the assumptions
document and the rule that feeds technology_assumptions.csv into the cost table are part of every stage.
Palette stages (catalyst.palette: true in the overlay, e.g. overlay.myopic.yaml): technology_assumptions.csv
decides what the model may build (technology-assumptions/scripts/palette.py): its `model`, `carrier`, `regions`,
`availability`, `min_load`, `fuel` and `color` columns become electricity.extendable_carriers (all four lists),
extendable_carriers_buses: all, max_hours, the fork's `conventional:` block, costs.fuel_map, plotting, and
costs.overrides = true: resources/<stage>/statistics/cost_overrides_<year>.csv, written per year by assumptions.smk (palette_costs)
from the CSV. Supply-curve technologies (model tranches) take their dataset and binning from the overlay's
supply_curves.<carrier> block (cutout filled in from the base config); without such a block they are not built.
Every stage runs in USD (costs.output_currency), the currency of the CSV and of the calibration price tables.
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
Parts of a country (catalyst: tables: region: <KEY> in config.<R>.yaml, e.g. US West / US East, both countries: [US]):
tables.smk overlays calibration/<year>/regions/<KEY>/ on the national tables; stage_table() returns a table as such a
stage sees it, for the scripts that compare a stage with its statistics (README "US West / US East").
Overlay inheritance: `inherit: <scen>` in overlay.<x>.yaml merges overlay.<scen>.yaml first (recursively), so a
sensitivity overlay carries only what differs (overlay.cfe.yaml inherits myopic, overlay.cfesec.yaml inherits cfe).
Branches (catalyst.branch: {from: <scen>, year: <Y>}): stage <R>-<x> shares every horizon up to Y with <R>-<scen>
(catalyst.branch.parent_stage): solved_horizon() of those years is the parent's file, `horizons` lists only the later
years, and the fork's myopic chain starts the branch from the parent's solved network of Y (Snakefile,
solved_previous_horizon_elec); clear_market.py init seeds the branch's market from the parent's (README "Branches").
The first element of every scenario list is used for the target (run.sh runs one scenario per stage).
"""
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "technology-assumptions", "scripts"))
import palette  # noqa: E402

SMK = "../../config-pypsa-earth/validation.smk"  # relative to the fork root, see custom_rules in the overlays
TABLES_SMK = "../../config-pypsa-earth/tables.smk"  # writes resources/<run>/statistics/ for the fork's statistics options
ASSUMPTIONS = "../../config-pypsa-earth/technology-assumptions"
ASSUMPTIONS_SMK = ASSUMPTIONS + "/assumptions.smk"
ASSUMPTIONS_PDF = ASSUMPTIONS + "/build/technology_assumptions.pdf"
STATISTICS = "statistics.yaml"  # calibration at the source: the 2024 statistics, under every stage config
PE = os.environ.get("CATALYST_PE") or os.path.join(HERE, "..", "models", "pypsa-earth")  # the fork root (config paths are relative to it)
# CATALYST_BASELINE=1 (baseline/run_overnight.sh): PyPSA-Earth v0.9.0 as it comes, for the before/after comparison:
# no statistics.yaml, the overlays are baseline/overlay.<scen>.yaml (the out-of-the-box definitions of 2026-09-19),
# baseline/common.yaml is merged on top of everything (read-only data/ and cutouts/), and the technology-assumptions
# rules are left out (they need fork options)
BASELINE = os.environ.get("CATALYST_BASELINE") == "1"
OVERLAY = "baseline/overlay.{scen}.yaml" if BASELINE else "overlay.{scen}.yaml"
MARKET = "results/learning/{scen}/market_{{year}}.csv"  # relative to the fork root; one market per overlay


def deep_merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def stage_files():
    """{stage: path of its config.<stage>.yaml} of every stage (smoke stages included). In baseline mode the configs of
    baseline/ come first and the stages that model a part of a country (catalyst: tables: region) are left out: v0.9.0
    models the US as one region (baseline/config.US.yaml), the fork as US West and US East."""
    import glob

    out = {os.path.basename(f)[len("config."):-len(".yaml")]: f for f in sorted(glob.glob(os.path.join(HERE, "config.*.yaml")))}
    if BASELINE:
        for stage, f in list(out.items()):
            with open(f) as fh:
                if (((yaml.safe_load(fh) or {}).get("catalyst") or {}).get("tables") or {}).get("region"):
                    del out[stage]
        for f in sorted(glob.glob(os.path.join(HERE, "baseline", "config.*.yaml"))):
            out[os.path.basename(f)[len("config."):-len(".yaml")]] = f
    return out


def load(name):
    if name == STATISTICS and BASELINE:
        return {}
    path = os.path.join(HERE, name)
    if BASELINE and name.startswith("config.") and os.path.exists(os.path.join(HERE, "baseline", name)):
        path = os.path.join(HERE, "baseline", name)
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_overlay(scen, seen=()):
    """overlay.<scen>.yaml, with `inherit: <parent>` resolved (the parent merged first, recursively)."""
    if scen in seen:
        raise ValueError(f"overlay inheritance loop: {' -> '.join(seen + (scen,))}")
    cfg = load(OVERLAY.format(scen=scen))
    parent = cfg.pop("inherit", None)
    return deep_merge(load_overlay(parent, seen + (scen,)), cfg) if parent else cfg


def stage_table(cfg, name, year=None):
    """calibration/<year>/<name>.csv as a stage sees it (cfg = its config, or a config.<R>.yaml alone): for a stage that
    models a part of a country (catalyst: tables: region, e.g. US West) the rows of
    calibration/<year>/regions/<region>/<name>.csv replace the rows of the same countries, as tables.smk does for the run."""
    import pandas as pd

    tables = (cfg.get("catalyst") or {}).get("tables") or {}
    year = year or tables.get("year", 2024)
    table = pd.read_csv(os.path.join(HERE, "calibration", str(year), f"{name}.csv"), comment="#")
    regional = os.path.join(HERE, "calibration", str(year), "regions", str(tables.get("region")), f"{name}.csv")
    if tables.get("region") and os.path.exists(regional):
        part = pd.read_csv(regional)
        table = pd.concat([table[~table.country.isin(part.country)], part], ignore_index=True)
    return table


def envelope_variant(cfg, variant):
    """Drop the `conventional: <carrier>: existing:` attributes that have no table in calibration/<year>/envelope/
    <variant>/ (the floors of emitting carriers in nofloor); tables.smk takes the tables of the variant
    (catalyst: envelope)."""
    year = ((cfg.get("catalyst") or {}).get("tables") or {}).get("year", 2024)
    for carrier, attrs in (cfg.get("conventional") or {}).items():
        existing = attrs.get("existing") or {}
        for attr, value in list(existing.items()):
            table = os.path.join(HERE, "calibration", str(year), "envelope", variant, f"{carrier}_{attr}.csv")
            if value == "statistics" and not os.path.exists(table):
                del existing[attr]


def stage_config(kind, stage):
    """Merged config dict of one stage: statistics.yaml < config.<R>.yaml (< overlay.<scen>.yaml)."""
    if kind == "overlay":
        base_run, scen = stage.rsplit("-", 1)
        cfg = deep_merge(deep_merge(load(STATISTICS), load(f"config.{base_run}.yaml")), load_overlay(scen))
        cfg.setdefault("run", {})["name"] = stage
        cat = cfg.setdefault("catalyst", {})
        cat.update(base_run=base_run, scenario=scen)
        if cat.get("branch"):
            br = cat["branch"]
            br["year"] = int(br["year"])
            br["parent_stage"] = f"{base_run}-{br['from']}"
            if br["year"] not in cfg["scenario"]["planning_horizons"][:-1]:
                raise ValueError(f"{stage}: branch year {br['year']} must be a planning horizon before the last")
        if cat.get("extra_opts"):
            cfg["scenario"]["opts"] = [f"{cat['extra_opts']}-{o}" for o in cfg["scenario"]["opts"]]
        cfg.setdefault("costs", {})["output_currency"] = "USD"  # the study's currency (technology_assumptions.csv, price tables)
        if cat.get("envelope", "floor") != "floor":
            envelope_variant(cfg, cat["envelope"])
        if cat.get("palette"):
            apply_palette(cfg, stage)
        check_market_zones(cfg, stage)
        check_cfe_shares(cfg, stage)
        if cat.get("learning"):
            if not cat.get("palette") or cfg.get("foresight") != "myopic":
                raise ValueError(f"{stage}: catalyst.learning needs catalyst.palette and foresight: myopic")
            cat["learning_market"] = MARKET.format(scen=scen)
    elif kind == "assumptions":
        cfg = {"run": {"name": "assumptions"}, "custom_rules": [SMK]}
    else:
        cfg = deep_merge(load(STATISTICS), load(f"config.{stage}.yaml"))
        cfg.setdefault("costs", {})["output_currency"] = "USD"  # the price tables of statistics.yaml are in USD
        if kind == "dashboard":
            cfg["custom_rules"] = sorted(set(cfg.get("custom_rules", []) or []) | {SMK})
    if BASELINE:
        deep_merge(cfg, load("baseline/common.yaml"))
    else:
        cfg["custom_rules"] = sorted(set(cfg.get("custom_rules", []) or []) | {ASSUMPTIONS_SMK, TABLES_SMK})
        if kind != "assumptions" and (cfg.get("catalyst") or {}).get("cluster_by_zone"):
            cluster_by_zone(cfg, stage)
        if kind != "assumptions":
            grid_expansion(cfg, stage.rsplit("-", 1)[0] if kind == "overlay" else stage)
    return cfg


def grid_expansion(cfg, region):
    """catalyst: grid_expansion: delivered | plan -> the fork's `lines: expansion_limit` with the region's rate of
    data/grid_expansion/grid_expansion.csv (column rate_<name>): the transmission volume of a planning horizon, or of
    the `year` an overlay names for a single-step run, is at most (1 + rate)^(year - 2024) x the existing grid.
    `none`, no key, or a region without a row (one-node countries, rest of world, test regions): no limit."""
    import csv

    name = (cfg.get("catalyst") or {}).get("grid_expansion")
    if not name or name == "none":
        return
    with open(os.path.join(HERE, "data", "grid_expansion", "grid_expansion.csv")) as f:
        rows = {r["region"]: r for r in csv.DictReader(line for line in f if not line.startswith("#"))}
    if region not in rows:
        return
    if f"rate_{name}" not in rows[region]:
        raise ValueError(f"catalyst: grid_expansion: {name}: no column rate_{name} in data/grid_expansion/grid_expansion.csv")
    lines = cfg.setdefault("lines", {})
    limit = lines.get("expansion_limit") or {}
    lines["expansion_limit"] = {**limit, "rate": float(rows[region][f"rate_{name}"]), "reference_year": 2024}


def cluster_by_zone(cfg, stage):
    """catalyst: cluster_by_zone: true -> PyPSA-Earth's `subregion` block, so that cluster_network forms the clusters
    inside each market zone (no cluster straddles a zone border; README "Market zones"). The zones are the rows of
    data/market_zones/ keyed by GADM unit, for the countries (and, with build_shape_options: gadm_subset, the units)
    of the stage. Applied to cluster_network only: simplify_network would keep every zone border bus, and for
    build_bus_regions PyPSA-Earth hands over the country's sea areas instead of the subregions' (the offshore regions
    of every subregion would be lost; same in upstream main, 2026-11-18)."""
    cat = cfg["catalyst"]
    name = (cat.get("tables") or {}).get("zones", "market_zones")
    path = os.path.join(HERE, "data", "market_zones", f"{name}.csv")
    subset = set((cfg.get("build_shape_options") or {}).get("gadm_subset") or [])
    zones, by_country = {}, set()
    with open(path) as f:
        for line in f:
            if not line.strip() or line.startswith(("#", "key,")):
                continue
            key, zone = line.split(",")[:2]
            if key in cfg["countries"]:
                by_country.add(key)
            if "." in key and key.split(".")[0] in cfg["countries"] and (not subset or key in subset):
                zones.setdefault(zone, []).append(key)
    if by_country:
        raise ValueError(f"{stage}: catalyst: cluster_by_zone takes zones made of GADM units; {sorted(by_country)} have "
                         f"zones by country in {path} (REFACTOR_LATER.md item F)")
    if len(zones) < 2:
        raise ValueError(f"{stage}: catalyst: cluster_by_zone, but {path} has {len(zones)} zones for {cfg['countries']}")
    cfg["subregion"] = {"method": "gadm", "apply_on": ["cluster_network"], "define_by_gadm": zones,
                        "path_custom_shapes": False, "path_custom_offshore": False, "tolerance": 100}


def check_market_zones(cfg, stage):
    """Warn when a stage with 24/7 CFE buyers models countries that have market zones (data/market_zones/) but does
    not read them (catalyst: cfe: zones: statistics in config.<R>.yaml): its buyers would be matched per country."""
    cfe = (cfg.get("catalyst") or {}).get("cfe") or {}
    if not cfe.get("share") or cfe.get("matching", "zone") != "zone" or cfe.get("zones", "country") == "statistics":
        return
    path = os.path.join(HERE, "data", "market_zones", "market_zones.csv")
    if not os.path.exists(path) or len(cfg.get("countries", [])) > 20:
        return
    with open(path) as f:
        keys = {line.split(",")[0].split(".")[0] for line in f if line.strip() and not line.startswith(("#", "key,"))}
    listed = sorted(set(cfg["countries"]) & keys)
    multi_node = any(str(c) not in ("1",) for c in cfg["scenario"]["clusters"]) and not cfg["catalyst"].get("single_node")
    if listed and multi_node:
        print(f"merge_config: {stage} has 24/7 CFE buyers and market zones are defined for {listed}, but the stage does "
              f"not read them (catalyst: cfe: zones: statistics); the buyers are matched per country", file=sys.stderr)


def check_cfe_shares(cfg, stage):
    """Stop when a stage with 24/7 CFE buyers reads their share from the table (catalyst: cfe: share: statistics) and a
    country of the stage has no row in it for one of the horizons with a buyer."""
    import pandas as pd

    cfe = (cfg.get("catalyst") or {}).get("cfe") or {}
    if str(cfe.get("share")) != "statistics":
        return
    horizons = cfg.get("scenario", {}).get("planning_horizons") or []
    for year in [h for h in horizons if int(h) >= int(cfe.get("start_year", 0))]:
        path = os.path.join(HERE, "calibration", str(year), "cfe_share.csv")
        have = set(pd.read_csv(path, keep_default_na=False).country) if os.path.exists(path) else set()
        missing = sorted(set(cfg.get("countries", [])) - have)
        if missing:
            sys.exit(f"merge_config: {stage}: calibration/{year}/cfe_share.csv has no share for {missing} "
                     f"(misc-quarter1/datacentre-demand: snakemake model_tables)")


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
    """Path (relative to the fork root) of the solved network of a myopic stage <R>-<scen> in one horizon; for a
    branch, the parent's file in the shared horizons (up to catalyst.branch.year)."""
    cfg = stage_config("overlay", stage)
    br = cfg["catalyst"].get("branch")
    if br and int(year) <= br["year"]:
        return solved_horizon(br["parent_stage"], year)
    return f"results/{stage}/networks/{network_stem(cfg)}_{year}.nc"


def horizons(stage):
    """Planning horizons a stage solves itself (a branch: only those after the branch year)."""
    cfg = stage_config("overlay", stage)
    br = cfg["catalyst"].get("branch")
    return [y for y in cfg["scenario"]["planning_horizons"] if not br or y > br["year"]]


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
        print(" ".join(str(y) for y in horizons(sys.argv[2])))
        sys.exit()
    if sys.argv[1] == "parent":   # the stage whose prepared inputs a stage starts from (run.sh copy_parent), or nothing:
        # the parent of a branch, else <R>-<catalyst.inputs_from>
        cat = stage_config("overlay", sys.argv[2])["catalyst"]
        src = (cat.get("branch") or {}).get("from") or cat.get("inputs_from")
        print(f"{cat['base_run']}-{src}" if src else "")
        sys.exit()
    kind, stage, out = sys.argv[1:4]
    horizon = sys.argv[4] if len(sys.argv) > 4 else None
    cfg = stage_config(kind, stage)
    # inside a Slurm job the solver gets the cores of the job (cluster/run.sbatch --cpus-per-task) instead of the
    # thread count the overlays set for the laptop; more threads than cores would only make them wait for each other
    cores = os.environ.get("SLURM_CPUS_PER_TASK")
    if cores:
        for options in ((cfg.get("solving") or {}).get("solver_options") or {}).values():
            if isinstance(options, dict) and "threads" in options:
                options["threads"] = int(cores)
    with open(out, "w") as f:
        f.write(f"# generated by config-pypsa-earth/merge_config.py for stage '{stage}' ({kind}); do not edit\n")
        yaml.safe_dump(cfg, f, sort_keys=False)
    print(target_of(kind, stage, cfg, horizon))
